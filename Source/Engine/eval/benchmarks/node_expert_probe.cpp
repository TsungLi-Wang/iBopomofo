// node_expert_probe — 把 NodeHomophoneExpert 的單點打分挖出來，跟 PyTorch 對數字。
//
// ## 為什麼這是換模型的第一道關卡
//
// 匯出格式錯一個位元組（矩陣方向、GELU 版本、左右文補 PAD 的對齊、特徵縮放…），
// C++ 端照樣「載得起來、分數看起來合理」，然後後面所有 A/B 數字都是假的。
// 這種錯不會報錯，只會讓人花半天怪模型。**兩邊不同分，後面什麼都不必看。**
//
// 輸入直接吃 node_sample_extract 產生的 nodes.tsv（含表頭），
// 每行輸出該節點各候選的 log-softmax，逗號分隔，順序＝候選在檔裡的順序
// （已按 unigram 分數排序並截到 max_cands，與訓練端同一條規則）。
//
//   node_expert_probe <model.bin> < nodes.tsv > scores.txt

#include <algorithm>
#include <array>
#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "NodeHomophoneExpert.h"

namespace {

// 與 train_node_expert.py 的 MAX_CANDS 相同。兩邊改一邊就會靜默不同分。
constexpr int kMaxCands = 24;

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
  if (!s.empty() && s.back() == sep) out.push_back("");
  return out;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "usage: node_expert_probe <model.bin> < nodes.tsv\n";
    return 2;
  }
  iBopomofo::NodeHomophoneExpert expert;
  if (!expert.load(argv[1])) {
    std::cerr << "FATAL: cannot load " << argv[1] << "\n";
    return 1;
  }
  std::cerr << "loaded params=" << expert.parameterCount() << "\n";

  std::string line;
  bool first = true;
  while (std::getline(std::cin, line)) {
    if (first) {  // 表頭
      first = false;
      continue;
    }
    std::vector<std::string> f = splitBy(line, '\t');
    if (f.size() < 16) {
      std::cout << "\n";
      continue;
    }
    const std::vector<std::string> syllables = splitBy(f[6], '-');
    const bool rightEmpty = f[14] == "1";
    // 候選要先按 unigram 分數排序再截斷 —— **與訓練端同一條規則**。
    // 順序不同分數就不同（softmax 集合不同），parity 會假紅燈。
    struct Cand {
      std::string value;
      double unigram;
      std::array<float, 4> feat;
    };
    std::vector<Cand> cands;
    for (const std::string& c : splitBy(f[15], '|')) {
      std::vector<std::string> p = splitBy(c, ':');
      if (p.size() != 5) continue;
      const double u = std::stod(p[1]);
      cands.push_back({p[0], u,
                       {static_cast<float>(u / 10.0),
                        static_cast<float>(std::stod(p[2])),
                        static_cast<float>(std::stod(p[3])),
                        p[4] == "1" ? 1.f : 0.f}});
    }
    std::stable_sort(cands.begin(), cands.end(),
                     [](const Cand& a, const Cand& b) {
                       return a.unigram > b.unigram;
                     });
    if (cands.size() > static_cast<size_t>(kMaxCands)) {
      cands.resize(static_cast<size_t>(kMaxCands));
    }
    std::vector<std::string> values;
    std::vector<std::array<float, 4>> feats;
    for (const Cand& c : cands) {
      values.push_back(c.value);
      feats.push_back(c.feat);
    }
    if (values.size() < 2) {
      std::cout << "\n";
      continue;
    }
    auto scores = expert.scoreCandidates(splitUtf8(f[12]), splitUtf8(f[13]),
                                         syllables, rightEmpty, values, feats);
    std::string out;
    for (size_t i = 0; i < scores.size(); ++i) {
      if (i) out += ",";
      char buf[48];
      std::snprintf(buf, sizeof(buf), "%.6f", scores[i]);
      out += buf;
    }
    std::cout << out << "\n";
  }
  return 0;
}
