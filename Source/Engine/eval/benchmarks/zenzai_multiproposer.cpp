// Zenzai-style constrained lattice re-search harness v3 — (i) CondConverter.
//
// Proposer = dedicated CondConverterScorer:
//   scoreCandidate(left_context, reading, word) = log10 P(word|left,reading)
//   Trained on PTT + dictionary-aligned (context,reading)→word pairs.
//   NOT generic char-LM scoreContinuation; NOT n-gram; NOT synthetic.
//
// Selective trigger + modes: fusion | neural | hybrid | cond
//   cond = pick max pathCondScore among pool (sum of scoreCandidate along path)
//
// Usage:
//   zenzai_constrained_search sentences data bigrams lambda lstm.bin
//     cond.bin [max_bad] [max_props] [nu] [mode] [margin] [logp_thr]
//     [neural_gain]
//
// mode ∈ {fusion, neural, hybrid, cond}
// POC only — no release / no default flag change.

#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "CondConverterScorer.h"
#include "CorpusBigramContextModel.h"
#include "NeuralLMPathScorer.h"
#include "ParselessLM.h"
#include "gramambular2/reading_grid.h"

using Formosa::Gramambular2::ReadingGrid;
using iBopomofo::CondConverterScorer;
using iBopomofo::CorpusBigramContextModel;
using iBopomofo::NeuralLMPathScorer;
using iBopomofo::ParselessLM;

namespace {

std::vector<std::string> splitSyllables(const std::string& readings) {
  std::vector<std::string> result;
  size_t start = 0;
  for (size_t i = 0; i < readings.size(); ++i) {
    if (readings[i] == '-') {
      if (i > start) result.push_back(readings.substr(start, i - start));
      start = i + 1;
    }
  }
  if (start < readings.size()) result.push_back(readings.substr(start));
  return result;
}

ReadingGrid makeGrid(ParselessLM* lm) {
  ReadingGrid grid(std::shared_ptr<Formosa::Gramambular2::LanguageModel>(
      lm, [](Formosa::Gramambular2::LanguageModel*) {}));
  grid.setReadingSeparator("-");
  return grid;
}

bool feed(ReadingGrid& grid, const std::string& readings) {
  for (const auto& syl : splitSyllables(readings)) {
    grid.setCursor(grid.length());
    if (!grid.insertReading(syl)) return false;
  }
  return true;
}

std::vector<std::string> pathWords(const ReadingGrid::WalkResult& w) {
  std::vector<std::string> words;
  words.reserve(w.nodes.size());
  for (size_t i = 0; i < w.nodes.size(); ++i) {
    words.push_back(w.chosenValueAt(i));
  }
  return words;
}

std::string joined(const std::vector<std::string>& words) {
  std::string s;
  for (const auto& w : words) s += w;
  return s;
}

std::string joinedWalk(const ReadingGrid::WalkResult& w) {
  return joined(pathWords(w));
}

bool readingsFaithful(const ReadingGrid::WalkResult& w,
                      const std::vector<std::string>& syls,
                      const std::string& sep) {
  size_t pos = 0;
  for (const auto& node : w.nodes) {
    if (!node) return false;
    size_t span = node->spanningLength();
    if (span == 0 || pos + span > syls.size()) return false;
    std::string expected;
    for (size_t k = 0; k < span; ++k) {
      if (k) expected += sep;
      expected += syls[pos + k];
    }
    if (node->reading() != expected) return false;
    if (node->unigrams().empty()) return false;
    pos += span;
  }
  return pos == syls.size();
}

bool chosenInNodeUnigrams(const ReadingGrid::WalkResult& w) {
  for (size_t i = 0; i < w.nodes.size(); ++i) {
    const std::string val = w.chosenValueAt(i);
    bool ok = false;
    for (const auto& u : w.nodes[i]->unigrams()) {
      if (u.value() == val) {
        ok = true;
        break;
      }
    }
    if (!ok) return false;
  }
  return true;
}

void clearAllOverrides(ReadingGrid& grid) {
  const auto& spans = grid.spans();
  for (size_t i = 0; i < spans.size(); ++i) {
    const auto& span = spans[i];
    for (size_t len = 1; len <= span.maxLength(); ++len) {
      const auto& n = span.nodeOf(len);
      if (n && n->isOverridden()) n->reset();
    }
  }
}

struct Constraint {
  size_t loc = 0;
  std::string reading;
  std::string value;
};

bool applyConstraints(ReadingGrid& grid, const std::vector<Constraint>& cs) {
  clearAllOverrides(grid);
  for (const auto& c : cs) {
    ReadingGrid::Candidate cand(c.reading, c.value);
    if (!grid.overrideCandidate(
            c.loc, cand,
            ReadingGrid::Node::OverrideType::kOverrideValueWithHighScore)) {
      return false;
    }
  }
  return true;
}

size_t utf8CharCount(const std::string& w) {
  size_t n = 0;
  size_t i = 0;
  while (i < w.size()) {
    unsigned char c = static_cast<unsigned char>(w[i]);
    size_t len = 1;
    if ((c & 0x80) == 0)
      len = 1;
    else if ((c & 0xE0) == 0xC0)
      len = 2;
    else if ((c & 0xF0) == 0xE0)
      len = 3;
    else if ((c & 0xF8) == 0xF0)
      len = 4;
    if (i + len > w.size()) len = 1;
    ++n;
    i += len;
  }
  return n;
}

std::vector<std::string> utf8Chars(const std::string& s) {
  std::vector<std::string> out;
  size_t i = 0;
  while (i < s.size()) {
    unsigned char c = static_cast<unsigned char>(s[i]);
    size_t len = 1;
    if ((c & 0x80) == 0) len = 1;
    else if ((c & 0xE0) == 0xC0) len = 2;
    else if ((c & 0xF0) == 0xE0) len = 3;
    else if ((c & 0xF8) == 0xF0) len = 4;
    if (i + len > s.size()) len = 1;
    out.push_back(s.substr(i, len));
    i += len;
  }
  return out;
}

std::vector<size_t> worstNodeIndices(const std::vector<std::string>& words,
                                     const std::vector<double>& charLog10,
                                     size_t maxNodes) {
  std::vector<std::pair<double, size_t>> scored;
  size_t charPos = 0;
  for (size_t ni = 0; ni < words.size(); ++ni) {
    size_t nc = utf8CharCount(words[ni]);
    if (nc == 0 || charPos + nc > charLog10.size()) {
      charPos += nc;
      continue;
    }
    double sum = 0.0;
    for (size_t k = 0; k < nc; ++k) sum += charLog10[charPos + k];
    scored.emplace_back(sum / static_cast<double>(nc), ni);
    charPos += nc;
  }
  std::sort(scored.begin(), scored.end(),
            [](const auto& a, const auto& b) { return a.first < b.first; });
  std::vector<size_t> out;
  for (size_t i = 0; i < scored.size() && i < maxNodes; ++i) {
    out.push_back(scored[i].second);
  }
  return out;
}

double minNodeMeanLogp(const std::vector<std::string>& words,
                       const std::vector<double>& charLog10) {
  double worst = 0.0;
  bool any = false;
  size_t charPos = 0;
  for (const auto& w : words) {
    size_t nc = utf8CharCount(w);
    if (nc == 0 || charPos + nc > charLog10.size()) {
      charPos += nc;
      continue;
    }
    double sum = 0.0;
    for (size_t k = 0; k < nc; ++k) sum += charLog10[charPos + k];
    double mean = sum / static_cast<double>(nc);
    if (!any || mean < worst) {
      worst = mean;
      any = true;
    }
    charPos += nc;
  }
  return any ? worst : 0.0;
}

// Fair classical score without override inflation.
double fairWalkScore(const ReadingGrid::WalkResult& w,
                     CorpusBigramContextModel* cm) {
  double total = 0.0;
  std::string prev;
  for (size_t i = 0; i < w.nodes.size(); ++i) {
    const std::string val = w.chosenValueAt(i);
    const auto& node = w.nodes[i];
    double uScore = -1e9;
    for (const auto& u : node->unigrams()) {
      if (u.value() == val) {
        uScore = u.score();
        break;
      }
    }
    double state = 0.0;
    double trans =
        cm ? cm->scoreWithReading(prev, node->reading(), val, state) : 0.0;
    total += uScore + trans;
    prev = val;
  }
  return total;
}

struct Case {
  std::string readings;
  std::string expected;
};

std::vector<Case> loadCases(const std::string& path) {
  std::ifstream in(path);
  std::vector<Case> cases;
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty() || line[0] == '#') continue;
    size_t tab = line.find('\t');
    if (tab == std::string::npos) continue;
    cases.push_back({line.substr(0, tab), line.substr(tab + 1)});
  }
  return cases;
}

