#!/usr/bin/env python3
"""Baton A-3: proxy discriminator ceiling (offline, no product path).

Uses a strong non-thinking instruct model (MLX Qwen2.5-Instruct 4bit)
as an upper-bound probe for a specialized homophone judge.

Layers:
  T1 — left-context constrained softmax (gold prefix; comparable to baton A)
  T2 — whole-sentence logprob with candidate substitution (shipping fill)
  T3 — prompted multiple-choice (shipping fill; greedy)

Does NOT write scores into the product ladder.

Example:
  ~/laowang-data/venv/bin/python Source/Engine/eval/tools/proxy_judge_measure.py \\
    --repo ~/iBopomofo --data-dir ~/laowang-data
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import mlx.core as mx
import numpy as np
from mlx_lm import load


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(8 * 1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_reading2chars(path: Path) -> dict[str, list[str]]:
    r2c: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line[0] == "#":
            continue
        tab = line.find("\t")
        if tab < 0:
            continue
        reading, body = line[:tab], line[tab + 1 :]
        chars = []
        for part in body.split(","):
            if ":" not in part:
                continue
            ch, _cnt = part.rsplit(":", 1)
            if ch:
                chars.append(ch)
        r2c[reading] = chars
    return r2c


def load_cases(path: Path) -> list[tuple[str, str]]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line[0] == "#":
            continue
        r, e = line.split("\t", 1)
        cases.append((r, e))
    return cases


def load_shipping(path: Path) -> list[dict]:
    """shipping_preds.tsv: sent_idx correct gold_in_pool pred gold ..."""
    rows = []
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    for line in lines[1:]:
        p = line.split("\t")
        d = {header[i]: p[i] if i < len(p) else "" for i in range(len(header))}
        rows.append(d)
    return rows


def load_entropy(path: Path) -> dict[tuple[int, int], dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    out = {}
    for line in lines[1:]:
        p = line.split("\t")
        d = {header[i]: p[i] if i < len(p) else "" for i in range(len(header))}
        out[(int(d["sent_idx"]), int(d["pos"]))] = d
    return out


class ProxyLM:
    def __init__(self, model_path: str):
        t0 = time.time()
        self.model, self.tokenizer = load(model_path)
        self.load_s = time.time() - t0
        self.model_path = model_path
        # cache char -> token id (single-token only)
        self._char_tid: dict[str, int | None] = {}

    def char_token_id(self, ch: str) -> int | None:
        if ch in self._char_tid:
            return self._char_tid[ch]
        ids = self.tokenizer.encode(ch, add_special_tokens=False)
        tid = ids[0] if len(ids) == 1 else None
        self._char_tid[ch] = tid
        return tid

    def encode_text(self, text: str) -> list[int]:
        return self.tokenizer.encode(text, add_special_tokens=False)

    def forward_logits(self, token_ids: list[int]) -> mx.array:
        """Return logits [1, T, V] for token_ids."""
        if not token_ids:
            # empty: use BOS if available
            bos = getattr(self.tokenizer, "bos_token_id", None) or getattr(
                self.tokenizer, "eos_token_id", 0
            )
            token_ids = [bos]
        x = mx.array([token_ids])
        out = self.model(x)
        if isinstance(out, (tuple, list)):
            out = out[0]
        mx.eval(out)
        return out

    def next_logprobs_for_candidates(
        self, prefix_ids: list[int], candidates: list[str]
    ) -> tuple[dict[str, float], float, str]:
        """Log-softmax over candidates only. Returns (logp_by_char, H_bits, argmax_char)."""
        logits = self.forward_logits(prefix_ids if prefix_ids else [self.tokenizer.eos_token_id or 0])
        last = logits[0, -1]  # [V]
        # gather candidate logits
        scored: list[tuple[str, float]] = []
        for ch in candidates:
            tid = self.char_token_id(ch)
            if tid is None:
                continue
            scored.append((ch, float(last[tid])))
        if not scored:
            return {}, float("nan"), ""
        # log-softmax
        m = max(s for _, s in scored)
        exps = [(ch, math.exp(s - m)) for ch, s in scored]
        Z = sum(e for _, e in exps)
        logp = {ch: math.log(e) - math.log(Z) for ch, e in exps}
        # entropy bits
        H = 0.0
        for ch, lp in logp.items():
            p = math.exp(lp)
            if p > 0:
                H -= p * math.log2(p)
        best = max(logp.items(), key=lambda kv: kv[1])[0]
        return logp, H, best

    def sequence_logprob(self, text: str) -> float:
        ids = self.encode_text(text)
        if len(ids) < 2:
            return 0.0
        logits = self.forward_logits(ids)
        # logits[t] predicts ids[t+1]
        lp = 0.0
        for t in range(len(ids) - 1):
            row = logits[0, t]
            # log_softmax at target
            # numerically stable via mx
            r = row - mx.max(row)
            log_denom = mx.log(mx.sum(mx.exp(r)))
            lp += float(r[ids[t + 1]] - log_denom)
        return lp

    def score_candidates_at_pos(
        self, base_text: str, pos: int, candidates: list[str]
    ) -> dict[str, float]:
        """T2: substitute each candidate at character position pos; return seq logprob."""
        chars = list(base_text)
        if pos < 0 or pos >= len(chars):
            return {}
        out = {}
        for ch in candidates:
            if self.char_token_id(ch) is None:
                continue
            chars[pos] = ch
            out[ch] = self.sequence_logprob("".join(chars))
        return out


T3_SYSTEM = (
    "你是繁體中文同音字判別助手。只輸出一個漢字，必須是候選清單中的字，"
    "不要輸出其他任何文字、標點或解釋。"
)

T3_USER_TMPL = """下列句子中，符號 ▢ 代表一個需要填入的位置。
請依整句語意，從候選字中選出最適合的一個字。

