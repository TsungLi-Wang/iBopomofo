#!/usr/bin/env python3
# 訓練節點層封閉集合打分器：P(候選 | 讀音, 節點當下看得到的東西)。
#
# ⚠️ 這不是 next-char LM，也不是路徑重排器。輸入是**一個 walk 節點**：
# 它的讀音、引擎給的候選（含 unigram 分數與 PMI）、walk 決定的左右詞與左右字、
# 右邊是不是空的。輸出是候選上的分數，softmax 只在這個節點的候選集合上做。
#
# 樣本由 `node_sample_extract`（真的跑 walk）產生 —— 不是拿金標句子切字窗湊的。
#
# 硬規則：
#   * 讀音含 ㄉㄜ˙ 的節點一律不進訓練（PTT 標籤髒，dead-ends D）
#   * 金標不在候選裡的節點丟掉（lattice-miss，不訓練模型去選不合法的字）
#   * 分層採樣：按「讀音 × 金標值」，不是按自然字頻，否則永遠選高頻同音
#   * 難例要加權，但**用 loss 權重，不是複製樣本**（棒⑭-B）：
#     棒⑬ 的 hard ×12 是物理複製，把「引擎多半是對的」這個先驗整個翻掉
#     （easy:hard 從 6.42:1 變 0.56:1，引擎正確率 88.8% → 35.8%），
#     模型因此學成「引擎通常不可信」。loss 權重能加重難例，又不動先驗。
#   * τ 只在 held-out 上定，不准看考卷或兩份真實驗證集

import argparse
import collections
import json
import math
import os
import random
import time

import hashlib

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

DE_READING = 'ㄉㄜ˙'
CTX_CHARS = 6      # 左右各看幾個 walk 字（當特徵，不是預測單位）
CAND_CHARS = 4     # 候選值取前幾個字
MAX_CANDS = 24     # 一個節點最多看幾個候選（按 unigram 分數取前 N）
PAD, UNK = 0, 1


class NodeExpert(nn.Module):
    """小分類器：上下文編一次，候選逐個打分，softmax 限制在候選集合上。

    刻意做小、做淺：它要在 walk 之後、打字當下跑，而且只在白名單讀音的節點上
    被呼叫。體積上限 1GB 是天花板不是目標 —— 只有證明「節點任務欠擬合」
    才准加大。
    """

    def __init__(self, n_char, n_syl, emb=128, syl_emb=64, hid=256,
                 repr_mode='base'):
        super().__init__()
        self.cfg = dict(n_char=n_char, n_syl=n_syl, emb=emb, syl_emb=syl_emb,
                        hid=hid, repr_mode=repr_mode)
        self.repr_mode = repr_mode
        self.char_emb = nn.Embedding(n_char, emb, padding_idx=0)
        self.syl_emb = nn.Embedding(n_syl, syl_emb, padding_idx=0)
        # ── 棒⑭-I：局部搭配表徵 ──
        # ⑭-H 量到判別力來自局部詞彙搭配（手作／大作／神作／合作），
        # 而串接式表徵表達不了「手＋作」這種組合。
        #   i1：把視窗內**相鄰字對**的交互（逐元素乘積）加進上下文分支
        #   i2：i1 ＋**候選條件化**的交互（左鄰⊗候選、候選⊗右鄰）——
        #       候選在推論時是已知的，沒有洩漏
        # 視窗仍固定 ±6，其他一律不動。
        ctx_in = emb * CTX_CHARS * 2 + syl_emb + 1
        if repr_mode in ('i1', 'i2'):
            ctx_in += emb * 2
        self.ctx = nn.Sequential(nn.Linear(ctx_in, hid), nn.GELU(),
                                 nn.Linear(hid, hid))
        # 候選：值的字元 + 三個引擎特徵（unigram、PMI 左、PMI 右）+ 是否 walk 選的
        cand_in = emb * CAND_CHARS + 4
        if repr_mode == 'i2':
            cand_in += emb * 2
        self.cand = nn.Sequential(nn.Linear(cand_in, hid), nn.GELU(),
                                  nn.Linear(hid, hid))
        self.head = nn.Sequential(nn.Linear(hid * 2, hid), nn.GELU(),
                                  nn.Linear(hid, 1))

    def forward(self, left, right, syl, right_empty, cand_chars, cand_feats,
                cand_mask):
        b = left.shape[0]
        le = self.char_emb(left)                      # [B, CTX, E]
        re = self.char_emb(right)
        l = le.reshape(b, -1)
        r = re.reshape(b, -1)
        s = self.syl_emb(syl).sum(1)
        parts = [l, r, s, right_empty[:, None]]
        if self.repr_mode in ('i1', 'i2'):
            parts.append((le[:, :-1] * le[:, 1:]).sum(1))
            parts.append((re[:, :-1] * re[:, 1:]).sum(1))
        h = self.ctx(torch.cat(parts, dim=-1))
        ce = self.char_emb(cand_chars)                # [B, C, CAND, E]
        c = ce.reshape(b, cand_chars.shape[1], -1)
        cparts = [c, cand_feats]
        if self.repr_mode == 'i2':
            first = ce[:, :, 0]                       # [B, C, E]
            cparts.append(first * le[:, -1][:, None, :])
            cparts.append(first * re[:, 0][:, None, :])
        c = self.cand(torch.cat(cparts, dim=-1))
        hx = h[:, None, :].expand(-1, c.shape[1], -1)
        logits = self.head(torch.cat([hx, c], dim=-1)).squeeze(-1)
        return logits.masked_fill(~cand_mask, -1e4)


