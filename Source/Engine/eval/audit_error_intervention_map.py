#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棒⑭-O：把 D2 的 3,192 個字級錯誤，按「錯在哪一層」與「有沒有可操作介入點」重分類。

**純分析。不訓練、不改 production、不跑正式 test、不新增人工標註。**

## 這一支跟 ⑭-M 的差別

⑭-M 的分類是**候選中心**的（金標在不在該節點候選裡）。
它答不出一件事：金標不在候選裡的那 578 個，到底是
「詞庫根本沒有這個字」還是「詞庫有、只是這條路徑的斷詞讓它選不到」。
這兩者要投的工程完全不同（補詞庫 vs 改路徑搜尋）。

本檔用 `bin/lexicon_probe` 直接查詞庫來切開這一刀：

    金標字在該字位的**單音節讀音**下查得到？
      是 → 詞庫有這個字，是**斷詞／路徑**沒走到 → PATH/SEG
      否 → **詞庫缺口** → LEXICON

因為 ReadingGrid 對每一個有 unigram 的跨度都會建節點，
「單音節查得到」就等於「lattice 裡存在一個含金標字的單字節點」——
所以 PATH/SEG 這一類**不需要動詞庫就有機會修**，這是一個可操作的判斷。

## 分類（互斥，先命中先算）

* `NODE`    該 walk 節點的候選裡就有金標跨度 → 換一次節點值即修好
* `PATH/SEG` 金標跨度不在該節點候選，但金標字在單音節讀音下查得到
             → lattice 裡有，是斷詞／路徑沒選它
* `LEXICON` 連單音節讀音都查不到金標字 → 詞庫缺口（或語料讀音本身有問題）
* `UNKNOWN` 資料不足以判定

⚠️ 本 dump 是 **walk 層**，不含 `ParticleRuleDisambiguator`。
   的／得 那一類在出貨路徑上會再被規則層處理，**本檔的數字與 production NOT COMPARABLE**。

用法：
  python3 audit_error_intervention_map.py --nodes <all-nodes.tsv> \\
      --items <自然驗證集.jsonl> --lex <lex.tsv> --out <報告片段.md>
