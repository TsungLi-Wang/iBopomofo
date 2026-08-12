#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_newstar_jsonl.py — 新北極星出題管線第 3 關

輸入：每行「連續漢字句子 + 小麥注音」（小麥線上注音工具的貼回結果）
輸出：newstar_homophone_eval 吃的 JSONL

腳本自己認答案：句中屬於 GROUP 的字必須剛好出現一個，那個字就是該題答案，
同組其餘字自動成為干擾字。零手動標記。換組只改下面 GROUP/PAIR_READING/PAIR_ID
（或用 --group / --reading / --pair-id 覆蓋）。

用法：
    python3 make_newstar_jsonl.py in.txt -o out.jsonl
    python3 make_newstar_jsonl.py in.txt -o out.jsonl --group 是,事,式 --reading ㄕˋ
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# ── 換組改這三行就好 ────────────────────────────────────────────
GROUP = ["在", "再"]          # 這組的候選字，順序不重要
PAIR_READING = "ㄗㄞˋ"        # 這組共同的讀音
PAIR_ID = "在/再"             # 逐對表用的 ID（雙向合併計分）
# ────────────────────────────────────────────────────────────

WEIGHT = 1.0                  # 該對的頻率權重（進 headline 加權）
TIER = "single"
HELDOUT_RATIO = 0.2           # 切多少當 held-out（決定性切分，重跑結果一樣）

_REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_TXT = __import__("os").environ.get(
    "IBOPOMOFO_DATA_TXT", str(_REPO_ROOT / "Source" / "Data" / "data.txt"))
BOPOMOFO = "".join(chr(c) for c in range(0x3105, 0x312A))  # ㄅ..ㄦ
TONES = "ˊˇˋ˙"                                             # 二三四聲＋輕聲（一聲不標）
INITIALS = set("ㄅㄆㄇㄈㄉㄊㄋㄌㄍㄎㄏㄐㄑㄒㄓㄔㄕㄖㄗㄘㄙ")
MEDIALS = set("ㄧㄨㄩ")
FINALS = set("ㄚㄛㄜㄝㄞㄟㄠㄡㄢㄣㄤㄥㄦ")
HAN = re.compile(r"^[㐀-䶿一-鿿豈-﫿]+$")


def split_sentence_and_reading(line):
    """用第一個注音符號切開「句子」與「注音」。"""
    for i, ch in enumerate(line):
        if ch in BOPOMOFO or ch in TONES:
            return line[:i].strip(), line[i:].strip()
    return line.strip(), ""


def clean_reading(raw):
    """只留注音符號、聲調與空白；其餘（數字、括號、標點）一律丟掉。"""
    return "".join(ch if (ch in BOPOMOFO or ch in TONES) else " " for ch in raw)


def segment_syllables(cleaned):
    """把清乾淨的注音串切成音節。有空白就照空白切，沒有就用結構規則自動切。"""
    if cleaned.split():
        parts = cleaned.split()
        if len(parts) > 1:
            return parts
        cleaned = parts[0]
    else:
        return []

    syllables, cur, seen_final, seen_medial = [], "", False, False
    for ch in cleaned:
        if ch in TONES:
            if ch == "˙" and cur == "":
                cur = ch  # 輕聲標在音節前的寫法
                continue
            cur += ch
            syllables.append(cur)
            cur, seen_final, seen_medial = "", False, False
            continue
        # 聲母、或已經看過韻母、或介音重複 → 開新音節（前一個是一聲）
        starts_new = cur and (ch in INITIALS or seen_final or (ch in MEDIALS and seen_medial))
        if starts_new:
            syllables.append(cur)
            cur, seen_final, seen_medial = "", False, False
        cur += ch
        if ch in FINALS:
            seen_final = True
        if ch in MEDIALS:
            seen_medial = True
    if cur:
        syllables.append(cur)
    return syllables


def normalize(syl):
    """一聲不標；其餘保留聲調符號。輕聲統一移到字尾。"""
    if syl.startswith("˙"):
        syl = syl[1:] + "˙"
    return syl


