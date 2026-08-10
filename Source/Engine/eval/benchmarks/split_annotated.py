#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""split_annotated.py — 把「一次貼完的注音檔」拆回各組

為什麼：小麥只是加注音，不管句子屬於哪一組。所以九個檔分開貼是多餘的手工，
合成一份貼一次、回來再拆，可以省掉八次來回。

用法：
    python3 split_annotated.py 待過小麥-全部-已加注音.txt

它會照 `.manifest.json`（合併時記下的「第幾句屬於哪一組」）拆回去，
並逐組跑一次健檢。行數對不上會直接報錯，不會默默拆錯。
"""

import json
import os
import subprocess
import sys

BASE = os.path.expanduser("~/Documents/i注音-語料")
OUT = os.path.join(BASE, "EX1166-已注音")
HERE = os.path.dirname(os.path.abspath(__file__))

GROUPS = {
    "在再": ("在,再", "ㄗㄞˋ", "在/再"),
    "的得": ("的,得", "ㄉㄜ˙", "的/得"),
    "那哪": ("那,哪", "ㄋㄚˇ", "那/哪"),
    "吧八巴": ("吧,八,巴", "ㄅㄚ", "吧/八/巴"),
    "前錢乾": ("前,錢,乾", "ㄑㄧㄢˊ", "前/錢/乾"),
    "作做坐座": ("作,做,坐,座", "ㄗㄨㄛˋ", "作/做/坐/座"),
    "覺較教叫": ("覺,較,教,叫", "ㄐㄧㄠˋ", "覺/較/教/叫"),
}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    annotated = [l.rstrip("\n") for l in open(sys.argv[1], encoding="utf-8")
                 if l.strip()]
    manifest = json.load(open(os.path.join(BASE, ".manifest.json"), encoding="utf-8"))

    if len(annotated) != len(manifest):
        print(f"❌ 行數對不上：注音檔 {len(annotated)} 行，"
              f"合併時記錄的是 {len(manifest)} 句。")
        print("   小麥可能吃掉或合併了某些行。請確認貼回來的行數跟貼進去的一樣，"
              "不要刪行、不要重排。")
        return 1

    os.makedirs(OUT, exist_ok=True)
    buckets = {}
    for line, group in zip(annotated, manifest):
        buckets.setdefault(group, []).append(line)

    print(f"拆成 {len(buckets)} 組：\n")
    fail = 0
    for group, lines in buckets.items():
        path = os.path.join(OUT, f"{group}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        chars, reading, pair = GROUPS[group]
        jsonl = os.path.join(OUT, f"{group}.jsonl")
        r = subprocess.run(
            ["python3", os.path.join(HERE, "make_newstar_jsonl.py"), path,
             "-o", jsonl, "--group", chars, "--reading", reading,
             "--pair-id", pair, "--source", "EX1166", "--fix-target-reading"],
            capture_output=True, text=True)
        kept = [l for l in r.stdout.split("\n") if l.startswith("KEPT")]
        fixed = [l for l in r.stdout.split("\n") if "強制修正" in l]
        status = kept[0] if kept else "轉檔失敗"
        if "轉檔失敗" in status:
            fail += 1
        print(f"  {group:<10}{len(lines):>3} 句　{status}")
        if fixed:
            print(f"             ⚠️ {fixed[0].strip()}")
        rejects = [l for l in r.stderr.split("\n") if l.startswith("REJECT")]
        for rj in rejects[:3]:
            print(f"             {rj[:110]}")

    print(f"\n輸出：{OUT}/")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
