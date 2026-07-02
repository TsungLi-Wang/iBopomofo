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

#include "ConfusionPairDisambiguator.h"

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

// A tiny LM with just enough unigrams to compose 你(ㄋㄧˇ)/我(ㄨㄛˇ)
// 在/再(ㄗㄞˋ)吃(ㄔ)飯(ㄈㄢˋ)、說(ㄕㄨㄛ)、見(ㄐㄧㄢˋ)、現在(ㄒㄧㄢˋ-ㄗㄞˋ)
// sentences. The scores make 在 the top unigram of ㄗㄞˋ, and — mirroring
// the real dictionary — ㄨㄛˇ-ㄗㄞˋ has both twins 我在/我再 with 我在 on
// top, so the walk goes through the two-character node.
class FakeLM : public LanguageModel {
 public:
  std::vector<Unigram> getUnigrams(const std::string& reading) override {
    if (reading == "ㄗㄞˋ") {
      return {Unigram("在", -3.0), Unigram("再", -4.5), Unigram("載", -6.0)};
    }
    if (reading == "ㄋㄧˇ") {
      return {Unigram("你", -3.0)};
    }
    if (reading == "ㄨㄛˇ") {
      return {Unigram("我", -3.0)};
    }
    if (reading == "ㄨㄛˇ-ㄗㄞˋ") {
      return {Unigram("我在", -4.2), Unigram("我再", -4.9)};
    }
    if (reading == "ㄔ") {
      return {Unigram("吃", -3.5)};
    }
    if (reading == "ㄈㄢˋ") {
      return {Unigram("飯", -3.5)};
    }
    if (reading == "ㄕㄨㄛ") {
      return {Unigram("說", -3.5)};
    }
    if (reading == "ㄐㄧㄢˋ") {
      return {Unigram("見", -4.0)};
    }
    if (reading == "ㄒㄧㄢˋ-ㄗㄞˋ") {
      return {Unigram("現在", -4.0)};
    }
    if (reading == "ㄒㄧㄢˋ") {
      return {Unigram("現", -5.0)};
    }
    return {};
  }

  bool hasUnigrams(const std::string& reading) override {
    return !getUnigrams(reading).empty();
  }
};

// Table: right neighbor 吃/說/見 and left neighbor begin-of-buffer point to
// 再; prior leans to 在. Threshold 0.
constexpr char kTable[] =
    "# test table\n"
    "PAIR\tㄗㄞˋ\t在\t再\n"
    "PRIOR\t-0.500000\n"
    "THRESHOLD\t0.000000\n"
    "L\t^\t1.200000\n"
    "L\t你\t0.300000\n"
    "L\t我\t0.300000\n"
    "L\t現\t-2.000000\n"
    "R\t吃\t2.000000\n"
    "R\t說\t2.000000\n"
    "R\t見\t3.000000\n"
    "R\t$\t-0.400000\n";

class ConfusionPairDisambiguatorTest : public ::testing::Test {
 protected:
  void SetUp() override {
    grid_ = std::make_unique<ReadingGrid>(std::make_shared<FakeLM>());
    std::istringstream table(kTable);
    ASSERT_TRUE(disambiguator_.load(table));
  }

  ReadingGrid::WalkResult insertAndWalk(
      const std::vector<std::string>& readings) {
    for (const std::string& reading : readings) {
      grid_->insertReading(reading);
    }
    ReadingGrid::WalkResult result = grid_->walk();
    disambiguator_.rescoreWalk(result);
    return result;
  }

  static std::string joinedValues(const ReadingGrid::WalkResult& result) {
    std::string joined;
    for (const std::string& value : result.valuesAsStrings()) {
      joined += value;
    }
    return joined;
  }

  std::unique_ptr<ReadingGrid> grid_;
  ConfusionPairDisambiguator disambiguator_;
};

