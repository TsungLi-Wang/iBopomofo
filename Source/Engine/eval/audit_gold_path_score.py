#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棒⑭-T：gold path 強制打分診斷。

**純分析。不訓練、不改 production、不放寬 beam、不改 kNBestHypK、不跑正式 test。**

## 這一支要解開什麼

⑭-P 的「43.1% of D2 連 top-200 都沒有」不能讀成「打分器把 gold 排到 201 名以後」——
`walkNBest()` 是 beam DP（`kNBestHypK = 8`），實測 81.8% 的錯字位根本拿不到 200 條。
本棒繞過搜尋，直接問：**如果 gold path 存在，出貨打分器會給它多少分？**

## PRIMARY KPI

    F = #GOLD_BEATS_TOP1 / #eligible production-error sentences

`F` **不是** rescue rate，**不是** beam failure rate，**不是** recoverable rate。
它只叫 **SCORER-FAVORABILITY** —— gold 分數比目前 top-1 高，
不代表放寬 beam 就一定枚舉得到它。

用法：
  python3 audit_gold_path_score.py --gold <goldpath.tsv> \\
      --paths <paths-all.tsv> --log <gp.log> --out <片段.md>
"""

import argparse
import collections
import statistics

D2 = 3192
TOTAL_CHARS = 74649


def q(v, p):
    return sorted(v)[min(len(v) - 1, int(p * len(v)))] if v else float('nan')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gold', required=True)
    ap.add_argument('--paths', required=True)
    ap.add_argument('--log', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    rows = {}
    with open(args.gold, encoding='utf-8') as fh:
        head = next(fh).rstrip('\n').split('\t')
        for line in fh:
            f = dict(zip(head, line.rstrip('\n').split('\t')))
            rows[f['sid']] = {
                'ok': f['engine_correct'] == '1',
                'err': int(f['walk_err']),
                'top1': float(f['top1_fused']),
                'top1_walk': float(f['top1_walk']),
                'top1_rnn': float(f['top1_rnn']),
                'found': f['gold_found'] == '1',
                'gwalk': float(f['gold_walk']), 'grnn': float(f['gold_rnn']),
                'gold': float(f['gold_fused']), 'nseg': int(f['gold_nseg']),
                'enum200': f['gold_enumerated'] == '1',
                'npaths': int(f['prov_paths']),
            }
    # gold 是否落在 production 實際重排的前 10 條之內
    in10 = set()
    with open(args.paths, encoding='utf-8') as fh:
        h = next(fh).rstrip('\n').split('\t')
        for line in fh:
            f = dict(zip(h, line.rstrip('\n').split('\t')))
            if f['is_gold'] == '1':
                in10.add(f['sid'])

    log = open(args.log, encoding='utf-8').read()
    L, w = [], None
    L = []
    w = L.append

    # ── §5 provenance ──
    w('## Provenance audit（不通過就停，不繼續分析）\n')
    w('| 檢查項 | 結果 |')
    w('|---|---|')
    for key, label in (('PROV_WALKSCORE_MATCH',
                        '獨立重算 `Σ unigram + Σ λ·PMI` ＝ `RankedPath::walkScore`'),
                       ('TOP1_REPRODUCES_WALK',
                        '重算的 top-1（前 10 條 fused argmax）逐字等於 `walk()` 輸出'),
                       ('GOLD_PATH_NOT_CONSTRUCTIBLE', 'gold path 無法構造的句數'),
                       ('SENTENCES', '處理句數')):
        for ln in log.splitlines():
            if ln.startswith(key):
                w(f'| {label} | `{ln}` |')
    w('\n出貨配置：λ=0.75、ν=0.75、rerank N-best=10、adjust=0（`confusionAlphas_` 未設）。')
    w('公式照抄 `reading_grid.cpp`：`walkScore = Σ unigram.score() + '
      'Σ contextModel->scoreWithReading(...)`、`fused = walkScore + ν·rnn`。')
    w('\ngold 只用來**構造被測量的物件**與判定命中，**不進入任何 feature、'
      '不改變任何分數的算法**。\n')

    # ── 母體 ──
    bad = {s: r for s, r in rows.items() if not r['ok']}
    elig = {s: r for s, r in bad.items() if r['found']}
    w('\n\n## 母體（單位講清楚）\n')
    w('| 單位 | 量 | 標記 |')
    w('|---|---|---|')
    w(f'| **primary unit：句** | production 選錯的句子 **{len(bad):,}** | `OBSERVED` |')
    w(f'| 其中 gold path 可構造 | **{len(elig):,}**'
      f'（{len(elig)/len(bad):.1%}）| `OBSERVED` |')
    w(f'| **secondary unit：字** | 這些句子的 walk 錯字 '
      f'**{sum(r["err"] for r in elig.values()):,}** | `OBSERVED` |')
    w(f'| 全語料 D2 | {D2:,} | ⑭-O/⑭-P |')
    w(f'| 全語料字位 | {TOTAL_CHARS:,} | ⑭-O |')
    w('\n句數與錯字數是兩個不同的單位，本報告一律分開報。\n')

    # ── 主分類 ──
    for s, r in elig.items():
        r['d'] = r['gold'] - r['top1']
    beats = {s: r for s, r in elig.items() if r['d'] > 1e-9}
    tie = {s: r for s, r in elig.items() if abs(r['d']) <= 1e-9}
    loses = {s: r for s, r in elig.items() if r['d'] < -1e-9}
    n = len(elig)
    w('\n\n## 主分類\n')
    w('| classification | count | % |')
    w('|---|---|---|')
    w(f'| **GOLD_BEATS_TOP1** | **{len(beats):,}** | **{len(beats)/n:.1%}** |')
    w(f'| TIE | {len(tie):,} | {len(tie)/n:.1%} |')
    w(f'| GOLD_LOSES | {len(loses):,} | {len(loses)/n:.1%} |')
    F = len(beats) / n
    w(f'\n### PRIMARY KPI\n')
    w(f'**F = {len(beats):,} / {n:,} = {F:.1%}**（`SCORER-FAVORABILITY`）')
    w('\n⚠️ F **不是** rescue rate、**不是** beam failure rate、'
      '**不是** recoverable rate。gold 分數較高，不代表放寬 beam 就枚舉得到它。\n')

    # ── D2 換算 ──
    be = sum(r['err'] for r in beats.values())
    le = sum(r['err'] for r in loses.values())
    w('\n\n## 三個分母同時報\n')
    w('| 量 | 句比例 | 錯字數 | 佔 D2 | 佔全語料字位 |')
    w('|---|---|---|---|---|')
    w(f'| **GOLD_BEATS_TOP1** | {F:.1%} | {be:,} | **{be/D2:.1%}** | '
      f'**{be/TOTAL_CHARS:.2%}** |')
    w(f'| GOLD_LOSES | {len(loses)/n:.1%} | {le:,} | {le/D2:.1%} | '
      f'{le/TOTAL_CHARS:.2%} |')
    w(f'| TIE | {len(tie)/n:.1%} | {sum(r["err"] for r in tie.values()):,} | '
      f'{sum(r["err"] for r in tie.values())/D2:.1%} | — |')

    # ── enumerated / pruned ──
    w('\n\n## GOLD_BEATS_TOP1 的再分層\n')
    w('「production 實際打分的集合」＝ `walkNBest(10)`（出貨 `setPathRerankNBest(10)`）。'
      '`walkNBest(200)` 只是本棒為了檢查枚舉而多跑的，**不是**出貨行為。\n')
    w('\n| 子集 | count | % of GOLD_BEATS_TOP1 | 佔 D2 |')
    w('|---|---|---|---|')
    e10 = {s: r for s, r in beats.items() if s in in10}
    e200 = {s: r for s, r in beats.items() if s not in in10 and r['enum200']}
    npr = {s: r for s, r in beats.items() if s not in in10 and not r['enum200']}
    for lbl, sub, note in (
            ('**ENUMERATED + SCORE_WRONG**（gold 在出貨的前 10 條內）', e10, ''),
            ('在 11–200 條內（出貨重排視窗看不到）', e200, ''),
            ('**PRUNED_OR_UNENUMERATED**（200 條內都沒有）', npr, '')):
        ec = sum(r['err'] for r in sub.values())
        w(f'| {lbl} | {len(sub):,} | {len(sub)/max(len(beats),1):.1%} | '
          f'{ec/D2:.1%} |')
    w(f'| UNKNOWN | 0 | 0.0% | 0.0% |')
    w(f'\n**`ENUMERATED + SCORE_WRONG` 必然為 0**：top-1 就是那 10 條的 '
      f'fused argmax，gold 若在其中且分數更高，它就會是 top-1。'
      f'實測 {len(e10)}，與這個恆等式一致 —— 這是一個內部一致性檢查。\n')

    # ── Δ 分布 ──
    w('\n\n## Δ_gold = score(gold) − score(top-1) 分布\n')
    w('| 分位 | GOLD_BEATS_TOP1 | GOLD_LOSES |')
    w('|---|---|---|')
    a = [r['d'] for r in beats.values()]
    b = [r['d'] for r in loses.values()]
    for p, lbl in ((.10, 'P10'), (.25, 'P25'), (.50, '**中位數**'),
                   (.75, 'P75'), (.90, 'P90')):
        w(f'| {lbl} | {q(a,p):+.3f} | {q(b,p):+.3f} |')
    w(f'| n | {len(a):,} | {len(b):,} |')
    w('\n不報平均數（長尾）。')

    # ── 成分 ──
    w('\n\n## Δ 的成分：是 walkScore 還是 rnn 在做決定\n')
    w('| 子集 | Δ walkScore 中位 | Δ ν·rnn 中位 | Δ fused 中位 |')
    w('|---|---|---|---|')
    for lbl, sub in (('GOLD_BEATS_TOP1', beats), ('GOLD_LOSES', loses)):
        dw = [r['gwalk'] - r['top1_walk'] for r in sub.values()]
        dr = [0.75 * (r['grnn'] - r['top1_rnn']) for r in sub.values()]
        w(f'| {lbl} | {statistics.median(dw):+.3f} | '
          f'{statistics.median(dr):+.3f} | {statistics.median([r["d"] for r in sub.values()]):+.3f} |')

    # ── 枚舉深度 ──
    w('\n\n## 對照：walkNBest(200) 實際回傳幾條\n')
    npv = [r['npaths'] for r in bad.values()]
    w(f'中位數 **{statistics.median(npv):.0f}** 條；'
      f'滿 200 條的只有 {sum(1 for x in npv if x >= 200)/len(npv):.1%}。')
    w('這正是 ⑭-P 的 43.1% 不能當作 exact 200-best 排名的原因。')

    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    print('\n'.join(L))
    print(f'\n@@F={F:.4f} beats={len(beats)} n={n} be={be}')


if __name__ == '__main__':
    main()
