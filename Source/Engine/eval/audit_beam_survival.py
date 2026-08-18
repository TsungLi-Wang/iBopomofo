#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棒⑮ 工作流 A：beam / pruning bounded attribution。

**只做 attribution。不修改 production、不改 `kNBestHypK`、不改任何權重。**
放寬 K 只發生在 `bin/beam_survival_audit` 的記憶體裡。

回答 A 的六個問題：
  1. gold path 是否在 decoding 的某個中間 stage 曾經存在
  2. 若存在，最後在哪一個 stage 被剪掉
  3. 若不存在，是在哪一個 beam state 被排除
  4. 造成多少 error
  5. 最多佔 D2 / 全語料字位的多少
  6. 放寬 pruning 的成本與理論可救空間

事前判準（資源分流門檻，非統計顯著性門檻）：
  可救空間 < 1% 全語料字位（< 746 字）→ SEARCH 降為次要
  > 1% 且 latency 成本合理           → 保留為候選 intervention

用法：
  python3 audit_beam_survival.py --beam <beam.tsv> --log <beam.log> --out <片段.md>
"""

import argparse
import collections
import statistics

D2 = 3192
TOTAL_CHARS = 74649
THRESH_PCT = 0.01
PROD_K = 8


def q(v, p):
    return sorted(v)[min(len(v) - 1, int(p * len(v)))] if v else float('nan')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--beam', required=True)
    ap.add_argument('--log', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    rows = collections.defaultdict(dict)
    with open(args.beam, encoding='utf-8') as fh:
        head = next(fh).rstrip('\n').split('\t')
        for line in fh:
            f = dict(zip(head, line.rstrip('\n').split('\t')))
            rows[f['sid']][int(f['K'])] = {
                'ok': f['engine_correct'] == '1',
                'err': int(f['walk_err']),
                'alive': f['gold_alive'] == '1',
                'last': int(f['last_alive_pos']),
                'len': int(f['sent_len']),
                'rank': int(f['gold_walk_rank']),
                'win': f['gold_in_window'] == '1',
                'pick': int(f['pick_err']),
                'edges': int(f['edges']),
            }
    Ks = sorted({k for v in rows.values() for k in v})
    log = open(args.log, encoding='utf-8').read()

    L = []
    w = L.append
    w('## A-0 Provenance\n')
    w('| 檢查項 | 結果 |')
    w('|---|---|')
    for ln in log.splitlines():
        if ln.startswith(('SENTENCES', 'K8_REPRODUCES_WALK')):
            w(f'| `{ln.split()[0]}` | `{ln}` |')
    w('\n本工具自行複製 `walkNBest()` 的 beam DP（`dp[pos][lastWord]` 每格留 K 個）。'
      '**K=8 必須逐句重現出貨輸出**。')
    w('已知偏差：引擎是**逐筆插入即裁切**，本工具是**累積後裁切**，'
      '在同分時保留的集合可能不同；另外本工具未複製 `forceTopUnigramOnly`'
      '（標點／字母讀音）與 node override —— 本語料無此類讀音。')
    w('\n**以下所有結論一律限制在「K=8 能重現出貨輸出」的句子上。**\n')

    ok8 = {s: v for s, v in rows.items()
           if PROD_K in v and v[PROD_K]['pick'] == v[PROD_K]['err']}
    bad = {s: v for s, v in ok8.items() if not v[PROD_K]['ok']}
    w(f'\n可用句子 **{len(ok8):,}**／全部 {len(rows):,}'
      f'（{len(ok8)/len(rows):.1%}）；其中 production 選錯的 **{len(bad):,}** 句。\n')

    # ── A-1/A-2/A-3 gold 存活與死亡階段 ──
    w('\n\n## A-1～A-3 gold path 在 beam 裡活到哪裡（K=8，出貨值）\n')
    alive = {s: v for s, v in bad.items() if v[PROD_K]['alive']}
    dead = {s: v for s, v in bad.items() if not v[PROD_K]['alive']}
    w('| 狀態 | 句數 | % | 錯字 |')
    w('|---|---|---|---|')
    w(f'| gold 前綴**活到終點** | {len(alive):,} | {len(alive)/len(bad):.1%} | '
      f'{sum(v[PROD_K]["err"] for v in alive.values()):,} |')
    w(f'| gold 前綴**中途被剪掉** | {len(dead):,} | {len(dead)/len(bad):.1%} | '
      f'{sum(v[PROD_K]["err"] for v in dead.values()):,} |')
    frac = [v[PROD_K]['last'] / max(v[PROD_K]['len'], 1) for v in dead.values()
            if v[PROD_K]['last'] >= 0]
    never = sum(1 for v in dead.values() if v[PROD_K]['last'] < 0)
    w(f'\n被剪掉的那些，gold 前綴最後存活的位置（佔句長比例）：')
    w('\n| 分位 | 位置 / 句長 |')
    w('|---|---|')
    for p, lbl in ((.10, 'P10'), (.25, 'P25'), (.50, '**中位數**'),
                   (.75, 'P75'), (.90, 'P90')):
        w(f'| {lbl} | {q(frac,p):.0%} |')
    w(f'\n從未建立過 gold 前綴的句數：**{never}**'
      f'（＝第一個字就沒進 beam）。')
    w('\n**A-3 的答案**：被排除的 beam state 是 '
      '`dp[位置][該位置的最後一個詞]` —— gold 前綴在該格的分數排不進前 K。')

    # ── A-4/A-5 錯誤量與兩個分母 ──
    w('\n\n## A-4／A-5 放寬 K 的理論可救空間\n')
    w('| K | gold 活到終點 | gold 進得了出貨的前 10 條視窗 | rescue 字 | '
      'damage 字 | **net 字** | 佔 D2 | 佔全語料字位 |')
    w('|---|---|---|---|---|---|---|---|')
    best = None
    for k in Ks:
        sub = [v[k] for v in ok8.values() if k in v]
        bd = [v[k] for v in bad.values() if k in v]
        r = sum(max(0, x['err'] - x['pick']) for x in sub)
        d = sum(max(0, x['pick'] - x['err']) for x in sub)
        n = r - d
        av = sum(1 for x in bd if x['alive'])
        wi = sum(1 for x in bd if x['win'])
        mark = ' ←出貨' if k == PROD_K else ''
        w(f'| {k}{mark} | {av:,}（{av/len(bd):.1%}）| {wi:,}（{wi/len(bd):.1%}）| '
          f'{r:,} | {d:,} | **{n:+,}** | {n/D2:+.1%} | {n/TOTAL_CHARS:+.3%} |')
        if best is None or n > best[1]:
            best = (k, n, r, d)
    w('\n⚠️ 這些是**放寬 beam 後、仍用現行出貨打分公式**重新選一次的結果，'
      '`COUNTERFACTUAL / OFFLINE ONLY`，不是 production 改動的預測值。')

    # ── A-6 成本 ──
    w('\n\n## A-6 成本（DP 邊評估次數，latency 的代理指標）\n')
    w('| K | 每句中位 edges | 相對 K=8 |')
    w('|---|---|---|')
    base = statistics.median([v[PROD_K]['edges'] for v in ok8.values()])
    for k in Ks:
        m = statistics.median([v[k]['edges'] for v in ok8.values() if k in v])
        w(f'| {k} | {m:,.0f} | **{m/base:.2f}×** |')
    w('\nDP 邊數與 K 近似線性。實際 latency 還要加上 N-best 重排時的 RNN 呼叫，'
      '但重排視窗仍是 10 條，**RNN 成本不隨 K 增加**。')

    # ── 判準 ──
    thr = THRESH_PCT * TOTAL_CHARS
    w('\n\n## 事前判準\n')
    w(f'門檻：可救空間 **{THRESH_PCT:.0%} 全語料字位 = {thr:.0f} 字**'
      f'（資源分流門檻，非統計顯著性門檻）。\n')
    w(f'\n實測最佳：**K={best[0]}，net {best[1]:+,} 字**'
      f'（rescue {best[2]:,}／damage {best[3]:,}）'
      f'＝ D2 的 {best[1]/D2:.1%}、全語料字位的 **{best[1]/TOTAL_CHARS:.3%}**。\n')
    verdict = ('**> 1% → 保留為候選 intervention**' if best[1] > thr
               else '**< 1% → SEARCH 降為次要，不再作為第一 product intervention**')
    w(f'\n→ {verdict}')

    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    print('\n'.join(L))
    print(f'\n@@bestK={best[0]} net={best[1]} pct={best[1]/TOTAL_CHARS:.5f}')


if __name__ == '__main__':
    main()
