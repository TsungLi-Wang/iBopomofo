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

#include "ConfusionPairDisambiguator.h"
#include "ParselessLM.h"
#include "gramambular2/reading_grid.h"

using Formosa::Gramambular2::ReadingGrid;
using McBopomofo::ConfusionPairDisambiguator;
using McBopomofo::ParselessLM;

namespace {

constexpr double kAlpha = 0.5;   // add-alpha 平滑
constexpr double kUnigramWeight = 0.10;
constexpr double kBigramWeight = 0.28;
constexpr double kTrigramWeight = 0.72;

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
    if (tab == std::string::npos) {
      std::cerr << "略過格式錯誤測資:" << line << "\n";
      continue;
    }
    std::string readings = line.substr(0, tab);
    std::string expected = line.substr(tab + 1);
    if (readings.empty() || expected.empty()) continue;
    cases.push_back({readings, expected});
  }
  return cases;
}

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

std::vector<std::string> splitTabs(const std::string& s) {
  std::vector<std::string> out;
  std::string cur;
  for (char c : s) {
    if (c == '\t') {
      out.push_back(cur);
      cur.clear();
    } else {
      cur.push_back(c);
    }
  }
  out.push_back(cur);
  return out;
}

std::string joinValues(const std::vector<std::string>& values, size_t begin) {
  std::string out;
  for (size_t i = begin; i < values.size(); ++i) out += values[i];
  return out;
}

// 字元 n-gram scorer。可讀外部語料訓練出的 TSV 模型;沒有模型時,從 data.txt
// 推一個 fallback,讓 harness 永遠可跑。
struct CharNgramModel {
  std::unordered_map<std::string, double> uni;
  std::unordered_map<std::string, std::unordered_map<std::string, double>> bi;
  std::unordered_map<std::string, double> left;
  std::unordered_map<std::string, std::unordered_map<std::string, double>> tri;
  std::unordered_map<std::string, double> triLeft;
  std::unordered_map<std::string, double> phrase;
  double uniTotal = 0.0;
  double phraseTotal = 0.0;
  double vocab = 1.0;
  bool external = false;

