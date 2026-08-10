#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""induce_rules.py — 從題庫自動歸納同音字規則（規則探勘）

跟「請 AI 讀例句寫規則」是兩條不同的路：AI 靠語感猜，這支靠數。
它掃過**全部** train 題目，對每一種「上下文樣式」算出現次數與純度，
只收「見過夠多次、而且幾乎都指向同一個答案」的樣式。

為什麼這樣做得到：同音字的正確答案通常由**局部搭配**決定
（「飯前別…」的前 vs「飯錢我出」的錢），這種局部規律用數的比用猜的可靠 ——
數得出支持度，也就擋得掉「只對得上一句話」的規則。

⚠️ 只吃 train。封存集碰都不碰 —— 規則是從哪份資料挖的，就不能拿那份報成績。

## 兩種收規則的準則（--criterion）

* `purity`：固定純度門檻，例如 90%。
* `sqrt`：**根號檢定** —— 收的條件是 `sqrt(多數次數) > 少數次數`。

根號檢定出自陳勇志、吳世弘等〈中文混淆字集應用於別字偵錯模板自動產生〉（2009，
朝陽科大＋資策會）。那篇原本用卡方檢定收錯別字模板，發現卡方允許「錯誤用法的頻率
隨正確用法線性成長」—— 但真實語料裡錯誤用法永遠是稀有的，所以卡方放進大量雜訊。
改成根號之後 Micro Precision 從 84.3% 升到 91.3%。

對我們的意義：**門檻應該隨頻率變**。固定 90% 門檻在樣式出現 1000 次時等於容忍
100 次反例（太鬆），根號檢定只容忍 31 次；反過來在樣式只出現 9 次時根號比固定
門檻寬鬆，因為小樣本本來就估不準純度。

用法：
    python3 induce_rules.py --items 題庫.jsonl --dump 逐題結果.tsv \\
        --group 前錢 --reading ㄑㄧㄢˊ -o 前錢-induced.tsv \\
        --min-support 8 --min-purity 0.95

