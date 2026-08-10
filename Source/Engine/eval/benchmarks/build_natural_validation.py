#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_natural_validation.py — 組裝「自然文本驗證集」

## 為什麼需要這份東西（跟 EX1166 不一樣的用途）

EX1166 刻意排除了「詞庫就分得開」的送分題，所以它量的是**難題上的能力**。
但日常打字裡送分題佔絕大多數，所以 EX1166 的分數**不等於使用者體感**。
2026-08-10 實測：同一批機制在 EX1166 上 +5.7 分，在自然文本上只有 +0.8 分。

更重要的是，自然文本會露出 EX1166 完全看不到的傷害：

    信長的全盛時期 → 信長得    （「長得」規則命中，但這裡「長」是人名一部分）
    垃圾在開       → 垃圾再開
    我們結婚吧到底  → 結婚巴

EX1166 裡不存在「信長」這種句子。**改選字機制一定要兩份都跑。**

## 資料怎麼來

1. 從真實語料（PTT）隨機抽句，每句含且只含一組同音字的一個字
2. 派給外部 AI 逐句判定「這個字用對了沒」，判不出來標 `?`
3. 這支把判定結果組裝成評分機吃得下的 jsonl

判定為 O 的 → 標準答案就是原字；判定為 X 且給了同組字的 → 標準答案是那個字；
`?` 與「改成組外字」一律丟掉（那些不是我們要量的問題）。

⚠️ 外部 AI 的判定要抽驗。2026-08-10 抽驗過一輪，判 O 的（記得／心得／獲得／
看得到／翻得超好）與判 X 的（博愛坐→座、坐墊→座墊、坐標→座標）都正確。

## 兩種抽樣，用途不同

* `natural`：隨機抽 —— 量**日常體感與誤報率**。會被高頻字主導，那是刻意的，
  因為日常打字就是那個分布。
* `minor`：只抽含低頻字的句子 —— 量**低頻側的正確率**。
  隨機抽樣裡低頻字太少（的得抽 200 句只有 12 句是「得」），量不準。

用法：
    python3 build_natural_validation.py \\
        --sents-dir <抽樣句子目錄> --verdicts-dir <外部 AI 回覆目錄> \\
        --annot <auto_annotate 產生的注音檔> -o 自然驗證集.jsonl
"""

import argparse
import collections
import json
import os
import re

GROUPS = {
    "的得": ("的得", "ㄉㄜ˙"),
    "在再": ("在再", "ㄗㄞˋ"),
    "吧八巴": ("吧八巴", "ㄅㄚ"),
    "作做坐座": ("作做坐座", "ㄗㄨㄛˋ"),
    "前錢": ("前錢", "ㄑㄧㄢˊ"),
    "較叫": ("較叫", "ㄐㄧㄠˋ"),
}
VERDICT = re.compile(r"^(\d+)\t([OX?])(?:\t([一-鿿]))?")


def collect(sents_dir, verdicts_dir):
    """把「句子檔」與「判定檔」配對。兩邊靠檔名相同（副檔名不同）對齊。"""
    rows, stats = [], collections.Counter()
    for fn in sorted(os.listdir(sents_dir)):
        if not fn.endswith(".txt"):
            continue
        stem = fn[:-4]
        vpath = os.path.join(verdicts_dir, stem + ".md")
        if not os.path.exists(vpath):
            stats["缺判定檔"] += 1
            continue
        sents = [l.strip() for l in
                 open(os.path.join(sents_dir, fn), encoding="utf-8") if l.strip()]
        group = next((g for g in GROUPS if g in stem), None)
        if group is None:
            stats["檔名認不出組別"] += 1
            continue
        cs = GROUPS[group][0]
        kind = "minor" if stem.endswith("minor") else "natural"
        for line in open(vpath, encoding="utf-8"):
            m = VERDICT.match(line.strip())
            if not m:
                continue
            i = int(m.group(1))
            if not (1 <= i <= len(sents)):
                stats["編號超出範圍"] += 1
                continue
            sent, v, fix = sents[i - 1], m.group(2), m.group(3)
            hits = [(k, c) for k, c in enumerate(sent) if c in cs]
            if len(hits) != 1:
                stats["同組字不只一個"] += 1
                continue
            k, c = hits[0]
            if v == "O":
                gold = c
            elif v == "X" and fix and fix in cs:
                gold = fix
            else:
                stats["判不出或改成組外字"] += 1
                continue
            rows.append({"sentence": sent, "target_index": k, "gold": gold,
                         "group": group, "kind": kind, "verdict": v})
            stats[f"{group}/{kind}"] += 1
    return rows, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sents-dir", action="append", required=True)
    ap.add_argument("--verdicts-dir", action="append", required=True)
    ap.add_argument("--annot", required=True,
                    help="auto_annotate.py 的輸出（句子<空白>注音）")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()

    if len(args.sents_dir) != len(args.verdicts_dir):
        raise SystemExit("--sents-dir 與 --verdicts-dir 要成對給")

    rows, stats = [], collections.Counter()
    for sd, vd in zip(args.sents_dir, args.verdicts_dir):
        r, s = collect(os.path.expanduser(sd), os.path.expanduser(vd))
        rows += r
        stats.update(s)

    seen, dedup = set(), []
    for r in rows:
        if r["sentence"] in seen:
            continue
        seen.add(r["sentence"])
        dedup.append(r)
    by_sent = {r["sentence"]: r for r in dedup}
    print(f"判定結果 {len(rows)} 筆 → 去重 {len(dedup)} 句")

    reading = {}
    with open(os.path.expanduser(args.annot), encoding="utf-8") as fh:
        for line in fh:
            p = line.strip().split()
            if len(p) == 2:
                reading[p[0]] = p[1]

    out, skip = [], collections.Counter()
    for n, (sent, r) in enumerate(sorted(by_sent.items()), 1):
        rd = reading.get(sent)
        if rd is None:
            skip["沒有注音"] += 1
            continue
        syl = rd.split("-")
        if len(syl) != len(sent):
            skip["注音音節數對不上"] += 1
            continue
        cs, want = GROUPS[r["group"]]
        if syl[r["target_index"]] != want:
            # 目標字在這句讀別的音 → 使用者根本打不到這個混淆，那題不算數
            skip["目標位讀音不符"] += 1
            continue
        out.append({
            "sentence_id": f"NAT-{n:05d}", "sentence": sent,
            "target_index": r["target_index"], "target_char": r["gold"],
            "wrong_chars": [c for c in cs if c != r["gold"]],
            "reading": want, "pair_id": r["group"], "n_way": len(cs),
            "weight": 1.0, "tier": "single", "split": "heldout",
            "domain": f"ptt-{r['kind']}", "full_reading": rd,
            "source": "corpus-audited",
        })

    with open(args.output, "w", encoding="utf-8") as fh:
        for d in out:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")

    print(f"\n寫出 {len(out)} 題 → {args.output}")
    per = collections.Counter((d["pair_id"], d["domain"]) for d in out)
    for (g, dom), n in sorted(per.items()):
        print(f"  {g:<10}{dom:<14}{n}")
    if skip:
        print("\n略過：" + "、".join(f"{k} {v}" for k, v in skip.most_common()))
    print("\n※ 這份要跟 EX1166 一起跑。EX1166 量難題能力，這份量日常體感與誤報率。")


if __name__ == "__main__":
    main()
