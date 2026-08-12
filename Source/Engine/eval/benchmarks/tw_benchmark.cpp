// Taiwan Typing Benchmark (北極星指標)
//
// 這是所有改動的唯一客觀裁判。
// 目標：乾淨台灣句子 → 轉注音鍵序 → 引擎 walk → 整句 top-1 字正確率。
//
// baseline = unigram-only walk。若提供真實語料 bigram PMI 表，會用
// CorpusBigramContextModel 對一組 lambda 做網格搜索（lambda 只由 benchmark
// 準確率決定，不手調、不為個別 demo 硬放大），印出 before/after 與最佳 lambda。
//
// 結果一律用 walk().chosenValueAt(i) 讀取：設了 ContextModel 後 walk 只在
// selectedUnigramIndices 記錄選擇、不改節點，node->value()/valuesAsStrings()
// 讀不到 DP 的選擇。
//
// 編譯見 benchmarks/build-and-run.sh。
//   ./tw_benchmark <sentences.tsv> <data.txt> [bigram-pmi.tsv] [single-lambda]

#include <algorithm>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "CorpusBigramContextModel.h"
#include "ParselessLM.h"
#include "gramambular2/reading_grid.h"
#include "../benchmark_gate.h"

using Formosa::Gramambular2::ReadingGrid;
using iBopomofo::CorpusBigramContextModel;
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

// Concatenate the chosen value of every node on the walked path. This is the
// only correct way to read a walk that used a ContextModel.
std::string walkTop1(ParselessLM* lm, const std::string& readings,
                     ReadingGrid::ContextModel* cm) {
  ReadingGrid grid = makeGrid(lm);
  if (!feed(grid, readings)) return "<insert-failed>";
  if (cm != nullptr) grid.setContextModel(cm);
  auto result = grid.walk();
  std::string out;
  for (size_t i = 0; i < result.nodes.size(); ++i) out += result.chosenValueAt(i);
  return out;
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

int accuracy(ParselessLM* lm, const std::vector<Case>& cases,
             ReadingGrid::ContextModel* cm, bool printMiss) {
  int correct = 0;
  for (const auto& c : cases) {
    std::string got = walkTop1(lm, c.readings, cm);
    if (got == c.expected) {
      ++correct;
    } else if (printMiss) {
      std::cout << "MISS: " << c.readings << " -> \"" << got << "\" expected \""
                << c.expected << "\"\n";
    }
  }
  return correct;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc >= 2) iBopomofoEval::AbortUnlessTw538(argv[1]);
  if (argc < 3) {
    std::cerr << "Usage: tw_benchmark <sentences.tsv> <data.txt> "
                 "[bigram-pmi.tsv] [single-lambda]\n";
    return 1;
  }

  auto cases = loadCases(argv[1]);
  std::string lm_path = argv[2];
  std::string bigram_path = argc > 3 ? argv[3] : "";
  bool singleLambda = argc > 4 && argv[4][0] != '\0';
  double onlyLambda = singleLambda ? std::stod(argv[4]) : 0.0;

  ParselessLM lm;
  if (!lm.open(lm_path.c_str())) {
    std::cerr << "無法開啟 LM: " << lm_path << "\n";
    return 1;
  }

  std::cout << "Loaded " << cases.size() << " benchmark cases.\n";
  std::cout << "LM: " << lm_path << "\n";

  int total = static_cast<int>(cases.size());
  int baseline = accuracy(&lm, cases, nullptr, /*printMiss=*/false);
  std::cout << "\n=== North Star Taiwan Typing Benchmark ===\n";
  std::cout << "baseline (unigram-only): " << (double)baseline / total << " ("
            << baseline << "/" << total << ")\n";

  if (bigram_path.empty()) {
    // No table: also print baseline miss list for inspection.
    accuracy(&lm, cases, nullptr, /*printMiss=*/true);
    return 0;
  }

  CorpusBigramContextModel cm;
  if (!cm.load(bigram_path)) {
    std::cerr << "無法載入 bigram 表: " << bigram_path << "\n";
    return 1;
  }
  std::cout << "bigram PMI table: " << bigram_path << " (" << cm.size()
            << " pairs)\n\n";

  std::vector<double> grid =
      singleLambda ? std::vector<double>{onlyLambda}
                   : std::vector<double>{0.25, 0.5, 0.75, 1.0, 1.5,
                                         2.0, 3.0, 5.0, 8.0};

  double bestLambda = 0.0;
  int bestCorrect = baseline;  // must beat baseline to be chosen
  for (double lambda : grid) {
    cm.setLambda(lambda);
    int correct = accuracy(&lm, cases, &cm, /*printMiss=*/false);
    std::cout << "lambda=" << lambda << " : " << (double)correct / total << " ("
              << correct << "/" << total << ")\n";
    if (correct > bestCorrect) {
      bestCorrect = correct;
      bestLambda = lambda;
    }
  }

  std::cout << "\nbest lambda=" << bestLambda << " : " << (double)bestCorrect / total
            << " (" << bestCorrect << "/" << total << ")  vs baseline "
            << (double)baseline / total << "\n";

  // Show the remaining misses at the best lambda for inspection.
  cm.setLambda(bestLambda);
  std::cout << "\n--- misses at best lambda ---\n";
  accuracy(&lm, cases, &cm, /*printMiss=*/true);
  return 0;
}
