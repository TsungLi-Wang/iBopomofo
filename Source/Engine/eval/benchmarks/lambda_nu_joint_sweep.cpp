// λ/ν joint sweep on tw538 under rerank ON (N=10).
//
// final = walk_score(λ) + ν · LSTM(path). For fixed λ, n-best pool + walk
// scores + LSTM scores are independent of ν → outer loop re-walks; inner
// loop is pure linear reweight (near free).
//
// Usage:
//   lambda_nu_joint_sweep <sentences> <data> <bigrams> <lstm.bin>
//                         [lambda_lo lambda_hi lambda_step]
//                         [nu_lo nu_hi nu_step]
//                         [control]
//
// control: if last arg is "control", only evaluates λ=0.75 ν=0.75 once
//          (must print CONTROL correct 387/537 before full sweep).
//
// Outputs:
//   stdout progress + CONTROL / BEST lines
//   TSV path can be redirected by caller (prints TSV rows to stdout with
//   prefix TSV\t and COVERAGE\t).

#include <chrono>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

#include "CorpusBigramContextModel.h"
#include "NeuralLMPathScorer.h"
#include "ParselessLM.h"
#include "gramambular2/reading_grid.h"

#include "../benchmark_gate.h"

using Formosa::Gramambular2::ReadingGrid;
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

