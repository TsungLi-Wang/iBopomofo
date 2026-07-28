// Homophone discrimination GO/NO-GO measurement harness (research only).
// Does not modify product code. Uses shipped NeuralLMPathScorer + walk.
//
// Usage:
//   homophone_measure <tw538.tsv> <data.txt> <word-bigrams.tsv> <lambda>
//                     <path-char-lstm.bin> <nu> <reading2chars.tsv>
//                     <out_dir>
//
// Writes:
//   shipping_preds.tsv, residual-entropy.tsv, flip-oracle.tsv, summary.txt
// And prints key metrics to stdout.

#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <map>
#include <numeric>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "CorpusBigramContextModel.h"
#include "NeuralLMPathScorer.h"
#include "ParselessLM.h"
#include "gramambular2/reading_grid.h"

#include "../benchmark_gate.h"

using Formosa::Gramambular2::ReadingGrid;
using McBopomofo::CorpusBigramContextModel;
using McBopomofo::NeuralLMPathScorer;
using McBopomofo::ParselessLM;

namespace {

std::vector<std::string> splitSyllables(const std::string& r) {
  std::vector<std::string> out;
  size_t s = 0;
  for (size_t i = 0; i < r.size(); ++i) {
    if (r[i] == '-') {
      if (i > s) out.push_back(r.substr(s, i - s));
      s = i + 1;
    }
  }
  if (s < r.size()) out.push_back(r.substr(s));
  return out;
}

// UTF-8 codepoint split (same spirit as NeuralLMPathScorer::flattenChars).
std::vector<std::string> utf8Chars(const std::string& s) {
  std::vector<std::string> chars;
  size_t i = 0;
  while (i < s.size()) {
    unsigned char c = static_cast<unsigned char>(s[i]);
    size_t len = 1;
    if ((c & 0x80) == 0)
      len = 1;
    else if ((c & 0xE0) == 0xC0)
      len = 2;
    else if ((c & 0xF0) == 0xE0)
      len = 3;
    else if ((c & 0xF8) == 0xF0)
      len = 4;
    if (i + len > s.size()) len = 1;
    chars.push_back(s.substr(i, len));
    i += len;
  }
  return chars;
}

ReadingGrid makeGrid(ParselessLM* lm) {
  ReadingGrid g(std::shared_ptr<Formosa::Gramambular2::LanguageModel>(
      lm, [](Formosa::Gramambular2::LanguageModel*) {}));
  g.setReadingSeparator("-");
  return g;
}

bool feed(ReadingGrid& g, const std::string& r) {
  for (const auto& syl : splitSyllables(r)) {
    g.setCursor(g.length());
    if (!g.insertReading(syl)) return false;
  }
  return true;
}

std::string joined(const ReadingGrid::WalkResult& w) {
  std::string s;
  for (size_t i = 0; i < w.nodes.size(); ++i) s += w.chosenValueAt(i);
  return s;
}

std::string joinedWords(const std::vector<std::string>& words) {
  std::string s;
  for (const auto& w : words) s += w;
  return s;
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
    size_t t = line.find('\t');
    if (t == std::string::npos) continue;
    cases.push_back({line.substr(0, t), line.substr(t + 1)});
  }
  return cases;
}

// reading -> ordered list of (char, count)
using CandList = std::vector<std::pair<std::string, int>>;
std::unordered_map<std::string, CandList> loadReading2Chars(
    const std::string& path) {
  std::unordered_map<std::string, CandList> m;
  std::ifstream in(path);
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty() || line[0] == '#') continue;
    size_t t = line.find('\t');
    if (t == std::string::npos) continue;
    std::string reading = line.substr(0, t);
    std::string body = line.substr(t + 1);
    CandList list;
    size_t i = 0;
    while (i < body.size()) {
      size_t colon = body.find(':', i);
      if (colon == std::string::npos) break;
      std::string ch = body.substr(i, colon - i);
      size_t comma = body.find(',', colon + 1);
      std::string num =
          comma == std::string::npos
              ? body.substr(colon + 1)
              : body.substr(colon + 1, comma - (colon + 1));
      int cnt = 0;
      try {
        cnt = std::stoi(num);
      } catch (...) {
        cnt = 0;
      }
      list.emplace_back(ch, cnt);
      if (comma == std::string::npos) break;
      i = comma + 1;
    }
    m[reading] = std::move(list);
  }
  return m;
}

