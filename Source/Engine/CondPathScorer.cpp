// Copyright (c) 2026 and onwards The McBopomofo Authors.

#include "CondPathScorer.h"

namespace McBopomofo {

size_t CondPathScorer::utf8CharCount(const std::string& s) {
  size_t n = 0;
  for (unsigned char c : s) {
    if ((c & 0xC0) != 0x80) ++n;
  }
  return n;
}

std::string CondPathScorer::joinReading(const std::vector<std::string>& syls,
                                        size_t begin, size_t end) {
  std::string out;
  for (size_t i = begin; i < end && i < syls.size(); ++i) {
    if (!out.empty()) out.push_back('-');
    out += syls[i];
  }
  return out;
}

double CondPathScorer::scoreSentence(const std::vector<std::string>& words) {
  if (!cond_.isLoaded() || words.empty()) return 0.0;
  if (syllables_.empty()) return 0.0;

  std::string left;
  size_t pos = 0;
  double sum = 0.0;
  int scored = 0;

  for (const auto& w : words) {
    size_t n = utf8CharCount(w);
    if (n == 0) continue;
    if (pos + n > syllables_.size()) {
      // length mismatch — cannot form hard reading constraint; abort score
      return -1e9;
    }
    std::string rd = joinReading(syllables_, pos, pos + n);
    sum += cond_.scoreCandidate(left, rd, w);
    left += w;
    pos += n;
    ++scored;
  }
  // If path doesn't consume all syllables, still return partial (rare)
  (void)scored;
  return sum;
}

}  // namespace McBopomofo