def load_split_override(sentences_path, dev_frac, salt='tau2'):
    """從 sentences.jsonl 重建 sid → train/dev。

    為什麼要能重切：nodes.tsv 裡的 split 是抽取當下寫死的（dev 8%），
    而白名單那一組（作做坐座）在 dev 裡只剩幾百個節點 —— 掃 τ 時出手次數
    不到 30，分母比 dead-ends B 節的下限還小，定出來的門檻不可信。
    加大 dev 是**修量測**，不是調參數：τ 仍然只在 held-out 上定。

    切分一律以 doc_id 為單位，同一篇文件不會一半訓練一半驗證。
    """
    sid_split = {}
    with open(sentences_path, encoding='utf-8') as fh:
        for i, line in enumerate(fh, start=1):
            doc = json.loads(line)['doc_id']
            h = int(hashlib.sha256((salt + ':' + doc).encode()).hexdigest()[:8], 16)
            sid_split[i] = 'dev' if (h % 1000) < int(dev_frac * 1000) else 'train'
    return sid_split


def utf8_chars(s):
    return list(s)


def build_vocab(path, limit=0):
    chars = collections.Counter()
    syls = collections.Counter()
    with open(path, encoding='utf-8') as fh:
        next(fh)
        for i, line in enumerate(fh):
            if limit and i >= limit:
                break
            f = line.rstrip('\n').split('\t')
            if len(f) < 16:
                continue
            for s in f[6].split('-'):
                syls[s] += 1
            for field in (f[7], f[8], f[12], f[13]):
                chars.update(field)
            for c in f[15].split('|'):
                p = c.split(':')
                if p:
                    chars.update(p[0])
    itos = ['<pad>', '<unk>'] + sorted(chars)
    stos = ['<pad>', '<unk>'] + sorted(syls)
    return itos, stos


