// Right-side ν scan for a fixed weight + N (pool scored once).
//
// Usage:
//   tw538_nu_right_scan <sentences.tsv> <data.txt> <word-bigrams.tsv>
//                       <lambda> <path-char-lstm.bin> <nbest_n> <nu1,nu2,...>
//
// Prints TABLE lines: NU <nu> correct X/Y mean_ms Z
// mean_ms = pool scoring time amortized (same for all ν; pick is free).

#include <chrono>
#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <string>
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

std::vector<double> parseNus(const std::string& s) {
  std::vector<double> out;
  std::stringstream ss(s);
  std::string tok;
  while (std::getline(ss, tok, ',')) {
    if (!tok.empty()) out.push_back(std::stod(tok));
  }
  return out;
}

struct PathScore {
  std::string text;
  double walk = 0;
  double lstm = 0;
};

}  // namespace

int main(int argc, char** argv) {
  if (argc < 8) {
    std::cerr << "Usage: tw538_nu_right_scan sentences data bigrams lambda "
                 "lstm.bin nbest_n nu_csv\n";
    return 1;
  }
  McBopomofoEval::AbortUnlessTw538(argv[1]);
  auto cases = loadCases(argv[1]);
  ParselessLM lm;
  if (!lm.open(argv[2])) return 1;
  CorpusBigramContextModel cm;
  if (!cm.load(argv[3])) return 1;
  cm.setLambda(std::stod(argv[4]));
  NeuralLMPathScorer neural;
  if (!neural.load(argv[5])) return 1;
  size_t nbestN = static_cast<size_t>(std::stoul(argv[6]));
  auto nus = parseNus(argv[7]);

  std::cout << "cases=" << cases.size() << " lambda=" << argv[4]
            << " nbest_n=" << nbestN << " params=" << neural.parameterCount()
            << " nus=";
  for (size_t i = 0; i < nus.size(); ++i) {
    if (i) std::cout << ",";
    std::cout << nus[i];
  }
  std::cout << std::endl;

  struct Item {
    std::string expected;
    std::vector<PathScore> pool;
  };
  std::vector<Item> items;
  items.reserve(cases.size());
  long long prepUs = 0;

  for (const auto& c : cases) {
    ReadingGrid g = makeGrid(&lm);
    if (!feed(g, c.readings)) continue;
    g.setContextModel(&cm);
    auto t0 = std::chrono::steady_clock::now();
    auto nb = g.walkNBest(nbestN);
    Item it;
    it.expected = c.expected;
    it.pool.reserve(nb.size());
    for (const auto& rp : nb) {
      PathScore ps;
      ps.text = joinedWords(rp.words);
      ps.walk = rp.walkScore;
      ps.lstm = neural.scoreSentence(rp.words);
      it.pool.push_back(std::move(ps));
    }
    auto t1 = std::chrono::steady_clock::now();
    prepUs += std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0)
                  .count();
    items.push_back(std::move(it));
  }
  double meanMs =
      items.empty() ? 0.0 : (prepUs / 1000.0) / static_cast<double>(items.size());
  std::cout << "PREP_POOLS " << items.size() << " mean_ms " << meanMs
            << std::endl;

  int bestCorrect = -1;
  double bestNu = 0;
  for (double nu : nus) {
    int correct = 0;
    for (const auto& it : items) {
      if (it.pool.empty()) continue;
      size_t bi = 0;
      double best = -std::numeric_limits<double>::infinity();
      for (size_t i = 0; i < it.pool.size(); ++i) {
        double s = it.pool[i].walk + nu * it.pool[i].lstm;
        if (s > best) {
          best = s;
          bi = i;
        }
      }
      if (it.pool[bi].text == it.expected) ++correct;
    }
    std::cout << "NU " << nu << " correct " << correct << "/" << cases.size()
              << " mean_ms " << meanMs << std::endl;
    if (correct > bestCorrect) {
      bestCorrect = correct;
      bestNu = nu;
    }
  }
  std::cout << "BEST_NU " << bestNu << " correct " << bestCorrect << "/"
            << cases.size() << std::endl;
  return 0;
}
