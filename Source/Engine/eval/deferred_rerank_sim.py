#!/usr/bin/env python3
"""Deferred global re-rank simulation for the right-context problem.

IMPORTANT FINDING (2026-07-07): llama-server /completion with n_predict=0 does
NOT return prompt logprobs -- it generates one token and returns that token's
logprob. llm_rerank_poc.py's score_full_sentence_logprob therefore measured
P(next-token | sentence), a weak proxy, not P(sentence). This script implements
TRUE sentence scoring via the chain rule: one single-token call per position
(token-array prompts + cache_prompt = nested prefixes decode incrementally),
reading the target token's logprob out of top_logprobs (n_probs).

One full-sentence pass per (case, candidate) yields per-token logprobs; every
right-context milestone k is then a partial sum derived offline, so flip-policy
and theta sweeps cost zero extra server calls.

Scenarios:
  E (engine-right): provisional decision = expected char (engine got it right)
  W (engine-wrong): provisional = first allowed char != expected
                    (the case deferred re-rank must rescue)

Run:
  python3 Source/Engine/eval/deferred_rerank_sim.py \
    --cases Source/Engine/eval/zhuyin_neural_rerank_poc_cases.jsonl \
    --server-url http://127.0.0.1:57762
"""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

from llm_rerank_poc import LlamaClient, load_cases

ABSENT_FLOOR_DELTA = 2.0  # target not in top_logprobs: min(listed) - this
TOP_LOGPROBS = 40