TEST_F(ConfusionPairDisambiguatorTest, FlipsToAltWithRightEvidence) {
  // 你(ㄗㄞˋ)吃飯: L=你 (+0.3), R=吃 (+2.0), prior -0.5 => 1.8 > 0 => 再.
  // ㄋㄧˇ-ㄗㄞˋ has no dictionary word, so this exercises the span-1 path.
  ReadingGrid::WalkResult result =
      insertAndWalk({"ㄋㄧˇ", "ㄗㄞˋ", "ㄔ", "ㄈㄢˋ"});
  EXPECT_EQ(joinedValues(result), "你再吃飯");
}

TEST_F(ConfusionPairDisambiguatorTest, KeepsDefaultWithoutEvidence) {
  // 你(ㄗㄞˋ)飯: R=飯 unknown (0), L=你 (+0.3), prior -0.5 => -0.2 => 在.
  ReadingGrid::WalkResult result = insertAndWalk({"ㄋㄧˇ", "ㄗㄞˋ", "ㄈㄢˋ"});
  EXPECT_EQ(joinedValues(result), "你在飯");
}

TEST_F(ConfusionPairDisambiguatorTest, FlipsInsideMultiCharTwinNode) {
  // ㄨㄛˇ-ㄗㄞˋ resolves to the two-character dictionary node 我在 (its twin
  // 我再 exists but scores lower). L is 我 inside the node, R is 說 from the
  // next node: 0.3 + 2.0 - 0.5 = 1.8 > 0 => flip the node value to 我再.
  ReadingGrid::WalkResult result = insertAndWalk({"ㄨㄛˇ", "ㄗㄞˋ", "ㄕㄨㄛ"});
  bool sawTwinNode = false;
  for (const ReadingGrid::NodePtr& node : result.nodes) {
    if (node->reading() == "ㄨㄛˇ-ㄗㄞˋ") {
      sawTwinNode = true;
    }
  }
  ASSERT_TRUE(sawTwinNode) << "walk should go through the 我在/我再 node";
  EXPECT_EQ(joinedValues(result), "我再說");
}

TEST_F(ConfusionPairDisambiguatorTest, SkipsMultiCharacterDictionaryNodes) {
  // 現在 is a span-2 dictionary node and must not be touched even though 見
  // follows: 現在見 stays intact.
  ReadingGrid::WalkResult result =
      insertAndWalk({"ㄒㄧㄢˋ", "ㄗㄞˋ", "ㄐㄧㄢˋ"});
  EXPECT_EQ(joinedValues(result), "現在見");
}

TEST_F(ConfusionPairDisambiguatorTest, RetractsWhenContextChanges) {
  // Typing progressively: (ㄗㄞˋ) alone at begin-of-buffer leans 再
  // (L=^ +1.2, R=$ -0.4, prior -0.5 => +0.3).
  grid_->insertReading("ㄗㄞˋ");
  ReadingGrid::WalkResult first = grid_->walk();
  disambiguator_.rescoreWalk(first);
  EXPECT_EQ(joinedValues(first), "再");

  // The next reading turns the context into (ㄗㄞˋ)飯: R=飯 unknown, so the
  // score drops to +0.7... (L=^ 1.2, R unknown 0, prior -0.5 => +0.7) which
  // still leans 再; use 現(ㄒㄧㄢˋ) inserted before instead to flip it back:
  // 現(ㄗㄞˋ): L=現 (-2.0), R=$ (-0.4), prior -0.5 => -2.9 => 在.
  grid_->setCursor(0);
  grid_->insertReading("ㄒㄧㄢˋ");
  ReadingGrid::WalkResult second = grid_->walk();
  disambiguator_.rescoreWalk(second);
  // 現-ㄗㄞˋ forms the dictionary word 現在 (span 2), which outranks the
  // single-character path; either way the surface must be 現在, and the
  // previously applied 再 override must not survive on the walked path.
  EXPECT_EQ(joinedValues(second), "現在");
}

