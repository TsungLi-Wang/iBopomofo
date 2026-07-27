// Copyright (c) 2026 and onwards The McBopomofo Authors.
//
// Permanent gate: NeuralLMPathScorer::scoreNBest must match the sequential
// scoreSentence oracle path-by-path (shipping uses scoreNBest only).
// Catches silent regressions when the batched/trie path drifts.

#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <string>
#include <vector>

#include <gtest/gtest.h>

#include "NeuralLMPathScorer.h"

namespace {

std::string FindShippingModel() {
  if (const char* env = std::getenv("MCBO_PATH_CHAR_LSTM")) {
    if (std::filesystem::exists(env)) return env;
  }
#ifdef MCBO_TEST_DATA_DIR
  {
    std::string p = std::string(MCBO_TEST_DATA_DIR) + "/path-char-lstm.bin";
    if (std::filesystem::exists(p)) return p;
  }
#endif
  // Relative to Source/Engine/build-test cwd or repo Source/Engine.
  const char* candidates[] = {
      "../Data/path-char-lstm.bin",
      "../../Data/path-char-lstm.bin",
      "Source/Data/path-char-lstm.bin",
      "../Source/Data/path-char-lstm.bin",
  };
  for (const char* c : candidates) {
    if (std::filesystem::exists(c)) return c;
  }
  return {};
}

// scoreNBest docs: arithmetically equal to scoreSentence except float
// reassociation. Observed diffs ~1e-6..1e-9 on log10 sums; still far below
// any ν·Δ that could flip n-best ranking (verified by argmax check below).
bool ScoresEqual(double a, double b) {
  if (a == b) return true;
  const double abs_tol = 1e-5;
  const double rel_tol = 1e-6;
  const double diff = std::fabs(a - b);
  if (diff <= abs_tol) return true;
  const double scale = std::max(std::fabs(a), std::fabs(b));
  return scale > 0 && diff <= rel_tol * scale;
}

}  // namespace

TEST(NeuralLMPathScorerEquality, ScoreNBestMatchesScoreSentenceOracle) {
  const std::string model = FindShippingModel();
  ASSERT_FALSE(model.empty()) << "path-char-lstm.bin not found; set MCBO_PATH_CHAR_LSTM";

  McBopomofo::NeuralLMPathScorer scorer;
  ASSERT_TRUE(scorer.load(model)) << "failed to load " << model;
  ASSERT_TRUE(scorer.isLoaded());

  // Multi-path pools (shared prefixes exercise the trie path).
  const std::vector<std::vector<std::vector<std::string>>> pools = {
      {
          {"百貨", "門市", "不", "適用"},
          {"百貨", "們", "是", "不", "是", "用"},
          {"慢慢", "的", "走", "過來"},
          {"慢慢", "地", "走", "過來"},
      },
      {
          {"一", "隻", "貓"},
          {"一", "只", "貓"},
          {"一", "支", "貓"},
      },
      {
          {"他", "跑得", "很快"},
          {"他", "跑", "的", "很快"},
          {"他", "跑", "得", "很快"},
      },
  };

  for (size_t pi = 0; pi < pools.size(); ++pi) {
    const auto& paths = pools[pi];
    std::vector<double> batched = scorer.scoreNBest(paths);
    ASSERT_EQ(batched.size(), paths.size()) << "pool " << pi;

    std::vector<double> sequential;
    sequential.reserve(paths.size());
    for (const auto& path : paths) {
      sequential.push_back(scorer.scoreSentence(path));
    }

    for (size_t i = 0; i < paths.size(); ++i) {
      EXPECT_TRUE(ScoresEqual(batched[i], sequential[i]))
          << "pool " << pi << " path " << i << " nbest=" << batched[i]
          << " sentence=" << sequential[i];
    }

    // Ranking (argmax) must agree.
    size_t bestB = 0, bestS = 0;
    for (size_t i = 1; i < paths.size(); ++i) {
      if (batched[i] > batched[bestB]) bestB = i;
      if (sequential[i] > sequential[bestS]) bestS = i;
    }
    EXPECT_EQ(bestB, bestS) << "pool " << pi << " argmax mismatch";
  }
}
