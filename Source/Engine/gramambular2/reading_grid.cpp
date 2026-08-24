// Copyright (c) 2022 and onwards Lukhnos Liu.
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

#include "reading_grid.h"

#include <algorithm>
#include <chrono>
#include <limits>
#include <memory>
#include <stack>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace Formosa::Gramambular2 {

void ReadingGrid::clear() {
  cursor_ = 0;
  readings_.clear();
  spans_.clear();
}

void ReadingGrid::setCursor(size_t cursor) {
  assert(cursor <= readings_.size());
  cursor_ = cursor;
}

void ReadingGrid::setReadingSeparator(const std::string& separator) {
  separator_ = separator;
}

bool ReadingGrid::insertReading(const std::string& reading) {
  if (reading.empty() || reading == separator_) {
    return false;
  }

  if (!lm_.hasUnigrams(reading)) {
    return false;
  }

  readings_.insert(readings_.begin() + static_cast<ptrdiff_t>(cursor_),
                   reading);
  expandGridAt(cursor_);
  update();

  // Cursor must only move after update().
  ++cursor_;
  return true;
}

bool ReadingGrid::deleteReadingBeforeCursor() {
  if (!cursor_) {
    return false;
  }

  readings_.erase(readings_.begin() + static_cast<ptrdiff_t>(cursor_ - 1),
                  readings_.begin() + static_cast<ptrdiff_t>(cursor_));
  // Cursor must decrement for grid-shrinking and update to work.
  --cursor_;
  shrinkGridAt(cursor_);
  update();
  return true;
}

bool ReadingGrid::deleteReadingAfterCursor() {
  if (cursor_ == readings_.size()) {
    return false;
  }

  readings_.erase(readings_.begin() + static_cast<ptrdiff_t>(cursor_),
                  readings_.begin() + static_cast<ptrdiff_t>(cursor_ + 1));
  shrinkGridAt(cursor_);
  update();
  return true;
}

std::optional<ReadingGrid::NodePtr> ReadingGrid::findInSpan(
    size_t cursor, const std::function<bool(const NodePtr&)>& predicate) const {
  assert(cursor <= readings_.size());
  std::vector<ReadingGrid::NodeInSpan> nodes =
      overlappingNodesAt(cursor == readings_.size() ? cursor - 1 : cursor);

  auto nodesIt = std::find_if(
      nodes.cbegin(), nodes.cend(),
      [&](const NodeInSpan& nodeInSpan) { return predicate(nodeInSpan.node); });

  return nodesIt == nodes.end()
             ? std::nullopt
             : std::optional<ReadingGrid::NodePtr>(nodesIt->node);
}

namespace {

std::string Join(const std::vector<std::string>& v) {
  std::string s;
  for (const auto& x : v) s += x;
  return s;
}


int64_t GetEpochNowInMicroseconds() {
  auto now = std::chrono::system_clock::now();
  int64_t timestamp =
      std::chrono::time_point_cast<std::chrono::microseconds>(now)
          .time_since_epoch()
          .count();
  return timestamp;
}

}  // namespace

