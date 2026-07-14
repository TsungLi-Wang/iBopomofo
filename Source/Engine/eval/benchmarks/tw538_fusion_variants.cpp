// T2a: fusion formula variants on tw538 (harness-only; does not change engine).
//
// Variants (each full pass over cases):
//   baseline:     final = walk + nu * lstm
//   len_char:     final = walk + nu * (lstm / char_count)
//   len_word:     final = walk + nu * (lstm / word_count)
//   zscore:       final = z(walk) + alpha * z(lstm)   (z over n-best pool)
//   minmax:       final = mm(walk) + alpha * mm(lstm) (mm over n-best pool)
//
// For zscore/minmax, alpha is swept; for length-norm, nu is swept.
//
// Usage:
//   tw538_fusion_variants <sentences.tsv> <data.txt> <word-bigrams.tsv>
//                         <lambda> <path-char-lstm.bin> <nbest_n>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <limits>
#include <numeric>
#include <string>
#include <vector>

#include "CorpusBigramContextModel.h"
#include "NeuralLMPathScorer.h"
#include "ParselessLM.h"
#include "gramambular2/reading_grid.h"

using Formosa::Gramambular2::ReadingGrid;
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

std::string joinedWords(const std::vector<std::string>& words) {
  std::string s;
  for (const auto& w : words) s += w;
  return s;
}

