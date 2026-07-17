#!/usr/bin/env python3
"""Train conditional conversion model: (left_context, reading) → target word.

Architecture (documented):
  - Char embedding E_c
  - Reading-syllable embedding E_r (split reading on '-')
  - Context LSTM over left chars → h_ctx
  - Reading LSTM over syllables → h_rd
  - Init decoder state: tanh(W [h_ctx; h_rd])
  - Char LSTM decoder teacher-forced on target word chars
  - Loss: CE next-char (BOS→c0→…→cLast→EOS)

At inference: scoreCandidate(left, reading, cand) = sum logP of cand chars
under teacher forcing (higher = better conversion score).

Binary export magic "LWCONV1\\0" for CondConverterScorer C++.
"""

from __future__ import annotations

import argparse
import math
import random
import struct
import sys
from collections import Counter
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

PAD, UNK, BOS, EOS, SEP = 0, 1, 2, 3, 4
SPECIAL = ["<pad>", "<unk>", "<s>", "</s>", "<sep>"]


def utf8_chars(s: str) -> list[str]:
    return list(s)  # Python str is already unicode codepoints for CJK


def split_reading(rd: str) -> list[str]:
    return [p for p in rd.split("-") if p]


class Vocab:
    def __init__(self):
        self.itos = list(SPECIAL)
        self.stoi = {t: i for i, t in enumerate(self.itos)}

    def add(self, tok: str):
        if tok not in self.stoi:
            self.stoi[tok] = len(self.itos)
            self.itos.append(tok)

    def get(self, tok: str) -> int:
        return self.stoi.get(tok, UNK)

    def __len__(self):
        return len(self.itos)


def load_pairs(path: Path, max_pairs: int = 0):
    pairs = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        left, rd, word = parts
        if not word:
            continue
        pairs.append((left, rd, word))
        if max_pairs and len(pairs) >= max_pairs:
            break
    return pairs


class PairDataset(Dataset):
    def __init__(self, pairs, char_v: Vocab, rd_v: Vocab, max_ctx: int, max_word: int):
        self.items = []
        for left, rd, word in pairs:
            lchars = utf8_chars(left)[-max_ctx:]
            rtoks = split_reading(rd)
            wchars = utf8_chars(word)[:max_word]
            if not wchars or not rtoks:
                continue
            self.items.append((lchars, rtoks, wchars))
        self.char_v = char_v
        self.rd_v = rd_v

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        lchars, rtoks, wchars = self.items[i]
        left_ids = [self.char_v.get(c) for c in lchars]
        rd_ids = [self.rd_v.get(t) for t in rtoks]
        # decoder: BOS + word + EOS
        tgt = [BOS] + [self.char_v.get(c) for c in wchars] + [EOS]
        return left_ids, rd_ids, tgt


import zlib
from torch.utils.data import IterableDataset, get_worker_info


def _is_val(line: str, val_mod: int) -> bool:
    # Deterministic content-hash holdout (stable across runs / workers).
    return (zlib.crc32(line.encode("utf-8")) % val_mod) == 0


def stream_vocab(path: Path, min_freq: int, val_mod: int):
    """One streaming pass over the pairs file → (char_v, rd_v, n_train, n_val).
    Counts only TRAIN lines for the frequency threshold (no val leakage)."""
    char_cnt: Counter = Counter()
    rd_cnt: Counter = Counter()
    n_train = n_val = 0
    with path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\n")
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            if _is_val(line, val_mod):
                n_val += 1
                continue
            n_train += 1
            left, rd, word = parts
            for c in left:
                char_cnt[c] += 1
            for c in word:
                char_cnt[c] += 1
            for t in rd.split("-"):
                if t:
                    rd_cnt[t] += 1
    char_v, rd_v = Vocab(), Vocab()
    for c, n in char_cnt.items():
        if n >= min_freq:
            char_v.add(c)
    for t, n in rd_cnt.items():
        if n >= min_freq:
            rd_v.add(t)
    return char_v, rd_v, n_train, n_val