// Find the weightiest path in the grid graph. The path represents the most
// likely hidden chain of events from the observations.
// We use the Viterbi algorithm to compute such path.
// Instead of computing the path with the shortest distance, though, we compute
// the path with the longest distance (so the weightiest), since with log
// probability a larger value means a larger probability. The algorithm runs in
// O(|V| + |E|) time for G = (V, E) where G is a DAG. This means the walk is
// fairly economical even when the grid is large.
//
// Full expert design: when contextModel_ is present, we expand the state
// to consider different unigram choices inside nodes. This lets bigram/higher
// context participate in the actual path selection during the DP (not post-fix).
ReadingGrid::WalkResult ReadingGrid::walk() {
  WalkResult result;
  if (spans_.empty()) {
    return result;
  }
  int64_t start = GetEpochNowInMicroseconds();

  const size_t readingLen = readings_.size();

  if (!contextModel_) {
    // Original fast path, unchanged
    struct State {
      size_t fromIndex = 0;
      ReadingGrid::NodePtr fromNode = nullptr;
      double maxScore = -std::numeric_limits<double>::infinity();
    };

    std::vector<State> viterbi(readingLen + 1);
    viterbi[0].maxScore = 0.0;

    size_t reachableStates = 0;
    size_t evaluatedEdges = 0;
    for (size_t i = 0; i < readingLen; ++i) {
      ++reachableStates;
      const ReadingGrid::Span& span = spans_[i];
      const size_t maxSpanLen = span.maxLength();
      for (size_t spanLen = 1; spanLen <= maxSpanLen; ++spanLen) {
        const ReadingGrid::NodePtr& node = span.nodeOf(spanLen);
        if (node == nullptr) continue;
        ++evaluatedEdges;
        double score = viterbi[i].maxScore + node->score();
        State& target = viterbi[i + spanLen];
        if (score > target.maxScore) {
          target.maxScore = score;
          target.fromNode = node;
          target.fromIndex = i;
        }
      }
    }
    result.vertices = reachableStates;
    result.edges = evaluatedEdges;

    size_t totalReadingLen = 0;
    for (size_t curr = readingLen; curr > 0; curr = viterbi[curr].fromIndex) {
      assert(viterbi[curr].fromNode != nullptr);
      totalReadingLen += viterbi[curr].fromNode->spanningLength();
      result.nodes.emplace_back(std::move(viterbi[curr].fromNode));
    }
    std::reverse(result.nodes.begin(), result.nodes.end());
    assert(totalReadingLen == readingLen);
    result.totalReadings = totalReadingLen;
    glueDictionaryPhrases(result);
    result.elapsedMicroseconds = GetEpochNowInMicroseconds() - start;
    return result;
  }

  // Expanded DP with a context model: an exact bigram Viterbi over the lattice.
  // State = (grid position, last chosen word). For every position we keep the
  // best-scoring path per distinct ending word (no lossy beam pruning), so with
  // an all-zero context model (e.g. lambda 0) this reproduces the unigram walk
  // above exactly; the context model only shifts which existing unigram wins by
  // scoring the transition into it. Only unigrams already present in a node are
  // ever considered, so the walk never generates text and never changes a
  // reading.
  struct Cell {
    double score = -std::numeric_limits<double>::infinity();
    size_t prevPos = 0;
    std::string prevWord;
    ReadingGrid::NodePtr node = nullptr;  // node that produced this cell's word
    size_t unigramIndex = 0;
  };

  std::vector<std::unordered_map<std::string, Cell>> dp(readingLen + 1);
  dp[0][std::string()] = Cell{0.0, 0, std::string(), nullptr, 0};

  size_t reachableStates = 0;
  size_t evaluatedEdges = 0;
  for (size_t i = 0; i < readingLen; ++i) {
    if (dp[i].empty()) continue;
    ++reachableStates;

    const ReadingGrid::Span& span = spans_[i];
    const size_t maxSpanLen = span.maxLength();

    for (size_t spanLen = 1; spanLen <= maxSpanLen; ++spanLen) {
      const ReadingGrid::NodePtr& node = span.nodeOf(spanLen);
      if (!node) continue;
      const auto& unigrams = node->unigrams();
      if (unigrams.empty()) continue;

      // When the user has overridden this node (e.g. hand-picked a candidate
      // from the menu), honor it exactly like the fast path does: only the
      // overridden unigram is walkable, and it carries node->score(), which
      // encodes kOverridingScore (or the top-unigram score) per the override
      // type. Without this the DP would re-pick by raw per-unigram score and
      // silently discard the user's selection (the v2.2.0 "selected candidate
      // does not commit" bug). Nodes without an override are unaffected: they
      // iterate every unigram with u.score() exactly as before.
      const bool nodeOverridden = node->isOverridden();
      const std::string overriddenValue =
          nodeOverridden ? node->value() : std::string();
      const double overriddenScore = node->score();

      // System readings (punctuation / letters) keep the score-ranked top
      // unigram only. ContextModel must not re-pick among equal-score
      // alternatives — that flipped Shift+, from ， to ︽ (and similar for
      // 。/letters) when EnableContextualWalk is on (v2.3.0 regression).
      // Unigrams are already score-sorted by ScoreRankedLanguageModel.
      const std::string& nodeReading = node->reading();
      const bool forceTopUnigramOnly =
          !nodeOverridden &&
          (nodeReading.rfind("_punctuation_", 0) == 0 ||
           nodeReading.rfind("_half_punctuation_", 0) == 0 ||
           nodeReading.rfind("_ctrl_punctuation_", 0) == 0 ||
           nodeReading.rfind("_letter_", 0) == 0);

      std::unordered_map<std::string, Cell>& target = dp[i + spanLen];
      for (const auto& entry : dp[i]) {
        const std::string& prevWord = entry.first;
        const Cell& cell = entry.second;
        for (size_t ui = 0; ui < unigrams.size(); ++ui) {
          if (forceTopUnigramOnly && ui != 0) {
            break;
          }
          const auto& u = unigrams[ui];
          if (nodeOverridden && u.value() != overriddenValue) {
            continue;
          }
          double state = 0.0;
          // Always ask the model (including sentence start / empty prev).
          // Corpus bigram returns 0 for empty prev; user soft may still score
          // via (prev="", reading, word). Models that ignore reading use the
          // default scoreWithReading → score path.
          double trans = contextModel_->scoreWithReading(
              prevWord, nodeReading, u.value(), state);
          double sc =
              cell.score + (nodeOverridden ? overriddenScore : u.score()) +
              trans;
          ++evaluatedEdges;
          auto it = target.find(u.value());
          if (it == target.end() || sc > it->second.score) {
            target[u.value()] = Cell{sc, i, prevWord, node, ui};
          }
        }
      }
    }
  }

  // Pick the best-scoring ending state, then backtrack through prevPos/prevWord.
  const Cell* bestCell = nullptr;
  double best = -std::numeric_limits<double>::infinity();
  for (const auto& entry : dp[readingLen]) {
    if (entry.second.score > best) {
      best = entry.second.score;
      bestCell = &entry.second;
    }
  }
  if (bestCell == nullptr) {
    result.elapsedMicroseconds = GetEpochNowInMicroseconds() - start;
    return result;
  }

  std::vector<const Cell*> path;
  for (const Cell* c = bestCell; c != nullptr && c->node != nullptr;) {
    path.push_back(c);
    auto& prevMap = dp[c->prevPos];
    auto it = prevMap.find(c->prevWord);
    c = (it == prevMap.end()) ? nullptr : &it->second;
  }
  std::reverse(path.begin(), path.end());

  size_t totalReadingLen = 0;
  result.selectedUnigramIndices.clear();
  for (const Cell* c : path) {
    result.nodes.push_back(c->node);
    result.selectedUnigramIndices.push_back(c->unigramIndex);
    totalReadingLen += c->node->spanningLength();
  }
  result.totalReadings = totalReadingLen;
  result.vertices = reachableStates;
  result.edges = evaluatedEdges;
  result.walkScore = best;
  result.elapsedMicroseconds = GetEpochNowInMicroseconds() - start;

  // Optional Mozc-style n-best + PathScorer fusion. When scorer is null or
  // nu==0 this branch is skipped → bit-identical to the single-best path above.
  if (pathScorer_ != nullptr && pathRerankNu_ != 0.0) {
    auto nbest = walkNBest(pathRerankNBest_);
    if (!nbest.empty()) {
      size_t bestIdx = 0;
      double bestFinal = -std::numeric_limits<double>::infinity();
      size_t bestNoAlphaIdx = 0;
      double bestNoAlpha = -std::numeric_limits<double>::infinity();
      std::vector<std::vector<std::string>> paths;
      paths.reserve(nbest.size());
      for (const auto& rp : nbest) paths.push_back(rp.words);
      std::vector<double> rnns = pathScorer_->scoreNBest(paths);
      for (size_t pi = 0; pi < nbest.size(); ++pi) {
        // 同音候選的頻率先驗壓縮（見 setConfusionAlphas 的說明）。
        // 對設定過 alpha 的讀音，把「非最高頻候選要付的頻率代價」折扣掉
        // (1-alpha)，讓 PathScorer 的上下文判斷不被頻率差淹沒。
        double adjust = 0.0;
        if (confusionAlphas_ != nullptr && !confusionAlphas_->empty()) {
          const RankedPath& rp = nbest[pi];
          for (size_t ni = 0; ni < rp.nodes.size(); ++ni) {
            // 只壓「單音節節點」。多字詞節點（現在／以前／作品）雖然讀音裡
            // 含目標音，但那是詞的一部分，候選之間的差異不是同音字混淆 ——
            // 壓它沒有意義，而且會改變整句路徑、傷到別的位置。
            // 2026-08-10 實測：不加這道限制，前/錢 −1.5、較/叫 −0.8。
            if (rp.nodes[ni]->spanningLength() != 1) continue;
            auto it = confusionAlphas_->find(rp.nodes[ni]->reading());
            if (it == confusionAlphas_->end() || it->second >= 1.0) continue;
            const auto& ug = rp.nodes[ni]->unigrams();
            if (ug.empty() || ni >= rp.selectedUnigramIndices.size()) continue;
            size_t sel = rp.selectedUnigramIndices[ni];
            if (sel >= ug.size()) continue;
            // ug[0] 是該節點最高頻候選；penalty ≤ 0
            double penalty = ug[sel].score() - ug[0].score();
            adjust += (1.0 - it->second) * -penalty;
          }
        }
        // 記軌跡時要知道「沒有壓縮的話誰會贏」，才分得出是重排還是壓縮造成的。
        if (decisionTrace_ != nullptr && decisionTrace_->enabled()) {
          double noAlpha = nbest[pi].walkScore + pathRerankNu_ * rnns[pi];
          if (noAlpha > bestNoAlpha) {
            bestNoAlpha = noAlpha;
            bestNoAlphaIdx = pi;
          }
        }
        double finalScore = nbest[pi].walkScore + adjust + pathRerankNu_ * rnns[pi];
        nbest[pi].pathScore = finalScore;
        if (finalScore > bestFinal) {
          bestFinal = finalScore;
          bestIdx = pi;
        }
      }
      if (decisionTrace_ != nullptr && decisionTrace_->enabled()) {
        // 誰換掉了 rank 0？分三種情況記，之後做錯誤分層時就不必事後猜。
        if (bestNoAlphaIdx != 0) {
          decisionTrace_->record(iBopomofo::DecisionTrace::kWholePath,
                                 Join(nbest[bestNoAlphaIdx].words),
                                 iBopomofo::DecisionTrace::Layer::kPathRerank,
                                 "rank0→rank" + std::to_string(bestNoAlphaIdx));
        }
        if (bestIdx != bestNoAlphaIdx) {
          decisionTrace_->record(iBopomofo::DecisionTrace::kWholePath,
                                 Join(nbest[bestIdx].words),
                                 iBopomofo::DecisionTrace::Layer::kConfusionAlpha,
                                 "rank" + std::to_string(bestNoAlphaIdx) + "→rank" +
                                     std::to_string(bestIdx));
        }
        if (bestIdx == 0 && bestNoAlphaIdx == 0) {
          decisionTrace_->record(iBopomofo::DecisionTrace::kWholePath,
                                 Join(nbest[0].words),
                                 iBopomofo::DecisionTrace::Layer::kContextModel, "rank0");
        }
      }
      const RankedPath& picked = nbest[bestIdx];
      result.nodes = picked.nodes;
      result.selectedUnigramIndices = picked.selectedUnigramIndices;
      result.walkScore = picked.walkScore;
      result.totalReadings = 0;
      for (const auto& n : result.nodes) {
        result.totalReadings += n->spanningLength();
      }
    }
  }

  glueDictionaryPhrases(result);
  result.elapsedMicroseconds = GetEpochNowInMicroseconds() - start;
  return result;
}