double medianOf(std::vector<double> v) {
  if (v.empty()) return 0;
  std::sort(v.begin(), v.end());
  size_t n = v.size();
  if (n % 2 == 1) return v[n / 2];
  return 0.5 * (v[n / 2 - 1] + v[n / 2]);
}

double meanOf(const std::vector<double>& v) {
  if (v.empty()) return 0;
  double s = 0;
  for (double x : v) s += x;
  return s / static_cast<double>(v.size());
}

// Score full sentence as char stream via scoreSentence({full_string as one
// word}) — flattenChars will split UTF-8. Using single-word path.
double scoreFull(NeuralLMPathScorer& scorer, const std::string& text) {
  if (text.empty()) return 0;
  return scorer.scoreSentence({text});
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 9) {
    std::cerr
        << "Usage: homophone_measure tw538 data bigrams lambda lstm nu "
           "reading2chars out_dir\n";
    return 1;
  }
  const std::string casesPath = argv[1];
  const std::string dataPath = argv[2];
  const std::string bigramPath = argv[3];
  const double lambda = std::stod(argv[4]);
  const std::string lstmPath = argv[5];
  const double nu = std::stod(argv[6]);
  const std::string r2cPath = argv[7];
  const std::string outDir = argv[8];

  std::cout << std::unitbuf;
  std::cerr << std::unitbuf;
  McBopomofoEval::AbortUnlessTw538(casesPath.c_str());
  auto cases = loadCases(casesPath);
  ParselessLM lm;
  if (!lm.open(dataPath.c_str())) {
    std::cerr << "fail open data\n";
    return 1;
  }
  CorpusBigramContextModel cm;
  if (!cm.load(bigramPath)) {
    std::cerr << "fail load bigrams\n";
    return 1;
  }
  cm.setLambda(lambda);
  NeuralLMPathScorer scorer;
  if (!scorer.load(lstmPath)) {
    std::cerr << "fail load lstm\n";
    return 1;
  }
  auto r2c = loadReading2Chars(r2cPath);
  std::cout << "loaded cases=" << cases.size() << " readings_in_map=" << r2c.size()
            << " lstm_params=" << scorer.parameterCount() << "\n";

  // ---------- shipping predictions ----------
  std::vector<std::string> preds(cases.size());
  std::vector<bool> correct(cases.size());
  std::vector<bool> goldInPool(cases.size(), false);
  int shipCorrect = 0;
  for (size_t i = 0; i < cases.size(); ++i) {
    ReadingGrid g = makeGrid(&lm);
    if (!feed(g, cases[i].readings)) {
      preds[i] = "";
      correct[i] = false;
      continue;
    }
    g.setContextModel(&cm);
    g.setPathScorer(&scorer);
    g.setPathRerankNu(nu);
    g.setPathRerankNBest(10);
    auto w = g.walk();
    preds[i] = joined(w);
    correct[i] = (preds[i] == cases[i].expected);
    if (correct[i]) ++shipCorrect;
    // gold in n-best pool?
    auto nb = g.walkNBest(10);
    for (const auto& p : nb) {
      if (joinedWords(p.words) == cases[i].expected) {
        goldInPool[i] = true;
        break;
      }
    }
  }
  std::cout << "SHIPPING_CORRECT " << shipCorrect << "/" << cases.size() << "\n";
  if (shipCorrect != 387) {
    std::cout << "ABORT: shipping != 387\n";
    return 2;
  }

  // ---------- step 2 coverage + step 3 char acc ----------
  int totalChars = 0;
  int coverOk = 0;
  int charOk = 0;
  std::vector<std::string> coverFails;
  for (size_t si = 0; si < cases.size(); ++si) {
    auto syls = splitSyllables(cases[si].readings);
    auto gchars = utf8Chars(cases[si].expected);
    auto pchars = utf8Chars(preds[si]);
    // Align: 1:1 when lengths match; else pair min and mark extras
    size_t nAlign = std::min(syls.size(), gchars.size());
    for (size_t i = 0; i < gchars.size(); ++i) {
      ++totalChars;
      std::string reading;
      if (i < syls.size())
        reading = syls[i];
      else
        reading = "<NO_READING>";
      bool inSet = false;
      if (i < syls.size()) {
        auto it = r2c.find(reading);
        if (it != r2c.end()) {
          for (const auto& kv : it->second) {
            if (kv.first == gchars[i]) {
              inSet = true;
              break;
            }
          }
        }
      }
      if (inSet)
        ++coverOk;
      else {
        std::ostringstream oss;
        oss << "sent=" << si << " pos=" << i << " reading=" << reading
            << " gold=" << gchars[i];
        coverFails.push_back(oss.str());
      }
      if (i < pchars.size() && pchars[i] == gchars[i]) ++charOk;
    }
    (void)nAlign;
  }
  double coverRate = totalChars ? 100.0 * coverOk / totalChars : 0;
  double charRate = totalChars ? 100.0 * charOk / totalChars : 0;
  double avgLen = cases.empty() ? 0 : static_cast<double>(totalChars) / cases.size();
  std::cout << "TOTAL_CHARS " << totalChars << "\n";
  std::cout << "AVG_SENT_LEN " << avgLen << "\n";
  std::cout << "COVER_OK " << coverOk << "/" << totalChars << " rate=" << coverRate
            << "%\n";
  std::cout << "CHAR_OK " << charOk << "/" << totalChars << " rate=" << charRate
            << "%\n";
  std::cout << "SENT_OK " << shipCorrect << "/" << cases.size() << " rate="
            << (100.0 * shipCorrect / cases.size()) << "%\n";
  std::cout << "COVER_FAIL_COUNT " << coverFails.size() << "\n";
  for (const auto& f : coverFails) std::cout << "COVER_FAIL " << f << "\n";

  if (coverRate < 99.0) {
    std::cout << "ABORT: coverage < 99%\n";
    // still write fails; caller decides — baton says stop before step 3/4/5
    // We already did char stats; stop before entropy/flip.
    std::ofstream sf(outDir + "/summary_partial.txt");
    sf << "coverage_abort rate=" << coverRate << "\n";
    return 3;
  }

  // ---------- step 4 residual entropy ----------
  std::ofstream entOut(outDir + "/tw538-residual-entropy.tsv");
  entOut << "sent_idx\tpos\treading\tgold\tpred\tcorrect\tH_bits\tgold_rank\t"
            "gold_prob\t|C|\n";

  struct Bucket {
    std::vector<double> H;
  };
  Bucket allB, okB, errB, errHighB, errLowB;
  std::map<int, int> rankHist;  // rank -> count among errors only; rank 2,3,4,>=5
  int rank2 = 0, rank3 = 0, rank4 = 0, rankGe5 = 0, rank1err = 0, rankMiss = 0;

  auto tEnt0 = std::chrono::steady_clock::now();
  for (size_t si = 0; si < cases.size(); ++si) {
    auto syls = splitSyllables(cases[si].readings);
    auto gchars = utf8Chars(cases[si].expected);
    auto pchars = utf8Chars(preds[si]);
    size_t n = std::min(syls.size(), gchars.size());
    for (size_t i = 0; i < n; ++i) {
      const std::string& reading = syls[i];
      const std::string& gold = gchars[i];
      std::string pred = (i < pchars.size()) ? pchars[i] : "";
      bool posOk = (pred == gold);

      // candidates
      CandList cands;
      auto it = r2c.find(reading);
      if (it != r2c.end()) cands = it->second;
      // ensure gold in set for scoring
      bool hasGold = false;
      for (const auto& kv : cands)
        if (kv.first == gold) hasGold = true;
      if (!hasGold && !gold.empty()) cands.emplace_back(gold, 0);

      // teacher-forced prefix = gold[0..i)
      std::string prefix;
      for (size_t j = 0; j < i; ++j) prefix += gchars[j];
      std::vector<std::string> prefixWords;
      if (!prefix.empty()) prefixWords.push_back(prefix);

      // log10 P for each candidate via scoreContinuation
      std::vector<std::pair<std::string, double>> scored;
      scored.reserve(cands.size());
      double maxLog = -1e300;
      for (const auto& kv : cands) {
        double lp = scorer.scoreContinuation(prefixWords, kv.first);
        scored.emplace_back(kv.first, lp);
        if (lp > maxLog) maxLog = lp;
      }
      // convert log10 -> natural log for softmax: ln p ∝ lp * ln(10)
      const double ln10 = std::log(10.0);
      double sumExp = 0;
      std::vector<double> probs(scored.size());
      for (size_t k = 0; k < scored.size(); ++k) {
        double x = (scored[k].second - maxLog) * ln10;
        probs[k] = std::exp(x);
        sumExp += probs[k];
      }
      for (size_t k = 0; k < probs.size(); ++k) probs[k] /= sumExp;

      // entropy bits
      double H = 0;
      for (double p : probs) {
        if (p > 0) H -= p * (std::log(p) / std::log(2.0));
      }

      // gold rank (1-based) & prob
      int goldRank = -1;
      double goldProb = 0;
      std::vector<size_t> order(scored.size());
      std::iota(order.begin(), order.end(), 0);
      std::sort(order.begin(), order.end(), [&](size_t a, size_t b) {
        return probs[a] > probs[b];
      });
      for (size_t r = 0; r < order.size(); ++r) {
        if (scored[order[r]].first == gold) {
          goldRank = static_cast<int>(r + 1);
          goldProb = probs[order[r]];
          break;
        }
      }

      entOut << si << '\t' << i << '\t' << reading << '\t' << gold << '\t'
             << pred << '\t' << (posOk ? 1 : 0) << '\t' << H << '\t' << goldRank
             << '\t' << goldProb << '\t' << cands.size() << '\n';

      allB.H.push_back(H);
      if (posOk)
        okB.H.push_back(H);
      else {
        errB.H.push_back(H);
        if (H >= 1.0) errHighB.H.push_back(H);
        if (H < 0.5) errLowB.H.push_back(H);
        if (goldRank == 1)
          ++rank1err;
        else if (goldRank == 2)
          ++rank2;
        else if (goldRank == 3)
          ++rank3;
        else if (goldRank == 4)
          ++rank4;
        else if (goldRank >= 5)
          ++rankGe5;
        else
          ++rankMiss;
      }
    }
    if ((si + 1) % 50 == 0) {
      std::cerr << "entropy progress " << (si + 1) << "/" << cases.size()
                << "\n";
    }
  }
  auto tEnt1 = std::chrono::steady_clock::now();
  double entSec =
      std::chrono::duration<double>(tEnt1 - tEnt0).count();
  std::cout << "ENTROPY_SECONDS " << entSec << "\n";

  auto dumpBucket = [](const char* name, const Bucket& b) {
    std::cout << "BUCKET " << name << " n=" << b.H.size()
              << " meanH=" << meanOf(b.H) << " medianH=" << medianOf(b.H)
              << "\n";
  };
  dumpBucket("all", allB);
  dumpBucket("correct", okB);
  dumpBucket("wrong", errB);
  dumpBucket("wrong_highH_ge1", errHighB);
  dumpBucket("wrong_lowH_lt0.5", errLowB);
  int errN = static_cast<int>(errB.H.size());
  std::cout << "ERR_GOLD_RANK1 " << rank1err << "\n";
  std::cout << "ERR_GOLD_RANK2 " << rank2 << " frac="
            << (errN ? 100.0 * rank2 / errN : 0) << "%\n";
  std::cout << "ERR_GOLD_RANK3 " << rank3 << " frac="
            << (errN ? 100.0 * rank3 / errN : 0) << "%\n";
  std::cout << "ERR_GOLD_RANK4 " << rank4 << " frac="
            << (errN ? 100.0 * rank4 / errN : 0) << "%\n";
  std::cout << "ERR_GOLD_RANK_GE5 " << rankGe5 << " frac="
            << (errN ? 100.0 * rankGe5 / errN : 0) << "%\n";
  std::cout << "ERR_GOLD_RANK_MISS " << rankMiss << "\n";

  // ---------- step 5 single-flip oracle (2 rounds) ----------
  // Perfect discriminator upper bound
  int perfect = 0;
  for (size_t si = 0; si < cases.size(); ++si) {
    // if every position could pick gold via reading alignment...
    auto syls = splitSyllables(cases[si].readings);
    auto gchars = utf8Chars(cases[si].expected);
    bool ok = true;
    if (syls.size() != gchars.size()) {
      // still could be perfect if we only care about producing gold string
      // baton: theoretically 537 if 100% reading-char aligned
      ok = false;
    } else {
      for (size_t i = 0; i < gchars.size(); ++i) {
        auto it = r2c.find(syls[i]);
        bool found = false;
        if (it != r2c.end()) {
          for (const auto& kv : it->second)
            if (kv.first == gchars[i]) found = true;
        }
        if (!found) ok = false;
      }
    }
    if (ok) ++perfect;
  }
  // baton also says perfect discriminator on aligned positions → full gold string
  // count sentences where we CAN form gold by picking from each C_i
  std::cout << "PERFECT_DISCRIMINATOR_REACHABLE " << perfect << "/"
            << cases.size() << "\n";

  auto tFlip0 = std::chrono::steady_clock::now();
  int correctR1 = 0, correctR2 = 0;
  std::vector<std::string> afterR1(cases.size()), afterR2(cases.size());
  std::ofstream flipOut(outDir + "/flip-oracle-detail.tsv");
  flipOut << "sent_idx\tround\tpos\tfrom\tto\tscore_before\tscore_after\t"
             "orig_pred\tgold\twas_correct\tnow_correct\tgold_in_pool\n";

  struct FlipEvent {
    size_t si;
    std::string before, after, gold;
    bool wasCorrect, nowCorrect, inPool;
  };
  std::vector<FlipEvent> rescues, regresses;

  for (size_t si = 0; si < cases.size(); ++si) {
    auto syls = splitSyllables(cases[si].readings);
    auto gchars = utf8Chars(cases[si].expected);
    std::string S = preds[si];
    auto Schars = utf8Chars(S);
    // pad/truncate Schars to gchars length for position flips?
    // Work on character positions of S; if |S|!=|gold|, still flip within S.
    // Use reading alignment length = min(syls, Schars) when possible.
    // Prefer gold length when |S|==|gold|.
    size_t nPos = Schars.size();
    // If lengths mismatch with readings, still try per-char of S with reading i
    // if i < syls.size().

    double scoreS = scoreFull(scorer, S);
    bool wasCorrect = correct[si];

    auto runRound = [&](int round) -> bool {
      // Batch all single-position flips with scoreNBest (prefix trie sharing).
      // paths[0] = current S; remaining = each (i,c) flip.
      std::vector<std::vector<std::string>> paths;
      std::vector<std::pair<int, std::string>> meta;  // pos, char for paths[1..]
      paths.push_back({S});
      for (size_t i = 0; i < nPos; ++i) {
        if (i >= syls.size()) continue;
        const std::string& reading = syls[i];
        auto it = r2c.find(reading);
        if (it == r2c.end()) continue;
        for (const auto& kv : it->second) {
          const std::string& c = kv.first;
          if (c == Schars[i]) continue;
          std::string Sp;
          for (size_t j = 0; j < Schars.size(); ++j) {
            if (j == i)
              Sp += c;
            else
              Sp += Schars[j];
          }
          paths.push_back({Sp});
          meta.emplace_back(static_cast<int>(i), c);
        }
      }
      if (paths.size() <= 1) return false;
      auto scores = scorer.scoreNBest(paths);
      double bestScore = scores[0];
      int bestIdx = -1;  // index into meta / paths[1..]
      for (size_t k = 1; k < scores.size(); ++k) {
        if (scores[k] > bestScore) {
          bestScore = scores[k];
          bestIdx = static_cast<int>(k - 1);
        }
      }
      if (bestIdx < 0) return false;
      int bestPos = meta[static_cast<size_t>(bestIdx)].first;
      std::string bestChar = meta[static_cast<size_t>(bestIdx)].second;
      std::string bestS = paths[static_cast<size_t>(bestIdx + 1)][0];
      std::string from = Schars[static_cast<size_t>(bestPos)];
      flipOut << si << '\t' << round << '\t' << bestPos << '\t' << from << '\t'
              << bestChar << '\t' << scores[0] << '\t' << bestScore << '\t'
              << preds[si] << '\t' << cases[si].expected << '\t'
              << (wasCorrect ? 1 : 0) << '\t'
              << (bestS == cases[si].expected ? 1 : 0) << '\t'
              << (goldInPool[si] ? 1 : 0) << '\n';
      S = bestS;
      Schars = utf8Chars(S);
      nPos = Schars.size();
      scoreS = bestScore;
      return true;
    };

  bool f1 = runRound(1);
    afterR1[si] = S;
    if (afterR1[si] == cases[si].expected) ++correctR1;
    if (f1) {
      runRound(2);
    }
    afterR2[si] = S;
    if (afterR2[si] == cases[si].expected) ++correctR2;

    bool nowCorrect = (afterR2[si] == cases[si].expected);
    if (!wasCorrect && nowCorrect) {
      rescues.push_back({si, preds[si], afterR2[si], cases[si].expected, false,
                         true, goldInPool[si]});
    }
    if (wasCorrect && !nowCorrect) {
      regresses.push_back({si, preds[si], afterR2[si], cases[si].expected, true,
                           false, goldInPool[si]});
    }

    if ((si + 1) % 25 == 0) {
      std::cerr << "flip progress " << (si + 1) << "/" << cases.size()
                << " r2_correct_so_far=" << correctR2 << "\n";
    }
  }
  // recompute correctR1/R2 carefully (already counted)
  auto tFlip1 = std::chrono::steady_clock::now();
  double flipSec = std::chrono::duration<double>(tFlip1 - tFlip0).count();

  int rescueA = 0, rescueB = 0;
  for (const auto& e : rescues) {
    if (e.inPool)
      ++rescueA;
    else
      ++rescueB;
  }

  std::cout << "FLIP_SECONDS " << flipSec << "\n";
  std::cout << "FLIP_R1_CORRECT " << correctR1 << "/" << cases.size()
            << " delta=" << (correctR1 - shipCorrect) << "\n";
  std::cout << "FLIP_R2_CORRECT " << correctR2 << "/" << cases.size()
            << " delta=" << (correctR2 - shipCorrect) << "\n";
  std::cout << "RESCUE_COUNT " << rescues.size() << " A=" << rescueA
            << " B=" << rescueB << "\n";
  std::cout << "REGRESS_COUNT " << regresses.size() << "\n";
  for (const auto& e : rescues) {
    std::cout << "RESCUE idx=" << e.si << " pool=" << (e.inPool ? "A" : "B")
              << "\n  pred=" << e.before << "\n  flip=" << e.after
              << "\n  gold=" << e.gold << "\n";
  }
  for (const auto& e : regresses) {
    std::cout << "REGRESS idx=" << e.si << " pool=" << (e.inPool ? "A" : "B")
              << "\n  pred=" << e.before << "\n  flip=" << e.after
              << "\n  gold=" << e.gold << "\n";
  }

  int net = correctR2 - shipCorrect;
  std::string decision;
  if (net >= 30)
    decision = "GO";
  else if (net >= 15)
    decision = "MARGINAL";
  else
    decision = "NO-GO";
  std::cout << "NET_GAIN_R2 " << net << "\n";
  std::cout << "DECISION " << decision << "\n";
  std::cout << "NOTE flip score = v2c scoreSentence only; walk score NOT used "
               "(flipped text may leave lattice).\n";

  // write summary
  std::ofstream sum(outDir + "/summary.txt");
  sum << "SHIPPING_CORRECT " << shipCorrect << "\n";
  sum << "FLIP_R1_CORRECT " << correctR1 << "\n";
  sum << "FLIP_R2_CORRECT " << correctR2 << "\n";
  sum << "NET_GAIN_R2 " << net << "\n";
  sum << "DECISION " << decision << "\n";
  sum << "RESCUE_COUNT " << rescues.size() << " A=" << rescueA
      << " B=" << rescueB << "\n";
  sum << "REGRESS_COUNT " << regresses.size() << "\n";
  sum << "TOTAL_CHARS " << totalChars << "\n";
  sum << "CHAR_OK " << charOk << "\n";
  sum << "COVER_OK " << coverOk << "\n";

  // preds dump
  std::ofstream predOut(outDir + "/shipping_preds.tsv");
  for (size_t i = 0; i < cases.size(); ++i) {
    predOut << i << '\t' << (correct[i] ? 1 : 0) << '\t'
            << (goldInPool[i] ? 1 : 0) << '\t' << preds[i] << '\t'
            << cases[i].expected << '\n';
  }

  return 0;
}
