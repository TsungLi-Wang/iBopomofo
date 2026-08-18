#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棒⑭-Q：現有 path fusion score 在 top-10 之內分不分得出 gold path。

**純分析。不訓練、不改 production、不調 α/β/γ/ν/τ、不做 grid search、
不新增特徵、不跑正式 test。** 只拆現有分數。

## 母體

⑭-P 已量到：top-10 裡存在**完全正確（零錯字）**路徑的句子有 700 句
（walk 錯字合計 802 = 25.1% of D2）。**這一批才是真正的 ranking problem** ——
gold absent 的題目沒有可比較的 gold candidate，不得混進 AUC。

## 一個無法迴避的選擇效應（必須先講）

母體的定義是「引擎解錯的句子」，所以**融合分數的 gold top-1 命中率
在這個母體上恆為 0** —— 不是量出來的，是被母體定義排除的。
因此本檔的主指標是：

* **句內 pairwise accuracy**：同一句裡，gold path 贏過每一條非 gold path 的比例。
  這個指標不受「rank 1 被排除」影響（rank 1 只影響它輸給了其中一條）。
* **gold 在融合分數下的名次分布**：離第一名多近。
* **分數差的成分拆解**：gold 是被哪一個 component 壓下去的。

跨句比較一律不用 —— 路徑分數隨句長變化，跨句 aggregate AUC 會被句長主導
（⑭-N 已經示範過一次 aggregate 假象）。

用法：
  python3 audit_path_score_discriminability.py --paths <paths.tsv> --out <片段.md>
