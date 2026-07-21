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
using McBopomofo::CondConverterScorer;
using McBopomofo::CorpusBigramContextModel;
using McBopomofo::NeuralLMPathScorer;
using McBopomofo::ParselessLM;

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
    double neuralGain) {
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

// ================= 60-sentence silence diagnostic (T1) =====================
// For each never-reached B-class case (expected ∉ n-best AND the current
// CondProposer never produces the gold path), answer per divergence position:
//   (a) cond rank of the gold char among single-syllable lattice candidates
//       at that position, under teacher-forced gold left context
//   (b) full-path cond preference: cond(gold-as-chars) vs cond(draft-as-chars)
//   (c) v2c preference: scoreSentence(gold) vs scoreSentence(draft)
// Bucket (priority): KNOW (gold not in cond top-5 at some divergence, incl.
// lattice miss) > VETO_RISK (reachable ≤5 but a neural vote opposes gold, so
// two-vote m>0 blocks it) > MECH (reachable ≤5 AND both votes prefer gold →
// wider beam / multi-position proposal recovers it and two-vote accepts).
// Gold left context is the optimistic ceiling on reach (single-divergence
// cases see the true draft context; multi-divergence cases see gold prefix).

namespace {

std::vector<std::string> utf8Split(const std::string& s) {
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

// Expand a walk into one char per syllable position (Mandarin: 1 syllable =
// 1 char). Returns false if any node's char count != its syllable span
// (segmentation that breaks the 1:1 assumption — flagged, position analysis
// skipped for that case).
bool draftCharsPerSyllable(const ReadingGrid::WalkResult& w, size_t nSyls,
                           std::vector<std::string>& out) {
  out.assign(nSyls, "");
  size_t pos = 0;
  for (const auto& node : w.nodes) {
    size_t span = node->spanningLength();
    auto chars = utf8Split(node->value());
    if (chars.size() != span) return false;
    for (size_t k = 0; k < span; ++k) {
      if (pos + k >= nSyls) return false;
      out[pos + k] = chars[k];
    }
    pos += span;
  }
  return pos == nSyls;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 7) {
    std::cerr << "Usage: zenzai_silence_diag sentences data bigrams lambda "
                 "lstm.bin cond.bin [max_bad] [max_props] [nu] [kcond] "
                 "[margin] [logp_thr] [tsv_out]\n";
    return 1;
  }
  auto cases = loadCases(argv[1]);
  ParselessLM lm;
  if (!lm.open(argv[2])) { std::cerr << "failed data\n"; return 1; }
  CorpusBigramContextModel cm;
  if (!cm.load(argv[3])) { std::cerr << "failed bigrams\n"; return 1; }
  cm.setLambda(std::stod(argv[4]));
  NeuralLMPathScorer neural;
  if (!neural.load(argv[5])) { std::cerr << "failed lstm\n"; return 1; }
  CondConverterScorer conv;
  if (!conv.load(argv[6])) { std::cerr << "failed cond\n"; return 1; }

  int maxBad   = argc > 7  ? std::stoi(argv[7])  : 5;
  int maxProps = argc > 8  ? std::stoi(argv[8])  : 8;
  double nuV2c = argc > 9  ? std::stod(argv[9])  : 0.5;
  double kCond = argc > 10 ? std::stod(argv[10]) : 0.25;
  double margin= argc > 11 ? std::stod(argv[11]) : 0.5;
  double logpThr=argc > 12 ? std::stod(argv[12]) : -2.5;
  std::string tsvOut = argc > 13 ? argv[13] : "";

  std::cout << "SILENCE_DIAG cond_params=" << conv.parameterCount()
            << " cfg=max_bad" << maxBad << " max_props" << maxProps
            << " nu" << nuV2c << " kcond" << kCond << " margin" << margin
            << " logp" << logpThr << "\n";
  std::cout << "AXIS_A rank of gold char among single-syllable lattice cands "
               "(cond, gold left ctx). AXIS_B cond(gold)-cond(draft) full path "
               "(char-level). AXIS_C v2c(gold)-v2c(draft).\n";

  // Rank threshold for "reachable by a small beam".
  const int TOP3 = 3, TOP5 = 5;

  int nBclass = 0, nReached = 0, nNever = 0;
  int nAlignSkip = 0;
  // buckets over never-reached
  int bMECH = 0, bKNOW = 0, bVETO = 0;
  int bMECH_top3 = 0, bMECH_top5 = 0;
  int bLatticeMiss = 0;   // never-reached with ≥1 divergence gold char not a lattice cand
  // axis-A distribution over all divergence positions in never-reached set
  long divTotal = 0, divTop1 = 0, divTop3 = 0, divTop5 = 0, divFar = 0, divMiss = 0;

  std::ofstream tsv;
  if (!tsvOut.empty()) {
    tsv.open(tsvOut);
    tsv << "idx\tbucket\tnum_div\tworst_rank\tlattice_miss\t"
           "cond_gold\tcond_draft\tcond_pref_gold\t"
           "v2c_gold\tv2c_draft\tv2c_pref_gold\t"
           "div_ranks\treadings\tdraft\tgold\n";
  }

  for (size_t ci = 0; ci < cases.size(); ++ci) {
    const auto& c = cases[ci];
    auto syls = splitSyllables(c.readings);
    if (syls.empty()) continue;

    // n-best membership → B-class filter
    std::unordered_set<std::string> nbestSet;
    std::string draftText;
    ReadingGrid::WalkResult draftWalk;
    {
      ReadingGrid g = makeGrid(&lm);
      if (!feed(g, c.readings)) continue;
      g.setContextModel(&cm);
      draftWalk = g.walk();
      draftText = joinedWalk(draftWalk);
      auto nb = g.walkNBest(10);
      for (const auto& rp : nb) {
        std::string t; for (const auto& x : rp.words) t += x;
        nbestSet.insert(t);
      }
    }
    if (nbestSet.count(c.expected)) continue;  // A-class, skip
    ++nBclass;

    // faithful reached flag from the real proposer
    ReadingGrid g2 = makeGrid(&lm);
    if (!feed(g2, c.readings)) continue;
    auto sr = constrainedSearch(g2, &cm, &neural, &conv, syls, c.expected,
                                maxBad, maxProps, nuV2c, kCond,
                                PickMode::ThreeWay, margin, logpThr, 0.0);
    bool reached = (sr.oracleHitExpected == 1);
    if (reached) { ++nReached; continue; }
    ++nNever;

    // ---- diagnose this never-reached case ----
    auto goldChars = utf8Split(c.expected);
    std::vector<std::string> draftChars;
    bool aligned = (goldChars.size() == syls.size()) &&
                   draftCharsPerSyllable(draftWalk, syls.size(), draftChars);
    if (!aligned) {
      ++nAlignSkip; ++bKNOW;  // segmentation-broken → not proposer-recoverable
      if (tsv.is_open())
        tsv << ci << "\tKNOW_ALIGN\t?\t9999\t1\t0\t0\t0\t0\t0\t0\t-\t"
            << c.readings << "\t" << draftText << "\t" << c.expected << "\n";
      continue;
    }

    // divergence positions + per-position cond rank of gold char
    ReadingGrid g3 = makeGrid(&lm);
    if (!feed(g3, c.readings)) continue;
    g3.setContextModel(&cm);
    std::string goldPrefix;  // teacher-forced gold left context
    std::vector<int> divRanks;
    int worstRank = 0; bool latticeMiss = false; int numDiv = 0;
    for (size_t i = 0; i < syls.size(); ++i) {
      std::string left = goldPrefix;
      if (left.size() > 24) left = left.substr(left.size() - 24);  // ~8 chars
      if (goldChars[i] != draftChars[i]) {
        ++numDiv;
        // rank gold among single-syllable lattice candidates at position i
        double goldScore = conv.scoreCandidate(left, syls[i], goldChars[i]);
        int better = 0; bool goldInLattice = false;
        for (const auto& cand : g3.candidatesAt(i)) {
          if (cand.reading.find('-') != std::string::npos) continue;  // multi-syl
          if (cand.reading != syls[i]) continue;
          if (cand.value == goldChars[i]) { goldInLattice = true; continue; }
          double s = conv.scoreCandidate(left, syls[i], cand.value);
          if (s > goldScore) ++better;
        }
        int rank = goldInLattice ? (better + 1) : 9999;
        divRanks.push_back(rank);
        if (rank > worstRank) worstRank = rank;
        if (!goldInLattice) latticeMiss = true;
        ++divTotal;
        if (rank == 9999) ++divMiss;
        else if (rank == 1) ++divTop1;
        else if (rank <= TOP3) ++divTop3;
        else if (rank <= TOP5) ++divTop5;
        else ++divFar;
      }
      goldPrefix += goldChars[i];
    }

    // axis B: full-path cond, char-level, both paths
    double condGold  = pathCondScore(&conv, goldChars, syls);
    double condDraft = pathCondScore(&conv, draftChars, syls);
    bool condPrefGold = condGold > condDraft;
    // axis C: v2c sentence score
    double v2cGold  = neural.scoreSentence(goldChars);
    double v2cDraft = neural.scoreSentence(draftChars);
    bool v2cPrefGold = v2cGold > v2cDraft;

    if (latticeMiss) ++bLatticeMiss;

    // bucket (priority: KNOW > VETO_RISK > MECH)
    std::string bucket;
    bool reachable = (worstRank <= TOP5) && !latticeMiss;
    if (!reachable) {
      bucket = "KNOW"; ++bKNOW;
    } else if (condPrefGold && v2cPrefGold) {
      bucket = "MECH"; ++bMECH;
      if (worstRank <= TOP3) ++bMECH_top3; else ++bMECH_top5;
    } else {
      bucket = "VETO_RISK"; ++bVETO;
    }

    if (tsv.is_open()) {
      std::string ranks;
      for (size_t k = 0; k < divRanks.size(); ++k) {
        if (k) ranks += ",";
        ranks += std::to_string(divRanks[k]);
      }
      tsv << ci << "\t" << bucket << "\t" << numDiv << "\t" << worstRank
          << "\t" << (latticeMiss ? 1 : 0) << "\t" << condGold << "\t"
          << condDraft << "\t" << (condPrefGold ? 1 : 0) << "\t" << v2cGold
          << "\t" << v2cDraft << "\t" << (v2cPrefGold ? 1 : 0) << "\t" << ranks
          << "\t" << c.readings << "\t" << draftText << "\t" << c.expected
          << "\n";
    }
  }
  if (tsv.is_open()) tsv.close();

  std::cout << "B_CLASS_TOTAL " << nBclass << "\n";
  std::cout << "REACHED " << nReached << "\n";
  std::cout << "NEVER_REACHED " << nNever << "\n";
  std::cout << "  ALIGN_SKIP " << nAlignSkip << " (segmentation broke 1:1; counted KNOW)\n";
  std::cout << "BUCKET_MECH " << bMECH << " (top3=" << bMECH_top3
            << " top5only=" << bMECH_top5 << ")\n";
  std::cout << "BUCKET_VETO_RISK " << bVETO << "\n";
  std::cout << "BUCKET_KNOW " << bKNOW << " (of which lattice_miss="
            << bLatticeMiss << ")\n";
  std::cout << "AXIS_A_DIV_POSITIONS " << divTotal << " top1=" << divTop1
            << " top2_3=" << divTop3 << " top4_5=" << divTop5
            << " rank>5=" << divFar << " lattice_miss=" << divMiss << "\n";
  double mechFrac = nNever ? 100.0 * bMECH / nNever : 0.0;
  double knowFrac = nNever ? 100.0 * bKNOW / nNever : 0.0;
  std::cout << "SUMMARY MECH=" << mechFrac << "% KNOW=" << knowFrac
            << "% VETO=" << (nNever ? 100.0 * bVETO / nNever : 0.0) << "%\n";
  std::cout << "STOP_CLAUSE KNOW>=40 ? " << (bKNOW >= 40 ? "YES (collect baton "
               "after MECH validation)" : "NO (mechanism headroom worth T2)")
            << " [KNOW=" << bKNOW << "/60 gate]\n";
  return 0;
}