class ChainRuleScorer:
    """True P(text | left) via per-token next-token calls."""

    def __init__(self, client: LlamaClient):
        self.client = client
        self.detok_cache: dict[int, str] = {}
        self.score_cache: dict[tuple, float] = {}
        self.call_count = 0
        self.approx_count = 0
        self.call_latencies: list[float] = []

    def tokenize(self, text: str, add_special: bool = True) -> list[int]:
        resp = self.client.session.post(
            f"{self.client.base_url}/tokenize",
            json={"content": text, "add_special": add_special},
            timeout=self.client.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("tokens", [])

    def detok(self, tok: int) -> str:
        if tok not in self.detok_cache:
            self.detok_cache[tok] = self.client.detokenize([tok])
        return self.detok_cache[tok]

    def next_token_logprob(self, prefix_tokens: list[int], target: int) -> float:
        key = (tuple(prefix_tokens), target)
        if key in self.score_cache:
            return self.score_cache[key]
        lp = self._next_token_logprob_uncached(prefix_tokens, target)
        self.score_cache[key] = lp
        return lp

    def _next_token_logprob_uncached(self, prefix_tokens: list[int], target: int) -> float:
        """Exact raw logprob of `target` after `prefix_tokens` via the
        logit_bias probe: bias the target +100 so greedy sampling picks it,
        then read its reported logprob -- verified on this server build
        (b9692) to be the RAW pre-bias value (matches the unbiased
        top_logprobs entry to full precision). One call, no top-k loss."""
        t0 = time.perf_counter()
        try:
            data = self.client.completion(
                prompt=prefix_tokens,
                max_tokens=1,
                temperature=0.0,
                logprobs=True,
                top_logprobs=1,
                cache_prompt=True,
                logit_bias={str(target): 100.0},
            )
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 500:
                # Sampled token is a bare UTF-8 continuation byte (rare char
                # split into byte tokens); this server build 500s formatting
                # the response. A char's continuation bytes are
                # near-deterministic given its first byte (P ~ 1), and the
                # same approximation applies to every candidate, so logprob 0
                # keeps comparisons fair.
                self.approx_count += 1
                return 0.0
            body = getattr(getattr(exc, "response", None), "text", "")
            print(f"DEBUG scoring call failed: prefix={prefix_tokens!r} target={target} body={body[:300]}")
            raise
        self.call_count += 1
        self.call_latencies.append((time.perf_counter() - t0) * 1000.0)
        probs = data.get("completion_probabilities") or []
        if probs and probs[0].get("id") == target:
            return float(probs[0]["logprob"])
        # Bias failed to force the target (raw < -100, effectively impossible)
        self.approx_count += 1
        return -30.0

    def token_scores(self, left: str, tail: str) -> list[tuple[int, float]]:
        """Score P(tail | left) token by token.

        Returns [(end_char_offset_within_tail, logprob), ...] so milestone
        partial sums can be derived offline. Left tokens carry offset <= 0 and
        must be included in every milestone sum.

        Scores the WHOLE sequence (sentinel + left + tail) for every
        candidate: BPE can merge left's last char with the candidate char into
        one token (e.g. "我再" is a single token while "我/載" is two), so
        scoring only from a common-prefix point would charge P(left char) to
        merged candidates and not to unmerged ones. Scoring everything from
        the sentinel gives each candidate the exact log-probability of its
        full character sequence under its canonical tokenization -- the
        comparable quantity. The per-case call overhead is absorbed by the
        client-side score cache (left-prefix calls are identical across
        candidates until the boundary).

        A newline sentinel avoids the empty-prompt 400 (Qwen has no BOS) and
        is identical across candidates.
        """
        sent_left = "\n" + left
        full_toks = self.tokenize(sent_left + tail)
        sent_toks = self.tokenize("\n")
        start = 0
        while (
            start < min(len(sent_toks), len(full_toks))
            and sent_toks[start] == full_toks[start]
        ):
            start += 1

        out = []
        consumed = self.client.detokenize(full_toks[:start])
        for i in range(start, len(full_toks)):
            lp = self.next_token_logprob(full_toks[:i], full_toks[i])
            consumed += self.detok(full_toks[i])
            end_in_tail = len(consumed) - len(sent_left)
            out.append((end_in_tail, lp))
        return out


def collect(client, cases, verbose=False):
    """matrix[case_id] = {focus, allowed, expected_char, k_max,
    per_candidate: {char: [(end_offset_in_tail, logprob), ...]}}"""
    scorer = ChainRuleScorer(client)
    matrix = {}
    for case in cases:
        focus = case.focus[0]
        allowed_f = case.allowed[focus]
        left = case.preceding + case.expected[:focus]
        right_full = case.expected[focus + 1 :]

        per_candidate = {}
        for ch in allowed_f:
            per_candidate[ch] = scorer.token_scores(left, ch + right_full)

        matrix[case.id] = {
            "focus": focus,
            "allowed": allowed_f,
            "expected_char": case.expected[focus],
            "k_max": len(right_full),
            "per_candidate": per_candidate,
        }
        if verbose:
            print(f"collected {case.id} (k_max={len(right_full)}, |allowed|={len(allowed_f)})")
    return matrix, scorer


def milestone_score(entry, ch, k):
    """Sum of logprobs of tokens fully inside candidate char + first k right chars."""
    limit = 1 + k  # tail offsets: candidate char occupies [0,1)
    return sum(lp for end, lp in entry["per_candidate"][ch] if end <= limit)


def replay(matrix, theta, milestones_fn, provisional_fn):
    correct = 0
    total_flips = 0
    multi_flip = 0
    details = []
    for cid, entry in matrix.items():
        current = provisional_fn(entry)
        flips = 0
        for k in milestones_fn(entry["k_max"]):
            scores = {ch: milestone_score(entry, ch, k) for ch in entry["allowed"]}
            best = max(scores, key=scores.get)
            if best != current and scores[best] - scores[current] > theta:
                current = best
                flips += 1
        ok = current == entry["expected_char"]
        correct += 1 if ok else 0
        total_flips += flips
        if flips > 1:
            multi_flip += 1
        details.append((cid, current, entry["expected_char"], flips, ok))
    return correct, total_flips, multi_flip, details


def main():
    parser = argparse.ArgumentParser(description="Deferred global re-rank simulation (true chain-rule scoring)")
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--server-url", default="http://127.0.0.1:8080")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    print(f"Loaded {len(cases)} cases")
    client = LlamaClient(args.server_url, timeout=25.0)
    if not client.health():
        print("WARNING: server /health not 200")

    t0 = time.perf_counter()
    matrix, scorer = collect(client, cases, verbose=args.verbose)
    lat = scorer.call_latencies
    print(
        f"\nCollection: {time.perf_counter() - t0:.1f}s, {scorer.call_count} single-token calls, "
        f"per-call mean={statistics.mean(lat):.1f}ms p95={sorted(lat)[int(0.95 * (len(lat) - 1))]:.1f}ms, "
        f"approximated continuation-byte calls={scorer.approx_count}"
    )

    print("\n=== Instantaneous argmax accuracy by right-context length k ===")
    for k_probe in range(0, 6):
        n = ok = 0
        for entry in matrix.values():
            k = min(k_probe, entry["k_max"])
            scores = {ch: milestone_score(entry, ch, k) for ch in entry["allowed"]}
            n += 1
            if max(scores, key=scores.get) == entry["expected_char"]:
                ok += 1
        print(f"  k={k_probe} (capped at k_max): {ok}/{n} ({ok / max(n, 1) * 100:.0f}%)")

    provisional = {
        "E(engine-right)": lambda e: e["expected_char"],
        "W(engine-wrong)": lambda e: next(
            (c for c in e["allowed"] if c != e["expected_char"]), e["expected_char"]
        ),
    }
    milestones = {
        "every-char": lambda km: list(range(1, km + 1)),
        "k2+end": lambda km: sorted({min(2, km), km} - {0}),
        "end-only": lambda km: [km] if km > 0 else [],
    }

    print("\n=== Flip-policy replay: final acc / flips f / multi-flip m ===")
    thetas = (0.0, 0.5, 1.0, 2.0, 3.0)
    print(f"{'scenario':<18}{'milestones':<12}" + "".join(f"{'th=' + str(t):<20}" for t in thetas))
    for pname, pfn in provisional.items():
        for mname, mfn in milestones.items():
            cells = []
            for theta in thetas:
                c, f, ff, _ = replay(matrix, theta, mfn, pfn)
                cells.append(f"{c}/{len(matrix)} f={f:<3} m={ff:<2}")
            print(f"{pname:<18}{mname:<12}" + "  ".join(cells))

    for pname in provisional:
        for theta in (0.5, 1.0):
            _, _, _, details = replay(matrix, theta, milestones["k2+end"], provisional[pname])
            misses = [d for d in details if not d[4]]
            if misses:
                print(f"\n=== Misses: {pname} + k2+end + th={theta} ===")
                for cid, got, exp, flips, _ in misses:
                    print(f"  {cid}: got={got} expected={exp} flips={flips}")


if __name__ == "__main__":
    main()
