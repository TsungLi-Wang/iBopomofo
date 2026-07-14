# T2b: spoken LSTM upgrade on tw538 (N=10, λ=0.75)

Corpus: Gossiping-only (QA v1+v2 + push replies), **han≈77.76M**, packed lines 474322.
Pollution ban enforced (no tw538 10 boards, no C_Chat). Stats: `spoken-corpus-v2-stats.json`.

| model | arch | params | val_ppl | ν=0.25 | ν=0.5 | ν=0.75 | mean_ms@best | SHA256 prefix |
|-------|------|--------|---------|--------|-------|--------|--------------|---------------|
| baseline spoken (v1) | emb64/hid128 | 1,272,852 | ~84 (train) | 348 | **356** | 349 | ~61 | e1a500db… |
| **(a) v2a** same arch + big corpus | emb64/hid128 | 1,751,299 | 101.6 | 354 | **362** | 353 | ~81 | 4970eee8… |
| **(b) v2b** larger + big corpus | emb128/hid256 | 3,953,475 | **75.4** | 367 | 369 | **374** | ~216 | 65da67e5… |

**Delta vs baseline 356:**
- (a) corpus-only: **+6** → 362 @ ν=0.5
- (b) corpus+capacity: **+18** → **374** @ ν=0.75

Raw stdout:
- train a: `train-v2a.stdout.txt`
- train b: `train-v2b.stdout.txt`
- eval a: `tw538-lstm-v2a.stdout.txt`
- eval b: `tw538-lstm-v2b.stdout.txt`

Weights:
- `../models/path-char-lstm-spoken-v2a.bin` (~6.7MB)
- `../models/path-char-lstm-spoken-v2b.bin` (~15MB) ← **new best teacher**

Latency note: v2b mean_ms≈216 (vs baseline ~61 / v2a ~81). Acceptable for offline/harness; app flag still OFF.
