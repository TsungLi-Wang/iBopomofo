#!/usr/bin/env python3
# 附帶傷害普查：節點層機制在**目標字以外**的位置改了多少字。
#
# ## 為什麼要有這支（現有的尺看不到這件事）
#
# 兩份真實語料與 ship-gate 都只看「目標那一個字對不對」。一個到處出手的節點層
# 機制可以在目標字上得分很漂亮，同時把句子其他地方改爛，而三支腳本全都是綠的。
# 六組同音規則翻車時的實際災情（前女友→錢女友、結婚吧→結婚巴）正是這一類，
# 只是那次剛好落在目標字上才被抓到。
#
# 這支不是尺，是**體檢**：出手次數、目標外改動數、以及改了什麼。
# 數字大不代表壞（有些改動是對的），但「目標外改動遠多於目標內」就要停下來看。
#
#   python3 node_scorer_collateral.py <before.tsv> <after.tsv> --items <題庫.jsonl>

import argparse
import collections
import json


def load_dump(path):
    rows = {}
    with open(path, encoding='utf-8') as fh:
        next(fh)
        for line in fh:
            f = line.rstrip('\n').split('\t')
            if len(f) >= 5:
                rows[f[0]] = {'correct': int(f[3]), 'output': f[4]}
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('before')
    ap.add_argument('after')
    ap.add_argument('--items', required=True)
    ap.add_argument('--show', type=int, default=10)
    args = ap.parse_args()

    items = {}
    with open(args.items, encoding='utf-8') as fh:
        for line in fh:
            r = json.loads(line)
            items[r['sentence_id']] = r

    a, b = load_dump(args.before), load_dump(args.after)
    keys = a.keys() & b.keys()

    changed_sent = 0
    target_changed = 0
    collateral_chars = 0
    collateral_sent = 0
    examples = []
    per_group = collections.Counter()

    for k in keys:
        oa, ob = a[k]['output'], b[k]['output']
        if oa == ob:
            continue
        changed_sent += 1
        it = items.get(k)
        ti = it['target_index'] if it else -1
        diffs = [i for i in range(min(len(oa), len(ob))) if oa[i] != ob[i]]
        if len(oa) != len(ob):
            # 長度變了 → 斷詞或候選長度不同，整句都算目標外改動
            diffs = list(range(max(len(oa), len(ob))))
        outside = [i for i in diffs if i != ti]
        if ti in diffs:
            target_changed += 1
        if outside:
            collateral_sent += 1
            collateral_chars += len(outside)
            if it:
                per_group[it.get('pair_id', '?')] += len(outside)
            if len(examples) < args.show:
                examples.append((k, oa, ob, ti, outside))

    # ── 整句逐字正確率 ──
    # 「目標字以外被改了幾個字」單看是**歧義的**：題庫的 sentence 是真人原文，
    # 引擎從注音解回來的整句本來就有一堆別的地方是錯的。模型把那些地方改對，
    # 跟改錯，在「改動數」上長得一模一樣。所以一定要對著原文數。
    ca = cb = ctot = 0
    for k in keys:
        it = items.get(k)
        if it is None:
            continue
        gold = it['sentence']
        oa, ob = a[k]['output'], b[k]['output']
        n = len(gold)
        ctot += n
        ca += sum(1 for i in range(min(n, len(oa))) if oa[i] == gold[i])
        cb += sum(1 for i in range(min(n, len(ob))) if ob[i] == gold[i])
    if ctot:
        print(f'整句逐字正確率（對真人原文）  前 {100 * ca / ctot:.3f}%  '
              f'後 {100 * cb / ctot:.3f}%  淨 {cb - ca:+d} 字 / {ctot} 字')
    print(f'共同題數 {len(keys)}')
    print(f'整句被改的題數      {changed_sent}')
    print(f'  其中目標字被改    {target_changed}')
    print(f'  其中有目標外改動  {collateral_sent}（合計 {collateral_chars} 個字）')
    if per_group:
        print('目標外改動逐組：' +
              '、'.join(f'{g} {n}' for g, n in per_group.most_common()))
    if examples:
        print('\n目標外改動範例：')
        for k, oa, ob, ti, outside in examples:
            marks = ''.join('^' if i in outside else ('T' if i == ti else ' ')
                            for i in range(max(len(oa), len(ob))))
            print(f'  {k}\n    前 {oa}\n    後 {ob}\n       {marks}')


if __name__ == '__main__':
    main()
