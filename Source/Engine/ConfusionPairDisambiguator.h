// Copyright (c) 2026 and onwards The McBopomofo Authors.
//
// Permission is hereby granted, free of charge, to any person
// obtaining a copy of this software and associated documentation
// files (the "Software"), to deal in the Software without
// restriction, including without limitation the rights to use,
// copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the
// Software is furnished to do so, subject to the following
// conditions:
//
// The above copyright notice and this permission notice shall be
// included in all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
// EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
// OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
// NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
// HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
// WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
// FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
// OTHER DEALINGS IN THE SOFTWARE.

#ifndef SRC_ENGINE_CONFUSIONPAIRDISAMBIGUATOR_H_
#define SRC_ENGINE_CONFUSIONPAIRDISAMBIGUATOR_H_

#include <istream>
#include <string>
#include <unordered_map>

#include "gramambular2/reading_grid.h"

namespace McBopomofo {

// Disambiguates curated homophone confusion pairs (e.g. 在/再, both ㄗㄞˋ) on
// a walked path. The underlying language model is unigram-only, so a
// single-reading node always resolves to the highest-frequency character
// (在); this class supplies the missing character-bigram signal via a
// corpus-derived log-odds table over the neighboring characters:
//
//   score(alt) = left + right + prior
//
// where the left/right terms first try two-character bigram evidence
// (LB/RB rows; a single neighbor cannot separate 我在說話 from 我再說一遍 —
// the signal sits one character further out) and back off to the
// single-character rows (L/R). Context characters are taken from the flat
// character sequence of the walked path, crossing node boundaries. This covers
// both a span-1 ㄗㄞˋ node and a multi-syllable dictionary node with a
// "twin" unigram differing only at the pair character (the dictionary
// contains both 我在 and 我再; the unigram walk always favors the frequent
// twin). If the score exceeds the pair's threshold, the twin value is
// selected inside the same node with a soft override
// (kOverrideValueWithScoreFromTopUnigram), so:
//
// - Only unigrams that already exist in the node can be picked; text is never
//   generated and the reading is never changed (engine-level guarantee).
// - The node score stays that of the top unigram, so path competition and
//   segmentation are unaffected and no re-walk is needed.
//
// Nodes overridden by the user or the user override model are never touched.
// Overrides applied by this class are tracked and re-evaluated on every walk,
// so a decision can be retracted when more context arrives. This class never
// feeds the user override model (override-without-observe; see
// docs/engine-node-override.md).
//
// Table rows are tab-separated; see eval/build_confusion_pair_table.py which
// must stay in sync, in particular the context-token normalization.
class ConfusionPairDisambiguator {
 public:
  // Loads a table, replacing any previously loaded pairs and forgetting the
  // overrides applied so far. Returns true if at least one pair is usable.
  bool load(const std::string& path);
  bool load(std::istream& input);

  [[nodiscard]] bool isLoaded() const { return !pairs_.empty(); }

  // Re-evaluates every eligible node of the walked path in place, applying
  // or retracting soft overrides. Returns true if any node changed. Must be
  // called on the thread that owns the grid.
  bool rescoreWalk(
      const Formosa::Gramambular2::ReadingGrid::WalkResult& walkResult);

  // Forgets the overrides applied so far, e.g. when the grid is cleared.
  void reset();

  // Maps a UTF-8 character to a context-token key of the table. Exposed for
  // tests; must stay in sync with build_confusion_pair_table.py.
  static std::string NormalizeContextToken(const std::string& utf8Char);

 private:
  struct Pair {
    std::string reading;
    std::string defaultValue;
    std::string altValue;
    double prior = 0.0;
    double threshold = 0.0;
    std::unordered_map<std::string, double> left;
    std::unordered_map<std::string, double> right;
    std::unordered_map<std::string, double> leftBigram;
    std::unordered_map<std::string, double> rightBigram;
  };

  bool isAppliedByUs(const Formosa::Gramambular2::ReadingGrid::NodePtr& node);

  // Keyed by reading (e.g. ㄗㄞˋ).
  std::unordered_map<std::string, Pair> pairs_;

  // Nodes we have soft-overridden. Keyed by address for lookup; the weak_ptr
  // guards against address reuse after the grid drops a node.
  std::unordered_map<const Formosa::Gramambular2::ReadingGrid::Node*,
                     std::weak_ptr<Formosa::Gramambular2::ReadingGrid::Node>>
      applied_;
};

}  // namespace McBopomofo

#endif  // SRC_ENGINE_CONFUSIONPAIRDISAMBIGUATOR_H_
