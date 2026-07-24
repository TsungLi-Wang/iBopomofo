// N-best + PathScorer fusion harness (Mozc-style).
//
// Usage:
//   nbest_path_rerank <sentences.tsv> <data.txt> <word-bigrams.tsv>
//                     <lambda> [path-char-ngrams.tsv] [nu]
//
// Without path-char-lstm.bin: prints n-best check (rank0 == walk top-1) + baseline.
// With path-char-lstm.bin + nu: scores accuracy with fusion (true LSTM LM).
// nu omitted → grid {0, 0.1, 0.25, 0.5, 0.75, 1.0}

#include <chrono>
#include <fstream>
#include <iostream>
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

std::string joined(const ReadingGrid::WalkResult& w) {
  std::string s;
  for (size_t i = 0; i < w.nodes.size(); ++i) s += w.chosenValueAt(i);
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

class MockZeroScorer : public ReadingGrid::PathScorer {
 public:
  double scoreSentence(const std::vector<std::string>&) override { return 0.0; }
};

}  // namespace

int main(int argc, char** argv) {
  if (argc < 5) {
    std::cerr << "Usage: nbest_path_rerank sentences data bigrams lambda "
                 "[path-ngram.tsv] [nu]\n";
    return 1;
  }
  McBopomofoEval::AbortUnlessTw538(argv[1]);
  auto cases = loadCases(argv[1]);
  ParselessLM lm;
  if (!lm.open(argv[2])) return 1;
  CorpusBigramContextModel cm;
  if (!cm.load(argv[3])) return 1;
  cm.setLambda(std::stod(argv[4]));

  NeuralLMPathScorer neuralScorer;
  bool hasScorer = false;
  if (argc > 5 && argv[5][0] != '\0') {
    hasScorer = neuralScorer.load(argv[5]);
    std::cout << "path scorer loaded=" << hasScorer
              << " params=" << neuralScorer.parameterCount()
              << " emb=" << neuralScorer.embDim()
              << " hidden=" << neuralScorer.hiddenDim()
              << " layers=" << neuralScorer.layers()
              << " vocab=" << neuralScorer.vocabSize() << "\n";
  }

  std::vector<double> nuGrid;
  if (argc > 6 && argv[6][0] != '\0') {
    nuGrid.push_back(std::stod(argv[6]));
  } else if (hasScorer) {
    nuGrid = {0.0, 0.1, 0.25, 0.5, 0.75, 1.0};
  } else {
    nuGrid = {0.0};
  }

  // Slice 1: n-best rank0 == walk top-1, and OFF/ON baseline.
  int matchTop = 0, nbestOk = 0, total = 0;
  int offCorrect = 0, onCorrect = 0;
  long long nbestUs = 0;
  for (const auto& c : cases) {
    // OFF
    {
      ReadingGrid g = makeGrid(&lm);
      if (!feed(g, c.readings)) continue;
      auto w = g.walk();
      if (joined(w) == c.expected) ++offCorrect;
    }
    // ON no scorer
    {
      ReadingGrid g = makeGrid(&lm);
      if (!feed(g, c.readings)) continue;
      g.setContextModel(&cm);
      auto t0 = std::chrono::steady_clock::now();
      auto w = g.walk();
      auto t1 = std::chrono::steady_clock::now();
      nbestUs += std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0)
                     .count();
      std::string top = joined(w);
      if (top == c.expected) ++onCorrect;
      auto nb = g.walkNBest(10);
      ++total;
      if (!nb.empty()) {
        std::string r0;
        for (const auto& x : nb[0].words) r0 += x;
        if (r0 == top) ++matchTop;
        ++nbestOk;
      }
    }
  }
  std::cout << "SLICE1_OFF " << offCorrect << "/" << cases.size() << "\n";
  std::cout << "SLICE1_ON " << onCorrect << "/" << cases.size() << "\n";
  std::cout << "SLICE1_NBEST_RANK0_MATCH " << matchTop << "/" << total << "\n";
  std::cout << "SLICE1_WALK_MEAN_US "
            << (total ? (double)nbestUs / total : 0) << "\n";

  // Slice 2: nu=0 with mock/scorer must match ON
  MockZeroScorer mock;
  int nu0 = 0;
  for (const auto& c : cases) {
    ReadingGrid g = makeGrid(&lm);
    if (!feed(g, c.readings)) continue;
    g.setContextModel(&cm);
    g.setPathScorer(&mock);
    g.setPathRerankNu(0.0);
    auto w0 = g.walk();
    g.setPathScorer(nullptr);
    auto w1 = g.walk();
    if (joined(w0) == joined(w1)) ++nu0;
  }
  std::cout << "SLICE2_NU0_MATCH " << nu0 << "/" << cases.size() << "\n";

  if (!hasScorer) return 0;

  // Slice 3/4: nu grid + latency with real scorer
  double bestNu = 0;
  int bestCorrect = onCorrect;
  for (double nu : nuGrid) {
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
        g.setPathScorer(&neuralScorer);
        g.setPathRerankNu(nu);
        g.setPathRerankNBest(10);
      }
      auto t0 = std::chrono::steady_clock::now();
      auto w = g.walk();
      auto t1 = std::chrono::steady_clock::now();
      us += std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0)
                .count();
      ++n;
      if (joined(w) == c.expected) ++correct;
    }
    double meanMs = n ? (double)us / n / 1000.0 : 0;
    std::cout << "NU " << nu << " correct " << correct << "/" << cases.size()
              << " mean_ms " << meanMs << "\n";
    if (correct > bestCorrect) {
      bestCorrect = correct;
      bestNu = nu;
    }
  }
  std::cout << "BEST_NU " << bestNu << " correct " << bestCorrect << "/"
            << cases.size() << "\n";
  return 0;
}