std::vector<ReadingGrid::RankedPath> ReadingGrid::walkNBest(size_t n) {
  std::vector<RankedPath> out;
  if (spans_.empty() || n == 0) {
    return out;
  }
  // N-best is defined under ContextModel DP. Without a model, only the single
  // unigram path exists (callers that need it can walk() separately).
  if (!contextModel_) {
    return out;
  }

  const size_t readingLen = readings_.size();
  const size_t K = kNBestHypK;

  struct Hyp {
    double score = -std::numeric_limits<double>::infinity();
    size_t prevPos = 0;
    std::string prevWord;
    size_t prevHypIndex = 0;
    ReadingGrid::NodePtr node = nullptr;
    size_t unigramIndex = 0;
    std::string word;
  };

  // dp[pos][lastWord] = up to K hyps ending there, sorted by score desc.
  std::vector<std::unordered_map<std::string, std::vector<Hyp>>> dp(
      readingLen + 1);
  {
    Hyp h0;
    h0.score = 0.0;
    h0.word = "";
    dp[0][std::string()].push_back(std::move(h0));
  }

  auto tryAdd = [K](std::vector<Hyp>& hyps, Hyp h) {
    hyps.push_back(std::move(h));
    std::stable_sort(hyps.begin(), hyps.end(),
                     [](const Hyp& a, const Hyp& b) { return a.score > b.score; });
    if (hyps.size() > K) {
      hyps.resize(K);
    }
  };

  for (size_t i = 0; i < readingLen; ++i) {
    if (dp[i].empty()) continue;
    const ReadingGrid::Span& span = spans_[i];
    const size_t maxSpanLen = span.maxLength();
    for (size_t spanLen = 1; spanLen <= maxSpanLen; ++spanLen) {
      const ReadingGrid::NodePtr& node = span.nodeOf(spanLen);
      if (!node) continue;
      const auto& unigrams = node->unigrams();
      if (unigrams.empty()) continue;

      const bool nodeOverridden = node->isOverridden();
      const std::string overriddenValue =
          nodeOverridden ? node->value() : std::string();
      const double overriddenScore = node->score();
      const std::string& nodeReading = node->reading();
      const bool forceTopUnigramOnly =
          !nodeOverridden &&
          (nodeReading.rfind("_punctuation_", 0) == 0 ||
           nodeReading.rfind("_half_punctuation_", 0) == 0 ||
           nodeReading.rfind("_ctrl_punctuation_", 0) == 0 ||
           nodeReading.rfind("_letter_", 0) == 0);

      auto& target = dp[i + spanLen];
      for (const auto& entry : dp[i]) {
        const std::string& prevWord = entry.first;
        const std::vector<Hyp>& prevHyps = entry.second;
        for (size_t phi = 0; phi < prevHyps.size(); ++phi) {
          const Hyp& ph = prevHyps[phi];
          for (size_t ui = 0; ui < unigrams.size(); ++ui) {
            if (forceTopUnigramOnly && ui != 0) break;
            const auto& u = unigrams[ui];
            if (nodeOverridden && u.value() != overriddenValue) continue;
            double state = 0.0;
            double trans = contextModel_->scoreWithReading(
                prevWord, nodeReading, u.value(), state);
            double sc =
                ph.score + (nodeOverridden ? overriddenScore : u.score()) +
                trans;
            Hyp nh;
            nh.score = sc;
            nh.prevPos = i;
            nh.prevWord = prevWord;
            nh.prevHypIndex = phi;
            nh.node = node;
            nh.unigramIndex = ui;
            nh.word = u.value();
            tryAdd(target[u.value()], std::move(nh));
          }
        }
      }
    }
  }

  // Collect ending hyps.
  struct EndRef {
    double score;
    std::string word;
    size_t hypIndex;
  };
  std::vector<EndRef> ends;
  for (const auto& entry : dp[readingLen]) {
    for (size_t hi = 0; hi < entry.second.size(); ++hi) {
      ends.push_back(EndRef{entry.second[hi].score, entry.first, hi});
    }
  }
  std::stable_sort(ends.begin(), ends.end(),
                   [](const EndRef& a, const EndRef& b) {
                     return a.score > b.score;
                   });

  std::unordered_set<std::string> seenJoined;
  for (const EndRef& er : ends) {
    if (out.size() >= n) break;
    // Backtrack.
    std::vector<const Hyp*> rev;
    size_t pos = readingLen;
    std::string word = er.word;
    size_t hi = er.hypIndex;
    while (pos > 0) {
      auto mit = dp[pos].find(word);
      if (mit == dp[pos].end() || hi >= mit->second.size()) break;
      const Hyp* h = &mit->second[hi];
      if (h->node == nullptr) break;
      rev.push_back(h);
      size_t ppos = h->prevPos;
      std::string pword = h->prevWord;
      size_t phi = h->prevHypIndex;
      pos = ppos;
      word = std::move(pword);
      hi = phi;
    }
    std::reverse(rev.begin(), rev.end());
    RankedPath rp;
    rp.walkScore = er.score;
    rp.pathScore = er.score;
    std::string joined;
    for (const Hyp* h : rev) {
      rp.nodes.push_back(h->node);
      rp.selectedUnigramIndices.push_back(h->unigramIndex);
      rp.words.push_back(h->word);
      joined += h->word;
    }
    if (joined.empty()) continue;
    if (!seenJoined.insert(joined).second) continue;
    out.push_back(std::move(rp));
  }
  return out;
}

