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

#include "CompositeContextModel.h"

#include <functional>
#include <string>

namespace McBopomofo {

void CompositeContextModel::configure(CorpusBigramContextModel* global,
                                      UserOverrideModel* user, double muUser,
                                      double timestamp) {
  global_ = global;
  user_ = user;
  muUser_ = muUser;
  timestamp_ = timestamp;
}

double CompositeContextModel::score(const std::string& prevWord,
                                    const std::string& word, double& state) {
  // Reading unknown: user soft contributes 0 without a reading.
  return scoreWithReading(prevWord, /*reading=*/"", word, state);
}

double CompositeContextModel::scoreWithReading(const std::string& prevWord,
                                               const std::string& reading,
                                               const std::string& word,
                                               double& state) {
  double total = 0.0;
  if (global_ != nullptr) {
    total += global_->score(prevWord, word, state);
  } else {
    // Stable recombination token when only the user model is present.
    state = static_cast<double>(std::hash<std::string>{}(word) & 0xFFFFFFFFULL);
  }
  if (user_ != nullptr && !reading.empty()) {
    total += muUser_ * user_->userScore(prevWord, reading, word, timestamp_);
  }
  return total;
}

}  // namespace McBopomofo
