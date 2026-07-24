// Scan n-best pool size N and fusion nu on tw538.
//
// Usage:
//   nbest_n_nu_scan <sentences.tsv> <data.txt> <word-bigrams.tsv>
//                   <lambda> <path-char-lstm.bin>
//                   <n_list_csv> <nu_list_csv>
//
// Example n_list: 10,20,30,50
// Example nu_list: 0.25,0.5,0.75
//
// Prints for each N: IN_POOL count, then for each nu: CORRECT + mean_ms.

#include <chrono>
#include <fstream>
#include <iostream>
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

std::string joinedWalk(const ReadingGrid::WalkResult& w) {
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
    size_t tab = line.find('\t');
    if (tab == std::string::npos) continue;
    cases.push_back({line.substr(0, tab), line.substr(tab + 1)});
  }
  return cases;
}

std::vector<double> parseList(const std::string& csv) {
  std::vector<double> out;
  std::stringstream ss(csv);
  std::string item;
  while (std::getline(ss, item, ',')) {
    if (!item.empty()) out.push_back(std::stod(item));
  }
  return out;
}

std::vector<size_t> parseSizeList(const std::string& csv) {
  std::vector<size_t> out;
  std::stringstream ss(csv);
  std::string item;
  while (std::getline(ss, item, ',')) {
    if (!item.empty()) out.push_back(static_cast<size_t>(std::stoul(item)));
  }
  return out;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 8) {
    std::cerr << "Usage: nbest_n_nu_scan sentences data bigrams lambda lstm "
                 "n_list nu_list\n";
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
  auto nList = parseSizeList(argv[6]);
  auto nuList = parseList(argv[7]);

  std::cout << "cases=" << cases.size()
            << " params=" << neural.parameterCount() << "\n";

  for (size_t N : nList) {
    int inPool = 0;
    int scored = 0;
    for (const auto& c : cases) {
      ReadingGrid g = makeGrid(&lm);
      if (!feed(g, c.readings)) continue;
      g.setContextModel(&cm);
      auto nb = g.walkNBest(N);
      ++scored;
      for (const auto& rp : nb) {
        if (joinedWords(rp.words) == c.expected) {
          ++inPool;
          break;
        }
      }
    }
    std::cout << "N " << N << " IN_POOL " << inPool << "/" << cases.size()
              << " scored_cases=" << scored << "\n";

    for (double nu : nuList) {
      int correct = 0;
      long long us = 0;
      int n = 0;
      for (const auto& c : cases) {
        ReadingGrid g = makeGrid(&lm);
        if (!feed(g, c.readings)) continue;
        g.setContextModel(&cm);
        if (nu == 0.0) {
          g.setPathScorer(nullptr);
          g.setPathRerankNu(0.0);
        } else {
          g.setPathScorer(&neural);
          g.setPathRerankNu(nu);
          g.setPathRerankNBest(N);
        }
        auto t0 = std::chrono::steady_clock::now();
        auto w = g.walk();
        auto t1 = std::chrono::steady_clock::now();
        us += std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0)
                  .count();
        ++n;
        if (joinedWalk(w) == c.expected) ++correct;
      }
      double meanMs = n ? (double)us / n / 1000.0 : 0;
      std::cout << "N " << N << " NU " << nu << " correct " << correct << "/"
                << cases.size() << " mean_ms " << meanMs << "\n";
    }
  }
  return 0;
}