def load_word_readings(path):
    """詞 → 該詞所有合法讀音序列（tuple）的集合，取自引擎詞庫。

    小麥線上工具是自動標音，破音字會標錯（得 ㄉㄜˊ／ㄉㄟˇ／˙ㄉㄜ、
    還 ㄏㄞˊ／ㄏㄨㄢˊ、了、行、重、長…）。標錯 → lattice 就錯 → 那題測到的
    不是我們要測的東西。

    單字級檢查在破音字上是瞎的（多個讀音都「合法」），所以要看**詞**：
    「還好」在詞庫裡就只有 ㄏㄞˊ-ㄏㄠˇ，標成 ㄏㄨㄢˊ-ㄏㄠˇ 就抓得到。
    """
    table = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            reading, word = parts[0], parts[1]
            syls = tuple(reading.split("-"))
            if len(syls) != len(word):
                continue
            table.setdefault(word, set()).add(syls)
    return table


def check_readings(sentence, syllables, word_readings, max_n=4):
    """用詞庫裡的多字詞核對讀音。回傳 [(起點, 詞, 標到的音, 詞庫的音)]。

    只在「這段字剛好是詞庫裡的詞，且該詞所有登錄讀音都對不上」時才報，
    所以不會因為斷詞歧義亂噴。長詞優先，報過的位置不重複報。
    """
    bad, covered = [], set()
    for n in range(max_n, 1, -1):
        for i in range(len(sentence) - n + 1):
            if any(j in covered for j in range(i, i + n)):
                continue
            word = sentence[i:i + n]
            legal = word_readings.get(word)
            if not legal:
                continue
            got = tuple(syllables[i:i + n])
            if got not in legal:
                bad.append((i, word, "-".join(got),
                            " / ".join("-".join(s) for s in sorted(legal)[:3])))
            covered.update(range(i, i + n))
    return sorted(bad)


