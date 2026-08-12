#!/usr/bin/env python3
"""Train a small char-level decoder-only Transformer LM for PathScorer.

Target params ~8–12M (same order as spoken LSTM v2c ≈9.73M).

Architecture (default):
  - 6 layers, d_model=256, n_head=4, ffn=1024, max_ctx=128
  - token emb + learned positional emb
  - causal self-attention (PyTorch MultiheadAttention with attn_mask)
  - pre-norm style: LN → Attn → residual → LN → FFN → residual
  - untied lm_head (for stable size / C++ export simplicity)
  - Loss: next-char cross-entropy

Binary export magic "LWTFMR1\\0":
  int32: d_model, n_head, n_layer, ffn, max_ctx, vocab
  vocab: int16 utf8_len + bytes per token
  float32 row-major:
    emb[V, D]
    pos[max_ctx, D]
    for each layer:
      ln1_w[D], ln1_b[D]
      W_q[D,D], W_k[D,D], W_v[D,D], W_o[D,D]
      b_q[D], b_k[D], b_v[D], b_o[D]
      ln2_w[D], ln2_b[D]
      W1[D, FFN], b1[FFN], W2[FFN, D], b2[D]
    ln_f_w[D], ln_f_b[D]
    lm_w[V, D], lm_b[V]

Usage:
  python3 train_char_transformer_lm.py \\
    --corpus /tmp/ptt-gossip-expand/ptt_spoken_train_v2_packed.txt \\
    --out ${IBOPOMOFO_EVAL_MODELS:-$HOME/laowang-data/eval-models}/path-char-tf-spoken.bin \\
    --epochs 4 --stream --device mps
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

# Reuse helpers from LSTM trainer
sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_char_lstm_lm import (  # noqa: E402
    StreamCharDataset,
    build_vocab,
    encode_line,
    load_text,
)


class CharTransformer(nn.Module):
    def __init__(
        self,
        vocab: int,
        d_model: int,
        n_head: int,
        n_layer: int,
        ffn: int,
        max_ctx: int,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.d_model = d_model
        self.n_head = n_head
        self.n_layer = n_layer
        self.ffn = ffn
        self.max_ctx = max_ctx
        self.emb = nn.Embedding(vocab, d_model, padding_idx=0)
        self.pos = nn.Embedding(max_ctx, d_model)
        self.drop = nn.Dropout(dropout)
        self.layers = nn.ModuleList()
        for _ in range(n_layer):
            self.layers.append(
                nn.ModuleDict(
                    {
                        "ln1": nn.LayerNorm(d_model),
                        "attn": nn.MultiheadAttention(
                            d_model, n_head, dropout=dropout, batch_first=True
                        ),
                        "ln2": nn.LayerNorm(d_model),
                        "ff1": nn.Linear(d_model, ffn),
                        "ff2": nn.Linear(ffn, d_model),
                    }
                )
            )
        self.ln_f = nn.LayerNorm(d_model)
        self.lm_head = nn.Linear(d_model, vocab, bias=True)
        # causal mask buffer
        mask = torch.triu(torch.ones(max_ctx, max_ctx), diagonal=1).bool()
        self.register_buffer("causal_mask", mask, persistent=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [B, T]
        B, T = x.shape
        if T > self.max_ctx:
            x = x[:, -self.max_ctx :]
            T = x.size(1)
        pos = torch.arange(T, device=x.device).unsqueeze(0).expand(B, T)
        h = self.drop(self.emb(x) + self.pos(pos))
        attn_mask = self.causal_mask[:T, :T]
        for layer in self.layers:
            h_norm = layer["ln1"](h)
            attn_out, _ = layer["attn"](
                h_norm, h_norm, h_norm, attn_mask=attn_mask, need_weights=False
            )
            h = h + self.drop(attn_out)
            h2 = layer["ln2"](h)
            h2 = layer["ff2"](torch.nn.functional.gelu(layer["ff1"](h2)))
            h = h + self.drop(h2)
        h = self.ln_f(h)
        return self.lm_head(h)


def count_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


def export_binary(
    path: Path,
    model: CharTransformer,
    itos: list[str],
    d_model: int,
    n_head: int,
    n_layer: int,
    ffn: int,
    max_ctx: int,
) -> None:
    """Export weights matching C++ NeuralTFPathScorer layout."""
    sd = model.state_dict()
    with path.open("wb") as f:
        f.write(b"LWTFMR1\0")
        f.write(
            struct.pack(
                "<iiiiii", d_model, n_head, n_layer, ffn, max_ctx, len(itos)
            )
        )
        for ch in itos:
            b = ch.encode("utf-8")
            if len(b) > 32767:
                b = b[:32767]
            f.write(struct.pack("<h", len(b)))
            f.write(b)

        def dump(t: torch.Tensor) -> None:
            t = t.detach().cpu().contiguous().to(torch.float32)
            f.write(bytes(t.untyped_storage()))

        dump(sd["emb.weight"])
        dump(sd["pos.weight"])
        for li in range(n_layer):
            p = f"layers.{li}."
            dump(sd[p + "ln1.weight"])
            dump(sd[p + "ln1.bias"])
            # MultiheadAttention packs in_proj as [3D, D] and out_proj [D, D]
            in_proj = sd[p + "attn.in_proj_weight"]  # [3D, D]
            in_bias = sd[p + "attn.in_proj_bias"]  # [3D]
            D = d_model
            Wq, Wk, Wv = in_proj[0:D], in_proj[D : 2 * D], in_proj[2 * D : 3 * D]
            bq, bk, bv = in_bias[0:D], in_bias[D : 2 * D], in_bias[2 * D : 3 * D]
            dump(Wq)
            dump(Wk)
            dump(Wv)
            dump(sd[p + "attn.out_proj.weight"])
            dump(bq)
            dump(bk)
            dump(bv)
            dump(sd[p + "attn.out_proj.bias"])
            dump(sd[p + "ln2.weight"])
            dump(sd[p + "ln2.bias"])
            dump(sd[p + "ff1.weight"].T.contiguous())  # store as [D, FFN] row-major for x @ W
            dump(sd[p + "ff1.bias"])
            dump(sd[p + "ff2.weight"].T.contiguous())  # [FFN, D]
            dump(sd[p + "ff2.bias"])
        dump(sd["ln_f.weight"])
        dump(sd["ln_f.bias"])
        dump(sd["lm_head.weight"])  # [V, D]
        dump(sd["lm_head.bias"])
    print(f"exported {path} ({path.stat().st_size} bytes)")


@torch.no_grad()
def eval_loss(model, dl, device, loss_fn) -> tuple[float, float]:
    model.eval()
    total = 0.0
    tokens = 0
    for bx, by in dl:
        bx, by = bx.to(device), by.to(device)
        # truncate to max_ctx
        if bx.size(1) > model.max_ctx:
            bx = bx[:, : model.max_ctx]
            by = by[:, : model.max_ctx]
        logits = model(bx)
        loss = loss_fn(logits.reshape(-1, logits.size(-1)), by.reshape(-1))
        total += loss.item() * by.numel()
        tokens += by.numel()
    avg = total / max(1, tokens)
    ppl = math.exp(min(20.0, avg))
    model.train()
    return avg, ppl


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--d-model", type=int, default=256)
    ap.add_argument("--n-head", type=int, default=4)
    ap.add_argument("--n-layer", type=int, default=6)
    ap.add_argument("--ffn", type=int, default=1024)
    ap.add_argument("--max-ctx", type=int, default=128)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--seq-len", type=int, default=128)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--val-ratio", type=float, default=0.02)
    ap.add_argument("--device", type=str, default="auto")
    ap.add_argument("--stream", action="store_true")
    ap.add_argument("--log-every", type=int, default=200)
    ap.add_argument("--dropout", type=float, default=0.1)
    args = ap.parse_args()

    if args.d_model % args.n_head != 0:
        print("ERROR: d_model must be divisible by n_head", file=sys.stderr)
        return 2

    random.seed(args.seed)
    torch.manual_seed(args.seed)

    text = load_text(args.corpus, None, 0)
    han = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    print(f"corpus chars≈{len(text)} han≈{han}")
    itos, stoi = build_vocab(text, min_count=2)
    print(
        f"vocab={len(itos)} d_model={args.d_model} n_head={args.n_head} "
        f"n_layer={args.n_layer} ffn={args.ffn} max_ctx={args.max_ctx}"
    )

    sequences: list[list[int]] = []
    for line in text.splitlines():
        ids = encode_line(line, stoi)
        if len(ids) >= 4:
            sequences.append(ids)
    random.shuffle(sequences)
    n_val = max(1, int(len(sequences) * args.val_ratio)) if args.val_ratio > 0 else 0
    val_seqs = sequences[:n_val] if n_val else []
    train_seqs = sequences[n_val:] if n_val else sequences
    print(f"sequences={len(sequences)} train={len(train_seqs)} val={len(val_seqs)}")

    seq_len = min(args.seq_len, args.max_ctx)
    if args.stream:
        ds = StreamCharDataset(train_seqs, seq_len=seq_len)
        val_ds = StreamCharDataset(val_seqs, seq_len=seq_len) if val_seqs else None
        collate_fn = None
    else:
        from train_char_lstm_lm import CharDataset, collate

        ds = CharDataset(train_seqs, seq_len=seq_len)
        val_ds = CharDataset(val_seqs, seq_len=seq_len) if val_seqs else None
        collate_fn = collate
    print(f"dataset samples={len(ds)}")
    if len(ds) < 10:
        print("ERROR: too few samples", file=sys.stderr)
        return 2

    dl = DataLoader(ds, batch_size=args.batch, shuffle=True, collate_fn=collate_fn)
    val_dl = None
    if val_ds and len(val_ds) > 0:
        val_dl = DataLoader(
            val_ds, batch_size=args.batch, shuffle=False, collate_fn=collate_fn
        )

    if args.device == "auto":
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = torch.device("mps")
        else:
            device = torch.device("cpu")
    else:
        device = torch.device(args.device)
    print(f"device={device}")

    model = CharTransformer(
        len(itos),
        args.d_model,
        args.n_head,
        args.n_layer,
        args.ffn,
        args.max_ctx,
        dropout=args.dropout,
    ).to(device)
    n_params = count_params(model)
    print(f"parameters={n_params}")
    # guard: stay within ±30% of 9.73M
    target = 9_730_000
    if n_params < target * 0.7 or n_params > target * 1.3:
        print(
            f"WARNING: params {n_params} outside ±30% of v2c {target} "
            f"(comparability premise)",
            file=sys.stderr,
        )

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    loss_fn = nn.CrossEntropyLoss(ignore_index=0)
    # cosine decay
    total_steps = max(1, args.epochs * len(dl))
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=total_steps)

    model.train()
    best_val = float("inf")
    step = 0
    for ep in range(1, args.epochs + 1):
        total = 0.0
        tokens = 0
        n_batches = len(dl)
        for bi, (bx, by) in enumerate(dl, 1):
            bx, by = bx.to(device), by.to(device)
            if bx.size(1) > model.max_ctx:
                bx = bx[:, : model.max_ctx]
                by = by[:, : model.max_ctx]
            opt.zero_grad()
            logits = model(bx)
            loss = loss_fn(logits.reshape(-1, logits.size(-1)), by.reshape(-1))
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            step += 1
            total += loss.item() * by.numel()
            tokens += by.numel()
            if args.log_every and bi % args.log_every == 0:
                print(
                    f"  ep{ep} batch {bi}/{n_batches} loss={loss.item():.4f} "
                    f"lr={sched.get_last_lr()[0]:.2e}",
                    flush=True,
                )
        avg = total / max(1, tokens)
        ppl = math.exp(min(20.0, avg))
        msg = f"epoch {ep}/{args.epochs} train_loss={avg:.4f} train_ppl≈{ppl:.2f}"
        if val_dl is not None:
            vloss, vppl = eval_loss(model, val_dl, device, loss_fn)
            msg += f" val_loss={vloss:.4f} val_ppl≈{vppl:.2f}"
            if vloss < best_val:
                best_val = vloss
                msg += " *best"
            # diverge guard
            if math.isnan(vloss) or vloss > 20:
                print(msg, flush=True)
                print(
                    "ERROR: val loss diverged; refusing to export",
                    file=sys.stderr,
                )
                return 3
        print(msg, flush=True)

    model.cpu()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    export_binary(
        args.out,
        model,
        itos,
        args.d_model,
        args.n_head,
        args.n_layer,
        args.ffn,
        args.max_ctx,
    )
    meta = args.out.with_suffix(".meta.txt")
    meta.write_text(
        f"arch=CharTransformer n_layer={args.n_layer} d_model={args.d_model} "
        f"n_head={args.n_head} ffn={args.ffn} max_ctx={args.max_ctx}\n"
        f"vocab={len(itos)} params={n_params}\n"
        f"epochs={args.epochs} lr={args.lr} seq_len={seq_len} dropout={args.dropout}\n"
        f"corpus={args.corpus} han_chars≈{han} val_ratio={args.val_ratio} "
        f"best_val_loss={best_val}\n"
        f"device={device}\n",
        encoding="utf-8",
    )
    print(f"meta {meta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
