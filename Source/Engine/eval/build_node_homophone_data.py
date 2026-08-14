#!/usr/bin/env python3
# 造「看注音、選同音」節點層模型的訓練資料（docs/decisions/0008）。
#
# 兩種樣本，同一個目標函數（候選受限 softmax）：
#
#   主監督  analysis/homophones/contexts.jsonl   注音＋左右文＋候選＋target
#   輔助    training/train_corpus_decontaminated.jsonl  單音字遮罩自監督
#
# 硬契約（0008 第三節，違反就不要跑）：
#   * contexts 必須先剔除 full_sentence_hint 命中 FROZEN_HASHES 的（實測 643 條）
#   * 「的得地」整組不當 gold（PTT 標籤髒，dead-ends D）
#   * benchmark/**、FROZEN_HASHES、raw/、train_corpus.jsonl 一律不進訓練
#   * 兩份 i注音真實驗證集與 EX1166 永不進訓練
#
# 候選集合一律取自引擎自己的 Source/Data/data.txt（讀音 → 單字），
# 不用 contexts 自帶的 candidates —— 出貨時節點候選來自引擎，訓練要對齊那一份。
#
# 輸出（--out 指的目錄，放在 repo 外）：
#   vocab.json      字表、讀音表、讀音→候選
#   train.npz / dev.npz    left[W] right[W] reading target source_kind
#   stats.json      逐項筆數（規格「執行紀錄」直接抄這份）

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

import numpy as np

HAN = re.compile(r'[一-鿿]')
WINDOW = 10                      # 左右各看幾個字（contexts 本身就是 ±10）
DE_GROUP = '的得地'              # dead-ends D：整組不當 gold
PAD, UNK = 0, 1                  # 字表保留位


def load_readings(data_txt):
    """從引擎詞庫讀「單字 ↔ 讀音」。回傳 (reading→候選, 字→讀音集合)。"""
    r2c, c2r = defaultdict(set), defaultdict(set)
    with open(data_txt, encoding='utf-8') as fh:
        for line in fh:
            if line.startswith('#'):
                continue
            f = line.rstrip('\n').split(' ')
            if len(f) < 3:
                continue
            reading, value = f[0], f[1]
            if len(value) != 1 or not HAN.match(value) or '-' in reading:
                continue
            r2c[reading].add(value)
            c2r[value].add(reading)
    return {k: sorted(v) for k, v in r2c.items()}, {k: sorted(v) for k, v in c2r.items()}


def frozen_hashes(path):
    with open(path, encoding='utf-8') as fh:
        return set(json.load(fh)['hashes'])