  void buildFallbackFromData(const std::string& dataPath) {
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
      phrase[value] += w;
      phraseTotal += w;
      for (const auto& ch : chars) {
        uni[ch] += w;
        uniTotal += w;
        seenChar[ch] = true;
      }
      if (chars.size() < 2) continue;
      for (size_t i = 0; i + 1 < chars.size(); ++i) {
        bi[chars[i]][chars[i + 1]] += w;
        left[chars[i]] += w;
      }
      for (size_t i = 0; i + 2 < chars.size(); ++i) {
        std::string prefix = chars[i] + chars[i + 1];
        tri[prefix][chars[i + 2]] += w;
        triLeft[prefix] += w;
      }
    }
    vocab = std::max<double>(1.0, static_cast<double>(seenChar.size()));
  }

  bool loadExternal(const std::string& modelPath) {
    std::ifstream in(modelPath);
    if (!in.good()) return false;
    std::string line;
    std::unordered_map<std::string, bool> seenChar;
    while (std::getline(in, line)) {
      if (line.empty() || line[0] == '#') continue;
      auto fields = splitTabs(line);
      if (fields.size() < 3) continue;
      double count = 0.0;
      try {
        count = std::stod(fields.back());
      } catch (...) {
        continue;
      }
      if (count <= 0) continue;

      if (fields[0] == "U" && fields.size() == 3) {
        uni[fields[1]] += count;
        uniTotal += count;
        seenChar[fields[1]] = true;
      } else if (fields[0] == "B" && fields.size() == 4) {
        bi[fields[1]][fields[2]] += count;
        left[fields[1]] += count;
        seenChar[fields[1]] = true;
        seenChar[fields[2]] = true;
      } else if (fields[0] == "T" && fields.size() == 5) {
        std::string prefix = fields[1] + fields[2];
        tri[prefix][fields[3]] += count;
        triLeft[prefix] += count;
        seenChar[fields[1]] = true;
        seenChar[fields[2]] = true;
        seenChar[fields[3]] = true;
      } else if (fields[0] == "P" && fields.size() == 3) {
        phrase[fields[1]] += count;
        phraseTotal += count;
      }
    }
    vocab = std::max<double>(1.0, static_cast<double>(seenChar.size()));
    external = !uni.empty() || !bi.empty() || !tri.empty();
    return external;
  }

  double logUni(const std::string& a) const {
    if (a.empty()) return 0.0;
    double c = 0.0;
    auto it = uni.find(a);
    if (it != uni.end()) c = it->second;
    return std::log((c + kAlpha) / (uniTotal + kAlpha * vocab));
  }

  double logBi(const std::string& a, const std::string& b) const {
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

  double logTri(const std::string& a, const std::string& b,
                const std::string& c) const {
    if (a.empty() || b.empty() || c.empty()) return 0.0;
    std::string prefix = a + b;
    double count = 0.0, L = 0.0;
    auto it = tri.find(prefix);
    if (it != tri.end()) {
      auto jt = it->second.find(c);
      if (jt != it->second.end()) count = jt->second;
    }
    auto lt = triLeft.find(prefix);
    if (lt != triLeft.end()) L = lt->second;
    return std::log((count + kAlpha) / (L + kAlpha * vocab));
  }

  double logPhrase(const std::string& value) const {
    double count = 0.0;
    auto it = phrase.find(value);
    if (it != phrase.end()) count = it->second;
    return std::log((count + kAlpha) / (phraseTotal + kAlpha * vocab));
  }

  double scoreText(const std::string& text, const std::string& candidate) const {
    auto chars = utf8Chars(text);
    if (chars.empty()) return -1e18;
    double score = 0.12 * logPhrase(candidate);
    for (size_t i = 0; i < chars.size(); ++i) {
      if (i >= 2) {
        score += kTrigramWeight * logTri(chars[i - 2], chars[i - 1], chars[i]);
        score += kBigramWeight * logBi(chars[i - 1], chars[i]);
      } else if (i >= 1) {
        score += logBi(chars[i - 1], chars[i]);
      } else {
        score += kUnigramWeight * logUni(chars[i]);
      }
    }
    return score;
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
std::string rescoredTop1(ParselessLM* lm, const CharNgramModel& ng,
                         const std::string& readings) {
  ReadingGrid grid = makeGrid(lm);
  if (!feed(grid, readings)) return "<insert-failed>";
  auto walk = grid.walk();
  std::vector<std::string> walkValues;
  for (const auto& node : walk.nodes) walkValues.push_back(node->value());
  std::vector<std::string> sel;
  for (size_t i = 0; i < walk.nodes.size(); ++i) {
    const auto& node = walk.nodes[i];
    std::string bestVal = node->value();
    double bestScore = -1e18;
    size_t candidateIndex = 0;
    for (const auto& u : node->unigrams()) {
      const std::string& v = u.value();
      std::string text;
      for (const auto& part : sel) text += part;
      text += v;
      text += joinValues(walkValues, i + 1);
      double s = u.score() + ng.scoreText(text, v) - (0.03 * candidateIndex);
      if (s > bestScore) {
        bestScore = s;
        bestVal = v;
      }
      ++candidateIndex;
    }
    sel.push_back(bestVal);
  }
  std::string out;
  for (const auto& v : sel) out += v;
  return out;
}

// disambiguated:引擎 walk top-1,再套 ConfusionPairDisambiguator(正式出貨
// 路徑,只在同讀音單字節點內軟覆寫,不動切詞)。
std::string disambiguatedTop1(ParselessLM* lm, ConfusionPairDisambiguator& d,
                              const std::string& readings) {
  ReadingGrid grid = makeGrid(lm);
  if (!feed(grid, readings)) return "<insert-failed>";
  ReadingGrid::WalkResult walk = grid.walk();
  d.reset();
  d.rescoreWalk(walk);
  std::string out;
  for (const auto& v : walk.valuesAsStrings()) out += v;
  return out;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 3) {
    std::cerr << "用法: rerank_eval <data.txt> <cases.tsv> [ngram-model.tsv]"
                 " [confusion-table.tsv]\n";
    return 2;
  }
  ParselessLM lm;
  if (!lm.open(argv[1])) {
    std::cerr << "無法開啟辭典: " << argv[1] << "\n";
    return 1;
  }
  CharNgramModel ng;
  if (argc >= 4 && argv[3][0] != '\0' && ng.loadExternal(argv[3])) {
    std::cout << "外部字元 trigram 已載入(vocab=" << ng.vocab << ")\n";
  } else {
    ng.buildFallbackFromData(argv[1]);
    std::cout << "詞庫 fallback 字元 n-gram 已建(vocab=" << ng.vocab << ")\n";
  }

  ConfusionPairDisambiguator disambiguator;
  bool hasConfusionTable =
      argc >= 5 && argv[4][0] != '\0' && disambiguator.load(argv[4]);
  if (hasConfusionTable) {
    std::cout << "混淆對 log-odds 表已載入:" << argv[4] << "\n";
  }

  std::vector<Case> cases = loadCases(argv[2]);
  if (cases.empty()) {
    std::cerr << "無可用測資: " << argv[2] << "\n";
    return 1;
  }

  int baseOK = 0, reOK = 0, disOK = 0;
  std::cout << "=== baseline(unigram) vs rescored(字元 n-gram)"
            << (hasConfusionTable ? " vs disambiguated(混淆對查表)" : "")
            << " ===\n";
  for (const auto& c : cases) {
    std::string b = baselineTop1(&lm, c.readings);
    std::string r = rescoredTop1(&lm, ng, c.readings);
    bool bo = (b == c.expected), ro = (r == c.expected);
    baseOK += bo;
    reOK += ro;
    std::cout << (bo ? "B-OK " : "B-MISS") << " " << b << "   "
              << (ro ? "R-OK " : "R-MISS") << " " << r;
    if (hasConfusionTable) {
      std::string d = disambiguatedTop1(&lm, disambiguator, c.readings);
      bool dok = (d == c.expected);
      disOK += dok;
      std::cout << "   " << (dok ? "D-OK " : "D-MISS") << " " << d;
    }
    std::cout << "   want=" << c.expected << "\n";
  }
  size_t n = cases.size();
  std::cout << "----\n";
  std::cout << "baseline top-1: " << baseOK << "/" << n << "  ("
            << (100.0 * baseOK / n) << "%)\n";
  std::cout << "rescored top-1: " << reOK << "/" << n << "  ("
            << (100.0 * reOK / n) << "%)\n";
  if (hasConfusionTable) {
    std::cout << "disambiguated top-1: " << disOK << "/" << n << "  ("
              << (100.0 * disOK / n) << "%)\n";
  }
  return 0;
}
