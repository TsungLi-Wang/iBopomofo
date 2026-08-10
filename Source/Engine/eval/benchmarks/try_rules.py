#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""try_rules.py — 規則表快速試跑（不用編譯引擎）

吃一份規則表，在引擎已經跑完的逐題結果上模擬「規則生效之後會怎樣」，
直接報 **救回幾題、改壞幾題**。

為什麼要有這支：規則要迭代。每改一次清單就重編引擎、重跑 5,646 題太慢，
一輪要好幾分鐘。這支幾秒鐘就給答案，確定有效再寫進 C++。

⚠️ 這支**不是**引擎，是模擬。它只在引擎已經產生的輸出字串上動手，
跟真規則（`ParticleRuleDisambiguator`，掛在 walk 之後）的作用點一樣，
所以結論可以直接套用 —— 但仍然要在引擎裡實作後重跑一次才算數。
用 `--selftest` 可以拿現行的「的/得」規則驗證這支的行為對不對。

用法：
    # 準備逐題結果（引擎跑一次就好）
    /tmp/newstar_homophone_eval <題庫.jsonl> ... shipping 0.75 0.75 <alphas> dump.tsv

    python3 try_rules.py 規則表.tsv --items <題庫.jsonl> --dump dump.tsv
    python3 try_rules.py 規則表.tsv --items ... --dump ... --show 20   # 列出改壞的句子

## 規則表格式（TSV，# 開頭是註解）

    GROUP    前錢                        這組叫什麼
    READING  ㄑㄧㄢˊ                      這組的讀音
    LIST     謂語開頭   別                 清單成員，一行一個
    LIST     謂語開頭   再
    RULE     時間狀語   錢   前   R1=謂語開頭
             ↑規則名   ↑從  ↑改成 ↑條件（分號分隔，要全部成立）

條件寫法（只有這幾種，刻意限制成「只看目標字前後幾個字」）：

    L1=清單   目標字左邊第 1 個字在清單裡      R1=清單   右邊第 1 個字
    L2=清單   左邊第 2 個字                   R2=清單   右邊第 2 個字
    L3=清單   左邊第 3 個字                   R3=清單   右邊第 3 個字
    LW2=清單  左邊兩個字合起來的詞             RW2=清單  右邊兩個字合起來的詞
    END       目標字在句尾                    NOTEND    不在句尾
    START     目標字在句首                    NOTSTART  不在句首
    前面加 !  表示否定，例如 !R1=名詞

