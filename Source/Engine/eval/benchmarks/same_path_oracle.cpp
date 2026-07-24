// Same-path oracle upper bound for the Taiwan Typing Benchmark.
//
// For each sentence that bigram walk (lambda fixed) gets wrong, ask:
// can the expected surface be formed by ONLY re-picking unigrams on the
// same path nodes (same segmentation / readings), without inventing text?
// That is the ceiling for a same-path unigram reselect / RNN reranker.
//
// Rank of the gold unigram on each path node is 1-based among node->unigrams()
// (already score-sorted by ScoreRankedLanguageModel).
//
// Build (from this directory):
//   clang++ -std=c++17 -O2 -I../.. -I../../gramambular2 \
//     same_path_oracle.cpp ../../gramambular2/reading_grid.cpp \
//     ../../CorpusBigramContextModel.cpp ../../ParselessLM.cpp \
//     ../../ParselessPhraseDB.cpp ../../MemoryMappedFile.cpp \
//     -o /tmp/same_path_oracle
// Run:
//   /tmp/same_path_oracle tw538-northstar.tsv ../../../Data/data.txt \
//       ../../../Data/word-bigrams.tsv 0.75

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

#include "CorpusBigramContextModel.h"
#include "ParselessLM.h"
#include "../benchmark_gate.h"
#include "gramambular2/reading_grid.h"

using Formosa::Gramambular2::LanguageModel;
using Formosa::Gramambular2::ReadingGrid;
using McBopomofo::CorpusBigramContextModel;
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
  ReadingGrid grid(std::shared_ptr<LanguageModel>(
      lm, [](LanguageModel*) {}));
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

// UTF-8 safe "starts with" for full unigram values (engine stores UTF-8).
bool startsWith(const std::string& s, size_t pos, const std::string& prefix) {
  if (pos > s.size() || prefix.size() > s.size() - pos) return false;
  return s.compare(pos, prefix.size(), prefix) == 0;
}

struct NodePick {
  std::string chosen;   // bigram walk pick
  std::string gold;     // unigram needed to match expected
  int goldRank = 0;     // 1-based among node unigrams; 0 = not found
  size_t unigramCount = 0;
  std::vector<std::pair<std::string, double>> top5;  // value, score
};

struct OracleResult {
  bool insertFailed = false;
  std::string got;
  bool fullyInOracle = false;  // expected formable on same path
  int worstGoldRank = 0;       // max goldRank among nodes that needed change
  std::vector<NodePick> picks; // one per path node when walk succeeded
  std::string failReason;
};

