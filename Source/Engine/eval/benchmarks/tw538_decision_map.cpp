// Per-sentence decision map for tw538 (walk ON + n-best LSTM rerank).
//
// Usage:
//   tw538_decision_map <sentences.tsv> <data.txt> <word-bigrams.tsv>
//                      <lambda> <path-char-lstm.bin> <nu> <nbest_n>
//                      <out.tsv>
//
// out.tsv columns (tab):
//   id reading gold walk_out rerank_out in_pool correct
//
// Also prints summary to stdout.

#include <chrono>
#include <fstream>
#include <iostream>
#include <string>
#include <unordered_set>
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

}  // namespace

int main(int argc, char** argv) {
  if (argc < 9) {
    std::cerr
        << "Usage: tw538_decision_map sentences data bigrams lambda lstm.bin "
           "nu nbest_n out.tsv\n";
    return 1;
  }
  auto cases = loadCases(argv[1]);
  ParselessLM lm;
  if (!lm.open(argv[2])) {
    std::cerr << "open data fail\n";
    return 1;
  }
  CorpusBigramContextModel cm;
  if (!cm.load(argv[3])) {
    std::cerr << "open bigrams fail\n";
    return 1;
  }
  cm.setLambda(std::stod(argv[4]));
  NeuralLMPathScorer neural;
  if (!neural.load(argv[5])) {
    std::cerr << "open lstm fail\n";
    return 1;
  }
  double nu = std::stod(argv[6]);
  size_t nbestN = static_cast<size_t>(std::stoul(argv[7]));
  std::string outPath = argv[8];

  std::cout << "cases=" << cases.size() << " lambda=" << argv[4]
            << " nu=" << nu << " nbest_n=" << nbestN
            << " params=" << neural.parameterCount() << "\n";

  std::ofstream out(outPath);
  out << "id\treading\tgold\twalk_out\trerank_out\tin_pool\tcorrect\n";

  int walkCorrect = 0, rerankCorrect = 0, inPool = 0, poolWrong = 0,
      poolMiss = 0, feedFail = 0;

  for (size_t i = 0; i < cases.size(); ++i) {
    const auto& c = cases[i];
    ReadingGrid g = makeGrid(&lm);
    if (!feed(g, c.readings)) {
      ++feedFail;
      out << (i + 1) << "\t" << c.readings << "\t" << c.expected
          << "\tFEED_FAIL\tFEED_FAIL\tN\tN\n";
      continue;
    }
    g.setContextModel(&cm);

    // Walk ON (no scorer)
    g.setPathScorer(nullptr);
    g.setPathRerankNu(0.0);
    auto walk = g.walk();
    std::string walkOut = joinedWalk(walk);
    if (walkOut == c.expected) ++walkCorrect;

    // N-best pool membership under ContextModel
    auto nb = g.walkNBest(nbestN);
    bool goldInPool = false;
    for (const auto& rp : nb) {
      if (joinedWords(rp.words) == c.expected) {
        goldInPool = true;
        break;
      }
    }
    if (goldInPool) ++inPool;

    // Rerank with scorer
    g.setPathScorer(&neural);
    g.setPathRerankNu(nu);
    g.setPathRerankNBest(nbestN);
    auto rerank = g.walk();
    std::string rerankOut = joinedWalk(rerank);
    bool ok = (rerankOut == c.expected);
    if (ok) ++rerankCorrect;
    if (goldInPool && !ok) ++poolWrong;
    if (!goldInPool && !ok) ++poolMiss;

    out << (i + 1) << "\t" << c.readings << "\t" << c.expected << "\t"
        << walkOut << "\t" << rerankOut << "\t" << (goldInPool ? "Y" : "N")
        << "\t" << (ok ? "Y" : "N") << "\n";
  }

  std::cout << "WALK_ON " << walkCorrect << "/" << cases.size() << "\n";
  std::cout << "RERANK " << rerankCorrect << "/" << cases.size() << "\n";
  std::cout << "IN_POOL " << inPool << "/" << cases.size() << "\n";
  std::cout << "POOL_WRONG_SCORER " << poolWrong << "\n";
  std::cout << "POOL_MISS " << poolMiss << "\n";
  std::cout << "FEED_FAIL " << feedFail << "\n";
  std::cout << "OUT " << outPath << "\n";
  return 0;
}
