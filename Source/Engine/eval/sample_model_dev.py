#!/usr/bin/env python3
# 建立**新的 audited model-dev**：三軸分層（engine choice × direction × node span）。
#（棒⑭-D PART A。只抽樣，不訓練。）
#
# ## 為什麼要重做一份，而不是沿用棒⑭-A-1 那 263 筆
#
# 那 263 筆是為「語料金標品質稽核」設計的，只按 engine choice × direction 分層。
# 棒⑭-C 量到後果：`作→作` 在那份 dev 只有 6.7% 是單字節點（2 個），
# 測試集是 33.1%（53 個）——而 **37 次改壞裡 34 次（92%）發生在單字節點**。
# 那份 dev 在傷害這一側的 Wilson 上界是 9.64%，真值 10.06%，**數學上偵測不到**。
# 所以第三軸（節點跨度）不是加分項，是必要條件。
#
# ## 兩個來源
#
#   訓練來源 nodes.tsv（train_corpus_decontaminated 抽出的節點）
#   contexts 來源 ctx-nodes.tsv（CONSUME 允許把 full_sentence_hint 再跑一遍引擎；
#                                已剔除命中 FROZEN_HASHES 的句子與「的得地」）
# 合併是為了補「坐／座」——但實測補不了多少：坐→坐·單字 全庫只有 23 個。
# **稀有格就是稀有，抽滿也不夠，只能標 insufficient power，不准憑空製造。**
#
# ## 逆機率權重
#
# 每列都寫 `ipw`＝該格母體／該格抽樣數。報 aggregate 時必須用它加權，
# 同時也要報未加權值（抽樣刻意不按母體比例）。
#
# 用法：
#   python3 sample_model_dev.py --nodes A.tsv --sentences A.jsonl \
#       --nodes2 B.tsv --sentences2 B.jsonl --out <目錄> [--cap 60]

import argparse
import collections
import json
import os
import random

FIRE = 'ㄗㄨㄛˋ'
GROUP = ['作', '做', '坐', '座']
GSET = set(GROUP)
MASK = '□'


