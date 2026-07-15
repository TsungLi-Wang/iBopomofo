# T2: char-Transformer vs v2c LSTM (same corpus, same order of params)

| system | arch | params | val_ppl | best correct/537 | best ν | mean_ms | A-class | single_char_swap residual |
|--------|------|--------|---------|------------------|--------|---------|---------|---------------------------|
| walk ON | bigram | — | — | 333 | — | ~0.3 | — | — |
| **v2c LSTM** | emb256/hid512 2L | **9.73M** | **64.7** | **387** | **0.75** | **~730** | **96** | **68** |
| **TF spoken** | 6L d256 h4 ffn1024 ctx128 | **8.81M** (−9.4% vs v2c) | **58.8** | **332** @0.25 (all ν≥0.25 ≤332) | 0.25 | **~720** | **138** | **94** |

## ν grid (TF raw stdout)

```
NU 0    correct 333/537 mean_ms 0.26
NU 0.25 correct 332/537 mean_ms 728.9
NU 0.5  correct 329/537 mean_ms 720.0
NU 0.75 correct 328/537 mean_ms 719.0
NU 1.0  correct 330/537 mean_ms 718.1
BEST among positive ν: 0.25 → 332 (worse than walk ON alone)
```

## Sanity

- C++ `scoreSentence` matches pure-Python reload of same `LWTFMR1` bin on sample strings (e.g. −42.5685).
- Params within ±30% of v2c (8.81M / 9.73M = 90.5%).
- Training: 4 epochs, val_ppl 58.75, no divergence.

## Conclusion (answer to the bar's question)

**No — same-order-of-magnitude char Transformer does NOT beat LSTM on tw538 PathScorer fusion**, and is **worse on single-char homophone residual (94 > 68)** despite **better val_ppl**. Attention LM quality ≠ n-best path ranking for this fusion setup. Next: features / calibration / ensemble, not more generic TF scale.

Weights: `../models/path-char-tf-spoken.bin` + SHA256 (persisted for reproducibility even though not SOTA).
