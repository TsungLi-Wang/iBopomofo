#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""assemble_newstar_batch.py — 把幾批生成的句子組裝成一份可直接貼小麥的題庫（第 2 關）

做四件事：
  1. 合併多個批次、去重（整句重複、開頭四字重複）
  2. 硬規則篩：答案字剛好一個、無標點空格數字英文、長度範圍
  3. 剔除「詞庫決定」句 —— 原字與鄰字成詞、換字後不成詞，
     引擎靠詞庫就分得開，是送分題（判準同 screen_newstar_batch.py）
  4. 按配額湊出指定句數：兩側各半 × 長度分佈

⚠️ 只剔「詞庫決定」帶。**不要**剔「bigram 無訊號」帶（在說／再說那種）——
   那些意思不同、只是鄰接字判不出來，正是最該考的主力題。

用法：
    python3 assemble_newstar_batch.py a.txt b.txt c.txt -o 在再-100句.txt
    python3 assemble_newstar_batch.py *.txt -o out.txt --target 100 --group 在,再
"""

import argparse
import collections
import re

DATA_TXT = "/Users/johnny.w_macmini/iBopomofo/Source/Data/data.txt"
DIRTY = re.compile(r"[，。、！？：；「」『』（）〈〉…—\s0-9A-Za-z]")
# 依 Johnny 定稿的 100 句實測分佈校準（2026-08-07，中位數 8 字、平均 8.8）。
# 長句已由 Johnny 裁決刪除 —— 台灣人日常打字不打長句，硬生出來的長句不自然。
BUCKETS = [("3-5", 3, 5, 0.22), ("6-8", 6, 8, 0.29),
           ("9-12", 9, 12, 0.40), ("13-16", 13, 16, 0.09)]


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


def dictionary_decided(sentence, idx, target, others, vocab):
    """鄰接位置出現「原字成詞、換字不成詞」→ 引擎一刀切開 → 送分題。"""
    def grams(ch):
        out = []
        if idx > 0:
            out.append(sentence[idx - 1] + ch)
        if idx + 1 < len(sentence):
            out.append(ch + sentence[idx + 1])
        return out
    orig = grams(target)
    for other in others:
        for o, s in zip(orig, grams(other)):
            if o in vocab and s not in vocab:
                return True, f"「{o}」成詞、「{s}」不成詞"
    return False, ""


def trigrams(s):
    """字元 bigram 集合（名字沿用，實際是 2-gram）。"""
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def too_similar(sentence, accepted, threshold):
    """擋掉「同一句換句話說」。開頭四字不同擋不住這種：
      「這件事我們等下週開會再說」／「這件事情我們下週開會再說」
      「室友在補廚房磁磚補到很晚」／「那個室友連日趕工在補廚房磁磚補到很晚」
    幾批用同一份 prompt 生，一定會收斂到同樣場景，不擋就等於同一個模式測很多次。

    用**包含率**（交集 ÷ 較短那邊）而非 Jaccard —— Jaccard 會被長度差稀釋，
    「同一句加長」反而分數最低，正好漏掉最該擋的那種。實測分佈：
      真重複 0.40~0.91　／　不同句 0.00~0.40（門檻 0.45 只放過最輕微的兩組）
    """
    g = trigrams(sentence)
    for other, og in accepted:
        inter = len(g & og)
        if inter and inter / min(len(g), len(og)) >= threshold:
            return other
    return None


def bucket_of(n):
    for name, lo, hi, _ in BUCKETS:
        if lo <= n <= hi:
            return name
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--group", default="在,再")
    ap.add_argument("--target", type=int, default=100)
    ap.add_argument("--data", default=DATA_TXT)
    ap.add_argument("--keep-freebies", action="store_true",
                    help="不剔除詞庫決定句（句源不足時救急用）")
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="既有題庫檔（句子在第一欄）。只餵去重、不佔配額，"
                         "用於第二輪擴充時避免跟已出過的題目重複。")
    ap.add_argument("--sim", type=float, default=0.45,
                    help="近似重複門檻（字元 bigram 包含率），越低擋越兇")
    ap.add_argument("--balance", choices=["equal", "keep-all"], default="equal",
                    help="equal：每個答案字取一樣多（--target 均分），少的那個字會拖垮全組；"
                         "keep-all：全部留著，不砍到齊。"
                         "用 keep-all 時成績要看**每字準確率的平均**（macro），"
                         "不能看整體百分比 —— 否則多數字會主導分數。")
    args = ap.parse_args()

    group = [c.strip() for c in args.group.split(",")]
    vocab = load_vocab(args.data)

    seen_line, seen_head, accepted = set(), set(), []
    pool = collections.defaultdict(list)   # (答案字, 長度帶) -> [句子]
    stats = collections.Counter()
    dupes = []

    for path in args.exclude:
        for raw in open(path, encoding="utf-8"):
            prev = raw.strip().split()[0] if raw.strip() else ""
            if prev:
                seen_line.add(prev); seen_head.add(prev[:4])
                accepted.append((prev, trigrams(prev)))
    if args.exclude:
        print(f"已排除 {len(accepted)} 句既有題目（只去重、不佔配額）\n")

    for path in args.inputs:
        for raw in open(path, encoding="utf-8"):
            line = raw.strip()
            if not line:
                continue
            stats["讀入"] += 1
            if line in seen_line:
                stats["整句重複"] += 1; continue
            hits = [i for i, ch in enumerate(line) if ch in group]
            if len(hits) != 1:
                stats["答案字不是剛好一個"] += 1; continue
            if DIRTY.search(line):
                stats["含標點空格數英"] += 1; continue
            # 簡體字擋掉。生成端偶爾會漏（2026-08-10 一輪 5652 句混進 5 句：
            # 装箱／电视／内科／誤点／硬抠）。詞庫是純繁體，簡體字一律查不到，
            # 拿它當篩子最準 —— 不必外掛 opencc。
            if any(ch not in vocab for ch in line):
                stats["含簡體字或詞庫外字"] += 1; continue
            b = bucket_of(len(line))
            if b is None:
                stats[f"長度出界({len(line)})"] += 1; continue
            if line[:4] in seen_head:
                stats["開頭四字重複"] += 1; continue
            dup = too_similar(line, accepted, args.sim)
            if dup:
                stats["近似重複"] += 1
                dupes.append((line, dup)); continue
            idx = hits[0]
            target = line[idx]
            if not args.keep_freebies:
                dec, why = dictionary_decided(
                    line, idx, target, [c for c in group if c != target], vocab)
                if dec:
                    stats["詞庫決定(送分)"] += 1; continue
            seen_line.add(line); seen_head.add(line[:4])
            accepted.append((line, trigrams(line)))
            pool[(target, b)].append(line)

    if args.balance == "keep-all":
        # 不砍到齊。理由：剔掉送分題之後，有些字（例如「作」）剩不到 50 句 ——
        # 那不是產能不足，是語言事實：那個字在台灣人日常打字裡幾乎只出現在
        # 固定詞裡，引擎靠詞庫就分得開。硬要等量會把另外三個字的好題目一起丟掉。
        # 代價：整體百分比會被多數字主導 → 成績一律看每字準確率的平均（macro）。
        picked = [s for c in group for b, _, _, _ in BUCKETS for s in pool[(c, b)]]
        with open(args.output, "w", encoding="utf-8") as out:
            for s in picked:
                out.write(s + "\n")
        print(f"讀入 {stats['讀入']} → 全數留用 {len(picked)}")
        print("\n── 被剔除的 ──")
        for k, v in stats.most_common():
            if k != "讀入":
                print(f"  {k:<22}{v}")
        print("\n── 每字句數（不等量，成績請看 macro 平均）──")
        for c in group:
            n = sum(len(pool[(c, b)]) for b, _, _, _ in BUCKETS)
            flag = "  ⚠️ 太少，這個字量不出東西" if n < 60 else ""
            print(f"  {c}　{n}{flag}")
        return

    per_char = args.target // len(group)
    picked, short = [], []
    for c in group:
        taken, used = [], {}
        for name, _, _, share in BUCKETS:
            need = round(per_char * share)
            have = pool[(c, name)]
            taken += have[:need]
            used[name] = len(have[:need])
            if len(have) < need:
                short.append((c, name, need - len(have), len(have)))
        # 該字沒湊滿 → 從同一個字的其他長度格補（字數平衡優先於長度分佈）
        if len(taken) < per_char:
            for name, _, _, _ in BUCKETS:
                spare = pool[(c, name)][used[name]:]
                while spare and len(taken) < per_char:
                    taken.append(spare.pop(0))
                    used[name] += 1
        picked += taken

    with open(args.output, "w", encoding="utf-8") as out:
        for s in picked:
            out.write(s + "\n")

    print(f"讀入 {stats['讀入']} → 可用 {sum(len(v) for v in pool.values())} → 取用 {len(picked)}")
    print("\n── 被剔除的 ──")
    for k, v in stats.most_common():
        if k != "讀入":
            print(f"  {k:<22}{v}")
    print("\n── 取用分佈 ──")
    for c in group:
        row = "　".join(f"{n}:{len([s for s in picked if bucket_of(len(s)) == n and c in s])}"
                        for n, _, _, _ in BUCKETS)
        print(f"  {c}　{row}　小計 {sum(1 for s in picked if c in s)}")
    if dupes:
        print(f"\n── 近似重複被剔 {len(dupes)} 句 ──")
        for line, dup in dupes[:15]:
            print(f"  {line}")
            print(f"      ≈ {dup}")
    if len(picked) < args.target:
        print("\n⚠️ 句源不足，需要再生一批：")
        for c, name, miss, have in short:
            print(f"  答案「{c}」× 長度 {name}：缺 {miss} 句（現有 {have}）")
    else:
        if short:
            print("\n（長度配額有偏移，已從同字的其他長度格補滿——字數平衡優先）")
        print(f"\n✅ {len(picked)} 句，{args.output} 可以直接貼小麥了")


if __name__ == "__main__":
    main()
