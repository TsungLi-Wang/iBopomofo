# The 60 silent B-class — mechanism vs knowledge, and a cheap multi-position beam

**Question the baton asked:** of the 67 pool-external (B-class) tw538 misses,
only 7 are ever *reached* by the CondProposer; 60 are never produced. Are those
60 silent because of a **mechanism** limit (single-position / threshold /
search width — fixable) or a **model-knowledge** limit (cond's distribution
simply doesn't favour gold — mechanism-proof)? And: cheaply recover the
mechanism part.

**Answer:** mechanism-dominated, not knowledge. Of 60 never-reached,
**MECH 24 · VETO_RISK 22 · KNOW 14** (stop-clause KNOW≥40 not triggered).
Every MECH miss diverges at **2–7 positions at once** — the single-position
proposer can't assemble them even though cond ranks each gold char top-1/3. A
multi-position cond beam reaches **4 more** (7→11); the *locked* two-vote accept
converts **1** of them → **402/537** (+1 over 401), regressions held at 1,
reading fidelity 0. The residual ceiling is now **acceptance**, not reach.

---

## T1 — silence diagnostic

`zenzai_silence_diag.cpp` reuses the 401 harness's `constrainedSearch` verbatim
to get the faithful reached flag (`oracleHitExpected`), then probes every
*never-reached* B-class case on three axes. Chars align 1:1 with syllables
(Mandarin), so divergence positions are exact.

- **(a) reach** — rank of the gold char among the single-syllable lattice
  candidates at each divergence position, scored by cond under **teacher-forced
  gold left context** (the optimistic ceiling on reach; single-divergence cases
  see the true draft context anyway).
- **(b) path cond** — `cond(gold-chars)` vs `cond(draft-chars)`, full path.
- **(c) path v2c** — `scoreSentence(gold)` vs `scoreSentence(draft)`.

**Buckets** (priority KNOW > VETO_RISK > MECH, so each sentence is the *binding*
constraint):

| bucket | n | meaning | lever |
|---|---|---|---|
| **MECH** | **24** | gold reachable ≤top-5 at every divergence (20 at top-3) **and** both neural votes prefer gold | wider proposal reach (beam / multi-position) — two-vote will accept |
| **VETO_RISK** | **22** | reachable but ≥1 neural vote opposes gold → two-vote (m>0) blocks it | acceptance rule (locked — see acceptance sweep) |
| **KNOW** | **14** | gold not in cond top-5 at some divergence (1 lattice miss, 1 segmentation break) | retrain / dictionary coverage — mechanism-proof |

**Axis-A, all 161 divergence positions in the 60:**

| gold char rank | positions | share |
|---|---|---|
| top-1 | 75 | 47% |
| top-2/3 | 59 | 37% |
| top-4/5 | 12 | 7% |
| rank > 5 | 14 | 9% |
| not a lattice candidate | 1 | <1% |

**84% of divergence positions have gold in cond top-3.** The model overwhelmingly
knows the character. The 60 fail not because cond is ignorant but because (i)
the gold path needs *several* positions corrected simultaneously and the
single-position proposer never assembles them (MECH), or (ii) even when
reachable, one of the two neural votes disagrees so the locked accept rule
vetoes it (VETO_RISK). Genuine knowledge gaps (KNOW) — rare words / proper
nouns (峽爸→呷霸, 英雕→櫻鯛), homophone-dense idioms, and one lattice-coverage
miss (剎 absent at its reading in 踩剎車) — are only 14/60.

**Every MECH case is multi-divergence** (2–7 positions; 0 single-divergence) —
the direct fingerprint of a joint-reach problem, and the mandate for T2.

Per-sentence table: `cond-proposer-silence-diag-tw538.tsv`
(idx, bucket, num_div, worst_rank, lattice_miss, cond/v2c gold-vs-draft, div_ranks, readings, draft, gold).

---

## T2 — multi-position cond beam

`zenzai_multiproposer.cpp` forks the 401 harness and injects one block into the
pool builder: after the single-position proposals, beam-decode cond's top-k over
the worst `beam_pos` syllable positions (by neural logp), keep `beam_width`
hypotheses by cumulative cond score, re-walk each survivor (reading-fidelity +
node-unigram checked), add to the pool. **Only the candidate pool grows; the
two-vote acceptance rule is byte-for-byte unchanged.** `beam_width=0` reproduces
the 401 baseline exactly (the A/B control).

Red lines held: cond weights untouched, reading law enforced (fidelity 0),
two-vote not weakened (best m stays 1.0, grid-searched, regressions ≤1).

| config | reached B-class | two-vote m=1.0 | net vs 397 | regress | fidelity | mean ms |
|---|---|---|---|---|---|---|
| **control** (beam off) | 7 | **401** | +4 | 1 | 0 | 3.8k |
| **beam 8/3/8** | **11** | **402** | +5 | 1 | 0 | 19k |

A richer beam (10/3/12) was **not pursued**: at 8/3/8 the beam already reached
+4 B-class and the *locked* two-vote converted only +1 (~25%). More reach cannot
move the headline while acceptance is the binding wall — so the marginal value
of a ~4× slower run is a near-certain +0. The knob to grid is not beam size but
the accept signal, which is out of this baton's red lines.

The beam assembles exactly the multi-divergence MECH targets — 硬邦邦, 是帶點油嫩
油嫩, 沒事…有沒有事, 還真是爛鍋配爛蓋 (all 2+ swaps). Reach climbs 7→11 (+4). But
the locked two-vote (which requires **both** v2c and cond to beat the in-pool
champion by margin 1.0 — stricter than "beat the draft") accepts only **1** of
the 4 → **402**. The other 3 reached-but-vetoed paths are the acceptance wall
biting again, now on freshly-reached candidates.

Two-vote m grid (beam 8/3/8): m=0→398, 0.25→400, 0.5→401, **1.0→402**, 2.0→397.
Same shape as the baseline sweep; m=1.0 remains the knee.

---

## Reading — keep attacking or stop?

- **Not a knowledge wall.** KNOW is 14/60; 84% of divergence positions have gold
  in cond top-3. The proposer is a mechanism problem, as suspected.
- **Reach is cheaply improvable, conversion is not.** Multi-position beam is the
  right shape (reach +4, and it hits the exact multi-divergence cases). But
  under the *locked* two-vote it converts +1. The binding constraint has moved
  from *reach* (T2 fixed a chunk of it) to **acceptance** (VETO_RISK 22 +
  reached-but-vetoed) — and acceptance was already榨乾'd in the prior baton
  (walk-downweight collapses; two-vote m=1 is the knee).
- **Recommendation for the B-class line:** the cheap mechanism win is banked
  (402). Beyond it, ~44/60 are gated by acceptance (VETO_RISK 22 + KNOW-adjacent
  vetoes) or knowledge (14). Neither yields to more proposer beam. **Further
  B-class gains need either a better acceptance signal (a genuinely stronger
  reranker, not a reweight) or model knowledge (2-epoch retrain / dictionary
  coverage for the KNOW 14)** — both larger investments. Absent those, the
  B-class line is near its cheap ceiling; the higher-leverage next move is the
  deferred shipping debt (distillation / latency of the 19s research config,
  which is not shippable as-is).

---

## Reproduce

```bash
cd Source/Engine/eval/benchmarks
ENGINE=../..
# T1 silence diagnostic (writes bucket TSV)
clang++ -std=c++17 -O2 -I$ENGINE -I$ENGINE/gramambular2 \
  zenzai_silence_diag.cpp $ENGINE/CondConverterScorer.cpp \
  $ENGINE/gramambular2/reading_grid.cpp $ENGINE/CorpusBigramContextModel.cpp \
  $ENGINE/NeuralLMPathScorer.cpp $ENGINE/ParselessLM.cpp \
  $ENGINE/ParselessPhraseDB.cpp $ENGINE/MemoryMappedFile.cpp -o /tmp/zenzai_diag
/tmp/zenzai_diag tw538-northstar.tsv ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv 0.75 \
  ../models/path-char-lstm-spoken-v2c.bin ../models/cond-converter-v2.bin \
  5 8 0.5 0.25 0.5 -2.5 ../analysis/cond-proposer-silence-diag-tw538.tsv
# expect: NEVER_REACHED 60 ; BUCKET_MECH 24 ; BUCKET_VETO_RISK 22 ; BUCKET_KNOW 14

# T2 multi-position beam (last three args = beam_pos beam_k beam_width; 0=off)
clang++ -std=c++17 -O2 -I$ENGINE -I$ENGINE/gramambular2 \
  zenzai_multiproposer.cpp $ENGINE/CondConverterScorer.cpp \
  $ENGINE/gramambular2/reading_grid.cpp $ENGINE/CorpusBigramContextModel.cpp \
  $ENGINE/NeuralLMPathScorer.cpp $ENGINE/ParselessLM.cpp \
  $ENGINE/ParselessPhraseDB.cpp $ENGINE/MemoryMappedFile.cpp -o /tmp/zenzai_mp
/tmp/zenzai_mp tw538-northstar.tsv ../../../Data/data.txt \
  ../../../Data/word-bigrams.tsv 0.75 \
  ../models/path-char-lstm-spoken-v2c.bin ../models/cond-converter-v2.bin \
  5 8 0.5 0.25 0.5 -2.5 8 3 8
# expect: beam off (…0) → twovote m=1 401 reached 7 ; beam 8 3 8 → m=1 402 reached 11
#         READING_FIDELITY_FAIL 0/537
```

## Evidence (persistent, `~/laowang-data/`)

```
silence_diag.out    sha256 51ae18182e83c8d9c5ba8cf69c26d916a202dd68a6253336cea1d0f514815607
zenzai_mp_run1.out  sha256 5a7fb7063779a8cb0af76900e7bdc81686fc8458ce28fe9bd4cd54a08e310551
```

`silence_diag.out` = T1 buckets (also `cond-proposer-silence-diag-tw538.tsv`,
committed). `zenzai_mp_run1.out` = T2 control (beam off → 401) + beam 8/3/8
(→ 402), both with the full two-vote m grid.