def load_rows(path, itos, stos, args, sid_split=None):
    """讀 TSV → 張量。同時回傳每筆的分層鍵與難例旗標。"""
    ci = {c: i for i, c in enumerate(itos)}
    si = {s: i for i, s in enumerate(stos)}
    rows = []
    stats = collections.Counter()
    with open(path, encoding='utf-8') as fh:
        next(fh)
        for line in fh:
            f = line.rstrip('\n').split('\t')
            if len(f) < 16:
                stats['bad_line'] += 1
                continue
            split, kind, reading = f[1], int(f[2]), f[6]
            if sid_split is not None:
                split = sid_split.get(int(f[0]), split)
            chosen, gold, gold_in = f[7], f[8], f[9] == '1'
            stats['total'] += 1
            if DE_READING in reading.split('-'):
                stats['drop_de'] += 1
                continue
            if not gold_in:
                stats['drop_lattice_miss'] += 1
                continue
            cands = []
            for c in f[15].split('|'):
                p = c.split(':')
                if len(p) != 5:
                    continue
                cands.append((p[0], float(p[1]), float(p[2]), float(p[3]),
                              p[4] == '1'))
            if len(cands) < 2:
                stats['drop_single_cand'] += 1
                continue
            cands.sort(key=lambda x: -x[1])
            cands = cands[:MAX_CANDS]
            gi = next((k for k, c in enumerate(cands) if c[0] == gold), -1)
            if gi < 0:
                # 金標被 MAX_CANDS 截掉了 —— 引擎其實有這個候選，但我們沒餵給
                # 模型。當成 lattice-miss 丟掉，不要製造一個「正解不在集合裡」
                # 的訓練樣本。
                stats['drop_gold_truncated'] += 1
                continue
            tgt_i = (reading.split('-').index('ㄗㄨㄛˋ')
                     if 'ㄗㄨㄛˋ' in reading.split('-') else -1)
            rows.append({
                'sid': int(f[0]), 'span': int(f[5]),
                'tgt_char': (chosen[tgt_i] if 0 <= tgt_i < len(chosen)
                             and len(chosen) == len(reading.split('-')) else ''),
                'split': split, 'kind': kind, 'reading': reading,
                'gold': gold, 'chosen': chosen, 'gi': gi, 'cands': cands,
                'left': f[12], 'right': f[13], 'right_empty': f[14] == '1',
                'hard': chosen != gold,
            })
            stats['kept'] += 1
            if chosen != gold:
                stats['kept_hard'] += 1
            if kind == 1:
                stats['kept_prefix'] += 1
    return rows, stats, ci, si


def encode(rows, ci, si):
    n = len(rows)
    left = np.zeros((n, CTX_CHARS), dtype=np.int32)
    right = np.zeros((n, CTX_CHARS), dtype=np.int32)
    syl = np.zeros((n, 4), dtype=np.int32)
    rempty = np.zeros(n, dtype=np.float32)
    cchars = np.zeros((n, MAX_CANDS, CAND_CHARS), dtype=np.int32)
    cfeat = np.zeros((n, MAX_CANDS, 4), dtype=np.float32)
    cmask = np.zeros((n, MAX_CANDS), dtype=bool)
    gold = np.zeros(n, dtype=np.int64)
    eng = np.zeros(n, dtype=np.int64)
    for i, r in enumerate(rows):
        lc = utf8_chars(r['left'])[-CTX_CHARS:]
        for j, c in enumerate(lc):
            left[i, CTX_CHARS - len(lc) + j] = ci.get(c, UNK)
        rc = utf8_chars(r['right'])[:CTX_CHARS]
        for j, c in enumerate(rc):
            right[i, j] = ci.get(c, UNK)
        for j, s in enumerate(r['reading'].split('-')[:4]):
            syl[i, j] = si.get(s, UNK)
        rempty[i] = 1.0 if r['right_empty'] else 0.0
        for k, (v, u, pl, pr, walk) in enumerate(r['cands']):
            vc = utf8_chars(v)[:CAND_CHARS]
            for j, c in enumerate(vc):
                cchars[i, k, j] = ci.get(c, UNK)
            # 引擎分數縮到 O(1)：unigram 大約 -3～-12，PMI 大約 -2～2
            cfeat[i, k] = (u / 10.0, pl, pr, 1.0 if walk else 0.0)
            cmask[i, k] = True
        gold[i] = r['gi']
        eng[i] = next((k for k, c in enumerate(r['cands'])
                       if c[0] == r['chosen']), r['gi'])
    return dict(left=left, right=right, syl=syl, rempty=rempty,
                cchars=cchars, cfeat=cfeat, cmask=cmask, gold=gold, eng=eng)