std::vector<double> grid(double lo, double hi, double step) {
  std::vector<double> out;
  // Inclusive range with integer steps to avoid float drift.
  int n = static_cast<int>(std::llround((hi - lo) / step));
  for (int i = 0; i <= n; ++i) {
    out.push_back(lo + step * i);
  }
  return out;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 5) {
    std::cerr
        << "Usage: lambda_nu_joint_sweep sentences data bigrams lstm.bin "
           "[lam_lo lam_hi lam_step] [nu_lo nu_hi nu_step] [control]\n";
    return 1;
  }

  bool controlOnly = false;
  for (int i = 1; i < argc; ++i) {
    if (std::string(argv[i]) == "control") controlOnly = true;
  }

  iBopomofoEval::AbortUnlessTw538(argv[1]);
  auto cases = loadCases(argv[1]);
  ParselessLM lm;
  if (!lm.open(argv[2])) {
    std::cerr << "data open fail\n";
    return 1;
  }
  CorpusBigramContextModel cm;
  if (!cm.load(argv[3])) {
    std::cerr << "bigrams load fail\n";
    return 1;
  }
  NeuralLMPathScorer neural;
  if (!neural.load(argv[4])) {
    std::cerr << "lstm load fail\n";
    return 1;
  }

  double lamLo = 0.0, lamHi = 1.5, lamStep = 0.05;
  double nuLo = 0.0, nuHi = 2.0, nuStep = 0.05;
  // Optional numeric args after lstm.bin (before optional "control")
  std::vector<double> nums;
  for (int i = 5; i < argc; ++i) {
    if (std::string(argv[i]) == "control") continue;
    nums.push_back(std::stod(argv[i]));
  }
  if (nums.size() >= 3) {
    lamLo = nums[0];
    lamHi = nums[1];
    lamStep = nums[2];
  }
  if (nums.size() >= 6) {
    nuLo = nums[3];
    nuHi = nums[4];
    nuStep = nums[5];
  }

  std::vector<double> lambdas;
  std::vector<double> nus;
  if (controlOnly) {
    lambdas = {0.75};
    nus = {0.75};
  } else {
    lambdas = grid(lamLo, lamHi, lamStep);
    nus = grid(nuLo, nuHi, nuStep);
  }

  std::cout << std::fixed << std::setprecision(4);
  std::cout << "cases=" << cases.size() << " params=" << neural.parameterCount()
            << " emb=" << neural.embDim() << " hidden=" << neural.hiddenDim()
            << " lambdas=" << lambdas.size() << " nus=" << nus.size()
            << " control=" << (controlOnly ? 1 : 0) << "\n";

  int bestCorrect = -1;
  double bestLam = 0, bestNu = 0;
  int controlCorrect = -1;

  // TSV header (machine-readable)
  std::cout << "TSV\tlambda\tnu\tcorrect\ttotal\tin_pool\n";
  std::cout << "COVERAGE\tlambda\tin_pool\ttotal\n";

  for (double lambda : lambdas) {
    cm.setLambda(lambda);

    // Per-sentence: pool + walk scores + lstm scores (ν-independent)
    struct ScoredCase {
      std::vector<double> walkScores;
      std::vector<double> lstmScores;
      std::vector<std::string> paths;
      bool inPool = false;
      bool ok = false;
    };
    std::vector<ScoredCase> scored;
    scored.reserve(cases.size());

    auto tLam0 = std::chrono::steady_clock::now();
    int inPool = 0;
    for (const auto& c : cases) {
      ScoredCase sc;
      ReadingGrid g = makeGrid(&lm);
      if (!feed(g, c.readings)) {
        scored.push_back(sc);
        continue;
      }
      g.setContextModel(&cm);
      auto nb = g.walkNBest(10);
      if (nb.empty()) {
        // Fallback: single walk path
        auto w = g.walk();
        std::vector<std::string> words;
        for (size_t i = 0; i < w.nodes.size(); ++i)
          words.push_back(w.chosenValueAt(i));
        ReadingGrid::RankedPath rp;
        rp.words = words;
        rp.walkScore = w.walkScore;
        nb.push_back(rp);
      }
      sc.ok = true;
      sc.walkScores.reserve(nb.size());
      sc.paths.reserve(nb.size());
      std::vector<std::vector<std::string>> pathWords;
      pathWords.reserve(nb.size());
      for (const auto& rp : nb) {
        sc.walkScores.push_back(rp.walkScore);
        sc.paths.push_back(joinedWords(rp.words));
        pathWords.push_back(rp.words);
        if (sc.paths.back() == c.expected) sc.inPool = true;
      }
      if (sc.inPool) ++inPool;
      sc.lstmScores = neural.scoreNBest(pathWords);
      if (sc.lstmScores.size() != sc.walkScores.size()) {
        // Defensive: pad zeros
        sc.lstmScores.assign(sc.walkScores.size(), 0.0);
      }
      scored.push_back(sc);
    }
    auto tLam1 = std::chrono::steady_clock::now();
    double lamMs = std::chrono::duration_cast<std::chrono::milliseconds>(
                       tLam1 - tLam0)
                       .count();

    std::cout << "COVERAGE\t" << lambda << "\t" << inPool << "\t"
              << cases.size() << "\n";
    std::cout << "LAMBDA_DONE " << lambda << " in_pool " << inPool << "/"
              << cases.size() << " wall_ms " << lamMs << "\n"
              << std::flush;

    for (double nu : nus) {
      int correct = 0;
      for (size_t ci = 0; ci < cases.size(); ++ci) {
        const auto& sc = scored[ci];
        if (!sc.ok || sc.paths.empty()) continue;
        size_t bestIdx = 0;
        double bestFinal = -std::numeric_limits<double>::infinity();
        for (size_t pi = 0; pi < sc.paths.size(); ++pi) {
          double finalScore = sc.walkScores[pi] + nu * sc.lstmScores[pi];
          if (finalScore > bestFinal) {
            bestFinal = finalScore;
            bestIdx = pi;
          }
        }
        if (sc.paths[bestIdx] == cases[ci].expected) ++correct;
      }
      std::cout << "TSV\t" << lambda << "\t" << nu << "\t" << correct << "\t"
                << cases.size() << "\t" << inPool << "\n";
      if (controlOnly && std::fabs(lambda - 0.75) < 1e-9 &&
          std::fabs(nu - 0.75) < 1e-9) {
        controlCorrect = correct;
        std::cout << "CONTROL lambda=0.75 nu=0.75 correct " << correct << "/"
                  << cases.size() << "\n";
      }
      if (correct > bestCorrect) {
        bestCorrect = correct;
        bestLam = lambda;
        bestNu = nu;
      }
    }
  }

  std::cout << "BEST lambda=" << bestLam << " nu=" << bestNu << " correct "
            << bestCorrect << "/" << cases.size() << "\n";
  if (controlOnly) {
    std::cout << "CONTROL_OK "
              << (controlCorrect == 387 ? "YES" : "NO") << " got="
              << controlCorrect << " expected=387\n";
    return controlCorrect == 387 ? 0 : 2;
  }
  // Delta vs baseline cell if present
  std::cout << "BASELINE_CELL lambda=0.75 nu=0.75 is the shipping reference "
               "(must appear in TSV)\n";
  return 0;
}