輸出的規則表可以直接餵給 try_rules.py 試跑，也可以直接進引擎。
"""

import argparse
import collections
import json
import math

# 上下文樣式。每個都是「只看目標字前後幾個字」，跟 try_rules.py 的條件語言一一對應。
# 刻意不放「整句」「句長」這種樣式 —— 那些學得到但推廣不了。
# ⚠️ 樣式裡**不可以包含目標字本身**。
# L1T（左1+目標）、TR1（目標+右1）看起來很好用，但規則是拿「引擎選出來的字」
# 去比對的 —— 引擎選錯時那個位置是錯字，「前別」這種樣式永遠對不上，規則等於死的。
# 這兩個樣式只適合當否定護欄（例如「的/得」規則裡的「真的／有的」不准動），
# 不能拿來歸納正面規則。
TEMPLATES = [
    ("L1",     lambda s, i: s[i - 1] if i >= 1 else None),
    ("R1",     lambda s, i: s[i + 1] if i + 1 < len(s) else None),
    ("LW2",    lambda s, i: s[i - 2:i] if i >= 2 else None),
    ("RW2",    lambda s, i: s[i + 1:i + 3] if i + 3 <= len(s) else None),
    ("L1_R1",  lambda s, i: (s[i - 1], s[i + 1]) if i >= 1 and i + 1 < len(s) else None),
    # 位置。語氣詞（吧）幾乎只出現在句尾，名詞的一部分（嘴巴／下巴）不會 ——
    # 「先去報到吧」跟「到八點」的差別就在這裡，光看左邊那個「到」分不出來。
    ("L1_END", lambda s, i: (s[i - 1], i == len(s) - 1) if i >= 1 else None),
]


def wilson_lower(hits, total, z=1.96):
    """純度的 Wilson 信賴區間下界。

    為什麼不直接用純度：9 次裡對 9 次（純度 100%）跟 200 次裡對 196 次
    （純度 98%）在固定門檻下前者贏，但前者其實只是樣本太小還沒看到反例。
    Wilson 下界把「看過幾次」算進去 —— 9/9 的下界是 0.70，196/200 是 0.95。

    這是論文那個「門檻要隨頻率變」的洞見，換成適合我們資料規模的做法：
    論文的 C 是語料庫詞頻（上萬），sqrt 在那個尺度很嚴；我們的樣式只出現
    5~200 次，sqrt 反而比固定門檻鬆（sqrt(100)=10，等於容忍 9% 反例）。
    我們需要的是**小樣本更嚴**，方向剛好相反。
    """
    if total == 0:
        return 0.0
    p = hits / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (centre - margin) / denom


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--dump", required=True,
                    help="評分機逐題結果。用來知道引擎在每題選了什麼 —— "
                         "規則只需要修引擎會錯的那些方向。")
    ap.add_argument("--group", required=True)
    ap.add_argument("--reading", required=True)
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--min-support", type=int, default=8,
                    help="一個樣式至少要在 train 出現這麼多次才收。"
                         "這一關就是擋『只對得上一兩句』的規則。")
    ap.add_argument("--min-purity", type=float, default=0.95,
                    help="該樣式底下同一個答案要佔到這個比例才收（--criterion purity 時用）")
    ap.add_argument("--min-exposure-ratio", type=float, default=0.0,
                    help="支持度 ÷ 觸發字在整份 train 出現的次數，要大於這個值才收。"
                         "擋的是「掛在高頻字上、但只見過幾次」的規則 —— "
                         "那種規則在題庫裡純度 100%%，實際打字卻常常踩到。"
                         "0 表示不啟用。實測安全規則的比值中位數 0.15，"
                         "會改壞的只有 0.079。")
    ap.add_argument("--criterion", choices=["purity", "sqrt", "wilson"],
                    default="wilson",
                    help="purity：固定純度門檻。sqrt：根號檢定，"
                         "收的條件是 sqrt(多數次數) > 少數次數。"
                         "根號檢定出自陳勇志等〈中文混淆字集應用於別字偵錯模板自動產生〉"
                         "（2009）—— 見本檔開頭的說明。"
                         "wilson：純度的信賴區間下界要超過門檻，"
                         "小樣本自動變嚴（推薦，理由見本檔開頭）。")
    args = ap.parse_args()

    items = {}
    with open(args.items, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                d = json.loads(line)
                items[d["sentence_id"]] = d

    engine_pick = {}
    with open(args.dump, encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            f = line.rstrip("\n").split("\t")
            engine_pick[f[0]] = f[4]

    # 觸發字曝險：整份 train（**六組都算**）裡這個字出現幾次。
    # 為什麼要全部算不是只算本組：規則在真實打字時會遇到各種句子，
    # 曝險程度跟本組題目多不多無關。封存集不碰。
    exposure = collections.Counter()
    for d in items.values():
        if d["split"] == "train":
            exposure.update(d["sentence"])

    # 只用 train
    train = [d for d in items.values()
             if d["pair_id"] == args.group and d["split"] == "train"]
    if not train:
        raise SystemExit(f"train 裡沒有 {args.group} 的題目")

    # 對每個樣式統計：樣式值 → 正確答案的分佈
    stats = {name: collections.defaultdict(collections.Counter)
             for name, _ in TEMPLATES}
    for d in train:
        s, i = d["sentence"], d["target_index"]
        for name, fn in TEMPLATES:
            v = fn(s, i)
            if v is not None:
                stats[name][v][d["target_char"]] += 1

    group_chars = sorted({d["target_char"] for d in train})

    # 收規則：夠多次、夠純
    picked = []
    for name, _ in TEMPLATES:
        for value, dist in stats[name].items():
            total = sum(dist.values())
            if total < args.min_support:
                continue
            top, n = dist.most_common(1)[0]
            purity = n / total
            minority = total - n
            if args.criterion == "purity":
                if purity < args.min_purity:
                    continue
            elif args.criterion == "sqrt":
                if math.sqrt(n) <= minority:
                    continue
            else:  # wilson
                if wilson_lower(n, total) < args.min_purity:
                    continue
            if args.min_exposure_ratio > 0:
                trigger = value[0] if isinstance(value, tuple) else value
                exp = sum(exposure[ch] for ch in trigger) if isinstance(trigger, str) else 0
                if exp > 0 and total / exp < args.min_exposure_ratio:
                    continue
            picked.append({"tpl": name, "value": value, "to": top,
                           "support": total, "purity": purity})

    # 樣式愈長愈具體，讓它先判；同長度先看純度、再看支持度。
    specific = {"L1": 0, "R1": 0, "LW2": 1, "RW2": 1, "L1_END": 2, "L1_R1": 2}
    picked.sort(key=lambda r: (-specific[r["tpl"]], -r["purity"], -r["support"]))

    lists = collections.defaultdict(list)
    rules = []
    for k, r in enumerate(picked):
        ln = f"{r['tpl']}_{r['to']}_{k}"
        if r["tpl"] == "L1_R1":
            l, rr = r["value"]
            lists[ln + "L"].append(l)
            lists[ln + "R"].append(rr)
            conds = f"L1={ln}L;R1={ln}R"
        elif r["tpl"] == "L1_END":
            l, at_end = r["value"]
            lists[ln].append(l)
            conds = f"L1={ln};" + ("END" if at_end else "NOTEND")
        else:
            lists[ln].append(r["value"])
            conds = f"{r['tpl']}={ln}"
        label = r['value'] if not isinstance(r['value'], tuple) else ''.join(str(x) for x in r['value'])
        rules.append((f"{r['tpl']}:{label}"
                      f"@{r['support']}/{r['purity']:.0%}", r["to"], conds))

    with open(args.output, "w", encoding="utf-8") as out:
        out.write(f"# {args.group} 規則，由 induce_rules.py 從 train 自動歸納。\n")
        out.write(f"# 門檻：至少出現 {args.min_support} 次、純度至少 "
                  f"{args.min_purity:.0%}。train 共 {len(train)} 題。\n")
        out.write("# 規則名稱裡的 @N/P% 是該樣式在 train 的支持度與純度，"
                  "方便事後追為什麼收這條。\n")
        out.write(f"GROUP\t{args.group}\nREADING\t{args.reading}\n")
        for name, members in lists.items():
            for m in sorted(set(members)):
                out.write(f"LIST\t{name}\t{m}\n")
        for name, to, conds in rules:
            for other in group_chars:
                if other == to:
                    continue
                out.write(f"RULE\t{name}\t{other}\t{to}\t{conds}\n")

    print(f"train {len(train)} 題　→　收了 {len(rules)} 條規則")
    by_tpl = collections.Counter(r["tpl"] for r in picked)
    for t, n in by_tpl.most_common():
        print(f"  {t:<8}{n}")
    print(f"寫到 {args.output}")


if __name__ == "__main__":
    main()