struct CandPath {
  std::string text;
  std::vector<std::string> words;
  std::vector<std::string> readings;
  double walkScore = 0.0;
  double neuralScore = 0.0;
  double fusion = 0.0;
  double pathCond = 0.0;       // full-path CondConverter score
  double threeWay = 0.0;       // walk + nuV2c*neural + kCond*pathCond (397 basis)
  bool scored = false;
  double proposalScore = 0.0;  // conversion score of forced alt
  int fromResearch = 0;
  int fromNBest = 0;
  int conversionProposed = 0;  // entered via top-K conversion rank
};

// Cached per-candidate scores → variant acceptance criteria are swept in
// main() over these (pool building is the only expensive part; do it once).
struct CandInfo {
  std::string text;
  double walk = 0.0;
  double neural = 0.0;  // v2c LSTM sentence score
  double cond = 0.0;    // CondConverter path score
  bool external = false;  // not in the original n-best (pool-external)
};

struct SearchResult {
  std::string text;
  std::string draftText;
  std::string base397Text;  // argmax three-way over {draft ∪ nbest} = 397 pick
  std::vector<CandInfo> pool;        // snapshot for variant sweep
  bool expectedReachedExternal = false;  // expected produced as a pool-external path
  double fusionScore = 0.0;
  double neuralScore = 0.0;
  int pathChanged = 0;       // final != draft
  int changedVs397 = 0;      // research changed the 397 answer
  int outsideNBest = 0;
  int fromResearch = 0;
  int triggered = 0;
  int oracleHitExpected = 0;
  int candCount = 0;
  int researchCandCount = 0;
  bool readingOk = true;
  std::unordered_set<std::string> explored;
  std::string pickMode;  // which branch selected the final path
};

enum class PickMode { Fusion, Neural, Hybrid, Cond, ThreeWay };

// Sum of CondConverter scores along a path (needs readings parallel to words).
double pathCondScore(CondConverterScorer* conv,
                     const std::vector<std::string>& words,
                     const std::vector<std::string>& readings) {
  if (!conv || !conv->isLoaded() || words.size() != readings.size()) return 0.0;
  std::string left;
  double sum = 0.0;
  for (size_t i = 0; i < words.size(); ++i) {
    sum += conv->scoreCandidate(left, readings[i], words[i]);
    left += words[i];
    if (left.size() > 64) left = left.substr(left.size() - 64);
  }
  return sum;
}