std::vector<ReadingGrid::Candidate> ReadingGrid::candidatesAt(size_t loc) {
  std::vector<ReadingGrid::Candidate> result;
  if (readings_.empty()) {
    return result;
  }

  if (loc > readings_.size()) {
    return result;
  }

  std::vector<NodeInSpan> nodes =
      overlappingNodesAt(loc == readings_.size() ? loc - 1 : loc);

  // Sort nodes by reading length.
  std::stable_sort(
      nodes.begin(), nodes.end(), [](const auto& n1, const auto& n2) {
        return n1.node->spanningLength() > n2.node->spanningLength();
      });

  for (const NodeInSpan& nodeInSpan : nodes) {
    for (const LanguageModel::Unigram& unigram : nodeInSpan.node->unigrams()) {
      result.emplace_back(nodeInSpan.node->reading(), unigram.value(),
                          unigram.rawValue());
    }
  }
  return result;
}

bool ReadingGrid::overrideCandidate(
    size_t loc, const ReadingGrid::Candidate& candidate,
    ReadingGrid::Node::OverrideType overrideType) {
  return overrideCandidate(loc, &candidate.reading, candidate.value,
                           overrideType);
}

bool ReadingGrid::overrideCandidate(
    size_t loc, const std::string& candidate,
    ReadingGrid::Node::OverrideType overrideType) {
  return overrideCandidate(loc, nullptr, candidate, overrideType);
}

