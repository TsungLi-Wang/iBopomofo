// 階段一/二 harness:量 unigram 引擎 top-1(baseline)vs 字元 n-gram rescorer(rescored)。
//
// rescorer 原則:只在引擎「已產生的合法候選」裡用上下文重挑,絕不生成新內容。
// 第一版的 n-gram 完全從既有 Source/Data/data.txt 的詞頻推出(字元 bigram,以詞頻加權),
// 不依賴任何外部語料——當「能跑的第一版」,之後可換成真語料訓練的 KenLM trigram。
//
// 獨立編譯,見 build-and-run.sh。輸出 baseline 與 rescored 兩個 top-1 準確率。

#include <cmath>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

#include "ParselessLM.h"
#include "gramambular2/reading_grid.h"

using Formosa::Gramambular2::ReadingGrid;
using McBopomofo::ParselessLM;

namespace {

constexpr double kLambda = 3.0;  // n-gram 上下文相對 unigram 的權重
constexpr double kAlpha = 0.5;   // add-alpha 平滑

struct Case {
  std::string readings;
  std::string expected;
};

std::vector<std::string> splitSyllables(const std::string& s) {
  std::vector<std::string> out;
  std::string cur;
  for (char c : s) {
    if (c == '-') {
      if (!cur.empty()) out.push_back(cur);
      cur.clear();
    } else {
      cur.push_back(c);
    }
  }
  if (!cur.empty()) out.push_back(cur);
  return out;
}

// 把 UTF-8 字串切成一個個字元(codepoint 子字串)。
std::vector<std::string> utf8Chars(const std::string& s) {
  std::vector<std::string> out;
  size_t i = 0;
  while (i < s.size()) {
    size_t len = 1;
    unsigned char c = static_cast<unsigned char>(s[i]);
    if ((c & 0x80) == 0) len = 1;
    else if ((c & 0xE0) == 0xC0) len = 2;
    else if ((c & 0xF0) == 0xE0) len = 3;
    else if ((c & 0xF8) == 0xF0) len = 4;
    out.push_back(s.substr(i, len));
    i += len;
  }
  return out;
}
std::string firstChar(const std::string& s) {
  auto v = utf8Chars(s);
  return v.empty() ? "" : v.front();
}
std::string lastChar(const std::string& s) {
  auto v = utf8Chars(s);
  return v.empty() ? "" : v.back();
}

// 從 data.txt 推字元 bigram:每個多字詞 value 以詞頻 exp(score) 加權,累加相鄰字轉移。
struct CharBigram {
  std::unordered_map<std::string, std::unordered_map<std::string, double>> bi;
  std::unordered_map<std::string, double> left;
  double vocab = 1.0;

  void build(const std::string& dataPath) {
    std::ifstream in(dataPath);
    std::string line;
    std::unordered_map<std::string, bool> seenChar;
    while (std::getline(in, line)) {
      if (line.empty() || line[0] == '#') continue;
      std::istringstream iss(line);
      std::string reading, value, scoreStr;
      if (!(iss >> reading >> value >> scoreStr)) continue;
      double w = 1.0;
      try { w = std::exp(std::stod(scoreStr)); } catch (...) { w = 1e-9; }
      auto chars = utf8Chars(value);
      if (chars.size() < 2) continue;
      for (size_t i = 0; i + 1 < chars.size(); ++i) {
        bi[chars[i]][chars[i + 1]] += w;
        left[chars[i]] += w;
        seenChar[chars[i]] = true;
        seenChar[chars[i + 1]] = true;
      }
    }
    vocab = std::max<double>(1.0, static_cast<double>(seenChar.size()));
  }

