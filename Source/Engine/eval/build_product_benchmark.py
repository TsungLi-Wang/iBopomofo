#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棒⑱：把 production 的 `manual-correction.log` 轉成 canonical benchmark。

**只在本機處理。不新增 telemetry、不上傳、不送外部服務、不修改 production。**
輸出寫到 repo 之外（使用者的個人輸入內容不得進 repo）。

## 兩個寫入點，語意不同 —— 這是本檔最重要的 provenance

`ManualCorrectionLog.append` 有兩個呼叫端：

1. `KeyHandler.mm fixNodeWithReading`（打字中選字）
   `wrong_char = ""`、`left_context = 選完之後的整串組字區`。
   **拿不到「引擎原本選什麼」**，而且 left_context **含有 chosen 本身**。
2. `InputMethodController+ShadowReselect.swift`（送出後重選）
   `wrong_char = oldValue`（引擎原本的字）、`left_context` 是真正的左文。
   **這才是「引擎錯了、使用者改掉」的事件。**

## 三種 schema（依欄位數分派，彼此不撞）

* **v2（10 欄，棒⑲ 起）**：`2 \t ISO8601 \t reading \t left_context \t
  engine_choice \t user_choice \t event_type \t source \t candidate_count \t
  candidate_values` —— 前 6 欄與 v1 版面對齊，`engine_choice` 就在 v1 的
  `wrong_char` 位置。**這是唯一能可靠判定引擎原本選什麼的格式。**
* v1（6 欄）：`schemaVer \t ISO8601 \t reading \t left_context \t wrong_char \t chosen`
* v0（4 欄，`272f46ee` 之前）：`ISO8601 \t reading \t left_context \t chosen`
  —— 由結構推斷（185 筆中 184 筆的讀音音節數等於第 4 欄長度），標 `INFERRED`。

## 分層

* **A 可完整 replay**：有 `wrong_char` **且 wrong_char != chosen**
  → 引擎輸出與修正目標都已知，而且真的改變了
* **A-noop**：有 `wrong_char` 但等於 `chosen` —— 使用者重選了同一個字，
  不是引擎錯誤。實測 28 筆裡有 13 筆是這種，**必須排除**，否則會高估可用樣本
* **B 部分 replay**：無 `wrong_char` → 只知道使用者選了什麼，不知道引擎原本選什麼
* **C 不可 replay**：欄位缺失或格式無法判定

用法：
  python3 build_product_benchmark.py --log <manual-correction.log> --out <目錄>