void ReadingGrid::glueDictionaryPhrases(WalkResult& result) const {
  if (result.nodes.size() < 2 || spans_.empty()) {
    return;
  }

  std::vector<NodePtr> newNodes;
  std::vector<size_t> newIdx;
  newNodes.reserve(result.nodes.size());
  newIdx.reserve(result.nodes.size());

  const bool hadIdx =
      result.selectedUnigramIndices.size() == result.nodes.size();
  size_t pos = 0;
  size_t i = 0;
  while (i < result.nodes.size()) {
    size_t run = 0;
    while (i + run < result.nodes.size()) {
      const NodePtr& n = result.nodes[i + run];
      if (n->spanningLength() != 1 || n->isOverridden()) {
        break;
      }
      ++run;
    }

    NodePtr glued;
    size_t gluedLen = 0;
    if (run >= 2 && pos < spans_.size()) {
      const Span& span = spans_[pos];
      const size_t maxLen = std::min(span.maxLength(), run);
      for (size_t len = maxLen; len >= 2; --len) {
        const NodePtr& p = span.nodeOf(len);
        if (p != nullptr && !p->unigrams().empty()) {
          glued = p;
          gluedLen = len;
          break;
        }
      }
    }

    if (glued) {
      newNodes.push_back(glued);
      newIdx.push_back(0);
      pos += gluedLen;
      i += gluedLen;
      continue;
    }

    newNodes.push_back(result.nodes[i]);
    newIdx.push_back(hadIdx ? result.selectedUnigramIndices[i] : 0);
    pos += result.nodes[i]->spanningLength();
    ++i;
  }

  if (newNodes.size() == result.nodes.size()) {
    return;
  }
  result.nodes = std::move(newNodes);
  result.selectedUnigramIndices = std::move(newIdx);
}

