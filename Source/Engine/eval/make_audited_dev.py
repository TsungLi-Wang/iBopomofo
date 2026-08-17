#!/usr/bin/env python3
# 把人工核驗結果接回節點特徵，做成 audited dev；同時輸出必須排除的文件清單。
#
# ## 為什麼需要這一步
#
# 核驗檔（corpus-gold-audit-annotated.tsv）只有題目與 human gold，沒有模型
# 要吃的特徵（候選與分數、左右文…）。要拿它當 dev，得用 `sid#node_index`
# 接回 nodes.tsv。
#
# ## 文件洩漏（這一條不做，後面所有 dev 數字都不算數）
#
# 核驗樣本有一半以上來自 train 側的文件。直接拿來當 dev，等於用模型看過的
# 文件評模型。所以這支同時輸出 `excluded-docs.txt`，訓練時必須整份排除。
# 代價實測：全部節點 −10.0%、作做坐座節點 −13.5%。這個代價是必須付的。
#
# ## UNCERTAIN 怎麼處理
#
# 連人都判不出來的題目**不進 dev 的正確率分母**，但保留在檔案裡（標記出來），
# 因為「模型在這種題目上有沒有亂出手」本身是要看的 —— 一個好的專家在
# 人都判不了的地方應該棄權。
#
# 用法：
#   python3 make_audited_dev.py --annotated <...tsv> --nodes <nodes.tsv> \
#       --sentences <sentences.jsonl> --out <目錄>

import argparse
import collections
import json
import os

FIRE = 'ㄗㄨㄛˋ'


def gold_char_at_target(reading, value):
    """節點可能是多字詞（工作、座位…），human_gold 是**單一字**。
    要比的是 ㄗㄨㄛˋ 那一格的字，不是整個節點的值 ——
    直接拿整個節點值去比，多字詞永遠不相等，統計會全錯。"""
    syls = reading.split('-')
    if FIRE not in syls:
        return None
    i = syls.index(FIRE)
    return value[i] if len(value) == len(syls) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--annotated', required=True)
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--sentences', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    L = open(args.annotated, encoding='utf-8').read().rstrip('\n').split('\n')
    ah = L[0].split('\t')
    ann = [dict(zip(ah, x.split('\t'))) for x in L[1:]]
    want = {r['node_id']: r for r in ann}
    docs = sorted({r['doc_id'] for r in ann})

    sid2doc = {}
    with open(args.sentences, encoding='utf-8') as fh:
        for i, line in enumerate(fh, start=1):
            sid2doc[i] = json.loads(line)['doc_id']

    header = None
    matched = []
    with open(args.nodes, encoding='utf-8') as fh:
        header = next(fh).rstrip('\n').split('\t')
        for line in fh:
            c = line.rstrip('\n').split('\t')
            if len(c) < 16:
                continue
            key = f'{c[0]}#{c[3]}'
            if key in want and int(c[2]) == 0:
                matched.append((c, want[key]))

    out_path = os.path.join(args.out, 'audited-dev.tsv')
    stats = collections.Counter()
    with open(out_path, 'w', encoding='utf-8') as fh:
        fh.write('\t'.join(header + ['human_gold', 'sample_id',
                                      'doc_id_audit']) + '\n')
        for c, a in matched:
            fh.write('\t'.join(c + [a['human_gold'], a['sample_id'],
                                    a['doc_id']]) + '\n')
            stats['matched'] += 1
            if a['human_gold'] == 'UNCERTAIN':
                stats['uncertain'] += 1
            elif a['human_gold'] == gold_char_at_target(c[6], c[8]):
                stats['human_agrees_corpus'] += 1
            else:
                stats['human_differs_corpus'] += 1

    with open(os.path.join(args.out, 'excluded-docs.txt'), 'w',
              encoding='utf-8') as fh:
        fh.write('\n'.join(docs) + '\n')

    print(f'核驗筆數 {len(ann)}；接回節點 {stats["matched"]}'
          f'（沒接上 {len(ann) - stats["matched"]}）')
    print(f'  人工同意語料金標 {stats["human_agrees_corpus"]}、'
          f'不同意 {stats["human_differs_corpus"]}、'
          f'判不出來 {stats["uncertain"]}')
    print(f'必須排除的文件 {len(docs)} 份 → '
          f'{os.path.join(args.out, "excluded-docs.txt")}')
    print(f'audited dev → {out_path}')


if __name__ == '__main__':
    main()
