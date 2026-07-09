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
//

#include "UserOverrideModel.h"

#include <cassert>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <list>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include "gramambular2/reading_grid.h"

namespace McBopomofo {

static constexpr char kEmptyNodeString[] = "()";
static constexpr char kCacheMagic[] = "laowang-uom-cache-v1";

// Hard-path suggest score (unchanged): balances recent-vs-frequent.
static double Score(size_t eventCount, size_t totalCount, double eventTimestamp,
                    double timestamp, double lambda);

// Form the observation key from a walk. Walks backward from head for up to
// two preceding nodes. Values come from WalkResult::chosenValueAt so that a
// ContextModel DP choice matches what the user saw (§1.2).
static std::string FormObservationKey(
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walk,
    std::vector<Formosa::Gramambular2::ReadingGrid::NodePtr>::const_iterator
        head);

static std::string CombineReadingValue(const std::string& reading,
                                       const std::string& value);
static bool IsPunctuation(
    const Formosa::Gramambular2::ReadingGrid::NodePtr& node);

UserOverrideModel::UserOverrideModel(size_t capacity, double decayConstant)
    : capacity_(capacity) {
  assert(capacity_ > 0);
  // NOLINTNEXTLINE(readability-magic-numbers)
  decayExponent_ = log(0.5) / decayConstant;
}

void UserOverrideModel::observe(
    const Formosa::Gramambular2::ReadingGrid::WalkResult&
        walkBeforeUserOverride,
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walkAfterUserOverride,
    size_t cursor, double timestamp) {
  if (walkBeforeUserOverride.nodes.empty() ||
      walkAfterUserOverride.nodes.empty()) {
    return;
  }

  if (walkBeforeUserOverride.totalReadings !=
      walkAfterUserOverride.totalReadings) {
    return;
  }

  size_t actualCursor = 0;
  auto currentNodeIt = walkAfterUserOverride.findNodeAt(cursor, &actualCursor);
  if (currentNodeIt == walkAfterUserOverride.nodes.cend()) {
    return;
  }

  if ((*currentNodeIt)->spanningLength() > 3) {
    return;
  }

  if (actualCursor == 0) {
    return;
  }
  --actualCursor;
  auto prevHeadNodeIt = walkBeforeUserOverride.findNodeAt(actualCursor);
  if (prevHeadNodeIt == walkBeforeUserOverride.nodes.cend()) {
    return;
  }

  // Cases (1)(2)(3): same as upstream UOM — which walk anchors the key and
  // whether forceHighScoreOverride is recommended. See historical comments.
  const auto& currentNode = *currentNodeIt;
  const auto& prevHeadNode = *prevHeadNodeIt;
  bool forceHighScoreOverride =
      currentNode->spanningLength() > prevHeadNode->spanningLength();
  bool breakingUp =
      currentNode->spanningLength() == 1 && prevHeadNode->spanningLength() > 1;

  const auto& keyWalk =
      breakingUp ? walkAfterUserOverride : walkBeforeUserOverride;
  auto nodeIter = breakingUp ? currentNodeIt : prevHeadNodeIt;

  std::string key = FormObservationKey(keyWalk, nodeIter);
  const std::string candidate = currentNode->currentUnigram().value();
  // observe() rebuilds the L0 soft index from observation keys (prev value +
  // head reading parsed out of the key + candidate). Do not also call
  // noteSoftObservation here or counts would double.
  observe(key, candidate, timestamp, forceHighScoreOverride);
}

UserOverrideModel::Suggestion UserOverrideModel::suggest(
    const Formosa::Gramambular2::ReadingGrid::WalkResult& currentWalk,
    size_t cursor, double timestamp) {
  auto nodeIter = currentWalk.findNodeAt(cursor);
  if (nodeIter == currentWalk.nodes.cend()) {
    return UserOverrideModel::Suggestion{};
  }
  std::string key = FormObservationKey(currentWalk, nodeIter);
  return suggest(key, timestamp);
}

void UserOverrideModel::observe(const std::string& key,
                                const std::string& candidate, double timestamp,
                                bool forceHighScoreOverride) {
  auto mapIter = lruMap_.find(key);
  if (mapIter == lruMap_.end()) {
    auto keyValuePair = KeyObservationPair(key, Observation());
    Observation& observation = keyValuePair.second;
    observation.update(candidate, timestamp, forceHighScoreOverride);

    lruList_.push_front(keyValuePair);
    auto listIter = lruList_.begin();
    lruMap_.insert(
        std::pair<std::string, std::list<KeyObservationPair>::iterator>(
            key, listIter));

    if (lruList_.size() > capacity_) {
      auto lastKeyValuePair = lruList_.end();
      --lastKeyValuePair;
      const std::string evictedKey = lastKeyValuePair->first;
      lruMap_.erase(evictedKey);
      lruList_.pop_back();
      // Soft index is rebuilt below so eviction is reflected.
    }
  } else {
    auto listIter = mapIter->second;
    lruList_.splice(lruList_.begin(), lruList_, listIter);

    auto& keyValuePair = *listIter;
    Observation& observation = keyValuePair.second;
    observation.update(candidate, timestamp, forceHighScoreOverride);
  }

  // Keep soft index coherent with LRU (handles eviction + multi-key overlap).
  rebuildSoftIndex();
}

UserOverrideModel::Suggestion UserOverrideModel::suggest(const std::string& key,
                                                         double timestamp) {
  auto mapIter = lruMap_.find(key);
  if (mapIter == lruMap_.end()) {
    return UserOverrideModel::Suggestion{};
  }

  auto listIter = mapIter->second;
  auto& keyValuePair = *listIter;
  const Observation& observation = keyValuePair.second;

  std::string candidate;
  bool forceHighScoreOverride = false;
  double score = 0;
  for (auto i = observation.overrides.begin(); i != observation.overrides.end();
       ++i) {
    const Override& o = i->second;
    double overrideScore = Score(o.count, observation.count, o.timestamp,
                                 timestamp, decayExponent_);
    if (overrideScore == 0.0) {
      continue;
    }

    if (overrideScore > score) {
      candidate = i->first;
      forceHighScoreOverride = o.forceHighScoreOverride;
      score = overrideScore;
    }
  }
  return UserOverrideModel::Suggestion{candidate, forceHighScoreOverride};
}

void UserOverrideModel::noteSoftObservation(const std::string& prevValue,
                                            const std::string& headReading,
                                            const std::string& word,
                                            double timestamp) {
  if (headReading.empty() || word.empty()) {
    return;
  }
  const std::string sk = SoftL0Key(prevValue, headReading, word);
  SoftEntry& e = softL0_[sk];
  e.count += 1;
  e.timestamp = timestamp;
}

double UserOverrideModel::userScore(const std::string& prevValue,
                                    const std::string& headReading,
                                    const std::string& word,
                                    double timestamp) const {
  if (headReading.empty() || word.empty()) {
    return 0.0;
  }
  // L0 exact.
  auto it = softL0_.find(SoftL0Key(prevValue, headReading, word));
  if (it != softL0_.end()) {
    const SoftEntry& e = it->second;
    if (e.count >= kMinSoftCount) {
      double decay = DecayWeight(e.timestamp, timestamp, decayExponent_);
      if (decay > 0.0) {
        double raw = std::log(1.0 + static_cast<double>(e.count));
        if (raw > kSoftScoreCap) {
          raw = kSoftScoreCap;
        }
        return raw * decay;
      }
    }
  }

  // L1 backoff reserved (beta1 = 0): do not consult coarser keys.
  (void)kBeta1;
  return 0.0;
}

bool UserOverrideModel::hasUsableSoftEvidence(double timestamp) const {
  for (const auto& entry : softL0_) {
    const SoftEntry& e = entry.second;
    if (e.count < kMinSoftCount) {
      continue;
    }
    if (DecayWeight(e.timestamp, timestamp, decayExponent_) > 0.0) {
      return true;
    }
  }
  return false;
}

void UserOverrideModel::clear() {
  lruList_.clear();
  lruMap_.clear();
  softL0_.clear();
}

bool UserOverrideModel::save(const std::string& path) const {
  const std::string tmpPath = path + ".tmp";
  std::ofstream out(tmpPath, std::ios::binary | std::ios::trunc);
  if (!out) {
    return false;
  }
  out << "# " << kCacheMagic << "\n";
  out << "# capacity=" << capacity_ << "\n";
  out << "# columns: key\\tcandidate\\tcand_count\\tobs_count\\ttimestamp\\t"
         "force(0|1)\n";
  out << "# LRU order: first data line = MRU\n";

  for (const auto& pair : lruList_) {
    const std::string& key = pair.first;
    const Observation& obs = pair.second;
    for (const auto& ov : obs.overrides) {
      out << key << '\t' << ov.first << '\t' << ov.second.count << '\t'
          << obs.count << '\t' << ov.second.timestamp << '\t'
          << (ov.second.forceHighScoreOverride ? 1 : 0) << '\n';
    }
  }
  out.close();
  if (!out) {
    return false;
  }
  if (std::rename(tmpPath.c_str(), path.c_str()) != 0) {
    std::remove(tmpPath.c_str());
    return false;
  }
  return true;
}

bool UserOverrideModel::load(const std::string& path) {
  std::ifstream in(path);
  if (!in) {
    return false;
  }
  clear();

  // Collect in file order (MRU first); insert so final list front = first line.
  struct Row {
    std::string key;
    std::string candidate;
    size_t candCount = 0;
    size_t obsCount = 0;
    double timestamp = 0;
    bool force = false;
  };
  std::vector<Row> rows;
  std::string line;
  while (std::getline(in, line)) {
    if (!line.empty() && line.back() == '\r') {
      line.pop_back();
    }
    if (line.empty() || line[0] == '#') {
      continue;
    }
    std::vector<std::string> cols;
    std::string col;
    std::istringstream ss(line);
    while (std::getline(ss, col, '\t')) {
      cols.push_back(col);
    }
    if (cols.size() < 6) {
      continue;
    }
    Row r;
    r.key = cols[0];
    r.candidate = cols[1];
    try {
      r.candCount = static_cast<size_t>(std::stoul(cols[2]));
      r.obsCount = static_cast<size_t>(std::stoul(cols[3]));
      r.timestamp = std::stod(cols[4]);
      r.force = (std::stoi(cols[5]) != 0);
    } catch (...) {
      continue;
    }
    if (r.key.empty() || r.candidate.empty() || r.candCount == 0) {
      continue;
    }
    rows.push_back(std::move(r));
  }

  // Replay MRU→LRU into observe-like structure without soft double-count:
  // build LRU then rebuildSoftIndex once.
  // Inserting front for each MRU-first row would reverse order; so walk
  // reverse (LRU first) and push_front, or walk MRU-first and push_back then
  // fix. Easiest: process rows reverse and push_front.
  for (auto it = rows.rbegin(); it != rows.rend(); ++it) {
    const Row& r = *it;
    auto mapIter = lruMap_.find(r.key);
    if (mapIter == lruMap_.end()) {
      KeyObservationPair kop(r.key, Observation());
      kop.second.count = r.obsCount;
      Override o;
      o.count = r.candCount;
      o.timestamp = r.timestamp;
      o.forceHighScoreOverride = r.force;
      kop.second.overrides[r.candidate] = o;
      lruList_.push_front(std::move(kop));
      lruMap_[r.key] = lruList_.begin();
    } else {
      auto listIter = mapIter->second;
      // Touch toward front to preserve relative MRU among keys as we go.
      lruList_.splice(lruList_.begin(), lruList_, listIter);
      Observation& obs = listIter->second;
      if (r.obsCount > obs.count) {
        obs.count = r.obsCount;
      }
      Override& o = obs.overrides[r.candidate];
      o.count = r.candCount;
      o.timestamp = r.timestamp;
      o.forceHighScoreOverride = r.force;
    }
    while (lruList_.size() > capacity_) {
      auto last = lruList_.end();
      --last;
      lruMap_.erase(last->first);
      lruList_.pop_back();
    }
  }

  rebuildSoftIndex();
  return true;
}

void UserOverrideModel::Observation::update(const std::string& candidate,
                                            double timestamp,
                                            bool forceHighScoreOverride) {
  count++;
  auto& o = overrides[candidate];
  o.timestamp = timestamp;
  o.count++;
  o.forceHighScoreOverride = forceHighScoreOverride;
}

void UserOverrideModel::rebuildSoftIndex() {
  softL0_.clear();
  for (const auto& pair : lruList_) {
    std::string prevValue;
    std::string headReading;
    if (!ParseObservationKey(pair.first, &prevValue, &headReading)) {
      continue;
    }
    for (const auto& ov : pair.second.overrides) {
      const std::string sk = SoftL0Key(prevValue, headReading, ov.first);
      SoftEntry& e = softL0_[sk];
      e.count += ov.second.count;
      if (ov.second.timestamp > e.timestamp) {
        e.timestamp = ov.second.timestamp;
      }
    }
  }
}

std::string UserOverrideModel::SoftL0Key(const std::string& prevValue,
                                         const std::string& headReading,
                                         const std::string& word) {
  return prevValue + "\t" + headReading + "\t" + word;
}

bool UserOverrideModel::ParseObservationKey(const std::string& key,
                                            std::string* prevValue,
                                            std::string* headReading) {
  // Key = ant + "-" + prev + "-" + head, each "()" or "(reading,value)".
  std::vector<std::string> parts;
  size_t i = 0;
  while (i < key.size() && parts.size() < 3) {
    if (key.compare(i, 2, kEmptyNodeString) == 0) {
      parts.emplace_back(kEmptyNodeString);
      i += 2;
    } else if (key[i] == '(') {
      size_t end = key.find(')', i);
      if (end == std::string::npos) {
        return false;
      }
      parts.push_back(key.substr(i, end - i + 1));
      i = end + 1;
    } else {
      return false;
    }
    if (i < key.size() && key[i] == '-') {
      ++i;
    }
  }
  if (parts.size() != 3) {
    return false;
  }
  // prev = parts[1], head = parts[2]
  auto parsePair = [](const std::string& p, std::string* reading,
                      std::string* value) -> bool {
    if (p == kEmptyNodeString) {
      if (reading) {
        reading->clear();
      }
      if (value) {
        value->clear();
      }
      return true;
    }
    if (p.size() < 3 || p.front() != '(' || p.back() != ')') {
      return false;
    }
    size_t comma = p.find(',');
    if (comma == std::string::npos) {
      return false;
    }
    if (reading) {
      *reading = p.substr(1, comma - 1);
    }
    if (value) {
      *value = p.substr(comma + 1, p.size() - comma - 2);
    }
    return true;
  };

  std::string prevReadingUnused;
  if (!parsePair(parts[1], &prevReadingUnused, prevValue)) {
    return false;
  }
  std::string headValueUnused;
  if (!parsePair(parts[2], headReading, &headValueUnused)) {
    return false;
  }
  return true;
}

double UserOverrideModel::DecayWeight(double eventTimestamp, double timestamp,
                                      double decayExponent) {
  double decay = exp((timestamp - eventTimestamp) * decayExponent);
  if (decay < kDecayThreshold) {
    return 0.0;
  }
  return decay;
}

static double Score(size_t eventCount, size_t totalCount, double eventTimestamp,
                    double timestamp, double lambda) {
  double decay = exp((timestamp - eventTimestamp) * lambda);
  if (decay < UserOverrideModel::kDecayThreshold) {
    return 0.0;
  }

  double prob =
      static_cast<double>(eventCount) / static_cast<double>(totalCount);
  return prob * decay;
}

static std::string CombineReadingValue(const std::string& reading,
                                       const std::string& value) {
  return std::string("(") + reading + "," + value + ")";
}

static bool IsPunctuation(
    const Formosa::Gramambular2::ReadingGrid::NodePtr& node) {
  const std::string& reading = node->reading();
  return !reading.empty() && reading[0] == '_';
}

static std::string FormObservationKey(
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walk,
    std::vector<Formosa::Gramambular2::ReadingGrid::NodePtr>::const_iterator
        head) {
  if (walk.nodes.empty() || head == walk.nodes.cend()) {
    return std::string(kEmptyNodeString) + "-" + kEmptyNodeString + "-" +
           kEmptyNodeString;
  }

  auto begin = walk.nodes.cbegin();
  size_t headIndex = static_cast<size_t>(std::distance(begin, head));

  std::string headStr = CombineReadingValue((*head)->reading(),
                                            walk.chosenValueAt(headIndex));

  std::string prevStr;
  bool prevIsPunctuation = false;
  if (head != begin) {
    --head;
    size_t prevIndex = static_cast<size_t>(std::distance(begin, head));
    prevIsPunctuation = IsPunctuation(*head);
    if (prevIsPunctuation) {
      prevStr = kEmptyNodeString;
    } else {
      prevStr = CombineReadingValue((*head)->reading(),
                                    walk.chosenValueAt(prevIndex));
    }
  } else {
    prevStr = kEmptyNodeString;
  }

  std::string anteriorStr;
  if (head != begin && !prevIsPunctuation) {
    --head;
    size_t anteriorIndex = static_cast<size_t>(std::distance(begin, head));
    if (IsPunctuation(*head)) {
      anteriorStr = kEmptyNodeString;
    } else {
      anteriorStr = CombineReadingValue((*head)->reading(),
                                        walk.chosenValueAt(anteriorIndex));
    }
  } else {
    anteriorStr = kEmptyNodeString;
  }

  return anteriorStr + "-" + prevStr + "-" + headStr;
}

}  // namespace McBopomofo