void ReadingGrid::expandGridAt(size_t loc) {
  if (!loc || loc == spans_.size()) {
    spans_.insert(spans_.begin() + static_cast<ptrdiff_t>(loc), Span());
    return;
  }
  spans_.insert(spans_.begin() + static_cast<ptrdiff_t>(loc), Span());
  removeAffectedNodes(loc);
}

void ReadingGrid::shrinkGridAt(size_t loc) {
  if (loc == spans_.size()) {
    return;
  }
  spans_.erase(spans_.begin() + static_cast<ptrdiff_t>(loc));
  removeAffectedNodes(loc);
}

void ReadingGrid::removeAffectedNodes(size_t loc) {
  // Because of the expansion, certain spans now have "broken" nodes. We need
  // to remove those. For example, before:
  //
  // Span index 0   1   2   3
  //                (---)
  //                (-------)
  //            (-----------)
  //
  // After we've inserted a span at 2:
  //
  // Span index 0   1   2   3   4
  //                (---)
  //                (----   ----)
  //            (--------   ----)
  //
  // Similarly for shrinkage, before:
  //
  // Span index 0   1   2   3
  //                (---)
  //                (-------)
  //            (-----------)
  //
  // After we've deleted the span at 2:
  //
  // Span index 0   1   2   3   4
  //                (---)
  //                XXXXX
  //            XXXXXXXXX
  //
  if (spans_.empty()) {
    return;
  }
  size_t affectedLength = kMaximumSpanLength - 1;
  size_t begin = loc <= affectedLength ? 0 : loc - affectedLength;
  size_t end = loc >= 1 ? loc - 1 : 0;
  for (size_t i = begin; i <= end; ++i) {
    spans_[i].removeNodesOfOrLongerThan(loc - i + 1);
  }
}

void ReadingGrid::insert(size_t loc, const ReadingGrid::NodePtr& node) {
  assert(loc < spans_.size());
  spans_[loc].add(node);
}

std::string ReadingGrid::combineReading(
    std::vector<std::string>::const_iterator begin,
    std::vector<std::string>::const_iterator end) {
  std::string result;
  for (auto iter = begin; iter != end;) {
    result += *iter;
    ++iter;
    if (iter != end) {
      result += separator_;
    }
  }
  return result;
}

bool ReadingGrid::hasNodeAt(size_t loc, size_t readingLen,
                            const std::string& reading) {
  if (loc > spans_.size()) {
    return false;
  }
  const NodePtr& n = spans_[loc].nodeOf(readingLen);
  if (n == nullptr) {
    return false;
  }
  return reading == n->reading();
}

void ReadingGrid::update() {
  size_t begin =
      (cursor_ <= kMaximumSpanLength) ? 0 : cursor_ - kMaximumSpanLength;
  size_t end = cursor_ + kMaximumSpanLength;
  end = std::min(end, readings_.size());

  for (size_t pos = begin; pos < end; pos++) {
    for (size_t len = 1; len <= kMaximumSpanLength && pos + len <= end; len++) {
      std::string combinedReading =
          combineReading(readings_.begin() + static_cast<ptrdiff_t>(pos),
                         readings_.begin() + static_cast<ptrdiff_t>(pos + len));

      if (!hasNodeAt(pos, len, combinedReading)) {
        auto unigrams = lm_.getUnigrams(combinedReading);
        if (unigrams.empty()) {
          continue;
        }

        insert(pos, std::make_shared<Node>(combinedReading, len, unigrams));
      }
    }
  }
}

