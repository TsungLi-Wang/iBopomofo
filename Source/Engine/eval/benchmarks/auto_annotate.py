#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auto_annotate.py — 用引擎詞庫自動標注音，取代人工貼小麥。

為什麼可以取代
--------------
2026-08-10 拿同一批 406 句比對「Johnny 貼小麥拿到的注音」與「本腳本自動標的」：

    2,553 個音節，只差 2 個（0.1%）
    那 2 個是「划算」的划 —— **詞庫是對的、小麥標錯**

準確度一樣，但自動標音是即時的、不用人動手。所以人工貼小麥那一步可以拿掉。

原本堅持用小麥是因為假設它 100% 正確。實測不是——它 99.9%，跟自動標音同級，
而且兩邊錯的地方幾乎重疊（共用同一個詞庫覆蓋盲點）。

共用的盲點
----------
詞庫沒收的動補結構（畫得／考得／寫得），兩種方法都會退回單字「得」的最高頻
讀音 ㄉㄜˊ，但補語的「得」實際讀 ㄉㄜ˙。

這個盲點只影響**答案位**，而答案位的讀音我們本來就知道（組別定義就是它），
所以轉檔時用 `--fix-target-reading` 修掉即可。**只有「的/得」這組需要。**

做法
----
最長匹配：優先用詞庫裡的多字詞讀音（「跑得」→ ㄆㄠˇ-ㄉㄜ˙），
查不到才退回單字的最高頻讀音。這跟標音器的做法一樣。

用法
----
    python3 auto_annotate.py 句子檔.txt                 # 印到 stdout
    python3 auto_annotate.py 句子檔.txt -o 已注音.txt
    python3 auto_annotate.py 句子檔.txt --check 小麥版.txt   # 兩種標法比對
