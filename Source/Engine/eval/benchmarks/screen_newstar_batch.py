#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""screen_newstar_batch.py — 新北極星出題管線第 1.5 關（先驗篩）

AI 生完句子、還沒送去小麥注音之前先跑這支。擋掉機器就看得出來的問題，
省下「注音→轉檔→評分機」整趟才發現整批是送分題的往返。

⚠️ **這支不是難度尺，別拿它的數字當成績。** 真正的難度只有評分機說了算
（而評分機要先過小麥注音）。這支只抓一類機器看得出來的送分題：

  「原字跟鄰字構成詞庫裡的詞、換字之後不成詞」
  例：還在／正在／實在／在於 —— 換「再」變成「還再／正再」，詞庫直接否決，
      引擎一刀就切開了，這種句子考不出東西。

**盲區**：兩邊都不在詞庫時（「半再去」「半在去」都查無此詞）它無話可說，
一律放行。所以「通過」不代表這句難，只代表「不是被這一類殺掉的」。

用法：
    python3 screen_newstar_batch.py sentences.txt
    python3 screen_newstar_batch.py sentences.txt --group 是,事,式
    python3 screen_newstar_batch.py sentences.txt --list-freebies   # 列出送分題好刪
"""

import argparse
import collections
import re
import sys

DATA_TXT = "/Users/johnny.w_macmini/iBopomofo/Source/Data/data.txt"
GROUP = ["在", "再"]
DIRTY = re.compile(r"[，。、！？：；「」『』（）〈〉…—\s0-9A-Za-z]")


def load_vocab(path):
    vocab = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                vocab.add(parts[1])
    return vocab


def neighbours(sentence, idx, char):
    """目標字與左右鄰字組成的兩個 2-gram（邊界則略過）。"""
    out = []
    if idx > 0:
        out.append(sentence[idx - 1] + char)
    if idx + 1 < len(sentence):
        out.append(char + sentence[idx + 1])
    return out


def classify(sentence, idx, target, others, vocab):
    """回傳 (是否真陷阱, 說明)。

    判準：只要**任一個**鄰接位置出現「原字成詞、換字不成詞」的落差，
    引擎就能一刀切開 → 送分題。要所有位置都沒有落差才算真陷阱。
    """
    orig = neighbours(sentence, idx, target)
    for other in others:
        subs = neighbours(sentence, idx, other)
        for o, s in zip(orig, subs):
            if o in vocab and s not in vocab:
                return False, f"「{o}」在詞庫、「{s}」不成詞 → 引擎一刀切開"
    return True, "換字後鄰接詞都還成立，引擎得靠上下文"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="一行一句的純句子檔（尚未加注音）")
    ap.add_argument("--group", help="逗號分隔候選字，預設 在,再")
    ap.add_argument("--data", default=DATA_TXT)
    ap.add_argument("--list-freebies", action="store_true", help="列出送分題")
    ap.add_argument("--min-len", type=int, default=8)
    ap.add_argument("--max-len", type=int, default=30)
    args = ap.parse_args()

    group = [c.strip() for c in args.group.split(",")] if args.group else list(GROUP)
    vocab = load_vocab(args.data)

    lines = [l.strip() for l in open(args.input, encoding="utf-8") if l.strip()]
    violations, traps, freebies = [], collections.Counter(), []
    dist, buckets = collections.Counter(), collections.Counter()
    starts = collections.Counter(l[:4] for l in lines)

    for n, line in enumerate(lines, 1):
        hits = [i for i, ch in enumerate(line) if ch in group]
        if len(hits) != 1:
            violations.append((n, line, f"候選字出現 {len(hits)} 次（須剛好 1）")); continue
        if DIRTY.search(line):
            violations.append((n, line, "含標點／空格／數字／英文")); continue
        if not (args.min_len <= len(line) <= args.max_len):
            violations.append((n, line, f"長度 {len(line)}"))
        if starts[line[:4]] > 1:
            violations.append((n, line, f"開頭四字「{line[:4]}」重複"))

        idx = hits[0]
        target = line[idx]
        dist[target] += 1
        buckets["8-12" if len(line) <= 12 else "13-20" if len(line) <= 20 else "21-30"] += 1
        is_trap, why = classify(line, idx, target, [c for c in group if c != target], vocab)
        if is_trap:
            traps[target] += 1
        else:
            freebies.append((n, line, target, why))

    total = sum(dist.values())
    print(f"句數 {len(lines)}　可判定 {total}　硬規則違規 {len(violations)}")
    print(f"答案分佈 {dict(dist)}")
    print(f"長度分佈 {dict(buckets)}")
    print()
    print("── 詞庫一刀切檢查（非難度尺；只抓「換字後不成詞」那一類送分題）──")
    for c in group:
        t, d = traps[c], dist[c]
        pct = f"{t / d * 100:4.0f}%" if d else "  — "
        bar = "█" * round(t / d * 20) if d else ""
        print(f"  答案是「{c}」 存活 {t:3d}/{d:<3d} {pct}  {bar}")
    if total:
        print(f"  合計　　　 存活 {sum(traps.values()):3d}/{total:<3d} "
              f"{sum(traps.values()) / total * 100:4.0f}%（被一刀切掉 {total - sum(traps.values())} 句）")
    rates = [traps[c] / dist[c] for c in group if dist[c]]
    if len(rates) > 1:
        gap = max(rates) - min(rates)
        verdict = ("✅ 兩側被切掉的比例接近" if gap <= 0.20
                   else "⚠️ 偏斜" if gap <= 0.40
                   else "❌ 嚴重偏斜：有一側大量句子被詞庫一刀切掉，那半沒有鑑別度")
        print(f"  兩側落差 {gap * 100:.0f} 個百分點　{verdict}")
        print("  （存活≠難。真正的難度要跑評分機才知道。）")

    if violations:
        print("\n── 硬規則違規 ──")
        for n, line, why in violations:
            print(f"  #{n} {line}　→ {why}")

    if args.list_freebies and freebies:
        print(f"\n── 被詞庫一刀切的 {len(freebies)} 句（建議刪掉重生）──")
        for n, line, target, why in freebies:
            print(f"  #{n} [{target}] {line}")
            print(f"        {why}")


if __name__ == "__main__":
    main()