bool ReadingGrid::overrideCandidate(
    size_t loc, const std::string* reading, const std::string& value,
    ReadingGrid::Node::OverrideType overrideType) {
  if (loc > readings_.size()) {
    return false;
  }

  std::vector<NodeInSpan> overlappingNodes =
      overlappingNodesAt(loc == readings_.size() ? loc - 1 : loc);
  NodeInSpan overridden;
  for (NodeInSpan& nis : overlappingNodes) {
    if (reading != nullptr && nis.node->reading() != *reading) {
      continue;
    }

    if (nis.node->selectOverrideUnigram(value, overrideType)) {
      overridden = nis;
      break;
    }
  }

  if (overridden.node == nullptr) {
    // Nothing gets overridden.
    return false;
  }

  for (size_t i = overridden.spanIndex;
       i < overridden.spanIndex + overridden.node->spanningLength() &&
       i < spans_.size();
       ++i) {
    // We also need to reset *all* nodes that share the same location in the
    // span. For example, if previously the two walked nodes are "A BC" where
    // A and BC are two nodes with overrides. The user now chooses "DEF" which
    // is a node that shares the same span location with "A". The node with BC
    // will be reset as it's part of the overlapping node, but A is not.
    std::vector<NodeInSpan> nodes = overlappingNodesAt(i);
    for (NodeInSpan& nis : nodes) {
      if (nis.node != overridden.node) {
        nis.node->reset();
      }
    }
  }
  return true;
}

std::vector<ReadingGrid::NodeInSpan> ReadingGrid::overlappingNodesAt(
    size_t loc) const {
  std::vector<ReadingGrid::NodeInSpan> results;

  if (spans_.empty() || loc >= spans_.size()) {
    return results;
  }

  // First, get all nodes from the span at location.
  for (size_t i = 1, len = spans_[loc].maxLength(); i <= len; ++i) {
    NodePtr ptr = spans_[loc].nodeOf(i);
    if (ptr != nullptr) {
      ReadingGrid::NodeInSpan element{std::move(ptr), loc};
      results.emplace_back(std::move(element));
    }
  }

  size_t begin = loc - std::min(loc, kMaximumSpanLength - 1);
  for (size_t i = begin; i < loc; ++i) {
    size_t beginLen = loc - i + 1;
    size_t endLen = spans_[i].maxLength();
    for (size_t j = beginLen; j <= endLen; ++j) {
      NodePtr ptr = spans_[i].nodeOf(j);
      if (ptr != nullptr) {
        ReadingGrid::NodeInSpan element{std::move(ptr), i};
        results.emplace_back(std::move(element));
      }
    }
  }

  return results;
}

LanguageModel::Unigram ReadingGrid::Node::currentUnigram() const {
  return unigrams_.empty() ? LanguageModel::Unigram{} : *unigramIter_;
}

std::string ReadingGrid::Node::value() const {
  return unigrams_.empty() ? "" : unigramIter_->value();
}

double ReadingGrid::Node::score() const {
  if (unigrams_.empty()) {
    return 0;
  }

  switch (overrideType_) {
    case OverrideType::kOverrideValueWithHighScore:
      return kOverridingScore;
    case OverrideType::kOverrideValueWithScoreFromTopUnigram:
      return unigrams_[0].score();
    case OverrideType::kNone:
    default:
      return unigramIter_->score();
  }
}

bool ReadingGrid::Node::isOverridden() const {
  return overrideType_ != OverrideType::kNone;
}

void ReadingGrid::Node::reset() {
  unigramIter_ = unigrams_.begin();
  overrideType_ = OverrideType::kNone;
}

bool ReadingGrid::Node::selectOverrideUnigram(
    const std::string& value, ReadingGrid::Node::OverrideType type) {
  assert(type != ReadingGrid::Node::OverrideType::kNone);
  for (auto it = unigrams_.begin(), end = unigrams_.end(); it != end; ++it) {
    if (value == it->value()) {
      unigramIter_ = it;
      overrideType_ = type;
      return true;
    }
  }
  return false;
}

std::vector<ReadingGrid::NodePtr>::const_iterator
ReadingGrid::WalkResult::findNodeAt(size_t cursor,
                                    size_t* outCursorPastNode) const {
  if (nodes.empty()) {
    return nodes.cend();
  }

  if (cursor > totalReadings) {
    return nodes.cend();
  }

  if (cursor == 0) {
    auto it = nodes.cbegin();
    if (outCursorPastNode != nullptr) {
      *outCursorPastNode = (*it)->spanningLength();
    }
    return it;
  }

  // Covers both the "cursor is right at end" and "cursor is one reading before
  // the end" cases.
  if (cursor >= totalReadings - 1) {
    if (outCursorPastNode != nullptr) {
      *outCursorPastNode = totalReadings;
    }
    return std::next(nodes.cbegin(), static_cast<ptrdiff_t>(nodes.size() - 1));
  }

  size_t accumulated = 0;
  for (auto i = nodes.cbegin(); i != nodes.cend(); ++i) {
    accumulated += (*i)->spanningLength();
    if (accumulated > cursor) {
      if (outCursorPastNode != nullptr) {
        *outCursorPastNode = accumulated;
      }
      return i;
    }
  }

  // Shouldn't happen.
  return nodes.cend();
}

