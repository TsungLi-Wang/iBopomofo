#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""profile_group_usage.py — 出題前先摸清這組的真實用法（第 0 關）

給一組同音字，掃真實台灣語料，把該組每個字的搭配分成三帶：

    弱勢佔比 <10%   詞庫決定 —— 鄰接字就分得開，引擎穩贏，出題避開（送分題）
    弱勢佔比 10~25% 偏向但不決定 —— 可以考
    弱勢佔比 >25%   **bigram 無訊號** —— 鄰接字給不出線索，必須靠更遠的上下文

⚠️ 最後那一帶要看語意才知道該不該考，光看次數分不出來：
     · 兩個字在這個位置**意思不同**（在說／再說、在過／再過）
       → 句子有唯一正解，只是 bigram 判不出來 → **最該考的就是這些**
     · 兩個字在這個位置**意思一樣**（作法／做法、啊／阿）
       → 真互通，兩個都對 → 避開（模稜兩可）
   B 類組（有語法/語意規則）的這一帶是金礦；A 類組的這一帶才是要避開的。

「弱勢佔比」＝ 同一個搭配位置上，第二名相對第一名的佔比（**只比前兩名**，
所以 2 路組和 n 路組的數字可以直接互相比較；否則字愈多弱勢天生愈高）。
例：作品 3331 / 做品 8 → 0.2%（一面倒）；作法 131 / 做法 182 → 58%（互通）。

用途：產「該組出題禁用清單」貼進生成 prompt，讓 AI 不要生送分題和模稜兩可句。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ **這支量的是「大家寫得一不一致」，不是「這組該不該考」。兩者無關。**

  先分清楚這組屬於哪一類，再決定要不要看這支的數字：

  【A 類 · 無語法規則】兩個字都對、選錯不影響理解 —— 例：啊／阿
      → 用量分散＝真的互通 → 歸「例外處理組」，不進考卷，交 UOM 學個人習慣。
      → 這支的數字有效。

  【B 類 · 有語法規則】有明確對錯，寫錯讀者會在意 —— 例：的／得
      → **用量五五波不代表互通，代表一半的人寫錯**。
      → 那是「一半使用者需要幫忙」，是最值得做的組，不是最不值得。
      → **這支的數字對這類組完全無效，別拿來判它該不該考。**
      → 而且語料裡的字不能當 gold（一半是錯的），只能照語法規則生成＋人工把關。

  判斷靠的是「有沒有語法規則」，不是靠這支的統計。統計只在 A 類上說得上話。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

用法：
    python3 profile_group_usage.py 在 再
    python3 profile_group_usage.py 作 做 --min-count 100
    python3 profile_group_usage.py 的 得 --side right   # 只看右鄰
"""

import argparse
import collections
import re
from pathlib import Path

# Default hard-mined corpus under ~/laowang-data; override with --corpus or IBOPOMOFO_HARD_CORPUS.
CORPUS = __import__("os").environ.get(
    "IBOPOMOFO_HARD_CORPUS",
    str(Path.home() / "laowang-data" / "batonD-final" / "traindata" / "hard_mined_full.txt"))
HAN = re.compile(r"[一-鿿]")


def scan(corpus, chars, side):
    """回傳 {(側, 鄰字): Counter{組員: 次數}}"""
    table = collections.defaultdict(collections.Counter)
    cset = set(chars)
    with open(corpus, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            n = len(line)
            for i, ch in enumerate(line):
                if ch not in cset:
                    continue
                if side in ("both", "right") and i + 1 < n and HAN.match(line[i + 1]):
                    table[("右", line[i + 1])][ch] += 1
                if side in ("both", "left") and i > 0 and HAN.match(line[i - 1]):
                    table[("左", line[i - 1])][ch] += 1
    return table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chars", nargs="+", help="同音組的字，例：在 再")
    ap.add_argument("--corpus", default=CORPUS)
    ap.add_argument("--min-count", type=int, default=50, help="搭配總次數門檻")
    ap.add_argument("--side", choices=["both", "left", "right"], default="both")
    ap.add_argument("--top", type=int, default=15, help="每帶列幾筆")
    args = ap.parse_args()

    chars = args.chars
    table = scan(args.corpus, chars, args.side)

    bands = {"一面倒": [], "甜蜜帶": [], "互通": []}
    for (side, nb), cnt in table.items():
        total = sum(cnt.values())
        if total < args.min_count:
            continue
        top = cnt.most_common()
        # 只比前兩名 —— n 路組的弱勢佔比天生偏高，這樣才跨組可比（等同 2 路）
        minority = 0.0 if len(top) < 2 else top[1][1] / (top[0][1] + top[1][1])
        label = "一面倒" if minority < 0.10 else ("甜蜜帶" if minority <= 0.25 else "互通")
        pat = [(f"{c}{nb}" if side == "右" else f"{nb}{c}", cnt[c]) for c in chars if cnt[c]]
        bands[label].append((minority, total, side, nb, pat))

    for label in ("甜蜜帶", "互通", "一面倒"):
        rows = sorted(bands[label], reverse=(label != "一面倒"))
        head = {"甜蜜帶": "✅ 偏向但不決定（10~25%）—— 可以考",
                "互通": "🎯 bigram 無訊號（>25%）—— 意思不同→最該考；意思相同→避開（看語意判）",
                "一面倒": "🚫 詞庫決定（<10%）—— 引擎穩贏，出題避開"}[label]
        print(f"\n{head}　共 {len(bands[label])} 個搭配")
        print("─" * 68)
        for minority, total, side, nb, pat in rows[:args.top]:
            shown = "　".join(f"{w}:{n:,}" for w, n in pat)
            print(f"  弱勢 {minority * 100:4.1f}%  {shown}")

    tot = sum(len(v) for v in bands.values())
    if tot:
        inter = len(bands["互通"]) / tot
        print(f"\n總計 {tot} 個搭配　互通佔 {inter * 100:.0f}%")
        if inter > 0.5:
            print("⚠️ 過半搭配是互通。")
            print("   若這組**沒有語法規則**（A 類，如啊／阿）→ 歸例外處理組，不進考卷。")
            print("   若這組**有語法規則**（B 類，如的／得）→ 這代表一半的人寫錯，"
                  "是最該做的組；本表對它無效，答案要照語法定、不照語料定。")
        else:
            print("→ 出題必禁「詞庫決定」帶；「bigram 無訊號」帶要逐條看語意："
                  "意思不同的拿來當主力題，意思相同的才禁。")


if __name__ == "__main__":
    main()
