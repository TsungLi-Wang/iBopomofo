#!/usr/bin/env python3
"""Convert eval TSV rows into rerank_eval cases.

Input format:

    expected_text<TAB>target_char<TAB>note

Output format:

    bpmf-readings-separated-by-dash<TAB>expected_text

The converter uses McBopomofo's BPMFBase.txt and BPMFMappings.txt. It is meant
for eval cases, not for committing new dictionary entries. Rows containing ASCII
letters or digits are skipped because the C++ harness feeds only BPMF syllables
into the engine.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


PUNCTUATION = set("，。！？、；：,.!?;:「」『』（）()《》【】[]")
ASCII_RE = re.compile(r"[A-Za-z0-9]")


@dataclass
class TrieNode:
    children: dict[str, "TrieNode"] = field(default_factory=dict)
    readings: list[str] | None = None


def add_to_trie(root: TrieNode, phrase: str, readings: list[str]) -> None:
    node = root
    for char in phrase:
        node = node.children.setdefault(char, TrieNode())
    if node.readings is None:
        node.readings = readings


def iter_base_rows(path: Path) -> Iterable[tuple[str, list[str]]]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        character = parts[0]
        reading = parts[1]
        if len(character) != 1:
            continue
        yield character, [reading]


def iter_phrase_rows(path: Path) -> Iterable[tuple[str, list[str]]]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        phrase = parts[0]
        readings = parts[1:]
        if len(phrase) != len(readings):
            continue
        yield phrase, readings


def load_trie(base_path: Path, mappings_path: Path) -> TrieNode:
    root = TrieNode()
    for phrase, readings in iter_base_rows(base_path):
        add_to_trie(root, phrase, readings)
    for phrase, readings in iter_phrase_rows(mappings_path):
        add_to_trie(root, phrase, readings)
    return root


def longest_match(root: TrieNode, text: str, start: int) -> tuple[list[str], int] | None:
    node = root
    best: tuple[list[str], int] | None = None
    index = start
    while index < len(text) and text[index] in node.children:
        node = node.children[text[index]]
        index += 1
        if node.readings is not None:
            best = (node.readings, index)
    return best


def text_to_readings(root: TrieNode, text: str) -> str:
    readings: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace() or char in PUNCTUATION:
            index += 1
            continue
        if ASCII_RE.match(char):
            raise ValueError("contains ASCII letters or digits")
        match = longest_match(root, text, index)
        if match is None:
            raise ValueError(f"no BPMF reading for {char!r}")
        matched_readings, index = match
        readings.extend(matched_readings)
    return "-".join(readings)


def convert(args: argparse.Namespace) -> int:
    trie = load_trie(args.bpmf_base, args.bpmf_mappings)
    output_lines: list[str] = []
    skipped_lines: list[str] = []

    for line_number, line in enumerate(args.input.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            skipped_lines.append(f"{line_number}\tbad-tsv\t{line}")
            continue
        expected = fields[0]
        try:
            readings = text_to_readings(trie, expected)
        except ValueError as error:
            skipped_lines.append(f"{line_number}\t{error}\t{line}")
            continue
        output_lines.append(f"{readings}\t{expected}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(output_lines) + ("\n" if output_lines else ""), encoding="utf-8")
    if args.skipped:
        args.skipped.parent.mkdir(parents=True, exist_ok=True)
        args.skipped.write_text(
            "\n".join(skipped_lines) + ("\n" if skipped_lines else ""), encoding="utf-8")

    print(f"wrote {args.output} ({len(output_lines)} cases)")
    if skipped_lines:
        destination = str(args.skipped) if args.skipped else "not written"
        print(f"skipped {len(skipped_lines)} rows ({destination})", file=sys.stderr)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Input eval TSV.")
    parser.add_argument("--output", required=True, type=Path, help="Output rerank cases TSV.")
    parser.add_argument("--skipped", type=Path, help="Optional skipped-row report TSV.")
    parser.add_argument(
        "--bpmf-base",
        type=Path,
        default=Path("Source/Data/BPMFBase.txt"),
        help="Path to BPMFBase.txt.",
    )
    parser.add_argument(
        "--bpmf-mappings",
        type=Path,
        default=Path("Source/Data/BPMFMappings.txt"),
        help="Path to BPMFMappings.txt.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    return convert(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
