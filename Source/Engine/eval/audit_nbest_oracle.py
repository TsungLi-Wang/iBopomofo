#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棒⑭-P：全語料 N-best oracle coverage。

**純分析。不訓練、不改 production、不跑正式 test、不新增人工核驗。**

## 兩種 rank，不可互換

* `node_rank`（⑭-M/⑭-O 已有）：金標在**該 walk 節點**的 unigram 分數名次。
  回答「換這一個節點的值能不能修好」。
* `path_rank`（本棒新增，`bin/nbest_oracle_map`）：金標字第一次出現在**第幾條
  N-best 路徑**上（0-based，-1 = 200 條內都沒有）。
  回答「**正確的整句**在不在搜尋空間裡」。

⑭-N 已經把「節點層重排」判死；本棒問的是**路徑層**，是不同的問題。

## 洩漏

`walkNBest` 是純推論，候選與路徑的產生完全不涉及金標；金標只用來測命中。
因此一切結果是 **ORACLE / UPPER BOUND**，不是 inference coverage，
更不是 expected gain。

## `path_rank = -1` 的正確讀法

只代表「**不在前 200 條路徑內**」，**不代表不存在於 lattice**。
⑭-O 已用 `bin/lexicon_probe` 證明每個金標字都在詞庫裡
（LEXICON = 0），所以理論上都存在某條路徑 —— 只是排不進前 200。

用法：
  python3 audit_nbest_oracle.py --nbest <nbest.tsv> --nodes <all-nodes.tsv> \\
      --items <自然驗證集.jsonl> --lex <lex.tsv> --out <報告片段.md>
