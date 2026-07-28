#!/usr/bin/env python3
"""Homophone discrimination GO/NO-GO measurement (research only).

Orchestrates:
  1) Build reading2chars.tsv from conversion_pairs_v2.tsv
  2) Compile+run C++ harness (homophone_measure.cpp) for shipping 387,
     coverage, char accuracy, residual entropy, single-flip oracle.

Does NOT modify app/engine product code or shipping knobs.

Example:
  python3 Source/Engine/eval/tools/measure_homophone_entropy.py \\
    --pairs ~/laowang-data/conversion_pairs_v2.tsv \\
    --data-dir ~/laowang-data \\
    --repo ~/iBopomofo
"""
from __future__ import annotations

import argparse
import hashlib
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(8 * 1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def build_reading2chars(pairs: Path, out: Path, stats_out: Path) -> dict:
    t0 = time.time()
    size = pairs.stat().st_size
    sha = sha256_file(pairs)
    print(f"INPUT path={pairs}")
    print(f"INPUT size_bytes={size}")
    print(f"INPUT sha256={sha}", flush=True)

    r2c: dict[str, Counter] = defaultdict(Counter)
    n_lines = n_aligned = n_skip_unequal = n_skip_bad = 0
    with pairs.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            n_lines += 1
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                n_skip_bad += 1
                continue
            _left, readings, word = parts[0], parts[1], parts[2]
            if not readings or not word:
                n_skip_bad += 1
                continue
            syls = [s for s in readings.split("-") if s]
            chars = list(word)
            if len(syls) != len(chars):
                n_skip_unequal += 1
                continue
            for s, ch in zip(syls, chars):
                if not ch.strip():
                    continue
                r2c[s][ch] += 1
                n_aligned += 1
            if n_lines % 5_000_000 == 0:
                print(
                    f"  progress lines={n_lines} readings={len(r2c)} aligned={n_aligned}",
                    flush=True,
                )

    with out.open("w", encoding="utf-8") as fo:
        for reading in sorted(r2c.keys()):
            items = sorted(r2c[reading].items(), key=lambda kv: (-kv[1], kv[0]))
            body = ",".join(f"{ch}:{cnt}" for ch, cnt in items)
            fo.write(f"{reading}\t{body}\n")

    set_sizes = [len(c) for c in r2c.values()]
    set_sizes_sorted = sorted(set_sizes)

    def pct(p: float) -> float:
        if not set_sizes_sorted:
            return 0.0
        k = (len(set_sizes_sorted) - 1) * p / 100.0
        f = int(k)
        c = min(f + 1, len(set_sizes_sorted) - 1)
        if f == c:
            return float(set_sizes_sorted[f])
        return set_sizes_sorted[f] + (set_sizes_sorted[c] - set_sizes_sorted[f]) * (
            k - f
        )

    num = den = 0.0
    for ctr in r2c.values():
        tot = sum(ctr.values())
        num += tot * len(ctr)
        den += tot
    wmean = num / den if den else 0.0
    mean = statistics.mean(set_sizes) if set_sizes else 0.0
    med = statistics.median(set_sizes) if set_sizes else 0.0
    oh = sha256_file(out)
    stats = {
        "unique_readings": len(r2c),
        "set_size_min": min(set_sizes) if set_sizes else 0,
        "set_size_max": max(set_sizes) if set_sizes else 0,
        "set_size_mean": mean,
        "set_size_median": med,
        "set_size_p90": pct(90),
        "set_size_freq_weighted_mean": wmean,
        "aligned_pairs": n_aligned,
        "skip_unequal": n_skip_unequal,
        "input_sha256": sha,
        "output_sha256": oh,
        "output_path": str(out),
        "input_path": str(pairs),
        "input_size_bytes": size,
    }
    lines = [
        f"INPUT path={pairs}",
        f"INPUT size_bytes={size}",
        f"INPUT sha256={sha}",
        f"lines={n_lines}",
        f"aligned_pairs={n_aligned}",
        f"skip_unequal={n_skip_unequal}",
        f"skip_bad={n_skip_bad}",
        f"unique_readings={len(r2c)}",
        f"set_size_min={stats['set_size_min']}",
        f"set_size_max={stats['set_size_max']}",
        f"set_size_mean={mean}",
        f"set_size_median={med}",
        f"set_size_p90={pct(90)}",
        f"set_size_freq_weighted_mean={wmean}",
        f"total_aligned_tokens={int(den)}",
        f"OUTPUT path={out}",
        f"OUTPUT size_bytes={out.stat().st_size}",
        f"OUTPUT sha256={oh}",
        f"elapsed_s={time.time()-t0:.1f}",
    ]
    stats_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for ln in lines:
        print(ln)
    return stats


def compile_and_run(repo: Path, r2c: Path, outdir: Path) -> int:
    tools = repo / "Source/Engine/eval/tools"
    engine = repo / "Source/Engine"
    bench = engine / "eval/benchmarks"
    data = repo / "Source/Data"
    bin_path = Path("/tmp/homophone_measure")
    src = tools / "homophone_measure.cpp"
    cmd_cc = [
        "clang++",
        "-std=c++17",
        "-O2",
        f"-I{engine}",
        f"-I{engine}/gramambular2",
        str(src),
        str(engine / "gramambular2/reading_grid.cpp"),
        str(engine / "CorpusBigramContextModel.cpp"),
        str(engine / "ParselessLM.cpp"),
        str(engine / "ParselessPhraseDB.cpp"),
        str(engine / "MemoryMappedFile.cpp"),
        str(engine / "NeuralLMPathScorer.cpp"),
        "-framework",
        "Accelerate",
        "-o",
        str(bin_path),
    ]
    print("COMPILE:", " ".join(cmd_cc), flush=True)
    subprocess.check_call(cmd_cc)
    outdir.mkdir(parents=True, exist_ok=True)
    stdout_path = outdir / "stdout.txt"
    cmd = [
        str(bin_path),
        str(bench / "tw538-northstar.tsv"),
        str(data / "data.txt"),
        str(data / "word-bigrams.tsv"),
        "0.75",
        str(data / "path-char-lstm.bin"),
        "0.75",
        str(r2c),
        str(outdir),
    ]
    print("RUN:", " ".join(cmd), flush=True)
    with stdout_path.open("w", encoding="utf-8") as fo:
        p = subprocess.run(cmd, stdout=fo, stderr=subprocess.STDOUT, text=True)
    print(stdout_path.read_text(encoding="utf-8"))
    print(f"STDOUT sha256={sha256_file(stdout_path)}")
    return p.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pairs",
        type=Path,
        default=Path.home() / "laowang-data/conversion_pairs_v2.tsv",
    )
    ap.add_argument(
        "--data-dir", type=Path, default=Path.home() / "laowang-data"
    )
    ap.add_argument("--repo", type=Path, default=Path.home() / "iBopomofo")
    ap.add_argument(
        "--skip-build-r2c",
        action="store_true",
        help="reuse existing reading2chars.tsv",
    )
    ap.add_argument(
        "--skip-harness",
        action="store_true",
        help="only build reading2chars",
    )
    args = ap.parse_args()
    data_dir: Path = args.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    r2c = data_dir / "reading2chars.tsv"
    stats = data_dir / "reading2chars.stats.txt"
    if not args.skip_build_r2c:
        build_reading2chars(args.pairs, r2c, stats)
    else:
        print(f"reuse {r2c} sha256={sha256_file(r2c)}")
    if args.skip_harness:
        return 0
    outdir = data_dir / "homophone-measure-run"
    return compile_and_run(args.repo, r2c, outdir)


if __name__ == "__main__":
    sys.exit(main())