std::vector<std::string> pathReadings(const ReadingGrid::WalkResult& w) {
  std::vector<std::string> r;
  r.reserve(w.nodes.size());
  for (const auto& n : w.nodes) r.push_back(n->reading());
  return r;
}

SearchResult constrainedSearch(
    ReadingGrid& grid, CorpusBigramContextModel* cm, NeuralLMPathScorer* neural,
    CondConverterScorer* conv, const std::vector<std::string>& syls,
    const std::string& expected, int maxBadNodes, int maxProps, double nuV2c,
    double kCond, PickMode pickMode, double nbestMarginThr, double logpThr,
    double neuralGain, int beamPos, int beamK, int beamWidth) {
  (void)pickMode;  // this harness always uses the three-way (397) basis
  SearchResult sr;
  grid.setContextModel(cm);
  grid.setPathScorer(nullptr);
  grid.setPathRerankNu(0.0);
  const std::string sep = grid.readingSeparator();

  clearAllOverrides(grid);
  auto draft = grid.walk();
  if (draft.nodes.empty()) {
    sr.readingOk = false;
    return sr;
  }

  auto words = pathWords(draft);
  auto draftRds = pathReadings(draft);
  sr.draftText = joined(words);
  sr.text = sr.draftText;
  sr.explored.insert(sr.draftText);

  // ---- Candidate pool ----
  std::unordered_map<std::string, CandPath> pool;
  auto addPath = [&](const std::vector<std::string>& wds,
                     const std::vector<std::string>& rds, double walkSc,
                     int fromResearch, int fromNBest, int convProp,
                     double propSc) {
    std::string text = joined(wds);
    sr.explored.insert(text);
    if (text == expected) sr.oracleHitExpected = 1;
    auto it = pool.find(text);
    if (it != pool.end()) {
      if (walkSc > it->second.walkScore) it->second.walkScore = walkSc;
      if (fromResearch) it->second.fromResearch = 1;
      if (fromNBest) it->second.fromNBest = 1;
      if (convProp) it->second.conversionProposed = 1;
      if (propSc > it->second.proposalScore)
        it->second.proposalScore = propSc;
      if (rds.size() == wds.size()) it->second.readings = rds;
      return;
    }
    CandPath cp;
    cp.text = text;
    cp.words = wds;
    cp.readings = rds;
    cp.walkScore = walkSc;
    cp.fromResearch = fromResearch;
    cp.fromNBest = fromNBest;
    cp.conversionProposed = convProp;
    cp.proposalScore = propSc;
    pool.emplace(text, std::move(cp));
  };

  // Base pool = n-best (the 397 basis: same walkNBest + rp.walkScore as
  // tw538_cond_rerank). draft == nbest[0]; add a fallback only if it isn't.
  std::vector<ReadingGrid::RankedPath> nbest = grid.walkNBest(10);
  std::unordered_set<std::string> nbestSet;
  double bestWalk = -1e300, secondWalk = -1e300;
  for (const auto& rp : nbest) {
    std::string t;
    for (const auto& w : rp.words) t += w;
    nbestSet.insert(t);
    if (rp.walkScore > bestWalk) {
      secondWalk = bestWalk;
      bestWalk = rp.walkScore;
    } else if (rp.walkScore > secondWalk) {
      secondWalk = rp.walkScore;
    }
    std::vector<std::string> rds;
    for (const auto& n : rp.nodes) rds.push_back(n->reading());
    addPath(rp.words, rds, rp.walkScore, 0, 1, 0, 0.0);
  }
  if (pool.find(sr.draftText) == pool.end()) {
    addPath(words, draftRds, fairWalkScore(draft, cm), 0, 0, 0, 0.0);
  }
  double margin = (secondWalk > -1e299) ? (bestWalk - secondWalk) : 1e9;

  // Three-way score (397 basis) — idempotent, only scores unscored members.
  auto scoreThreeWay = [&]() {
    for (auto& kv : pool) {
      CandPath& cp = kv.second;
      if (cp.scored) continue;
      cp.neuralScore = neural->scoreSentence(cp.words);
      cp.pathCond = pathCondScore(conv, cp.words, cp.readings);
      cp.threeWay = cp.walkScore + nuV2c * cp.neuralScore + kCond * cp.pathCond;
      cp.scored = true;
    }
  };
  auto argmaxThreeWay = [&]() -> const CandPath* {
    const CandPath* best = nullptr;
    for (auto& kv : pool) {
      if (!best || kv.second.threeWay > best->threeWay) best = &kv.second;
    }
    return best;
  };

  scoreThreeWay();
  const CandPath* base397 = argmaxThreeWay();
  sr.base397Text = base397 ? base397->text : sr.draftText;

  // Selective trigger (gates the expensive research only; base = 397 always).
  auto charScores = neural->scoreCharsLog10(words);
  double worstLogp = minNodeMeanLogp(words, charScores);
  bool trigger = (worstLogp < logpThr) || (margin < nbestMarginThr);

  auto finalize = [&](const CandPath* best) {
    if (!best) {
      sr.candCount = static_cast<int>(pool.size());
      return;
    }
    sr.text = best->text;
    sr.neuralScore = best->neuralScore;
    sr.fusionScore = best->threeWay;
    sr.candCount = static_cast<int>(pool.size());
    sr.pathChanged = (sr.text != sr.draftText) ? 1 : 0;
    sr.changedVs397 = (sr.text != sr.base397Text) ? 1 : 0;
    sr.fromResearch = best->fromResearch && !best->fromNBest;
    sr.outsideNBest =
        (nbestSet.count(sr.text) == 0 && sr.pathChanged) ? 1 : 0;
    sr.pickMode = sr.changedVs397 ? "threeway_research" : "threeway_base";
  };

  // Snapshot the scored pool for the variant sweep in main().
  auto populatePool = [&]() {
    sr.pool.clear();
    sr.pool.reserve(pool.size());
    for (auto& kv : pool) {
      CandInfo ci;
      ci.text = kv.second.text;
      ci.walk = kv.second.walkScore;
      ci.neural = kv.second.neuralScore;
      ci.cond = kv.second.pathCond;
      ci.external = (nbestSet.count(kv.second.text) == 0);
      if (ci.external && kv.second.text == expected)
        sr.expectedReachedExternal = true;
      sr.pool.push_back(std::move(ci));
    }
  };

  if (!trigger) {
    sr.triggered = 0;
    populatePool();
    finalize(base397);
    return sr;
  }
  sr.triggered = 1;

  // ---- Conversion-style proposals at bad nodes ----
  std::vector<size_t> nodeStart(draft.nodes.size(), 0);
  {
    size_t pos = 0;
    for (size_t i = 0; i < draft.nodes.size(); ++i) {
      nodeStart[i] = pos;
      pos += draft.nodes[i]->spanningLength();
    }
  }
  auto badNodes =
      worstNodeIndices(words, charScores, static_cast<size_t>(maxBadNodes));

  int researchAdded = 0;
  // bigram weight for proposal ranking (secondary to neural continuation)
  constexpr double kBigramInProposal = 0.15;

  for (size_t ni : badNodes) {
    if (ni >= draft.nodes.size()) continue;
    size_t loc = nodeStart[ni];
    const std::string curVal = words[ni];

    // Left context string for CondConverter (last 16 chars of path prefix).
    std::string leftStr;
    for (size_t j = 0; j < ni; ++j) leftStr += words[j];
    if (leftStr.size() > 16) leftStr = leftStr.substr(leftStr.size() - 16);
    std::string prevWord = (ni == 0) ? std::string() : words[ni - 1];

    struct Prop {
      std::string reading;
      std::string value;
      double score = 0.0;
    };
    auto cands = grid.candidatesAt(loc);
    std::vector<Prop> props;
    std::unordered_set<std::string> seen;
    seen.insert(curVal + "\x1f" + draft.nodes[ni]->reading());

    // Baseline: CondConverter P(cur|left,reading) — true (i) model.
    double curScore = 0.0;
    if (conv && conv->isLoaded()) {
      curScore = conv->scoreCandidate(leftStr, draft.nodes[ni]->reading(),
                                      curVal);
    } else {
      // Fallback only if cond missing (should not happen in v3 runs).
      curScore = neural->scoreContinuation(
          std::vector<std::string>(words.begin(),
                                   words.begin() + static_cast<std::ptrdiff_t>(ni)),
          curVal);
    }
    double curState = 0.0;
    double curBg =
        cm ? cm->scoreWithReading(prevWord, draft.nodes[ni]->reading(), curVal,
                                  curState)
           : 0.0;
    curScore = curScore + kBigramInProposal * curBg;

    for (const auto& cand : cands) {
      std::string key = cand.value + "\x1f" + cand.reading;
      if (seen.count(key)) continue;
      if (cand.reading.rfind("_punctuation_", 0) == 0 ||
          cand.reading.rfind("_half_punctuation_", 0) == 0 ||
          cand.reading.rfind("_ctrl_punctuation_", 0) == 0 ||
          cand.reading.rfind("_letter_", 0) == 0) {
        continue;
      }
      seen.insert(key);

      // (i) CondConverter: P(cand | left, cand.reading)
      double cond = 0.0;
      if (conv && conv->isLoaded()) {
        cond = conv->scoreCandidate(leftStr, cand.reading, cand.value);
      } else {
        cond = neural->scoreContinuation(
            std::vector<std::string>(
                words.begin(),
                words.begin() + static_cast<std::ptrdiff_t>(ni)),
            cand.value);
      }
      double state = 0.0;
      double bg =
          cm ? cm->scoreWithReading(prevWord, cand.reading, cand.value, state)
             : 0.0;
      double score = cond + kBigramInProposal * bg;
      // Multi-syllable always keep (segmentation change).
      size_t candSyls = 1;
      for (char ch : cand.reading) {
        if (ch == '-') ++candSyls;
      }
      size_t curSyls = draft.nodes[ni]->spanningLength();
      bool multiSeg = candSyls > curSyls;
      if (multiSeg) {
        score += 0.05;
      } else if (score <= curScore + 1e-6) {
        continue;
      }
      props.push_back(Prop{cand.reading, cand.value, score});
    }

    // Rank by conversion score (higher = better proposal).
    std::sort(props.begin(), props.end(),
              [](const Prop& a, const Prop& b) { return a.score > b.score; });
    if (static_cast<int>(props.size()) > maxProps) {
      props.resize(static_cast<size_t>(maxProps));
    }

    for (const auto& prop : props) {
      // Prefix lock + force conversion proposal.
      std::vector<Constraint> trial;
      {
        size_t p = 0;
        for (size_t j = 0; j < ni; ++j) {
          trial.push_back(
              Constraint{p, draft.nodes[j]->reading(), words[j]});
          p += draft.nodes[j]->spanningLength();
        }
      }
      trial.push_back(Constraint{loc, prop.reading, prop.value});
      if (!applyConstraints(grid, trial)) continue;

      auto w = grid.walk();
      if (w.nodes.empty()) continue;
      if (!readingsFaithful(w, syls, sep)) continue;
      if (!chosenInNodeUnigrams(w)) continue;

      auto tw = pathWords(w);
      auto tr = pathReadings(w);
      size_t before = pool.size();
      addPath(tw, tr, fairWalkScore(w, cm), 1, 0, 1, prop.score);
      if (pool.size() > before) ++researchAdded;
    }
  }
  clearAllOverrides(grid);
  sr.researchCandCount = researchAdded;
  (void)neuralGain;  // conservative accept is implicit in argmax three-way

  // ---- Multi-position cond beam (T2) ------------------------------------
  // The single-position loop above fixes ONE worst node at a time; the T1
  // diagnostic showed every mechanism-recoverable B-class miss diverges at
  // 2–7 positions at once (gold char is cond top-1/3 at each, but never
  // assembled jointly). Beam-decode cond's top-k over the worst syllable
  // positions and re-walk each surviving hypothesis. This ONLY enlarges the
  // candidate pool; the two-vote acceptance rule downstream is unchanged.
  if (beamWidth > 0) {
    std::vector<std::string> sylChar(syls.size());
    {
      size_t pos = 0;
      for (const auto& node : draft.nodes) {
        auto cs = utf8Chars(node->value());
        size_t span = node->spanningLength();
        for (size_t k = 0; k < span && pos + k < syls.size(); ++k)
          sylChar[pos + k] = (cs.size() == span) ? cs[k] : std::string();
        pos += span;
      }
    }
    std::vector<size_t> badPos;
    {
      std::vector<std::pair<double, size_t>> v;
      for (size_t i = 0; i < charScores.size() && i < syls.size(); ++i)
        v.emplace_back(charScores[i], i);
      std::sort(v.begin(), v.end(),
                [](const auto& a, const auto& b) { return a.first < b.first; });
      for (size_t i = 0; i < v.size() && static_cast<int>(i) < beamPos; ++i)
        badPos.push_back(v[i].second);
      std::sort(badPos.begin(), badPos.end());
    }
    if (!badPos.empty()) {
      struct Hyp {
        std::vector<std::string> chosen;  // char picked at each processed badPos
        double score = 0.0;
      };
      std::vector<Hyp> beam(1);
      for (size_t bi = 0; bi < badPos.size(); ++bi) {
        size_t p = badPos[bi];
        std::vector<std::string> vals;
        std::unordered_set<std::string> seenV;
        for (const auto& c : grid.candidatesAt(p)) {
          if (c.reading != syls[p]) continue;  // single-syllable, exact reading
          if (seenV.count(c.value)) continue;
          seenV.insert(c.value);
          vals.push_back(c.value);
        }
        if (vals.empty() && !sylChar[p].empty()) vals.push_back(sylChar[p]);
        std::vector<Hyp> next;
        for (const auto& h : beam) {
          std::vector<std::string> cur = sylChar;
          for (size_t j = 0; j < bi; ++j) cur[badPos[j]] = h.chosen[j];
          std::string left;
          for (size_t q = 0; q < p; ++q) left += cur[q];
          if (left.size() > 24) left = left.substr(left.size() - 24);
          std::vector<std::pair<double, std::string>> scored;
          for (const auto& val : vals) {
            double s = (conv && conv->isLoaded())
                           ? conv->scoreCandidate(left, syls[p], val)
                           : 0.0;
            scored.emplace_back(s, val);
          }
          std::sort(scored.begin(), scored.end(),
                    [](const auto& a, const auto& b) { return a.first > b.first; });
          int kk = 0;
          for (const auto& sc : scored) {
            if (kk++ >= beamK) break;
            Hyp nh = h;
            nh.chosen.push_back(sc.second);
            nh.score += sc.first;
            next.push_back(std::move(nh));
          }
        }
        std::sort(next.begin(), next.end(),
                  [](const Hyp& a, const Hyp& b) { return a.score > b.score; });
        if (static_cast<int>(next.size()) > beamWidth)
          next.resize(static_cast<size_t>(beamWidth));
        beam = std::move(next);
      }
      for (const auto& h : beam) {
        std::vector<Constraint> trial;
        for (size_t bi = 0; bi < badPos.size() && bi < h.chosen.size(); ++bi)
          trial.push_back(
              Constraint{badPos[bi], syls[badPos[bi]], h.chosen[bi]});
        if (trial.empty()) continue;
        if (!applyConstraints(grid, trial)) continue;
        auto w = grid.walk();
        if (w.nodes.empty()) continue;
        if (!readingsFaithful(w, syls, sep)) continue;
        if (!chosenInNodeUnigrams(w)) continue;
        size_t before = pool.size();
        addPath(pathWords(w), pathReadings(w), fairWalkScore(w, cm), 1, 0, 1,
                h.score);
        if (pool.size() > before) ++researchAdded;
      }
      clearAllOverrides(grid);
      sr.researchCandCount = researchAdded;
    }
  }

  // Score the newly-added research members on the same three-way (397) basis,
  // then pick argmax over the FULL pool. Because the n-best (397) candidates
  // are in the pool, a research path wins only if its three-way beats every
  // 397 candidate → conservative accept, no regression vs 397 by construction.
  scoreThreeWay();
  populatePool();
  finalize(argmaxThreeWay());
  return sr;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 7) {
    std::cerr
        << "Usage: zenzai_constrained_search sentences data bigrams lambda "
           "lstm.bin cond.bin [max_bad] [max_props] [nu] [mode] [margin] "
           "[logp_thr] [neural_gain]\n"
           "  mode: fusion|neural|hybrid|cond  (default cond)\n";
    return 1;
  }
  auto cases = loadCases(argv[1]);
  ParselessLM lm;
  if (!lm.open(argv[2])) {
    std::cerr << "failed to open data\n";
    return 1;
  }
  CorpusBigramContextModel cm;
  if (!cm.load(argv[3])) {
    std::cerr << "failed to open bigrams\n";
    return 1;
  }
  cm.setLambda(std::stod(argv[4]));

  NeuralLMPathScorer neural;
  if (!neural.load(argv[5])) {
    std::cerr << "failed to load lstm\n";
    return 1;
  }
  CondConverterScorer conv;
  if (!conv.load(argv[6])) {
    std::cerr << "failed to load cond converter\n";
    return 1;
  }
  std::cout << "PROPOSER approach=i_cond_converter\n";
  std::cout << "PROPOSER model=CondConverter scoreCandidate(left,reading,word)\n";
  std::cout << "PROPOSER params=" << conv.parameterCount()
            << " char_vocab=" << conv.charVocab()
            << " rd_vocab=" << conv.readingVocab() << " emb=" << conv.embDim()
            << " hidden=" << conv.hiddenDim() << " layers=" << conv.layers()
            << "\n";
  std::cout << "PROPOSER train_corpus=PTT_Gossiping+dict_aligned real "
               "(no synthetic)\n";
  std::cout << "PROPOSER why=dedicated_reading_conditioned_conversion_model\n";
  std::cout << "TRIGGER_LM params=" << neural.parameterCount()
            << " (spoken char-LSTM for disagreement/trigger only)\n";

  // args: max_bad max_props nuV2c kCond margin logp_thr
  int maxBad = argc > 7 ? std::stoi(argv[7]) : 5;
  int maxProps = argc > 8 ? std::stoi(argv[8]) : 8;
  double nuV2c = argc > 9 ? std::stod(argv[9]) : 0.5;    // v2c weight (397 cfg)
  double kCond = argc > 10 ? std::stod(argv[10]) : 0.25;  // cond weight (397 cfg)
  double margin = argc > 11 ? std::stod(argv[11]) : 0.5;
  double logpThr = argc > 12 ? std::stod(argv[12]) : -2.5;
  double neuralGain = 0.0;
  // T2 multi-position cond beam: beamWidth=0 disables (reproduces the 401
  // single-position baseline exactly — the A/B control).
  int beamPos   = argc > 13 ? std::stoi(argv[13]) : 8;  // worst syllables scanned
  int beamK     = argc > 14 ? std::stoi(argv[14]) : 3;  // cond top-k per position
  int beamWidth = argc > 15 ? std::stoi(argv[15]) : 0;  // beam width (0 = off)
  PickMode pickMode = PickMode::ThreeWay;

  std::cout << "params max_bad=" << maxBad << " max_props=" << maxProps
            << " nuV2c=" << nuV2c << " kCond=" << kCond
            << " basis=walk+nuV2c*v2c+kCond*cond (397 fusion)"
            << " nbest_margin_thr=" << margin << " logp_thr=" << logpThr
            << " beam_pos=" << beamPos << " beam_k=" << beamK
            << " beam_width=" << beamWidth << (beamWidth ? "" : " (OFF)")
            << "\n";

  int walkOn = 0;
  int zenzaiCorrect = 0;
  int base397Correct = 0;   // argmax three-way over n-best only (397 control)
  int regressions = 0;      // base397 right → constrained-search wrong
  int gains = 0;            // base397 wrong → constrained-search right
  int changedVs397 = 0;     // research changed the 397 answer
  int bClassFixed = 0;      // expected ∉ n-best AND final == expected
  int pathChanged = 0;
  int outsideNBest = 0;
  int fromResearchPick = 0;
  int breakthrough = 0;
  int oracleBreakthrough = 0;
  int readingFail = 0;
  int nbestContainsExpected = 0;
  int nbestMissExpected = 0;
  int exploredHitExpected = 0;
  int triggeredN = 0;
  int hybridResearchPicks = 0;
  long long candSum = 0;
  long long researchCandSum = 0;
  long long us = 0;
  int n = 0;

  struct Ex {
    std::string expected;
    std::string draft;
    std::string zenzai;
    std::string readings;
    std::string note;
  };
  std::vector<Ex> greedyEx;
  std::vector<Ex> oracleEx;
  std::vector<Ex> improvedEx;  // fixed vs walk draft

  // Cached per-case pools for the acceptance-variant sweep.
  struct CaseCache {
    std::vector<CandInfo> pool;
    std::string expected;
    bool expectedInNBest = false;
  };
  std::vector<CaseCache> caches;
  caches.reserve(cases.size());

  for (const auto& c : cases) {
    auto syls = splitSyllables(c.readings);

    std::string draftText;
    std::unordered_set<std::string> nbestSet;
    {
      ReadingGrid g = makeGrid(&lm);
      if (!feed(g, c.readings)) continue;
      g.setContextModel(&cm);
      auto w = g.walk();
      draftText = joinedWalk(w);
      if (draftText == c.expected) ++walkOn;
      auto nb = g.walkNBest(10);
      for (const auto& rp : nb) {
        std::string t;
        for (const auto& x : rp.words) t += x;
        nbestSet.insert(t);
      }
    }
    bool expectedInNBest = nbestSet.count(c.expected) > 0;
    if (expectedInNBest)
      ++nbestContainsExpected;
    else
      ++nbestMissExpected;

    ReadingGrid g = makeGrid(&lm);
    if (!feed(g, c.readings)) continue;
    auto t0 = std::chrono::steady_clock::now();
    auto sr = constrainedSearch(g, &cm, &neural, &conv, syls, c.expected,
                                maxBad, maxProps, nuV2c, kCond, pickMode,
                                margin, logpThr, neuralGain, beamPos, beamK,
                                beamWidth);
    auto t1 = std::chrono::steady_clock::now();
    us += std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0).count();
    ++n;

    bool base397ok = (sr.base397Text == c.expected);
    bool finalok = (sr.text == c.expected);
    if (base397ok) ++base397Correct;
    if (sr.changedVs397) ++changedVs397;
    if (base397ok && !finalok) ++regressions;
    if (!base397ok && finalok) ++gains;
    if (!expectedInNBest && finalok) ++bClassFixed;

    if (!sr.readingOk) ++readingFail;
    if (sr.triggered) ++triggeredN;
    if (sr.pathChanged) ++pathChanged;
    if (sr.outsideNBest) ++outsideNBest;
    if (sr.fromResearch) ++fromResearchPick;
    if (sr.pickMode == "hybrid_proposal_first" ||
      sr.pickMode == "hybrid_research" ||
      sr.pickMode == "hybrid_cond_research")
    ++hybridResearchPicks;
    if (sr.explored.count(c.expected)) ++exploredHitExpected;
    candSum += sr.candCount;
    researchCandSum += sr.researchCandCount;

    caches.push_back({std::move(sr.pool), c.expected, expectedInNBest});

    if (sr.text == c.expected) {
      ++zenzaiCorrect;
      if (!expectedInNBest) {
        ++breakthrough;
        if (greedyEx.size() < 15) {
          greedyEx.push_back(
              {c.expected, draftText, sr.text, c.readings, "breakthrough"});
        }
      }
      if (draftText != c.expected && improvedEx.size() < 15) {
        improvedEx.push_back(
            {c.expected, draftText, sr.text, c.readings, "fixed_vs_draft"});
      }
    }
    if (!expectedInNBest && sr.explored.count(c.expected)) {
      ++oracleBreakthrough;
      if (oracleEx.size() < 12) {
        oracleEx.push_back(
            {c.expected, draftText, sr.text, c.readings, "oracle"});
      }
    }
  }

  double meanMs = n ? (double)us / n / 1000.0 : 0;
  double triggerRate = n ? (double)triggeredN / n : 0;
  std::cout << "WALK_ON " << walkOn << "/" << cases.size() << "\n";
  std::cout << "BASE397_CONTROL " << base397Correct << "/" << cases.size()
            << " (argmax three-way over n-best only; must reproduce 397)\n";
  std::cout << "ZENZAI_CORRECT " << zenzaiCorrect << "/" << cases.size()
            << " (constrained search on the same three-way basis)\n";
  std::cout << "NET_VS_397 " << (zenzaiCorrect - base397Correct)
            << "  gains=" << gains << " regressions=" << regressions << "\n";
  std::cout << "B_CLASS_FIXED " << bClassFixed << "/" << nbestMissExpected
            << " (pool-external expected recovered by re-search)\n";
  std::cout << "CHANGED_VS_397 " << changedVs397 << "/" << n << "\n";
  std::cout << "TRIGGERED " << triggeredN << "/" << n
            << " rate=" << triggerRate << "\n";
  std::cout << "PATH_CHANGED " << pathChanged << "/" << n << "\n";
  std::cout << "OUTSIDE_NBEST_FINAL " << outsideNBest << "/" << n << "\n";
  std::cout << "PICK_FROM_RESEARCH " << fromResearchPick << "/" << n << "\n";
  std::cout << "HYBRID_RESEARCH_PICKS " << hybridResearchPicks << "/" << n
            << "\n";
  std::cout << "NBEST10_CONTAINS_EXPECTED " << nbestContainsExpected << "/"
            << cases.size() << "\n";
  std::cout << "NBEST10_MISS_EXPECTED " << nbestMissExpected << "/"
            << cases.size() << "\n";
  std::cout << "EXPLORED_HIT_EXPECTED " << exploredHitExpected << "/"
            << cases.size() << "\n";
  std::cout << "BREAKTHROUGH_GREEDY " << breakthrough << "/" << cases.size()
            << "\n";
  std::cout << "BREAKTHROUGH_ORACLE_EXPLORED " << oracleBreakthrough << "/"
            << cases.size() << "\n";
  std::cout << "MEAN_CAND_POOL " << (n ? (double)candSum / n : 0) << "\n";
  std::cout << "MEAN_RESEARCH_ADDED "
            << (n ? (double)researchCandSum / n : 0) << "\n";
  std::cout << "READING_FIDELITY_FAIL " << readingFail << "/" << n << "\n";
  std::cout << "MEAN_MS " << meanMs << "\n";
  std::cout << "COMPARE_TW538_MIX_397 397  (walk+0.5v2c+0.25cond rerank)\n";
  std::cout << "COMPARE_TW538_V2C_ONLY 387\n";
  std::cout << "COMPARE_TW538_WALK_ON 333\n";

  std::cout << "BREAKTHROUGH_GREEDY_EXAMPLES " << greedyEx.size() << "\n";
  for (size_t i = 0; i < greedyEx.size(); ++i) {
    const auto& e = greedyEx[i];
    std::cout << "GEX" << i << " readings=" << e.readings << "\n";
    std::cout << "GEX" << i << " draft=" << e.draft << "\n";
    std::cout << "GEX" << i << " zenzai=" << e.zenzai << "\n";
    std::cout << "GEX" << i << " expected=" << e.expected << "\n";
  }
  std::cout << "FIXED_VS_DRAFT_EXAMPLES " << improvedEx.size() << "\n";
  for (size_t i = 0; i < improvedEx.size(); ++i) {
    const auto& e = improvedEx[i];
    std::cout << "FIX" << i << " readings=" << e.readings << "\n";
    std::cout << "FIX" << i << " draft=" << e.draft << "\n";
    std::cout << "FIX" << i << " zenzai=" << e.zenzai << "\n";
    std::cout << "FIX" << i << " expected=" << e.expected << "\n";
  }
  std::cout << "BREAKTHROUGH_ORACLE_EXAMPLES " << oracleEx.size() << "\n";
  for (size_t i = 0; i < oracleEx.size(); ++i) {
    const auto& e = oracleEx[i];
    std::cout << "OEX" << i << " readings=" << e.readings << "\n";
    std::cout << "OEX" << i << " draft=" << e.draft << "\n";
    std::cout << "OEX" << i << " pick=" << e.zenzai << "\n";
    std::cout << "OEX" << i << " expected_in_explored=" << e.expected << "\n";
  }

  // ================= Acceptance-variant sweep (cached pools) =================
  // Pool building was the only expensive step; all variants below re-select
  // from the cached per-case pools, so this is ~free.
  auto three = [&](const CandInfo& c, double alpha) {
    double a = c.external ? alpha : 1.0;
    return a * c.walk + nuV2c * c.neural + kCond * c.cond;
  };
  std::vector<std::string> base397Pick(caches.size());
  int nbestMiss = 0, reachedB = 0;
  for (size_t i = 0; i < caches.size(); ++i) {
    const auto& cc = caches[i];
    const CandInfo* b = nullptr;
    for (const auto& c : cc.pool) {
      if (c.external) continue;
      if (!b || three(c, 1.0) > three(*b, 1.0)) b = &c;
    }
    base397Pick[i] = b ? b->text : "";
    if (!cc.expectedInNBest) {
      ++nbestMiss;
      for (const auto& c : cc.pool)
        if (c.external && c.text == cc.expected) { ++reachedB; break; }
    }
  }
  int base397correct = 0;
  for (size_t i = 0; i < caches.size(); ++i)
    if (base397Pick[i] == caches[i].expected) ++base397correct;

  auto evalAlpha = [&](double alpha, bool dumpVeto) {
    int correct = 0, gains = 0, regress = 0, bclass = 0, vetoed = 0;
    std::vector<std::string> vetoList;
    for (size_t i = 0; i < caches.size(); ++i) {
      const auto& cc = caches[i];
      const CandInfo* best = nullptr;
      for (const auto& c : cc.pool)
        if (!best || three(c, alpha) > three(*best, alpha)) best = &c;
      std::string pick = best ? best->text : "";
      bool ok = (pick == cc.expected);
      bool base_ok = (base397Pick[i] == cc.expected);
      if (ok) ++correct;
      if (!base_ok && ok) ++gains;
      if (base_ok && !ok) ++regress;
      if (ok && !cc.expectedInNBest) ++bclass;
      if (!cc.expectedInNBest) {
        bool reached = false;
        for (const auto& c : cc.pool)
          if (c.external && c.text == cc.expected) { reached = true; break; }
        if (reached && !ok) {
          ++vetoed;
          if (dumpVeto && vetoList.size() < 20)
            vetoList.push_back(cc.expected + "  (got: " + pick + ")");
        }
      }
    }
    std::cout << "VARIANT alpha=" << alpha << " correct " << correct << "/"
              << cases.size() << " net " << (correct - base397correct)
              << " gains " << gains << " regress " << regress
              << " bclass_fixed " << bclass << "/" << nbestMiss << " vetoed "
              << vetoed << "\n";
    for (size_t k = 0; k < vetoList.size(); ++k)
      std::cout << "  VETO" << k << " " << vetoList[k] << "\n";
  };

  auto evalTwoVote = [&](double m) {
    int correct = 0, gains = 0, regress = 0, bclass = 0;
    for (size_t i = 0; i < caches.size(); ++i) {
      const auto& cc = caches[i];
      const CandInfo* base = nullptr;
      for (const auto& c : cc.pool) {
        if (c.external) continue;
        if (!base || three(c, 1.0) > three(*base, 1.0)) base = &c;
      }
      std::string pick = base ? base->text : "";
      if (base) {
        const CandInfo* bestExt = nullptr;
        for (const auto& c : cc.pool) {
          if (!c.external) continue;
          // both neural votes must prefer the pool-external path by margin m.
          if (c.neural > base->neural + m && c.cond > base->cond + m) {
            if (!bestExt || (c.neural + c.cond) > (bestExt->neural + bestExt->cond))
              bestExt = &c;
          }
        }
        if (bestExt) pick = bestExt->text;
      }
      bool ok = (pick == cc.expected);
      bool base_ok = (base397Pick[i] == cc.expected);
      if (ok) ++correct;
      if (!base_ok && ok) ++gains;
      if (base_ok && !ok) ++regress;
      if (ok && !cc.expectedInNBest) ++bclass;
    }
    std::cout << "VARIANT twovote m=" << m << " correct " << correct << "/"
              << cases.size() << " net " << (correct - base397correct)
              << " gains " << gains << " regress " << regress
              << " bclass_fixed " << bclass << "/" << nbestMiss << "\n";
  };

  std::cout << "SWEEP_BASE397 " << base397correct << "/" << cases.size()
            << " nbest_miss " << nbestMiss << " reached_bclass " << reachedB
            << " never_reached " << (nbestMiss - reachedB) << "\n";
  std::cout << "SWEEP_VARIANT_A pool-external walk downweight (alpha):\n";
  for (double a : {1.0, 0.75, 0.5, 0.25, 0.0}) evalAlpha(a, false);
  std::cout << "SWEEP_VARIANT_B neural two-vote (v2c AND cond prefer, margin m):\n";
  for (double m : {0.0, 0.25, 0.5, 1.0, 2.0}) evalTwoVote(m);
  std::cout << "SWEEP_RESIDUAL veto list @ alpha=1.0 (the 400 config):\n";
  evalAlpha(1.0, true);
  return 0;
}
