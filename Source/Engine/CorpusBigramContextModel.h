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

#ifndef SRC_ENGINE_CORPUSBIGRAMCONTEXTMODEL_H_
#define SRC_ENGINE_CORPUSBIGRAMCONTEXTMODEL_H_

#include <istream>
#include <string>
#include <unordered_map>

#include "gramambular2/reading_grid.h"

namespace iBopomofo {

// A word-level bigram ContextModel for ReadingGrid::walk(). When set on a grid,
// walk() runs its expanded per-unigram DP and adds this model's transition
// score to each candidate's unigram score, so word context participates in the
// actual path/choice competition (not a post-hoc fix). Only unigrams that
// already exist in a node are ever scored, so no text is generated and the
// reading is never changed.
//
// The transition score is lambda * PMI(prev, word), where the pointwise mutual
// information PMI = log P(word|prev) - log P(word) is the contextual adjustment
// on top of the unigram score. PMI is precomputed from a real corpus by
// eval/build_word_bigram_table.py (which must stay in sync); it is independent
// of lambda so lambda can be grid-searched against the benchmark without
// regenerating the table. Pairs absent from the table contribute 0 (the
// unigram score decides), so a bigram only ever tilts a decision when the
// corpus actually saw that adjacency.
//
// Table rows are tab-separated `prev<TAB>word<TAB>pmi`; lines starting with
// '#' are comments. A malformed line is skipped rather than fatal, since the
// engine may load this during input-method startup.
class CorpusBigramContextModel
    : public Formosa::Gramambular2::ReadingGrid::ContextModel {
 public:
  // Loads a table, replacing any previously loaded entries. Returns true if at
  // least one bigram is usable.
  bool load(const std::string& path);
  bool load(std::istream& input);

  void setLambda(double lambda) { lambda_ = lambda; }
  [[nodiscard]] double lambda() const { return lambda_; }

  [[nodiscard]] bool isLoaded() const { return count_ > 0; }
  [[nodiscard]] size_t size() const { return count_; }

  // ReadingGrid::ContextModel. Returns lambda * PMI(prevWord, word), or 0 when
  // the pair is absent. Writes a stable per-word value into state so the DP
  // recombines hypotheses that end in the same word (bigram history).
  double score(const std::string& prevWord, const std::string& word,
               double& state) override;
  double beginState() override { return 0.0; }

 private:
  // prev -> (word -> PMI).
  std::unordered_map<std::string, std::unordered_map<std::string, double>>
      table_;
  double lambda_ = 1.0;
  size_t count_ = 0;
};

}  // namespace iBopomofo

#endif  // SRC_ENGINE_CORPUSBIGRAMCONTEXTMODEL_H_