"""

import argparse
import os
import re
import sys

DATA_TXT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "../../../Data/data.txt")
MAX_WORD = 6
BPMF_ONLY = re.compile(r"^[\u3105-\u3129ˊˇˋ˙]+$")  # ㄅ..ㄩ（介音 ㄧㄨㄩ 在 ㄦ 之後，寫 ㄅ-ㄦ 會漏掉）
# 次高讀音跟最高差多少以內才算「有爭議」（log 機率差；越小越嚴格）
GAP_THRESHOLD = 2.0


def load_tables(path):
    """詞 → 最高頻讀音；單字 → 最高頻讀音；單字 → 所有可能讀音。"""
    word, char, multi = {}, {}, {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                score = float(parts[2])
            except ValueError:
                continue
            reading, value = parts[0], parts[1]
            syls = tuple(reading.split("-"))
            if len(syls) != len(value):
                continue
            if not all("一" <= c <= "鿿" for c in value):
                continue
            if value not in word or score > word[value][1]:
                word[value] = (syls, score)
            # 只收真正的注音讀音；標點的「讀音」是 _half_punctuation_ 那種
            # 控制字串，混進來會讓頻率差統計整個歪掉。
            if len(value) == 1 and BPMF_ONLY.match(syls[0]):
                d = multi.setdefault(value, {})
                d[syls[0]] = max(d.get(syls[0], -99.0), score)
                if value not in char or score > char[value][1]:
                    char[value] = (syls, score)
    return word, char, multi


def annotate(sentence, word, char, multi=None):
    """回傳 (音節list, 沒把握的位置list)；標不出來回 (None, [])。

    「沒把握」＝ 字典查不到詞、退回單字猜，**而且那個字有多個讀音**。
    被多字詞確認過的位置就是有把握的（「走路」查得到 → 走＝ㄗㄡˇ 確定）。
    """
    out, unsure, i = [], [], 0
    while i < len(sentence):
        hit = None
        for n in range(min(MAX_WORD, len(sentence) - i), 1, -1):
            w = sentence[i:i + n]
            if w in word:
                hit = (n, word[w][0])
                break
        if hit:
            out.extend(hit[1])
            i += hit[0]
        else:
            c = sentence[i]
            if c not in char:
                return None, []
            out.extend(char[c][0])
            # 只有「次高讀音的頻率接近最高」時才算沒把握。
            # 「了」的 ㄌㄧㄠˇ、「嗎」的 ㄇㄚˇ 雖然登記在字典裡，但頻率差幾個
            # 數量級，實務上不會標錯 —— 那種列出來只是雜訊。
            opts = multi.get(c, {})
            if len(opts) > 1:
                ranked = sorted(opts.items(), key=lambda kv: -kv[1])
                gap = ranked[0][1] - ranked[1][1]
                if gap < GAP_THRESHOLD:
                    unsure.append((len(out) - 1, c, ranked[0][0],
                                   [r for r, _ in ranked[1:]], gap))
            i += 1
    return out, unsure


def main():
    global GAP_THRESHOLD
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="一行一句的純句子檔")
    ap.add_argument("-o", "--output")
    ap.add_argument("--data", default=DATA_TXT)
    ap.add_argument("--check", help="拿另一份已注音檔比對（驗證用）")
    ap.add_argument("--gap", type=float, default=GAP_THRESHOLD,
                    help="爭議門檻：次高讀音跟最高的頻率差小於此值才列出")
    args = ap.parse_args()

    GAP_THRESHOLD = args.gap
    word, char, multi = load_tables(args.data)
    lines = [l.strip() for l in open(args.input, encoding="utf-8") if l.strip()]

    if args.check:
        other = {}
        for line in open(args.check, encoding="utf-8"):
            parts = line.strip().split()
            if len(parts) >= 2:
                other[parts[0]] = parts[1].split("-")
        same = diff = 0
        tot_syl = diff_syl = 0
        shown = 0
        for s in lines:
            sent = s.split()[0]
            auto, _ = annotate(sent, word, char, multi)
            ref = other.get(sent)
            if auto is None or ref is None or len(auto) != len(ref):
                continue
            tot_syl += len(ref)
            bad = [(i, sent[i], ref[i], auto[i])
                   for i in range(len(ref)) if ref[i] != auto[i]]
            diff_syl += len(bad)
            if bad:
                diff += 1
                if shown < 20:
                    for i, c, r, a in bad:
                        print(f"  {sent}　「{c}」對照 {r} / 自動 {a}")
                    shown += 1
            else:
                same += 1
        n = same + diff
        print(f"\n比對 {n} 句、{tot_syl} 音節")
        print(f"  完全一致 {same} 句　音節差異率 "
              f"{diff_syl / tot_syl * 100:.2f}%（{diff_syl}/{tot_syl}）")
        return 0

    out_lines, failed, unsure_all = [], [], []
    for s in lines:
        sent = s.split()[0]
        syls, unsure = annotate(sent, word, char, multi)
        if syls is None or len(syls) != len(sent):
            failed.append(sent)
            continue
        if unsure:
            unsure_all.append((sent, syls, unsure))
        out_lines.append(f"{sent} {'-'.join(syls)}")

    target = args.output
    if target:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out_lines) + "\n")
    else:
        print("\n".join(out_lines))

    print(f"\n標音成功 {len(out_lines)}/{len(lines)} 句", file=sys.stderr)
    if unsure_all:
        n = sum(len(u) for _, _, u in unsure_all)
        print(f"\n⚠️ 沒把握的位置 {n} 處，分佈在 {len(unsure_all)} 句 "
              f"（字典查不到詞、退回單字猜，而且該字有多個讀音）：",
              file=sys.stderr)
        for sent, syls, unsure in unsure_all:
            for pos, c, picked, options, gap in unsure:
                print(f"  {sent}　「{c}」標成 {picked}"
                      f"（也可能是 {'／'.join(options)}，頻率差 {gap:.1f}）",
                      file=sys.stderr)
    if failed:
        print(f"失敗 {len(failed)} 句（有詞庫查不到的字）：", file=sys.stderr)
        for s in failed[:10]:
            print(f"  {s}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
