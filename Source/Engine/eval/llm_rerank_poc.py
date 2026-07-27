#!/usr/bin/env python3
"""
LLM Single-Position Constrained Pick PoC Harness for iBopomofo.

New focus after first run:
- Only perform constrained pick on the positions listed in "focus".
- Extremely strict prompt that demands the model output EXACTLY one character
  from the allowed list for that position.
- Post-parse enforcement + safe fallback.
- Goal: respect allowed sets + much lower latency (target << 1s per decision).

Input format (JSONL):

{
  "id": "...",
  "preceding": "...",
  "readings": ["ㄨㄛˇ", "ㄗㄞˋ", ...],
  "allowed": [ ["我"], ["在","再"], ... ],
  "expected": "...",
  "focus": [1],
  "note": "..."
}

Run with:
  python3 Source/Engine/eval/llm_rerank_poc.py \
    --cases Source/Engine/eval/example_llm_cases.jsonl \
    --server-url http://127.0.0.1:8080 \
    --mode constrained \
    --verbose
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Case:
    id: str
    preceding: str
    readings: List[str]
    allowed: List[List[str]]
    expected: str
    focus: List[int]
    note: str = ""


# ---------------------------------------------------------------------------
# llama-server client (OpenAI-compatible /v1/chat/completions)
# ---------------------------------------------------------------------------

class LlamaClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 16,
        temperature: float = 0.0,
        logprobs: bool = False,
        top_logprobs: int = 20,
        stop: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/chat/completions"
        payload: Dict[str, Any] = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if logprobs:
            payload["logprobs"] = True
            payload["top_logprobs"] = top_logprobs
        if stop:
            payload["stop"] = stop

        resp = self.session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def tokenize(self, text: str) -> list[int]:
        url = f"{self.base_url}/tokenize"
        try:
            resp = self.session.post(url, json={"content": text, "add_special": False}, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json().get("tokens", [])
        except Exception:
            return []

    def detokenize(self, tokens: list[int]) -> str:
        url = f"{self.base_url}/detokenize"
        try:
            resp = self.session.post(url, json={"tokens": tokens}, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json().get("content", "")
        except Exception:
            return ""

    def completion(
        self,
        prompt: str,
        logit_bias: Optional[dict] = None,
        max_tokens: int = 1,
        temperature: float = 0.0,
        logprobs: bool = True,
        top_logprobs: int = 50,
        cache_prompt: bool = True,
        stop: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Use raw /completion endpoint for better control over logit_bias and scoring."""
        url = f"{self.base_url}/completion"
        payload: Dict[str, Any] = {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if logit_bias:
            payload["logit_bias"] = {str(k): float(v) for k, v in logit_bias.items()}
        if logprobs:
            payload["logprobs"] = True
            payload["n_probs"] = top_logprobs   # llama-server often uses n_probs
        if cache_prompt:
            payload["cache_prompt"] = True
        if stop:
            payload["stop"] = stop

        resp = self.session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def health(self) -> bool:
        try:
            r = self.session.get(f"{self.base_url}/health", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Core: logit_bias + position-level constrained beam search
# ---------------------------------------------------------------------------

def baseline_choice(allowed: List[List[str]]) -> str:
    """Naive engine-like: always take the first entry in each allowed list."""
    return "".join(a[0] for a in allowed if a)


def build_char_to_token_map(client: LlamaClient, chars: set[str]) -> dict[str, set[int]]:
    """Build reliable mapping from char to the token IDs that can produce it.

    Tries multiple boundary contexts and verifies round-trip with detokenize.
    This is critical for correct logit_bias application.
    """
    mapping: dict[str, set[int]] = {ch: set() for ch in chars}
    for ch in chars:
        candidates = set()
        for ctx in ["", " ", "\n", "的", "我"]:  # common boundaries to catch tokenization variants
            test = ctx + ch
            toks = client.tokenize(test)
            if not toks:
                continue
            # Check last 1-2 tokens
            for length in [1, 2]:
                if length > len(toks):
                    continue
                last_toks = toks[-length:]
                decoded = client.detokenize(last_toks).strip()
                if ch in decoded or decoded == ch:
                    candidates.update(last_toks)
                    break
        # Also try the char alone
        toks = client.tokenize(ch)
        if toks:
            decoded = client.detokenize(toks[-1:]).strip()
            if ch in decoded or decoded == ch:
                candidates.add(toks[-1])
        mapping[ch] = candidates
    return mapping


def build_logit_bias(allowed_token_ids: set[int], boost: float = 100.0, suppress: float = -100.0) -> dict[str, float]:
    """Create logit_bias dict.

    We boost the allowed tokens strongly. 
    To strictly mask, we would need the full vocab to suppress others.
    In practice for this server + top_logprobs approach, we boost allowed
    and later filter/renormalize in the beam logic.
    """
    bias = {}
    for tok in allowed_token_ids:
        bias[str(tok)] = boost
    # Note: tokens not listed get bias=0 by default in llama-server.
    # For stricter suppression we would list common tokens with negative,
    # but boosting + filtering in post-processing is the workable PoC approach.
    return bias


def get_allowed_tokens_for_pos(token_map: dict[str, set[int]], allowed_chars: list[str]) -> set[int]:
    toks = set()
    for ch in allowed_chars:
        toks.update(token_map.get(ch, set()))
    return toks


def expand_one_position(
    client: LlamaClient,
    prefix: str,
    allowed_chars: list[str],
    token_map: dict[str, set[int]],
    beam_size: int,
    debug: bool = False,
) -> list[tuple[str, float]]:
    """One step of constrained expansion using logit_bias + top_logprobs.

    Returns list of (new_partial_text, new_score) for this step.
    Uses boost on allowed tokens and filters results to only allowed chars.
    """
    allowed_toks = get_allowed_tokens_for_pos(token_map, allowed_chars)
    if not allowed_toks:
        return [(prefix + allowed_chars[0], -1e9)] if allowed_chars else [(prefix, -1e9)]

    # Optimization: if only one possible char, no need to call server
    if len(allowed_chars) == 1:
        return [(prefix + allowed_chars[0], 0.0)]

    logit_bias = build_logit_bias(allowed_toks, boost=100.0)  # stronger boost

    try:
        data = client.completion(
            prompt=prefix,
            logit_bias=logit_bias,
            max_tokens=2,
            temperature=0.0,
            logprobs=True,
            top_logprobs=40,
            cache_prompt=True,
        )
    except Exception:
        # Safe fallback
        return [(prefix + allowed_chars[0], -1e9) for _ in range(min(beam_size, len(allowed_chars)))]

    if debug:
        print("\n=== DEBUG EXPAND ===")
        print(f"prefix: {prefix!r}")
        print(f"allowed_chars: {allowed_chars}")
        print(f"allowed_toks: {allowed_toks}")
        print(f"logit_bias keys (sample): {list(logit_bias.keys())[:5]}...")
        print(f"raw response content: {data.get('content', '')!r}")
        print(f"full logprobs section: {data.get('logprobs', {})}")

    candidates: list[tuple[str, float]] = []

    # Parse logprobs. Structure varies slightly by llama-server version.
    # We look for content and probs.
    content = data.get("content", "") or ""
    logprobs_section = data.get("logprobs", {})
    top_probs = logprobs_section.get("top_logprobs", []) or logprobs_section.get("content", []) or []

    if debug:
        print(f"top_probs raw (first 5): {top_probs[:5]}")

    # First, try to use generated content if it matches an allowed char
    for ch in content:
        if ch in allowed_chars:
            candidates.append((prefix + ch, 0.0))
            break

    # Improved multi-token aware extraction + accumulation
    # For each top token, map to char and accumulate logprob per char
    char_to_best_logp: dict[str, float] = {}
    for entry in top_probs:
        if not isinstance(entry, dict):
            continue
        tok_id = entry.get("id") or entry.get("token_id")
        logp = entry.get("logprob", -10.0)
        if tok_id is None:
            continue

        try:
            decoded = client.detokenize([tok_id]).strip()
        except:
            decoded = entry.get("token", "")

        for ch in allowed_chars:
            # Match if the token decodes to the char or starts/contains it (for multi-token)
            if ch == decoded or decoded == ch or decoded.startswith(ch) or ch in decoded:
                if ch not in char_to_best_logp or logp > char_to_best_logp[ch]:
                    char_to_best_logp[ch] = float(logp)
                break

    for ch, sc in char_to_best_logp.items():
        candidates.append((prefix + ch, sc))

    # Fallback if nothing matched
    if not candidates:
        for ch in allowed_chars[:beam_size]:
            candidates.append((prefix + ch, -5.0))

    # Keep only valid and sort by score (higher logprob better)
    valid = [c for c in candidates if any(ch in c[0][-len(ch):] or c[0].endswith(ch) for ch in allowed_chars)]
    valid.sort(key=lambda x: x[1], reverse=True)

    if debug and valid:
        print(f"char_to_best_logp: {char_to_best_logp}")
        print(f"Final valid candidates for this pos: {valid}")

    return valid[:beam_size] if valid else [(prefix + allowed_chars[0], -10.0)]


def position_level_constrained_beam_search(
    client: LlamaClient,
    preceding: str,
    readings: List[str],
    allowed: List[List[str]],
    beam_size: int = 3,
    debug_case_id: str | None = None,
    focus: Optional[List[int]] = None,
) -> str:
    """Core: position-level constrained beam search using logit_bias.

    - For non-focus positions: use lightweight local constrained scoring (expand_one_position).
    - For focus positions: use expensive global full-sentence preview scoring.
    This preserves accuracy on ambiguous positions while keeping most positions fast.
    """
    if not readings:
        return ""

    all_chars = {ch for alist in allowed for ch in alist}
    token_map = build_char_to_token_map(client, all_chars)

    if focus is None:
        focus = []

    # Simple client-side cache
    prefix_cache: dict[str, dict] = {}

    beams: list[tuple[str, float]] = [("", 0.0)]

    baseline_rest = [a[0] for a in allowed]

    for pos in range(len(readings)):
        new_beams: list[tuple[str, float]] = []
        allowed_chars = allowed[pos]
        do_debug = (debug_case_id == "seed-4" and pos == 1)
        use_global = pos in focus

        for partial, score in beams:
            prefix = preceding + partial
            if use_global:
                # Expensive global full preview only on focus positions
                for ch in allowed_chars:
                    preview_full = preceding + partial + ch + ''.join(baseline_rest[pos+1:])
                    full_score = score_full_sentence_logprob(client, preview_full)
                    new_partial = partial + ch
                    new_beams.append((new_partial[len(preceding):], full_score))
            else:
                # Lightweight local for non-focus
                expansions = expand_one_position(
                    client, prefix, allowed_chars, token_map, beam_size, debug=do_debug
                )
                for new_partial, delta in expansions:
                    new_beams.append((new_partial[len(preceding):], score + delta))

        if not new_beams:
            new_beams = [(partial + allowed_chars[0], score - 1.0) for partial, score in beams]

        new_beams.sort(key=lambda x: x[1], reverse=True)
        beams = new_beams[:beam_size]

    if not beams:
        return baseline_choice(allowed)

    # Final global re-rank among surviving beams using full sentence score
    # This helps correct any local mistakes if the correct path survived in beam.
    best_text = beams[0][0]
    best_score = beams[0][1]
    for partial, _ in beams:
        full_text = preceding + partial
        full_score = score_full_sentence_logprob(client, full_text)
        if full_score > best_score:
            best_score = full_score
            best_text = partial
    return best_text


def score_full_sentence_logprob(client: LlamaClient, text: str) -> float:
    """Score the full sentence by summing logprobs of its tokens using the model.
    Use SUM (not average) to preserve magnitude of differences around focus position.
    """
    try:
        data = client.completion(
            prompt=text,
            max_tokens=0,
            temperature=0.0,
            logprobs=True,
            top_logprobs=1,
            cache_prompt=True,
        )
        probs = data.get("completion_probabilities", [])
        if not probs:
            return -1e9
        return sum(p.get("logprob", 0.0) for p in probs)  # sum for stronger signal
    except:
        return -1e9


# ---------------------------------------------------------------------------
# Evaluation loop
# ---------------------------------------------------------------------------

def load_cases(path: Path) -> List[Case]:
    cases: List[Case] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        obj = json.loads(line)
        # Support both "focus" and "focus_positions" for compatibility with new real cases
        focus = obj.get("focus") or obj.get("focus_positions") or list(range(len(obj["readings"])))
        cases.append(
            Case(
                id=obj["id"],
                preceding=obj.get("preceding", ""),
                readings=obj["readings"],
                allowed=obj["allowed"],
                expected=obj["expected"],
                focus=focus,
                note=obj.get("note", ""),
            )
        )
    return cases


def evaluate(
    client: LlamaClient,
    cases: List[Case],
    mode: str,
    beam_size: int,
    verbose: bool,
) -> None:
    """Evaluation using logit_bias + position-level constrained beam search.

    Full sequence beam search where at every position the expansion is
    strictly limited via logit_bias to tokens that decode to the allowed
    homophones for that reading.
    """
    baseline_correct = 0
    llm_correct = 0
    focus_correct = 0
    focus_total = 0

    latencies: List[float] = []
    details: List[Dict[str, Any]] = []

    for case in cases:
        t0 = time.perf_counter()

        base = baseline_choice(case.allowed)
        base_ok = base == case.expected

        llm_text = base
        llm_ok = base_ok

        if mode in ("constrained", "beam", "both"):
            llm_text = position_level_constrained_beam_search(
                client,
                case.preceding,
                case.readings,
                case.allowed,
                beam_size=beam_size,
                debug_case_id=case.id,
                focus=case.focus,
            )
            llm_ok = llm_text == case.expected

        dt = (time.perf_counter() - t0) * 1000.0  # ms
        latencies.append(dt)

        if base_ok:
            baseline_correct += 1
        if llm_ok:
            llm_correct += 1

        # Focus position accuracy
        for fi in case.focus:
            if fi < len(case.allowed):
                focus_total += 1
                chosen = llm_text[fi] if fi < len(llm_text) else ""
                if chosen == case.expected[fi]:
                    focus_correct += 1

        details.append(
            {
                "id": case.id,
                "expected": case.expected,
                "baseline": base,
                "llm": llm_text,
                "baseline_ok": base_ok,
                "llm_ok": llm_ok,
                "latency_ms": round(dt, 1),
                "note": case.note,
            }
        )

        if verbose:
            status = "OK" if llm_ok else "MISS"
            print(f"[{status}] {case.id}: exp={case.expected!r} llm={llm_text!r} ({dt:.1f}ms)")

    n = len(cases) or 1
    print("\n=== Summary ===")
    print(f"Cases: {len(cases)}")
    print(f"Baseline sentence acc : {baseline_correct}/{len(cases)} ({baseline_correct / n * 100:.1f}%)")
    print(f"LLM (logit_bias + beam) acc : {llm_correct}/{len(cases)} ({llm_correct / n * 100:.1f}%)")

    if focus_total > 0:
        print(f"LLM focus-pos acc     : {focus_correct}/{focus_total} ({focus_correct / focus_total * 100:.1f}%)")

    if latencies:
        mean = statistics.mean(latencies)
        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(0.95 * (len(latencies) - 1))]
        print(f"Latency (ms)  mean={mean:.1f}  p50={p50:.1f}  p95={p95:.1f}  max={max(latencies):.1f}")

    regressions = sum(1 for d in details if d["baseline_ok"] and not d["llm_ok"])
    print(f"Regressions (baseline OK but LLM wrong): {regressions}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="LLM logit_bias + position-level constrained beam search PoC"
    )
    parser.add_argument("--cases", required=True, type=Path, help="JSONL file with cases")
    parser.add_argument(
        "--server-url",
        default=os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:8080"),
        help="Base URL of running llama-server",
    )
    parser.add_argument(
        "--mode",
        choices=["constrained", "beam", "both"],
        default="constrained",
        help="constrained = logit_bias beam search",
    )
    parser.add_argument("--beam-size", type=int, default=3, help="Beam width")
    parser.add_argument("--verbose", action="store_true", help="Print per-case results")
    parser.add_argument("--timeout", type=float, default=25.0, help="HTTP timeout seconds")

    args = parser.parse_args(argv)

    print(f"Loading cases from {args.cases}")
    cases = load_cases(args.cases)
    print(f"Loaded {len(cases)} cases")

    client = LlamaClient(args.server_url, timeout=args.timeout)

    print(f"Checking server health at {args.server_url} ...")
    if not client.health():
        print("WARNING: /health did not return 200. Model may still be loading.")

    evaluate(client, cases, mode=args.mode, beam_size=args.beam_size, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
