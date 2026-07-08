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

#include "CorpusBigramContextModel.h"

#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include "gramambular2/language_model.h"
#include "gramambular2/reading_grid.h"
#include "gtest/gtest.h"

namespace McBopomofo {

using Formosa::Gramambular2::LanguageModel;
using Formosa::Gramambular2::ReadingGrid;

namespace {

// A tiny LM for 他跑(的/得/地)很快. 的 is the dominant unigram of ㄉㄜ˙ (as in
// the real dictionary), so a unigram-only walk always yields 的; only a strong
// enough bigram into 得 can flip the choice.
class FakeLM : public LanguageModel {
 public:
  std::vector<Unigram> getUnigrams(const std::string& reading) override {
    if (reading == "ㄊㄚ") return {Unigram("他", -3.0)};
    if (reading == "ㄆㄠˇ") return {Unigram("跑", -3.8)};
    if (reading == "ㄉㄜ˙") {
      return {Unigram("的", -1.6), Unigram("得", -6.8), Unigram("地", -6.8)};
    }
    if (reading == "ㄏㄣˇ") return {Unigram("很", -3.0)};
    if (reading == "ㄎㄨㄞˋ") return {Unigram("快", -3.0)};
    return {};
  }
  bool hasUnigrams(const std::string& reading) override {
    return !getUnigrams(reading).empty();
  }
};

constexpr char kTable[] =
    "# laowang-word-bigram-v1\n"
    "# a comment line\n"
    "跑\t得\t6.00000\n"
    "跑\t的\t-0.50000\n"
    "得\t很\t2.00000\n"
    "malformed-line-without-tabs\n"
    "跑\t地\tnot-a-number\n";

std::string chosenJoined(const ReadingGrid::WalkResult& result) {
  std::string joined;
  for (size_t i = 0; i < result.nodes.size(); ++i) {
    joined += result.chosenValueAt(i);
  }
  return joined;
}

std::string nodeValueJoined(const ReadingGrid::WalkResult& result) {
  std::string joined;
  for (const std::string& value : result.valuesAsStrings()) joined += value;
  return joined;
}

class CorpusBigramContextModelTest : public ::testing::Test {
 protected:
  void SetUp() override {
    std::istringstream table(kTable);
    ASSERT_TRUE(model_.load(table));
  }

  ReadingGrid::WalkResult walkWith(double lambda, bool useModel) {
    ReadingGrid grid(std::make_shared<FakeLM>());
    for (const std::string& reading :
         {"ㄊㄚ", "ㄆㄠˇ", "ㄉㄜ˙", "ㄏㄣˇ", "ㄎㄨㄞˋ"}) {
      grid.insertReading(reading);
    }
    if (useModel) {
      model_.setLambda(lambda);
      grid.setContextModel(&model_);
    }
    return grid.walk();
  }

  CorpusBigramContextModel model_;
};

TEST_F(CorpusBigramContextModelTest, LoadSkipsCommentsAndMalformedRows) {
  // Three well-formed rows; comments and the two malformed rows are skipped.
  EXPECT_EQ(model_.size(), 3u);
  EXPECT_TRUE(model_.isLoaded());
}

TEST_F(CorpusBigramContextModelTest, ScoreReturnsLambdaTimesPmiOrZero) {
  double state = 0.0;
  model_.setLambda(1.0);
  EXPECT_DOUBLE_EQ(model_.score("跑", "得", state), 6.0);
  EXPECT_DOUBLE_EQ(model_.score("跑", "的", state), -0.5);
  model_.setLambda(0.5);
  EXPECT_DOUBLE_EQ(model_.score("跑", "得", state), 3.0);
  // Absent pair, empty previous word, and lambda 0 all contribute nothing.
  EXPECT_DOUBLE_EQ(model_.score("跑", "unknown", state), 0.0);
  EXPECT_DOUBLE_EQ(model_.score("", "得", state), 0.0);
  model_.setLambda(0.0);
  EXPECT_DOUBLE_EQ(model_.score("跑", "得", state), 0.0);
}

TEST_F(CorpusBigramContextModelTest, UnigramOnlyWalkKeepsDominantCharacter) {
  // No context model: 的 is the top unigram of ㄉㄜ˙, so the walk keeps it.
  EXPECT_EQ(chosenJoined(walkWith(0.0, /*useModel=*/false)), "他跑的很快");
}

TEST_F(CorpusBigramContextModelTest, StrongBigramFlipsTwinWithoutMutatingNode) {
  // lambda 1: bigram into 得 (+6) and out of 得 (得很 +2) overcome the ~5.2
  // unigram gap, so the chosen path is 他跑得很快.
  ReadingGrid::WalkResult result = walkWith(1.0, /*useModel=*/true);
  EXPECT_EQ(chosenJoined(result), "他跑得很快");
  // The DP records the choice in selectedUnigramIndices without mutating the
  // node, so the node's own top unigram is still 的 (soft, non-destructive).
  EXPECT_EQ(nodeValueJoined(result), "他跑的很快");
}

TEST_F(CorpusBigramContextModelTest, WeakBigramDoesNotFlip) {
  // lambda 0.25: the bigram bonus is too small to overcome the unigram gap.
  EXPECT_EQ(chosenJoined(walkWith(0.25, /*useModel=*/true)), "他跑的很快");
}

TEST_F(CorpusBigramContextModelTest, ZeroLambdaReproducesUnigramWalk) {
  EXPECT_EQ(chosenJoined(walkWith(0.0, /*useModel=*/true)), "他跑的很快");
}

}  // namespace
}  // namespace McBopomofo
