#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_contrastive_data.py — 從語料切出「同音字對比訓練」用的資料（路線 C）

每筆資料長這樣：一個句子、一個目標位置、正解字、同組的其他候選字。
訓練時把整句用每個候選字各算一次分數，要求正解那句分數最高。

## 為什麼是整句對比，不是單點分類

v2c 是**因果**字元 LSTM —— 在目標位置它只看得到左邊的字。「跑得很快」在「得」
那個位置，模型只看過「跑」。它能分辨的原因是**換字之後後面的字變得多不合理**
（P(很|跑得) 高於 P(很|跑的)）。所以訓練目標必須是整句分數的比較，
單點預測學不到右邊的訊號。

## ⚠️ 只收語料乾淨的組

2026-08-10 實測（見交班檔）：
  在再 92%、吧八巴 98.6%、前錢 100%、較叫 98% → 可用
  **的得 39.5~57.3% → 不可用**，語料寫錯的比寫對的還多，訓練會學到錯的
  作做坐座 94% 但路徑層天花板只有 71.1%，投報低

## ⚠️ 平衡取樣：不給模型頻率資訊

每個候選字當正解的筆數取一樣多。不平衡的話模型會重新學到「在比再常見」，
那正是我們要拿掉的東西（路線 A 在推論時做同一件事）。

用法：
    python3 build_contrastive_data.py -o /tmp/rc-data \\
        --corpus ~/laowang-data/ptt_spoken_train_v2.txt \\
        --corpus ~/laowang-data/replies_pushes_only.txt \\
        --exclude-items ~/Documents/i注音-語料/EX1166-題庫/EX1166-全部.jsonl
"""

import argparse
import collections
import json
import os
import random
import re

# 只放語料乾淨、而且路徑層還有空間的組。加組之前先跑語料乾淨度審計。
GROUPS = {
    "在再": "在再",
    "吧八巴": "吧八巴",
    "前錢": "前錢",
    "較叫": "較叫",
    # 2026-08-13 issue #9 加入。天花板偏低（見上），要做就一組一模型獨立驗。
    "作做坐座": "作做坐座",
}

HAN_ONLY = re.compile(r"^[一-鿿]+$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out-dir", required=True)
    ap.add_argument("--corpus", action="append", required=True)
    ap.add_argument("--exclude-items", default="",
                    help="EX1166 jsonl —— 這些句子一律不進訓練資料。"
                         "生成句理論上不會出現在語料裡，但這道防線不能省。")
    ap.add_argument("--per-char", type=int, default=20000,
                    help="每個候選字當正解取幾筆（平衡取樣）")
    ap.add_argument("--min-len", type=int, default=6)
    ap.add_argument("--max-len", type=int, default=30)
    ap.add_argument("--heldout-ratio", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=1234)
    args = ap.parse_args()

    banned = set()
    if args.exclude_items:
        with open(os.path.expanduser(args.exclude_items), encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    banned.add(json.loads(line)["sentence"])
        print(f"排除名單 {len(banned)} 句（EX1166）")

    char_to_group = {}
    for g, cs in GROUPS.items():
        for c in cs:
            char_to_group[c] = g

    pool = collections.defaultdict(list)   # (組, 正解字) -> [(句子, 位置)]
    seen = set()
    scanned = 0
    for path in args.corpus:
        p = os.path.expanduser(path)
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                for seg in re.split(r"[，。！？、\s]+", line.strip()):
                    scanned += 1
                    if not (args.min_len <= len(seg) <= args.max_len):
                        continue
                    if not HAN_ONLY.match(seg) or seg in banned or seg in seen:
                        continue
                    hits = [(i, c) for i, c in enumerate(seg)
                            if c in char_to_group]
                    if len(hits) != 1:
                        continue
                    i, c = hits[0]
                    # 只排除句首（完全沒有左文可條件）。
                    # ⚠️ 不要排除句尾 —— 「吧」最典型的用法就是句尾語氣詞，
                    # 排掉之後這組只剩 3,439 筆，等於把最有鑑別度的資料丟光。
                    # 因果模型在句尾仍然有訊號：P(吧|走) vs P(八|走)。
                    if i == 0:
                        continue
                    g = char_to_group[c]
                    key = (g, c)
                    if len(pool[key]) >= args.per_char * 3:
                        continue
                    seen.add(seg)
                    pool[key].append((seg, i))
    print(f"掃過 {scanned} 個片段")

    os.makedirs(args.out_dir, exist_ok=True)
    rng = random.Random(args.seed)
    stats = []
    for g, cs in GROUPS.items():
        avail = {c: len(pool[(g, c)]) for c in cs}
        take = min(min(avail.values()), args.per_char)
        rows = []
        for c in cs:
            items = pool[(g, c)]
            rng.shuffle(items)
            for seg, i in items[:take]:
                rows.append({"sentence": seg, "target_index": i,
                             "gold": c, "candidates": list(cs), "group": g})
        rng.shuffle(rows)
        cut = int(len(rows) * (1 - args.heldout_ratio))
        for split, part in (("train", rows[:cut]), ("dev", rows[cut:])):
            path = os.path.join(args.out_dir, f"{g}.{split}.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                for r in part:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        stats.append((g, avail, take, len(rows)))

    print(f"\n{'組':<10}{'各字可取筆數':<34}{'平衡後每字':>10}{'合計':>8}")
    for g, avail, take, total in stats:
        detail = " ".join(f"{c}:{n}" for c, n in avail.items())
        print(f"{g:<10}{detail:<34}{take:>10}{total:>8}")
    print(f"\n寫到 {args.out_dir}/（每組 train + dev）")
    print("※ 平衡取樣後每個字筆數相同 —— 模型拿不到頻率資訊，只能從上下文學。")


if __name__ == "__main__":
    main()
