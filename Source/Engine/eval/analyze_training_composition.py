#!/usr/bin/env python3
# 訓練樣本組成分析：誰在佔 loss？（棒⑭-B 動手前的必要前置）
#
# 棒⑭-A 已經量到「方向」層面的分布；這一支補的是**組成**層面：
#   * easy（engine==gold） vs hard
#   * 單字節點 vs 多字詞節點
#   * 各類別在「每個 epoch 實際看到幾次」裡佔多少 —— 也就是對 loss 的實際貢獻
#
# 為什麼要算 loss 貢獻而不是只算筆數：棒⑬ 的 ×12 是**物理複製**，
# 一筆難例在一個 epoch 裡出現 12 次。所以「資料集裡有多少」跟
# 「模型實際看到多少」是兩回事，後者才是決定模型學到什麼的東西。
#
# 全域（所有讀音）與目標組（作做坐座）分開report —— 模型是通用的，
# 但開火只在 ㄗㄨㄛˋ，兩邊的組成不一定一樣。
#
# 用法：
#   python3 analyze_training_composition.py --nodes <nodes.tsv> \
#       --sentences <sentences.jsonl> [--hard-weight 12] [--per-stratum 400]

import argparse
import collections
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_node_expert import (DE_READING, MAX_CANDS,  # noqa: E402
                               load_rows, load_split_override)

GROUP = set('作做坐座')
FIRE = 'ㄗㄨㄛˋ'


class Args:
    pass


def span_of(row):
    return len(row['reading'].split('-'))


def in_group(row):
    syls = row['reading'].split('-')
    if FIRE not in syls:
        return False
    i = syls.index(FIRE)
    if len(row['chosen']) != len(syls) or len(row['gold']) != len(syls):
        return False
    return row['chosen'][i] in GROUP and row['gold'][i] in GROUP


def direction(row):
    syls = row['reading'].split('-')
    i = syls.index(FIRE)
    return row['chosen'][i], row['gold'][i]