std::vector<std::string> ReadingGrid::WalkResult::valuesAsStrings() const {
  std::vector<std::string> result;
  for (const NodePtr& node : nodes) {
    result.emplace_back(node->value());
  }
  return result;
}

std::vector<std::string> ReadingGrid::WalkResult::readingsAsStrings() const {
  std::vector<std::string> result;
  for (const NodePtr& node : nodes) {
    result.emplace_back(node->reading());
  }
  return result;
}

std::string ReadingGrid::WalkResult::chosenValueAt(size_t i) const {
  if (i >= nodes.size()) {
    return "";
  }
  const NodePtr& node = nodes[i];
  // Post-walk overrides (hand-picked candidate, soft neural reselect via
  // node override) must beat ContextModel DP indices. Without this, a neural
  // soft override after a contextual walk updates node->value() but the UI
  // still reads the stale DP pick from selectedUnigramIndices — n-gram walk
  // and RNN layer never compose. Pre-walk overrides are already baked into
  // the DP's selectedUnigramIndices (override collapses the candidate set).
  if (node->isOverridden()) {
    return node->value();
  }
  if (selectedUnigramIndices.size() == nodes.size()) {
    size_t idx = selectedUnigramIndices[i];
    const auto& unigrams = node->unigrams();
    if (idx < unigrams.size()) {
      return unigrams[idx].value();
    }
  }
  return node->value();
}

bool ReadingGrid::WalkResult::reselectUnigramValue(size_t nodeIndex,
                                                   const std::string& value) {
  if (nodeIndex >= nodes.size() || value.empty()) {
    return false;
  }
  const NodePtr& node = nodes[nodeIndex];
  const auto& unigrams = node->unigrams();
  size_t found = unigrams.size();
  for (size_t ui = 0; ui < unigrams.size(); ++ui) {
    if (unigrams[ui].value() == value) {
      found = ui;
      break;
    }
  }
  if (found >= unigrams.size()) {
    return false;
  }

  // Ensure indices are parallel to nodes so future chosenValueAt reads DP
  // (or reselect) choices rather than silently falling back mid-path.
  if (selectedUnigramIndices.size() != nodes.size()) {
    selectedUnigramIndices.assign(nodes.size(), 0);
    for (size_t j = 0; j < nodes.size(); ++j) {
      const auto& ugs = nodes[j]->unigrams();
      const std::string cur = nodes[j]->value();
      size_t idx = 0;
      for (size_t ui = 0; ui < ugs.size(); ++ui) {
        if (ugs[ui].value() == cur) {
          idx = ui;
          break;
        }
      }
      selectedUnigramIndices[j] = idx;
    }
  }
  selectedUnigramIndices[nodeIndex] = found;
  return true;
}

void ReadingGrid::Span::clear() {
  nodes_.fill(nullptr);
  maxLength_ = 0;
}

void ReadingGrid::Span::add(const ReadingGrid::NodePtr& node) {
  assert(node->spanningLength() > 0 &&
         node->spanningLength() <= kMaximumSpanLength);
  nodes_[node->spanningLength() - 1] = node;
  maxLength_ = std::max(maxLength_, node->spanningLength());
}

void ReadingGrid::Span::removeNodesOfOrLongerThan(size_t length) {
  assert(length > 0 && length <= kMaximumSpanLength);
  for (size_t i = length - 1; i < kMaximumSpanLength; ++i) {
    nodes_[i] = nullptr;
  }
  maxLength_ = 0;
  if (length == 1) {
    return;
  }

  size_t i = length - 2;
  while (true) {
    if (nodes_[i] != nullptr) {
      maxLength_ = i + 1;
      return;
    }

    if (i == 0) {
      return;
    }

    --i;
  }
}

const ReadingGrid::NodePtr& ReadingGrid::Span::nodeOf(size_t length) const {
  assert(length > 0 && length <= kMaximumSpanLength);
  return nodes_[length - 1];
}

std::vector<LanguageModel::Unigram>
ReadingGrid::ScoreRankedLanguageModel::getUnigrams(const std::string& reading) {
  auto unigrams = lm_->getUnigrams(reading);
  std::stable_sort(
      unigrams.begin(), unigrams.end(),
      [](const auto& u1, const auto& u2) { return u1.score() > u2.score(); });
  return unigrams;
}

bool ReadingGrid::ScoreRankedLanguageModel::hasUnigrams(
    const std::string& reading) {
  return lm_->hasUnigrams(reading);
}

}  // namespace Formosa::Gramambular2
