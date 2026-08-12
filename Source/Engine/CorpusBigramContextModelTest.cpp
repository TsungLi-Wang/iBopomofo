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

namespace iBopomofo {

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

  // Builds the 他跑?很快 grid, optionally sets the context model, then
  // simulates the user hand-picking a candidate from the menu at overrideLoc
  // (this is exactly what KeyHandler's fixNodeWithReading does: overrideCandidate
  // with the default kOverrideValueWithHighScore, then re-walk).
  ReadingGrid::WalkResult walkWithOverride(bool useModel, double lambda,
                                           size_t overrideLoc,
                                           const std::string& overrideValue) {
    ReadingGrid grid(std::make_shared<FakeLM>());
    for (const std::string& reading :
         {"ㄊㄚ", "ㄆㄠˇ", "ㄉㄜ˙", "ㄏㄣˇ", "ㄎㄨㄞˋ"}) {
      grid.insertReading(reading);
    }
    if (useModel) {
      model_.setLambda(lambda);
      grid.setContextModel(&model_);
    }
    EXPECT_TRUE(grid.overrideCandidate(overrideLoc, overrideValue));
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

// Control: with no context model (the pre-v2.2.0 fast path), a user override is
// honored. 的 is the top unigram of ㄉㄜ˙, so only the override can move the
// choice onto 得. chosenValueAt falls back to node->value() (the overridden
// unigram) because selectedUnigramIndices is empty on the fast path. This proves
// the override machinery itself is sound; the divergence below is walk-specific.
TEST_F(CorpusBigramContextModelTest, OverrideIsHonoredOnFastPath) {
  ReadingGrid::WalkResult result =
      walkWithOverride(/*useModel=*/false, /*lambda=*/0.0,
                       /*overrideLoc=*/2, /*overrideValue=*/"得");
  EXPECT_EQ(result.chosenValueAt(2), "得");
  EXPECT_EQ(chosenJoined(result), "他跑得很快");
}

// Regression for the v2.2.0 "selected candidate does not commit" bug. With a
// context model set (EnableContextualWalk ON), the DP recomputes
// selectedUnigramIndices from raw per-unigram scores (u.score()) and never
// consults the node's override, so chosenValueAt returns the DP's own pick and
// the user's hand-picked candidate is silently discarded. lambda 0 makes the
// context model contribute nothing, so the ONLY thing that could move the choice
// off the top unigram (的) onto 得 is the override, which must be honored exactly
// as it is on the fast path above.
TEST_F(CorpusBigramContextModelTest, OverrideIsHonoredWithContextModel) {
  ReadingGrid::WalkResult result =
      walkWithOverride(/*useModel=*/true, /*lambda=*/0.0,
                       /*overrideLoc=*/2, /*overrideValue=*/"得");
  EXPECT_EQ(result.chosenValueAt(2), "得")
      << "Contextual-walk DP ignored the user's candidate override and returned "
         "its own pick instead.";
  EXPECT_EQ(chosenJoined(result), "他跑得很快");
}

// n-gram + RNN hybrid: after a ContextModel walk has filled
// selectedUnigramIndices, a post-walk path reselect (no node override) must
// change chosenValueAt. This is the clean write path for neural path scoring
// — selection lives in WalkResult, not as a lattice patch.
TEST_F(CorpusBigramContextModelTest, PostWalkReselectUpdatesChosenWithContextModel) {
  ReadingGrid::WalkResult result = walkWith(0.0, /*useModel=*/true);
  ASSERT_EQ(result.chosenValueAt(2), "的");
  ASSERT_EQ(result.selectedUnigramIndices.size(), result.nodes.size());
  ASSERT_TRUE(result.reselectUnigramValue(2, "得"));
  EXPECT_FALSE(result.nodes[2]->isOverridden());
  EXPECT_EQ(result.chosenValueAt(2), "得");
  EXPECT_EQ(chosenJoined(result), "他跑得很快");
}

// Regression: soft override applied AFTER contextual walk (neural deferred
// style) must win over stale DP indices in chosenValueAt. Without override
// priority, EnableContextualWalk ON would make post-walk neural flips invisible.
TEST_F(CorpusBigramContextModelTest, PostWalkSoftOverrideBeatsDpIndices) {
  ReadingGrid::WalkResult result = walkWith(0.0, /*useModel=*/true);
  ASSERT_EQ(result.chosenValueAt(2), "的");
  ASSERT_TRUE(result.nodes[2]->selectOverrideUnigram(
      "得", ReadingGrid::Node::OverrideType::kOverrideValueWithScoreFromTopUnigram));
  EXPECT_EQ(result.chosenValueAt(2), "得")
      << "Post-walk soft override lost to ContextModel selectedUnigramIndices.";
  EXPECT_EQ(chosenJoined(result), "他跑得很快");
}

}  // namespace
}  // namespace iBopomofo