TEST_F(ConfusionPairDisambiguatorTest, RetractsToEngineTopOnSingleCharPath) {
  // Same retract scenario but forcing a single-character context by using a
  // reading pair that does not form a dictionary word: (ㄗㄞˋ) then 飯 after.
  grid_->insertReading("ㄗㄞˋ");
  ReadingGrid::WalkResult first = grid_->walk();
  disambiguator_.rescoreWalk(first);
  EXPECT_EQ(joinedValues(first), "再");  // L=^, R=$: 1.2-0.4-0.5 = +0.3

  grid_->insertReading("ㄈㄢˋ");
  ReadingGrid::WalkResult second = grid_->walk();
  bool changed = disambiguator_.rescoreWalk(second);
  // Now L=^ (+1.2), R=飯 unknown (0), prior -0.5 => +0.7 => still 再, no
  // change expected this time.
  EXPECT_FALSE(changed);
  EXPECT_EQ(joinedValues(second), "再飯");

  // Insert 現 at the front: L becomes 現 (-2.0), R=飯 (0), prior -0.5 =>
  // -2.5 => retract to 在. (現-ㄗㄞˋ-ㄈㄢˋ: the 現在 dictionary node also
  // competes; accept either surface as long as no 再 survives.)
  grid_->setCursor(0);
  grid_->insertReading("ㄒㄧㄢˋ");
  ReadingGrid::WalkResult third = grid_->walk();
  disambiguator_.rescoreWalk(third);
  std::string surface = joinedValues(third);
  EXPECT_TRUE(surface == "現在飯") << "surface=" << surface;
}

TEST_F(ConfusionPairDisambiguatorTest, RespectsUserOverride) {
  grid_->insertReading("ㄋㄧˇ");
  grid_->insertReading("ㄗㄞˋ");
  grid_->insertReading("ㄔ");
  grid_->insertReading("ㄈㄢˋ");

  // The user explicitly picks 在 at the ㄗㄞˋ position (index 1), the way
  // fixNodeWithReading does.
  ASSERT_TRUE(grid_->overrideCandidate(
      1, ReadingGrid::Candidate("ㄗㄞˋ", "在"),
      ReadingGrid::Node::OverrideType::kOverrideValueWithHighScore));
  ReadingGrid::WalkResult result = grid_->walk();
  bool changed = disambiguator_.rescoreWalk(result);
  EXPECT_FALSE(changed);
  EXPECT_EQ(joinedValues(result), "你在吃飯");
}

TEST_F(ConfusionPairDisambiguatorTest, SoftOverrideKeepsNodeScore) {
  ReadingGrid::WalkResult result =
      insertAndWalk({"ㄋㄧˇ", "ㄗㄞˋ", "ㄔ", "ㄈㄢˋ"});
  ASSERT_EQ(joinedValues(result), "你再吃飯");
  // The flipped node must carry the top unigram's score (在, -3.0) so path
  // competition is unaffected.
  for (const ReadingGrid::NodePtr& node : result.nodes) {
    if (node->reading() == "ㄗㄞˋ") {
      EXPECT_TRUE(node->isOverridden());
      EXPECT_DOUBLE_EQ(node->score(), -3.0);
    }
  }
}

TEST_F(ConfusionPairDisambiguatorTest, NotLoadedDoesNothing) {
  ConfusionPairDisambiguator empty;
  EXPECT_FALSE(empty.isLoaded());
  ReadingGrid::WalkResult result =
      insertAndWalk({"ㄋㄧˇ", "ㄗㄞˋ", "ㄔ", "ㄈㄢˋ"});
  EXPECT_FALSE(empty.rescoreWalk(result));
}

TEST(ConfusionPairDisambiguatorTokenTest, NormalizeContextToken) {
  EXPECT_EQ(ConfusionPairDisambiguator::NormalizeContextToken("好"), "好");
  EXPECT_EQ(ConfusionPairDisambiguator::NormalizeContextToken("，"), "，");
  EXPECT_EQ(ConfusionPairDisambiguator::NormalizeContextToken("7"), "#D");
  EXPECT_EQ(ConfusionPairDisambiguator::NormalizeContextToken("７"), "#D");
  EXPECT_EQ(ConfusionPairDisambiguator::NormalizeContextToken("x"), "#A");
  EXPECT_EQ(ConfusionPairDisambiguator::NormalizeContextToken("★"), "#O");
  EXPECT_EQ(ConfusionPairDisambiguator::NormalizeContextToken(""), "#O");
}

}  // namespace

}  // namespace McBopomofo
