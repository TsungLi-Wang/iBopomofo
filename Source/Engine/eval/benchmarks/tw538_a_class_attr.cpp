// T1: A-class (in-pool scorer wrong) attribution into FUSION_LOSS vs MODEL_LOSS.
//
// For each case where gold is in n-best pool but rerank picks wrong:
//   LSTM_gold / LSTM_chosen  = PathScorer scores
//   walk_gold / walk_chosen  = RankedPath.walkScore from n-best
//
// FUSION_LOSS: LSTM_gold > LSTM_chosen  (teacher preferred gold; fusion killed it)
// MODEL_LOSS:  LSTM_gold <= LSTM_chosen (teacher itself preferred wrong path)
//
// Usage:
//   tw538_a_class_attr <sentences.tsv> <data.txt> <word-bigrams.tsv>
//                      <lambda> <path-char-lstm.bin> <nu> <nbest_n>
//                      <out.tsv>
//
// out.tsv columns:
//   id reading gold walk_out rerank_out
//   walk_gold walk_chosen lstm_gold lstm_chosen
//   fusion_gold fusion_chosen loss_type
//   char_n_gold char_n_chosen

#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "CorpusBigramContextModel.h"
#include "NeuralLMPathScorer.h"
#include "ParselessLM.h"
#include "gramambular2/reading_grid.h"

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

// Count UTF-8 CJK-ish codepoints roughly by non-continuation bytes.
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

}  // namespace

int main(int argc, char** argv) {
  if (argc < 9) {
    std::cerr << "Usage: tw538_a_class_attr sentences data bigrams lambda "
                 "lstm.bin nu nbest_n out.tsv\n";
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

  std::cout << "cases=" << cases.size() << " lambda=" << argv[4] << " nu=" << nu
            << " nbest_n=" << nbestN << " params=" << neural.parameterCount()
            << "\n";

  std::ofstream out(outPath);
  out << "id\treading\tgold\twalk_out\trerank_out\t"
         "walk_gold\twalk_chosen\tlstm_gold\tlstm_chosen\t"
         "fusion_gold\tfusion_chosen\tloss_type\t"
         "char_n_gold\tchar_n_chosen\tword_n_gold\tword_n_chosen\n";

  int aClass = 0, fusionLoss = 0, modelLoss = 0, goldMissingInNb = 0;
  int correct = 0, inPool = 0, poolMiss = 0;

  for (size_t i = 0; i < cases.size(); ++i) {
    const auto& c = cases[i];
    ReadingGrid g = makeGrid(&lm);
    if (!feed(g, c.readings)) continue;
    g.setContextModel(&cm);

    g.setPathScorer(nullptr);
    g.setPathRerankNu(0.0);
    auto walk = g.walk();
    std::string walkOut = joinedWalk(walk);

    auto nb = g.walkNBest(nbestN);
    const ReadingGrid::RankedPath* goldPath = nullptr;
    for (const auto& rp : nb) {
      if (joinedWords(rp.words) == c.expected) {
        goldPath = &rp;
        break;
      }
    }
    bool goldInPool = goldPath != nullptr;
    if (goldInPool) ++inPool;

    g.setPathScorer(&neural);
    g.setPathRerankNu(nu);
    g.setPathRerankNBest(nbestN);
    auto rerank = g.walk();
    std::string rerankOut = joinedWalk(rerank);
    bool ok = (rerankOut == c.expected);
    if (ok) ++correct;
    if (!goldInPool && !ok) ++poolMiss;

    if (!goldInPool || ok) continue;  // A-class only: in-pool and wrong

    ++aClass;

    // Locate chosen path in n-best (must exist)
    const ReadingGrid::RankedPath* chosenPath = nullptr;
    for (const auto& rp : nb) {
      if (joinedWords(rp.words) == rerankOut) {
        chosenPath = &rp;
        break;
      }
    }
    // Fallback: rescore chosen words even if path object missing
    std::vector<std::string> chosenWords;
    if (chosenPath) {
      chosenWords = chosenPath->words;
    } else {
      // Reconstruct from walk result nodes
      for (size_t ni = 0; ni < rerank.nodes.size(); ++ni) {
        chosenWords.push_back(rerank.chosenValueAt(ni));
      }
    }

    double walkGold = goldPath->walkScore;
    double walkChosen =
        chosenPath ? chosenPath->walkScore : rerank.walkScore;
    double lstmGold = neural.scoreSentence(goldPath->words);
    double lstmChosen = neural.scoreSentence(chosenWords);
    double fusionGold = walkGold + nu * lstmGold;
    double fusionChosen = walkChosen + nu * lstmChosen;

    std::string lossType;
    if (lstmGold > lstmChosen) {
      lossType = "FUSION_LOSS";
      ++fusionLoss;
    } else {
      lossType = "MODEL_LOSS";
      ++modelLoss;
    }

    size_t charGold = utf8CharCount(c.expected);
    size_t charChosen = utf8CharCount(rerankOut);

    out << (i + 1) << "\t" << c.readings << "\t" << c.expected << "\t"
        << walkOut << "\t" << rerankOut << "\t" << walkGold << "\t"
        << walkChosen << "\t" << lstmGold << "\t" << lstmChosen << "\t"
        << fusionGold << "\t" << fusionChosen << "\t" << lossType << "\t"
        << charGold << "\t" << charChosen << "\t" << goldPath->words.size()
        << "\t" << chosenWords.size() << "\n";

    if (!chosenPath) ++goldMissingInNb;  // misuse counter: chosen missing
  }

  std::cout << "CORRECT " << correct << "/" << cases.size() << "\n";
  std::cout << "IN_POOL " << inPool << "/" << cases.size() << "\n";
  std::cout << "A_CLASS " << aClass << "\n";
  std::cout << "FUSION_LOSS " << fusionLoss;
  if (aClass) {
    std::cout << " (" << (100.0 * fusionLoss / aClass) << "%)";
  }
  std::cout << "\n";
  std::cout << "MODEL_LOSS " << modelLoss;
  if (aClass) {
    std::cout << " (" << (100.0 * modelLoss / aClass) << "%)";
  }
  std::cout << "\n";
  std::cout << "POOL_MISS " << poolMiss << "\n";
  std::cout << "CHOSEN_PATH_FALLBACK " << goldMissingInNb << "\n";
  std::cout << "OUT " << outPath << "\n";
  return 0;
}
