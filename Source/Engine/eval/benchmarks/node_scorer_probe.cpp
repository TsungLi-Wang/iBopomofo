// node_scorer_probe — 把 NodeHomophoneScorer 的單點打分挖出來，好跟 PyTorch 對數字。
//
// 為什麼要有這支：匯出格式錯一個位元組，C++ 端照樣「跑得起來、分數看起來合理」，
// 然後所有 A/B 數字都是假的。這種錯不會報錯，只會讓你花半天怪模型。
// 所以換模型的第一道關卡不是效果，是 **C++ 與 PyTorch 逐題同分**。
//
//   node_scorer_probe <model.bin> < cases.tsv > scores.tsv
//
// 輸入每行：left <TAB> right <TAB> reading <TAB> cand1,cand2,…
// 輸出每行：cand1:score1,cand2:score2,…（log-softmax，限制在候選集合上）

#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "NodeHomophoneScorer.h"

namespace {

std::vector<std::string> splitUtf8(const std::string& s) {
  std::vector<std::string> out;
  size_t i = 0;
  while (i < s.size()) {
    unsigned char c = static_cast<unsigned char>(s[i]);
    size_t len = 1;
    if ((c & 0x80) == 0) {
      len = 1;
    } else if ((c & 0xE0) == 0xC0) {
      len = 2;
    } else if ((c & 0xF0) == 0xE0) {
      len = 3;
    } else if ((c & 0xF8) == 0xF0) {
      len = 4;
    }
    if (i + len > s.size()) len = 1;
    out.push_back(s.substr(i, len));
    i += len;
  }
  return out;
}

std::vector<std::string> splitBy(const std::string& s, char sep) {
  std::vector<std::string> out;
  std::string cur;
  std::istringstream ss(s);
  while (std::getline(ss, cur, sep)) out.push_back(cur);
  return out;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "usage: node_scorer_probe <model.bin> < cases.tsv\n";
    return 2;
  }
  iBopomofo::NodeHomophoneScorer scorer;
  if (!scorer.load(argv[1])) {
    std::cerr << "FATAL: cannot load " << argv[1] << "\n";
    return 1;
  }
  std::cerr << "loaded params=" << scorer.parameterCount() << "\n";

  std::string line;
  while (std::getline(std::cin, line)) {
    std::vector<std::string> f = splitBy(line, '\t');
    if (f.size() < 4) {
      std::cout << "\n";
      continue;
    }
    auto scored = scorer.scoreCandidates(splitUtf8(f[0]), splitUtf8(f[1]), f[2],
                                         splitBy(f[3], ','));
    std::string out;
    for (size_t i = 0; i < scored.size(); ++i) {
      if (i) out += ",";
      char buf[64];
      std::snprintf(buf, sizeof(buf), "%.6f", scored[i].second);
      out += scored[i].first + ":" + buf;
    }
    std::cout << out << "\n";
  }
  return 0;
}
