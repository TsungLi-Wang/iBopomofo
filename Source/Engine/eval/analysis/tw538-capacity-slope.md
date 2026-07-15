# Capacity slope (tw538, N=10, λ=0.75)

| model | params | emb/hid | val_ppl | best correct | best ν | mean_ms | Δ vs prev |
|-------|--------|---------|---------|--------------|--------|---------|-----------|
| v1 spoken | 1.27M | 64/128 | ~84 | **356** | 0.5 | ~61 | baseline |
| v2a (corpus only) | 1.75M | 64/128 | 101.6 | **362** | 0.5 | ~81 | +6 (data) |
| v2b | 3.95M | 128/256 | 75.4 | **374** | 0.75 | ~226 | +12 (capacity) |
| **v2c** | **9.73M** | **256/512** | **64.7** | **387** | **0.75** | **~730** | **+13** |

## Slope (params → correct)

```
1.27M → 356
3.95M → 374   (+18 / +2.68M ≈ +6.7 per M params)
9.73M → 387   (+13 / +5.78M ≈ +2.2 per M params)
```

**Interpretation**: capacity still lifts accuracy, but **diminishing returns** (slope 6.7 → 2.2 per M). Latency grows faster than accuracy (61 → 226 → 730 ms). Next capacity step (e.g. emb384/hid768) likely < +10 sentences at multi-second latency — prefer architecture change (Transformer) or A-class single-char features over pure LSTM scale.

## Latency curve (mean_ms @ best ν)

| params | mean_ms | ms per correct-point over v1 |
|--------|---------|------------------------------|
| 1.27M | 61 | — |
| 3.95M | 226 | +9.2 ms/pt (374-356) |
| 9.73M | 730 | +36.3 ms/pt (387-356) |

App-wiring note: v2c ~730ms is **not** interactive-budget friendly; keep flag OFF; harness/offline only until smaller distilled student.
