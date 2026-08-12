// Dump ALL single-char flip proposals from shipping prediction for gate sweep.
// Also dumps n-best paths with walkScore + v2c for V4.
// Research-only; does not modify product code.
//
// Usage:
//   flip_proposal_dump tw538 data bigrams lambda lstm nu reading2chars out_dir

#include <fstream>
#include <iostream>
#include <string>
#include <unordered_map>
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

std::vector<std::string> splitSyllables(const std::string& r) {
  std::vector<std::string> out;
  size_t s = 0;
  for (size_t i = 0; i < r.size(); ++i) {
    if (r[i] == '-') {
      if (i > s) out.push_back(r.substr(s, i - s));
      s = i + 1;
    }
  }
  if (s < r.size()) out.push_back(r.substr(s));
  return out;
}

std::vector<std::string> utf8Chars(const std::string& s) {
  std::vector<std::string> chars;
  size_t i = 0;
  while (i < s.size()) {
    unsigned char c = static_cast<unsigned char>(s[i]);
    size_t len = 1;
    if ((c & 0x80) == 0)
      len = 1;
    else if ((c & 0xE0) == 0xC0)
      len = 2;
    else if ((c & 0xF0) == 0xE0)
      len = 3;
    else if ((c & 0xF8) == 0xF0)
      len = 4;
    if (i + len > s.size()) len = 1;
    chars.push_back(s.substr(i, len));
    i += len;
  }
  return chars;
}

ReadingGrid makeGrid(ParselessLM* lm) {
  ReadingGrid g(std::shared_ptr<Formosa::Gramambular2::LanguageModel>(
      lm, [](Formosa::Gramambular2::LanguageModel*) {}));
  g.setReadingSeparator("-");
  return g;
}

bool feed(ReadingGrid& g, const std::string& r) {
  for (const auto& syl : splitSyllables(r)) {
    g.setCursor(g.length());
    if (!g.insertReading(syl)) return false;
  }
  return true;
}

std::string joined(const ReadingGrid::WalkResult& w) {
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
  std::string readings, expected;
};

std::vector<Case> loadCases(const std::string& path) {
  std::ifstream in(path);
  std::vector<Case> cases;
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty() || line[0] == '#') continue;
    size_t t = line.find('\t');
    if (t != std::string::npos)
      cases.push_back({line.substr(0, t), line.substr(t + 1)});
  }
  return cases;
}

using CandList = std::vector<std::pair<std::string, int>>;

