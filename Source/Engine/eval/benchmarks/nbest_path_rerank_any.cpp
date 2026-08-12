// Like nbest_path_rerank, but auto-detects LWLSTM1 vs LWTFMR1 weight magic.
//
// Usage:
//   nbest_path_rerank_any <sentences.tsv> <data.txt> <word-bigrams.tsv>
//                         <lambda> <weights.bin> [nu]
// nu omitted → grid {0, 0.25, 0.5, 0.75, 1.0}

#include <chrono>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "CorpusBigramContextModel.h"
#include "NeuralLMPathScorer.h"
#include "NeuralTFPathScorer.h"
#include "ParselessLM.h"
#include "gramambular2/reading_grid.h"

using Formosa::Gramambular2::ReadingGrid;
using iBopomofo::CorpusBigramContextModel;
using iBopomofo::NeuralLMPathScorer;
using iBopomofo::NeuralTFPathScorer;
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

std::string peekMagic(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  char m[8] = {};
  in.read(m, 8);
  return std::string(m, m + 8);
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 6) {
    std::cerr << "Usage: nbest_path_rerank_any sentences data bigrams lambda "
                 "weights.bin [nu]\n";
    return 1;
  }
  auto cases = loadCases(argv[1]);
  ParselessLM lm;
  if (!lm.open(argv[2])) return 1;
  CorpusBigramContextModel cm;
  if (!cm.load(argv[3])) return 1;
  cm.setLambda(std::stod(argv[4]));

  NeuralLMPathScorer lstm;
  NeuralTFPathScorer tf;
  ReadingGrid::PathScorer* scorer = nullptr;
  std::string magic = peekMagic(argv[5]);
  bool hasScorer = false;
  if (magic == std::string("LWLSTM1\0", 8) ||
      magic == std::string("LWLSTM8\0", 8)) {
    hasScorer = lstm.load(argv[5]);
    scorer = &lstm;
    std::cout << "scorer=LSTM loaded=" << hasScorer
              << " params=" << lstm.parameterCount()
              << " vocab=" << lstm.vocabSize() << "\n";
  } else if (magic == std::string("LWTFMR1\0", 8)) {
    hasScorer = tf.load(argv[5]);
    scorer = &tf;
    std::cout << "scorer=Transformer loaded=" << hasScorer
              << " params=" << tf.parameterCount() << " d=" << tf.dModel()
              << " layers=" << tf.nLayer() << " heads=" << tf.nHead()
              << " ffn=" << tf.ffn() << " max_ctx=" << tf.maxCtx()
              << " vocab=" << tf.vocabSize() << "\n";
  } else {
    std::cerr << "unknown weight magic\n";
    return 1;
  }
  if (!hasScorer || !scorer) return 1;

  std::vector<double> nuGrid;
  if (argc > 6 && argv[6][0] != '\0') {
    nuGrid.push_back(std::stod(argv[6]));
  } else {
    nuGrid = {0.0, 0.25, 0.5, 0.75, 1.0};
  }

  int offCorrect = 0, onCorrect = 0;
  for (const auto& c : cases) {
    {
      ReadingGrid g = makeGrid(&lm);
      if (!feed(g, c.readings)) continue;
      if (joined(g.walk()) == c.expected) ++offCorrect;
    }
    {
      ReadingGrid g = makeGrid(&lm);
      if (!feed(g, c.readings)) continue;
      g.setContextModel(&cm);
      if (joined(g.walk()) == c.expected) ++onCorrect;
    }
  }
  std::cout << "SLICE1_OFF " << offCorrect << "/" << cases.size() << "\n";
  std::cout << "SLICE1_ON " << onCorrect << "/" << cases.size() << "\n";

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
        g.setPathScorer(scorer);
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
