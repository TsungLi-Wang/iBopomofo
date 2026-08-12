// Copyright (c) 2026 and onwards The McBopomofo Authors.
//
// Char-level trigram PathScorer for Mozc-style n-best path rerank.
// Trained on zh-TW wiki sample + Taiwan typing corpus; MIT/permissive data.
// Log10 domain with additive smoothing; higher = better.

#ifndef SRC_ENGINE_CHARNGRAMPATHSCORER_H_
#define SRC_ENGINE_CHARNGRAMPATHSCORER_H_

#include <string>
#include <unordered_map>
#include <vector>

#include "gramambular2/reading_grid.h"

namespace iBopomofo {

class CharNGramPathScorer
    : public Formosa::Gramambular2::ReadingGrid::PathScorer {
 public:
  bool load(const std::string& path);
  [[nodiscard]] bool isLoaded() const { return loaded_; }
  [[nodiscard]] size_t size() const { return uni_.size() + bi_.size() + tri_.size(); }

  double scoreSentence(
      const std::vector<std::string>& words) override;

 private:
  static constexpr double kAlpha = 0.1;
  bool loaded_ = false;
  double totalUni_ = 0;
  size_t vocab_ = 1;
  std::unordered_map<std::string, double> uni_;
  std::unordered_map<std::string, double> bi_;   // a\x1fb -> count
  std::unordered_map<std::string, double> tri_;  // a\x1fb\x1fc
  std::unordered_map<std::string, double> biLeft_; // a -> sum
  std::unordered_map<std::string, double> triLeft_; // a\x1fb -> sum

  static std::vector<std::string> flattenChars(
      const std::vector<std::string>& words);
  double logP(const std::string& a, const std::string& b,
              const std::string& c) const;
};

}  // namespace iBopomofo

#endif  // SRC_ENGINE_CHARNGRAMPATHSCORER_H_
