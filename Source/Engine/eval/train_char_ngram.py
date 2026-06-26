#!/usr/bin/env python3
"""Train a compact character n-gram model for candidate reranking.

The model is intentionally simple and deterministic. It consumes plain text
files or a compressed zhwiki XML dump, counts character uni/bi/trigrams, and
writes a TSV model shared by the Swift app and the C++ eval harness.
"""

from __future__ import annotations

import argparse
import bz2
import html
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator


MODEL_HEADER = "# laowang-char-ngram-v1"
DEFAULT_MIN_COUNT = 2
DEFAULT_MAX_TEXT_CHARS = 10_000_000

HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
XML_TAG_RE = re.compile(r"<[^>]+>")
WIKI_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
WIKI_LINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]")
URL_RE = re.compile(r"https?://\S+")


def iter_paths(inputs: list[Path]) -> Iterator[Path]:
    for item in inputs:
        if item.is_dir():
            for path in sorted(item.rglob("*")):
                if path.is_file():
                    yield path
        elif item.is_file():
            yield item


def open_text(path: Path) -> Iterable[str]:
    if path.suffix == ".bz2":
        try:
            with bz2.open(path, "rt", encoding="utf-8", errors="ignore") as handle:
                yield from handle
        except EOFError:
            print(f"warning: {path} is truncated; using decoded prefix", file=sys.stderr)
        return
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        yield from handle


def clean_line(line: str) -> str:
    line = html.unescape(line)
    line = XML_TAG_RE.sub("", line)
    line = WIKI_TEMPLATE_RE.sub("", line)
    line = WIKI_LINK_RE.sub(r"\1", line)
    line = URL_RE.sub("", line)
    return line


def han_runs(line: str) -> Iterator[str]:
    cleaned = clean_line(line)
    for match in HAN_RE.finditer(cleaned):
        text = match.group(0)
        if len(text) >= 2:
            yield text


def count_corpus(paths: Iterable[Path], max_text_chars: int) -> tuple[Counter, Counter, Counter, Counter]:
    unigrams: Counter[str] = Counter()
    bigrams: Counter[str] = Counter()
    trigrams: Counter[str] = Counter()
    phrases: Counter[str] = Counter()
    consumed = 0

    for path in paths:
        for line in open_text(path):
            for run in han_runs(line):
                chars = list(run)
                consumed += len(chars)
                unigrams.update(chars)
                bigrams.update("".join(chars[index : index + 2]) for index in range(len(chars) - 1))
                trigrams.update("".join(chars[index : index + 3]) for index in range(len(chars) - 2))
                if 2 <= len(run) <= 8:
                    phrases[run] += 1
                if consumed >= max_text_chars:
                    return unigrams, bigrams, trigrams, phrases
    return unigrams, bigrams, trigrams, phrases


def write_count(handle, tag: str, key: str, count: int) -> None:
    fields = [tag, *list(key), str(count)]
    handle.write("\t".join(fields) + "\n")


def write_model(
    output: Path,
    unigrams: Counter,
    bigrams: Counter,
    trigrams: Counter,
    phrases: Counter,
    min_count: int,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        handle.write(MODEL_HEADER + "\n")
        for key, count in sorted(unigrams.items()):
            if count >= min_count:
                write_count(handle, "U", key, count)
        for key, count in sorted(bigrams.items()):
            if count >= min_count:
                write_count(handle, "B", key, count)
        for key, count in sorted(trigrams.items()):
            if count >= min_count:
                write_count(handle, "T", key, count)
        for key, count in sorted(phrases.items()):
            if count >= min_count:
                handle.write(f"P\t{key}\t{count}\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        type=Path,
        help="Plain text file, .bz2 zhwiki dump, or directory. Can be repeated.",
    )
    parser.add_argument("--output", required=True, type=Path, help="Output TSV model path.")
    parser.add_argument("--min-count", type=int, default=DEFAULT_MIN_COUNT)
    parser.add_argument(
        "--max-text-chars",
        type=int,
        default=DEFAULT_MAX_TEXT_CHARS,
        help="Cap training text size for quick repeatable experiments.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    paths = list(iter_paths(args.input))
    if not paths:
        print("No input files found.", file=sys.stderr)
        return 2
    unigrams, bigrams, trigrams, phrases = count_corpus(paths, args.max_text_chars)
    write_model(args.output, unigrams, bigrams, trigrams, phrases, args.min_count)
    print(
        "wrote "
        f"{args.output} "
        f"(U={len(unigrams)} B={len(bigrams)} T={len(trigrams)} P={len(phrases)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