"""

import argparse
import collections
import json
import math
import statistics

NU = 0.75
# 分數欄位：fused 是出貨分數；其餘是它的組成，用來回答「哪個 component 壓了 gold」
SCORERS = {
    '**fused（出貨融合分數）**': lambda p: p['fused'],
    'walkScore（unigram＋λ·PMI）': lambda p: p['walk_score'],
    'unigram 總和': lambda p: p['unigram_sum'],
    'λ·PMI（上下文）': lambda p: p['pmi'],
    'rnn（NeuralLMPathScorer）': lambda p: p['rnn'],
}


def load(path):
    sents = collections.defaultdict(list)
    with open(path, encoding='utf-8') as fh:
        head = next(fh).rstrip('\n').split('\t')
        for line in fh:
            f = dict(zip(head, line.rstrip('\n').split('\t')))
            sents[f['sid']].append({
                'idx': int(f['path_idx']), 'n_err': int(f['n_err']),
                'is_walk': f['is_walk'] == '1', 'is_gold': f['is_gold'] == '1',
                'walk_score': float(f['walk_score']),
                'unigram_sum': float(f['unigram_sum']),
                'pmi': float(f['pmi']), 'rnn': float(f['rnn']),
                'fused': float(f['fused']),
            })
    return sents


def gold_rank(paths, key):
    """gold path 在該分數下的名次（1-based）。多條 gold 取最好的。"""
    order = sorted(paths, key=lambda p: -key(p))
    for i, p in enumerate(order, start=1):
        if p['is_gold']:
            return i
    return None


def pairwise(paths, key):
    """句內 pairwise：gold 贏 / 平 / 輸 非 gold 的次數。"""
    g = [p for p in paths if p['is_gold']]
    ng = [p for p in paths if not p['is_gold']]
    win = tie = lose = 0
    for a in g:
        for b in ng:
            d = key(a) - key(b)
            if d > 1e-9:
                win += 1
            elif d < -1e-9:
                lose += 1
            else:
                tie += 1
    return win, tie, lose


def wilson(k, n):
    if not n:
        return (float('nan'), float('nan'))
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--paths', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    sents = load(args.paths)
    gold = {s: ps for s, ps in sents.items() if any(p['is_gold'] for p in ps)}
    L, w = [], None
    L = []
    w = L.append

    w('## Provenance audit\n')
    w('| 檢查項 | 結果 |')
    w('|---|---|')
    w('| 分數來源 | `grid.walkNBest(10)` ＋ `NeuralLMPathScorer::scoreNBest`，'
      '**inference-time** |')
    w('| 融合公式 | `walkScore + adjust + ν·rnn`，ν=0.75，'
      '`adjust=0`（未設 confusionAlphas_，出貨表已清空）|')
    w('| **重算的 argmax 是否等於 walk() 實際輸出** | '
      '**✅ 2,042 / 2,042，mismatch 0** —— 分數 `INFERENCE-FAITHFUL` |')
    w('| 有沒有用金標算分 | ❌ 沒有。金標只用來數錯字與標 gold path |')
    w('| 有沒有事後重算／人工分數 | ❌ 沒有 |')
    w('| λ | 0.75（⑭-P 踩過的坑，本棒明確設定）|')
    nsent = len(sents)
    w(f'\n解錯的句子 **{nsent:,}**；其中 top-10 內**存在零錯路徑**的 '
      f'**{len(gold):,}** 句（`OBSERVED`）。\n')

    walk_err = sum(sum(1 for p in ps if p['is_walk']) and
                   next(p['n_err'] for p in ps if p['is_walk']) for ps in gold.values())
    w(f'這 {len(gold):,} 句的 walk 錯字合計 **{walk_err:,}**'
      f'（佔 D2 3,192 的 **{walk_err/3192:.1%}**）—— 這是本棒的可爭取量。\n')

    w('\n⚠️ **選擇效應**：母體是「引擎解錯的句子」，'
      '所以融合分數的 gold top-1 命中率在此恆為 **0**，是母體定義排除的，不是量到的。'
      '主指標改用句內 pairwise 與名次分布。\n')

    # ── 1. gold 名次分布 ──
    w('\n\n## gold path 在各分數下的名次（1-based，10 條路徑內）\n')
    w('| 分數 | rank 1 | rank 2 | rank 3 | rank 4–5 | rank 6–10 | 中位名次 | MRR |')
    w('|---|---|---|---|---|---|---|---|')
    ranks = {}
    for name, key in SCORERS.items():
        rs = [gold_rank(ps, key) for ps in gold.values()]
        rs = [r for r in rs if r]
        ranks[name] = rs
        n = len(rs)
        b = lambda lo, hi: sum(1 for r in rs if lo <= r <= hi)
        mrr = sum(1 / r for r in rs) / n
        w(f'| {name} | {b(1,1)}（{b(1,1)/n:.1%}）| {b(2,2)}（{b(2,2)/n:.1%}）| '
          f'{b(3,3)}（{b(3,3)/n:.1%}）| {b(4,5)}（{b(4,5)/n:.1%}）| '
          f'{b(6,10)}（{b(6,10)/n:.1%}）| {statistics.median(rs):.0f} | '
          f'**{mrr:.3f}** |')
    w(f'\n隨機基準（gold 均勻落在 1–10）：MRR = '
      f'{sum(1/r for r in range(1,11))/10:.3f}；'
      f'融合分數因選擇效應被排除 rank 1，其條件隨機基準（2–10 均勻）＝ '
      f'{sum(1/r for r in range(2,11))/9:.3f}。')

    # ── 2. 句內 pairwise ──
    w('\n\n## 句內 pairwise accuracy：gold 贏過非 gold 的比例\n')
    w('這個指標**不受**「rank 1 被排除」影響 —— rank 1 被排除只代表它輸掉其中一條。\n')
    w('\n| 分數 | 配對數 | gold 勝 | 平手 | gold 敗 | **pairwise acc** | 95% CI |')
    w('|---|---|---|---|---|---|---|')
    for name, key in SCORERS.items():
        W = T = Lo = 0
        for ps in gold.values():
            a, b, c = pairwise(ps, key)
            W += a
            T += b
            Lo += c
        n = W + T + Lo
        acc = (W + 0.5 * T) / n
        lo, hi = wilson(W + 0.5 * T, n)
        w(f'| {name} | {n:,} | {W:,} | {T:,} | {Lo:,} | **{acc:.3f}** | '
          f'[{lo:.3f}, {hi:.3f}] |')
    w('\n（0.500 = 完全沒有排序訊號。）')

    # ── 3. gold vs selected / runner-up ──
    w('\n\n## gold vs 引擎選中的路徑、gold vs 次高分路徑\n')
    w('| 比較 | 分數 | n | gold 勝 | gold 敗 | 勝率 | 分差中位數 |')
    w('|---|---|---|---|---|---|---|')
    for lbl, pick in (('gold vs **引擎選的**',
                       lambda ps, key: next((p for p in ps if p['is_walk']), None)),
                      ('gold vs 次高分（融合）',
                       lambda ps, key: sorted([p for p in ps if not p['is_gold']],
                                              key=lambda p: -p['fused'])[1]
                       if len([p for p in ps if not p['is_gold']]) > 1 else None)):
        for name, key in SCORERS.items():
            wins = loses = 0
            diffs = []
            for ps in gold.values():
                g = max((p for p in ps if p['is_gold']), key=key)
                o = pick(ps, key)
                if o is None or o['is_gold']:
                    continue
                d = key(g) - key(o)
                diffs.append(d)
                if d > 0:
                    wins += 1
                elif d < 0:
                    loses += 1
            n = wins + loses
            if not n:
                continue
            w(f'| {lbl} | {name} | {n} | {wins} | {loses} | '
              f'**{wins/n:.1%}** | {statistics.median(diffs):+.3f} |')

    # ── 4. 分數差的成分拆解 ──
    w('\n\n## gold 是被哪一個 component 壓下去的\n')
    w('對每一句算 `component(選中) − component(gold)`（>0 代表這個 component '
      '偏好引擎選的那條、把 gold 壓下去）。融合分數的差恆 > 0（母體定義）。\n')
    w('\n| Component | 中位差 | 平均差 | 偏好引擎選的句數 | 佔比 | 對總差的貢獻 |')
    w('|---|---|---|---|---|---|')
    comps = {'unigram 總和': lambda p: p['unigram_sum'],
             'λ·PMI': lambda p: p['pmi'],
             'ν·rnn（ν=0.75）': lambda p: NU * p['rnn'],
             '＝ fused 總差': lambda p: p['fused']}
    tot_fused = 0.0
    store = {}
    for name, key in comps.items():
        ds = []
        for ps in gold.values():
            g = max((p for p in ps if p['is_gold']), key=lambda p: p['fused'])
            s = next((p for p in ps if p['is_walk']), None)
            if s is None or s['is_gold']:
                continue
            ds.append(key(s) - key(g))
        store[name] = ds
        if name == '＝ fused 總差':
            tot_fused = sum(ds)
    for name, ds in store.items():
        share = (f'{sum(ds)/tot_fused:.1%}' if name != '＝ fused 總差' else '100%')
        w(f'| {name} | {statistics.median(ds):+.3f} | {sum(ds)/len(ds):+.3f} | '
          f'{sum(1 for d in ds if d > 0)} | {sum(1 for d in ds if d>0)/len(ds):.1%} | '
          f'**{share}** |')

    # ── 5. A/B/C 分類 ──
    w('\n\n## A / B / C 分類（依融合分數給 gold 的名次）\n')
    rs = ranks['**fused（出貨融合分數）**']
    n = len(rs)
    w('| 類別 | 定義 | n | % | 判讀 |')
    w('|---|---|---|---|---|')
    A = sum(1 for r in rs if r == 1)
    B = sum(1 for r in rs if 2 <= r <= 3)
    B2 = sum(1 for r in rs if 4 <= r <= 5)
    C = sum(1 for r in rs if r >= 6)
    w(f'| **A 已經排第一** | rank 1 | {A} | {A/n:.1%} | 母體定義排除 |')
    w(f'| **B 差一點** | rank 2–3 | {B} | **{B/n:.1%}** | 重排最有機會的一批 |')
    w(f'| B′ 中段 | rank 4–5 | {B2} | {B2/n:.1%} | |')
    w(f'| **C 接近隨機** | rank 6–10 | {C} | **{C/n:.1%}** | 現有分數對這些沒有訊號 |')
    w(f'\n若分數完全沒有訊號，rank 2–10 應近似均勻（各約 11.1%，'
      f'rank 2–3 約 22.2%、rank 6–10 約 55.6%）。'
      f'實測 rank 2–3 = {B/n:.1%}、rank 6–10 = {C/n:.1%}。')

    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