規則是**單向**的：`FROM` 是引擎選的那個錯字，`TO` 是要改成的字。
引擎沒選 FROM 的題目完全不碰 —— 這是刻意的，跟「的/得」規則同一個設計：
只修有把握的那個方向，寧可少改不要改錯。
"""

import argparse
import collections
import json
import sys

COND_SLOTS = {"L1", "L2", "L3", "R1", "R2", "R3", "LW2", "RW2", "L1T", "TR1"}
COND_FLAGS = {"END", "NOTEND", "START", "NOTSTART"}
# 特殊清單：@DICT = 引擎詞庫收錄的詞。用來擋「右邊兩個字自己就成詞」那種情況
# ——那代表目標字其實不跟右邊那個字連在一起，規則不該出手。
DICT_LIST = "@DICT"


def load_rules(path):
    meta, lists, rules = {}, collections.defaultdict(set), []
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            f = line.split("\t")
            key = f[0].strip()
            if key in ("GROUP", "READING"):
                meta[key] = f[1].strip()
            elif key == "LIST":
                if len(f) < 3:
                    sys.exit(f"第 {lineno} 行 LIST 少欄位：{line}")
                lists[f[1].strip()].add(f[2].strip())
            elif key == "RULE":
                if len(f) < 5:
                    sys.exit(f"第 {lineno} 行 RULE 要有 名稱/從/改成/條件：{line}")
                conds = [c.strip() for c in f[4].split(";") if c.strip()]
                rules.append({"name": f[1].strip(), "frm": f[2].strip(),
                              "to": f[3].strip(), "conds": conds, "line": lineno})
            else:
                sys.exit(f"第 {lineno} 行不認得的欄位「{key}」：{line}")

    # 條件先驗一次，別讓打錯的清單名安靜地變成「永遠不成立」
    for r in rules:
        for c in r["conds"]:
            body = c[1:] if c.startswith("!") else c
            if body in COND_FLAGS:
                continue
            if "=" not in body:
                sys.exit(f"第 {r['line']} 行條件寫錯：{c}")
            slot, name = body.split("=", 1)
            if slot not in COND_SLOTS:
                sys.exit(f"第 {r['line']} 行沒有這種位置「{slot}」：{c}")
            if name != DICT_LIST and name not in lists:
                sys.exit(f"第 {r['line']} 行用了沒定義的清單「{name}」：{c}")
    return meta, lists, rules


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


def slot_value(chars, i, slot):
    n = len(chars)
    if slot == "L1":
        return chars[i - 1] if i >= 1 else None
    if slot == "L2":
        return chars[i - 2] if i >= 2 else None
    if slot == "R1":
        return chars[i + 1] if i + 1 < n else None
    if slot == "R2":
        return chars[i + 2] if i + 2 < n else None
    if slot == "L3":
        return chars[i - 3] if i >= 3 else None
    if slot == "R3":
        return chars[i + 3] if i + 3 < n else None
    if slot == "LW2":
        return "".join(chars[i - 2:i]) if i >= 2 else None
    if slot == "RW2":
        return "".join(chars[i + 1:i + 3]) if i + 3 <= n else None
    if slot == "L1T":     # 左邊一個字 ＋ 目標字（例如「我的」）
        return "".join(chars[i - 1:i + 1]) if i >= 1 else None
    if slot == "TR1":     # 目標字 ＋ 右邊一個字（例如「得到」）
        return "".join(chars[i:i + 2]) if i + 2 <= n else None
    return None


def cond_holds(cond, chars, i, lists):
    neg = cond.startswith("!")
    body = cond[1:] if neg else cond
    if body in COND_FLAGS:
        n = len(chars)
        got = {"END": i == n - 1, "NOTEND": i != n - 1,
               "START": i == 0, "NOTSTART": i != 0}[body]
    else:
        slot, name = body.split("=", 1)
        v = slot_value(chars, i, slot)
        got = v is not None and v in lists[name]
    return (not got) if neg else got


def parse_rule_conditions(rules, lists, vocab):
    """把 @DICT 換成真的詞庫集合。放在這裡是為了讓 cond_holds 保持單純。"""
    if vocab is not None:
        lists[DICT_LIST] = vocab
    elif any(DICT_LIST in c for r in rules for c in r["conds"]):
        sys.exit(f"規則用到 {DICT_LIST} 但沒給 --data")


def apply_rules(chars, i, rules, lists):
    """回傳 (改成什麼, 哪條規則)。沒有規則出手就回 (None, None)。"""
    cur = chars[i]
    for r in rules:
        if r["frm"] != cur:
            continue
        if all(cond_holds(c, chars, i, lists) for c in r["conds"]):
            return r["to"], r["name"]
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rules", help="規則表 TSV")
    ap.add_argument("--items", required=True, help="題庫 jsonl")
    ap.add_argument("--dump", required=True,
                    help="評分機的逐題結果 tsv（第 9 個參數產生的）")
    ap.add_argument("--show", type=int, default=10, help="列幾句改壞的")
    ap.add_argument("--data", default="", help="引擎詞庫 data.txt，規則用到 @DICT 時必給")
    args = ap.parse_args()

    meta, lists, rules = load_rules(args.rules)
    parse_rule_conditions(rules, lists, load_vocab(args.data) if args.data else None)
    group = meta.get("GROUP", "")
    if not group:
        sys.exit("規則表沒寫 GROUP")

    items = {}
    with open(args.items, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            d = json.loads(line)
            items[d["sentence_id"]] = d

    saved, broken, moved = [], [], []
    n_group = n_correct = 0
    with open(args.dump, encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            f = line.rstrip("\n").split("\t")
            sid, pid, split, ok, out = f[0], f[1], f[2], int(f[3]), f[4]
            if pid != group:
                continue
            d = items.get(sid)
            if d is None:
                continue
            n_group += 1
            n_correct += ok
            chars = list(out)
            i = d["target_index"]
            if i >= len(chars):
                continue
            new, why = apply_rules(chars, i, rules, lists)
            if new is None:
                continue
            now_ok = (new == d["target_char"])
            rec = (d["sentence"], chars[i], new, d["target_char"], why, split)
            moved.append(rec)
            if now_ok and not ok:
                saved.append(rec)
            elif ok and not now_ok:
                broken.append(rec)

    if n_group == 0:
        sys.exit(f"逐題結果裡找不到 pair_id = {group} 的題目")

    base = n_correct
    net = len(saved) - len(broken)
    print(f"組別 {group}　題數 {n_group}")
    print(f"原本答對 {base}（{base * 100 / n_group:.1f}%）")
    print(f"規則出手 {len(moved)} 題　→　救回 {len(saved)}、改壞 {len(broken)}、"
          f"淨 {net:+d}")
    print(f"新分數 {base + net}（{(base + net) * 100 / n_group:.1f}%）")
    if len(moved):
        print(f"出手準確率 {len(saved) * 100 / len(moved):.1f}%"
              f"　（低於 90% 就別上，寧可少改不要改錯）")

    print("\n── 逐條規則 ──")
    per = collections.Counter()
    per_bad = collections.Counter()
    for rec in moved:
        per[rec[4]] += 1
    for rec in broken:
        per_bad[rec[4]] += 1
    for name, n in per.most_common():
        bad = per_bad[name]
        print(f"  {name:<16} 出手 {n:>4}　改壞 {bad:>3}　"
              f"準確 {(n - bad) * 100 / n:>5.1f}%")

    # train / heldout 分開報。規則若是看著封存集調的，那邊的數字不算數。
    print("\n── 分 train / 封存集 ──")
    for sp in ("train", "heldout"):
        s = sum(1 for r in saved if r[5] == sp)
        b = sum(1 for r in broken if r[5] == sp)
        print(f"  {sp:<8} 救回 {s:>4}　改壞 {b:>3}　淨 {s - b:+d}")

    if broken and args.show:
        print(f"\n── 改壞的（最多列 {args.show} 句）──")
        for s, was, now, gold, why, sp in broken[:args.show]:
            print(f"  {s}　本來對的「{was}」被規則「{why}」改成「{now}」")

    print("\n⚠️ 這是模擬。確定要上就寫進 ParticleRuleDisambiguator，"
          "再用評分機重跑一次對照實驗。")


if __name__ == "__main__":
    main()
