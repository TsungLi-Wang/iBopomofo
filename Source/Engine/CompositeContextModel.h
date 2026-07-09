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

#ifndef SRC_ENGINE_COMPOSITECONTEXTMODEL_H_
#define SRC_ENGINE_COMPOSITECONTEXTMODEL_H_

#include <string>

#include "CorpusBigramContextModel.h"
#include "UserOverrideModel.h"
#include "gramambular2/reading_grid.h"

namespace McBopomofo {

// ContextModel that stacks optional global corpus bigram PMI with optional
// per-user soft personalization:
//   trans = (global ? λ·PMI(prev, word) : 0) + μ_user · userScore(prev, reading, word)
//
// Either pointer may be null. Attach this to ReadingGrid only when at least one
// source is active (global loaded and/or user has usable soft evidence). Cold
// empty user cache + contextual walk OFF must leave contextModel_ as nullptr
// so the unigram fast path stays bit-identical to pre-personalization.
class CompositeContextModel
    : public Formosa::Gramambular2::ReadingGrid::ContextModel {
 public:
  void configure(CorpusBigramContextModel* global, UserOverrideModel* user,
                 double muUser, double timestamp);

  [[nodiscard]] bool isActive() const {
    return global_ != nullptr || user_ != nullptr;
  }

  double score(const std::string& prevWord, const std::string& word,
               double& state) override;
  double scoreWithReading(const std::string& prevWord,
                          const std::string& reading, const std::string& word,
                          double& state) override;
  double beginState() override { return 0.0; }

 private:
  CorpusBigramContextModel* global_ = nullptr;
  UserOverrideModel* user_ = nullptr;
  double muUser_ = UserOverrideModel::kDefaultMuUser;
  double timestamp_ = 0.0;
};

}  // namespace McBopomofo

#endif  // SRC_ENGINE_COMPOSITECONTEXTMODEL_H_
