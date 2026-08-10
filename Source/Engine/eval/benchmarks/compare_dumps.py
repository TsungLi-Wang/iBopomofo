#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compare_dumps.py — 比較兩次評分機跑出來的逐題結果（配對檢定）

改引擎之後要回答的問題是「這個改動是真的有效，還是雜訊」。
只比兩邊的總分回答不了：**淨進步 41 題**可以是「84 題改對／43 題改錯」，
也可以是「300 題改對／259 題改錯」—— 前者是穩定的改進，後者是把答案洗牌。

這支拿兩份 dump 逐題對照，算出改對／改錯的題數與 McNemar 檢定值。

用法：
    # 兩次跑評分機，第 9 個參數指定 dump 路徑
    /tmp/newstar_homophone_eval <題庫> ... <alphas> before.tsv
    /tmp/newstar_homophone_eval <題庫> ... <alphas> after.tsv <規則表>

    python3 compare_dumps.py before.tsv after.tsv
    python3 compare_dumps.py before.tsv after.tsv --items 題庫.jsonl --show 15

⚠️ 對照組（before）必須是「機制關閉」的那次，而且要先確認它跟你**改程式之前**
   的結果逐位相同。沒有這一步，你不知道新加的程式碼在關閉時是不是真的沒作用。
"""

import argparse
import collections
import json
import math


def load(path):
    rows = {}
    with open(path, encoding="utf-8") as fh:
        header = next(fh)
        if not header.startswith("sentence_id"):
            raise SystemExit(f"{path} 不像 dump 檔（第一行應該是欄位名）")
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) < 5:
                continue
            rows[f[0]] = {"pair": f[1], "split": f[2],
                          "ok": int(f[3]), "out": f[4]}
    return rows


def mcnemar_p(b, c):
    """b = 改對的題數、c = 改壞的題數。回傳雙尾 p 值（含連續性校正）。"""
    n = b + c
    if n == 0:
        return 1.0
    z = (abs(b - c) - 1) / math.sqrt(n)
    if z <= 0:
        return 1.0
    return math.erfc(z / math.sqrt(2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--items", default="", help="題庫 jsonl，給了才能列出句子")
    ap.add_argument("--show", type=int, default=10, help="列幾句改壞的")
    args = ap.parse_args()

    a, b = load(args.before), load(args.after)
    common = set(a) & set(b)
    if not common:
        raise SystemExit("兩份 dump 沒有共同的題目，檢查是不是跑了不同題庫")
    if len(common) != len(a) or len(common) != len(b):
        print(f"⚠️ 兩份題數不同（{len(a)} vs {len(b)}），只比共同的 {len(common)} 題\n")

    items = {}
    if args.items:
        with open(args.items, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    d = json.loads(line)
                    items[d["sentence_id"]] = d

    # (split, pair) -> [題數, before 對, 改對, 改壞]
    agg = collections.defaultdict(lambda: [0, 0, 0, 0])
    broken = []
    for sid in common:
        x, y = a[sid], b[sid]
        for key in ((x["split"], "總計"), (x["split"], x["pair"])):
            g = agg[key]
            g[0] += 1
            g[1] += x["ok"]
            if y["ok"] and not x["ok"]:
                g[2] += 1
            elif x["ok"] and not y["ok"]:
                g[3] += 1
        if x["ok"] and not y["ok"]:
            broken.append((sid, x["out"], y["out"], x["pair"], x["split"]))

    print(f"{'組':<10}{'題數':>6}{'原本':>9}{'改對':>6}{'改壞':>6}{'淨':>6}"
          f"{'新分':>9}{'McNemar p':>12}")
    for split in ("heldout", "train"):
        rows = sorted([k for k in agg if k[0] == split],
                      key=lambda k: (k[1] != "總計", k[1]))
        if not rows:
            continue
        print(f"\n【{split}】" + ("  ← 這欄才算數（沒被拿來調過）"
                                 if split == "heldout" else ""))
        for key in rows:
            n, base, gain, loss = agg[key]
            net = gain - loss
            p = mcnemar_p(gain, loss)
            ps = f"{p:.2g}" if p >= 1e-6 else "<1e-6"
            mark = " ✅" if p < 0.05 and net > 0 else (" ❌" if p < 0.05 else "")
            print(f"  {key[1]:<8}{n:>6}{base * 100 / n:>8.1f}%{gain:>6}{loss:>6}"
                  f"{net:>+6}{(base + net) * 100 / n:>8.1f}%{ps:>12}{mark}")

    if broken and args.show:
        print(f"\n── 被改壞的（最多列 {args.show} 句）──")
        for sid, before, after, pair, split in broken[:args.show]:
            gold = items.get(sid, {}).get("sentence", "")
            print(f"  [{pair}/{split}] {before}  →  {after}"
                  + (f"　（正解 {gold}）" if gold and gold != before else ""))
        if len(broken) > args.show:
            print(f"  …還有 {len(broken) - args.show} 句")

    print("\n※ 分母小於 100 的那幾列別下結論 —— 「+9.1 分」在 44 題裡只是多對 4 題。")


if __name__ == "__main__":
    main()