"""

import argparse
import collections
import hashlib
import json
import os
import re

BPMF = re.compile(r"^[ㄅ-ㄩˇˊˋ˙ˉ\-]+$")
ISO = re.compile(r"^\d{4}-\d\d-\d\dT")
SIX = {
    "作做坐座": set("作做坐座"),
    "前錢": set("前錢"),
    "吧八巴": set("吧八巴"),
    "在再": set("在再"),
    "的得": set("的得"),
    "較叫": set("較叫"),
}
SIX_CHARS = set().union(*SIX.values())


def parse(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            f = line.split("\t")
            if len(f) == 10 and f[0] == "2":
                ts, reading, ctx = f[1], f[2], f[3]
                wrong, chosen = f[4], f[5]
                ev, src, ccount, cvals = f[6], f[7], f[8], f[9]
                ver, prov = "v2", "OBSERVED"
                try:
                    ccount = int(ccount)
                except ValueError:
                    ccount = -1
                cands = [c for c in cvals.split("|") if c] if cvals else []
            elif len(f) == 6 and f[0] == "1":
                ts, reading, ctx, wrong, chosen = f[1], f[2], f[3], f[4], f[5]
                ver, prov = "v1", "OBSERVED"
                ev, src, ccount, cands = "", "", -1, []
            elif len(f) == 4 and ISO.match(f[0]):
                ts, reading, ctx, wrong, chosen = f[0], f[1], f[2], "", f[3]
                ver, prov = "v0", "INFERRED"
                ev, src, ccount, cands = "", "", -1, []
            else:
                rows.append({"lineno": lineno, "schema": "UNKNOWN",
                             "tier": "C", "provenance": "UNPARSEABLE"})
                continue
            if not reading or not chosen or not BPMF.match(reading):
                rows.append({"lineno": lineno, "schema": ver, "tier": "C",
                             "provenance": "MISSING_REQUIRED_FIELD"})
                continue
            syl = reading.split("-")
            rows.append({
                "lineno": lineno,
                "schema": ver,
                "provenance": prov,
                "timestamp": ts,
                "reading": reading,
                "n_syllables": len(syl),
                # v1/KeyHandler 與 v0 的 left_context 是「選完之後的整串組字區」，
                # 含 chosen 本身；ShadowReselect 的才是真正左文。旗標記下來。
                "left_context": ctx,
                "left_context_semantics": (
                    "true_left_context" if src == "reselect"
                    else "composing_surface_after_pick"
                ),
                "source": src or ("reselect" if wrong else "composing"),
                "candidate_count": ccount,
                "candidate_values": cands,
                "candidate_truncated": bool(cands) and ccount > len(cands),
                "user_choice_in_candidates": (chosen in cands) if cands else None,
                "engine_output": wrong or None,
                "corrected_value": chosen,
                # 依 PART 9：這是使用者修正，不是語言學金標
                "label_status": "USER_CORRECTION",
                "gold_confidence": "unverified",
                "event_type": ev or (
                    "UNKNOWN_ORIGINAL" if not wrong
                    else "NOOP_RESELECT" if wrong == chosen
                    else "TRUE_CORRECTION"),
                "tier": ("A" if (wrong and wrong != chosen)
                         else "A-noop" if wrong else "B"),
                "is_noop": bool(wrong) and wrong == chosen,
                "syllable_len_matches_value": len(syl) == len(chosen),
                "is_multi_char": len(chosen) > 1,
                "touches_six_groups": bool(set(chosen) & SIX_CHARS) or bool(
                    set(wrong or "") & SIX_CHARS),
            })
    return rows


def event_id(r):
    key = f"{r.get('timestamp','')}|{r.get('reading','')}|" \
          f"{r.get('engine_output') or ''}|{r.get('corrected_value','')}"
    return "MC-" + hashlib.sha256(key.encode()).hexdigest()[:12]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--out", required=True, help="輸出目錄（必須在 repo 之外）")
    args = ap.parse_args()
    assert "/iBopomofo/" not in os.path.abspath(args.out) + "/", \
        "輸出目錄不得在 repo 內（個人輸入內容不進 repo）"
    os.makedirs(args.out, exist_ok=True)

    rows = parse(args.log)
    seen = set()
    for r in rows:
        if r["tier"] == "C":
            continue
        r["event_id"] = event_id(r)
        r["exact_duplicate"] = r["event_id"] in seen
        seen.add(r["event_id"])
    content = collections.Counter(
        (r.get("reading"), r.get("left_context"), r.get("engine_output"),
         r.get("corrected_value")) for r in rows if r["tier"] != "C")
    for r in rows:
        if r["tier"] != "C":
            k = (r["reading"], r["left_context"], r["engine_output"],
                 r["corrected_value"])
            r["content_duplicate_count"] = content[k]

    path = os.path.join(args.out, "items.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    tier = collections.Counter(r["tier"] for r in rows)
    ver = collections.Counter(r.get("schema") for r in rows)
    ev = collections.Counter(r.get("event_type") for r in rows if r["tier"] != "C")
    print(f"事件總數 {len(rows)}")
    print(f"  schema: " + "、".join(f"{k} {v}" for k, v in sorted(ver.items())))
    print(f"  event_type: " + "、".join(f"{k} {v}" for k, v in ev.most_common()))
    cov = [r for r in rows if r.get("user_choice_in_candidates") is not None]
    if cov:
        hit = sum(1 for r in cov if r["user_choice_in_candidates"])
        print(f"  candidate coverage（有候選集的 {len(cov)} 筆）: "
              f"{hit}/{len(cov)} = {hit/len(cov):.1%}")
    print(f"  A   可完整 replay（引擎真的錯了）  : {tier['A']}")
    print(f"  A-noop 重選了同一個字，非引擎錯誤  : {tier['A-noop']}")
    print(f"  B   部分 replay（無 engine_output）: {tier['B']}")
    print(f"  C   不可 replay                    : {tier['C']}")
    print(f"→ {path}")
    with open(os.path.join(args.out, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"source": os.path.abspath(args.log),
                   "total": len(rows), "tiers": dict(tier),
                   "note": "USER_CORRECTION，非語言學金標；只在本機處理，未上傳"},
                  fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