句子：
{sentence}

候選字（只能選一個）：
{choices}

請只輸出一個候選字。"""


def build_t3_prompt(tokenizer, sentence_with_blank: str, choices: list[str]) -> str:
    user = T3_USER_TMPL.format(
        sentence=sentence_with_blank, choices="、".join(choices)
    )
    # chat template, non-thinking
    messages = [
        {"role": "system", "content": T3_SYSTEM},
        {"role": "user", "content": user},
    ]
    try:
        return tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
    except Exception:
        return T3_SYSTEM + "\n\n" + user + "\n答案："


def t3_pick(lm: ProxyLM, sentence_with_blank: str, choices: list[str]) -> tuple[str, bool]:
    prompt = build_t3_prompt(lm.tokenizer, sentence_with_blank, choices)
    ids = lm.tokenizer.encode(prompt)
    logits = lm.forward_logits(ids)
    last = logits[0, -1]
    # constrain to choice token ids
    best_ch, best_logit = "", -1e30
    for ch in choices:
        tid = lm.char_token_id(ch)
        if tid is None:
            continue
        v = float(last[tid])
        if v > best_logit:
            best_logit = v
            best_ch = ch
    valid = best_ch in choices and best_ch != ""
    return best_ch, valid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path.home() / "iBopomofo")
    ap.add_argument("--data-dir", type=Path, default=Path.home() / "laowang-data")
    ap.add_argument(
        "--model",
        type=str,
        default=str(Path.home() / "laowang-data/models/Qwen2.5-7B-Instruct-4bit-mlx"),
    )
    ap.add_argument(
        "--max-sents",
        type=int,
        default=0,
        help="0=all 537; for smoke tests use e.g. 20",
    )
    ap.add_argument(
        "--skip-t2",
        action="store_true",
        help="skip expensive T2 (report partial)",
    )
    ap.add_argument(
        "--t2-sample-sents",
        type=int,
        default=0,
        help="if >0 and full T2 too heavy, only first N sentences for T2",
    )
    args = ap.parse_args()
    repo: Path = args.repo
    data: Path = args.data_dir
    out_dir = data / "batonA3-proxy-judge"
    out_dir.mkdir(parents=True, exist_ok=True)
    analysis = repo / "Source/Engine/eval/analysis"

    cases = load_cases(repo / "Source/Engine/eval/benchmarks/tw538-northstar.tsv")
    r2c = load_reading2chars(data / "reading2chars.tsv")
    # shipping preds from A-2 dump
    ship_path = data / "batonA2-gate-dump/shipping_preds.tsv"
    if not ship_path.exists():
        print("FATAL: missing shipping preds", ship_path, file=sys.stderr)
        return 1
    ships = load_shipping(ship_path)
    ent = load_entropy(analysis / "tw538-residual-entropy.tsv")

    n_sents = len(cases) if args.max_sents <= 0 else min(args.max_sents, len(cases))
    log_path = out_dir / "measure.stdout.txt"
    log_f = log_path.open("w", encoding="utf-8")

    def log(msg: str = "") -> None:
        print(msg, flush=True)
        log_f.write(msg + "\n")
        log_f.flush()

    # model fingerprint
    model_path = Path(args.model)
    wpath = model_path / "model.safetensors"
    wsha = sha256_file(wpath) if wpath.exists() else "N/A"
    log(f"MODEL_PATH\t{model_path}")
    log(f"MODEL_WEIGHTS_SHA256\t{wsha}")
    log(f"MODEL_CONFIG\t{(model_path/'config.json').read_text()[:500]}")
    log(f"FRAMEWORK\tmlx-lm + mlx")
    log(f"SAMPLING\tgreedy / temperature 0 (argmax over constrained logits)")
    log(f"THINKING\tdisabled (non-thinking instruct; logits path, no CoT)")

    lm = ProxyLM(str(model_path))
    log(f"LOAD_SECONDS\t{lm.load_s:.3f}")
    log(f"MLX_LM_NOTE\tQwen2.5-7B-Instruct-4bit (mlx-community)")

    # ---------- T1 + validity gate ----------
    t1_rows = []  # per position
    t1_pos_ok = 0
    t1_pos_n = 0
    t1_gate_ok = 0  # on shipping-correct positions
    t1_gate_n = 0
    t1_sent_correct = 0
    t0 = time.time()

    for si in range(n_sents):
        readings, gold = cases[si]
        syls = [s for s in readings.split("-") if s]
        gchars = list(gold)
        ship = ships[si]["pred"] if si < len(ships) else gold
        schars = list(ship)
        # align length
        n = min(len(syls), len(gchars), len(schars))
        # T1: process gold left-to-right with one forward for full gold
        # encode each gold char; for position i, prefix = gold[:i]
        pred_chars_t1 = []
        gold_ids_prefix: list[int] = []
        for i in range(n):
            cands = r2c.get(syls[i], [])
            if gchars[i] not in cands:
                cands = list(cands) + [gchars[i]]
            # ensure single-token candidates
            cands = [c for c in cands if lm.char_token_id(c) is not None]
            if not cands:
                cands = [gchars[i]]
            logp, H, best = lm.next_logprobs_for_candidates(gold_ids_prefix, cands)
            if not best:
                best = gchars[i]
            pred_chars_t1.append(best)
            ship_ok_pos = schars[i] == gchars[i]
            t1_ok = best == gchars[i]
            t1_pos_n += 1
            if t1_ok:
                t1_pos_ok += 1
            if ship_ok_pos:
                t1_gate_n += 1
                if t1_ok:
                    t1_gate_ok += 1
            # advance prefix with GOLD (teacher forcing)
            tid = lm.char_token_id(gchars[i])
            if tid is not None:
                gold_ids_prefix.append(tid)
            else:
                # fallback encode
                gold_ids_prefix.extend(lm.encode_text(gchars[i]))

            t1_rows.append(
                {
                    "sent_idx": si,
                    "pos": i,
                    "reading": syls[i],
                    "gold": gchars[i],
                    "ship": schars[i],
                    "ship_ok": int(ship_ok_pos),
                    "t1_pred": best,
                    "t1_ok": int(t1_ok),
                    "t1_H": H,
                    "t1_gold_logp": logp.get(gchars[i], float("nan")),
                    "M": len(cands),
                    "gold_in_pool": ships[si].get("gold_in_pool", ""),
                }
            )
        # pad remaining gold chars if length mismatch
        t1_text = "".join(pred_chars_t1)
        # for sentence score compare full gold vs t1 on aligned prefix + rest gold?
        # standard: reconstruct full string with t1 preds for aligned, gold for rest
        if len(gchars) > n:
            t1_text = t1_text + "".join(gchars[n:])
        if t1_text == gold:
            t1_sent_correct += 1
        if (si + 1) % 25 == 0:
            log(f"T1_PROGRESS\t{si+1}/{n_sents}\tpos_acc={t1_pos_ok}/{t1_pos_n}")

    t1_s = time.time() - t0
    gate_rate = t1_gate_ok / t1_gate_n if t1_gate_n else 0
    log(f"T1_SECONDS\t{t1_s:.2f}")
    log(f"T1_POS\t{t1_pos_ok}/{t1_pos_n}\t{100*t1_pos_ok/max(t1_pos_n,1):.4f}%")
    log(f"T1_SENT\t{t1_sent_correct}/{n_sents}")
    log(f"VALIDITY_GATE\t{t1_gate_ok}/{t1_gate_n}\t{100*gate_rate:.4f}%")
    if gate_rate < 0.96:
        log("ABORT\tvalidity gate failed (<96% on shipping-correct positions)")
        log_f.close()
        return 2
    log("VALIDITY_GATE\tPASS")

    # ---------- T2 ----------
    t2_rows_extra = {}  # (si,pos) -> t2 fields
    t2_pos_ok = t2_pos_n = 0
    t2_sent_correct = 0
    t2_s = 0.0
    t2_mode = "full"
    t2_sents = n_sents
    if args.skip_t2:
        t2_mode = "skipped"
        log("T2_SKIPPED")
    else:
        # time estimate on first 3 sentences
        t_est0 = time.time()
        est_ops = 0
        for si in range(min(3, n_sents)):
            readings, gold = cases[si]
            syls = [s for s in readings.split("-") if s]
            ship = ships[si]["pred"]
            schars = list(ship)
            n = min(len(syls), len(schars), len(gold))
            for i in range(n):
                cands = [c for c in r2c.get(syls[i], []) if lm.char_token_id(c) is not None]
                if not cands:
                    continue
                _ = lm.score_candidates_at_pos(ship[:n] if len(ship) >= n else ship, i, cands[: min(5, len(cands))])
                est_ops += min(5, len(cands))
        est_dt = time.time() - t_est0
        # rough full estimate
        # count total candidate ops
        total_ops = 0
        for si in range(n_sents):
            readings, gold = cases[si]
            syls = [s for s in readings.split("-") if s]
            ship = ships[si]["pred"]
            n = min(len(syls), len(list(ship)), len(gold))
            for i in range(n):
                cands = [c for c in r2c.get(syls[i], []) if lm.char_token_id(c) is not None]
                total_ops += max(len(cands), 1)
        sec_per_op = est_dt / max(est_ops, 1)
        est_full_h = total_ops * sec_per_op / 3600
        log(f"T2_ESTIMATE\tops={total_ops}\tsec_per_op={sec_per_op:.4f}\test_hours={est_full_h:.2f}")
        if est_full_h > 4.0 and args.t2_sample_sents <= 0:
            # auto sample 150 sentences
            t2_sents = min(150, n_sents)
            t2_mode = "sample150"
            log(f"T2_DOWNSAMPLE\t{t2_sents} sentences (est >4h)")
        elif args.t2_sample_sents > 0:
            t2_sents = min(args.t2_sample_sents, n_sents)
            t2_mode = f"sample{t2_sents}"
        else:
            t2_sents = n_sents
            t2_mode = "full"

        t0 = time.time()
        # For sentence-level T2: apply independent per-position argmax on shipping base
        # (character-level parallel decisions; product string may not be coherent)
        # Also compute "sequential" optional - baton says per position substitute others with shipping
        t2_pred_by_sent: dict[int, list[str]] = {}
        for si in range(t2_sents):
            readings, gold = cases[si]
            syls = [s for s in readings.split("-") if s]
            gchars = list(gold)
            ship = ships[si]["pred"]
            schars = list(ship)
            n = min(len(syls), len(gchars), len(schars))
            base = "".join(schars[:n])
            preds = list(schars[:n])
            for i in range(n):
                cands = [c for c in r2c.get(syls[i], []) if lm.char_token_id(c) is not None]
                if gchars[i] not in cands and lm.char_token_id(gchars[i]) is not None:
                    cands.append(gchars[i])
                if not cands:
                    cands = [schars[i]]
                scores = lm.score_candidates_at_pos(base, i, cands)
                if not scores:
                    best = schars[i]
                    best_s = float("nan")
                else:
                    best = max(scores.items(), key=lambda kv: kv[1])[0]
                    best_s = scores[best]
                preds[i] = best
                ok = best == gchars[i]
                t2_pos_n += 1
                if ok:
                    t2_pos_ok += 1
                t2_rows_extra[(si, i)] = {
                    "t2_pred": best,
                    "t2_ok": int(ok),
                    "t2_score": best_s,
                    "t2_delta_vs_ship": (
                        scores.get(best, 0) - scores.get(schars[i], 0)
                        if scores and schars[i] in scores
                        else float("nan")
                    ),
                }
            t2_text = "".join(preds)
            if len(gchars) > n:
                t2_text = t2_text + "".join(gchars[n:])
            if t2_text == gold:
                t2_sent_correct += 1
            t2_pred_by_sent[si] = preds
            if (si + 1) % 10 == 0:
                log(
                    f"T2_PROGRESS\t{si+1}/{t2_sents}\tpos_acc={t2_pos_ok}/{t2_pos_n}\t"
                    f"sent={t2_sent_correct}"
                )
        t2_s = time.time() - t0
        log(f"T2_SECONDS\t{t2_s:.2f}\tmode={t2_mode}")
        log(f"T2_POS\t{t2_pos_ok}/{t2_pos_n}\t{100*t2_pos_ok/max(t2_pos_n,1):.4f}%")
        log(f"T2_SENT\t{t2_sent_correct}/{t2_sents}")

    # ---------- T3 ----------
    t0 = time.time()
    t3_pos_ok = t3_pos_n = t3_invalid = 0
    t3_sent_correct = 0
    t3_extra = {}
    t3_sents = n_sents
    for si in range(t3_sents):
        readings, gold = cases[si]
        syls = [s for s in readings.split("-") if s]
        gchars = list(gold)
        ship = ships[si]["pred"]
        schars = list(ship)
        n = min(len(syls), len(gchars), len(schars))
        preds = list(schars[:n])
        for i in range(n):
            cands = [c for c in r2c.get(syls[i], []) if lm.char_token_id(c) is not None]
            if gchars[i] not in cands and lm.char_token_id(gchars[i]) is not None:
                cands.append(gchars[i])
            if not cands:
                cands = [schars[i]]
            # blank position i
            blanked = "".join(schars[j] if j != i else "▢" for j in range(n))
            pick, valid = t3_pick(lm, blanked, cands)
            if not valid:
                t3_invalid += 1
                pick = schars[i]  # fallback keep shipping for string rebuild
            preds[i] = pick
            ok = pick == gchars[i]
            t3_pos_n += 1
            if ok:
                t3_pos_ok += 1
            t3_extra[(si, i)] = {
                "t3_pred": pick,
                "t3_ok": int(ok),
                "t3_valid": int(valid),
            }
        t3_text = "".join(preds)
        if len(gchars) > n:
            t3_text += "".join(gchars[n:])
        if t3_text == gold:
            t3_sent_correct += 1
        if (si + 1) % 25 == 0:
            log(f"T3_PROGRESS\t{si+1}/{t3_sents}\tpos={t3_pos_ok}/{t3_pos_n}\tinv={t3_invalid}")
    t3_s = time.time() - t0
    log(f"T3_SECONDS\t{t3_s:.2f}")
    log(f"T3_POS\t{t3_pos_ok}/{t3_pos_n}\t{100*t3_pos_ok/max(t3_pos_n,1):.4f}%")
    log(f"T3_SENT\t{t3_sent_correct}/{t3_sents}")
    log(f"T3_INVALID\t{t3_invalid}/{t3_pos_n}")

    # ---------- A/B class sentence rescues ----------
    # Rebuild sentence predictions for T1 fully; T2/T3 for their ranges
    def sent_stats(layer: str, sent_correct_map: dict[int, bool]):
        # A/B: among sentences wrong under shipping, how many fixed
        rescue_a = rescue_b = still_a = still_b = 0
        for si in range(n_sents):
            if si not in sent_correct_map:
                continue
            ship_ok = ships[si]["correct"] == "1"
            gip = ships[si].get("gold_in_pool", "0") == "1"
            now_ok = sent_correct_map[si]
            if ship_ok:
                continue
            if now_ok:
                if gip:
                    rescue_a += 1
                else:
                    rescue_b += 1
            else:
                if gip:
                    still_a += 1
                else:
                    still_b += 1
        log(
            f"AB_{layer}\trescue_a={rescue_a}\trescue_b={rescue_b}\t"
            f"still_a={still_a}\tstill_b={still_b}"
        )

    # T1 sentence map
    t1_map = {}
    for si in range(n_sents):
        readings, gold = cases[si]
        # recompute from t1_rows
        preds = [r["t1_pred"] for r in t1_rows if r["sent_idx"] == si]
        gchars = list(gold)
        n = len(preds)
        text = "".join(preds) + ("".join(gchars[n:]) if len(gchars) > n else "")
        t1_map[si] = text == gold
    sent_stats("T1", t1_map)

    t2_map = {}
    if t2_mode != "skipped":
        for si in range(t2_sents):
            readings, gold = cases[si]
            gchars = list(gold)
            preds = []
            for i in range(min(len(gchars), len(list(ships[si]["pred"])))):
                ex = t2_rows_extra.get((si, i))
                preds.append(ex["t2_pred"] if ex else list(ships[si]["pred"])[i])
            text = "".join(preds)
            if len(gchars) > len(preds):
                text += "".join(gchars[len(preds) :])
            t2_map[si] = text == gold
        sent_stats("T2", t2_map)

    t3_map = {}
    for si in range(t3_sents):
        readings, gold = cases[si]
        gchars = list(gold)
        preds = []
        schars = list(ships[si]["pred"])
        n = min(len(gchars), len(schars))
        for i in range(n):
            ex = t3_extra.get((si, i))
            preds.append(ex["t3_pred"] if ex else schars[i])
        text = "".join(preds) + ("".join(gchars[n:]) if len(gchars) > n else "")
        t3_map[si] = text == gold
    sent_stats("T3", t3_map)

    # scale T2 sentence score to 537 if sample
    def scale_sent(correct, denom, total=537):
        if denom <= 0:
            return float("nan")
        return correct / denom * total

    t1_sent_score = t1_sent_correct  # already on n_sents; if n_sents==537 exact
    if n_sents < 537:
        t1_sent_scaled = scale_sent(t1_sent_correct, n_sents)
    else:
        t1_sent_scaled = float(t1_sent_correct)

    if t2_mode != "skipped":
        t2_sent_scaled = (
            float(t2_sent_correct)
            if t2_sents == 537
            else scale_sent(t2_sent_correct, t2_sents)
        )
    else:
        t2_sent_scaled = float("nan")

    t3_sent_scaled = (
        float(t3_sent_correct) if t3_sents == 537 else scale_sent(t3_sent_correct, t3_sents)
    )

    log(f"SCORE_T1_SENT\t{t1_sent_correct}/{n_sents}\tscaled_537={t1_sent_scaled:.1f}")
    log(f"SCORE_T2_SENT\t{t2_sent_correct if t2_mode!='skipped' else 'NA'}/{t2_sents if t2_mode!='skipped' else 0}\tscaled_537={t2_sent_scaled}")
    log(f"SCORE_T3_SENT\t{t3_sent_correct}/{t3_sents}\tscaled_537={t3_sent_scaled:.1f}")
    log(f"SCORE_T2_MINUS_T1\t{(t2_sent_scaled - t1_sent_scaled) if t2_mode!='skipped' else 'NA'}")
    log(f"SCORE_T3_MINUS_T2\t{(t3_sent_scaled - t2_sent_scaled) if t2_mode!='skipped' else 'NA'}")

    # GO/NO-GO
    candidates = [("T1", t1_sent_scaled)]
    if t2_mode != "skipped":
        candidates.append(("T2", t2_sent_scaled))
    candidates.append(("T3", t3_sent_scaled))
    best_layer, best_score = max(candidates, key=lambda x: x[1])
    if best_score >= 450:
        decision = "GO"
    elif best_score >= 430:
        decision = "边际"
    else:
        decision = "NO-GO"
    log(f"BEST_LAYER\t{best_layer}\tscore={best_score:.1f}")
    log(f"DECISION\t{decision}")
    log(
        "POLLUTION\tProxy numbers are ceiling estimates only; "
        "MUST NOT enter product score ladder (296/333/387/...)."
    )

    # write positions tsv
    pos_path = analysis / "tw538-proxy-judge-positions.tsv"
    with pos_path.open("w", encoding="utf-8") as fo:
        fo.write(
            "sent_idx\tpos\treading\tgold\tship\tship_ok\tgold_in_pool\t"
            "t1_pred\tt1_ok\tt1_H\tt1_gold_logp\tM\t"
            "t2_pred\tt2_ok\tt2_score\tt3_pred\tt3_ok\tt3_valid\n"
        )
        for r in t1_rows:
            key = (r["sent_idx"], r["pos"])
            t2 = t2_rows_extra.get(key, {})
            t3 = t3_extra.get(key, {})
            fo.write(
                f"{r['sent_idx']}\t{r['pos']}\t{r['reading']}\t{r['gold']}\t{r['ship']}\t"
                f"{r['ship_ok']}\t{r['gold_in_pool']}\t"
                f"{r['t1_pred']}\t{r['t1_ok']}\t{r['t1_H']}\t{r['t1_gold_logp']}\t{r['M']}\t"
                f"{t2.get('t2_pred','')}\t{t2.get('t2_ok','')}\t{t2.get('t2_score','')}\t"
                f"{t3.get('t3_pred','')}\t{t3.get('t3_ok','')}\t{t3.get('t3_valid','')}\n"
            )
    log(f"WROTE\t{pos_path}")

    # summary json
    summary = {
        "model": str(model_path),
        "weights_sha256": wsha,
        "validity_gate": gate_rate,
        "t1_sent": t1_sent_correct,
        "t1_sent_scaled": t1_sent_scaled,
        "t1_pos_acc": t1_pos_ok / max(t1_pos_n, 1),
        "t2_mode": t2_mode,
        "t2_sent": t2_sent_correct if t2_mode != "skipped" else None,
        "t2_sent_scaled": t2_sent_scaled,
        "t2_pos_acc": t2_pos_ok / max(t2_pos_n, 1) if t2_pos_n else None,
        "t3_sent": t3_sent_correct,
        "t3_sent_scaled": t3_sent_scaled,
        "t3_pos_acc": t3_pos_ok / max(t3_pos_n, 1),
        "t3_invalid_rate": t3_invalid / max(t3_pos_n, 1),
        "best_layer": best_layer,
        "best_score": best_score,
        "decision": decision,
        "n_sents": n_sents,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"SUMMARY\t{json.dumps(summary, ensure_ascii=False)}")
    log_f.close()
    print("LOG", log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
