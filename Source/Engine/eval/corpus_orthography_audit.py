#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""corpus_orthography_audit.py — 語料在同音字上有多髒？

要回答的問題：**拿這份語料訓練同音字消歧，會不會學到錯的？**

2026-08-10 已知「的／得」在 PTT 語料只有約 57% 正確（「跑得很快」875 次 vs
「跑的很快」643 次），所以 v2c 學到的就是錯的 —— 它不是能力不足，是被教壞。
但其他五組的乾淨度**沒人量過**，而那決定了路線 C（對比訓練）能做幾組。

## 做法：拿**已驗證的規則**當標準答案（不是拿題庫）

⚠️ 第一版是拿題庫的三字窗當標準答案，**那是錯的**。題庫刻意只收「看前後幾個字
分不出答案」的難題 —— 「你在說什麼」跟「你再說一次」的三字窗完全一樣，兩個都對。
於是語料裡合法的另一種寫法會被算成「寫錯」，量出來的髒度全是假的
（實測「你_說」報出「寫錯 1755 次」，但那些幾乎都是正確的「你在說」）。

**只有在「上下文真的決定答案」的地方才量得準。** 我們手上正好有一批這種上下文：
`Source/Data/homophone-rules.tsv` 的規則 —— 每條都在封存集驗過
（整體出手準確率 92.7%），而且形式就是「左邊／右邊某個字 → 答案一定是 X」。

所以做法是：把每條 L1／R1 規則展開成具體字串，去語料數
「寫成規則說的那個字」vs「寫成同組其他字」的次數。規則說了算，
語料跟它不一致就是語料寫錯。

    規則：左邊是「跑」→ 得
    語料：跑得 875 次、跑的 643 次
    → 這個上下文的語料正確率 57.7%

用法：
    python3 corpus_orthography_audit.py --rules ../../Data/homophone-rules.tsv \\
        --corpus ~/laowang-data/ptt_spoken_train_v2.txt \\
        --corpus ~/laowang-data/replies_pushes_only.txt

判讀：
    ≥90%  乾淨，可以拿來做對比訓練
    70~90% 邊緣，訓練前要先過濾
    <70%  不能用，模型會學到錯的（「的／得」就是這一類）
"""

import argparse
import collections
import os
import sys

GROUPS = ["的得", "在再", "吧八巴", "作做坐座", "前錢", "較叫"]


def load_rules(path):
    """回傳 [(組, 位置L1/R1, 觸發字, 正解字)]，只收單一 L1= 或 R1= 條件的規則。

    多條件規則（例如「右1 在清單且右2 在清單」）不收 —— 展開成字串會爆炸，
    而且那種規則本來就少。單條件的已經足以代表「上下文決定答案」的情況。
    """
    lists = collections.defaultdict(set)
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            f = line.rstrip("\n").split("\t")
            if f[0] == "LIST" and len(f) >= 3:
                lists[f[1]].add(f[2])
            elif f[0] == "RULE" and len(f) >= 5:
                conds = [c for c in f[4].split(";") if c]
                if len(conds) != 1:
                    continue
                c = conds[0]
                if c.startswith("!") or "=" not in c:
                    continue
                slot, name = c.split("=", 1)
                if slot not in ("L1", "R1") or name == "@DICT":
                    continue
                group = f[1].split("/")[0]
                for trigger in lists.get(name, ()):
                    out.append((group, slot, trigger, f[3]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", required=True, help="homophone-rules.tsv")
    ap.add_argument("--corpus", action="append", required=True)
    ap.add_argument("--min-hits", type=int, default=20,
                    help="該上下文在語料出現幾次以上才納入")
    args = ap.parse_args()

    rules = load_rules(args.rules)
    if not rules:
        sys.exit("規則檔裡沒有單一 L1/R1 條件的規則")
    chars = {g: set(g) for g in GROUPS}

    # 展開成具體字串：觸發字 + 該組每個字（L1），或該組每個字 + 觸發字（R1）
    probes = {}
    for g, slot, trig, gold in rules:
        if g not in chars:
            continue
        for c in chars[g]:
            frag = (trig + c) if slot == "L1" else (c + trig)
            probes[frag] = (g, slot, trig, gold, c)
    print(f"從規則展開 {len(probes)} 個二字探針"
          f"（{len(set((g, s, t) for g, s, t, _ in rules))} 個上下文）")

    counts = collections.Counter()
    mb = 0
    for path in args.corpus:
        p = os.path.expanduser(path)
        if not os.path.exists(p):
            sys.exit(f"找不到語料：{p}")
        mb += os.path.getsize(p)
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                for k in range(len(line) - 1):
                    frag = line[k:k + 2]
                    if frag in probes:
                        counts[frag] += 1
    print(f"掃過 {mb / 1024 / 1024:.0f} MB 語料\n")

    slot_agg = collections.defaultdict(lambda: {"gold": 0, "wrong": 0})
    for frag, (g, slot, trig, gold, c) in probes.items():
        key = (g, slot, trig, gold)
        slot_agg[key]["gold" if c == gold else "wrong"] += counts[frag]

    per = collections.defaultdict(lambda: {"gold": 0, "wrong": 0, "n": 0})
    bad = collections.defaultdict(list)
    for (g, slot, trig, gold), v in slot_agg.items():
        tot = v["gold"] + v["wrong"]
        if tot < args.min_hits:
            continue
        per[g]["gold"] += v["gold"]
        per[g]["wrong"] += v["wrong"]
        per[g]["n"] += 1
        rate = v["gold"] / tot
        if rate < 0.85:
            frag = (trig + gold) if slot == "L1" else (gold + trig)
            bad[g].append((frag, v["gold"], v["wrong"], rate))

    print(f"{'組':<10}{'上下文':>7}{'寫對':>10}{'寫錯':>9}{'語料正確率':>12}   判讀")
    print("─" * 62)
    for g in GROUPS:
        v = per.get(g)
        if not v or v["gold"] + v["wrong"] == 0:
            print(f"{g:<10}{'—':>7}   規則展開後在語料裡出現太少，量不出來")
            continue
        tot = v["gold"] + v["wrong"]
        rate = v["gold"] / tot
        verdict = ("✅ 可用於對比訓練" if rate >= 0.9 else
                   "⚠️ 邊緣，訓練前要過濾" if rate >= 0.7 else
                   "❌ 不能用，會學到錯的")
        print(f"{g:<10}{v['n']:>7}{v['gold']:>10}{v['wrong']:>9}"
              f"{rate * 100:>11.1f}%   {verdict}")

    print("\n── 語料寫錯最兇的上下文（<85%，各組列 4 個）──")
    for g in GROUPS:
        ex = sorted(bad.get(g, []), key=lambda x: -(x[1] + x[2]))[:4]
        if not ex:
            continue
        print(f"  【{g}】")
        for frag, ok, bd, rate in ex:
            print(f"    {frag}　語料寫對 {ok} 次、寫錯 {bd} 次（{rate * 100:.0f}%）")

    print("\n※ 只量「規則說了算」的上下文 —— 那些地方語料跟規則不一致就是語料寫錯。"
          "\n※ 規則本身在封存集的出手準確率是 92.7%，所以這個標準有據可查。")


if __name__ == "__main__":
    main()