"""

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_full_corpus_error_map import SIX, SIX_CHARS, build, load_nodes  # noqa

RULE_CHARS = set('的得地')     # ParticleRuleDisambiguator 的作用範圍


def load_lex(path):
    out = {}
    with open(path, encoding='utf-8') as fh:
        next(fh)
        for line in fh:
            f = line.rstrip('\n').split('\t')
            if len(f) >= 2:
                out[f[0]] = set(f[1].split('|')) if f[1] else set()
            elif f:
                out[f[0]] = set()
    return out


def classify(e, lex):
    if e['gold_in_cands']:
        return 'NODE'
    syl = e.get('syl')
    if syl is None or syl not in lex:
        return 'UNKNOWN'
    return 'PATH/SEG' if e['gold'] in lex[syl] else 'LEXICON'


def main():
    ap = argparse.ArgumentParser()
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
    errs, tot_chars, tot_sents, skipped = build(load_nodes(args.nodes), meta)

    for e in errs:
        m = meta[e['sid']]
        syl = m['full_reading'].split('-')
        e['syl'] = syl[e['pos']] if len(syl) == len(m['sentence']) else None
        e['family'] = classify(e, lex)
        e['isolated'] = e['run_len'] == 1
        e['six'] = e['gold'] in SIX_CHARS
        e['rule'] = e['gold'] in RULE_CHARS or e['chosen'] in RULE_CHARS

    N = len(errs)
    out, w = [], None
    L = []
    w = L.append

    w('## D2 的三層介入分類（OBSERVED）\n')
    w(f'母體：{tot_sents:,} 句 / {tot_chars:,} 字位 / **{N:,} 個錯字**'
      f'（略過 {skipped} 句）。walk 層，不含規則層。\n')
    w('\n| 家族 | 錯字 | 佔 D2 | 其中孤立 | 介入點 | 要不要動詞庫 |')
    w('|---|---|---|---|---|---|')
    fam = collections.Counter(e['family'] for e in errs)
    desc = {
        'NODE': ('節點內重排（換該節點的值）', '否'),
        'PATH/SEG': ('斷詞／路徑搜尋（字在 lattice 裡，只是沒選到）', '**否**'),
        'LEXICON': ('候選生成／詞庫', '**是**'),
        'UNKNOWN': ('—', '—'),
    }
    for k in ('NODE', 'PATH/SEG', 'LEXICON', 'UNKNOWN'):
        if not fam[k]:
            continue
        iso = sum(1 for e in errs if e['family'] == k and e['isolated'])
        w(f'| **{k}** | {fam[k]:,} | {fam[k]/N:.1%} | {iso:,} | '
          f'{desc[k][0]} | {desc[k][1]} |')

    ps = fam['PATH/SEG']
    w(f'\n**關鍵新發現**：⑭-M 報「金標不在候選」578 個，本棒切開後 '
      f'**{ps} 個（{ps/N:.1%} of D2）的金標字其實在詞庫裡** —— '
      f'lattice 有這個字，是斷詞／路徑沒走到。**這一類不必動詞庫。**')
    w(f'真正的詞庫缺口只有 **{fam["LEXICON"]} 個（{fam["LEXICON"]/N:.1%} of D2）**。\n')

    # ── NODE 再拆 ──
    node = [e for e in errs if e['family'] == 'NODE']
    w('\n\n## NODE 家族再拆（誰把它選錯的）\n')
    w('| 子類 | 錯字 | 佔 NODE | 佔 D2 | 判讀 |')
    w('|---|---|---|---|---|')
    sub = {
        '引擎選了 unigram 第一名（chosen_rank=0）': lambda e: e['chosen_rank'] == 0,
        '引擎沒選第一名（路徑分數推翻了詞頻序）': lambda e: e['chosen_rank'] > 0,
    }
    for k, f in sub.items():
        s = [e for e in node if f(e)]
        note = ('詞頻先驗／語言模型問題 —— 節點重排要對抗的是先驗'
                if '第一名（chosen' in k else
                '路徑層已經動過手，且動錯了 —— 路徑分數是嫌疑人')
        w(f'| {k} | {len(s):,} | {len(s)/len(node):.1%} | {len(s)/N:.1%} | {note} |')
    w('\n金標在候選中的名次（NODE 家族）：')
    rk = collections.Counter(min(e['gold_rank'], 5) for e in node)
    w('\n| gold_rank | 錯字 | 佔 NODE |')
    w('|---|---|---|')
    for k in sorted(rk):
        w(f'| {k if k < 5 else "≥5"} | {rk[k]:,} | {rk[k]/len(node):.1%} |')

    # ── 孤立 vs 連鎖 × 家族 ──
    w('\n\n## 規模 × 介入可行性（兩個維度分開看）\n')
    w('| 家族 | 孤立單字錯 | 連鎖錯 | 合計 | 已證實的介入 | 證據強度 |')
    w('|---|---|---|---|---|---|')
    ev = {
        'NODE': ('方向專屬 expert：⑭-K 實測 system 貢獻 0.082% of D2；'
                 '通用 expert：⑭-N NO-GO', '**強（兩條路都測過）**'),
        'PATH/SEG': ('無直接實驗。已知 O1=97.3%、O3=97.7%（N-best 擴張已耗盡）',
                     '弱（只有 oracle 上界）'),
        'LEXICON': ('無實驗', '**UNKNOWN**'),
        'UNKNOWN': ('—', '—'),
    }
    for k in ('NODE', 'PATH/SEG', 'LEXICON', 'UNKNOWN'):
        if not fam[k]:
            continue
        i1 = sum(1 for e in errs if e['family'] == k and e['isolated'])
        w(f'| {k} | {i1:,} | {fam[k]-i1:,} | {fam[k]:,} | {ev[k][0]} | {ev[k][1]} |')

    # ── 六組內外 ──
    w('\n\n## 六組內 / 六組外 × 家族\n')
    w('| | NODE | PATH/SEG | LEXICON | 合計 |')
    w('|---|---|---|---|---|')
    for lbl, f in (('六組字', lambda e: e['six']), ('**六組以外**', lambda e: not e['six'])):
        s = [e for e in errs if f(e)]
        cells = [str(sum(1 for e in s if e['family'] == k))
                 for k in ('NODE', 'PATH/SEG', 'LEXICON')]
        w(f'| {lbl} | ' + ' | '.join(cells) + f' | {len(s):,} |')

    # ── 規則層 ──
    ru = [e for e in errs if e['rule']]
    w(f'\n\n## 規則層（的／得／地）\n')
    w(f'涉及 的／得／地 的錯字 **{len(ru)}**（{len(ru)/N:.1%} of D2）。')
    w('本 dump **不含** `ParticleRuleDisambiguator`，出貨路徑會再處理這一批。')
    w('**因此這 %d 個與 production NOT COMPARABLE**，不列入 ROI 排序的可爭取量。'
      % len(ru))

    # ── 連鎖錯（整句解碼錯的 D2 版）──
    w('\n\n## 連鎖錯（整句解碼錯的 D2 版本）\n')
    run = [e for e in errs if not e['isolated']]
    w(f'連鎖錯（run ≥ 2）共 **{len(run):,}**（{len(run)/N:.1%} of D2）。'
      f'⑭-L 的「整句解碼錯 209」是 **D1′** 上的量，NOT COMPARABLE。\n')
    w('\n| 連鎖錯的家族 | 錯字 | 佔連鎖錯 | 判讀 |')
    w('|---|---|---|---|')
    for k in ('NODE', 'PATH/SEG', 'LEXICON', 'UNKNOWN'):
        c = sum(1 for e in run if e['family'] == k)
        if not c:
            continue
        note = {'NODE': '**候選裡就有正解** —— 換節點值即可，不必改解碼',
                'PATH/SEG': '字在詞庫但斷詞沒走到 —— 這才是真正的解碼問題',
                'LEXICON': '詞庫缺口', 'UNKNOWN': '—'}[k]
        w(f'| {k} | {c:,} | {c/len(run):.1%} | {note} |')
    nr = sum(1 for e in run if e['family'] == 'NODE')
    w(f'\n**連鎖錯裡有 {nr:,}（{nr/len(run):.1%}）其實是 NODE 家族** ——'
      f'「連續錯字」不等於「整句解碼壞掉」，其中大部分每一個位置的正解都還在候選裡。')

    # ── PATH/SEG 細看 ──
    w('\n\n## PATH/SEG 家族細看\n')
    pss = [e for e in errs if e['family'] == 'PATH/SEG']
    w('| 該錯字所在節點的 span | 錯字 | 佔 PATH/SEG |')
    w('|---|---|---|')
    sp = collections.Counter(e['span'] for e in pss)
    for k in sorted(sp):
        if sp[k] < 5 and k > 3:
            continue
        w(f'| {k} | {sp[k]:,} | {sp[k]/len(pss):.1%} |')
    one = sum(1 for e in pss if e['n_cands'] == 1)
    w(f'\n其中該節點**只有一個候選**（完全沒得選）的有 **{one:,}**'
      f'（{one/len(pss):.1%}）—— 這些一定要改斷詞才有機會。')

    # ── 詞庫缺口細看 ──
    lx = [e for e in errs if e['family'] == 'LEXICON']
    if lx:
        w('\n\n## LEXICON 家族細看（Top 15 缺的字）\n')
        w('| 金標字 | 錯字數 | 讀音（示例）|')
        w('|---|---|---|')
        for ch, n in collections.Counter(e['gold'] for e in lx).most_common(15):
            syl = next((e['syl'] for e in lx if e['gold'] == ch), '?')
            w(f'| {ch} | {n} | {syl} |')

    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