def batches(enc, idx, bs, device, weights=None, submask=None):
    for i in range(0, len(idx), bs):
        sel = idx[i:i + bs]
        extra = ((torch.from_numpy(weights[sel]).to(device),)
                 if weights is not None else ())
        if submask is not None:
            extra = extra + (torch.from_numpy(submask[sel]).to(device),)
        yield (torch.from_numpy(enc['left'][sel].astype(np.int64)).to(device),
               torch.from_numpy(enc['right'][sel].astype(np.int64)).to(device),
               torch.from_numpy(enc['syl'][sel].astype(np.int64)).to(device),
               torch.from_numpy(enc['rempty'][sel]).to(device),
               torch.from_numpy(enc['cchars'][sel].astype(np.int64)).to(device),
               torch.from_numpy(enc['cfeat'][sel]).to(device),
               torch.from_numpy(enc['cmask'][sel]).to(device),
               torch.from_numpy(enc['gold'][sel]).to(device),
               torch.from_numpy(enc['eng'][sel]).to(device)) + extra


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--epochs', type=int, default=6)
    ap.add_argument('--batch', type=int, default=512)
    ap.add_argument('--lr', type=float, default=2e-3)
    ap.add_argument('--hard-weight', type=float, default=1.0,
                    help='難例的 **loss 權重**（不是複製倍數）。1.0＝不加權')
    ap.add_argument('--single-weight', type=float, default=1.0,
                    help='單字節點的 loss 權重（多字詞維持 1.0）')
    ap.add_argument('--dir-bounded', action='store_true',
                    help='目標組內逐方向的有界權重 clip(sqrt(median/n),0.5,3)')
    ap.add_argument('--dir-clip', type=float, nargs=2, default=(0.5, 3.0))
    ap.add_argument('--exclude-docs', default='',
                    help='要整份排除的 doc_id 清單（audited dev 的文件，防洩漏）')
    ap.add_argument('--min-sentence-len', type=int, default=0,
                    help='句長下限；0＝不過濾')
    ap.add_argument('--margin-easy-lambda', type=float, default=0.0,
                    help='B：引擎已選對時，要求 score(engine) 領先次高至少 m 的 hinge 權重')
    ap.add_argument('--margin-easy-m', type=float, default=1.0)
    ap.add_argument('--margin-hard-lambda', type=float, default=0.0,
                    help='A：引擎選錯時，要求 score(gold) 領先 score(engine) 至少 m')
    ap.add_argument('--margin-hard-m', type=float, default=1.0)
    ap.add_argument('--repr-mode', default='base', choices=['base', 'i1', 'i2'],
                    help='棒⑭-I：局部搭配表徵。base=現況；i1=加相鄰字對交互；'
                         'i2=i1＋候選條件化交互。視窗仍固定 ±6')
    ap.add_argument('--subgroup-lambda', type=float, default=0.0,
                    help='棒⑭-G：**只**對「引擎已選對、單字節點、目標字＝指定字」'
                         '這個子群加 margin penalty。不是 global hinge——'
                         '棒⑭-D 已證明 global 版會把 作→做 的 rescue 一起壓掉')
    ap.add_argument('--subgroup-m', type=float, default=1.0)
    ap.add_argument('--subgroup-char', default='作')
    ap.add_argument('--folds', default='',
                    help='folds.json（doc_id→fold）。給了就用 fold 切 train/dev，'
                         '取代 --dev-frac 的固定切法')
    ap.add_argument('--fold', type=int, default=-1, help='這一輪拿哪個 fold 當 dev')
    ap.add_argument('--recipe', default='',
                    help='只是寫進 meta 的標籤，方便對照 R0/R1/R2/R3')
    ap.add_argument('--per-stratum', type=int, default=400,
                    help='每個（讀音×金標值）最多留幾筆；分層採樣，不是自然字頻')
    ap.add_argument('--sentences', default='',
                    help='給了就用它重切 train/dev（修量測用，見 load_split_override）')
    ap.add_argument('--dev-frac', type=float, default=0.20)
    ap.add_argument('--fire-readings', default='ㄗㄨㄛˋ',
                    help='挑 checkpoint 時看的那一組（＝引擎端的開火白名單）')
    ap.add_argument('--device', default='mps')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    device = torch.device(args.device if (args.device != 'mps' or
                                          torch.backends.mps.is_available())
                          else 'cpu')
    itos, stos = build_vocab(args.nodes)
    if args.folds:
        # ── document-level k-fold（棒⑭-F）──
        # 固定切法會把稀有方向一次吃光（做→坐 可訓練 0）；改成 fold 之後
        # 每個節點在 k−1 個 fold 裡是訓練、在 1 個 fold 裡是 dev，
        # 同一份文件永遠不跨邊。這是本棒**唯一**改動的東西。
        fj = json.load(open(args.folds, encoding='utf-8'))
        assign = fj['assign']
        sid_split = {}
        with open(args.sentences, encoding='utf-8') as fh:
            for i, line in enumerate(fh, start=1):
                d = json.loads(line)['doc_id']
                sid_split[i] = ('dev' if assign.get(d, -1) == args.fold
                                else 'train')
        print(f'fold {args.fold}/{fj["k"]}（seed={fj["seed"]}）'
              f'：dev 文件 {sum(1 for v in assign.values() if v == args.fold):,}')
    else:
        sid_split = (load_split_override(args.sentences, args.dev_frac)
                     if args.sentences else None)
    rows, stats, ci, si = load_rows(args.nodes, itos, stos, args, sid_split)
    print(json.dumps(dict(stats), ensure_ascii=False, indent=2))

    # ── 分層採樣：按（讀音 × 金標值）截頂 ──
    rng = random.Random(20260814)
    by_stratum = collections.defaultdict(list)
    for i, r in enumerate(rows):
        by_stratum[(r['reading'], r['gold'])].append(i)
    keep = []
    for k, v in by_stratum.items():
        if len(v) > args.per_stratum:
            v = rng.sample(v, args.per_stratum)
        keep.extend(v)
    keep.sort()
    rows = [rows[i] for i in keep]
    print(f'分層採樣後 {len(rows):,} 筆（{len(by_stratum):,} 個層）')

    # ── 防洩漏：audited dev 的文件整份排除 ──
    # 不做這一條，dev 就是「模型看過的文件」，後面所有 dev 數字都不算數。
    if args.exclude_docs:
        bad = {ln.strip() for ln in open(args.exclude_docs, encoding='utf-8')
               if ln.strip()}
        sid2doc = {}
        with open(args.sentences, encoding='utf-8') as fh:
            for i, line in enumerate(fh, start=1):
                sid2doc[i] = json.loads(line)['doc_id']
        before = len(rows)
        rows = [r for r in rows if sid2doc.get(r['sid']) not in bad]
        print(f'排除 audited 文件 {len(bad)} 份：{before:,} → {len(rows):,} 筆')

    # ── 句長下限（context filtering）──
    if args.min_sentence_len > 0:
        sid_len = {}
        with open(args.sentences, encoding='utf-8') as fh:
            for i, line in enumerate(fh, start=1):
                sid_len[i] = len(json.loads(line)['text'])
        before = len(rows)
        rows = [r for r in rows
                if sid_len.get(r['sid'], 0) >= args.min_sentence_len]
        print(f'句長 ≥{args.min_sentence_len}：{before:,} → {len(rows):,} 筆')

    enc = encode(rows, ci, si)
    is_dev = np.array([r['split'] == 'dev' for r in rows])
    is_hard = np.array([r['hard'] for r in rows])
    tr_idx = np.where(~is_dev)[0]
    dv_idx = np.where(is_dev)[0]

    # ── 每筆一個 loss 權重（**不複製樣本**）──
    # 棒⑬ 用物理複製，先驗被翻掉；這裡改成權重，資料的 easy/hard 比例維持真實。
    w = np.ones(len(rows), dtype=np.float32)
    if args.hard_weight != 1.0:
        w[is_hard] *= args.hard_weight
    if args.single_weight != 1.0:
        single = np.array([r['span'] == 1 for r in rows])
        w[single] *= args.single_weight
    if args.dir_bounded:
        # 只在目標組內做，而且有界：稀有方向給有限加成，不是無中生有。
        fire = set(args.fire_readings.split(','))

        def dir_key(r):
            syls = r['reading'].split('-')
            hit = [x for x in syls if x in fire]
            if not hit or not r['hard']:
                return None
            i = syls.index(hit[0])
            if len(r['chosen']) != len(syls) or len(r['gold']) != len(syls):
                return None
            # 節點層 hard 不等於目標字錯：多字詞可能是別的位置錯了
            # （chosen「坐在」vs gold「坐再」），那種不該進方向權重。
            if r['chosen'][i] == r['gold'][i]:
                return None
            return (r['chosen'][i], r['gold'][i])

        keys = [dir_key(r) for r in rows]
        cnt = collections.Counter(k for k, d in zip(keys, is_dev)
                                  if k is not None and not d)
        if cnt:
            med = sorted(cnt.values())[len(cnt) // 2]
            lo, hi = args.dir_clip
            for i, k in enumerate(keys):
                if k is not None:
                    w[i] *= float(np.clip((med / cnt[k]) ** 0.5, lo, hi))
            print('逐方向有界權重（中位數 %d）：' % med
                  + '、'.join(f'{a}→{b} ×{float(np.clip((med / n) ** 0.5, *args.dir_clip)):.2f}'
                              for (a, b), n in sorted(cnt.items(), key=lambda x: -x[1])))

    # ── 棒⑭-G：子群遮罩（只有這個子群會吃到 margin penalty）──
    sub_mask = np.array([
        bool(args.subgroup_lambda > 0 and (not r['hard']) and r['span'] == 1
             and r['tgt_char'] == args.subgroup_char)
        for r in rows])
    if args.subgroup_lambda > 0:
        print(f'子群（引擎選對·單字·目標字={args.subgroup_char}）：'
              f'train {int(sub_mask[np.where(~is_dev)[0]].sum()):,} 筆'
              f'（占 train {100 * sub_mask[np.where(~is_dev)[0]].mean():.2f}%）')

    pool = tr_idx
    eff_hard = w[tr_idx][is_hard[tr_idx]].sum()
    eff_all = w[tr_idx].sum()
    print(f'train {len(tr_idx):,}（難例 {int(is_hard[tr_idx].sum()):,}）'
          f' dev {len(dv_idx):,}')
    print(f'  hard 佔 loss：{100 * eff_hard / eff_all:.1f}%'
          f'（筆數佔比 {100 * is_hard[tr_idx].mean():.1f}%）')
    single_tr = np.array([r['span'] == 1 for r in rows])[tr_idx]
    print(f'  單字節點佔 loss：'
          f'{100 * w[tr_idx][single_tr].sum() / eff_all:.1f}%'
          f'（筆數佔比 {100 * single_tr.mean():.1f}%）')

    model = NodeExpert(len(itos), len(stos), repr_mode=args.repr_mode).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f'參數 {n_params:,}  fp32 {n_params * 4 / 1e6:.1f}MB  device={device}')

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    steps = args.epochs * math.ceil(len(pool) / args.batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr,
                                                total_steps=steps, pct_start=0.1)
    # 挑 checkpoint 用「這顆模型的職位」：在開火組的 dev 節點上，
    # argmax 相對引擎的淨救回（救 − 壞）。整體 dev_acc 挑出來的是
    # 「最會複製引擎」的那一顆（棒⑬ 就是這樣：dev_acc 一路升、
    # 難例正確率一路降）。
    fire_set = set(args.fire_readings.split(','))
    in_fire = np.array([bool(fire_set & set(r['reading'].split('-')))
                        for r in rows])
    grp_dev = dv_idx[in_fire[dv_idx]]
    print(f'  開火組 dev 節點 {len(grp_dev):,}'
          f'（引擎選錯 {int(is_hard[grp_dev].sum()):,}）')

    meta = dict(vars(args), n_params=n_params, stats=dict(stats), history=[])
    best = -1e9
    nprng = np.random.default_rng(20260814)
    for ep in range(args.epochs):
        model.train()
        order = nprng.permutation(pool)
        tot = seen = 0
        t0 = time.time()
        for *x, g, eg, sw, sm in batches(enc, order, args.batch, device, w,
                                         sub_mask):
            logits = model(*x)
            # 逐樣本加權：加重難例，但**不動資料的 easy/hard 先驗**
            loss = (F.cross_entropy(logits, g, reduction='none') * sw).sum() \
                / sw.sum()
            # ── margin hinge：把訓練目標對準「部署時真正用的量」──
            # 部署規則是 score(best) − score(engine) > τ，但 cross-entropy
            # 只要求 argmax 對，對這個差值沒有任何壓力。所以引擎選對時，
            # 只要有一點擾動就會把差值推過 τ 而誤觸發（作→作·單字 18/18 全改壞）。
            # 這裡明確地訓練那個差值，不動架構、不動特徵、不動 τ。
            if args.subgroup_lambda > 0 and sm.any():
                # 只在這個子群上要求「引擎的選擇要領先次高至少 m」。
                # 其他所有樣本（含 作→做／作→座／做→X 的 hard 例）完全不受影響，
                # 所以它們的 rescue signal 不會像 global hinge 那樣被壓掉。
                masked = logits.clone()
                masked.scatter_(1, eg[:, None], -1e4)
                runner = masked.max(dim=1).values
                s_eng2 = logits.gather(1, eg[:, None]).squeeze(1)
                hinge = F.relu(args.subgroup_m - (s_eng2 - runner))
                loss = loss + args.subgroup_lambda * (
                    hinge * sm.float() * sw).sum() / sw.sum()
            if args.margin_easy_lambda > 0 or args.margin_hard_lambda > 0:
                s_gold = logits.gather(1, g[:, None]).squeeze(1)
                s_eng = logits.gather(1, eg[:, None]).squeeze(1)
                easy = (g == eg)
                if args.margin_easy_lambda > 0 and easy.any():
                    # 引擎選對：要求它領先「最好的其他候選」至少 m
                    masked = logits.clone()
                    masked.scatter_(1, eg[:, None], -1e4)
                    runner = masked.max(dim=1).values
                    hinge = F.relu(args.margin_easy_m - (s_eng - runner))
                    loss = loss + args.margin_easy_lambda * (
                        hinge * easy.float() * sw).sum() / sw.sum()
                if args.margin_hard_lambda > 0 and (~easy).any():
                    # 引擎選錯：要求金標領先引擎的選擇至少 m
                    hinge = F.relu(args.margin_hard_m - (s_gold - s_eng))
                    loss = loss + args.margin_hard_lambda * (
                        hinge * (~easy).float() * sw).sum() / sw.sum()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            tot += loss.item() * len(g)
            seen += len(g)
        # dev：整體、難例（引擎選錯）、以及引擎自己的準確率當基線
        model.eval()
        agg = collections.Counter()
        with torch.no_grad():
            for i in range(0, len(dv_idx), 2048):
                sel = dv_idx[i:i + 2048]
                *x, g, _eg = next(batches(enc, sel, len(sel), device))
                pred = model(*x).argmax(1).cpu().numpy()
                gold = g.cpu().numpy()
                hard = is_hard[sel]
                agg['n'] += len(sel)
                agg['ok'] += int((pred == gold).sum())
                agg['hard_n'] += int(hard.sum())
                agg['hard_ok'] += int((pred == gold)[hard].sum())
                agg['engine_ok'] += int((~hard).sum())
        # 開火組上的淨救回（argmax，未套 τ）
        saved = broke = 0
        with torch.no_grad():
            for i in range(0, len(grp_dev), 2048):
                sel = grp_dev[i:i + 2048]
                if not len(sel):
                    break
                *x, g, _eg = next(batches(enc, sel, len(sel), device))
                pred = model(*x).argmax(1).cpu().numpy()
                gold = g.cpu().numpy()
                hard = is_hard[sel]
                saved += int(((pred == gold) & hard).sum())
                broke += int(((pred != gold) & ~hard).sum())
        line = {'epoch': ep + 1, 'loss': tot / seen,
                'dev_acc': round(agg['ok'] / max(agg['n'], 1), 4),
                'dev_hard_acc': round(agg['hard_ok'] / max(agg['hard_n'], 1), 4),
                'engine_acc': round(agg['engine_ok'] / max(agg['n'], 1), 4),
                'grp_saved': saved, 'grp_broke': broke,
                'grp_net': saved - broke,
                'sec': round(time.time() - t0)}
        meta['history'].append(line)
        print(json.dumps(line, ensure_ascii=False))
        if line['grp_net'] > best:
            best = line['grp_net']
            torch.save({'model': model.state_dict(), 'cfg': model.cfg,
                        'itos': itos, 'stos': stos},
                       os.path.join(args.out, 'node-expert.pt'))
            meta['best_epoch'] = ep + 1
            meta['best_grp_net'] = best
            meta['best_dev_acc'] = line['dev_acc']
    with open(os.path.join(args.out, 'train-meta.json'), 'w',
              encoding='utf-8') as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    print(f'best 開火組淨救回 {best:+.0f} @ epoch {meta.get("best_epoch")}')


if __name__ == '__main__':
    main()
