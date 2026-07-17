# CondProposer constrained search — attacking B-class path_locked on tw538

**Question the baton asked:** with the CondConverter as the *proposer* (not a
generic scorer), how many of the 67 pool-external B-class sentences can
constrained lattice re-search recover?

**Answer: 4 of 67 recovered → 400/537 (net +3 over the 397 rerank).**
The proposer *reaches* 7 of the 67; the conservative three-way accept selects
4. The other 3 are reached but vetoed by the walk term — the ceiling of a
walk-anchored acceptance.

## Method (faithful to the baton's conservative accept)

- Base pool = `walkNBest(10)` scored on the shipping fusion
  `walk + 0.5·v2c + 0.25·cond`. Its argmax = **BASE397_CONTROL**, which
  reproduces **397/537 exactly** (basis validated — same walk/cond/v2c scoring
  as `tw538_cond_rerank`).
- Selective trigger (worst-node LM logp `< -2.5` OR n-best margin `< 0.5`).
- On trigger: for each worst node, the **CondConverter** scores every lattice
  candidate `P(cand | left_ctx, cand.reading)` (the true conditional
  distribution — NOT a generic char-LM). Top proposals → prefix-lock +
  `overrideCandidate` → **re-walk** → reading-fidelity + node-unigram checks →
  add to pool.
- Final = argmax three-way over the **full** pool. Because the 397 candidates
  are in the pool, a pool-external research path wins only if its three-way
  beats every 397 candidate → **conservative accept, no regression vs 397 by
  construction** (measured: 1 regression, see below).

## Result (tw538, 537 sentences; `5 8 0.5 0.25 0.5 -2.5`)

| metric | value |
|---|---|
| WALK_ON | 333/537 |
| BASE397_CONTROL (argmax three-way over n-best) | **397/537** (reproduces the mix) |
| **ZENZAI_CORRECT** (constrained search) | **400/537** |
| NET_VS_397 | **+3** (gains 4, regressions 1) |
| **B_CLASS_FIXED** (pool-external recovered) | **4 / 67** |
| oracle-reached B-class (expected ∈ explored, ∉ n-best) | 7 |
| CHANGED_VS_397 | 10/537 |
| TRIGGERED | 478/537 (89%) |
| READING_FIDELITY_FAIL | **0/537** (reading law enforced) |
| MEAN_MS | 3748 (research config; latency debt) |

Grid probe `8 12 0.5 0.25 0.6 -2.2` (wider trigger 95.5%, more coverage):
**identical** 400 / B_CLASS 4 / oracle 7, only slower (4485 ms). More coverage
does **not** help → the binding constraint is *selection*, not proposal reach.

## The 4 recovered (rerank structurally could not — pool-external)

| draft (wrong) | recovered | reading confusion |
|---|---|---|
| 果**之**甜點 | 果**汁**甜點 | 之/汁 |
| 耐**衰**耐操 | 耐**摔**耐操 | 衰/摔 |
| **灣到的灣**度 | **彎道的彎**度 | 灣/彎, 到/道 |
| 很好**其** | 很好**奇** | 其/奇 |

## The 3 reached-but-vetoed (conservative-accept ceiling)

The cond proposer produced the correct pool-external path (reading-faithful),
but the three-way score kept the fluent-but-wrong draft — the walk term
penalizes pool-external paths by construction:

| draft (kept) | correct (reached, not selected) |
|---|---|
| **黨**片拆下 | **擋**片拆下 |
| 點**集**後 | 點**擊**後 |
| **驗**紅色 | **豔**紅色 |

## Reading

- **Positive:** the conditional proposer opens a door reranking cannot — 4
  pool-external answers recovered, 0 reading-law violations. B-class (67) was
  untouched by every rerank config; it now moves.
- **Ceiling:** conservative three-way accept caps recovery at 4 (of 7 reached).
  Recovering the other 3+ needs an acceptance that trusts the conditional model
  more for pool-external paths (where walk is, by definition, unreliable) —
  without re-introducing regressions. That is a tuning problem for the next
  baton, not a re-architecture.
- **Regression:** 1 case correct-at-397 lost (a research path scored higher
  three-way but was wrong). Conservative accept is not perfectly safe; 1/537.

## Reproduce

```bash
ENGINE=Source/Engine
clang++ -std=c++17 -O2 -I"$ENGINE" -I"$ENGINE/gramambular2" \
  $ENGINE/eval/benchmarks/zenzai_constrained_search.cpp \
  $ENGINE/CondConverterScorer.cpp $ENGINE/gramambular2/reading_grid.cpp \
  $ENGINE/CorpusBigramContextModel.cpp $ENGINE/NeuralLMPathScorer.cpp \
  $ENGINE/ParselessLM.cpp $ENGINE/ParselessPhraseDB.cpp \
  $ENGINE/MemoryMappedFile.cpp -o /tmp/zenzai_cond

cd $ENGINE/eval/benchmarks
/tmp/zenzai_cond tw538-northstar.tsv ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv 0.75 \
  ../models/path-char-lstm-spoken-v2c.bin ../models/cond-converter-v2.bin \
  5 8 0.5 0.25 0.5 -2.5
# expect: BASE397_CONTROL 397 · ZENZAI_CORRECT 400 · B_CLASS_FIXED 4/67
#         READING_FIDELITY_FAIL 0/537
```