def table(rows, weights, keyfn, title, fh, order=None):
    """rows 依 keyfn 分組，報筆數與（加權後的）loss 佔比。"""
    cnt = collections.Counter()
    wgt = collections.Counter()
    hard_cnt = collections.Counter()
    for r, w in zip(rows, weights):
        k = keyfn(r)
        cnt[k] += 1
        wgt[k] += w
        if r['hard']:
            hard_cnt[k] += 1
    tot_c, tot_w = sum(cnt.values()), sum(wgt.values())
    keys = order or sorted(cnt, key=lambda k: -cnt[k])
    print(f'\n### {title}\n', file=fh)
    print('| 類別 | 筆數 | 筆數佔比 | 其中 hard | hard 率 | '
          'epoch 出現次數 | **loss 佔比** |', file=fh)
    print('|---|---|---|---|---|---|---|', file=fh)
    for k in keys:
        if not cnt[k]:
            continue
        print(f'| {k} | {cnt[k]:,} | {100 * cnt[k] / tot_c:.1f}% | '
              f'{hard_cnt[k]:,} | {100 * hard_cnt[k] / cnt[k]:.1f}% | '
              f'{wgt[k]:,.0f} | **{100 * wgt[k] / tot_w:.1f}%** |', file=fh)
    print(f'| **合計** | {tot_c:,} | 100% | '
          f'{sum(hard_cnt.values()):,} | '
          f'{100 * sum(hard_cnt.values()) / tot_c:.1f}% | {tot_w:,.0f} | 100% |',
          file=fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--sentences', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--hard-weight', type=int, default=12)
    ap.add_argument('--per-stratum', type=int, default=400)
    ap.add_argument('--dev-frac', type=float, default=0.20)
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)

    a = Args()
    rows, stats, _, _ = load_rows(args.nodes, ['<pad>', '<unk>'],
                                  ['<pad>', '<unk>'], a)

    # 重放分層採樣（同 seed）與 split
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
    strat = [rows[i] for i in keep]

    kept_sids = []
    with open(args.nodes, encoding='utf-8') as f:
        next(f)
        for line in f:
            c = line.rstrip('\n').split('\t')
            if len(c) < 16 or DE_READING in c[6].split('-') or c[9] != '1':
                continue
            cands = [q.split(':') for q in c[15].split('|')]
            cands = [(q[0], float(q[1])) for q in cands if len(q) == 5]
            if len(cands) < 2:
                continue
            cands.sort(key=lambda x: -x[1])
            if c[8] not in [v for v, _ in cands[:MAX_CANDS]]:
                continue
            kept_sids.append(int(c[0]))
    sid_split = load_split_override(args.sentences, args.dev_frac)
    for r, s in zip(strat, [kept_sids[i] for i in keep]):
        r['split'] = sid_split.get(s, r['split'])
        r['sid'] = s
    train = [r for r in strat if r['split'] == 'train']

    # 棒⑬ 的實際 loss 權重＝物理複製次數
    w13 = [args.hard_weight if r['hard'] else 1 for r in train]
    w_flat = [1] * len(train)

    grp = [r for r in train if in_group(r)]
    w13g = [args.hard_weight if r['hard'] else 1 for r in grp]
    w_flatg = [1] * len(grp)

    with open(args.out, 'w', encoding='utf-8') as fh:
        w = fh.write
        w('# 訓練樣本組成分析（棒⑭-B 前置）\n\n')
        w('「筆數」＝資料集裡有幾筆；「loss 佔比」＝一個 epoch 裡實際被看到幾次。\n')
        w(f'棒⑬ 的 ×{args.hard_weight} 是**物理複製**，所以兩者不一樣，'
          f'後者才決定模型學到什麼。\n\n')
        w(f'train 共 {len(train):,} 筆（其中作做坐座 {len(grp):,} 筆）\n')

        w('\n## A. 全域（所有讀音）\n')
        w(f'\n#### 棒⑬ 實際配方（hard ×{args.hard_weight}）\n')
        table(train, w13, lambda r: 'hard（engine≠gold）' if r['hard']
              else 'easy（engine==gold）', 'easy / hard', fh,
              order=['easy（engine==gold）', 'hard（engine≠gold）'])
        table(train, w13, lambda r: '單字節點' if span_of(r) == 1 else '多字詞節點',
              '單字 / 多字詞', fh, order=['單字節點', '多字詞節點'])
        table(train, w13,
              lambda r: ('單字' if span_of(r) == 1 else '多字') +
                        ('·hard' if r['hard'] else '·easy'),
              '交叉：單字/多字 × easy/hard', fh,
              order=['單字·easy', '單字·hard', '多字·easy', '多字·hard'])
        w(f'\n#### 移除 ×{args.hard_weight}（每筆算一次）後同一張表\n')
        table(train, w_flat, lambda r: 'hard' if r['hard'] else 'easy',
              'easy / hard（無加權）', fh, order=['easy', 'hard'])
        table(train, w_flat,
              lambda r: ('單字' if span_of(r) == 1 else '多字') +
                        ('·hard' if r['hard'] else '·easy'),
              '交叉（無加權）', fh,
              order=['單字·easy', '單字·hard', '多字·easy', '多字·hard'])

        w('\n## B. 目標組（作做坐座）\n')
        w(f'\n#### 棒⑬ 實際配方（hard ×{args.hard_weight}）\n')
        table(grp, w13g, lambda r: 'hard' if r['hard'] else 'easy',
              'easy / hard', fh, order=['easy', 'hard'])
        table(grp, w13g, lambda r: '單字節點' if span_of(r) == 1 else '多字詞節點',
              '單字 / 多字詞', fh, order=['單字節點', '多字詞節點'])
        table(grp, w13g, lambda r: f'{direction(r)[0]}→{direction(r)[1]}',
              '逐方向（含對角線）', fh)
        w(f'\n#### 移除 ×{args.hard_weight} 後\n')
        table(grp, w_flatg, lambda r: 'hard' if r['hard'] else 'easy',
              'easy / hard（無加權）', fh, order=['easy', 'hard'])
        table(grp, w_flatg, lambda r: '單字節點' if span_of(r) == 1 else '多字詞節點',
              '單字 / 多字詞（無加權）', fh, order=['單字節點', '多字詞節點'])

        # 句長 × 價值
        w('\n## C. 句長與訓練價值\n\n')
        w('| 句長 | 節點數 | hard 率 | 佔全部 hard |\n|---|---|---|---|\n')
        by_len = collections.Counter()
        hard_len = collections.Counter()

        def bucket(n):
            if n <= 6:
                return '≤6'
            if n <= 8:
                return '7–8'
            if n <= 12:
                return '9–12'
            if n <= 20:
                return '13–20'
            return '21+'

        sent_len = {}
        with open(args.sentences, encoding='utf-8') as f:
            for i, line in enumerate(f, start=1):
                sent_len[i] = len(json.loads(line)['text'])
        tot_hard = sum(1 for r in train if r['hard'])
        for r in train:
            b = bucket(sent_len.get(r.get('sid', 0), 0))
            by_len[b] += 1
            if r['hard']:
                hard_len[b] += 1
        for b in ['≤6', '7–8', '9–12', '13–20', '21+']:
            if not by_len[b]:
                continue
            w(f'| {b} | {by_len[b]:,} | {100 * hard_len[b] / by_len[b]:.1f}% | '
              f'{100 * hard_len[b] / tot_hard:.1f}% |\n')

    print(open(args.out, encoding='utf-8').read())


if __name__ == '__main__':
    main()