std::unordered_map<std::string, CandList> loadR2C(const std::string& path) {
  std::unordered_map<std::string, CandList> m;
  std::ifstream in(path);
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty() || line[0] == '#') continue;
    size_t t = line.find('\t');
    if (t == std::string::npos) continue;
    std::string reading = line.substr(0, t);
    std::string body = line.substr(t + 1);
    CandList list;
    size_t i = 0;
    while (i < body.size()) {
      size_t colon = body.find(':', i);
      if (colon == std::string::npos) break;
      std::string ch = body.substr(i, colon - i);
      size_t comma = body.find(',', colon + 1);
      std::string num =
          comma == std::string::npos
              ? body.substr(colon + 1)
              : body.substr(colon + 1, comma - (colon + 1));
      int cnt = 0;
      try {
        cnt = std::stoi(num);
      } catch (...) {
      }
      list.emplace_back(ch, cnt);
      if (comma == std::string::npos) break;
      i = comma + 1;
    }
    m[reading] = std::move(list);
  }
  return m;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 9) {
    std::cerr << "usage: flip_proposal_dump tw538 data bigrams lambda lstm nu "
                 "r2c outdir\n";
    return 1;
  }
  std::cout << std::unitbuf;
  std::cerr << std::unitbuf;
  iBopomofoEval::AbortUnlessTw538(argv[1]);
  auto cases = loadCases(argv[1]);
  ParselessLM lm;
  if (!lm.open(argv[2])) return 1;
  CorpusBigramContextModel cm;
  if (!cm.load(argv[3])) return 1;
  cm.setLambda(std::stod(argv[4]));
  NeuralLMPathScorer scorer;
  if (!scorer.load(argv[5])) return 1;
  double nu = std::stod(argv[6]);
  auto r2c = loadR2C(argv[7]);
  std::string outDir = argv[8];

  std::ofstream propOut(outDir + "/flip_proposals_all.tsv");
  propOut << "sent_idx\tpos\tfrom\tto\tscore_S\tscore_Sp\tdelta_v2c\t"
             "ship_correct\tafter_correct\tgold_in_pool\tpred\tgold\n";

  std::ofstream nbestOut(outDir + "/nbest_paths.tsv");
  nbestOut << "sent_idx\trank\ttext\twalk_score\tv2c_score\tfused_075\t"
              "is_shipping\tis_gold\n";

  std::ofstream shipOut(outDir + "/shipping_preds.tsv");
  shipOut << "sent_idx\tcorrect\tgold_in_pool\tpred\tgold\twalk_score\t"
             "v2c_score\n";

  int shipCorrect = 0;
  for (size_t si = 0; si < cases.size(); ++si) {
    ReadingGrid g = makeGrid(&lm);
    if (!feed(g, cases[si].readings)) continue;
    g.setContextModel(&cm);

    // shipping walk+neural
    g.setPathScorer(&scorer);
    g.setPathRerankNu(nu);
    g.setPathRerankNBest(10);
    auto wShip = g.walk();
    std::string pred = joined(wShip);
    bool shipOk = (pred == cases[si].expected);
    if (shipOk) ++shipCorrect;
    double v2cShip = scorer.scoreSentence({pred});

    // n-best (neural on): RankedPath.walkScore is pre-fusion walk DP score
    auto nb = g.walkNBest(10);
    bool goldInPool = false;
    std::vector<std::string> uniq;
    std::vector<double> walkScores;
    std::unordered_map<std::string, int> seen;
    for (const auto& p : nb) {
      std::string t = joinedWords(p.words);
      if (t == cases[si].expected) goldInPool = true;
      if (!seen.count(t)) {
        seen[t] = static_cast<int>(uniq.size());
        uniq.push_back(t);
        walkScores.push_back(p.walkScore);
      }
    }
    // pure-walk nbest for any extra paths
    g.setPathScorer(nullptr);
    g.setPathRerankNu(0.0);
    auto nbWalk = g.walkNBest(10);
    double walkTop = nbWalk.empty() ? 0.0 : nbWalk[0].walkScore;
    for (const auto& p : nbWalk) {
      std::string t = joinedWords(p.words);
      if (!seen.count(t)) {
        seen[t] = static_cast<int>(uniq.size());
        uniq.push_back(t);
        walkScores.push_back(p.walkScore);
      }
    }

    std::vector<std::vector<std::string>> paths;
    paths.reserve(uniq.size());
    for (const auto& t : uniq) paths.push_back({t});
    auto v2cs = scorer.scoreNBest(paths);
    for (size_t r = 0; r < uniq.size(); ++r) {
      double ws = walkScores[r];
      double vs = v2cs[r];
      double fused = ws + 0.75 * vs;
      nbestOut << si << '\t' << r << '\t' << uniq[r] << '\t' << ws << '\t' << vs
               << '\t' << fused << '\t' << (uniq[r] == pred ? 1 : 0) << '\t'
               << (uniq[r] == cases[si].expected ? 1 : 0) << '\n';
    }

    shipOut << si << '\t' << (shipOk ? 1 : 0) << '\t' << (goldInPool ? 1 : 0)
            << '\t' << pred << '\t' << cases[si].expected << '\t' << walkTop
            << '\t' << v2cShip << '\n';

    // All single-char flip proposals from shipping pred
    auto syls = splitSyllables(cases[si].readings);
    auto Schars = utf8Chars(pred);
    size_t nPos = Schars.size();
    std::vector<std::vector<std::string>> fpaths;
    std::vector<std::tuple<int, std::string, std::string>> fmeta;
    fpaths.push_back({pred});
    for (size_t i = 0; i < nPos; ++i) {
      if (i >= syls.size()) continue;
      auto it = r2c.find(syls[i]);
      if (it == r2c.end()) continue;
      for (const auto& kv : it->second) {
        if (kv.first == Schars[i]) continue;
        std::string Sp;
        for (size_t j = 0; j < Schars.size(); ++j)
          Sp += (j == i) ? kv.first : Schars[j];
        fpaths.push_back({Sp});
        fmeta.emplace_back(static_cast<int>(i), Schars[i], kv.first);
      }
    }
    auto fscores = scorer.scoreNBest(fpaths);
    double scoreS = fscores[0];
    for (size_t k = 0; k < fmeta.size(); ++k) {
      int pos = std::get<0>(fmeta[k]);
      const std::string& from = std::get<1>(fmeta[k]);
      const std::string& to = std::get<2>(fmeta[k]);
      double scoreSp = fscores[k + 1];
      double delta = scoreSp - scoreS;
      const std::string& Sp = fpaths[k + 1][0];
      bool afterOk = (Sp == cases[si].expected);
      propOut << si << '\t' << pos << '\t' << from << '\t' << to << '\t' << scoreS
              << '\t' << scoreSp << '\t' << delta << '\t' << (shipOk ? 1 : 0)
              << '\t' << (afterOk ? 1 : 0) << '\t' << (goldInPool ? 1 : 0)
              << '\t' << pred << '\t' << cases[si].expected << '\n';
    }
    if ((si + 1) % 25 == 0)
      std::cerr << "dump progress " << (si + 1) << "/" << cases.size() << "\n";
  }
  std::cout << "SHIPPING_CORRECT " << shipCorrect << "/" << cases.size() << "\n";
  return shipCorrect == 387 ? 0 : 2;
}
