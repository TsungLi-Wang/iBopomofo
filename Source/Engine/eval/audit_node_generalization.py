#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棒⑭-N：Node-level 訊號能不能跨「沒見過的 engine→gold 方向」泛化。

**這是 diagnostic / offline-only。**
* 不接 production，不使用任何 production model checkpoint（R4／I2 都不載入）。
* 訓練的是固定容量的 L2 logistic regression，只為回答「排序訊號在不在」。
* **diagnostic AUC 不是 system net。** 本檔任何輸出都不得被引用為系統效果。

## 研究問題

某個方向（engine=A、gold=B）在訓練時**完全沒出現**時，模型還能不能
用局部脈絡、候選身分、引擎側數值來判斷「該不該推翻引擎的選擇」？

## 母體

⑭-M 的全語料 node dump（`bin/full_corpus_error_map`）中：
* `kind=0`（完整句，不用前綴樣本 —— 前綴與完整句同源，是 leakage 來源）
* `span=1`（單字節點 —— 節點專家真正會出手的地方）
* `n_cands>=2`（有得選才有決策可言）

label：1 = 引擎選錯（chosen≠gold），0 = 引擎選對。
span=1 時金標必然在候選裡（⑭-M §3 的結構性事實），所以正例全都是 candidate-reachable。

## 切分（兩層同時成立）

1. **direction-held-out**：方向鍵 = `f"{chosen}→{gold}"`（選對的節點是對角線 `A→A`）。
   fold = `sha256(seed:direction) % 5`，deterministic，不手動調整。
   held-out fold 的方向，**一個訓練節點都不會出現**。
2. **document-held-out**：訓練集再剔除所有出現在該 fold 測試集裡的文件。
   本語料一句一個 doc_id，所以 doc = sentence。

兩者交集 = 最嚴格的泛化測試。

## 特徵族（全部只用推論時可得的資訊）

* `ENG` 引擎側**字元無關**數值：候選分數、分數差、PMI、名次結構、n_cands、
  句長、位置、右邊是否為空。**這是唯一有可能跨未見字泛化的一族。**
* `CTX` walk 輸出的左右 ±6 字（字元身分，位置分左右）
* `CAND` 候選集合的字元身分
* `CCI` 候選條件化字對：(左1, 候選)、(候選, 右1)

⚠️ 字元身分特徵在**未見方向**上必然權重為 0 —— 這正是要量的東西，不是 bug。

用法：
  python3 audit_node_generalization.py --nodes <all-nodes.tsv> \\
      --items <自然驗證集.jsonl> --out <報告片段.md>
