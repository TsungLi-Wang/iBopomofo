// Copyright (c) 2022 and onwards The McBopomofo Authors.
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

#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include "CorpusBigramContextModel.h"
#include "UserOverrideModel.h"
#include "gramambular2/language_model.h"
#include "gramambular2/reading_grid.h"
#include "gtest/gtest.h"

namespace McBopomofo {

using Formosa::Gramambular2::LanguageModel;
using Formosa::Gramambular2::ReadingGrid;

namespace {
constexpr double kFakeNow = 1657772432;
constexpr int kCapacity = 5;
constexpr double kHalflife = 5400.0;  // 1.5 hr.

// Tiny LM for 他跑(的/得/地)很(快/塊). 的 is top unigram of ㄉㄜ˙; 快 is top of
// ㄎㄨㄞˋ. Strong bigram into 得 flips the display to 得 without mutating the
// node (selectedUnigramIndices only). 塊 is a non-top alternate for the last
// reading so we can simulate a hand pick that UOM should remember.
class UomContextFakeLM : public LanguageModel {
 public:
  std::vector<Unigram> getUnigrams(const std::string& reading) override {
    if (reading == "ㄊㄚ") return {Unigram("他", -3.0)};
    if (reading == "ㄆㄠˇ") return {Unigram("跑", -3.8)};
    if (reading == "ㄉㄜ˙") {
      return {Unigram("的", -1.6), Unigram("得", -6.8), Unigram("地", -6.8)};
    }
    if (reading == "ㄏㄣˇ") return {Unigram("很", -3.0)};
    if (reading == "ㄎㄨㄞˋ") {
      return {Unigram("快", -3.0), Unigram("塊", -7.0)};
    }
    return {};
  }
  bool hasUnigrams(const std::string& reading) override {
    return !getUnigrams(reading).empty();
  }
};

constexpr char kUomBigramTable[] =
    "跑\t得\t6.00000\n"
    "跑\t的\t-0.50000\n"
    "得\t很\t2.00000\n";

// Reading index of the last syllable ㄎㄨㄞˋ (0-based: 他 跑 的 很 快).
constexpr size_t kLastReadingCursor = 4;

std::string chosenJoined(const ReadingGrid::WalkResult& result) {
  std::string joined;
  for (size_t i = 0; i < result.nodes.size(); ++i) {
    joined += result.chosenValueAt(i);
  }
  return joined;
}

// Builds 他跑?很快, optionally with ContextModel. If overrideLast is set,
// hand-picks that value at the last reading then re-walks (same path as
// KeyHandler fixNodeWithReading).
ReadingGrid::WalkResult walkGrid(CorpusBigramContextModel* model, double lambda,
                                 const std::string* overrideLast) {
  ReadingGrid grid(std::make_shared<UomContextFakeLM>());
  for (const std::string& reading :
       {"ㄊㄚ", "ㄆㄠˇ", "ㄉㄜ˙", "ㄏㄣˇ", "ㄎㄨㄞˋ"}) {
    grid.insertReading(reading);
  }
  if (model != nullptr) {
    model->setLambda(lambda);
    grid.setContextModel(model);
  }
  if (overrideLast != nullptr) {
    EXPECT_TRUE(grid.overrideCandidate(kLastReadingCursor, *overrideLast));
  }
  return grid.walk();
}

}  // namespace

TEST(UserOverrideModelTest, BasicOperation) {
  UserOverrideModel uom(kCapacity, kHalflife);
  std::string key = "abc";
  std::string candidate = "v";
  uom.observe(key, candidate, kFakeNow);

  auto v = uom.suggest(key, kFakeNow);
  ASSERT_EQ(v.candidate, candidate);

  v = uom.suggest(key, kFakeNow + kHalflife * 1);
  ASSERT_EQ(v.candidate, candidate);
  v = uom.suggest(key, kFakeNow + kHalflife * 5);
  ASSERT_EQ(v.candidate, candidate);
  v = uom.suggest(key, kFakeNow + kHalflife * 10);
  ASSERT_EQ(v.candidate, candidate);
  v = uom.suggest(key, kFakeNow + kHalflife * 20);
  ASSERT_EQ(v.candidate, candidate);

  // The suggestion is no longer valid after ~30 hours.
  v = uom.suggest(key, kFakeNow + kHalflife * 21);
  ASSERT_TRUE(v.empty());
}

TEST(UserOverrideModelTest, FreshVsFrequent) {
  UserOverrideModel uom(kCapacity, kHalflife);
  std::string key = "abc";
  std::string olderValue = "older";
  std::string newerValue = "newer";

  uom.observe(key, olderValue, kFakeNow);
  uom.observe(key, olderValue, kFakeNow + kHalflife * 1);
  uom.observe(key, olderValue, kFakeNow + kHalflife * 2);
  uom.observe(key, olderValue, kFakeNow + kHalflife * 3);
  uom.observe(key, olderValue, kFakeNow + kHalflife * 4);
  uom.observe(key, newerValue, kFakeNow + kHalflife * 5);
  uom.observe(key, newerValue, kFakeNow + kHalflife * 5.25);

  // Even if newerValue is more recent, olderValue is used more frequently,
  // and so initially olderValue is still suggested.
  auto v = uom.suggest(key, kFakeNow + kHalflife * 7);
  ASSERT_EQ(v.candidate, olderValue);
  v = uom.suggest(key, kFakeNow + kHalflife * 20);
  ASSERT_EQ(v.candidate, olderValue);
  v = uom.suggest(key, kFakeNow + kHalflife * 22);
  ASSERT_EQ(v.candidate, olderValue);

  // At this point, even if olderValue hasn't expired yet, but the
  // less-frequently observed newerValue is fresher.
  uom.observe(key, newerValue, kFakeNow + kHalflife * 23);
  v = uom.suggest(key, kFakeNow + kHalflife * 23.5);
  ASSERT_EQ(v.candidate, newerValue);

  v = uom.suggest(key, kFakeNow + kHalflife * 25);
  ASSERT_EQ(v.candidate, newerValue);

  v = uom.suggest(key, kFakeNow + kHalflife * 45);
  ASSERT_TRUE(v.empty());
}

TEST(UserOverrideModelTest, LRUBehavior) {
  UserOverrideModel uom(2, kHalflife);
  uom.observe("abc", "x", kFakeNow);
  uom.observe("def", "y", kFakeNow + kHalflife);
  uom.observe("ghi", "z", kFakeNow + kHalflife * 2);

  auto v = uom.suggest("ghi", kFakeNow + kHalflife * 3);
  ASSERT_EQ(v.candidate, "z");

  v = uom.suggest("def", kFakeNow + kHalflife * 4);
  ASSERT_EQ(v.candidate, "y");

  // abc evicted.
  v = uom.suggest("abc", kFakeNow + kHalflife * 5);
  ASSERT_TRUE(v.empty());

  uom.observe("jkl", "p", kFakeNow + kHalflife * 6);

  v = uom.suggest("ghi", kFakeNow + kHalflife * 7);
  ASSERT_EQ(v.candidate, "z");

  // def evicted.
  v = uom.suggest("def", kFakeNow + kHalflife * 7);
  ASSERT_TRUE(v.empty());
}

// Control (fast path, no ContextModel): top unigram == display value, so the
// historical FormObservationKey that reads node static values is already
// correct. Learning 快→塊 under that context must still retrieve on the same
// walk. Pairs with ObservationKeyUsesChosenValueWithContextModel below.
TEST(UserOverrideModelTest, ObservationKeyUsesNodeValueOnFastPath) {
  UserOverrideModel uom(kCapacity, kHalflife);
  const std::string kBlock = "塊";

  ReadingGrid::WalkResult before =
      walkGrid(/*model=*/nullptr, /*lambda=*/0.0, /*overrideLast=*/nullptr);
  ASSERT_EQ(chosenJoined(before), "他跑的很快");
  // Without DP, node top unigram is also 的 at the ambiguous slot.
  ASSERT_EQ(before.nodes[2]->unigrams()[0].value(), "的");
  ASSERT_EQ(before.chosenValueAt(2), "的");

  ReadingGrid::WalkResult after =
      walkGrid(/*model=*/nullptr, /*lambda=*/0.0, &kBlock);
  ASSERT_EQ(after.chosenValueAt(kLastReadingCursor), "塊");

  uom.observe(before, after, kLastReadingCursor, kFakeNow);

  ReadingGrid::WalkResult again =
      walkGrid(/*model=*/nullptr, /*lambda=*/0.0, /*overrideLast=*/nullptr);
  auto suggestion = uom.suggest(again, kLastReadingCursor, kFakeNow);
  EXPECT_EQ(suggestion.candidate, "塊");
}

// Regression for §1.2: FormObservationKey used to read node top/current
// unigram, not WalkResult::chosenValueAt. With EnableContextualWalk ON, DP can
// flip a context node (的→得) without mutating the node, so the key stored
// "的" while the user saw "得". That preference then leaks into any later
// walk whose static node value is still "的" (including unigram-only walks).
//
// Protocol (red before fix, green after):
// 1. Strong bigram walk displays 得 (chosen) while node top stays 的.
// 2. User overrides 快→塊; UOM observes under that walk.
// 3. Suggest on the same flipped walk must return 塊 (learned under 得).
// 4. Suggest on a non-flipped walk (display 的) must NOT return 塊 — otherwise
//    the key was keyed on top unigram and polluted unrelated 的 contexts.
TEST(UserOverrideModelTest, ObservationKeyUsesChosenValueWithContextModel) {
  CorpusBigramContextModel model;
  {
    std::istringstream table(kUomBigramTable);
    ASSERT_TRUE(model.load(table));
  }
  UserOverrideModel uom(kCapacity, kHalflife);
  const std::string kBlock = "塊";

  // Walk before override: DP flips 的→得; node is not mutated.
  ReadingGrid::WalkResult before =
      walkGrid(&model, /*lambda=*/1.0, /*overrideLast=*/nullptr);
  ASSERT_EQ(chosenJoined(before), "他跑得很快");
  ASSERT_EQ(before.chosenValueAt(2), "得");
  ASSERT_EQ(before.nodes[2]->unigrams()[0].value(), "的")
      << "Preconditions: DP must flip without mutating the node top unigram.";
  ASSERT_EQ(before.nodes[2]->value(), "的");

  ReadingGrid::WalkResult after =
      walkGrid(&model, /*lambda=*/1.0, &kBlock);
  ASSERT_EQ(after.chosenValueAt(kLastReadingCursor), "塊");
  // Context slot still shows 得 via DP (override is only on the last node).
  ASSERT_EQ(after.chosenValueAt(2), "得");

  uom.observe(before, after, kLastReadingCursor, kFakeNow);

  // Same flipped context: preference must be retrievable.
  ReadingGrid::WalkResult flippedAgain =
      walkGrid(&model, /*lambda=*/1.0, /*overrideLast=*/nullptr);
  ASSERT_EQ(flippedAgain.chosenValueAt(2), "得");
  auto underFlipped =
      uom.suggest(flippedAgain, kLastReadingCursor, kFakeNow);
  EXPECT_EQ(underFlipped.candidate, "塊")
      << "Preference learned while display showed 得 must retrieve when the "
         "walk still shows 得.";

  // Non-flipped context (lambda 0 ⇒ pure unigram path under the same model):
  // display is 的. Must not inherit the 得-context preference.
  ReadingGrid::WalkResult unflipped =
      walkGrid(&model, /*lambda=*/0.0, /*overrideLast=*/nullptr);
  ASSERT_EQ(unflipped.chosenValueAt(2), "的");
  ASSERT_EQ(unflipped.nodes[2]->unigrams()[0].value(), "的");
  auto underUnflipped =
      uom.suggest(unflipped, kLastReadingCursor, kFakeNow);
  EXPECT_TRUE(underUnflipped.empty())
      << "Bug §1.2: key was built from top unigram 的 while user saw 得, so "
         "the preference leaks into any 的 context (including unigram-only). "
         "Got candidate='"
      << underUnflipped.candidate << "'.";
}

}  // namespace McBopomofo
