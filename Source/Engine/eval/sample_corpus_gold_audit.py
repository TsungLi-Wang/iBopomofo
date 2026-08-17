#!/usr/bin/env python3
# 從**棒⑬實際用的訓練來源**抽出作做坐座節點，做成人工核驗清單。
#
# ## 這份要回答的問題
#
# 不是「引擎對不對」，是 **「語料金標（corpus gold）本身可不可信」**。
# 棒⑭-A 量到訓練來源與人工核驗語料的金標分布差很多
# （作 57.4% vs 30.3%、坐 3.4% vs 13.0%），現有資料分不出那是
# (a) PTT 原文本身寫錯、還是 (b) 抽樣造成的選擇偏差。只有人工核驗能分。
#
# ## 抽樣不是單純 random
#
# 目的是**診斷**，不是估計整體準確率。所以分層抽：
#   1. engine choice（作／做／坐／座）
#   2. engine == corpus gold vs engine != corpus gold
#   3. engine != gold 時再依 X→Y 方向分層
# 小方向全抽，大方向設上限。**不憑空製造不存在的方向**（坐→作 原始 0 筆就是 0 筆）。
#
# ## 兩個刻意的設計
#
# * **句子裡的目標字會被遮成 □**。若把原句照抄出來，corpus gold 就直接印在
#   句子裡，核驗者一眼看到答案 —— 那是在驗「你同不同意」，不是在驗金標。
#   engine choice 與 corpus gold 另外列在旁邊（`--blind` 可連這兩欄一起藏）。
# * **同一層裡優先抽 dev 側的節點**。切分是依 doc_id hash，跟標籤品質無關，
#   所以這不會偏誤；但將來若要把核驗結果當 dev-audited 用來定 τ，
#   落在 train 側的樣本就得先從訓練集剔除。`split` 欄有記，別忘了。
#
# 用法：
#   python3 sample_corpus_gold_audit.py --nodes <nodes.tsv> --sentences <sentences.jsonl> \
#       --out <目錄> [--correct-per-char 30] [--wrong-cap 20]

import argparse
import collections
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_node_expert import DE_READING, MAX_CANDS  # noqa: E402

GROUP = ['作', '做', '坐', '座']
GROUP_SET = set(GROUP)
FIRE_READING = 'ㄗㄨㄛˋ'
MASK = '□'