size_t utf8CharCount(const std::string& s) {
  size_t n = 0;
  for (unsigned char c : s) {
    if ((c & 0xC0) != 0x80) ++n;
  }
  return n;
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

struct ScoredPath {
  std::string text;
  double walk = 0;
  double lstm = 0;
  size_t chars = 0;
  size_t words = 0;
};

std::vector<ScoredPath> scorePool(ReadingGrid& g, NeuralLMPathScorer& neural,
                                  size_t nbestN) {
  auto nb = g.walkNBest(nbestN);
  std::vector<ScoredPath> out;
  out.reserve(nb.size());
  for (const auto& rp : nb) {
    ScoredPath sp;
    sp.text = joinedWords(rp.words);
    sp.walk = rp.walkScore;
    sp.lstm = neural.scoreSentence(rp.words);
    sp.chars = std::max<size_t>(1, utf8CharCount(sp.text));
    sp.words = std::max<size_t>(1, rp.words.size());
    out.push_back(std::move(sp));
  }
  return out;
}

std::string pickBaseline(const std::vector<ScoredPath>& pool, double nu) {
  size_t best = 0;
  double bestS = -std::numeric_limits<double>::infinity();
  for (size_t i = 0; i < pool.size(); ++i) {
    double s = pool[i].walk + nu * pool[i].lstm;
    if (s > bestS) {
      bestS = s;
      best = i;
    }
  }
  return pool.empty() ? "" : pool[best].text;
}

std::string pickLenNorm(const std::vector<ScoredPath>& pool, double nu,
                        bool byChar) {
  size_t best = 0;
  double bestS = -std::numeric_limits<double>::infinity();
  for (size_t i = 0; i < pool.size(); ++i) {
    double denom = byChar ? static_cast<double>(pool[i].chars)
                          : static_cast<double>(pool[i].words);
    double s = pool[i].walk + nu * (pool[i].lstm / denom);
    if (s > bestS) {
      bestS = s;
      best = i;
    }
  }
  return pool.empty() ? "" : pool[best].text;
}

std::string pickZScore(const std::vector<ScoredPath>& pool, double alpha) {
  if (pool.empty()) return "";
  if (pool.size() == 1) return pool[0].text;
  double meanW = 0, meanL = 0;
  for (const auto& p : pool) {
    meanW += p.walk;
    meanL += p.lstm;
  }
  meanW /= pool.size();
  meanL /= pool.size();
  double varW = 0, varL = 0;
  for (const auto& p : pool) {
    double dw = p.walk - meanW;
    double dl = p.lstm - meanL;
    varW += dw * dw;
    varL += dl * dl;
  }
  double stdW = std::sqrt(varW / pool.size());
  double stdL = std::sqrt(varL / pool.size());
  if (stdW < 1e-12) stdW = 1.0;
  if (stdL < 1e-12) stdL = 1.0;

  size_t best = 0;
  double bestS = -std::numeric_limits<double>::infinity();
  for (size_t i = 0; i < pool.size(); ++i) {
    double zw = (pool[i].walk - meanW) / stdW;
    double zl = (pool[i].lstm - meanL) / stdL;
    double s = zw + alpha * zl;
    if (s > bestS) {
      bestS = s;
      best = i;
    }
  }
  return pool[best].text;
}

std::string pickMinMax(const std::vector<ScoredPath>& pool, double alpha) {
  if (pool.empty()) return "";
  if (pool.size() == 1) return pool[0].text;
  double minW = pool[0].walk, maxW = pool[0].walk;
  double minL = pool[0].lstm, maxL = pool[0].lstm;
  for (const auto& p : pool) {
    minW = std::min(minW, p.walk);
    maxW = std::max(maxW, p.walk);
    minL = std::min(minL, p.lstm);
    maxL = std::max(maxL, p.lstm);
  }
  double rangeW = maxW - minW;
  double rangeL = maxL - minL;
  if (rangeW < 1e-12) rangeW = 1.0;
  if (rangeL < 1e-12) rangeL = 1.0;

  size_t best = 0;
  double bestS = -std::numeric_limits<double>::infinity();
  for (size_t i = 0; i < pool.size(); ++i) {
    double mw = (pool[i].walk - minW) / rangeW;
    double ml = (pool[i].lstm - minL) / rangeL;
    double s = mw + alpha * ml;
    if (s > bestS) {
      bestS = s;
      best = i;
    }
  }
  return pool[best].text;
}

// Additional: length-normalized both walk and lstm (per-char), then mix.
std::string pickBothLenChar(const std::vector<ScoredPath>& pool, double nu) {
  size_t best = 0;
  double bestS = -std::numeric_limits<double>::infinity();
  for (size_t i = 0; i < pool.size(); ++i) {
    double c = static_cast<double>(pool[i].chars);
    double s = (pool[i].walk / c) + nu * (pool[i].lstm / c);
    if (s > bestS) {
      bestS = s;
      best = i;
    }
  }
  return pool.empty() ? "" : pool[best].text;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 7) {
    std::cerr << "Usage: tw538_fusion_variants sentences data bigrams lambda "
                 "lstm.bin nbest_n\n";
    return 1;
  }
  auto cases = loadCases(argv[1]);
  ParselessLM lm;
  if (!lm.open(argv[2])) return 1;
  CorpusBigramContextModel cm;
  if (!cm.load(argv[3])) return 1;
  cm.setLambda(std::stod(argv[4]));
  NeuralLMPathScorer neural;
  if (!neural.load(argv[5])) return 1;
  size_t nbestN = static_cast<size_t>(std::stoul(argv[6]));

  std::cout << "cases=" << cases.size() << " lambda=" << argv[4]
            << " nbest_n=" << nbestN << " params=" << neural.parameterCount()
            << std::endl;

  // Precompute pools once (expensive)
  struct Item {
    std::string expected;
    std::vector<ScoredPath> pool;
  };
  std::vector<Item> items;
  items.reserve(cases.size());
  long long prepUs = 0;
  for (const auto& c : cases) {
    ReadingGrid g = makeGrid(&lm);
    if (!feed(g, c.readings)) continue;
    g.setContextModel(&cm);
    auto t0 = std::chrono::steady_clock::now();
    auto pool = scorePool(g, neural, nbestN);
    auto t1 = std::chrono::steady_clock::now();
    prepUs += std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0)
                  .count();
    items.push_back({c.expected, std::move(pool)});
  }
  std::cout << "PREP_POOLS " << items.size()
            << " mean_ms=" << (items.empty() ? 0.0 : prepUs / 1000.0 / items.size())
            << std::endl;

  auto evalPick = [&](const char* name, auto picker) {
    int correct = 0;
    auto t0 = std::chrono::steady_clock::now();
    for (const auto& it : items) {
      if (it.pool.empty()) continue;
      std::string pred = picker(it.pool);
      if (pred == it.expected) ++correct;
    }
    auto t1 = std::chrono::steady_clock::now();
    double meanMs =
        items.empty()
            ? 0.0
            : std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0)
                      .count() /
                  1000.0 / items.size();
    // Total latency ≈ prep pool mean + pick mean (pool already includes LSTM)
    std::cout << "VARIANT " << name << " correct " << correct << "/"
              << cases.size() << " pick_mean_ms " << meanMs
              << " (pool_prep_mean_ms included separately)" << std::endl;
  };

  // Baseline nu sweep
  for (double nu : {0.25, 0.5, 0.75, 1.0}) {
    evalPick(("baseline_nu" + std::to_string(nu)).c_str(),
             [nu](const std::vector<ScoredPath>& p) {
               return pickBaseline(p, nu);
             });
  }
  // Force print baseline with exact names for table
  for (double nu : {0.25, 0.5, 0.75}) {
    int correct = 0;
    for (const auto& it : items) {
      if (pickBaseline(it.pool, nu) == it.expected) ++correct;
    }
    std::cout << "TABLE baseline nu=" << nu << " correct " << correct << "/"
              << cases.size() << std::endl;
  }

  // (1) length norm LSTM only
  for (double nu : {0.25, 0.5, 0.75, 1.0, 2.0, 4.0, 8.0, 16.0}) {
    int cChar = 0, cWord = 0;
    for (const auto& it : items) {
      if (pickLenNorm(it.pool, nu, true) == it.expected) ++cChar;
      if (pickLenNorm(it.pool, nu, false) == it.expected) ++cWord;
    }
    std::cout << "TABLE len_char nu=" << nu << " correct " << cChar << "/"
              << cases.size() << std::endl;
    std::cout << "TABLE len_word nu=" << nu << " correct " << cWord << "/"
              << cases.size() << std::endl;
  }

  // both length-norm
  for (double nu : {0.25, 0.5, 0.75, 1.0, 2.0, 4.0}) {
    int c = 0;
    for (const auto& it : items) {
      if (pickBothLenChar(it.pool, nu) == it.expected) ++c;
    }
    std::cout << "TABLE both_len_char nu=" << nu << " correct " << c << "/"
              << cases.size() << std::endl;
  }

  // (2) z-score / minmax alpha sweep
  for (double alpha :
       {0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0}) {
    int cz = 0, cm = 0;
    for (const auto& it : items) {
      if (pickZScore(it.pool, alpha) == it.expected) ++cz;
      if (pickMinMax(it.pool, alpha) == it.expected) ++cm;
    }
    std::cout << "TABLE zscore alpha=" << alpha << " correct " << cz << "/"
              << cases.size() << std::endl;
    std::cout << "TABLE minmax alpha=" << alpha << " correct " << cm << "/"
              << cases.size() << std::endl;
  }

  // Latency sample for best-looking recipes at end (re-run pick only)
  std::cout << "DONE" << std::endl;
  return 0;
}
