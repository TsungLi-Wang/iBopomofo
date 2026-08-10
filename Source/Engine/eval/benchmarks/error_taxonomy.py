#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""error_taxonomy.py — 把剩下的錯誤按「哪一層造成的」分類

## 為什麼要有這張表

改選字機制時最容易犯的錯，是先問「該用哪個模型」而不是先問
**「這個錯誤是在哪一層產生的」**。層搞錯了，再厲害的機制也修不到。

最關鍵的分野是：

    正確答案根本沒進候選  →  搜尋問題（Search）
    正確答案在候選裡但排錯 →  排序問題（Ranking）

前者再怎麼加重排器、加參數都沒用，因為正解不在搜尋空間裡。
2026-08-10 實測「的／得」就是這一類：正解連前 200 條路徑都擠不進去。

## 分類的判斷順序（由外而內，先命中先算）

0. **整句解碼錯** — 目標字以外的位置也錯了。這種錯不是「這個位置排序錯」，
   是整句被解錯而目標字被連坐（例：「先寄的初稿」被解成「先記得初稿」）。
   把它們算進排序問題會嚴重高估重排器能修的比例。
1. **規則誤開火** — 規則關掉時是對的，開了之後變錯
2. **候選沒進來** — 正解不在該節點的候選裡，也不在任何路徑上（真正的搜尋問題）
3. **斷詞錯** — 正解在某條路徑上，但當前斷詞下的節點改選不出來
4. **頻率先驗壓制** — 正解就在節點候選裡，但詞頻分數差得很遠（≥ 門檻）
5. **神經模型偏** — 正解在十條候選路徑裡，但融合後的分數把它排到後面
6. **上下文不足** — 正解在節點裡、分數差也不大，但十條路徑撈不到它

用法：
    /tmp/oracle_ceiling <題庫> <data.txt> <bigrams> <v2c.bin> 10 diag.tsv
    python3 error_taxonomy.py --diag diag.tsv \\
        --rules-off dump-off.tsv --rules-on dump-on.tsv --items 題庫.jsonl
"""

import argparse
import collections
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diag", required=True, help="oracle_ceiling 的第 6 個參數輸出")
    ap.add_argument("--items", required=True)
    ap.add_argument("--rules-off", required=True, help="規則關掉那次的 dump")
    ap.add_argument("--rules-on", required=True, help="規則開啟那次的 dump")
    ap.add_argument("--gap-threshold", type=float, default=2.0,
                    help="詞頻分數差多少算「被頻率壓死」。"
                         "log10 尺度，2.0 = 相差 100 倍")
    ap.add_argument("--split", default="heldout")
    ap.add_argument("--show", type=int, default=3, help="每類列幾個例子")
    args = ap.parse_args()

    items = {}
    with open(args.items, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                d = json.loads(line)
                items[d["sentence"]] = d

    def load(path):
        out = {}
        with open(path, encoding="utf-8") as fh:
            next(fh)
            for line in fh:
                f = line.rstrip("\n").split("\t")
                if len(f) >= 5:
                    out[f[0]] = (f[1], f[2], int(f[3]), f[4])
        return out

    off, on = load(args.rules_off), load(args.rules_on)
    id_by_sent = {items[s]["sentence"]: items[s]["sentence_id"]
                  for s in items if "sentence_id" in items[s]}

    diag = {}
    with open(args.diag, encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) < 11:
                continue
            diag[f[0]] = {
                "pair": f[1], "split": f[2], "gold": f[3], "chosen": f[4],
                "in_node": f[5] == "1", "in_10": f[6] == "1",
                "in_200": f[7] == "1", "node_len": int(f[8]),
                "gap": float(f[9]), "segs": f[10],
            }

    cats = collections.defaultdict(list)
    total = 0
    for sent, d in diag.items():
        if args.split and d["split"] != args.split:
            continue
        sid = id_by_sent.get(sent)
        ok_on = on.get(sid, (None, None, None, None))[2] if sid else None
        ok_off = off.get(sid, (None, None, None, None))[2] if sid else None
        if ok_on is None:
            continue
        if ok_on == 1:
            continue          # 現在是對的，不是錯誤
        total += 1

        gold_sent = items[sent]["sentence"]
        out_sent = on[sid][3]
        ti = items[sent]["target_index"]
        # 目標字以外還有別的位置也錯 → 整句解碼錯，目標字是被連坐的
        others_wrong = (len(out_sent) != len(gold_sent) or
                        any(a != b for k, (a, b) in enumerate(zip(gold_sent, out_sent))
                            if k != ti))
        if ok_off == 1:
            cat = "規則誤開火"
        elif others_wrong:
            cat = "整句解碼錯"
        elif not d["in_node"] and not d["in_200"]:
            cat = "候選沒進來"
        elif not d["in_node"] and d["in_200"]:
            cat = "斷詞錯"
        elif d["gap"] >= args.gap_threshold:
            cat = "頻率先驗壓制"
        elif d["in_10"]:
            cat = "神經模型偏"
        else:
            cat = "上下文不足"
        cats[cat].append((sent, d))

    print(f"分析 {total} 個錯誤（{args.split}）\n")
    print(f"{'類別':<14}{'題數':>6}{'佔比':>8}   這一類該修哪裡")
    print("─" * 74)
    WHERE = {
        "整句解碼錯": "目標字被連坐 —— 要修的是整句解碼，不是這個位置的排序",
        "候選沒進來": "詞庫／候選生成 —— 重排器再強也沒用",
        "斷詞錯": "walk 斷詞或 N-best 多樣性",
        "頻率先驗壓制": "路線 A（壓縮頻率）或節點內改選（規則／神經專家）",
        "神經模型偏": "路線 C（對比訓練）或調 ν",
        "上下文不足": "加大 N-best、或更強的上下文模型",
        "規則誤開火": "剪規則或加 abstention —— 這是我們自己造成的",
    }
    ORDER = ["整句解碼錯", "規則誤開火", "候選沒進來", "斷詞錯",
             "頻率先驗壓制", "神經模型偏", "上下文不足"]
    for c in ORDER:
        n = len(cats[c])
        if not n:
            continue
        print(f"{c:<14}{n:>6}{n * 100 / max(total, 1):>7.1f}%   {WHERE[c]}")

    for c in ORDER:
        ex = cats[c][:args.show]
        if not ex:
            continue
        print(f"\n【{c}】")
        for sent, d in ex:
            print(f"  {sent}")
            print(f"    正解「{d['gold']}」選成「{d['chosen']}」　"
                  f"節點內有正解:{'是' if d['in_node'] else '否'}　"
                  f"詞頻差:{d['gap']:.1f}　斷詞:{d['segs'][:34]}")

    print("\n── 逐組 ──")
    per = collections.defaultdict(collections.Counter)
    for c, rows in cats.items():
        for _, d in rows:
            per[d["pair"]][c] += 1
    for g in sorted(per):
        tot = sum(per[g].values())
        detail = "、".join(f"{c} {n}" for c, n in per[g].most_common())
        print(f"  {g:<10}共 {tot:>3}　{detail}")

    print("\n※ 先問「錯在哪一層」再問「該用哪個模型」。"
          "候選沒進來那一類，加再多參數都修不到。")


if __name__ == "__main__":
    main()
