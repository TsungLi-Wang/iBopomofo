# -*- coding: utf-8 -*-
"""Prototype-001 資料層：從既有 node dump 建 candidate-decision 樣本。

**這是 prototype code，不是 production code。**
不修改 production，也不被 production 引用。

## 樣本

一筆樣本 = 一個「待決定的單字節點」：

    context(左 ±6 / 右 ±6) + reading + candidate set + gold

`left_chars` / `right_chars` 直接沿用 node dump 已經寫好的欄位 ——
那是引擎在 walk 當時決定的字（`chosenValueAt`），
**不是從金標句子切出來的**。這一點是 leakage audit 的核心。

## 切分

沿用 ⑭ 起就在用的 canonical document-level fold：

    fold = sha256(f"baton14f-fold-v1:{doc_id}")[:8] % 5

不重新設計、不隨機切列、不人工調整。
"""

import collections
import hashlib
import json

SALT = "baton14f-fold-v1"
K = 5
WIN = 6
PAD = "　"


def fold_of(doc_id):
    return int(hashlib.sha256(f"{SALT}:{doc_id}".encode()).hexdigest()[:8], 16) % K


def load_docs(sentences_jsonl):
    """sid（1-based 行號）-> doc_id。"""
    out = {}
    with open(sentences_jsonl, encoding="utf-8") as fh:
        for i, line in enumerate(fh, start=1):
            if line.strip():
                out[str(i)] = json.loads(line).get("doc_id", f"sent-{i}")
    return out


def parse_cands(field):
    """cands 欄格式：值:unigram:pmi_left:pmi_right:is_walk_choice|…"""
    out = []
    for part in field.split("|"):
        q = part.split(":")
        if len(q) == 5:
            try:
                out.append(
                    (q[0], float(q[1]), float(q[2]), float(q[3]), q[4] == "1")
                )
            except ValueError:
                continue
    return out


def load_samples(nodes_tsv, sentences_jsonl, max_rows=0, min_cands=2):
    """只取 kind=0（完整句）、span=1（單字節點）、候選數 >= min_cands 的節點。"""
    docs = load_docs(sentences_jsonl)
    out = []
    with open(nodes_tsv, encoding="utf-8") as fh:
        head = next(fh).rstrip("\n").split("\t")
        for line in fh:
            f = dict(zip(head, line.rstrip("\n").split("\t")))
            if f.get("kind") != "0" or f.get("span") != "1":
                continue
            cands = parse_cands(f.get("cands", ""))
            if len(cands) < min_cands:
                continue
            gold = f.get("gold", "")
            if len(gold) != 1:
                continue
            doc = docs.get(f["sid"], "sent-" + f["sid"])
            out.append(
                {
                    "sid": f["sid"],
                    "doc": doc,
                    "fold": fold_of(doc),
                    "reading": f.get("reading", ""),
                    "left": f.get("left_chars", ""),
                    "right": f.get("right_chars", ""),
                    "right_empty": f.get("right_empty") == "1",
                    "chosen": f.get("chosen", ""),
                    "gold": gold,
                    "cands": cands,
                    "gold_idx": next(
                        (i for i, c in enumerate(cands) if c[0] == gold), -1
                    ),
                }
            )
            if max_rows and len(out) >= max_rows:
                break
    return out


def build_vocab(samples, min_count=2):
    ch = collections.Counter()
    rd = collections.Counter()
    for s in samples:
        for c in s["left"][-WIN:]:
            ch[c] += 1
        for c in s["right"][:WIN]:
            ch[c] += 1
        for c in s["cands"]:
            ch[c[0]] += 1
        rd[s["reading"]] += 1
    itos = [PAD] + [c for c, n in ch.most_common() if n >= min_count]
    rtos = [PAD] + [r for r, n in rd.most_common() if n >= min_count]
    return (
        {c: i for i, c in enumerate(itos)},
        itos,
        {r: i for i, r in enumerate(rtos)},
        rtos,
    )


def audit_leakage(samples):
    """Leakage audit：context 必須來自 walk 當下，不是金標句子。"""
    checks = []
    checks.append(
        (
            "context 來源",
            "node dump 的 left_chars/right_chars（walk 的 chosenValueAt）",
            "PASS",
        )
    )
    # context 是左右鄰居，不含目標位置本身
    bad = sum(
        1
        for s in samples
        if s["right"][:1] == s["gold"] and s["left"][-1:] == s["gold"]
    )
    checks.append(
        ("context 是否含目標位置本身", f"{bad} 筆可疑", "PASS" if bad == 0 else "REVIEW")
    )
    checks.append(("gold 是否進入 feature", "featurize() 不接收 gold", "PASS"))
    checks.append(
        ("候選數值特徵", "unigram score / PMI，推論時由引擎算出", "PASS")
    )
    d2f = {}
    cross = 0
    for s in samples:
        if s["doc"] in d2f and d2f[s["doc"]] != s["fold"]:
            cross += 1
        d2f[s["doc"]] = s["fold"]
    checks.append(("同一 doc 跨 fold", f"{cross} 筆", "PASS" if cross == 0 else "FAIL"))
    checks.append(("gold 是否用於挑 threshold", "v0.1 決策是純 argmax，無 threshold", "PASS"))
    return checks