OracleResult analyzeCase(ParselessLM* lm, const Case& c,
                         CorpusBigramContextModel* cm) {
  OracleResult r;
  ReadingGrid grid = makeGrid(lm);
  if (!feed(grid, c.readings)) {
    r.insertFailed = true;
    r.got = "<insert-failed>";
    r.fullyInOracle = false;
    r.failReason = "insert-failed";
    return r;
  }
  grid.setContextModel(cm);
  auto walk = grid.walk();
  for (size_t i = 0; i < walk.nodes.size(); ++i) {
    r.got += walk.chosenValueAt(i);
  }
  if (r.got == c.expected) {
    // Should not be called on hits, but handle anyway.
    r.fullyInOracle = true;
    return r;
  }

  // Greedy left-to-right: each path node must contribute exactly one of its
  // unigrams as a prefix of the remaining expected string.
  size_t pos = 0;
  const std::string& exp = c.expected;
  for (size_t ni = 0; ni < walk.nodes.size(); ++ni) {
    const auto& node = walk.nodes[ni];
    const auto& ugs = node->unigrams();
    NodePick pick;
    pick.chosen = walk.chosenValueAt(ni);
    pick.unigramCount = ugs.size();
    for (size_t k = 0; k < ugs.size() && k < 5; ++k) {
      pick.top5.emplace_back(ugs[k].value(), ugs[k].score());
    }

    // Among unigrams that are a prefix of remaining expected, take the longest
    // match (stable for rare mixed lengths). Rank = 1-based index of that
    // value in the score-sorted unigram list.
    std::string goldValue;
    for (size_t k = 0; k < ugs.size(); ++k) {
      if (startsWith(exp, pos, ugs[k].value())) {
        if (goldValue.empty() || ugs[k].value().size() > goldValue.size()) {
          goldValue = ugs[k].value();
        }
      }
    }
    int goldRank = 0;
    if (!goldValue.empty()) {
      for (size_t k = 0; k < ugs.size(); ++k) {
        if (ugs[k].value() == goldValue) {
          goldRank = static_cast<int>(k + 1);
          break;
        }
      }
    }

    if (goldRank == 0) {
      r.fullyInOracle = false;
      r.failReason = "no-unigram-prefix@node" + std::to_string(ni) +
                     " pos=" + std::to_string(pos);
      r.picks.push_back(pick);
      // Still record remaining nodes as incomplete.
      return r;
    }
    pick.gold = goldValue;
    pick.goldRank = goldRank;
    r.picks.push_back(pick);
    pos += goldValue.size();
  }

  if (pos != exp.size()) {
    r.fullyInOracle = false;
    r.failReason = "path-consumed-but-expected-remainder len_left=" +
                   std::to_string(exp.size() - pos);
    return r;
  }

  r.fullyInOracle = true;
  int worst = 0;
  for (const auto& p : r.picks) {
    if (p.gold != p.chosen && p.goldRank > worst) worst = p.goldRank;
  }
  // If every node already matched chosen==gold but strings differed, impossible
  // after full consume; worst stays 0 only if all nodes already correct (then
  // got==expected). Treat worst==0 with fullyInOracle as rank-1 bucket of
  // "no change needed" — should not appear on misses.
  if (worst == 0) {
    // All gold ranks equal chosen — path values equal expected pieces but
    // joined got differed? Should not happen. Fall back to max goldRank.
    for (const auto& p : r.picks) {
      if (p.goldRank > worst) worst = p.goldRank;
    }
  }
  r.worstGoldRank = worst;
  return r;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc >= 2) McBopomofoEval::AbortUnlessTw538(argv[1]);
  if (argc < 5) {
    std::cerr << "Usage: same_path_oracle <sentences.tsv> <data.txt> "
                 "<bigram-pmi.tsv> <lambda>\n";
    return 1;
  }
  const std::string casesPath = argv[1];
  const std::string dataPath = argv[2];
  const std::string bigramPath = argv[3];
  const double lambda = std::stod(argv[4]);

  auto cases = loadCases(casesPath);
  ParselessLM lm;
  if (!lm.open(dataPath.c_str())) {
    std::cerr << "cannot open LM\n";
    return 1;
  }
  CorpusBigramContextModel cm;
  if (!cm.load(bigramPath)) {
    std::cerr << "cannot load bigram\n";
    return 1;
  }
  cm.setLambda(lambda);

  int correct = 0;
  int miss = 0;
  int inOracle = 0;
  int outOracle = 0;
  int insertFailed = 0;
  int rank1 = 0, rank23 = 0, rank4p = 0;

  struct Example {
    std::string expected;
    std::string got;
    int worstRank = 0;
    bool inOracle = false;
    std::string note;
    std::vector<NodePick> picks;
  };
  std::vector<Example> examples;

  std::cout << "Loaded " << cases.size() << " cases. lambda=" << lambda << "\n";

  for (const auto& c : cases) {
    ReadingGrid grid = makeGrid(&lm);
    std::string got;
    bool inserted = feed(grid, c.readings);
    if (!inserted) {
      got = "<insert-failed>";
    } else {
      grid.setContextModel(&cm);
      auto w = grid.walk();
      for (size_t i = 0; i < w.nodes.size(); ++i) got += w.chosenValueAt(i);
    }
    if (got == c.expected) {
      ++correct;
      continue;
    }
    ++miss;

    OracleResult o = analyzeCase(&lm, c, &cm);
    if (o.insertFailed) ++insertFailed;

    if (o.fullyInOracle) {
      ++inOracle;
      if (o.worstGoldRank <= 1)
        ++rank1;
      else if (o.worstGoldRank <= 3)
        ++rank23;
      else
        ++rank4p;
    } else {
      ++outOracle;
    }

    // Collect a few examples across buckets.
    auto wantExample = [&]() {
      if (examples.size() >= 12) return false;
      if (o.insertFailed) return examples.size() < 2;
      if (!o.fullyInOracle) return true;
      if (o.worstGoldRank <= 1) return true;
      if (o.worstGoldRank >= 2 && o.worstGoldRank <= 3) return true;
      if (o.worstGoldRank >= 4) return true;
      return false;
    };
    // Prefer diversity: keep at most 2 per bucket in first pass by tagging.
    if (examples.size() < 10) {
      Example ex;
      ex.expected = c.expected;
      ex.got = o.got;
      ex.worstRank = o.worstGoldRank;
      ex.inOracle = o.fullyInOracle;
      if (o.insertFailed)
        ex.note = "insert-failed (lattice cannot host readings)";
      else if (!o.fullyInOracle)
        ex.note = "out-of-oracle: " + o.failReason;
      else
        ex.note = "in-oracle worstGoldRank=" + std::to_string(o.worstGoldRank);
      ex.picks = o.picks;
      // Limit examples: 2 insert/out, 2 rank1, 2 rank23, 2 rank4
      int bucket = o.insertFailed || !o.fullyInOracle
                       ? 0
                       : (o.worstGoldRank <= 1
                              ? 1
                              : (o.worstGoldRank <= 3 ? 2 : 3));
      int countBucket = 0;
      for (const auto& e : examples) {
        int b = (!e.inOracle)
                    ? 0
                    : (e.worstRank <= 1 ? 1 : (e.worstRank <= 3 ? 2 : 3));
        if (b == bucket) ++countBucket;
      }
      if (countBucket < 2) examples.push_back(std::move(ex));
    }
  }

  const int total = static_cast<int>(cases.size());
  std::cout << "\n=== North Star accuracy (bigram) ===\n";
  std::cout << "correct: " << correct << "/" << total << " ("
            << (double)correct / total << ")\n";
  std::cout << "miss: " << miss << "/" << total << "\n";

  std::cout << "\n=== Same-path oracle (miss sentences only) ===\n";
  std::cout << "ORACLE_MISS_TOTAL " << miss << "\n";
  std::cout << "ORACLE_IN " << inOracle << "\n";
  std::cout << "ORACLE_OUT " << outOracle << "\n";
  std::cout << "ORACLE_INSERT_FAILED " << insertFailed << "\n";
  std::cout << "ORACLE_RANK1 " << rank1 << "\n";
  std::cout << "ORACLE_RANK23 " << rank23 << "\n";
  std::cout << "ORACLE_RANK4P " << rank4p << "\n";

  std::cout << "\n=== Examples ===\n";
  int idx = 1;
  for (const auto& ex : examples) {
    std::cout << "EX" << idx++ << " expected=\"" << ex.expected << "\" got=\""
              << ex.got << "\" inOracle=" << (ex.inOracle ? "yes" : "no")
              << " worstRank=" << ex.worstRank << " note=" << ex.note << "\n";
    for (size_t ni = 0; ni < ex.picks.size(); ++ni) {
      const auto& p = ex.picks[ni];
      std::cout << "  node" << ni << " chosen=\"" << p.chosen << "\" gold=\""
                << p.gold << "\" goldRank=" << p.goldRank
                << " ugCount=" << p.unigramCount << " top5=";
      for (size_t t = 0; t < p.top5.size(); ++t) {
        if (t) std::cout << " | ";
        std::cout << p.top5[t].first << "(" << p.top5[t].second << ")";
      }
      std::cout << "\n";
    }
  }
  return 0;
}
