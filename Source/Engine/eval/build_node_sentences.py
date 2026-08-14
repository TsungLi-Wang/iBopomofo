#!/usr/bin/env python3
# 第一步：把訓練正文切成「純漢字句 + 對齊的注音」，給 C++ 抽取器吃。
#
# 注音一律走**現成的**詞庫最長匹配（`convert_eval_tsv_to_cases.py` 的
# `text_to_readings`，BPMFBase + BPMFMappings 同一棵 trie）。
# 對不齊、查不到讀音、音節數對不上 → **丟這句**。
# **不准自己發明破音**：破音字以詞庫最長匹配為準，對齊後仍對不上就丟。
#
# 為什麼只留純漢字段：評分機與引擎吃的是注音音節序列，標點／英數在
# text_to_readings 裡是被跳過的 —— 一旦跳過，字元位置就跟音節位置對不上，
# 後面「節點 span → 金標子字串」的對齊會整個歪掉，而且不會報錯。
#
# 用法：
#   python3 build_node_sentences.py --out <dir> [--sample N] [--must 作做坐座]

import argparse
import hashlib
import json
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_eval_tsv_to_cases import load_trie, text_to_readings  # noqa: E402

HAN = re.compile(r'[一-鿿]+')


def is_dev(doc_id, frac):
    """依 doc id 切 held-out。τ 只准在這一側定，不准看考卷或真實驗證集。"""
    h = int(hashlib.sha256(('nodesent:' + doc_id).encode()).hexdigest()[:8], 16)
    return (h % 1000) < int(frac * 1000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--train', default=os.path.expanduser(
        '~/Documents/taiwan-mandarin-dataset/training/train_corpus_decontaminated.jsonl'))
    ap.add_argument('--bpmf-base', default='Source/Data/BPMFBase.txt')
    ap.add_argument('--bpmf-mappings', default='Source/Data/BPMFMappings.txt')
    ap.add_argument('--out', required=True)
    ap.add_argument('--min-len', type=int, default=4)
    ap.add_argument('--max-len', type=int, default=40)
    ap.add_argument('--sample', type=int, default=60000,
                    help='一般句抽多少（含 --must 的句子一律全收，不佔這個額度）')
    ap.add_argument('--must', default='作做坐座',
                    help='含這些字的句子全收（本棒的目標組）')
    ap.add_argument('--dev-frac', type=float, default=0.08)
    ap.add_argument('--quality-band', default='',
                    help='逗號分隔；空＝不過濾。過濾了什麼要寫進報告')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    trie = load_trie(Path(args.bpmf_base), Path(args.bpmf_mappings))
    bands = {b for b in args.quality_band.split(',') if b}
    must = set(args.must)

    rng = random.Random(20260814)
    stats = {'docs': 0, 'docs_band_skipped': 0, 'runs': 0, 'too_short': 0,
             'too_long': 0, 'no_reading': 0, 'len_mismatch': 0,
             'kept_must': 0, 'kept_other_seen': 0}
    must_rows, other_rows = [], []

    with open(args.train, encoding='utf-8') as fh:
        for line in fh:
            doc = json.loads(line)
            stats['docs'] += 1
            if bands and doc.get('quality_band') not in bands:
                stats['docs_band_skipped'] += 1
                continue
            dev = is_dev(doc['id'], args.dev_frac)
            for m in HAN.finditer(doc['text']):
                run = m.group(0)
                stats['runs'] += 1
                if len(run) < args.min_len:
                    stats['too_short'] += 1
                    continue
                if len(run) > args.max_len:
                    stats['too_long'] += 1
                    continue
                try:
                    readings = text_to_readings(trie, run)
                except ValueError:
                    stats['no_reading'] += 1
                    continue
                syl = readings.split('-')
                if len(syl) != len(run):
                    # 詞庫的詞讀音數與字數對不上 → 位置對不齊，丟掉。
                    stats['len_mismatch'] += 1
                    continue
                row = {'doc_id': doc['id'], 'text': run,
                       'readings': readings, 'split': 'dev' if dev else 'train'}
                if must & set(run):
                    must_rows.append(row)
                    stats['kept_must'] += 1
                else:
                    stats['kept_other_seen'] += 1
                    # 蓄水池抽樣：一般句只留 --sample 句，記憶體不隨語料長大
                    if len(other_rows) < args.sample:
                        other_rows.append(row)
                    else:
                        j = rng.randrange(stats['kept_other_seen'])
                        if j < args.sample:
                            other_rows[j] = row

    rows = must_rows + other_rows
    rng.shuffle(rows)
    out = os.path.join(args.out, 'sentences.jsonl')
    with open(out, 'w', encoding='utf-8') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    stats['kept_other'] = len(other_rows)
    stats['total'] = len(rows)
    stats['dev'] = sum(1 for r in rows if r['split'] == 'dev')
    with open(os.path.join(args.out, 'sentences-stats.json'), 'w',
              encoding='utf-8') as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f'→ {out}')


if __name__ == '__main__':
    main()
