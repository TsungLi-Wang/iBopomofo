#!/usr/bin/env python3
# 誤傷普查：專家在**目標組以外**動了多少東西。
#
# ## 為什麼現有的尺看不到這件事
#
# 兩份真實語料、ship-gate、compare_dumps 全都只看「目標那一個字對不對」。
# 一個到處出手的節點層機制可以在目標字上很漂亮，同時把句子其他地方改爛，
# 而所有腳本都是綠的。棒⑫ 就是這樣：目標字帳面只有 −28，同一批卻有 3,409 句
# 在目標字以外被改了 5,522 個字。
#
# 這支報三個數字：
#   1. 被改的句子數，以及其中**目標不是本棒目標組**的句數（這個必須接近 0）
#   2. 目標字以外被改的字數
#   3. **整句逐字正確率（對真人原文）** —— 沒有這一欄會把改善誤判成傷害：
#      題庫的 sentence 是真人原文，引擎解出來的整句本來就有別的地方是錯的，
#      模型把那些地方改對跟改錯，在「改動數」上長得一模一樣。
#
#   python3 node_expert_collateral.py <before.tsv> <after.tsv> \
#       --items <題庫.jsonl> [--group 作做坐座]

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
    ap.add_argument('--group', default='作做坐座')
    ap.add_argument('--show', type=int, default=5)
    args = ap.parse_args()

    items = {}
    with open(args.items, encoding='utf-8') as fh:
        for line in fh:
            r = json.loads(line)
            items[r['sentence_id']] = r

    a, b = load_dump(args.before), load_dump(args.after)
    keys = a.keys() & b.keys()

    changed = off_target_sent = 0
    outside_chars = 0
    ca = cb = ctot = 0
    per_group = collections.Counter()
    examples = []

    for k in sorted(keys):
        it = items.get(k)
        oa, ob = a[k]['output'], b[k]['output']
        if it is not None:
            gold = it['sentence']
            n = len(gold)
            ctot += n
            ca += sum(1 for i in range(min(n, len(oa))) if oa[i] == gold[i])
            cb += sum(1 for i in range(min(n, len(ob))) if ob[i] == gold[i])
        if oa == ob:
            continue
        changed += 1
        pair = it.get('pair_id', '?') if it else '?'
        per_group[pair] += 1
        if pair != args.group:
            off_target_sent += 1
            if len(examples) < args.show:
                examples.append((k, pair, oa, ob))
        ti = it['target_index'] if it else -1
        if len(oa) == len(ob):
            outside_chars += sum(1 for i in range(len(oa))
                                 if oa[i] != ob[i] and i != ti)
        else:
            outside_chars += abs(len(oa) - len(ob)) + 1

    print(f'共同題數 {len(keys)}')
    print(f'整句被改的題數            {changed}')
    print(f'  其中目標不是「{args.group}」  {off_target_sent}'
          f'   ← 這個數字必須接近 0')
    print(f'  目標字以外被改的字數      {outside_chars}')
    if per_group:
        print('被改的句子逐組：' +
              '、'.join(f'{g} {n}' for g, n in per_group.most_common()))
    if ctot:
        print(f'整句逐字正確率（對真人原文）  前 {100 * ca / ctot:.3f}%  '
              f'後 {100 * cb / ctot:.3f}%  淨 {cb - ca:+d} 字 / {ctot} 字')
    if examples:
        print(f'\n目標不是「{args.group}」卻被改的例子：')
        for k, pair, oa, ob in examples:
            print(f'  {k}（{pair}）\n    前 {oa}\n    後 {ob}')


if __name__ == '__main__':
    main()