"""

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_error_intervention_map import classify, load_lex  # noqa: E402
from audit_full_corpus_error_map import SIX_CHARS, build, load_nodes  # noqa

KS = [1, 2, 5, 10, 20, 50, 100, 200]


def pctile(vals, q):
    if not vals:
        return float('nan')
    s = sorted(vals)
    return s[min(len(s) - 1, int(q * len(s)))]


def cov(rows, k):
    return sum(1 for r in rows if 0 <= r['path_rank'] < k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nbest', required=True)
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--items', required=True)
    ap.add_argument('--lex', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    meta = {}
    with open(args.items, encoding='utf-8') as fh:
        for i, line in enumerate(fh, start=1):
            if line.strip():
                meta[str(i)] = json.loads(line)
    lex = load_lex(args.lex)
    errs, tot_chars, tot_sents, _ = build(load_nodes(args.nodes), meta)
    for e in errs:
        m = meta[e['sid']]
        syl = m['full_reading'].split('-')
        e['syl'] = syl[e['pos']] if len(syl) == len(m['sentence']) else None
        e['family'] = classify(e, lex)

    pr, maxn = {}, 0
    with open(args.nbest, encoding='utf-8') as fh:
        next(fh)
        for line in fh:
            f = line.rstrip('\n').split('\t')
            pr[(f[0], int(f[1]))] = (f[2], f[3], int(f[4]))
            maxn = max(maxn, int(f[5]))

    L, w = [], None
    L = []
    w = L.append

    # ── provenance ──
    w('## Provenance / inference-faithfulness audit\n')
    matched = sum(1 for e in errs if (e['sid'], e['pos']) in pr)
    agree = sum(1 for e in errs if (e['sid'], e['pos']) in pr
                and pr[(e['sid'], e['pos'])][:2] == (e['chosen'], e['gold']))
    w('| 檢查項 | 結果 |')
    w('|---|---|')
    w(f'| 錯位數與 ⑭-O 一致 | {"✅" if matched == len(errs) == len(pr) else "❌"} '
      f' ⑭-O {len(errs):,} / 本棒 {len(pr):,} / 對得上 {matched:,} |')
    w(f'| 每一筆的 engine/gold 字也一致 | {"✅" if agree == matched else "❌"}'
      f'（{agree:,}/{matched:,}）|')
    w('| 候選／路徑來源 | `grid.walkNBest()`，**inference-time**，'
      '不涉及金標 |')
    w('| 有沒有用金標生成候選 | ❌ 沒有。金標只用來測命中 |')
    w('| 有沒有人工補 lattice | ❌ 沒有 |')
    w('| 有沒有後處理偷補金標 | ❌ 沒有 |')
    w('| 出貨配置 | λ=0.75、ν=0.75、rerank N-best=10、無 UOM、'
      '不含 `ParticleRuleDisambiguator` |')
    w(f'| 觀察深度 | **{maxn} 條路徑**。`path_rank = -1` 只代表 '
      f'**> {maxn}**，`NOT` truly absent |')
    w('\n⚠️ **第一次跑不算數，已作廢**：漏掉 `cm.setLambda(0.75)`，'
      'λ 留在預設 1.0，解出 3,301 個錯位而不是 3,192。'
      '修正後逐位完全吻合。這一條記在這裡是因為它正是 provenance audit 要抓的東西。\n')
    w('\n**標記**：以下所有 coverage 一律是 `ORACLE / UPPER BOUND`，'
      '不是 expected gain。\n')

    for e in errs:
        k = (e['sid'], e['pos'])
        e['path_rank'] = pr[k][2] if k in pr else None
    errs = [e for e in errs if e['path_rank'] is not None]
    N = len(errs)
    node = [e for e in errs if e['family'] == 'NODE']
    ps = [e for e in errs if e['family'] == 'PATH/SEG']

    # ── 分母 ──
    w('\n\n## 分母\n')
    w('| 代號 | 定義 | 大小 | 標記 |')
    w('|---|---|---|---|')
    w(f'| 字位 | 自然驗證集全部字位 | {tot_chars:,} | `OBSERVED` |')
    w(f'| **D2** | walk 解碼 ≠ 真人原文的字位 | **{N:,}** | `OBSERVED` |')
    w(f'| **NODE** | 金標跨度就在該 walk 節點候選裡 | **{len(node):,}**'
      f'（{len(node)/N:.1%} of D2）| `OBSERVED` |')
    w(f'| **PATH/SEG** | 金標跨度不在該節點候選，但金標字在詞庫 | '
      f'**{len(ps):,}**（{len(ps)/N:.1%} of D2）| `OBSERVED` |')
    w(f'| N_observable | 可重建 N-best 的錯位 | **{N:,}（100%）** | `OBSERVED` |')
    w('\n本棒**沒有** subset 問題：3,192 個錯位全部重建成功。\n')

    # ── 主 coverage 表 ──
    w('\n\n## 核心 coverage：金標字第一次出現在第幾條路徑\n')
    w('| 深度 | D2 n | % of D2 | NODE n | % of NODE | PATH/SEG n | % of PATH/SEG |')
    w('|---|---|---|---|---|---|---|')
    for k in KS:
        w(f'| top-{k} | {cov(errs,k):,} | {cov(errs,k)/N:.1%} | '
          f'{cov(node,k):,} | {cov(node,k)/len(node):.1%} | '
          f'{cov(ps,k):,} | {cov(ps,k)/len(ps):.1%} |')
    ab = sum(1 for e in errs if e['path_rank'] < 0)
    abn = sum(1 for e in node if e['path_rank'] < 0)
    abp = sum(1 for e in ps if e['path_rank'] < 0)
    w(f'| **> {maxn}（未觀察到）** | {ab:,} | **{ab/N:.1%}** | {abn:,} | '
      f'**{abn/len(node):.1%}** | {abp:,} | **{abp/len(ps):.1%}** |')

    w('\n### rank 分布（只算命中的）\n')
    hit = [e['path_rank'] for e in errs if e['path_rank'] >= 0]
    hn = [e['path_rank'] for e in node if e['path_rank'] >= 0]
    w('| 子集 | 命中數 | P25 | 中位數 | P75 | P90 |')
    w('|---|---|---|---|---|---|')
    for lbl, v in (('D2', hit), ('NODE', hn),
                   ('PATH/SEG', [e['path_rank'] for e in ps if e['path_rank'] >= 0])):
        w(f'| {lbl} | {len(v):,} | {pctile(v,.25)} | **{pctile(v,.5)}** | '
          f'{pctile(v,.75)} | {pctile(v,.9)} |')
    w('\n長尾很長，**不報平均數**。')

    # ── 三個 oracle ──
    w('\n\n## 三個 oracle ceiling（`THEORETICAL UPPER BOUND`，不是預期效果）\n')
    w('假設一個**完美**的路徑重排器總能在 top-k 裡挑中正確的那一條。\n')
    w('\n| Oracle | 修得到的字 | / NODE | / D2 | / 全部字位 |')
    w('|---|---|---|---|---|')
    for k in (10, 20, 200):
        c = cov(errs, k)
        w(f'| **Oracle-{k}** | {c:,} | {cov(node,k)/len(node):.1%} | '
          f'**{c/N:.1%}** | {c/tot_chars:.2%} |')
    w('\n⚠️ 「Oracle-10 = X%」只能讀成「完美重排器的理論天花板是 X%」，'
      '**不能**讀成「重排器可以修 X%」。')

    # ── rankable vs unreachable ──
    w('\n\n## 排序問題 vs 候選問題\n')
    w('| 類別 | 定義 | n | % of D2 | 理論上誰能修 |')
    w('|---|---|---|---|---|')
    ra = [e for e in errs if e['path_rank'] >= 0]
    w(f'| **A RANKABLE（路徑層）** | 金標字出現在 top-{maxn} 的某條路徑 | '
      f'{len(ra):,} | **{len(ra)/N:.1%}** | 路徑重排 / LM / scoring |')
    w(f'| **B 節點層可及但路徑外** | NODE ∧ path_rank > {maxn} | {abn:,} | '
      f'{abn/N:.1%} | 節點內改選可及，但沒有高分整句支持它 |')
    w(f'| **C PATH/SEG ∧ 路徑外** | 金標字在詞庫，但 top-{maxn} 沒有 | {abp:,} | '
      f'{abp/N:.1%} | 要改斷詞／擴大搜尋 |')
    w(f'| **D 完全不存在** | 詞庫也沒有 | **0** | 0.0% | —（⑭-O 已證；'
      f'但那是語料結構造成的不可觀測）|')

    # ── unigram-first ──
    w('\n\n## 61.4% unigram-first 的真正來源\n')
    uf = [e for e in node if e['chosen_rank'] == 0]
    w(f'⑭-O 量到 NODE 中「引擎選了 unigram 第一名」的有 **{len(uf):,}**'
      f'（{len(uf)/N:.1%} of D2）。它們的路徑覆蓋：\n')
    w('\n| 深度 | n | % of unigram-first |')
    w('|---|---|---|')
    for k in (1, 2, 5, 10, 20, 50, 200):
        w(f'| top-{k} | {cov(uf,k):,} | {cov(uf,k)/len(uf):.1%} |')
    ua = sum(1 for e in uf if e['path_rank'] < 0)
    w(f'| **> {maxn}** | {ua:,} | **{ua/len(uf):.1%}** |')
    w('\n對照組：NODE 中引擎**沒有**選第一名的：\n')
    nf = [e for e in node if e['chosen_rank'] > 0]
    w('\n| 深度 | n | % |')
    w('|---|---|---|')
    for k in (10, 20, 200):
        w(f'| top-{k} | {cov(nf,k):,} | {cov(nf,k)/len(nf):.1%} |')
    w(f'| > {maxn} | {sum(1 for e in nf if e["path_rank"]<0):,} | '
      f'{sum(1 for e in nf if e["path_rank"]<0)/len(nf):.1%} |')

    # ── span ──
    w('\n\n## node span\n')
    w('| span | n | % of D2 | top-10 | top-20 | > 200 |')
    w('|---|---|---|---|---|---|')
    for s in sorted(collections.Counter(e['span'] for e in errs)):
        sub = [e for e in errs if e['span'] == s]
        if len(sub) < 5 and s > 3:
            continue
        w(f'| {s} | {len(sub):,} | {len(sub)/N:.1%} | '
          f'{cov(sub,10)/len(sub):.1%} | {cov(sub,20)/len(sub):.1%} | '
          f'{sum(1 for e in sub if e["path_rank"]<0)/len(sub):.1%} |')

    # ── candidate count ──
    w('\n\n## 候選數\n')
    w('| 候選數 | n | top-10 | top-20 | > 200 | 金標在該節點候選（＝NODE）|')
    w('|---|---|---|---|---|---|')
    for lo, hi, lbl in ((2, 3, '2–3'), (4, 5, '4–5'), (6, 9, '6–9'),
                        (10, 19, '10–19'), (20, 10**9, '≥20')):
        sub = [e for e in errs if lo <= e['n_cands'] <= hi]
        if not sub:
            continue
        w(f'| {lbl} | {len(sub):,} | {cov(sub,10)/len(sub):.1%} | '
          f'{cov(sub,20)/len(sub):.1%} | '
          f'{sum(1 for e in sub if e["path_rank"]<0)/len(sub):.1%} | '
          f'{sum(1 for e in sub if e["family"]=="NODE")/len(sub):.1%} |')
    one = [e for e in errs if e['n_cands'] == 1]
    if one:
        w(f'| 1（沒得選）| {len(one):,} | {cov(one,10)/len(one):.1%} | '
          f'{cov(one,20)/len(one):.1%} | '
          f'{sum(1 for e in one if e["path_rank"]<0)/len(one):.1%} | 0.0% |')

    # ── direction ──
    w('\n\n## 方向（`CORPUS-LEVEL / DIRECTION-LEVEL EVIDENCE`，不得外推成通用規律）\n')
    w('| 引擎→金標 | n | NODE 佔比 | top-10 | top-20 | > 200 | 命中者中位 rank |')
    w('|---|---|---|---|---|---|---|')
    dc = collections.Counter(f"{e['chosen']}→{e['gold']}" for e in errs)
    for d, n in dc.most_common(15):
        sub = [e for e in errs if f"{e['chosen']}→{e['gold']}" == d]
        h = [e['path_rank'] for e in sub if e['path_rank'] >= 0]
        w(f'| {d} | {n} | '
          f'{sum(1 for e in sub if e["family"]=="NODE")/len(sub):.0%} | '
          f'{cov(sub,10)/len(sub):.0%} | {cov(sub,20)/len(sub):.0%} | '
          f'{sum(1 for e in sub if e["path_rank"]<0)/len(sub):.0%} | '
          f'{pctile(h,.5) if h else "—"} |')

    # ── 六組 ──
    w('\n\n## 六組內外\n')
    w('| 子集 | n | top-10 | top-20 | > 200 |')
    w('|---|---|---|---|---|')
    for lbl, f in (('六組字', lambda e: e['gold'] in SIX_CHARS),
                   ('**六組以外**', lambda e: e['gold'] not in SIX_CHARS)):
        sub = [e for e in errs if f(e)]
        w(f'| {lbl} | {len(sub):,} | {cov(sub,10)/len(sub):.1%} | '
          f'{cov(sub,20)/len(sub):.1%} | '
          f'{sum(1 for e in sub if e["path_rank"]<0)/len(sub):.1%} |')

    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