  double logP(const std::string& a, const std::string& b) const {
    if (a.empty() || b.empty()) return 0.0;
    double c = 0.0, L = 0.0;
    auto it = bi.find(a);
    if (it != bi.end()) {
      auto jt = it->second.find(b);
      if (jt != it->second.end()) c = jt->second;
    }
    auto lt = left.find(a);
    if (lt != left.end()) L = lt->second;
    return std::log((c + kAlpha) / (L + kAlpha * vocab));
  }
};

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

// baseline:引擎 walk 的 top-1,直接串接各節點 value。
std::string baselineTop1(ParselessLM* lm, const std::string& readings) {
  ReadingGrid grid = makeGrid(lm);
  if (!feed(grid, readings)) return "<insert-failed>";
  std::string out;
  for (const auto& v : grid.walk().valuesAsStrings()) out += v;
  return out;
}

// rescored:沿 walk 的切詞,對每個節點「在它自己的合法候選裡」用左右字元 n-gram 重挑。
// 只重排候選、不生成;切詞沿用引擎結果(第一版不動 segmentation)。
std::string rescoredTop1(ParselessLM* lm, const CharBigram& ng,
                         const std::string& readings) {
  ReadingGrid grid = makeGrid(lm);
  if (!feed(grid, readings)) return "<insert-failed>";
  auto walk = grid.walk();
  std::vector<std::string> sel;
  for (size_t i = 0; i < walk.nodes.size(); ++i) {
    const auto& node = walk.nodes[i];
    std::string prev = sel.empty() ? "" : lastChar(sel.back());
    std::string next =
        (i + 1 < walk.nodes.size()) ? firstChar(walk.nodes[i + 1]->value()) : "";
    std::string bestVal = node->value();
    double bestScore = -1e18;
    for (const auto& u : node->unigrams()) {
      const std::string& v = u.value();
      double s = u.score() +
                 kLambda * (ng.logP(prev, firstChar(v)) + ng.logP(lastChar(v), next));
      if (s > bestScore) {
        bestScore = s;
        bestVal = v;
      }
    }
    sel.push_back(bestVal);
  }
  std::string out;
  for (const auto& v : sel) out += v;
  return out;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "用法: rerank_eval <path/to/data.txt>\n";
    return 2;
  }
  ParselessLM lm;
  if (!lm.open(argv[1])) {
    std::cerr << "無法開啟辭典: " << argv[1] << "\n";
    return 1;
  }
  CharBigram ng;
  ng.build(argv[1]);
  std::cout << "字元 bigram 已建(vocab=" << ng.vocab << ")\n";

  std::vector<Case> cases = {
      {"ㄧㄢˊ-ㄐㄧㄡˋ-ㄕㄥ-ㄇㄧㄥˋ", "研究生命"},
      {"ㄨㄛˇ-ㄕˋ-ㄧㄢˊ-ㄐㄧㄡˋ-ㄕㄥ", "我是研究生"},
      {"ㄧˋ-ㄏㄤˊ-ㄖㄣˊ", "一行人"},
      {"ㄨㄛˇ-ㄗㄞˋ-ㄓㄜˋ-ㄌㄧˇ", "我在這裡"},
      {"ㄨㄛˇ-ㄗㄞˋ-ㄕㄨㄛ-ㄧˋ-ㄘˋ", "我再說一次"},
      {"ㄊㄞˊ-ㄨㄢ-ㄉㄜ˙-ㄊㄧㄢ-ㄑㄧˋ", "台灣的天氣"},
      {"ㄒㄧㄝˋ-ㄒㄧㄝ˙-ㄋㄧˇ", "謝謝你"},
      {"ㄐㄧㄣ-ㄊㄧㄢ-ㄊㄧㄢ-ㄑㄧˋ-ㄏㄣˇ-ㄏㄠˇ", "今天天氣很好"},
  };

  int baseOK = 0, reOK = 0;
  std::cout << "=== baseline(unigram) vs rescored(字元 n-gram) ===\n";
  for (const auto& c : cases) {
    std::string b = baselineTop1(&lm, c.readings);
    std::string r = rescoredTop1(&lm, ng, c.readings);
    bool bo = (b == c.expected), ro = (r == c.expected);
    baseOK += bo;
    reOK += ro;
    std::cout << (bo ? "B-OK " : "B-MISS") << " " << b << "   "
              << (ro ? "R-OK " : "R-MISS") << " " << r << "   want=" << c.expected
              << "\n";
  }
  size_t n = cases.size();
  std::cout << "----\n";
  std::cout << "baseline top-1: " << baseOK << "/" << n << "  ("
            << (100.0 * baseOK / n) << "%)\n";
  std::cout << "rescored top-1: " << reOK << "/" << n << "  ("
            << (100.0 * reOK / n) << "%)\n";
  return 0;
}