def encode_ctx(s, stoi, left):
    """左文取尾 WINDOW 個、右文取頭 WINDOW 個；不足補 PAD（補在遠端）。"""
    ids = [stoi.get(ch, UNK) for ch in s]
    if left:
        ids = ids[-WINDOW:]
        return [PAD] * (WINDOW - len(ids)) + ids
    ids = ids[:WINDOW]
    return ids + [PAD] * (WINDOW - len(ids))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', default=os.path.expanduser(
        '~/Documents/taiwan-mandarin-dataset'))
    ap.add_argument('--data-txt', default='Source/Data/data.txt')
    ap.add_argument('--out', required=True)
    ap.add_argument('--dev-frac', type=float, default=0.05)
    args = ap.parse_args()

    ds = args.dataset
    os.makedirs(args.out, exist_ok=True)

    # ── 禁區防呆：這幾個檔名絕不允許出現在讀取清單裡 ──
    ctx_path = os.path.join(ds, 'analysis/homophones/contexts.jsonl')
    train_path = os.path.join(ds, 'training/train_corpus_decontaminated.jsonl')
    frozen_path = os.path.join(ds, 'benchmark/FROZEN_HASHES.json')
    for p in (ctx_path, train_path, frozen_path):
        if not os.path.exists(p):
            sys.exit(f'讀不到：{p}')

    r2c, c2r = load_readings(args.data_txt)
    frozen = frozen_hashes(frozen_path)

    # 只留「候選 > 1」的讀音（候選只有一個就沒得選，不是這顆模型的題）
    ambiguous = {r: cs for r, cs in r2c.items() if len(cs) > 1}
    mono_chars = {c for c, rs in c2r.items() if len(rs) == 1}

    # ── 字表：詞庫裡所有單字 + 特殊符號 ──
    chars = sorted(c2r.keys())
    itos = ['<pad>', '<unk>'] + chars
    stoi = {c: i for i, c in enumerate(itos)}
    readings = sorted(r2c.keys())
    rtoi = {r: i for i, r in enumerate(readings)}
    # 讀音 → 候選（字表 id），推論端要一模一樣的表
    cand = {rtoi[r]: [stoi[c] for c in cs] for r, cs in r2c.items()}

    stats = Counter()
    rows_main, rows_aux = [], []
    dev_docs_main, dev_docs_aux = set(), set()

    def is_dev(doc_id):
        h = int(hashlib.sha256(doc_id.encode()).hexdigest()[:8], 16)
        return (h % 1000) < int(args.dev_frac * 1000)

    # ── 主監督：contexts.jsonl ──
    with open(ctx_path, encoding='utf-8') as fh:
        for line in fh:
            r = json.loads(line)
            stats['contexts_total'] += 1
            hint = r.get('full_sentence_hint') or ''
            if hint and hashlib.sha256(hint.encode()).hexdigest() in frozen:
                stats['contexts_dropped_frozen'] += 1
                continue
            if r['target_group'] == DE_GROUP:
                stats['contexts_dropped_de'] += 1
                continue
            reading, target = r['input_zhuyin'], r['target']
            if reading not in rtoi or target not in stoi:
                stats['contexts_dropped_oov'] += 1
                continue
            if target not in r2c[reading]:
                # 詞庫裡這個讀音出不了這個字 → 引擎在那個節點根本不會有這個候選
                stats['contexts_dropped_not_in_engine_candidates'] += 1
                continue
            if reading not in ambiguous:
                stats['contexts_dropped_unambiguous'] += 1
                continue
            row = (encode_ctx(r.get('left_context', ''), stoi, True),
                   encode_ctx(r.get('right_context', ''), stoi, False),
                   rtoi[reading], stoi[target], 0)
            doc = r['source_doc_id']
            if is_dev(doc):
                dev_docs_main.add(doc)
                rows_main.append((row, True))
            else:
                rows_main.append((row, False))
            stats['contexts_kept'] += 1

    # ── 輔助自監督：全文遮罩（只遮單音字，避免多音字讀音判錯注入雜訊）──
    with open(train_path, encoding='utf-8') as fh:
        for line in fh:
            r = json.loads(line)
            stats['train_docs'] += 1
            text = r['text']
            dev = is_dev(r['id'])
            if dev:
                dev_docs_aux.add(r['id'])
            for i, ch in enumerate(text):
                if ch not in mono_chars:
                    continue
                reading = c2r[ch][0]
                if reading not in ambiguous:
                    continue
                row = (encode_ctx(text[max(0, i - WINDOW):i], stoi, True),
                       encode_ctx(text[i + 1:i + 1 + WINDOW], stoi, False),
                       rtoi[reading], stoi[ch], 1)
                rows_aux.append((row, dev))
                stats['aux_kept'] += 1

    def pack(rows):
        n = len(rows)
        left = np.zeros((n, WINDOW), dtype=np.int16)
        right = np.zeros((n, WINDOW), dtype=np.int16)
        rd = np.zeros(n, dtype=np.int16)
        tg = np.zeros(n, dtype=np.int16)
        kind = np.zeros(n, dtype=np.int8)
        for i, (l, rt, rr, t, k) in enumerate(rows):
            left[i] = l
            right[i] = rt
            rd[i] = rr
            tg[i] = t
            kind[i] = k
        return dict(left=left, right=right, reading=rd, target=tg, kind=kind)

    train_rows = [r for r, d in rows_main + rows_aux if not d]
    dev_rows = [r for r, d in rows_main + rows_aux if d]
    np.savez_compressed(os.path.join(args.out, 'train.npz'), **pack(train_rows))
    np.savez_compressed(os.path.join(args.out, 'dev.npz'), **pack(dev_rows))

    stats['train_rows'] = len(train_rows)
    stats['dev_rows'] = len(dev_rows)
    stats['vocab_chars'] = len(itos)
    stats['vocab_readings'] = len(readings)
    stats['ambiguous_readings'] = len(ambiguous)
    stats['mono_chars'] = len(mono_chars)

    with open(os.path.join(args.out, 'vocab.json'), 'w', encoding='utf-8') as fh:
        json.dump({'itos': itos, 'readings': readings, 'cand': cand,
                   'window': WINDOW}, fh, ensure_ascii=False)
    with open(os.path.join(args.out, 'stats.json'), 'w', encoding='utf-8') as fh:
        json.dump(dict(sorted(stats.items())), fh, ensure_ascii=False, indent=2)
    print(json.dumps(dict(sorted(stats.items())), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
