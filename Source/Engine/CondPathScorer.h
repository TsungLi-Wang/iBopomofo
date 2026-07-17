// Copyright (c) 2026 and onwards The McBopomofo Authors.
//
// PathScorer adapter over CondConverterScorer:
//   sum_i log10 P(word_i | left_context, reading_span_i)
// Reading syllables are set per-case via setSyllables() (hard constraint input).

#ifndef SRC_ENGINE_CONDPATHSCORER_H_
#define SRC_ENGINE_CONDPATHSCORER_H_

#include <string>
#include <vector>

#include "CondConverterScorer.h"
#include "gramambular2/reading_grid.h"

namespace McBopomofo {

class CondPathScorer
    : public Formosa::Gramambular2::ReadingGrid::PathScorer {
 public:
  bool load(const std::string& path) { return cond_.load(path); }
  [[nodiscard]] bool isLoaded() const { return cond_.isLoaded(); }
  [[nodiscard]] size_t parameterCount() const { return cond_.parameterCount(); }
  CondConverterScorer& underlying() { return cond_; }

  // Full-case syllable sequence (Bopomofo tokens, one per han char typically).
  void setSyllables(std::vector<std::string> syls) {
    syllables_ = std::move(syls);
  }
  void clearSyllables() { syllables_.clear(); }

  double scoreSentence(const std::vector<std::string>& words) override;

 private:
  CondConverterScorer cond_;
  std::vector<std::string> syllables_;

  static size_t utf8CharCount(const std::string& s);
  static std::string joinReading(const std::vector<std::string>& syls,
                                 size_t begin, size_t end);
};

}  // namespace McBopomofo

#endif  // SRC_ENGINE_CONDPATHSCORER_H_
