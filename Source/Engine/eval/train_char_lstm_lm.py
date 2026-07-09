#!/usr/bin/env python3
"""Train a tiny char-level LSTM language model for PathScorer (true neural LM).

Architecture (fixed, documented for CHANGELOG):
  - Embedding: vocab_size x emb_dim
  - LSTM: 2 layers, hidden_dim, batch_first
  - Linear: hidden_dim -> vocab_size
  - Loss: cross-entropy next-char prediction

Corpus: Taiwan typing corpus + Han runs from zh-TW wiki dump (same spirit as
word-bigrams; frequencies from real text only).

Exports a portable binary for pure-C++ inference (NeuralLMPathScorer):
  magic "LWLSTM1\\0"
  int32 emb, hidden, layers, vocab
  vocab: for each id: int16 utf8_len + bytes
  float32 weights in row-major order:
    emb[V,E]
    LSTM layer0: weight_ih[4H,E], weight_hh[4H,H], bias_ih[4H], bias_hh[4H]
    LSTM layer1: weight_ih[4H,H], weight_hh[4H,H], bias_ih[4H], bias_hh[4H]
    (for layers=2; general: first layer input is E, later H)
    fc_w[V,H], fc_b[V]

Usage:
  python3 train_char_lstm_lm.py \\
    --corpus ../../eval/generated/tw_corpus.txt \\
    --wiki-dump ../corpus/zhwiki-latest-pages-articles.xml.bz2 \\
    --out ../../../Data/path-char-lstm.bin \\
    --epochs 8 --emb 64 --hidden 128 --layers 2
"""

from __future__ import annotations

import argparse
import bz2
import math
import random
import re
import struct
import sys
from collections import Counter
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

HAN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
XML_TAG = re.compile(r"<[^>]+>")