def is_heldout(sentence, ratio):
    """決定性切分：同一句永遠落在同一邊，重跑不會換組。"""
    h = int(hashlib.sha256(sentence.encode("utf-8")).hexdigest()[:8], 16)
    return (h % 1000) < ratio * 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="小麥注音貼回的 txt（每行：句子＋注音）")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--group", help="逗號分隔的候選字，覆蓋檔頭 GROUP")
    ap.add_argument("--reading", help="覆蓋檔頭 PAIR_READING")
    ap.add_argument("--pair-id", help="覆蓋檔頭 PAIR_ID")
    ap.add_argument("--weight", type=float, default=WEIGHT)
    ap.add_argument("--tier", default=TIER)
    ap.add_argument("--heldout-ratio", type=float, default=HELDOUT_RATIO)
    ap.add_argument("--train-only", default="",
                    help="一行一句的檔案；裡面的句子一律歸 train，不准進封存集。"
                         "用途：調機制時看過的句子（例如推 particle-rules.tsv 那批）"
                         "留在題庫裡沒關係，但拿它當考題等於考自己出的題 —— "
                         "分數會虛高，而且是那種事後看不出來的虛高。")
    ap.add_argument("--domain", default="")
    ap.add_argument("--source", default="")
    ap.add_argument("--id-prefix", default="")
    ap.add_argument("--data", default=DATA_TXT, help="引擎詞庫，用來查破音字")
    ap.add_argument("--strict-readings", action="store_true",
                    help="破音字可疑的句子直接 REJECT（預設只警告、仍收下）")
    ap.add_argument("--fix-target-reading", action="store_true",
                    help="把答案位的讀音強制改成該組讀音，並逐句列出改了什麼。\n"
                         "用於小麥把答案字標成別的破音（例：補語的「得」被標成 ㄉㄜˊ，"
                         "但「的」只有 ㄉㄜ˙，標成 ㄉㄜˊ 就沒有混淆可言、那題白測）。"
                         "只動答案位，其餘位置不碰。")
    args = ap.parse_args()

    word_readings = load_word_readings(args.data)

    group = [c.strip() for c in args.group.split(",")] if args.group else list(GROUP)
    pair_reading = normalize(args.reading or PAIR_READING)
    pair_id = args.pair_id or PAIR_ID
    prefix = args.id_prefix or (pair_id.replace("/", "") + "-")

    train_only = set()
    if args.train_only:
        with open(args.train_only, encoding="utf-8") as fh:
            for raw in fh:
                s = raw.strip().split()
                if s:
                    train_only.add(s[0])

    kept, rejected, suspect, fixed = [], 0, [], []
    with open(args.input, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line:
                continue

            def reject(reason):
                nonlocal rejected
                rejected += 1
                print(f"REJECT line={lineno} reason={reason} :: {line}", file=sys.stderr)

            sentence, reading_raw = split_sentence_and_reading(line)
            if not sentence:
                reject("空句子"); continue
            if not HAN.match(sentence):
                reject("句子含非漢字（標點／空格／數字／英文）"); continue

            hits = [i for i, ch in enumerate(sentence) if ch in group]
            if len(hits) != 1:
                reject(f"句中該組候選字出現 {len(hits)} 次（必須剛好 1 次）"); continue
            idx = hits[0]
            target = sentence[idx]

            syllables = [normalize(s) for s in segment_syllables(clean_reading(reading_raw))]
            if not syllables:
                reject("沒有注音"); continue
            if len(syllables) != len(sentence):
                reject(f"音節數 {len(syllables)} != 字數 {len(sentence)}"); continue
            if syllables[idx] != pair_reading:
                if args.fix_target_reading:
                    fixed.append((lineno, sentence, syllables[idx]))
                    syllables[idx] = pair_reading
                else:
                    reject(f"答案位讀音 {syllables[idx]} != {pair_reading}"); continue

            bad = check_readings(sentence, syllables, word_readings)
            if bad:
                detail = "；".join(
                    f"第{i + 1}字起「{word}」標成 {got}（詞庫：{legal}）"
                    for i, word, got, legal in bad)
                if args.strict_readings:
                    reject(f"破音字可疑 → {detail}"); continue
                suspect.append((lineno, line, detail))

            wrong = [c for c in group if c != target]
            kept.append({
                "sentence_id": f"{prefix}{len(kept) + 1:04d}",
                "sentence": sentence,
                "target_index": idx,
                "target_char": target,
                "wrong_chars": wrong,
                "reading": pair_reading,
                "pair_id": pair_id,
                "n_way": 1 + len(wrong),
                "weight": args.weight,
                "tier": args.tier,
                "split": "train" if sentence in train_only
                         else ("heldout" if is_heldout(sentence, args.heldout_ratio) else "train"),
                "domain": args.domain,
                "full_reading": " ".join(syllables),
                "source": args.source,
            })

    with open(args.output, "w", encoding="utf-8") as out:
        for item in kept:
            out.write(json.dumps(item, ensure_ascii=False) + "\n")

    dist = {c: sum(1 for k in kept if k["target_char"] == c) for c in group}
    heldout = sum(1 for k in kept if k["split"] == "heldout")
    print(f"KEPT={len(kept)} REJECTED={rejected}")
    print(f"ANSWER_DIST={dist}")
    print(f"SPLIT train={len(kept) - heldout} heldout={heldout}")
    if rejected:
        print("（REJECT 明細見上方 stderr）")
    if fixed:
        print(f"\n🔧 答案位讀音已強制修正 {len(fixed)} 句（--fix-target-reading）")
        by = {}
        for lineno, sent, got in fixed:
            by.setdefault(got, []).append(sent)
        for got, sents in by.items():
            print(f"  {got} → {pair_reading}　{len(sents)} 句　例：{'、'.join(sents[:3])}")
    if suspect:
        print(f"\n⚠️ 破音字可疑 {len(suspect)} 句（已收下，但注音可能被小麥標錯，"
              f"請人工看一眼；要直接擋掉加 --strict-readings）")
        for lineno, line, detail in suspect:
            print(f"  line={lineno} {line.split()[0] if line.split() else line}")
            print(f"      {detail}")


if __name__ == "__main__":
    main()
