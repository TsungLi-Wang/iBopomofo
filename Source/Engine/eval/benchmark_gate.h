// Gate: only tw538 (537 sentences) may be used as the north-star benchmark.
// Retired corpora (any other size / known retired filenames) abort hard.
// No bypass flag — Johnny 2026-07-24.

#pragma once

#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>

namespace McBopomofoEval {

inline size_t CountBenchmarkSentences(const std::string& path) {
  std::ifstream in(path);
  if (!in) return 0;
  size_t n = 0;
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty() || line[0] == '#') continue;
    if (line.find('\t') == std::string::npos) continue;
    ++n;
  }
  return n;
}

// Returns false and prints abort message if path is not allowed.
inline bool RequireTw538Benchmark(const std::string& path) {
  // Filename denylist (retired sets)
  const std::string base = path.substr(path.find_last_of("/\\") == std::string::npos
                                           ? 0
                                           : path.find_last_of("/\\") + 1);
  if (base == "tw-sentences.tsv" || base.find("tw-sentences") != std::string::npos) {
    std::cerr << "FATAL: retired benchmark corpus refused: " << path
              << "\nOnly tw538-northstar.tsv (537 sentences) is allowed.\n";
    return false;
  }

  const size_t n = CountBenchmarkSentences(path);
  if (n != 537) {
    std::cerr << "FATAL: benchmark gate: expected 537 sentences (tw538), got " << n
              << " from " << path
              << "\nOnly tw538-northstar.tsv is the north-star set.\n";
    return false;
  }
  return true;
}

inline void AbortUnlessTw538(const std::string& path) {
  if (!RequireTw538Benchmark(path)) {
    std::exit(3);
  }
}

}  // namespace McBopomofoEval
