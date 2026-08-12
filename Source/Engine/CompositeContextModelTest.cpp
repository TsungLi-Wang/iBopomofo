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

#include <cmath>
#include <cstdio>
#include <memory>
#include <string>
#include <unistd.h>
#include <vector>

#include "UserOverrideModel.h"
#include "gramambular2/language_model.h"
#include "gramambular2/reading_grid.h"
#include "gtest/gtest.h"

namespace iBopomofo {
namespace {

using Formosa::Gramambular2::LanguageModel;
using Formosa::Gramambular2::ReadingGrid;

// Moderate unigram gap (~3.0): with mu=4 and count=2,
// userScore = log(3)≈1.099 → 4.39 > 3.0 so S1 flips at C_min.
// Still requires soft boost (top unigram wins without it).
class SoftFlipFakeLM : public LanguageModel {
 public:
  std::vector<Unigram> getUnigrams(const std::string& reading) override {
    if (reading == "ㄊㄚ") return {Unigram("他", -3.0)};
    if (reading == "ㄆㄠˇ") return {Unigram("跑", -3.8)};
    if (reading == "ㄉㄜ˙") {
      return {Unigram("的", -2.0), Unigram("得", -5.0), Unigram("地", -6.0)};
    }
    if (reading == "ㄏㄣˇ") return {Unigram("很", -3.0)};
    if (reading == "ㄎㄨㄞˋ") return {Unigram("快", -3.0)};
    // Unrelated context for S2/S3-style no-spill: 說的...
    if (reading == "ㄕㄨㄛ") return {Unigram("說", -3.0)};
    return {};
  }
  bool hasUnigrams(const std::string& reading) override {
    return !getUnigrams(reading).empty();
  }
};

std::string chosenJoined(const ReadingGrid::WalkResult& r) {
  std::string s;
  for (size_t i = 0; i < r.nodes.size(); ++i) s += r.chosenValueAt(i);
  return s;
}

ReadingGrid::WalkResult walkReadings(const std::vector<std::string>& readings,
                                     ReadingGrid::ContextModel* model) {
  ReadingGrid grid(std::make_shared<SoftFlipFakeLM>());
  for (const auto& r : readings) grid.insertReading(r);
  grid.setContextModel(model);
  return grid.walk();
}

ReadingGrid::WalkResult walkTaPaoDe(ReadingGrid::ContextModel* model) {
  return walkReadings({"ㄊㄚ", "ㄆㄠˇ", "ㄉㄜ˙", "ㄏㄣˇ", "ㄎㄨㄞˋ"}, model);
}

void trainSoftDe(UserOverrideModel* uom, int k, double t0) {
  // prev=跑, reading=ㄉㄜ˙, word=得
  for (int i = 0; i < k; ++i) {
    uom->noteSoftObservation("跑", "ㄉㄜ˙", "得", t0 + i);
  }
}

// --- Cold / attach policy ---

TEST(CompositeContextModelTest, ColdEmptyNeverNeedsAttach) {
  UserOverrideModel uom(32, 604800.0);
  EXPECT_FALSE(uom.hasUsableSoftEvidence(1000.0));
  CompositeContextModel composite;
  composite.configure(/*global=*/nullptr, /*user=*/nullptr, 4.0, 1000.0);
  EXPECT_FALSE(composite.isActive());
}

TEST(CompositeContextModelTest, SoftEvidenceAfterCmin) {
  UserOverrideModel uom(32, 604800.0);
  const double t = 1000.0;
  uom.noteSoftObservation("跑", "ㄉㄜ˙", "得", t);  // count 1 < C_min
  EXPECT_FALSE(uom.hasUsableSoftEvidence(t));
  uom.noteSoftObservation("跑", "ㄉㄜ˙", "得", t + 1);
  EXPECT_TRUE(uom.hasUsableSoftEvidence(t + 1));
}

// --- S1: learn 得 under 跑, flip at k>=C_min with mu=4 ---

TEST(CompositeContextModelTest, S1_LearnsAndFlipsAtCmin) {
  const double t = 5000.0;
  // Baseline without user: 的 wins.
  EXPECT_EQ(chosenJoined(walkTaPaoDe(nullptr)), "他跑的很快");

  UserOverrideModel uom(32, 604800.0);
  trainSoftDe(&uom, /*k=*/1, t);
  CompositeContextModel composite;
  composite.configure(nullptr, &uom, UserOverrideModel::kDefaultMuUser, t + 10);
  // Below C_min: still 的.
  EXPECT_EQ(chosenJoined(walkTaPaoDe(&composite)), "他跑的很快");

  uom.clear();
  trainSoftDe(&uom, /*k=*/2, t);
  composite.configure(nullptr, &uom, UserOverrideModel::kDefaultMuUser, t + 10);
  EXPECT_EQ(chosenJoined(walkTaPaoDe(&composite)), "他跑得很快")
      << "S1: after k=C_min=2, soft must flip 的→得 under prev=跑";
}

// --- S2: no spill to unrelated prev ---

TEST(CompositeContextModelTest, S2_NoSpillToUnrelatedPrev) {
  const double t = 5000.0;
  UserOverrideModel uom(32, 604800.0);
  trainSoftDe(&uom, /*k=*/5, t);
  CompositeContextModel composite;
  composite.configure(nullptr, &uom, UserOverrideModel::kDefaultMuUser, t + 10);

  // 他說的很快 — prev before ㄉㄜ˙ is 說, not 跑.
  auto result =
      walkReadings({"ㄊㄚ", "ㄕㄨㄛ", "ㄉㄜ˙", "ㄏㄣˇ", "ㄎㄨㄞˋ"}, &composite);
  EXPECT_EQ(result.chosenValueAt(2), "的")
      << "S2: preference taught under 跑 must not leak to 說";
  EXPECT_EQ(chosenJoined(result), "他說的很快");
}

// --- S4: save/load survives ---

TEST(CompositeContextModelTest, S4_PersistsAcrossReload) {
  const double t = 8000.0;
  UserOverrideModel uom(32, 604800.0);
  // Full-key observe so save/load round-trips LRU + soft rebuild.
  // Key shape: ant-prev-head with head reading ㄉㄜ˙ and prev value 跑.
  const std::string key = "()-(ㄆㄠˇ,跑)-(ㄉㄜ˙,的)";
  uom.observe(key, "得", t, false);
  uom.observe(key, "得", t + 1, false);
  ASSERT_TRUE(uom.hasUsableSoftEvidence(t + 2));
  EXPECT_GT(uom.userScore("跑", "ㄉㄜ˙", "得", t + 2), 0.0);

  char path[] = "/tmp/laowang-uom-test-XXXXXX";
  int fd = mkstemp(path);
  ASSERT_GE(fd, 0);
  close(fd);

  ASSERT_TRUE(uom.save(path));
  UserOverrideModel loaded(32, 604800.0);
  ASSERT_TRUE(loaded.load(path));
  EXPECT_GT(loaded.userScore("跑", "ㄉㄜ˙", "得", t + 2), 0.0);
  CompositeContextModel composite;
  composite.configure(nullptr, &loaded, UserOverrideModel::kDefaultMuUser,
                      t + 2);
  EXPECT_EQ(chosenJoined(walkTaPaoDe(&composite)), "他跑得很快");
  std::remove(path);
}

// --- S5: decay eventually returns 0 ---

TEST(CompositeContextModelTest, S5_DecaysAfterManyHalflives) {
  const double halflife = 100.0;
  UserOverrideModel uom(32, halflife);
  const double t0 = 0.0;
  trainSoftDe(&uom, 5, t0);
  EXPECT_GT(uom.userScore("跑", "ㄉㄜ˙", "得", t0), 0.0);
  // 21 half-lives past last observation → past kDecayThreshold.
  const double far = t0 + 4 + 21 * halflife;
  EXPECT_DOUBLE_EQ(uom.userScore("跑", "ㄉㄜ˙", "得", far), 0.0);
  EXPECT_FALSE(uom.hasUsableSoftEvidence(far));
}

// --- S6: hard node override still wins over soft ---

TEST(CompositeContextModelTest, S6_HardOverrideBeatsSoft) {
  const double t = 9000.0;
  UserOverrideModel uom(32, 604800.0);
  trainSoftDe(&uom, 5, t);
  CompositeContextModel composite;
  composite.configure(nullptr, &uom, UserOverrideModel::kDefaultMuUser, t + 1);

  ReadingGrid grid(std::make_shared<SoftFlipFakeLM>());
  for (const std::string& r :
       {"ㄊㄚ", "ㄆㄠˇ", "ㄉㄜ˙", "ㄏㄣˇ", "ㄎㄨㄞˋ"}) {
    grid.insertReading(r);
  }
  grid.setContextModel(&composite);
  // Soft would pick 得; force 的 via override.
  ASSERT_TRUE(grid.overrideCandidate(/*loc=*/2, "的"));
  auto result = grid.walk();
  EXPECT_EQ(result.chosenValueAt(2), "的")
      << "S6: hand override must beat soft personalization";
}

// --- Promotion gate: mu sweep, S1 at k=C_min..C_min+2 ---

TEST(CompositeContextModelTest, PromotionGate_MuSweep) {
  const double t = 12000.0;
  const std::vector<double> mus = {2.0, 3.0, 4.0, 5.0, 6.0};
  double bestMu = -1;
  double bestAdoption = -1;
  double bestSpill = 1.0;

  std::printf("=== Soft personalization mu sweep (synthetic) ===\n");
  for (double mu : mus) {
    int adoptOk = 0;
    int adoptN = 0;
    int spillHit = 0;
    int spillN = 0;
    for (int k = static_cast<int>(UserOverrideModel::kMinSoftCount);
         k <= static_cast<int>(UserOverrideModel::kMinSoftCount) + 2; ++k) {
      UserOverrideModel uom(32, 604800.0);
      trainSoftDe(&uom, k, t);
      CompositeContextModel composite;
      composite.configure(nullptr, &uom, mu, t + 10);
      auto flipped = walkTaPaoDe(&composite);
      ++adoptN;
      if (flipped.chosenValueAt(2) == "得") ++adoptOk;

      auto spill = walkReadings(
          {"ㄊㄚ", "ㄕㄨㄛ", "ㄉㄜ˙", "ㄏㄣˇ", "ㄎㄨㄞˋ"}, &composite);
      ++spillN;
      if (spill.chosenValueAt(2) == "得") ++spillHit;
    }
    double adoption =
        adoptN ? static_cast<double>(adoptOk) / adoptN : 0.0;
    double spillRate =
        spillN ? static_cast<double>(spillHit) / spillN : 0.0;
    std::printf("mu=%.1f  adoption=%.0f%% (%d/%d)  spill=%.0f%% (%d/%d)\n", mu,
                100.0 * adoption, adoptOk, adoptN, 100.0 * spillRate, spillHit,
                spillN);
    // Prefer full adoption with zero spill; among those, prefer default 4.0.
    if (adoption >= bestAdoption && spillRate <= bestSpill) {
      if (adoption > bestAdoption || spillRate < bestSpill ||
          (adoption == bestAdoption && spillRate == bestSpill &&
           std::abs(mu - UserOverrideModel::kDefaultMuUser) <
               std::abs(bestMu - UserOverrideModel::kDefaultMuUser))) {
        bestAdoption = adoption;
        bestSpill = spillRate;
        bestMu = mu;
      }
    }
  }
  std::printf("best mu=%.1f adoption=%.0f%% spill=%.0f%%\n", bestMu,
              100.0 * bestAdoption, 100.0 * bestSpill);
  ASSERT_EQ(bestAdoption, 1.0)
      << "Promotion gate: must reach 100% adoption for some mu in 2..6";
  ASSERT_EQ(bestSpill, 0.0) << "Promotion gate: spill must stay 0%";
  // Default mu=4.0 must itself pass (not only some other mu).
  {
    UserOverrideModel uom(32, 604800.0);
    trainSoftDe(&uom, static_cast<int>(UserOverrideModel::kMinSoftCount), t);
    CompositeContextModel composite;
    composite.configure(nullptr, &uom, UserOverrideModel::kDefaultMuUser,
                        t + 10);
    EXPECT_EQ(walkTaPaoDe(&composite).chosenValueAt(2), "得");
    EXPECT_EQ(walkReadings({"ㄊㄚ", "ㄕㄨㄛ", "ㄉㄜ˙", "ㄏㄣˇ", "ㄎㄨㄞˋ"},
                           &composite)
                  .chosenValueAt(2),
              "的");
  }
}

// Zero user contribution must not change unigram walk when composite is
// attached with empty soft (should not attach in production; still check
// mathematical neutrality of userScore=0 path via null user).
TEST(CompositeContextModelTest, NullUserCompositeMatchesUnigram) {
  CompositeContextModel composite;
  composite.configure(nullptr, nullptr, 4.0, 0.0);
  // isActive false — callers must not attach; if forced, score is 0.
  double state = 0;
  EXPECT_DOUBLE_EQ(composite.scoreWithReading("跑", "ㄉㄜ˙", "得", state), 0.0);
}

// S7: forceHighScoreOverride flag still recorded for multi-char competition
// cases; Slice B keeps hard suggest only when this flag is true.
TEST(CompositeContextModelTest, S7_ForceHighScoreFlagPreserved) {
  UserOverrideModel uom(32, 604800.0);
  const double t = 100.0;
  const std::string key = "()-(ㄗㄥ,增)-(ㄐㄧㄚ,加)";
  uom.observe(key, "字彙", t, /*forceHighScoreOverride=*/true);
  auto s = uom.suggest(key, t);
  EXPECT_EQ(s.candidate, "字彙");
  EXPECT_TRUE(s.forceHighScoreOverride);

  uom.observe(key, "字彙", t + 1, /*forceHighScoreOverride=*/false);
  // Latest observe sets force on that override entry; force flag follows the
  // winning override row.
  s = uom.suggest(key, t + 1);
  EXPECT_EQ(s.candidate, "字彙");
}

}  // namespace
}  // namespace iBopomofo
