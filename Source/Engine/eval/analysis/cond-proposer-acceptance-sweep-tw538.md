# Pool-external acceptance sweep — threading the precision-recall wall

**Question the baton asked:** the conservative three-way accept recovered 4 of
7 *reached* B-class answers and vetoed 3 (擋片/點擊/豔紅色). Can a different
pool-external acceptance criterion recover more without regressions?

**Answer: yes, modestly. Neural two-vote (m=1.0) → 401/537 (+1 over 400),
recovering 5 of 7 reached B-class with 1 regression. Walk-downweight hits a
hard precision-recall wall. The real ceiling has moved: 60 of 67 B-class are
never *reached* by the proposer.**

## Method (cached-pool sweep)

Pool building (draft → cond proposals → override → re-walk → fidelity) is the
only expensive step. `zenzai_constrained_search.cpp` now snapshots each case's
scored candidates — `(text, walk, v2c, cond, external)` — once, then sweeps all
acceptance variants in memory. One run = the whole grid. Red lines held: the
proposer (cond conditional distribution), the reading law, and all model
weights are **unchanged**.

Validation: α=1 reproduces **400**, BASE397 = **397**, READING_FIDELITY_FAIL
**0/537**.

## Residual map (variant-independent)

| B-class (n-best miss) | reached by proposer | never reached |
|---|---|---|
| 67 | **7** | **60** |

Only 7 of 67 pool-external answers are ever produced by the proposer (and this
did not grow with more coverage — see prior grid probe). Acceptance can at best
recover those 7; the other 60 are a **proposal-reach** problem.

## Variant A — pool-external walk downweight `(external?α:1)·walk + 0.5·v2c + 0.25·cond`

| α | correct | net vs 397 | bclass_fixed | regressions |
|---|---|---|---|---|
| 1.0 | 400 | +3 | 4 | 1 |
| 0.75 | 259 | −138 | 7 | **145** |
| 0.5 | 241 | −156 | 7 | 163 |
| 0.25 | 241 | −156 | 7 | 163 |
| 0.0 | 241 | −156 | 7 | 163 |

The moment walk is downweighted for pool-external paths, **all 7** reached
B-class come in — but **145+ regressions** flood with them. Walk is exactly
what keeps pool-external candidates honest (a pool-external path is, by
definition, one walk disfavors). Removing it is all-or-nothing: full recall,
collapsed precision. This is the precision-recall wall, quantified.

## Variant B — neural two-vote (accept external iff v2c AND cond both beat the in-pool best by margin m; walk tie-breaks)

| m | correct | net vs 397 | bclass_fixed | regressions |
|---|---|---|---|---|
| 0.0 | 396 | −1 | 5 | 6 |
| 0.25 | 399 | +2 | 5 | 3 |
| 0.5 | 400 | +3 | 5 | 2 |
| **1.0** | **401** | **+4** | **5** | **1** |
| 2.0 | 397 | 0 | 1 | 1 |

Requiring **both** neural models to prefer the pool-external path threads the
wall the single α knob cannot: at m=1.0 it recovers 5 of 7 reached B-class with
just 1 regression → **401/537**, +1 over the conservative three-way (400) and
+4 over the 397 rerank. Too loose (m=0) lets regressions in (6); too tight
(m=2) starves recall (1).

## Reading

- **Best acceptance = neural two-vote m=1.0 → 401/537.** Modest (+1 over 400)
  but real, and it demonstrates the right shape of criterion: trust the two
  *reading-conditioned/general* neural signals jointly for pool-external paths,
  not walk (which is structurally biased against them).
- **Walk-downweight is a dead end** (variant A): the precision-recall wall is
  real and steep — this is the "judge = defendant" problem made numeric.
- **The ceiling moved.** With acceptance now near its reachable limit (5–7 of
  the 7 reached), B-class progress is bounded by **proposal reach**: 60/67 are
  never produced. The next war is the proposer — multi-position / beam
  exploration, or a stronger conditional decoder — not the accept rule.

## Reproduce

```bash
cd Source/Engine/eval/benchmarks
clang++ -std=c++17 -O2 -I../.. -I../../gramambular2 \
  zenzai_constrained_search.cpp ../../CondConverterScorer.cpp \
  ../../gramambular2/reading_grid.cpp ../../CorpusBigramContextModel.cpp \
  ../../NeuralLMPathScorer.cpp ../../ParselessLM.cpp \
  ../../ParselessPhraseDB.cpp ../../MemoryMappedFile.cpp -o /tmp/zenzai_cond
/tmp/zenzai_cond tw538-northstar.tsv ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv 0.75 \
  ../models/path-char-lstm-spoken-v2c.bin ../models/cond-converter-v2.bin \
  5 8 0.5 0.25 0.5 -2.5
# expect: SWEEP_BASE397 397 ... reached_bclass 7 never_reached 60
#         VARIANT alpha=1 → 400 ; VARIANT twovote m=1 → 401
#         READING_FIDELITY_FAIL 0/537
```
