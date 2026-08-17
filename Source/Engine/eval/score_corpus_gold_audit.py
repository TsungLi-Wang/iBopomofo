#!/usr/bin/env python3
# 人工核驗結果計分：語料金標可不可信？引擎準不準？兩件事完全分開算。
#
# `corpus_gold_correct` = (corpus_gold == human_gold)
# `engine_correct`      = (engine_choice == human_gold)
# 兩欄都由這支自動算，**不讓人工自己填**（自己填會不自覺地往一邊靠）。
#
# ⚠️ 抽樣是刻意不按母體比例的（小方向被過抽到 100%）。所以：
#   * 逐格數字直接看
#   * 任何「整體」數字一律用母體比例**回加權**再報，並同時附上未加權值
# 不回加權就直接報整體準確率，等於拿一份刻意偏斜的樣本冒充母體估計。
#
# 用法：
#   python3 score_corpus_gold_audit.py --file <corpus-gold-audit.tsv> \
#       --meta <sampling-meta.json> [--out <報告.md>]

import argparse
import collections
import json
import sys

GROUP = ['作', '做', '坐', '座']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', required=True)
    ap.add_argument('--meta', required=True)
    ap.add_argument('--out', default='')
    args = ap.parse_args()

    with open(args.file, encoding='utf-8') as fh:
        lines = fh.read().rstrip('\n').split('\n')
    header = lines[0].split('\t')
    rows = [dict(zip(header, ln.split('\t'))) for ln in lines[1:]]
    meta = json.load(open(args.meta, encoding='utf-8'))
    pop_dir = meta['population_dir']
    pop_total = meta['population_total']

    filled = [r for r in rows if r.get('human_gold')]
    judged = [r for r in filled if r['human_gold'] in GROUP]
    uncertain = [r for r in filled if r['human_gold'] == 'UNCERTAIN']
    if not filled:
        sys.exit('還沒有任何人工核驗結果 —— 先跑 annotate_corpus_gold.py')

    out = []
    w = out.append
    w('# 語料金標人工核驗結果（棒⑭-A-1）\n')
    w(f'待核 {len(rows)} 筆；已核 {len(filled)} 筆'
      f'（可判定 {len(judged)}、判不出來 {len(uncertain)}）\n')
    if len(filled) < len(rows):
        w(f'\n> ⚠️ **尚未核完**（{len(filled)}/{len(rows)}），'
          f'以下數字只是進度快照，不得當結論。\n')

    # ── G. Corpus gold accuracy ──
    w('\n## G. Corpus gold accuracy（語料金標對不對）\n')
    w('| 切面 | 已判定 | 金標正確 | 準確率 |')
    w('|---|---|---|---|')

    def acc(items, key):
        n = len(items)
        ok = sum(1 for r in items if r[key] == r['human_gold'])
        return n, ok, (100 * ok / n if n else 0)

    n, ok, a = acc(judged, 'corpus_gold')
    w(f'| **整體（未加權）** | {n} | {ok} | {a:.1f}% |')
    for e in GROUP:
        sub = [r for r in judged if r['engine_choice'] == e]
        n, ok, a = acc(sub, 'corpus_gold')
        if n:
            w(f'| 引擎選「{e}」 | {n} | {ok} | {a:.1f}% |')
    for g in GROUP:
        sub = [r for r in judged if r['corpus_gold'] == g]
        n, ok, a = acc(sub, 'corpus_gold')
        if n:
            w(f'| 語料金標＝「{g}」 | {n} | {ok} | {a:.1f}% |')

    # 母體回加權
    num = den = 0.0
    for e in GROUP:
        for g in GROUP:
            key = f'{e}→{g}'
            sub = [r for r in judged
                   if r['engine_choice'] == e and r['corpus_gold'] == g]
            if not sub or not pop_dir.get(key):
                continue
            rate = sum(1 for r in sub if r['corpus_gold'] == r['human_gold']) / len(sub)
            num += rate * pop_dir[key]
            den += pop_dir[key]
    if den:
        w(f'\n**母體回加權後的語料金標準確率：{100 * num / den:.1f}%**'
          f'（涵蓋母體 {den:,.0f}/{pop_total:,} 個節點）\n')

    # ── H. Engine accuracy ──
    w('\n## H. Engine accuracy（引擎對不對）\n')
    w('| 切面 | 已判定 | 引擎正確 | 準確率 |')
    w('|---|---|---|---|')
    n, ok, a = acc(judged, 'engine_choice')
    w(f'| **整體（未加權）** | {n} | {ok} | {a:.1f}% |')
    for e in GROUP:
        sub = [r for r in judged if r['engine_choice'] == e]
        n, ok, a = acc(sub, 'engine_choice')
        if n:
            w(f'| 引擎選「{e}」 | {n} | {ok} | {a:.1f}% |')
    num = den = 0.0
    for e in GROUP:
        for g in GROUP:
            key = f'{e}→{g}'
            sub = [r for r in judged
                   if r['engine_choice'] == e and r['corpus_gold'] == g]
            if not sub or not pop_dir.get(key):
                continue
            rate = sum(1 for r in sub if r['engine_choice'] == r['human_gold']) / len(sub)
            num += rate * pop_dir[key]
            den += pop_dir[key]
    if den:
        w(f'\n**母體回加權後的引擎準確率：{100 * num / den:.1f}%**\n')

    # ── Directional label accuracy ──
    w('\n## 逐方向：語料金標對不對\n')
    w('| 格 | 母體 | 已判定 | 金標正確 | 金標錯 | 判不出來 | 金標準確率 |')
    w('|---|---|---|---|---|---|---|')
    for e in GROUP:
        for g in GROUP:
            key = f'{e}→{g}'
            if not pop_dir.get(key):
                continue
            sub = [r for r in judged
                   if r['engine_choice'] == e and r['corpus_gold'] == g]
            unc = sum(1 for r in uncertain
                      if r['engine_choice'] == e and r['corpus_gold'] == g)
            n = len(sub)
            good = sum(1 for r in sub if r['corpus_gold'] == r['human_gold'])
            tag = key + ('（引擎選對）' if e == g else '')
            rate = f'{100 * good / n:.1f}%' if n else '—'
            w(f'| {tag} | {pop_dir[key]:,} | {n} | {good} | {n - good} | '
              f'{unc} | {rate} |')

    # ── Gold distribution 三方比較 ──
    w('\n## Gold distribution：訓練母體 vs 抽樣 vs 人工\n')
    pop_gold = meta['population_gold']
    smp_gold = collections.Counter(r['corpus_gold'] for r in judged)
    hum_gold = collections.Counter(r['human_gold'] for r in judged)
    # 人工金標也回加權到母體
    wt = collections.Counter()
    for e in GROUP:
        for g in GROUP:
            key = f'{e}→{g}'
            sub = [r for r in judged
                   if r['engine_choice'] == e and r['corpus_gold'] == g]
            if not sub or not pop_dir.get(key):
                continue
            for h in GROUP:
                share = sum(1 for r in sub if r['human_gold'] == h) / len(sub)
                wt[h] += share * pop_dir[key]
    wt_tot = sum(wt.values())
    w('| | 作 | 做 | 坐 | 座 |')
    w('|---|---|---|---|---|')
    pt = sum(pop_gold.values())
    w('| 訓練母體（語料金標） | ' + ' | '.join(
        f'{100 * pop_gold[c] / pt:.1f}%' for c in GROUP) + ' |')
    st = sum(smp_gold.values()) or 1
    w('| 抽樣樣本（語料金標） | ' + ' | '.join(
        f'{100 * smp_gold[c] / st:.1f}%' for c in GROUP) + ' |')
    ht = sum(hum_gold.values()) or 1
    w('| 抽樣樣本（人工金標） | ' + ' | '.join(
        f'{100 * hum_gold[c] / ht:.1f}%' for c in GROUP) + ' |')
    if wt_tot:
        w('| **人工金標（回加權到母體）** | ' + ' | '.join(
            f'{100 * wt[c] / wt_tot:.1f}%' for c in GROUP) + ' |')

    # ── I. 三向交叉表 ──
    w('\n## I. Engine × Corpus gold × Human gold\n')
    w('把「引擎錯了嗎」與「語料金標錯了嗎」完全分開。\n')
    w('| 引擎 | 語料金標 | 人工金標 | 筆數 | 引擎對？ | 語料金標對？ |')
    w('|---|---|---|---|---|---|')
    cross = collections.Counter(
        (r['engine_choice'], r['corpus_gold'], r['human_gold']) for r in judged)
    for (e, g, h), n in sorted(cross.items(), key=lambda x: -x[1]):
        w(f'| {e} | {g} | {h} | {n} | '
          f'{"✅" if e == h else "❌"} | {"✅" if g == h else "❌"} |')
    if uncertain:
        w(f'\n另有 {len(uncertain)} 筆判不出來（UNCERTAIN），不計入上表。')

    # 四象限摘要
    w('\n### 四象限摘要（可判定的樣本）\n')
    q = collections.Counter()
    for r in judged:
        q[(r['engine_choice'] == r['human_gold'],
           r['corpus_gold'] == r['human_gold'])] += 1
    w('| | 語料金標對 | 語料金標錯 |')
    w('|---|---|---|')
    w(f'| **引擎對** | {q[(True, True)]} | {q[(True, False)]} '
      f'← 引擎其實是對的，語料在騙訓練 |')
    w(f'| **引擎錯** | {q[(False, True)]} ← 真正該修的 | {q[(False, False)]} |')

    text = '\n'.join(out) + '\n'
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            fh.write(text)
    print(text)


if __name__ == '__main__':
    main()