"""

import argparse
import collections
import hashlib
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_representation import boot_ci, fit_lr, pr_auc, roc_auc  # noqa: E402

SEED = 'baton14n-direction-v1'
K = 5
WIN = 6
MIN_DIR_N = 10          # 低於這個數的 held-out 方向標 INSUFFICIENT POWER
MIN_COUNT = 3           # 字表出現次數門檻

# ⑭-M §6 認定的正字法／風格變體（人工清單，非量測類別）
VARIANTS = {('他', '她'), ('她', '他'), ('你', '妳'), ('妳', '你'),
            ('什', '甚'), ('甚', '什'), ('啊', '阿'), ('阿', '啊'),
            ('那', '哪'), ('哪', '那')}


def dfold(direction):
    h = hashlib.sha256(f'{SEED}:{direction}'.encode('utf-8')).hexdigest()
    return int(h[:8], 16) % K


def load(nodes_path, items_path):
    meta = {}
    with open(items_path, encoding='utf-8') as fh:
        for i, line in enumerate(fh, start=1):
            if line.strip():
                meta[str(i)] = json.loads(line)
    rows = []
    with open(nodes_path, encoding='utf-8') as fh:
        head = next(fh).rstrip('\n').split('\t')
        for line in fh:
            c = dict(zip(head, line.rstrip('\n').split('\t')))
            if c['kind'] != '0' or c['span'] != '1':
                continue
            n_cands = int(c['n_cands'])
            if n_cands < 2:
                continue
            cands = []
            for part in c['cands'].split('|'):
                q = part.split(':')
                if len(q) == 5:
                    cands.append((q[0], float(q[1]), float(q[2]),
                                  float(q[3]), q[4] == '1'))
            if not cands:
                continue
            m = meta.get(c['sid'], {})
            ch, gd = c['chosen'], c['gold']
            rows.append({
                'sid': c['sid'], 'doc': m.get('sentence_id', c['sid']),
                'pos': int(c['char_start']), 'reading': c['reading'],
                'chosen': ch, 'gold': gd, 'label': 1 if ch != gd else 0,
                'direction': f'{ch}→{gd}',
                'n_cands': n_cands, 'gold_rank': int(c['gold_rank']),
                'chosen_rank': int(c['chosen_rank']),
                'left': c['left_chars'], 'right': c['right_chars'],
                'right_empty': c['right_empty'] == '1',
                'cands': cands, 'domain': m.get('domain', ''),
                'sent_len': len(m.get('sentence', '')),
                'variant': (ch, gd) in VARIANTS,
            })
    return rows


# ── 特徵 ────────────────────────────────────────────────────────────────────
def feat_eng(r):
    """引擎側、**字元無關**的數值特徵。未見方向上唯一可能泛化的一族。"""
    sc = sorted((c[1] for c in r['cands']), reverse=True)
    ch = next((c for c in r['cands'] if c[4]), None)
    chs = ch[1] if ch else sc[0]
    top1 = sc[0]
    top2 = sc[1] if len(sc) > 1 else sc[0]
    pmis_l = [c[2] for c in r['cands']]
    pmis_r = [c[3] for c in r['cands']]
    chl = ch[2] if ch else 0.0
    chr_ = ch[3] if ch else 0.0
    return np.array([
        chs, top1, top2, top1 - top2, chs - top1, chs - top2,
        float(np.mean(sc)), float(np.std(sc)),
        chl, chr_, max(pmis_l), max(pmis_r),
        chl - max(pmis_l), chr_ - max(pmis_r),
        float(np.mean(pmis_l)), float(np.mean(pmis_r)),
        math.log1p(r['n_cands']), float(r['chosen_rank']),
        1.0 if r['chosen_rank'] == 0 else 0.0,
        1.0 if r['right_empty'] else 0.0,
        math.log1p(r['sent_len']), r['pos'] / max(r['sent_len'], 1),
        1.0 if r['pos'] == 0 else 0.0,
    ], dtype=np.float32)


def build_vocabs(rows):
    uni, cand, cbi = collections.Counter(), collections.Counter(), collections.Counter()
    for r in rows:
        for ch in r['left'][-WIN:]:
            uni[('L', ch)] += 1
        for ch in r['right'][:WIN]:
            uni[('R', ch)] += 1
        for c in r['cands'][:12]:
            cand[c[0]] += 1
        l = r['left'][-1:] or ['']
        rt = r['right'][:1] or ['']
        for c in r['cands'][:12]:
            cbi[('L', l[0], c[0])] += 1
            cbi[('R', c[0], rt[0])] += 1
    keep = lambda x: {k: i for i, (k, n) in enumerate(
        v for v in x.most_common() if v[1] >= MIN_COUNT)}
    return keep(uni), keep(cand), keep(cbi)


def feat_ctx(r, V):
    uni = V[0]
    v = np.zeros(len(uni), dtype=np.float32)
    for ch in r['left'][-WIN:]:
        k = ('L', ch)
        if k in uni:
            v[uni[k]] += 1
    for ch in r['right'][:WIN]:
        k = ('R', ch)
        if k in uni:
            v[uni[k]] += 1
    return v


def feat_cand(r, V):
    cd = V[1]
    v = np.zeros(len(cd), dtype=np.float32)
    for c in r['cands'][:12]:
        if c[0] in cd:
            v[cd[c[0]]] += 1
    return v


def feat_cci(r, V):
    cbi = V[2]
    v = np.zeros(len(cbi), dtype=np.float32)
    l = r['left'][-1:] or ['']
    rt = r['right'][:1] or ['']
    for c in r['cands'][:12]:
        for k in (('L', l[0], c[0]), ('R', c[0], rt[0])):
            if k in cbi:
                v[cbi[k]] += 1
    return v


FAMILIES = {
    'ENG 引擎側數值（字元無關）': ['eng'],
    'CTX 上下文字元 ±6': ['ctx'],
    'CAND 候選身分': ['cand'],
    'ENG+CTX': ['eng', 'ctx'],
    'ENG+CTX+CAND': ['eng', 'ctx', 'cand'],
    '**FULL（＋候選條件化字對）**': ['eng', 'ctx', 'cand', 'cci'],
}


def make_X(rows, parts, V):
    blocks = []
    for p in parts:
        if p == 'eng':
            blocks.append(np.stack([feat_eng(r) for r in rows]))
        elif p == 'ctx':
            blocks.append(np.stack([feat_ctx(r, V) for r in rows]))
        elif p == 'cand':
            blocks.append(np.stack([feat_cand(r, V) for r in rows]))
        elif p == 'cci':
            blocks.append(np.stack([feat_cci(r, V) for r in rows]))
    return np.concatenate(blocks, axis=1)


def prec_at_override(score, label, frac):
    """在「出手率 = frac」的操作點上的 precision。"""
    n = max(1, int(round(len(score) * frac)))
    order = np.argsort(-np.asarray(score))[:n]
    y = np.asarray(label)[order]
    return float(y.mean()), n


def balanced_acc(score, label):
    """在最佳門檻上的 balanced accuracy（診斷用）。"""
    s = np.asarray(score)
    y = np.asarray(label)
    order = np.argsort(-s)
    y = y[order]
    P, N = y.sum(), len(y) - y.sum()
    if not P or not N:
        return float('nan')
    tp = np.cumsum(y)
    fp = np.cumsum(1 - y)
    return float(np.max(0.5 * (tp / P + 1 - fp / N)))


def recall_at_fpr(score, label, target):
    s, y = np.asarray(score), np.asarray(label)
    order = np.argsort(-s)
    y = y[order]
    P, N = y.sum(), len(y) - y.sum()
    tp, fp = np.cumsum(y), np.cumsum(1 - y)
    ok = fp / N <= target
    return float(tp[ok].max() / P) if ok.any() else 0.0


def leakage_audit(rows, folds, w):
    """§七 要求的逐項洩漏檢查。任何一項不綠都必須寫在報告裡。"""
    w('\n## Leakage audit\n')
    w('| 檢查項 | 結果 |')
    w('|---|---|')
    ok = True

    # 1 方向不相交
    bad = 0
    for k in range(K):
        tr = {r['direction'] for r in rows if folds[r['direction']] != k}
        te = {r['direction'] for r in rows if folds[r['direction']] == k}
        if tr & te:
            bad += 1
    w(f'| train/test **方向**不相交 | {"✅ 5/5 folds" if not bad else f"❌ {bad} folds 重疊"} |')
    ok &= not bad

    # 2 文件不相交（訓練集已剔除測試文件）
    bad = 0
    for k in range(K):
        te_docs = {r['doc'] for r in rows if folds[r['direction']] == k}
        tr_docs = {r['doc'] for r in rows
                   if folds[r['direction']] != k and r['doc'] not in te_docs}
        if tr_docs & te_docs:
            bad += 1
    w(f'| train/test **文件**不相交 | {"✅ 5/5 folds" if not bad else f"❌ {bad} folds 重疊"} |')
    ok &= not bad

    # 3 完全相同的句子出現在不同 doc
    bysent = collections.defaultdict(set)
    for r in rows:
        bysent[r['sid']].add(r['doc'])
    dupsent = sum(1 for v in bysent.values() if len(v) > 1)
    w(f'| 同一 sid 對到多個 doc | {"✅ 0" if not dupsent else f"⚠️ {dupsent}"} |')

    # 4 完全相同的節點（同 doc 同位置）重複出現
    seen = collections.Counter((r['doc'], r['pos']) for r in rows)
    dupnode = sum(1 for v in seen.values() if v > 1)
    w(f'| 重複節點（同 doc 同位置）| {"✅ 0" if not dupnode else f"❌ {dupnode}"} |')
    ok &= not dupnode

    # 5 完全相同的 (左文, 讀音, 右文, 候選集) 跨 fold 出現
    sig = collections.defaultdict(set)
    for r in rows:
        key = (r['left'][-WIN:], r['reading'], r['right'][:WIN],
               tuple(c[0] for c in r['cands'][:12]))
        sig[key].add(folds[r['direction']])
    cross = sum(1 for v in sig.values() if len(v) > 1)
    w(f'| 相同左右文＋候選集跨 fold | {"✅ 0" if not cross else f"⚠️ {cross} 組"}'
      f'（共 {len(sig):,} 種簽名）|')

    # 6 前綴樣本
    w('| 前綴樣本（kind=1）| ✅ 已在載入時全部排除 |')

    # 7 重複句子文字
    txt = collections.Counter(r['sid'] for r in rows)
    w(f'| 語料重複句 | 由 sid 唯一性保證（{len(txt):,} 句）|')
    return ok, cross


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--items', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--l2', type=float, default=2.0)
    args = ap.parse_args()

    rows = load(args.nodes, args.items)
    dirs = sorted({r['direction'] for r in rows})
    folds = {d: dfold(d) for d in dirs}
    for r in rows:
        r['fold'] = folds[r['direction']]

    out = []
    w = out.append
    npos = sum(r['label'] for r in rows)
    w('## 資料集\n')
    w(f'* span=1、n_cands≥2、kind=0 的節點：**{len(rows):,}**')
    w(f'* 正例（引擎選錯）**{npos:,}**（{npos/len(rows):.2%}）、'
      f'負例 {len(rows)-npos:,}')
    w(f'* 方向數 **{len(dirs):,}**（其中非對角＝真正的錯誤方向 '
      f'{sum(1 for d in dirs if d.split("→")[0] != d.split("→")[1]):,}）')
    w(f'* 文件（＝句）**{len({r["doc"] for r in rows}):,}**')
    w(f'\n切分種子 `{SEED}`，K={K}，fold = sha256(seed:direction) % {K}。'
      f'deterministic、不手動調整。\n')

    ok, cross = leakage_audit(rows, folds, w)

    # ── 逐 fold 規模 ──
    w('\n\n## 切分規模\n')
    w('| Fold | train 方向 | test 方向 | train 節點 | test 節點 | '
      'train 文件 | test 文件 | test 正例 |')
    w('|---|---|---|---|---|---|---|---|')
    split = {}
    for k in range(K):
        te = [r for r in rows if r['fold'] == k]
        te_docs = {r['doc'] for r in te}
        tr = [r for r in rows if r['fold'] != k and r['doc'] not in te_docs]
        split[k] = (tr, te)
        w(f'| {k} | {len({r["direction"] for r in tr}):,} | '
          f'{len({r["direction"] for r in te}):,} | {len(tr):,} | {len(te):,} | '
          f'{len({r["doc"] for r in tr}):,} | {len(te_docs):,} | '
          f'{sum(r["label"] for r in te):,} |')

    # ── 可用的 held-out 方向 ──
    dc = collections.Counter(r['direction'] for r in rows if r['label'] == 1)
    err_dirs = [d for d in dirs if d.split('→')[0] != d.split('→')[1]]
    usable = [d for d in err_dirs if dc[d] >= MIN_DIR_N]
    w(f'\n**held-out 方向**：錯誤方向共 {len(err_dirs):,}；'
      f'n ≥ {MIN_DIR_N} 的 **{len(usable)}** 個可單獨評估；'
      f'其餘 {len(err_dirs)-len(usable):,} 個標 **INSUFFICIENT POWER**，'
      f'只進 aggregate、不單獨下結論。\n')

    # ── 主結果：逐特徵族 ──
    V = build_vocabs(rows)
    w(f'\n字表（出現 ≥{MIN_COUNT} 次）：上下文 {len(V[0]):,}、'
      f'候選 {len(V[1]):,}、候選條件化字對 {len(V[2]):,}。L2 = {args.l2}（全族相同）。\n')

    w('\n\n## 主結果：held-out 方向 ＋ held-out 文件\n')
    w('| 特徵族 | 維度 | **ROC-AUC** | 95% CI | PR-AUC | bal-acc | '
      'recall@FPR5% | 逐 fold AUC |')
    w('|---|---|---|---|---|---|---|---|')
    store = {}
    for name, parts in FAMILIES.items():
        sc = np.zeros(len(rows))
        idx_of = {id(r): i for i, r in enumerate(rows)}
        per = {}
        dim = 0
        for k in range(K):
            tr, te = split[k]
            if not tr or not te:
                continue
            Xtr = make_X(tr, parts, V)
            Xte = make_X(te, parts, V)
            dim = Xtr.shape[1]
            mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-6
            ytr = np.array([r['label'] for r in tr], dtype=np.float32)
            wv, b = fit_lr((Xtr - mu) / sd, ytr, l2=args.l2)
            s = ((Xte - mu) / sd) @ wv + b
            for r, v in zip(te, s):
                sc[idx_of[id(r)]] = v
            yte = [r['label'] for r in te]
            per[k] = roc_auc(list(s), yte) if 0 < sum(yte) < len(yte) else float('nan')
        y = [r['label'] for r in rows]
        docs = [r['doc'] for r in rows]
        a = roc_auc(list(sc), y)
        lo, hi = boot_ci(list(sc), y, docs, n=400)
        store[name] = (sc.copy(), per)
        w(f'| {name} | {dim:,} | **{a:.3f}** | [{lo:.3f}, {hi:.3f}] | '
          f'{pr_auc(sc, y):.3f} | {balanced_acc(sc, y):.3f} | '
          f'{recall_at_fpr(sc, y, 0.05):.3f} | '
          + ' '.join(f'{per[k]:.2f}' for k in sorted(per)) + ' |')

    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out) + '\n')
    print('\n'.join(out))
    np.save(args.out + '.scores.npy',
            np.stack([store[n][0] for n in FAMILIES]))
    with open(args.out + '.rows.json', 'w', encoding='utf-8') as fh:
        json.dump([{k: r[k] for k in
                    ('doc', 'pos', 'direction', 'label', 'fold', 'chosen',
                     'gold', 'n_cands', 'domain', 'variant')} for r in rows],
                  fh, ensure_ascii=False)


if __name__ == '__main__':
    main()
