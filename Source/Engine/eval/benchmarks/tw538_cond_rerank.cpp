// CondConverter PathScorer fusion + optional 3-way mix with Neural LSTM.
//
// Usage:
//   tw538_cond_rerank <sentences.tsv> <data.txt> <bigrams.tsv> <lambda>
//                     <cond.bin> [lstm.bin]
//
// Prints:
//   COND_ONLY NU <nu> correct X/Y mean_ms Z   (if no lstm)
//   MIX nu=<nu> kappa=<k> correct X/Y mean_ms Z  (if lstm given)
//
// Cond syllables = case readings (hard constraint). N-best N=10.

#include <chrono>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

#include "CondPathScorer.h"
#include "CorpusBigramContextModel.h"
#include "NeuralLMPathScorer.h"
#include "ParselessLM.h"
#include "gramambular2/reading_grid.h"

using Formosa::Gramambular2::ReadingGrid;
using McBopomofo::CondPathScorer;
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

struct PoolItem {
  std::string text;
  double walk = 0;
  double cond = 0;
  double lstm = 0;
};

}  // namespace

int main(int argc, char** argv) {
  if (argc < 6) {
    std::cerr << "Usage: tw538_cond_rerank sentences data bigrams lambda "
                 "cond.bin [lstm.bin]\n";
    return 1;
  }
  auto cases = loadCases(argv[1]);
  ParselessLM lm;
  if (!lm.open(argv[2])) return 1;
  CorpusBigramContextModel cm;
  if (!cm.load(argv[3])) return 1;
  cm.setLambda(std::stod(argv[4]));

  CondPathScorer cond;
  if (!cond.load(argv[5])) {
    std::cerr << "cond load fail\n";
    return 1;
  }
  std::cout << "cond_params=" << cond.parameterCount() << std::endl;

  NeuralLMPathScorer neural;
  bool hasLstm = false;
  if (argc > 6 && argv[6][0] != '\0') {
    hasLstm = neural.load(argv[6]);
    std::cout << "lstm_loaded=" << hasLstm
              << " params=" << neural.parameterCount() << std::endl;
  }

  const size_t nbestN = 10;
  std::vector<std::vector<PoolItem>> allPools;
  allPools.reserve(cases.size());
  std::vector<std::string> expecteds;
  std::vector<std::string> keptReadings;
  long long prepUs = 0;
  int walkOn = 0;

  for (const auto& c : cases) {
    ReadingGrid g = makeGrid(&lm);
    if (!feed(g, c.readings)) continue;
    g.setContextModel(&cm);
    auto t0 = std::chrono::steady_clock::now();
    auto nb = g.walkNBest(nbestN);
    // walk top
    if (!nb.empty() && joinedWords(nb[0].words) == c.expected) ++walkOn;

    cond.setSyllables(splitSyllables(c.readings));
    std::vector<PoolItem> pool;
    pool.reserve(nb.size());
    for (const auto& rp : nb) {
      PoolItem it;
      it.text = joinedWords(rp.words);
      it.walk = rp.walkScore;
      it.cond = cond.scoreSentence(rp.words);
      if (hasLstm) it.lstm = neural.scoreSentence(rp.words);
      pool.push_back(std::move(it));
    }
    auto t1 = std::chrono::steady_clock::now();
    prepUs += std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0)
                  .count();
    allPools.push_back(std::move(pool));
    expecteds.push_back(c.expected);
    keptReadings.push_back(c.readings);
  }
  double meanMs = allPools.empty()
                      ? 0.0
                      : (prepUs / 1000.0) / static_cast<double>(allPools.size());
  std::cout << "PREP cases=" << allPools.size()
            << " walk_top≈" << walkOn << "/" << cases.size()
            << " pool_mean_ms=" << meanMs << std::endl;

  auto pick = [](const std::vector<PoolItem>& pool, double nu, double kappa,
                 bool useLstm) -> std::string {
    if (pool.empty()) return "";
    size_t bi = 0;
    double best = -std::numeric_limits<double>::infinity();
    for (size_t i = 0; i < pool.size(); ++i) {
      double s = pool[i].walk + nu * pool[i].cond;
      if (useLstm) s += kappa * pool[i].lstm;
      if (s > best) {
        best = s;
        bi = i;
      }
    }
    return pool[bi].text;
  };

  // Cond-only ν scan
  for (double nu : {0.0, 0.25, 0.5, 0.75, 1.0}) {
    int correct = 0;
    for (size_t i = 0; i < allPools.size(); ++i) {
      if (pick(allPools[i], nu, 0.0, false) == expecteds[i]) ++correct;
    }
    std::cout << "COND_ONLY NU " << nu << " correct " << correct << "/"
              << cases.size() << " mean_ms " << meanMs << std::endl;
  }

  if (hasLstm) {
    // Reference: LSTM only (as control on same pools)
    for (double nu : {0.5, 0.75}) {
      int correct = 0;
      for (size_t i = 0; i < allPools.size(); ++i) {
        // walk + nu * lstm
        size_t bi = 0;
        double best = -std::numeric_limits<double>::infinity();
        for (size_t j = 0; j < allPools[i].size(); ++j) {
          double s = allPools[i][j].walk + nu * allPools[i][j].lstm;
          if (s > best) {
            best = s;
            bi = j;
          }
        }
        if (allPools[i][bi].text == expecteds[i]) ++correct;
      }
      std::cout << "LSTM_ONLY NU " << nu << " correct " << correct << "/"
                << cases.size() << " mean_ms " << meanMs << std::endl;
    }
    // 3-way: walk + nu*lstm + kappa*cond ; fix nu at 0.75 (v2c best), sweep kappa
    // Also sweep nu a bit
    for (double nu : {0.5, 0.75}) {
      for (double kappa : {0.25, 0.5, 1.0}) {
        int correct = 0;
        for (size_t i = 0; i < allPools.size(); ++i) {
          if (pick(allPools[i], kappa, nu, true) == expecteds[i]) ++correct;
        }
        // pick uses: walk + nu_arg*cond + kappa_arg*lstm when useLstm
        // we want walk + nu*lstm + kappa*cond → pass kappa as first (cond), nu as second (lstm)
        std::cout << "MIX nu_lstm=" << nu << " kappa_cond=" << kappa
                  << " correct " << correct << "/" << cases.size()
                  << " mean_ms " << meanMs << std::endl;
      }
    }

    // Error dump for A-class single_char_swap attribution (classified in
    // Python). Dumps wrong cases for two configs on the SAME cached pools:
    //   (a) v2c-only  walk + 0.75*lstm      (reproduces the 387 baseline)
    //   (b) best mix  walk + 0.5*lstm + 0.25*cond
    // Fields: DUMP <tag> <reading> <expected> <chosen> <inpool 0/1>
    auto pickMix = [](const std::vector<PoolItem>& pool, double nuL,
                      double kCond) -> std::string {
      if (pool.empty()) return "";
      size_t bi = 0;
      double best = -std::numeric_limits<double>::infinity();
      for (size_t i = 0; i < pool.size(); ++i) {
        double s = pool[i].walk + nuL * pool[i].lstm + kCond * pool[i].cond;
        if (s > best) { best = s; bi = i; }
      }
      return pool[bi].text;
    };
    auto inPool = [](const std::vector<PoolItem>& pool,
                     const std::string& exp) -> bool {
      for (const auto& it : pool) if (it.text == exp) return true;
      return false;
    };
    struct Cfg { const char* tag; double nuL; double kCond; };
    for (Cfg cfg : {Cfg{"V2C", 0.75, 0.0}, Cfg{"MIX", 0.5, 0.25}}) {
      for (size_t i = 0; i < allPools.size(); ++i) {
        std::string chosen = pickMix(allPools[i], cfg.nuL, cfg.kCond);
        if (chosen == expecteds[i]) continue;
        std::cout << "DUMP " << cfg.tag << "\t" << keptReadings[i] << "\t"
                  << expecteds[i] << "\t" << chosen << "\t"
                  << (inPool(allPools[i], expecteds[i]) ? 1 : 0) << std::endl;
      }
    }
  }
  return 0;
}
