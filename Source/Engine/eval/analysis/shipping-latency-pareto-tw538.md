# Shipping-debt Pareto — the neural rerank fits the latency budget after all

**Question the baton asked:** the shipped app is still walk-ON **333/537
(62%)**; the neural rerank (v2c → **387**, 74.8%) was considered unshippable at
~730 ms/sentence. Within an input method's commit-time latency budget (**≤100 ms
甲級 / ≤160 ms 乙級**, N=10), how many tw538 points can we buy?

**Answer: all of them, with no training and no accuracy loss.** Two engineering
levers — **prefix-state sharing** across the 10 candidates and **Accelerate
BLAS** matmuls — put **v2c 387 @ ~44 ms** (甲級). int8 (all weight tensors) is
**lossless on v2c (still 387)** and cuts the model 38.9 MB → **9.9 MB**. The
"distil to hit latency" premise is dead: we can ship the teacher itself, and the
smaller-size points (v2b, v1) already exist without training. **Distillation is
therefore de-scoped** per the T2 conditional (≥380 @ 甲級 reached).

---

## Where the ~730 ms went

`NeuralLMPathScorer::scoreSentence` is called once per n-best candidate
(`reading_grid.cpp:330`), and each call restarts the LSTM from BOS. So the 10
candidates — which share almost the entire sentence — each re-run the whole
shared prefix, and every char step does a **full-vocab softmax** (a V×H = 7875×512
projection, memory-bound). 10 × ~15 chars × (2-layer LSTM + V×H fc) ≈ the
observed cost.

## T1 — cheap, training-free compression

`rerank_opt.cpp` reranks the **same** `walkNBest(10)` the engine produces (so
`correct` is faithful to the shipped path — only the scorer changes) with:

1. **Prefix trie** over the candidates' char-id sequences. Each distinct prefix
   computes its LSTM step + one softmax **once**; identical prefixes are shared.
   10 candidates collapse to ~1.5× the unique work of one, not 10×.
2. **Accelerate BLAS** (`cblas_sgemv`) for the 4H×in gate matvecs and the V×H
   output projection.
3. **weight-only int8** (per-output-row symmetric, all weight tensors) — round-
   tripped in place, so the fp32 path runs over exactly the values int8 inference
   would use; accuracy is **measured, not assumed**.

fp32 mode is arithmetically the engine's rerank (trie/BLAS only reassociate
floats) → it reproduces the known scores exactly.

### Pareto (tw538, N=10 rerank, this machine)

| config | correct | %/537 | MEAN_MS total (nbest+rerank) | on-disk | grade |
|---|---|---|---|---|---|
| shipped app (walk ON) | 333 | 62.0 | — (no neural) | — | — |
| baseline v2c per-cand fp32 | 387 | 72.1 | **723** | 38.9 MB | — |
| **v2c fp32 opt** | **387** | **72.1** | **~44** (5.6+38.4) | 38.9 MB | 甲級 |
| **v2c int8 opt** | **387** | **72.1** | ~44 (≈fp32) | **9.9 MB** | 甲級 |
| v2b fp32 opt | 374 | 69.6 | 14.3 (5.7+8.6) | 15.8 MB | 甲級 |
| v2b int8 opt | 372 | 69.3 | ~14 | 4.1 MB | 甲級 |
| v1 fp32 opt | 356 | 66.3 | 9.4 (5.7+3.8) | 5.1 MB | 甲級 |
| v1 int8 opt | 353 | 65.7 | ~9 | 1.3 MB | 甲級 |

- **Every point is 甲級.** The latency wall was an implementation artefact, not a
  model-size limit. Speedup on v2c: 723 → ~44 ms ≈ 16×,
  same 387.
- **v2c nu robustness** (opt fp32): nu 0.25→375, 0.5→386, **0.75→387**, 1.0→385;
  latency 47–48 ms across the grid. Peak unchanged, budget held.
- **int8 accuracy loss** (all weight tensors): v2c **387→387 (0)**, v2b 374→372
  (−2), v1 356→353 (−3). Bigger model = more int8-robust; the one we'd ship
  (v2c) is lossless. int8 gave no latency gain here (dequant-to-float path) — its
  role is **bundle size** (3.9× smaller), not speed.
- The n-best enumeration itself is ~5.7 ms (model-independent); it is a floor on
  any rerank config and already well inside budget.

## T2 — distillation (de-scoped: validation only)

