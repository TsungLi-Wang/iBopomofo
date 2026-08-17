#!/usr/bin/env python3
# 人工核驗 CLI：一次一題，可中斷續做。
#
# ## 你在判的是「語料金標對不對」，不是「引擎對不對」
#
# 看到 `引擎＝作、語料金標＝做`，**不要**因為引擎看起來合理就接受語料金標；
# 看到兩邊都是「坐」，也還是要真的讀上下文確認。兩邊的答案都可能是錯的。
# 判不出來就按 `?`（UNCERTAIN）—— 不要硬選，硬選的那一票會變成假的證據。
#
# 句子裡的目標字已經遮成 □。這是刻意的：把原字印在句子裡，等於先把答案
# 告訴你，之後量到的就不是金標品質，而是「你同不同意」。
#
# 用法：
#   python3 annotate_corpus_gold.py --file <corpus-gold-audit.tsv>
#   python3 annotate_corpus_gold.py --file <...> --blind      # 連引擎與金標都不顯示
#   python3 annotate_corpus_gold.py --file <...> --only-unfilled
#
# 按鍵：1=作 2=做 3=坐 4=座 ?=判不出來 s=跳過 b=上一題 q=存檔離開
# 每答一題就立刻寫回檔案，**當機也不會掉進度**。

import argparse
import os
import shutil
import sys
import unicodedata

CHOICES = {'1': '作', '2': '做', '3': '坐', '4': '座'}
MASK = '□'


def read_tsv(path):
    with open(path, encoding='utf-8') as fh:
        lines = fh.read().rstrip('\n').split('\n')
    header = lines[0].split('\t')
    rows = [dict(zip(header, ln.split('\t'))) for ln in lines[1:]]
    return header, rows


def write_tsv(path, header, rows):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write('\t'.join(header) + '\n')
        for r in rows:
            fh.write('\t'.join(r.get(k, '') for k in header) + '\n')
    os.replace(tmp, path)


def display_width(text):
    """終端機欄寬。CJK 是全形佔兩欄，用半形空格對齊會讓箭頭指錯字 ——
    箭頭指錯字比沒有箭頭更糟，所以這裡老實算寬度。"""
    return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)


def render(r, idx, total, done, blind):
    sent = r['sentence_masked']
    pos = int(r['target_position'])
    width = shutil.get_terminal_size((100, 24)).columns
    print('\n' + '═' * min(width, 78))
    print(f'  {r["sample_id"]}    第 {idx + 1} / {total} 題    已完成 {done}')
    print('─' * min(width, 78))
    # 上下文各留 30 字，太長的句子不要塞爆終端機
    lo = max(0, pos - 30)
    hi = min(len(sent), pos + 31)
    shown = ('…' if lo > 0 else '') + sent[lo:hi] + ('…' if hi < len(sent) else '')
    print(f'\n  {shown}\n')
    prefix = ('…' if lo > 0 else '') + sent[lo:pos]
    print(' ' * (2 + display_width(prefix)) + '↑')
    extra = r.get('node_reading') or r.get('cell', '')
    span = r.get('span_class') or (
        '單字' if r.get('span') == '1' else '多字詞' if r.get('span') else '')
    print(f'  讀音：{r["reading"]}    {"節點" if r.get("node_reading") else "分層"}：{extra}'
          + (f'    節點跨度：{span}' if span else ''))
    print(f'  候選：{r["candidates"]}')
    if not blind:
        print(f'  引擎選了：{r["engine_choice"]}      語料金標：{r["corpus_gold"]}'
              + ('   （兩邊不同）' if r['is_hard'] == '1' else '   （兩邊相同）'))
    else:
        print('  （blind 模式：引擎與語料金標都不顯示）')
    if r.get('human_gold'):
        print(f'  ← 你上次填的：{r["human_gold"]}'
              + (f'（{r["human_confidence"]}）' if r.get('human_confidence') else ''))
    print('\n  1=作  2=做  3=坐  4=座  ?=判不出來  s=跳過  b=上一題  q=存檔離開')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', required=True)
    ap.add_argument('--blind', action='store_true',
                    help='連引擎選擇與語料金標都不顯示（測錨定效應用）')
    ap.add_argument('--only-unfilled', action='store_true',
                    help='只跑還沒填的題（預設就會從第一題未填處開始）')
    args = ap.parse_args()

    header, rows = read_tsv(args.file)
    for k in ('human_gold', 'human_confidence', 'notes'):
        if k not in header:
            sys.exit(f'檔案缺欄位 {k} —— 這不是抽樣工具產生的待核清單')

    order = [i for i, r in enumerate(rows)
             if not (args.only_unfilled and r.get('human_gold'))]
    if not order:
        print('沒有待核的題目。')
        return
    # 從第一題還沒填的開始
    start = 0
    for j, i in enumerate(order):
        if not rows[i].get('human_gold'):
            start = j
            break

    j = start
    try:
        while 0 <= j < len(order):
            i = order[j]
            done = sum(1 for r in rows if r.get('human_gold'))
            render(rows[i], j, len(order), done, args.blind)
            try:
                key = input('  > ').strip()
            except EOFError:
                break
            if key == 'q':
                break
            if key == 'b':
                j = max(0, j - 1)
                continue
            if key == 's':
                j += 1
                continue
            if key == '?':
                rows[i]['human_gold'] = 'UNCERTAIN'
                rows[i]['human_confidence'] = 'low'
            elif key in CHOICES:
                rows[i]['human_gold'] = CHOICES[key]
                rows[i]['human_confidence'] = 'high'
            else:
                print('  ← 沒這個按鍵，再試一次')
                continue
            note = ''
            if key == '?':
                note = input('  備註（可留空）：').strip()
            if note:
                rows[i]['notes'] = note
            write_tsv(args.file, header, rows)   # 每題立刻存
            j += 1
    finally:
        write_tsv(args.file, header, rows)
        done = sum(1 for r in rows if r.get('human_gold'))
        print(f'\n已存檔：{args.file}')
        print(f'完成 {done} / {len(rows)}'
              + ('  ← 全部完成，可以跑 score_corpus_gold_audit.py'
                 if done == len(rows) else '  ← 下次執行同一行指令會從這裡接續'))


if __name__ == '__main__':
    main()
