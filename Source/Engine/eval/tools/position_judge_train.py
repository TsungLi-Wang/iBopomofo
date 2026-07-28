#!/usr/bin/env python3
"""Baton C: position-level homophone judge — data, train, eval.

Pure research. Does not touch product shipping path.

Pipeline:
  1) Build clean + noisy training sets from spoken corpus + reading2chars
  2) Train BiLSTM char encoder + reading emb (5–20M params)
  3) Evaluate gold-prefix / shipping-context position accuracy
  4) Export flip proposals for analyze_flip_gates.py

Usage examples:
  python position_judge_train.py build-data
  python position_judge_train.py train --variant clean
  python position_judge_train.py train --variant noisy
  python position_judge_train.py eval --ckpt ...
  python position_judge_train.py all
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import struct
import time
from collections import Counter, defaultdict
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset

HAN_RE = re.compile(r"[\u4e00-\u9fff]")
POLLUTE_BOARDS = {
    "Stock",
    "PC_Shopping",
    "Tech_Job",
    "WomenTalk",
    "movie",
    "Food",
    "Lifeismoney",
    "Soft_Job",
    "MobileComm",
    "car",
    "C_Chat",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(8 * 1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_reading2chars(path: Path) -> dict[str, list[tuple[str, int]]]:
    r2c: dict[str, list[tuple[str, int]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line[0] == "#":
            continue
        tab = line.find("\t")
        if tab < 0:
            continue
        reading, body = line[:tab], line[tab + 1 :]
        items = []
        for part in body.split(","):
            if ":" not in part:
                continue
            ch, cnt = part.rsplit(":", 1)
            try:
                items.append((ch, int(cnt)))
            except ValueError:
                continue
        if items:
            r2c[reading] = items
    return r2c


def invert_char_reading(r2c: dict[str, list[tuple[str, int]]]) -> dict[str, str]:
    """char -> reading with max count."""
    best: dict[str, tuple[int, str]] = {}
    for rd, items in r2c.items():
        for ch, cnt in items:
            if ch not in best or cnt > best[ch][0]:
                best[ch] = (cnt, rd)
    return {ch: rd for ch, (_, rd) in best.items()}


def load_tw538(path: Path) -> list[tuple[str, str]]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line[0] == "#":
            continue
        r, e = line.split("\t", 1)
        cases.append((r, e))
    return cases


# ---------------------------------------------------------------------------
# Data build
# ---------------------------------------------------------------------------


def build_data(args: argparse.Namespace) -> None:
    data_dir = Path(args.data_dir)
    out_dir = data_dir / "batonC-traindata"
    out_dir.mkdir(parents=True, exist_ok=True)

    r2c = load_reading2chars(data_dir / "reading2chars.tsv")
    char2rd = invert_char_reading(r2c)
    # candidate list (chars only, sorted by count)
    r2clist = {rd: [c for c, _ in items] for rd, items in r2c.items()}
    r2ccount = {rd: {c: n for c, n in items} for rd, items in r2c.items()}

    cases = load_tw538(
        Path(args.repo) / "Source/Engine/eval/benchmarks/tw538-northstar.tsv"
    )
    tw538_golds = {e for _, e in cases}

    spoken = data_dir / "ptt_spoken_train_v2.txt"
    max_sents = args.max_sents
    max_samples = args.max_samples
    min_len, max_len = 4, 40
    noise_p = args.noise_p

    # Streaming: each line is a sentence (may contain spaces)
    clean_path = out_dir / "samples_clean.jsonl"
    noisy_path = out_dir / "samples_noisy.jsonl"
    stats = Counter()
    pollution_hits = 0
    pollution_examples = []

    rng = random.Random(42)
    t0 = time.time()

    def maybe_noise(chars: list[str], readings: list[str], target_i: int) -> list[str]:
        out = chars[:]
        for j in range(len(chars)):
            if j == target_i:
                continue
            if rng.random() >= noise_p:
                continue
            rd = readings[j]
            cands = r2clist.get(rd, [])
            # pick another char with similar freq if possible
            alts = [c for c in cands if c != chars[j]]
            if not alts:
                continue
            # prefer mid-frequency alts: top half of remaining
            counts = r2ccount.get(rd, {})
            alts_sorted = sorted(alts, key=lambda c: counts.get(c, 0), reverse=True)
            # pick from top-min(5, len) excluding exact same rank noise
            pool = alts_sorted[: max(3, min(8, len(alts_sorted)))]
            out[j] = rng.choice(pool)
            stats["noise_replacements"] += 1
        return out

    n_clean = n_noisy = 0
    with spoken.open(encoding="utf-8", errors="replace") as fin, clean_path.open(
        "w", encoding="utf-8"
    ) as fc, noisy_path.open("w", encoding="utf-8") as fn:
        for line_i, line in enumerate(fin):
            if max_sents and line_i >= max_sents:
                break
            raw = line.strip()
            if not raw:
                continue
            # drop board-tagged lines if present
            # compact han-only sequence
            chars = [c for c in raw if "\u4e00" <= c <= "\u9fff"]
            if not (min_len <= len(chars) <= max_len):
                stats["skip_len"] += 1
                continue
            text = "".join(chars)
            # pollution: exact gold string match
            if text in tw538_golds:
                pollution_hits += 1
                if len(pollution_examples) < 5:
                    pollution_examples.append(text)
                stats["pollution_skip"] += 1
                continue
            # assign readings
            readings = []
            ok = True
            for ch in chars:
                rd = char2rd.get(ch)
                if not rd:
                    ok = False
                    break
                readings.append(rd)
            if not ok:
                stats["skip_no_reading"] += 1
                continue

            # positions with |C|>1
            for i, rd in enumerate(readings):
                cands = r2clist.get(rd, [])
                if len(cands) <= 1:
                    stats["skip_unambiguous"] += 1
                    continue
                gold = chars[i]
                if gold not in cands:
                    # still keep if we can add gold
                    cands = list(cands) + [gold]
                sample = {
                    "chars": chars,
                    "readings": readings,
                    "i": i,
                    "reading": rd,
                    "gold": gold,
                    "cands": cands[:32],  # cap extreme
                }
                fc.write(json.dumps(sample, ensure_ascii=False) + "\n")
                n_clean += 1
                # noisy context version
                nchars = maybe_noise(chars, readings, i)
                nsample = {
                    "chars": nchars,
                    "readings": readings,
                    "i": i,
                    "reading": rd,
                    "gold": gold,
                    "cands": cands[:32],
                }
                fn.write(json.dumps(nsample, ensure_ascii=False) + "\n")
                n_noisy += 1
                if max_samples and n_clean >= max_samples:
                    break
            if max_samples and n_clean >= max_samples:
                break
            if (line_i + 1) % 200000 == 0:
                print(
                    f"  lines={line_i+1} clean_samples={n_clean} pollute={pollution_hits}",
                    flush=True,
                )

    # Full pollution check: also substring? baton says full sentence string match
    # re-scan remaining file only for exact gold hits if we early-stopped samples
    # Do full exact-line compact match over entire spoken for the 537
    print("Full pollution scan over spoken corpus...", flush=True)
    hit_counts = Counter()
    with spoken.open(encoding="utf-8", errors="replace") as fin:
        for line in fin:
            compact = "".join(c for c in line if "\u4e00" <= c <= "\u9fff")
            if compact in tw538_golds:
                hit_counts[compact] += 1
    pollution_total = sum(hit_counts.values())
    pollution_unique = len(hit_counts)

    meta = {
        "n_clean": n_clean,
        "n_noisy": n_noisy,
        "noise_p": noise_p,
        "pollution_hits_during_build": pollution_hits,
        "pollution_full_scan_occurrences": pollution_total,
        "pollution_full_scan_unique": pollution_unique,
        "pollution_examples": pollution_examples,
        "pollution_hit_golds": list(hit_counts.keys())[:10],
        "stats": dict(stats),
        "elapsed_s": time.time() - t0,
        "spoken": str(spoken),
        "r2c_sha": sha256_file(data_dir / "reading2chars.tsv"),
    }
    # IMPORTANT: if pollution in training samples we skipped them; full scan is inventory
    # Training set excludes exact matches when compact text == gold.
    # If pollution_total > 0, those lines exist in corpus but were skipped when encountered
    # during sample build — still report. Baton stops if training set contains them.
    # Verify training files don't contain golds:
    train_hits = 0
    for path in (clean_path, noisy_path):
        with path.open(encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line)
                text = "".join(obj["chars"])
                if text in tw538_golds:
                    train_hits += 1
    meta["train_file_tw538_hits"] = train_hits
    (out_dir / "build_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print("clean_sha", sha256_file(clean_path))
    print("noisy_sha", sha256_file(noisy_path))
    if train_hits > 0:
        print("FATAL pollution in train files", train_hits)
        raise SystemExit(3)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class PositionJudge(nn.Module):
    """BiLSTM over chars; target reading emb; vocab logits masked to C_i."""

    def __init__(
        self,
        n_chars: int,
        n_readings: int,
        emb: int = 256,
        hid: int = 384,
        layers: int = 2,
        rd_emb: int = 64,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.emb = nn.Embedding(n_chars, emb, padding_idx=0)
        self.rd_emb = nn.Embedding(n_readings, rd_emb, padding_idx=0)
        self.mask_id = 1  # reserved
        self.lstm = nn.LSTM(
            emb,
            hid,
            num_layers=layers,
            batch_first=True,
            bidirectional=True,
            dropout=dropout if layers > 1 else 0.0,
        )
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hid * 2 + rd_emb, n_chars)
        self.n_chars = n_chars

    def forward(
        self,
        char_ids: torch.Tensor,
        lengths: torch.Tensor,
        target_pos: torch.Tensor,
        reading_ids: torch.Tensor,
    ) -> torch.Tensor:
        """
        char_ids: [B, T] with target positions already set to MASK
        lengths: [B]
        target_pos: [B]
        reading_ids: [B]
        returns logits [B, n_chars]
        """
        x = self.emb(char_ids)  # [B,T,E]
        packed = nn.utils.rnn.pack_padded_sequence(
            x, lengths.cpu(), batch_first=True, enforce_sorted=False
        )
        out, _ = self.lstm(packed)
        out, _ = nn.utils.rnn.pad_packed_sequence(out, batch_first=True)
        # gather target position
        B = char_ids.size(0)
        idx = target_pos.view(B, 1, 1).expand(B, 1, out.size(-1))
        h = out.gather(1, idx).squeeze(1)  # [B, 2H]
        r = self.rd_emb(reading_ids)
        h = self.dropout(torch.cat([h, r], dim=-1))
        return self.fc(h)

    def parameter_count(self) -> int:
        return sum(p.numel() for p in self.parameters())


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


class JudgeDataset(Dataset):
    def __init__(
        self,
        path: Path,
        char2id: dict[str, int],
        rd2id: dict[str, int],
        max_len: int = 40,
        limit: int | None = None,
    ):
        self.rows = []
        with path.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if limit and i >= limit:
                    break
                self.rows.append(json.loads(line))
        self.char2id = char2id
        self.rd2id = rd2id
        self.max_len = max_len
        self.unk = char2id["<unk>"]
        self.mask = char2id["<mask>"]
        self.pad = char2id["<pad>"]

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, idx: int):
        o = self.rows[idx]
        chars = o["chars"][: self.max_len]
        i = min(o["i"], len(chars) - 1)
        ids = [self.char2id.get(c, self.unk) for c in chars]
        ids[i] = self.mask
        gold_id = self.char2id.get(o["gold"], self.unk)
        rd_id = self.rd2id.get(o["reading"], 0)
        cand_ids = [self.char2id.get(c, self.unk) for c in o["cands"]]
        return {
            "ids": ids,
            "pos": i,
            "rd": rd_id,
            "gold": gold_id,
            "cands": cand_ids,
            "gold_char": o["gold"],
            "reading": o["reading"],
            "cands_chars": o["cands"],
        }


def collate(batch):
    B = len(batch)
    lengths = torch.tensor([len(b["ids"]) for b in batch], dtype=torch.long)
    T = int(lengths.max())
    ids = torch.zeros(B, T, dtype=torch.long)
    pos = torch.zeros(B, dtype=torch.long)
    rd = torch.zeros(B, dtype=torch.long)
    gold = torch.zeros(B, dtype=torch.long)
    # cand mask matrix
    # store list
    cands = []
    for i, b in enumerate(batch):
        L = len(b["ids"])
        ids[i, :L] = torch.tensor(b["ids"], dtype=torch.long)
        pos[i] = b["pos"]
        rd[i] = b["rd"]
        gold[i] = b["gold"]
        cands.append(b["cands"])
    return {
        "ids": ids,
        "lengths": lengths,
        "pos": pos,
        "rd": rd,
        "gold": gold,
        "cands": cands,
        "meta": batch,
    }


def masked_ce(logits: torch.Tensor, gold: torch.Tensor, cands: list[list[int]]) -> torch.Tensor:
    """CE after masking to candidates (set non-cand to large negative)."""
    B, V = logits.shape
    # Stable mask: -50 is enough to zero-out softmax without fp overflow on MPS
    neg = torch.tensor(-50.0, device=logits.device, dtype=logits.dtype)
    masked = logits.clone()
    for i in range(B):
        allow = set(cands[i])
        if not allow:
            continue
        # ensure gold is allowed
        allow.add(int(gold[i].item()))
        mask = torch.ones(V, dtype=torch.bool, device=logits.device)
        idx = torch.tensor(list(allow), device=logits.device, dtype=torch.long)
        mask[idx] = False
        masked[i] = torch.where(mask, neg, masked[i])
    return F.cross_entropy(masked, gold)


def restricted_argmax(
    logits: torch.Tensor, cands: list[list[int]]
) -> torch.Tensor:
    B, V = logits.shape
    out = torch.zeros(B, dtype=torch.long, device=logits.device)
    for i in range(B):
        if not cands[i]:
            out[i] = int(logits[i].argmax())
            continue
        idx = torch.tensor(cands[i], device=logits.device, dtype=torch.long)
        local = logits[i].index_select(0, idx)
        out[i] = idx[int(local.argmax())]
    return out


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------


def build_vocabs(clean_path: Path, limit: int = 500000):
    chars = Counter()
    readings = Counter()
    with clean_path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= limit:
                break
            o = json.loads(line)
            for c in o["chars"]:
                chars[c] += 1
            readings[o["reading"]] += 1
            for c in o["cands"]:
                chars[c] += 1
    # specials
    char2id = {"<pad>": 0, "<mask>": 1, "<unk>": 2}
    for c, _ in chars.most_common():
        if c not in char2id:
            char2id[c] = len(char2id)
    rd2id = {"<pad>": 0}
    for r, _ in readings.most_common():
        if r not in rd2id:
            rd2id[r] = len(rd2id)
    return char2id, rd2id


def train_variant(args: argparse.Namespace) -> Path:
    data_dir = Path(args.data_dir)
    out_dir = data_dir / f"batonC-model-{args.variant}"
    out_dir.mkdir(parents=True, exist_ok=True)
    train_path = data_dir / "batonC-traindata" / f"samples_{args.variant}.jsonl"
    if not train_path.exists():
        # noisy file is samples_noisy.jsonl
        if args.variant == "noisy":
            train_path = data_dir / "batonC-traindata" / "samples_noisy.jsonl"
        else:
            train_path = data_dir / "batonC-traindata" / "samples_clean.jsonl"

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    print(f"device={device} variant={args.variant} data={train_path}", flush=True)

    # vocabs from clean always (shared)
    clean_path = data_dir / "batonC-traindata" / "samples_clean.jsonl"
    char2id, rd2id = build_vocabs(clean_path, limit=args.vocab_scan)
    id2char = {i: c for c, i in char2id.items()}
    (out_dir / "char2id.json").write_text(
        json.dumps(char2id, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "rd2id.json").write_text(
        json.dumps(rd2id, ensure_ascii=False), encoding="utf-8"
    )

    model = PositionJudge(
        n_chars=len(char2id),
        n_readings=len(rd2id),
        emb=args.emb,
        hid=args.hid,
        layers=args.layers,
        rd_emb=args.rd_emb,
    ).to(device)
    nparam = model.parameter_count()
    print(f"params={nparam} ({nparam/1e6:.2f}M)", flush=True)
    if not (5_000_000 <= nparam <= 20_000_000):
        print(f"WARNING params {nparam} outside 5–20M band", flush=True)

    # dataset: use subset for speed if needed
    ds = JudgeDataset(train_path, char2id, rd2id, limit=args.train_limit)
    # train/val split 95/5
    n = len(ds)
    n_val = max(1000, n // 20)
    n_train = n - n_val
    g = torch.Generator().manual_seed(42)
    train_ds, val_ds = torch.utils.data.random_split(ds, [n_train, n_val], generator=g)
    train_loader = DataLoader(
        train_ds,
        batch_size=args.batch,
        shuffle=True,
        collate_fn=collate,
        num_workers=0,
    )
    val_loader = DataLoader(
        val_ds, batch_size=args.batch, shuffle=False, collate_fn=collate, num_workers=0
    )
    print(f"train={n_train} val={n_val}", flush=True)

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    log_path = out_dir / "train.log"
    log_f = log_path.open("w", encoding="utf-8")

    def log(msg: str) -> None:
        print(msg, flush=True)
        log_f.write(msg + "\n")
        log_f.flush()

    # G1 baseline from args
    v2c_baseline = args.v2c_baseline  # fraction
    t_start = time.time()
    max_seconds = args.max_hours * 3600
    g1_deadline = t_start + 3600  # ~1h first checkpoint
    g2_deadline = t_start + 3 * 3600
    step = 0
    best_val = -1.0
    history = []
    g1_passed = False
    stopped_reason = "completed"

    model.train()
    epoch = 0
    while time.time() - t_start < max_seconds:
        epoch += 1
        epoch_loss = 0.0
        n_batches = 0
        for batch in train_loader:
            if time.time() - t_start >= max_seconds:
                stopped_reason = "time_budget"
                break
            ids = batch["ids"].to(device)
            lengths = batch["lengths"]
            pos = batch["pos"].to(device)
            rd = batch["rd"].to(device)
            gold = batch["gold"].to(device)
            opt.zero_grad()
            logits = model(ids, lengths, pos, rd)
            loss = masked_ce(logits, gold, batch["cands"])
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            epoch_loss += float(loss.item())
            n_batches += 1
            step += 1

            # periodic val / gates
            if step % args.eval_every == 0 or (
                not g1_passed and time.time() >= g1_deadline and step > 50
            ):
                acc = eval_loader(model, val_loader, device)
                elapsed = time.time() - t_start
                log(
                    f"step={step} epoch={epoch} loss={epoch_loss/max(n_batches,1):.4f} "
                    f"val_acc={acc:.4f} elapsed_h={elapsed/3600:.2f}"
                )
                history.append(
                    {"step": step, "val_acc": acc, "elapsed_h": elapsed / 3600}
                )
                ckpt = out_dir / f"ckpt_step{step}.pt"
                torch.save(
                    {
                        "model": model.state_dict(),
                        "char2id": char2id,
                        "rd2id": rd2id,
                        "args": vars(args),
                        "val_acc": acc,
                        "nparam": nparam,
                    },
                    ckpt,
                )
                if acc > best_val:
                    best_val = acc
                    torch.save(
                        {
                            "model": model.state_dict(),
                            "char2id": char2id,
                            "rd2id": rd2id,
                            "args": vars(args),
                            "val_acc": acc,
                            "nparam": nparam,
                        },
                        out_dir / "best.pt",
                    )

                # G1 at ~1h
                if not g1_passed and elapsed >= 3600 * 0.9:
                    g1_passed = True
                    log(f"G1_CHECK val_acc={acc:.4f} baseline={v2c_baseline:.4f}")
                    if acc < v2c_baseline:
                        log("G1_FAIL stop training")
                        stopped_reason = "G1_fail"
                        (out_dir / "stopped.json").write_text(
                            json.dumps(
                                {
                                    "reason": stopped_reason,
                                    "val_acc": acc,
                                    "baseline": v2c_baseline,
                                }
                            ),
                            encoding="utf-8",
                        )
                        log_f.close()
                        return out_dir / "best.pt"
                    log("G1_PASS")

                # G2 at ~3h: must still be rising and > baseline+1pp
                if elapsed >= 3 * 3600 * 0.95 and len(history) >= 2:
                    recent = history[-1]["val_acc"]
                    prev = history[-2]["val_acc"]
                    log(
                        f"G2_CHECK recent={recent:.4f} prev={prev:.4f} "
                        f"need>{v2c_baseline+0.01:.4f}"
                    )
                    if recent < v2c_baseline + 0.01 or recent <= prev + 1e-4:
                        log("G2_STALL stop training")
                        stopped_reason = "G2_stall"
                        break

        if stopped_reason in ("G1_fail", "G2_stall", "time_budget"):
            break
        # end epoch val
        acc = eval_loader(model, val_loader, device)
        log(f"EPOCH_END {epoch} val_acc={acc:.4f}")
        if acc > best_val:
            best_val = acc
            torch.save(
                {
                    "model": model.state_dict(),
                    "char2id": char2id,
                    "rd2id": rd2id,
                    "args": vars(args),
                    "val_acc": acc,
                    "nparam": nparam,
                },
                out_dir / "best.pt",
            )

    (out_dir / "history.json").write_text(
        json.dumps(history, indent=2), encoding="utf-8"
    )
    (out_dir / "stopped.json").write_text(
        json.dumps(
            {
                "reason": stopped_reason,
                "best_val": best_val,
                "elapsed_h": (time.time() - t_start) / 3600,
                "g1_passed": g1_passed,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    log(f"DONE reason={stopped_reason} best_val={best_val:.4f}")
    log_f.close()
    return out_dir / "best.pt"


@torch.no_grad()
def eval_loader(model, loader, device) -> float:
    model.eval()
    correct = total = 0
    for batch in loader:
        ids = batch["ids"].to(device)
        lengths = batch["lengths"]
        pos = batch["pos"].to(device)
        rd = batch["rd"].to(device)
        gold = batch["gold"].to(device)
        logits = model(ids, lengths, pos, rd)
        pred = restricted_argmax(logits, batch["cands"])
        correct += int((pred == gold).sum().item())
        total += gold.size(0)
    model.train()
    return correct / max(total, 1)


# ---------------------------------------------------------------------------
# Eval on tw538
# ---------------------------------------------------------------------------


@torch.no_grad()
def eval_tw538(args: argparse.Namespace) -> dict:
    data_dir = Path(args.data_dir)
    repo = Path(args.repo)
    ckpt_path = Path(args.ckpt)
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    char2id = ckpt["char2id"]
    rd2id = ckpt["rd2id"]
    id2char = {i: c for c, i in char2id.items()}
    conf = ckpt.get("args", {})
    model = PositionJudge(
        n_chars=len(char2id),
        n_readings=len(rd2id),
        emb=conf.get("emb", 256),
        hid=conf.get("hid", 384),
        layers=conf.get("layers", 2),
        rd_emb=conf.get("rd_emb", 64),
    ).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()

    r2c = load_reading2chars(data_dir / "reading2chars.tsv")
    r2clist = {rd: [c for c, _ in items] for rd, items in r2c.items()}
    cases = load_tw538(repo / "Source/Engine/eval/benchmarks/tw538-northstar.tsv")
    # shipping
    ships = []
    sp = data_dir / "batonA2-gate-dump/shipping_preds.tsv"
    lines = sp.read_text(encoding="utf-8").splitlines()
    hdr = lines[0].split("\t")
    for line in lines[1:]:
        p = line.split("\t")
        ships.append({hdr[i]: p[i] if i < len(p) else "" for i in range(len(hdr))})

    unk = char2id["<unk>"]
    mask = char2id["<mask>"]

    def predict(context_chars: list[str], pos: int, reading: str, cands: list[str]) -> str:
        ids = [char2id.get(c, unk) for c in context_chars]
        if pos < len(ids):
            ids[pos] = mask
        t = torch.tensor([ids], dtype=torch.long, device=device)
        lengths = torch.tensor([len(ids)], dtype=torch.long)
        pos_t = torch.tensor([pos], dtype=torch.long, device=device)
        rd_t = torch.tensor([rd2id.get(reading, 0)], dtype=torch.long, device=device)
        logits = model(t, lengths, pos_t, rd_t)[0]
        cand_ids = [char2id.get(c, unk) for c in cands]
        if not cand_ids:
            return context_chars[pos]
        idx = torch.tensor(cand_ids, device=device)
        best = idx[int(logits.index_select(0, idx).argmax())]
        return id2char.get(int(best), context_chars[pos])

    # Gate 1: gold prefix context (other positions = gold)
    g1_ok = g1_n = 0
    # Gate 2: shipping context
    g2_ok = g2_n = 0
    rows = []
    # for flip proposals: delta scores via model logprob difference
    # Use logit of chosen vs shipping char as score signal
    proposals = []  # for gate sweep

    for si, (readings, gold) in enumerate(cases):
        syls = [s for s in readings.split("-") if s]
        gchars = list(gold)
        schars = list(ships[si]["pred"])
        n = min(len(syls), len(gchars), len(schars))
        # gold-context preds
        g_preds = []
        s_preds = []
        for i in range(n):
            rd = syls[i]
            cands = r2clist.get(rd, [])
            if gchars[i] not in cands:
                cands = list(cands) + [gchars[i]]
            # gold context
            ctx_g = gchars[:n]
            pg = predict(ctx_g, i, rd, cands)
            g_preds.append(pg)
            ok1 = pg == gchars[i]
            g1_n += 1
            if ok1:
                g1_ok += 1
            # shipping context
            ctx_s = schars[:n]
            ps = predict(ctx_s, i, rd, cands)
            s_preds.append(ps)
            ok2 = ps == gchars[i]
            g2_n += 1
            if ok2:
                g2_ok += 1

            # flip proposal: if shipping char differs from model pick under shipping ctx
            # score = logit(ps) - logit(ship_char) under shipping context
            ids = [char2id.get(c, unk) for c in ctx_s]
            ids[i] = mask
            t = torch.tensor([ids], dtype=torch.long, device=device)
            lengths = torch.tensor([len(ids)], dtype=torch.long)
            pos_t = torch.tensor([i], dtype=torch.long, device=device)
            rd_t = torch.tensor([rd2id.get(rd, 0)], dtype=torch.long, device=device)
            logits = model(t, lengths, pos_t, rd_t)[0]
            ship_id = char2id.get(schars[i], unk)
            # score all cands for flip dump
            for c in cands:
                if c == schars[i]:
                    continue
                cid = char2id.get(c, unk)
                delta = float(logits[cid] - logits[ship_id])
                after = list(ctx_s)
                after[i] = c
                after_text = "".join(after)
                # pad to full gold length if needed
                if len(gchars) > n:
                    after_text = after_text + "".join(gchars[n:])
                ship_text = ships[si]["pred"]
                proposals.append(
                    {
                        "sent_idx": si,
                        "pos": i,
                        "from": schars[i],
                        "to": c,
                        "delta": delta,
                        "ship_correct": ships[si]["correct"] == "1",
                        "after_correct": after_text == gold,
                        "gold_in_pool": ships[si].get("gold_in_pool", "0") == "1",
                        "pred": ship_text,
                        "gold": gold,
                    }
                )

            rows.append(
                {
                    "sent_idx": si,
                    "pos": i,
                    "reading": rd,
                    "gold": gchars[i],
                    "ship": schars[i],
                    "g1_pred": pg,
                    "g1_ok": int(ok1),
                    "g2_pred": ps,
                    "g2_ok": int(ok2),
                    "gold_in_pool": ships[si].get("gold_in_pool", ""),
                }
            )

    result = {
        "g1_pos_acc": g1_ok / max(g1_n, 1),
        "g1_ok": g1_ok,
        "g1_n": g1_n,
        "g2_pos_acc": g2_ok / max(g2_n, 1),
        "g2_ok": g2_ok,
        "g2_n": g2_n,
        "ckpt": str(ckpt_path),
        "val_acc_train": ckpt.get("val_acc"),
        "nparam": ckpt.get("nparam"),
    }
    print(json.dumps(result, indent=2))
    return {"result": result, "rows": rows, "proposals": proposals}


def write_proposals_tsv(proposals: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as fo:
        fo.write(
            "sent_idx\tpos\tfrom\tto\tscore_S\tscore_Sp\tdelta_v2c\t"
            "ship_correct\tafter_correct\tgold_in_pool\tpred\tgold\n"
        )
        for p in proposals:
            # reuse column name delta_v2c for compatibility with analyze_flip_gates
            fo.write(
                f"{p['sent_idx']}\t{p['pos']}\t{p['from']}\t{p['to']}\t"
                f"0\t{p['delta']}\t{p['delta']}\t"
                f"{1 if p['ship_correct'] else 0}\t"
                f"{1 if p['after_correct'] else 0}\t"
                f"{1 if p['gold_in_pool'] else 0}\t"
                f"{p['pred']}\t{p['gold']}\n"
            )


# ---------------------------------------------------------------------------
# Recon (step 1)
# ---------------------------------------------------------------------------


def recon(args: argparse.Namespace) -> None:
    """30-min optional: whole-sentence rescoring proxy on 300 positions."""
    data_dir = Path(args.data_dir)
    out = data_dir / "batonC-recon"
    out.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + 30 * 60
    try:
        from mlx_lm import load
        import mlx.core as mx
    except ImportError:
        print("RECON_SKIP no mlx_lm")
        (out / "recon.json").write_text(
            json.dumps({"skipped": True, "reason": "no mlx"}), encoding="utf-8"
        )
        return

    model_path = data_dir / "models/Qwen2.5-7B-Instruct-4bit-mlx"
    if not model_path.exists():
        print("RECON_SKIP no model")
        return

    print("RECON load model", flush=True)
    model, tok = load(str(model_path))

    def seq_lp(text: str) -> float:
        ids = tok.encode(text, add_special_tokens=False)
        if len(ids) < 2:
            return 0.0
        logits = model(mx.array([ids]))
        if isinstance(logits, (tuple, list)):
            logits = logits[0]
        mx.eval(logits)
        lp = 0.0
        for t in range(len(ids) - 1):
            row = logits[0, t]
            r = row - mx.max(row)
            log_denom = mx.log(mx.sum(mx.exp(r)))
            lp += float(r[ids[t + 1]] - log_denom)
        return lp

    # positions from entropy
    ent_path = (
        Path(args.repo) / "Source/Engine/eval/analysis/tw538-residual-entropy.tsv"
    )
    lines = ent_path.read_text(encoding="utf-8").splitlines()
    hdr = lines[0].split("\t")
    ok_pos, bad_pos = [], []
    for line in lines[1:]:
        d = dict(zip(hdr, line.split("\t")))
        item = (int(d["sent_idx"]), int(d["pos"]), d["reading"], d["gold"], d["pred"])
        if d["correct"] == "1":
            ok_pos.append(item)
        else:
            bad_pos.append(item)
    rng = random.Random(0)
    sample_ok = rng.sample(ok_pos, min(150, len(ok_pos)))
    sample_bad = rng.sample(bad_pos, min(150, len(bad_pos)))
    sample = sample_ok + sample_bad

    r2c = load_reading2chars(data_dir / "reading2chars.tsv")
    r2clist = {rd: [c for c, _ in items] for rd, items in r2c.items()}
    ships = []
    sp = data_dir / "batonA2-gate-dump/shipping_preds.tsv"
    L = sp.read_text(encoding="utf-8").splitlines()
    h = L[0].split("\t")
    for line in L[1:]:
        p = line.split("\t")
        ships.append({h[i]: p[i] if i < len(p) else "" for i in range(len(h))})
    cases = load_tw538(
        Path(args.repo) / "Source/Engine/eval/benchmarks/tw538-northstar.tsv"
    )

    ctrl_ok = ctrl_n = 0
    bad_fixed = bad_n = 0
    done = 0
    for si, pos, rd, gold, pred in sample:
        if time.time() > deadline:
            print("RECON_TIMEOUT", done, flush=True)
            break
        ship = ships[si]["pred"]
        schars = list(ship)
        gchars = list(cases[si][1])
        n = min(len(schars), len(gchars))
        if pos >= n:
            continue
        cands = r2clist.get(rd, [])
        if gold not in cands:
            cands = list(cands) + [gold]
        # score each cand by whole-sentence logprob with shipping fill
        best_c, best_s = schars[pos], -1e30
        base = schars[:n]
        for c in cands[:16]:  # cap for time
            tmp = base[:]
            tmp[pos] = c
            s = seq_lp("".join(tmp))
            if s > best_s:
                best_s, best_c = s, c
        ship_ok = schars[pos] == gold
        if ship_ok:
            ctrl_n += 1
            if best_c == gold:
                ctrl_ok += 1
        else:
            bad_n += 1
            if best_c == gold:
                bad_fixed += 1
        done += 1
        if done % 20 == 0:
            print(
                f"recon {done}/{len(sample)} ctrl={ctrl_ok}/{ctrl_n} "
                f"fixed={bad_fixed}/{bad_n}",
                flush=True,
            )

    res = {
        "done": done,
        "ctrl_acc": ctrl_ok / max(ctrl_n, 1),
        "ctrl_ok": ctrl_ok,
        "ctrl_n": ctrl_n,
        "bad_fixed": bad_fixed,
        "bad_n": bad_n,
        "bad_fix_rate": bad_fixed / max(bad_n, 1),
        "method": "whole_sentence_logprob_shipping_fill",
    }
    print("RECON", json.dumps(res))
    (out / "recon.json").write_text(json.dumps(res, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build-data", "train", "eval", "recon", "all"])
    ap.add_argument("--repo", default=str(Path.home() / "iBopomofo"))
    ap.add_argument("--data-dir", default=str(Path.home() / "laowang-data"))
    ap.add_argument("--variant", choices=["clean", "noisy"], default="clean")
    ap.add_argument("--max-sents", type=int, default=0, help="0=all spoken lines")
    ap.add_argument("--max-samples", type=int, default=400000)
    ap.add_argument("--noise-p", type=float, default=0.15)
    ap.add_argument("--emb", type=int, default=256)
    ap.add_argument("--hid", type=int, default=384)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--rd-emb", type=int, default=64)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--max-hours", type=float, default=6.0)
    ap.add_argument("--eval-every", type=int, default=500)
    ap.add_argument("--train-limit", type=int, default=0, help="0=all samples")
    ap.add_argument("--vocab-scan", type=int, default=800000)
    ap.add_argument("--v2c-baseline", type=float, default=0.874982)
    ap.add_argument("--ckpt", type=str, default="")
    args = ap.parse_args()
    if args.train_limit == 0:
        args.train_limit = None

    if args.cmd == "build-data":
        build_data(args)
    elif args.cmd == "train":
        train_variant(args)
    elif args.cmd == "eval":
        if not args.ckpt:
            raise SystemExit("--ckpt required")
        eval_tw538(args)
    elif args.cmd == "recon":
        recon(args)
    elif args.cmd == "all":
        build_data(args)
        # train both
        for v in ("clean", "noisy"):
            args.variant = v
            train_variant(args)


if __name__ == "__main__":
    main()
