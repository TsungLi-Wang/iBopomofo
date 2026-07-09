// Copyright (c) 2017 ond onwards The McBopomofo Authors.
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

#ifndef SRC_ENGINE_USEROVERRIDEMODEL_H_
#define SRC_ENGINE_USEROVERRIDEMODEL_H_

#include <list>
#include <map>
#include <string>
#include <unordered_map>
#include <utility>

#include "gramambular2/reading_grid.h"

namespace McBopomofo {

// User override / personalization memory.
//
// Hard path (legacy): observe/suggest with full observation keys, used by
// KeyHandler to overrideCandidate after walk (Slice B limits this to
// forceHighScoreOverride only).
//
// Soft path (roadmap step 4 B): a parallel L0 soft index keyed by
// (prevValue, headReading, word) feeds userScore() into the walk DP as
// mu_user * userScore. Count threshold + decay; L1 backoff is reserved
// (beta1 = 0). Soft evidence is derived from the same observe() stream and
// can be persisted to a private user-data file (never bundled / never git).
class UserOverrideModel {
 public:
  // Soft-score policy (Johnny-approved §6).
  static constexpr size_t kMinSoftCount = 2;
  static constexpr double kSoftScoreCap = 4.0;
  static constexpr double kBeta1 = 0.0;  // L1 reserved, disabled
  static constexpr double kDefaultMuUser = 4.0;
  // Fully decay after ~20 half-lives (same spirit as the hard-path Score).
  static constexpr double kDecayThreshold = 1.0 / 1048576.0;

  UserOverrideModel(size_t capacity, double decayConstant);

  struct Suggestion {
    Suggestion() = default;
    Suggestion(std::string c, bool f)
        : candidate(std::move(c)), forceHighScoreOverride(f) {}
    std::string candidate;
    bool forceHighScoreOverride = false;

    [[nodiscard]] bool empty() const { return candidate.empty(); }
  };

  void observe(const Formosa::Gramambular2::ReadingGrid::WalkResult&
                   walkBeforeUserOverride,
               const Formosa::Gramambular2::ReadingGrid::WalkResult&
                   walkAfterUserOverride,
               size_t cursor, double timestamp);

  Suggestion suggest(
      const Formosa::Gramambular2::ReadingGrid::WalkResult& currentWalk,
      size_t cursor, double timestamp);

  void observe(const std::string& key, const std::string& candidate,
               double timestamp, bool forceHighScoreOverride = false);

  Suggestion suggest(const std::string& key, double timestamp);

  // Explicit soft-index bump (also called from walk-based observe). Safe for
  // unit harnesses that do not go through FormObservationKey.
  void noteSoftObservation(const std::string& prevValue,
                           const std::string& headReading,
                           const std::string& word, double timestamp);

  // Soft score for DP: min(kSoftScoreCap, log(1+count)) * decay, or 0 if
  // count < kMinSoftCount or fully decayed. L1 backoff is reserved (returns
  // 0 when L0 misses; beta1 = 0).
  [[nodiscard]] double userScore(const std::string& prevValue,
                                 const std::string& headReading,
                                 const std::string& word,
                                 double timestamp) const;

  // True if any L0 soft entry would currently return a positive userScore.
  // Used by KeyHandler: never attach a user-only ContextModel when this is
  // false (cold empty must stay on the fast path for bit-identical tw Guard).
  [[nodiscard]] bool hasUsableSoftEvidence(double timestamp) const;

  [[nodiscard]] bool empty() const { return lruList_.empty(); }
  [[nodiscard]] size_t size() const { return lruList_.size(); }

  // Text format v1 persistence (atomic write via tmp + rename). Returns false
  // on I/O failure; corrupt lines are skipped rather than fatal.
  bool save(const std::string& path) const;
  bool load(const std::string& path);

  // Test / harness helpers.
  void clear();
  [[nodiscard]] double decayExponent() const { return decayExponent_; }

 private:
  struct Override {
    size_t count = 0;
    double timestamp = 0;
    bool forceHighScoreOverride = false;
  };

  struct Observation {
    size_t count;
    std::map<std::string, Override> overrides;

    Observation() : count(0) {}
    void update(const std::string& candidate, double timestamp,
                bool forceHighScoreOverride);
  };

  struct SoftEntry {
    size_t count = 0;
    double timestamp = 0;
  };

  typedef std::pair<std::string, Observation> KeyObservationPair;

  void rebuildSoftIndex();
  static std::string SoftL0Key(const std::string& prevValue,
                               const std::string& headReading,
                               const std::string& word);
  static bool ParseObservationKey(const std::string& key,
                                  std::string* prevValue,
                                  std::string* headReading);
  static double DecayWeight(double eventTimestamp, double timestamp,
                            double decayExponent);

  size_t capacity_;
  double decayExponent_;
  std::list<KeyObservationPair> lruList_;
  std::map<std::string, std::list<KeyObservationPair>::iterator> lruMap_;
  // L0: prevValue \t headReading \t word -> counts. Rebuilt from LRU; also
  // updated incrementally by noteSoftObservation.
  std::unordered_map<std::string, SoftEntry> softL0_;
};

}  // namespace McBopomofo

#endif  // SRC_ENGINE_USEROVERRIDEMODEL_H_