The baton's T2 conditional: *if T1 reaches ≥380 @ 甲級, T2 shrinks to one
validation file.* It does (v2c 387 @ ~44 ms), so **no distillation was run.**
The reasoning that makes it unnecessary, not just skipped:

- Distillation's pitch is "small model, teacher accuracy, low latency." But we
  can ship the **teacher** (v2c) at ~44 ms / 9.9 MB (int8) — a student can't beat
  387, its own ceiling.
- The smaller-size points a KD curve would chart **already exist as trained
  models**: v2b int8 (372 @ 4.1 MB) and v1 int8 (353 @ 1.3 MB). The size/accuracy
  trade is on the table without spending a training run.
- Bundle budget: current dmg is ~31 MB (25 MB word-bigrams). +9.9 MB (v2c int8)
  → ~41 MB, embeddable; no first-run download needed.

The KD-vs-scratch control the full T2 branch specifies remains the right
experiment **only if** a sub-v1 (<1 MB) model is ever demanded — not the case
now. The B-class research pipeline and this Pareto are in repo to restart from.

## T3 — shipping candidates (ammunition for the wiring baton)

App / flag / weights still **unchanged** — wiring is the next baton. Proposed:

| # | config | tw538 | Δ vs shipped 333 | MEAN_MS | bundle | note |
|---|---|---|---|---|---|---|
| **A (recommended)** | v2c int8 + trie + BLAS | **387** | **+54** | ~44 ms | +9.9 MB | max accuracy, 甲級, lossless int8 |
| B (lean) | v2b int8 + trie + BLAS | 372 | +39 | ~14 ms | +4.1 MB | if 9.9 MB is unwanted; −15 vs A |

Wiring checklist for the next baton: port the **prefix-trie + BLAS batched
rerank** into `NeuralLMPathScorer` (or a new batched `scoreNBest`), replacing the
per-candidate loop at `reading_grid.cpp:330`; add an int8 on-disk weight format;
set `EnableNeuralPathRerank` default ON with nu=0.75, NBest=10; re-run
`scripts/e2e-typing-check.sh`.

## Reproduce

```bash
cd Source/Engine/eval/benchmarks
ENGINE=../..
clang++ -std=c++17 -O2 -I$ENGINE -I$ENGINE/gramambular2 \
  rerank_opt.cpp $ENGINE/CorpusBigramContextModel.cpp $ENGINE/ParselessLM.cpp \
  $ENGINE/ParselessPhraseDB.cpp $ENGINE/MemoryMappedFile.cpp \
  $ENGINE/gramambular2/reading_grid.cpp -framework Accelerate -o /tmp/rerank_opt
# args: sentences data bigrams lambda lstm.bin nu [int8]
/tmp/rerank_opt tw538-northstar.tsv ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv 0.75 ../models/path-char-lstm-spoken-v2c.bin 0.75 0
# expect: CORRECT 387/537 · MEAN_MS_TOTAL ~44 (nbest ~5.6 + rerank_score ~38); varies 36-48 by load
#   int8=1 → CORRECT 387/537 (lossless); v2b→374/372, v1→356/353
```

Baseline (per-candidate, engine path) for the speedup anchor:
`nbest_path_rerank_any.cpp` (same args, no int8 flag).

## Evidence (persistent, `~/laowang-data/`)

```
rerank_baseline_fp32.out    sha256 f27a700fc7e74f18cf908a47bfafabdcd7105643a6a1a08c3e6efc8ec8b8aba0  (v1 356@61.7ms, v2b 374@242ms — per-candidate engine path)
rerank_baseline_v2c.out     sha256 a861f44092e310efad4d0a1518923e1ba706deb40d341c19e65f13d031c14e44  (v2c 387@723ms — per-candidate engine path)
rerank_opt_pareto.out       sha256 8858a8b262e37c22b65754f1736383a9a79682928f9abb5c6f250b377e5007ee  (fp32 + int8-all × v2c/v2b/v1, optimized)
rerank_opt_v2c_nugrid.out   sha256 37f96ae95091b3498bb793b073ab8f10d0c7192d1595246b5355c63cb3349f90  (v2c opt nu 0.25/0.5/0.75/1.0)
```

Timing is machine-load sensitive (v2c fp32 measured 36–48 ms across runs; 3
back-to-back unloaded runs = 43.5/45.3/45.1 ms → ~44 ms). Every figure is well
inside 甲級 regardless; `correct` is invariant.