def extract_wiki_han(path: Path, max_chars: int) -> str:
    out: list[str] = []
    n = 0
    try:
        opener = bz2.open if path.suffix == ".bz2" else open
        with opener(path, "rt", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = XML_TAG.sub("", line)
                for m in HAN_RE.finditer(line):
                    s = m.group(0)
                    out.append(s)
                    n += len(s)
                    if n >= max_chars:
                        return "\n".join(out)
    except Exception as e:
        print(f"wiki extract warning: {e}", file=sys.stderr)
    return "\n".join(out)


def load_text(corpus: Path, wiki: Path | None, max_wiki: int) -> str:
    parts: list[str] = []
    if corpus.exists():
        parts.append(corpus.read_text(encoding="utf-8", errors="ignore"))
    if wiki and wiki.exists():
        print(f"extracting wiki han up to {max_wiki} chars from {wiki} ...")
        parts.append(extract_wiki_han(wiki, max_wiki))
    return "\n".join(parts)


def build_vocab(text: str, min_count: int = 2) -> tuple[list[str], dict[str, int]]:
    # single UTF-8 characters (CJK) + specials
    cnt: Counter[str] = Counter()
    for line in text.splitlines():
        for ch in line:
            if "\u4e00" <= ch <= "\u9fff" or ch in "，。！？、；：":
                cnt[ch] += 1
    chars = ["<pad>", "<unk>", "<s>", "</s>"]
    for c, v in cnt.most_common():
        if v >= min_count and c not in chars:
            chars.append(c)
    stoi = {c: i for i, c in enumerate(chars)}
    return chars, stoi


def encode_line(line: str, stoi: dict[str, int]) -> list[int]:
    ids = [stoi["<s>"]]
    unk = stoi["<unk>"]
    for ch in line:
        if "\u4e00" <= ch <= "\u9fff" or ch in "，。！？、；：":
            ids.append(stoi.get(ch, unk))
    ids.append(stoi["</s>"])
    return ids


class CharDataset(Dataset):
    def __init__(self, sequences: list[list[int]], seq_len: int = 64):
        self.samples: list[tuple[list[int], list[int]]] = []
        for seq in sequences:
            if len(seq) < 3:
                continue
            for i in range(0, max(1, len(seq) - seq_len), seq_len // 2 or 1):
                chunk = seq[i : i + seq_len + 1]
                if len(chunk) < 3:
                    continue
                x = chunk[:-1]
                y = chunk[1:]
                self.samples.append((x, y))

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int):
        x, y = self.samples[idx]
        return torch.tensor(x, dtype=torch.long), torch.tensor(y, dtype=torch.long)


def collate(batch):
    xs, ys = zip(*batch)
    maxlen = max(x.size(0) for x in xs)
    bx = torch.full((len(xs), maxlen), 0, dtype=torch.long)
    by = torch.full((len(ys), maxlen), 0, dtype=torch.long)
    for i, (x, y) in enumerate(zip(xs, ys)):
        bx[i, : x.size(0)] = x
        by[i, : y.size(0)] = y
    return bx, by


class CharLSTM(nn.Module):
    def __init__(self, vocab: int, emb: int, hidden: int, layers: int):
        super().__init__()
        self.emb = nn.Embedding(vocab, emb, padding_idx=0)
        self.lstm = nn.LSTM(emb, hidden, num_layers=layers, batch_first=True)
        self.fc = nn.Linear(hidden, vocab)

    def forward(self, x):
        e = self.emb(x)
        o, _ = self.lstm(e)
        return self.fc(o)


def export_binary(path: Path, model: CharLSTM, itos: list[str], emb: int, hidden: int, layers: int):
    sd = model.state_dict()
    with path.open("wb") as f:
        f.write(b"LWLSTM1\0")
        f.write(struct.pack("<iiii", emb, hidden, layers, len(itos)))
        for ch in itos:
            b = ch.encode("utf-8")
            if len(b) > 32767:
                b = b[:32767]
            f.write(struct.pack("<h", len(b)))
            f.write(b)

        def dump(t: torch.Tensor):
            arr = t.detach().cpu().contiguous().float().numpy()
            f.write(arr.tobytes(order="C"))

        dump(sd["emb.weight"])
        for li in range(layers):
            dump(sd[f"lstm.weight_ih_l{li}"])
            dump(sd[f"lstm.weight_hh_l{li}"])
            dump(sd[f"lstm.bias_ih_l{li}"])
            dump(sd[f"lstm.bias_hh_l{li}"])
        dump(sd["fc.weight"])
        dump(sd["fc.bias"])
    print(f"exported {path} ({path.stat().st_size} bytes)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--wiki-dump", type=Path, default=None)
    ap.add_argument("--max-wiki-chars", type=int, default=3_000_000)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--emb", type=int, default=64)
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seq-len", type=int, default=64)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    random.seed(args.seed)
    torch.manual_seed(args.seed)

    text = load_text(args.corpus, args.wiki_dump, args.max_wiki_chars)
    print(f"corpus chars≈{len(text)}")
    itos, stoi = build_vocab(text, min_count=2)
    print(f"vocab={len(itos)} emb={args.emb} hidden={args.hidden} layers={args.layers}")

    sequences: list[list[int]] = []
    for line in text.splitlines():
        ids = encode_line(line, stoi)
        if len(ids) >= 4:
            sequences.append(ids)
    random.shuffle(sequences)
    print(f"sequences={len(sequences)}")

    ds = CharDataset(sequences, seq_len=args.seq_len)
    if len(ds) < 10:
        print("ERROR: too few training samples", file=sys.stderr)
        return 2
    dl = DataLoader(ds, batch_size=args.batch, shuffle=True, collate_fn=collate)

    device = torch.device("cpu")
    model = CharLSTM(len(itos), args.emb, args.hidden, args.layers).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = nn.CrossEntropyLoss(ignore_index=0)

    n_params = sum(p.numel() for p in model.parameters())
    print(f"parameters={n_params}")

    model.train()
    for ep in range(1, args.epochs + 1):
        total = 0.0
        tokens = 0
        for bx, by in dl:
            bx, by = bx.to(device), by.to(device)
            opt.zero_grad()
            logits = model(bx)
            loss = loss_fn(logits.reshape(-1, logits.size(-1)), by.reshape(-1))
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            total += loss.item() * by.numel()
            tokens += by.numel()
        avg = total / max(1, tokens)
        ppl = math.exp(min(20.0, avg))
        print(f"epoch {ep}/{args.epochs} loss={avg:.4f} ppl≈{ppl:.2f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    export_binary(args.out, model, itos, args.emb, args.hidden, args.layers)
    meta = args.out.with_suffix(".meta.txt")
    meta.write_text(
        f"arch=CharLSTM layers={args.layers} emb={args.emb} hidden={args.hidden}\n"
        f"vocab={len(itos)} params={n_params}\n"
        f"epochs={args.epochs} lr={args.lr} seq_len={args.seq_len}\n"
        f"corpus={args.corpus} wiki={args.wiki_dump} max_wiki={args.max_wiki_chars}\n",
        encoding="utf-8",
    )
    print(f"meta {meta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
