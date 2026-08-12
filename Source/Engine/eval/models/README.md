# Research eval models (weights outside git)

Out-of-tree weights used by research harnesses (not shipping).

## Location

```text
IBOPOMOFO_EVAL_MODELS  (default: ~/laowang-data/eval-models/)
```

This directory only keeps **index files**:

- `*.sha256` — expected SHA-256 of each weight
- `*.meta.txt` — architecture / training notes

Shipping product weights stay in `Source/Data/path-char-lstm.bin` (tracked).

## Files

| weight | notes |
|--------|--------|
| `path-char-lstm-spoken.bin` | v1 spoken LSTM |
| `path-char-lstm-spoken-v2a.bin` | emb64/hid128 |
| `path-char-lstm-spoken-v2b.bin` | emb128/hid256 |
| `path-char-lstm-spoken-v2c.bin` | emb256/hid512 float baseline |
| `path-char-lstm-spoken-v2d.bin` | float 在/再 micro-tune (int8 ships in Data/) |
| `path-char-tf-spoken.bin` | spoken transformer (negative result) |
| `cond-converter-v2.bin` | conditional converter experiment |

## Verify

```bash
MODELS="${IBOPOMOFO_EVAL_MODELS:-$HOME/laowang-data/eval-models}"
cd "$(git rev-parse --show-toplevel)/Source/Engine/eval/models"
for s in *.sha256; do
  expected=$(awk '{print $1}' "$s")
  name=$(basename "$s" .sha256).bin
  actual=$(shasum -a 256 "$MODELS/$name" | awk '{print $1}')
  if [ "$expected" = "$actual" ]; then echo "OK $name"; else echo "MISMATCH $name"; fi
done
```

If a weight is missing:

```text
找不到 $IBOPOMOFO_EVAL_MODELS/<name>.bin
請將研究模型放到該目錄（或設定 IBOPOMOFO_EVAL_MODELS 指向存放處）。
索引與 SHA 見本目錄 *.sha256。
```
