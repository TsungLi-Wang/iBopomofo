#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lwlstm_io.py — 讀寫引擎用的 LWLSTM1 模型檔（v2c 那個格式）

train_char_lstm_lm.py 只有寫出去的 export_binary，沒有讀回來的。
要對既有模型做微調（路線 C）就得先能讀回來，所以補這一支。

⚠️ 動任何權重之前，先跑 `--selftest` 確認「讀進來再寫出去」跟原檔逐位元組相同。
沒有這一關，之後量到的任何差異都分不清是訓練造成的還是 I/O 造成的。

格式（與 export_binary 一致）：
    magic "LWLSTM1\\0"
    int32 emb, hidden, layers, vocab
    vocab 個字串（int16 長度 + UTF-8 bytes）
    emb.weight            [V, E]  fp32
    每層：weight_ih [4H, in]、weight_hh [4H, H]、bias_ih [4H]、bias_hh [4H]
    fc.weight             [V, H]
    fc.bias               [V]
"""

import argparse
import struct
import sys
from pathlib import Path

import torch


MAGIC = b"LWLSTM1\0"


class CharLSTM(torch.nn.Module):
    """與 train_char_lstm_lm.py 的定義完全相同，權重才對得起來。"""

    def __init__(self, vocab: int, emb: int, hidden: int, layers: int):
        super().__init__()
        self.emb = torch.nn.Embedding(vocab, emb)
        self.lstm = torch.nn.LSTM(emb, hidden, num_layers=layers, batch_first=True)
        self.fc = torch.nn.Linear(hidden, vocab)

    def forward(self, x):
        h, _ = self.lstm(self.emb(x))
        return self.fc(h)


def load(path) -> tuple[CharLSTM, list[str], dict]:
    data = Path(path).read_bytes()
    if data[:8] != MAGIC:
        sys.exit(f"{path} 不是 LWLSTM1（magic={data[:8]!r}）。"
                 "int8 版（LWLSTM8）請用 fp32 原檔。")
    off = 8
    emb, hidden, layers, vocab = struct.unpack_from("<iiii", data, off)
    off += 16
    itos = []
    for _ in range(vocab):
        (n,) = struct.unpack_from("<h", data, off)
        off += 2
        itos.append(data[off:off + n].decode("utf-8"))
        off += n

    def take(*shape):
        nonlocal off
        n = 1
        for s in shape:
            n *= s
        t = torch.frombuffer(bytearray(data[off:off + n * 4]),
                             dtype=torch.float32).reshape(*shape).clone()
        off += n * 4
        return t

    model = CharLSTM(vocab, emb, hidden, layers)
    sd = {"emb.weight": take(vocab, emb)}
    for li in range(layers):
        indim = emb if li == 0 else hidden
        sd[f"lstm.weight_ih_l{li}"] = take(4 * hidden, indim)
        sd[f"lstm.weight_hh_l{li}"] = take(4 * hidden, hidden)
        sd[f"lstm.bias_ih_l{li}"] = take(4 * hidden)
        sd[f"lstm.bias_hh_l{li}"] = take(4 * hidden)
    sd["fc.weight"] = take(vocab, hidden)
    sd["fc.bias"] = take(vocab)
    model.load_state_dict(sd)
    if off != len(data):
        sys.exit(f"讀完還剩 {len(data) - off} bytes —— 格式對不上，別繼續")
    return model, itos, {"emb": emb, "hidden": hidden, "layers": layers,
                         "vocab": vocab}


def save(path, model: CharLSTM, itos: list[str], meta: dict):
    sd = model.state_dict()
    with Path(path).open("wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<iiii", meta["emb"], meta["hidden"],
                            meta["layers"], len(itos)))
        for ch in itos:
            b = ch.encode("utf-8")
            f.write(struct.pack("<h", len(b)))
            f.write(b)

        def dump(t):
            f.write(bytes(t.detach().cpu().contiguous()
                          .to(torch.float32).untyped_storage()))

        dump(sd["emb.weight"])
        for li in range(meta["layers"]):
            dump(sd[f"lstm.weight_ih_l{li}"])
            dump(sd[f"lstm.weight_hh_l{li}"])
            dump(sd[f"lstm.bias_ih_l{li}"])
            dump(sd[f"lstm.bias_hh_l{li}"])
        dump(sd["fc.weight"])
        dump(sd["fc.bias"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--selftest", metavar="OUT",
                    help="讀進來再寫出去，比對是否逐位元組相同")
    args = ap.parse_args()

    model, itos, meta = load(args.model)
    print(f"讀入 {args.model}")
    print(f"  emb={meta['emb']} hidden={meta['hidden']} "
          f"layers={meta['layers']} vocab={meta['vocab']}")
    print(f"  參數量 {sum(p.numel() for p in model.parameters()) / 1e6:.2f}M")

    if args.selftest:
        save(args.selftest, model, itos, meta)
        a = Path(args.model).read_bytes()
        b = Path(args.selftest).read_bytes()
        if a == b:
            print(f"✅ 來回無損：{args.selftest} 與原檔逐位元組相同")
        else:
            print(f"❌ 不一致（原檔 {len(a)} bytes、輸出 {len(b)} bytes）")
            sys.exit(1)


if __name__ == "__main__":
    main()