def _encode_pair(left, rd, word, char_v, rd_v, max_ctx, max_word):
    lchars = utf8_chars(left)[-max_ctx:]
    rtoks = split_reading(rd)
    wchars = utf8_chars(word)[:max_word]
    if not wchars or not rtoks:
        return None
    left_ids = [char_v.get(c) for c in lchars]
    rd_ids = [rd_v.get(t) for t in rtoks]
    tgt = [BOS] + [char_v.get(c) for c in wchars] + [EOS]
    return left_ids, rd_ids, tgt


class StreamPairDataset(IterableDataset):
    """Streams TRAIN pairs from disk (no full load → fits 16GB for 43M pairs).
    Per-worker line sharding + a bounded shuffle buffer. Re-reads file each
    epoch (DataLoader re-iterates)."""

    def __init__(self, path, char_v, rd_v, max_ctx, max_word, val_mod,
                 shuffle_buf=200_000, seed=0):
        self.path = path
        self.char_v = char_v
        self.rd_v = rd_v
        self.max_ctx = max_ctx
        self.max_word = max_word
        self.val_mod = val_mod
        self.shuffle_buf = shuffle_buf
        self.seed = seed
        self.epoch = 0

    def set_epoch(self, e):
        self.epoch = e

    def __iter__(self):
        wi = get_worker_info()
        nshard = wi.num_workers if wi else 1
        sid = wi.id if wi else 0
        rng = random.Random(self.seed + self.epoch * 1000 + sid)
        buf = []
        with self.path.open(encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if (i % nshard) != sid:
                    continue
                line = line.rstrip("\n")
                parts = line.split("\t")
                if len(parts) != 3 or _is_val(line, self.val_mod):
                    continue
                enc = _encode_pair(parts[0], parts[1], parts[2],
                                   self.char_v, self.rd_v,
                                   self.max_ctx, self.max_word)
                if enc is None:
                    continue
                if len(buf) < self.shuffle_buf:
                    buf.append(enc)
                    continue
                j = rng.randrange(len(buf))
                yield buf[j]
                buf[j] = enc
            rng.shuffle(buf)
            for enc in buf:
                yield enc


def load_val(path: Path, char_v, rd_v, max_ctx, max_word, val_mod, cap):
    """Materialize a bounded held-out val set (hash holdout, cap examples)."""
    items = []
    with path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\n")
            parts = line.split("\t")
            if len(parts) != 3 or not _is_val(line, val_mod):
                continue
            enc = _encode_pair(parts[0], parts[1], parts[2], char_v, rd_v,
                               max_ctx, max_word)
            if enc is not None:
                items.append(enc)
                if len(items) >= cap:
                    break
    return items


def collate(batch):
    lefts, rds, tgts = zip(*batch)
    def pad(seqs, pad_id=PAD):
        m = max(len(s) for s in seqs) if seqs else 1
        m = max(m, 1)
        out = torch.full((len(seqs), m), pad_id, dtype=torch.long)
        lens = []
        for i, s in enumerate(seqs):
            if not s:
                lens.append(1)
                continue
            out[i, : len(s)] = torch.tensor(s, dtype=torch.long)
            lens.append(len(s))
        return out, torch.tensor(lens, dtype=torch.long)

    L, Ll = pad(lefts)
    R, Rl = pad(rds)
    T, Tl = pad(tgts)
    return L, Ll, R, Rl, T, Tl


class CondConverter(nn.Module):
    def __init__(self, n_char: int, n_rd: int, emb: int, hidden: int, layers: int):
        super().__init__()
        self.emb = emb
        self.hidden = hidden
        self.layers = layers
        self.char_emb = nn.Embedding(n_char, emb, padding_idx=PAD)
        self.rd_emb = nn.Embedding(n_rd, emb, padding_idx=PAD)
        self.ctx_lstm = nn.LSTM(emb, hidden, num_layers=layers, batch_first=True)
        self.rd_lstm = nn.LSTM(emb, hidden, num_layers=layers, batch_first=True)
        self.fuse = nn.Linear(hidden * 2, hidden * layers)
        self.fuse_c = nn.Linear(hidden * 2, hidden * layers)
        self.dec_lstm = nn.LSTM(emb, hidden, num_layers=layers, batch_first=True)
        self.fc = nn.Linear(hidden, n_char)

    def encode(self, left, left_len, rd, rd_len):
        # left: [B,T], may be all pad for empty context
        be = self.char_emb(left)
        packed_ok = left_len.max().item() > 0
        if packed_ok:
            # replace zero lengths with 1 for pack
            ll = left_len.clamp(min=1)
            out, (h, c) = self.ctx_lstm(be)
            # take last real step per row
            idx = (ll - 1).clamp(min=0)
            b = torch.arange(left.size(0), device=left.device)
            h_ctx = out[b, idx]  # [B,H]
        else:
            h_ctx = torch.zeros(left.size(0), self.hidden, device=left.device)

        re = self.rd_emb(rd)
        rl = rd_len.clamp(min=1)
        out_r, _ = self.rd_lstm(re)
        idx_r = (rl - 1).clamp(min=0)
        b = torch.arange(rd.size(0), device=rd.device)
        h_rd = out_r[b, idx_r]

        cat = torch.cat([h_ctx, h_rd], dim=-1)
        B = left.size(0)
        # fuse(cat) is [B, H*layers]; reshape as [B, layers, H] then move layer
        # axis to front → [layers, B, H]. NOTE: a direct .view(layers, B, H)
        # scrambles across the batch when layers>1 (flat layout is [b, l*H+h],
        # not [l, b*H+h]); it only coincides for layers==1 or B==1. The C++
        # inference path runs B==1 and indexes layer li as h0[li*H:(li+1)*H],
        # which matches this per-batch grouping. Keep them consistent.
        h0 = torch.tanh(self.fuse(cat)).view(B, self.layers, self.hidden).transpose(0, 1).contiguous()
        c0 = torch.tanh(self.fuse_c(cat)).view(B, self.layers, self.hidden).transpose(0, 1).contiguous()
        return h0, c0

    def forward(self, left, left_len, rd, rd_len, tgt):
        # tgt: [B, S] with BOS ... EOS; predict tgt[:,1:] from tgt[:,:-1]
        h0, c0 = self.encode(left, left_len, rd, rd_len)
        inp = self.char_emb(tgt[:, :-1])
        out, _ = self.dec_lstm(inp, (h0.contiguous(), c0.contiguous()))
        logits = self.fc(out)
        return logits


def export_binary(path: Path, model: CondConverter, char_v: Vocab, rd_v: Vocab):
    sd = model.state_dict()
    with path.open("wb") as f:
        f.write(b"LWCONV1\0")
        f.write(struct.pack("<iiii", model.emb, model.hidden, model.layers, len(char_v)))
        f.write(struct.pack("<i", len(rd_v)))

        def write_vocab(itos):
            for s in itos:
                b = s.encode("utf-8")
                f.write(struct.pack("<h", len(b)))
                f.write(b)

        write_vocab(char_v.itos)
        write_vocab(rd_v.itos)

        def dump(t: torch.Tensor):
            t = t.detach().cpu().contiguous().to(torch.float32)
            f.write(bytes(t.untyped_storage()))

        dump(sd["char_emb.weight"])
        dump(sd["rd_emb.weight"])
        # ctx LSTM
        for li in range(model.layers):
            suf = f"_l{li}" if model.layers > 1 else ""
            # PyTorch names: weight_ih_l0, weight_hh_l0, bias_ih_l0, bias_hh_l0
            dump(sd[f"ctx_lstm.weight_ih_l{li}"])
            dump(sd[f"ctx_lstm.weight_hh_l{li}"])
            dump(sd[f"ctx_lstm.bias_ih_l{li}"])
            dump(sd[f"ctx_lstm.bias_hh_l{li}"])
        for li in range(model.layers):
            dump(sd[f"rd_lstm.weight_ih_l{li}"])
            dump(sd[f"rd_lstm.weight_hh_l{li}"])
            dump(sd[f"rd_lstm.bias_ih_l{li}"])
            dump(sd[f"rd_lstm.bias_hh_l{li}"])
        dump(sd["fuse.weight"])
        dump(sd["fuse.bias"])
        dump(sd["fuse_c.weight"])
        dump(sd["fuse_c.bias"])
        for li in range(model.layers):
            dump(sd[f"dec_lstm.weight_ih_l{li}"])
            dump(sd[f"dec_lstm.weight_hh_l{li}"])
            dump(sd[f"dec_lstm.bias_ih_l{li}"])
            dump(sd[f"dec_lstm.bias_hh_l{li}"])
        dump(sd["fc.weight"])
        dump(sd["fc.bias"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--emb", type=int, default=64)
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--layers", type=int, default=1)
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--max-ctx", type=int, default=16)
    ap.add_argument("--max-word", type=int, default=6)
    ap.add_argument("--max-pairs", type=int, default=0)
    ap.add_argument("--val-ratio", type=float, default=0.02)
    ap.add_argument("--min-freq", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", type=str, default="auto", help="cpu|mps|auto")
    ap.add_argument("--log-every", type=int, default=500)
    # streaming (for corpora too large to load into 16GB RAM)
    ap.add_argument("--stream", action="store_true",
                    help="stream pairs from disk instead of full in-memory load")
    ap.add_argument("--num-workers", type=int, default=4)
    ap.add_argument("--shuffle-buf", type=int, default=200_000)
    ap.add_argument("--val-cap", type=int, default=30_000)
    ap.add_argument("--val-mod", type=int, default=64,
                    help="content-hash holdout: crc32(line)%%mod==0 → val")
    args = ap.parse_args()

    random.seed(args.seed)
    torch.manual_seed(args.seed)

    stream_ds = None
    if args.stream:
        print(f"[stream] vocab pass over {args.pairs}", flush=True)
        char_v, rd_v, n_train, n_val = stream_vocab(
            args.pairs, args.min_freq, args.val_mod)
        print(f"char_vocab={len(char_v)} rd_vocab={len(rd_v)}", flush=True)
        print(f"train={n_train} val={n_val} (hash holdout mod={args.val_mod})",
              flush=True)
        stream_ds = StreamPairDataset(
            args.pairs, char_v, rd_v, args.max_ctx, args.max_word,
            args.val_mod, shuffle_buf=args.shuffle_buf, seed=args.seed)
        # persistent_workers=False so workers respawn each epoch and capture
        # the updated stream_ds.epoch → epoch-varying shuffle.
        train_dl = DataLoader(
            stream_ds, batch_size=args.batch, collate_fn=collate,
            num_workers=args.num_workers)
        val_items = load_val(args.pairs, char_v, rd_v, args.max_ctx,
                             args.max_word, args.val_mod, args.val_cap)
        val_dl = DataLoader(val_items, batch_size=args.batch, shuffle=False,
                            collate_fn=collate)
        est_batches = max(1, n_train // args.batch)
    else:
        print(f"loading pairs {args.pairs}", flush=True)
        pairs = load_pairs(args.pairs, args.max_pairs)
        print(f"pairs_loaded={len(pairs)}", flush=True)
        if len(pairs) < 1000:
            print("too few pairs", file=sys.stderr)
            return 1

        # build vocab from pairs
        char_cnt: Counter = Counter()
        rd_cnt: Counter = Counter()
        for left, rd, word in pairs:
            for c in utf8_chars(left) + utf8_chars(word):
                char_cnt[c] += 1
            for t in split_reading(rd):
                rd_cnt[t] += 1

        char_v, rd_v = Vocab(), Vocab()
        for c, n in char_cnt.items():
            if n >= args.min_freq:
                char_v.add(c)
        for t, n in rd_cnt.items():
            if n >= args.min_freq:
                rd_v.add(t)
        print(f"char_vocab={len(char_v)} rd_vocab={len(rd_v)}", flush=True)

        random.shuffle(pairs)
        n_val = max(500, int(len(pairs) * args.val_ratio))
        val_pairs = pairs[:n_val]
        train_pairs = pairs[n_val:]
        print(f"train={len(train_pairs)} val={len(val_pairs)}", flush=True)

        train_ds = PairDataset(train_pairs, char_v, rd_v, args.max_ctx, args.max_word)
        val_ds = PairDataset(val_pairs, char_v, rd_v, args.max_ctx, args.max_word)
        train_dl = DataLoader(
            train_ds, batch_size=args.batch, shuffle=True, collate_fn=collate
        )
        val_dl = DataLoader(val_ds, batch_size=args.batch, shuffle=False, collate_fn=collate)
        est_batches = len(train_dl)

    if args.device == "auto":
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = torch.device("mps")
        else:
            device = torch.device("cpu")
    else:
        device = torch.device(args.device)
    print(f"device={device}", flush=True)

    model = CondConverter(len(char_v), len(rd_v), args.emb, args.hidden, args.layers).to(
        device
    )
    nparams = sum(p.numel() for p in model.parameters())
    print(
        f"arch=CondConverter layers={args.layers} emb={args.emb} hidden={args.hidden} "
        f"params={nparams}",
        flush=True,
    )
    # comparability guard vs v2c ~9.73M
    if nparams < 7_000_000 or nparams > 13_000_000:
        print(
            f"WARNING: params {nparams} outside target 8–12M band (v2c-comparable)",
            file=sys.stderr,
            flush=True,
        )

    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    crit = nn.CrossEntropyLoss(ignore_index=PAD)

    best_val = 1e9
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for ep in range(1, args.epochs + 1):
        model.train()
        total_loss, ntok = 0.0, 0
        if stream_ds is not None:
            stream_ds.set_epoch(ep)
        n_batches = est_batches
        for bi, (L, Ll, R, Rl, T, Tl) in enumerate(train_dl, 1):
            L, Ll, R, Rl, T = L.to(device), Ll.to(device), R.to(device), Rl.to(device), T.to(device)
            logits = model(L, Ll, R, Rl, T)  # [B,S-1,V]
            loss = crit(logits.reshape(-1, logits.size(-1)), T[:, 1:].reshape(-1))
            if math.isnan(loss.item()) or math.isinf(loss.item()):
                print("ERROR: train loss NaN/Inf — abort", file=sys.stderr, flush=True)
                return 3
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            total_loss += loss.item() * T[:, 1:].numel()
            ntok += (T[:, 1:] != PAD).sum().item()
            if args.log_every and bi % args.log_every == 0:
                print(
                    f"  ep{ep} batch {bi}/{n_batches} loss={loss.item():.4f}",
                    flush=True,
                )
        train_ppl = math.exp(min(20.0, total_loss / max(1, ntok)))

        model.eval()
        vloss, vtok = 0.0, 0
        with torch.no_grad():
            for L, Ll, R, Rl, T, Tl in val_dl:
                L, Ll, R, Rl, T = (
                    L.to(device),
                    Ll.to(device),
                    R.to(device),
                    Rl.to(device),
                    T.to(device),
                )
                logits = model(L, Ll, R, Rl, T)
                loss = crit(logits.reshape(-1, logits.size(-1)), T[:, 1:].reshape(-1))
                vloss += loss.item() * T[:, 1:].numel()
                vtok += (T[:, 1:] != PAD).sum().item()
        val_avg = vloss / max(1, vtok)
        if math.isnan(val_avg) or val_avg > 20:
            print(
                f"ERROR: val diverged val_loss={val_avg} — abort, no bad export",
                file=sys.stderr,
                flush=True,
            )
            return 3
        val_ppl = math.exp(min(20.0, val_avg))
        print(
            f"epoch {ep}/{args.epochs} train_loss={total_loss/max(1,ntok):.4f} "
            f"train_ppl≈{train_ppl:.2f} val_loss={val_avg:.4f} val_ppl≈{val_ppl:.2f}",
            flush=True,
        )
        if val_ppl < best_val:
            best_val = val_ppl
            # export on CPU tensors
            model.cpu()
            export_binary(args.out, model, char_v, rd_v)
            model.to(device)
            meta = args.out.with_suffix(".meta.txt")
            meta.write_text(
                f"arch=CondConverter layers={args.layers} emb={args.emb} hidden={args.hidden}\n"
                f"char_vocab={len(char_v)} rd_vocab={len(rd_v)} params={nparams}\n"
                f"epochs={ep} lr={args.lr} batch={args.batch} device={device}\n"
                f"pairs_train={len(train_pairs)} pairs_val={len(val_pairs)}\n"
                f"best_val_ppl≈{best_val:.4f}\n"
                f"corpus_pairs={args.pairs}\n",
                encoding="utf-8",
            )
            print(f"  saved {args.out} (best val_ppl≈{best_val:.2f})", flush=True)

    print(f"final_best_val_ppl≈{best_val:.4f}", flush=True)
    print(f"params={nparams}", flush=True)
    print(f"out={args.out} size={args.out.stat().st_size}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