def target_index_in_node(reading):
    syls = reading.split('-')
    return syls.index(FIRE_READING) if FIRE_READING in syls else -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--sentences', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--correct-per-char', type=int, default=30,
                    help='engine == corpus gold 時，每個字抽幾筆')
    ap.add_argument('--wrong-cap', type=int, default=20,
                    help='engine != corpus gold 時，每個方向上限（不足者全抽）')
    ap.add_argument('--seed', type=int, default=20260817)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    # sid → 原句與 doc_id
    sents = {}
    with open(args.sentences, encoding='utf-8') as fh:
        for i, line in enumerate(fh, start=1):
            r = json.loads(line)
            sents[i] = (r['doc_id'], r['text'], r['split'])

    pool = []
    pop_engine = collections.Counter()
    pop_gold = collections.Counter()
    pop_dir = collections.Counter()
    skipped = collections.Counter()

    with open(args.nodes, encoding='utf-8') as fh:
        next(fh)
        for lineno, line in enumerate(fh, start=1):
            c = line.rstrip('\n').split('\t')
            if len(c) < 16:
                continue
            sid, kind = int(c[0]), int(c[2])
            reading, chosen, gold = c[6], c[7], c[8]
            # 前綴樣本是同一句的重複觀察，核驗會重複看到同一個位置 → 只留完整句
            if kind != 0:
                continue
            ti = target_index_in_node(reading)
            if ti < 0:
                continue
            syls = reading.split('-')
            if len(chosen) != len(syls) or len(gold) != len(syls):
                skipped['長度對不上'] += 1
                continue
            e, g = chosen[ti], gold[ti]
            if e not in GROUP_SET or g not in GROUP_SET:
                continue
            if DE_READING in syls:
                continue
            if sid not in sents:
                skipped['找不到原句'] += 1
                continue
            doc_id, text, _ = sents[sid]
            pos = int(c[4]) + ti            # 目標字在整句裡的位置
            if pos >= len(text) or text[pos] != g:
                # 對不齊就丟。寧可少幾筆，也不要給核驗者一個位置錯的題目。
                skipped['位置對不上原句'] += 1
                continue
            cands = []
            for part in c[15].split('|'):
                q = part.split(':')
                if len(q) == 5:
                    cands.append((q[0], float(q[1])))
            cands.sort(key=lambda x: -x[1])
            cand_names = [v for v, _ in cands[:MAX_CANDS]]

            pop_engine[e] += 1
            pop_gold[g] += 1
            pop_dir[(e, g)] += 1
            pool.append({
                'row': lineno, 'sid': sid, 'doc_id': doc_id,
                'node_index': c[3], 'split': sents[sid][2],
                'sentence': text, 'pos': pos, 'reading': reading,
                'node_reading': reading, 'node_chosen': chosen,
                'node_gold': gold, 'engine': e, 'gold': g,
                'cands': cand_names, 'gold_in_cands': c[9] == '1',
                'span': int(c[5]),
            })

    # ── 分層抽樣 ──
    rng = random.Random(args.seed)
    by_correct = collections.defaultdict(list)
    by_dir = collections.defaultdict(list)
    for r in pool:
        if r['engine'] == r['gold']:
            by_correct[r['engine']].append(r)
        else:
            by_dir[(r['engine'], r['gold'])].append(r)

    def pick(items, n):
        """同層內優先取 dev 側（將來可當 dev-audited 重用），其餘隨機。"""
        dev = [x for x in items if x['split'] == 'dev']
        tr = [x for x in items if x['split'] != 'dev']
        rng.shuffle(dev)
        rng.shuffle(tr)
        return (dev + tr)[:n]

    sample = []
    for ch in GROUP:
        sample += pick(by_correct.get(ch, []), args.correct_per_char)
    for e in GROUP:
        for g in GROUP:
            if e == g:
                continue
            items = by_dir.get((e, g), [])
            if not items:
                continue          # 不存在的方向就是不存在，不憑空製造
            sample += pick(items, args.wrong_cap)

    rng.shuffle(sample)   # 打散，避免核驗者按層產生節奏性偏誤

    # ── 寫待核 TSV ──
    cols = ['sample_id', 'doc_id', 'sentence_id', 'node_id', 'split',
            'sentence_masked', 'sentence_len', 'target_position', 'reading',
            'node_reading', 'engine_choice', 'corpus_gold', 'candidates',
            'is_hard', 'direction', 'gold_in_candidates',
            'human_gold', 'human_confidence', 'notes']
    path = os.path.join(args.out, 'corpus-gold-audit.tsv')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\t'.join(cols) + '\n')
        for i, r in enumerate(sample, start=1):
            masked = r['sentence'][:r['pos']] + MASK + r['sentence'][r['pos'] + 1:]
            hard = r['engine'] != r['gold']
            fh.write('\t'.join([
                f'CGA-{i:04d}', r['doc_id'], str(r['sid']),
                f"{r['sid']}#{r['node_index']}", r['split'],
                masked, str(len(r['sentence'])), str(r['pos']),
                FIRE_READING, r['node_reading'], r['engine'], r['gold'],
                '/'.join(r['cands']), '1' if hard else '0',
                f"{r['engine']}→{r['gold']}" if hard else '-',
                '1' if r['gold_in_cands'] else '0',
                '', '', '',
            ]) + '\n')

    # ── 分布報告（population vs sample）──
    smp_engine = collections.Counter(r['engine'] for r in sample)
    smp_gold = collections.Counter(r['gold'] for r in sample)
    smp_dir = collections.Counter((r['engine'], r['gold']) for r in sample)
    pop_n, smp_n = len(pool), len(sample)

    rep = os.path.join(args.out, 'sampling-report.md')
    with open(rep, 'w', encoding='utf-8') as fh:
        w = fh.write
        w('# 人工核驗抽樣報告（棒⑭-A-1）\n\n')
        w(f'來源：`{args.nodes}`（棒⑬ 實際訓練來源；只取完整句樣本，'
          f'前綴樣本是同一位置的重複觀察，排除）\n\n')
        w(f'母體 {pop_n:,} 個作做坐座節點 → 抽出 **{smp_n}** 筆'
          f'（每字正確樣本 {args.correct_per_char}、每方向上限 {args.wrong_cap}）\n\n')
        if skipped:
            w('對不齊而排除：' + '、'.join(f'{k} {v}' for k, v in skipped.items()) + '\n\n')

        w('## Population distribution（整個訓練來源）\n\n')
        w('| | 作 | 做 | 坐 | 座 | 合計 |\n|---|---|---|---|---|---|\n')
        w('| engine choice | ' + ' | '.join(
            f'{pop_engine[c]:,}（{100 * pop_engine[c] / pop_n:.1f}%）'
            for c in GROUP) + f' | {pop_n:,} |\n')
        w('| corpus gold | ' + ' | '.join(
            f'{pop_gold[c]:,}（{100 * pop_gold[c] / pop_n:.1f}%）'
            for c in GROUP) + f' | {pop_n:,} |\n\n')
        corr = sum(pop_dir[(c, c)] for c in GROUP)
        w(f'engine == corpus gold：{corr:,}（{100 * corr / pop_n:.1f}%）；'
          f'!= ：{pop_n - corr:,}（{100 * (pop_n - corr) / pop_n:.1f}%）\n\n')

        w('## Population vs Sample（逐格）\n\n')
        w('| 格 | 母體 | 抽出 | 抽樣率 |\n|---|---|---|---|\n')
        for e in GROUP:
            for g in GROUP:
                if not pop_dir[(e, g)]:
                    continue
                tag = f'{e}→{g}' + ('（引擎選對）' if e == g else '')
                p, s = pop_dir[(e, g)], smp_dir[(e, g)]
                w(f'| {tag} | {p:,} | {s} | {100 * s / p:.1f}% |\n')
        w(f'| **合計** | {pop_n:,} | {smp_n} | {100 * smp_n / pop_n:.2f}% |\n\n')

        w('## Sample distribution\n\n')
        w('| | 作 | 做 | 坐 | 座 | 合計 |\n|---|---|---|---|---|---|\n')
        w('| engine choice | ' + ' | '.join(str(smp_engine[c]) for c in GROUP)
          + f' | {smp_n} |\n')
        w('| corpus gold | ' + ' | '.join(str(smp_gold[c]) for c in GROUP)
          + f' | {smp_n} |\n\n')
        dev_n = sum(1 for r in sample if r['split'] == 'dev')
        w(f'其中 dev 側 {dev_n} 筆、train 側 {smp_n - dev_n} 筆。\n\n')
        w('> ⚠️ **抽樣是刻意不按母體比例的**（小方向被大幅過抽）。'
          '解讀核驗結果時，任何「整體準確率」都必須用母體比例回加權，'
          '不能直接拿樣本平均當母體估計。\n')

    meta = {'population_engine': {c: pop_engine[c] for c in GROUP},
            'population_gold': {c: pop_gold[c] for c in GROUP},
            'population_dir': {f'{e}→{g}': pop_dir[(e, g)]
                               for e in GROUP for g in GROUP},
            'population_total': pop_n,
            'sample_dir': {f'{e}→{g}': smp_dir[(e, g)]
                           for e in GROUP for g in GROUP},
            'sample_total': smp_n,
            'params': vars(args)}
    with open(os.path.join(args.out, 'sampling-meta.json'), 'w',
              encoding='utf-8') as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    print(open(rep, encoding='utf-8').read())
    print(f'\n待核清單 → {path}')


if __name__ == '__main__':
    main()