def load(nodes, sents, tag):
    sid = {}
    with open(sents, encoding='utf-8') as fh:
        for i, line in enumerate(fh, start=1):
            r = json.loads(line)
            sid[i] = (r['doc_id'], r['text'])
    out = []
    with open(nodes, encoding='utf-8') as fh:
        head = next(fh).rstrip('\n').split('\t')
        for line in fh:
            c = dict(zip(head, line.rstrip('\n').split('\t')))
            if int(c['kind']) != 0:
                continue
            syls = c['reading'].split('-')
            if FIRE not in syls:
                continue
            ti = syls.index(FIRE)
            if len(c['chosen']) != len(syls) or len(c['gold']) != len(syls):
                continue
            e, g = c['chosen'][ti], c['gold'][ti]
            if e not in GSET or g not in GSET:
                continue
            s = int(c['sid'])
            if s not in sid:
                continue
            doc, text = sid[s]
            pos = int(c['char_start']) + ti
            if pos >= len(text) or text[pos] != g:
                continue
            cands = []
            for part in c['cands'].split('|'):
                q = part.split(':')
                if len(q) == 5:
                    cands.append((q[0], float(q[1])))
            cands.sort(key=lambda x: -x[1])
            span = int(c['span'])
            out.append({
                'src': tag, 'doc_id': doc, 'sid': s, 'node_index': c['node_index'],
                'text': text, 'pos': pos, 'reading': c['reading'],
                'engine': e, 'corpus_gold': g, 'span': span,
                'span_class': '單字' if span == 1 else '多字',
                'cands': [v for v, _ in cands[:24]],
                'gold_in_cands': c['gold_in_cands'] == '1',
            })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--sentences', required=True)
    ap.add_argument('--nodes2', default='')
    ap.add_argument('--sentences2', default='')
    ap.add_argument('--out', required=True)
    ap.add_argument('--cap', type=int, default=60,
                    help='每個 cell 的抽樣上限（母體不足就全抽）')
    ap.add_argument('--diagonal-min', type=int, default=132,
                    help='每個對角線（engine==gold）至少抽這麼多；'
                         '132 抽樣 → 約 120 可判定 → 0 次改壞時 Wilson 上界約 3%%。'
                         '母體不足者全抽並標 insufficient power')
    ap.add_argument('--seed', type=int, default=20260817)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    pool = load(args.nodes, args.sentences, 'train-src')
    if args.nodes2:
        pool += load(args.nodes2, args.sentences2, 'contexts')
    # 同一個 (doc, 位置) 可能在兩個來源都出現 → 去重
    seen = set()
    dedup = []
    for r in pool:
        k = (r['doc_id'], r['text'], r['pos'])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(r)
    pool = dedup

    cells = collections.defaultdict(list)
    for r in pool:
        cells[(r['engine'], r['corpus_gold'], r['span_class'])].append(r)

    rng = random.Random(args.seed)
    sample = []
    rows_meta = {}
    # 對角線要另外拉到 --diagonal-min（估 damage 用），多的份額給母體大的那個跨度
    quota = {k: min(len(v), args.cap) for k, v in cells.items()}
    for ch in GROUP:
        diag = [k for k in cells if k[0] == ch and k[1] == ch]
        have = sum(quota[k] for k in diag)
        room = sorted(diag, key=lambda k: -(len(cells[k]) - quota[k]))
        for k in room:
            if have >= args.diagonal_min:
                break
            add = min(len(cells[k]) - quota[k], args.diagonal_min - have)
            quota[k] += add
            have += add
    for k, v in cells.items():
        n = quota[k]
        picked = rng.sample(v, n)
        for r in picked:
            r['ipw'] = len(v) / n
            r['cell'] = f'{k[0]}→{k[1]}·{k[2]}'
        sample += picked
        rows_meta[f'{k[0]}→{k[1]}·{k[2]}'] = {'population': len(v), 'sampled': n,
                                              'ipw': len(v) / n}
    rng.shuffle(sample)

    cols = ['sample_id', 'source', 'doc_id', 'sentence_id', 'node_id', 'cell',
            'direction', 'span', 'span_class', 'ipw', 'sentence_masked',
            'sentence_len', 'target_position', 'reading', 'engine_choice',
            'corpus_gold', 'candidates', 'is_hard', 'gold_in_candidates',
            'human_gold', 'human_confidence', 'notes']
    path = os.path.join(args.out, 'model-dev-audit.tsv')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\t'.join(cols) + '\n')
        for i, r in enumerate(sorted(sample, key=lambda x: (x['cell'], x['doc_id'])), 1):
            masked = r['text'][:r['pos']] + MASK + r['text'][r['pos'] + 1:]
            hard = r['engine'] != r['corpus_gold']
            fh.write('\t'.join([
                f'MDV-{i:04d}', r['src'], r['doc_id'], str(r['sid']),
                f"{r['sid']}#{r['node_index']}", r['cell'],
                f"{r['engine']}→{r['corpus_gold']}", str(r['span']),
                r['span_class'], f"{r['ipw']:.4f}", masked, str(len(r['text'])),
                str(r['pos']), FIRE, r['engine'], r['corpus_gold'],
                '/'.join(r['cands']), '1' if hard else '0',
                '1' if r['gold_in_cands'] else '0', '', '', '',
            ]) + '\n')

    docs = sorted({r['doc_id'] for r in sample})
    with open(os.path.join(args.out, 'excluded-docs.txt'), 'w',
              encoding='utf-8') as fh:
        fh.write('\n'.join(docs) + '\n')
    with open(os.path.join(args.out, 'model-dev-meta.json'), 'w',
              encoding='utf-8') as fh:
        json.dump({'cells': rows_meta, 'total_sampled': len(sample),
                   'total_population': len(pool), 'cap': args.cap,
                   'excluded_docs': len(docs)}, fh, ensure_ascii=False, indent=2)

    print(f'母體 {len(pool):,} 個節點 → 抽出 **{len(sample)}** 筆'
          f'（每 cell 上限 {args.cap}）；涵蓋 {len(docs)} 份文件（訓練必須整份排除）')
    print(f'\n{"cell":<14}{"母體":>7}{"抽樣":>6}{"IPW":>8}')
    for k in sorted(rows_meta, key=lambda x: -rows_meta[x]['population']):
        m = rows_meta[k]
        print(f'{k:<14}{m["population"]:>7}{m["sampled"]:>6}{m["ipw"]:>8.2f}')
    print(f'\n→ {path}')


if __name__ == '__main__':
    main()
