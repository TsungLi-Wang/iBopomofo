// full_corpus_error_map — 棒⑭-M：把**整批語料的每一個 walk 節點**倒出來，
// 用來畫全語料字級錯誤地圖。
//
// ## 為什麼不能直接用 node_sample_extract
//
// 那支是抽**訓練樣本**用的，有一行 `if (unigrams.size() >= 2)` ——
// 只有一個候選的節點不會被發射。對訓練沒差（沒得選就沒得學），
// 但對「重現整句解碼結果」是致命的：少了那些節點，重組出來的句子是破的
// （實測只重組出 34,136 字，真值 73,756 字的一半不到）。
//
// 這支發射**每一個**節點，並且多帶三個地圖需要的欄位：
//   n_cands     該節點的候選總數
//   gold_rank   金標在候選中的名次（依 unigram 分數排序，0-based；不在則 -1）
//   chosen_rank 引擎選的那個的名次
//
// 其餘配置與 node_sample_extract／ship-gate 的 shipping 路徑完全相同
// （λ=0.75、ν=0.75、N-best 10、無 UOM），只讀不寫，不碰 production。
//
// ⚠️ 這是 **walk 層的解碼結果**，不含 ParticleRuleDisambiguator 規則層。
//    與 0008 §D 的 95.773% 比較時必須把這件事說出來。
//
// 用法：
//   full_corpus_error_map <sentences.jsonl> <data.txt> <word-bigrams.tsv>
//                         <path-char-lstm.bin> <out.tsv>

#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
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

constexpr const char* kHeader =
    "sid\tsplit\tkind\tnode_index\tchar_start\tspan\treading\tchosen\tgold\t"
    "gold_in_cands\tn_cands\tgold_rank\tchosen_rank\t"
    "left_word\tright_word\tleft_chars\tright_chars\t"
    "right_empty\tcands\n";

std::vector<std::string> utf8Chars(const std::string& s) {
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
    } else {
      ++i;
      continue;
    }
    if (i + len > s.size()) break;
    out.push_back(s.substr(i, len));
    i += len;
  }
  return out;
}

std::string jsonStringField(const std::string& line, const std::string& key) {
  const std::string pat = "\"" + key + "\"";
  size_t k = line.find(pat);
  if (k == std::string::npos) return "";
  size_t colon = line.find(':', k + pat.size());
  if (colon == std::string::npos) return "";
  size_t q1 = line.find('"', colon + 1);
  if (q1 == std::string::npos) return "";
  size_t q2 = q1 + 1;
  while (q2 < line.size()) {
    if (line[q2] == '"' && line[q2 - 1] != '\\') break;
    ++q2;
  }
  if (q2 >= line.size()) return "";
  return line.substr(q1 + 1, q2 - q1 - 1);
}

std::vector<std::string> splitSyllables(const std::string& readings) {
  std::vector<std::string> out;
  size_t start = 0;
  for (size_t i = 0; i <= readings.size(); ++i) {
    if (i == readings.size() || readings[i] == '-') {
      if (i > start) out.push_back(readings.substr(start, i - start));
      start = i + 1;
    }
  }
  return out;
}

ReadingGrid makeGrid(ParselessLM* lm) {
  ReadingGrid grid(std::shared_ptr<Formosa::Gramambular2::LanguageModel>(
      lm, [](Formosa::Gramambular2::LanguageModel*) {}));
  grid.setReadingSeparator("-");
  return grid;
}

bool feed(ReadingGrid& grid, const std::vector<std::string>& syls, size_t n) {
  for (size_t i = 0; i < n && i < syls.size(); ++i) {
    grid.setCursor(grid.length());
    if (!grid.insertReading(syls[i])) return false;
  }
  return true;
}

std::string joinChars(const std::vector<std::string>& chars, size_t from,
                      size_t to) {
  std::string s;
  for (size_t i = from; i < to && i < chars.size(); ++i) s += chars[i];
  return s;
}

// TSV 安全：欄位裡不該出現 tab / 換行 / 我們的分隔符。真的出現就換掉，
// 不要靜默寫出一個欄位數對不上的檔（下游只會看到莫名其妙的錯位）。
std::string sanitize(std::string s) {
  for (char& c : s) {
    if (c == '\t' || c == '\n' || c == '\r' || c == '|' || c == ':') c = '_';
  }
  return s;
}

struct Sample {
  std::string line;
};

}  // namespace

int main(int argc, char** argv) {
  if (argc < 6) {
    std::cerr << "usage: node_sample_extract <sentences.jsonl> <data.txt> "
                 "<word-bigrams.tsv> <path-char-lstm.bin> <out.tsv> "
                 "[prefix_every]\n";
    return 2;
  }
  const std::string sentPath = argv[1];
  const std::string dataPath = argv[2];
  const std::string bigramPath = argv[3];
  const std::string lstmPath = argv[4];
  const std::string outPath = argv[5];
  const int prefixEvery = argc > 6 ? std::atoi(argv[6]) : 4;

  ParselessLM lm;
  if (!lm.open(dataPath.c_str())) {
    std::cerr << "FATAL: cannot open data.txt\n";
    return 1;
  }
  CorpusBigramContextModel cm;
  if (!cm.load(bigramPath.c_str())) {
    std::cerr << "FATAL: cannot load bigrams\n";
    return 1;
  }
  cm.setLambda(0.75);
  NeuralLMPathScorer scorer;
  if (!scorer.load(lstmPath.c_str())) {
    std::cerr << "FATAL: cannot load path scorer\n";
    return 1;
  }

  std::ifstream in(sentPath);
  if (!in) {
    std::cerr << "FATAL: cannot open sentences\n";
    return 1;
  }
  std::ofstream out(outPath);
  if (!out) {
    std::cerr << "FATAL: cannot write out\n";
    return 1;
  }
  out << kHeader;

  long sid = 0, emitted = 0, feedFail = 0, goldMiss = 0, sentences = 0;
  long lenMismatch = 0, prefixSamples = 0;
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty()) continue;
    ++sid;
    const std::string text = jsonStringField(line, "text");
    const std::string readings = jsonStringField(line, "readings");
    const std::string split = jsonStringField(line, "split");
    if (text.empty() || readings.empty()) continue;
    std::vector<std::string> goldChars = utf8Chars(text);
    std::vector<std::string> syls = splitSyllables(readings);
    if (goldChars.size() != syls.size()) {
      ++lenMismatch;
      continue;
    }
    ++sentences;

    // kind=0 完整句；kind=1 前綴（右邊被切掉，模擬人還在打）
    for (int kind = 0; kind < 2; ++kind) {
      size_t take = syls.size();
      if (kind == 1) {
        if (prefixEvery <= 0 || (sid % prefixEvery) != 0) continue;
        // 切在 1/3 ~ 2/3 之間，讓右邊真的是空的
        take = syls.size() / 2 + 1;
        if (take < 2 || take >= syls.size()) continue;
      }
      ReadingGrid grid = makeGrid(&lm);
      if (!feed(grid, syls, take)) {
        ++feedFail;
        continue;
      }
      grid.setContextModel(&cm);
      grid.setPathScorer(&scorer);
      grid.setPathRerankNu(0.75);
      grid.setPathRerankNBest(10);
      auto w = grid.walk();

      // 攤平 walk 的字，供左右文特徵用（一律 chosenValueAt，不是 value()）
      std::vector<std::string> walkChars;
      std::vector<std::string> nodeValues;
      for (size_t n = 0; n < w.nodes.size(); ++n) {
        nodeValues.push_back(w.chosenValueAt(n));
        for (const auto& c : utf8Chars(nodeValues.back())) walkChars.push_back(c);
      }

      size_t charStart = 0;
      for (size_t n = 0; n < w.nodes.size(); ++n) {
        const auto& node = w.nodes[n];
        const size_t span = node->spanningLength();
        if (charStart + span > goldChars.size()) break;

        const std::string goldSpan = joinChars(goldChars, charStart, charStart + span);
        const std::string chosen = nodeValues[n];
        const auto& unigrams = node->unigrams();

        {
          bool goldIn = false;
          long goldRank = -1, chosenRank = -1;
          for (size_t ui = 0; ui < unigrams.size(); ++ui) {
            if (unigrams[ui].value() == goldSpan && goldRank < 0) {
              goldIn = true;
              goldRank = static_cast<long>(ui);
            }
            if (unigrams[ui].value() == chosen && chosenRank < 0) {
              chosenRank = static_cast<long>(ui);
            }
          }
          if (!goldIn) ++goldMiss;

          const std::string leftWord = n > 0 ? nodeValues[n - 1] : "";
          const std::string rightWord =
              (n + 1 < nodeValues.size()) ? nodeValues[n + 1] : "";
          const std::string leftChars =
              joinChars(walkChars, charStart >= 6 ? charStart - 6 : 0, charStart);
          const std::string rightChars =
              joinChars(walkChars, charStart + span, charStart + span + 6);
          const bool rightEmpty = (charStart + span >= walkChars.size());

          std::string cands;
          for (size_t ui = 0; ui < unigrams.size(); ++ui) {
            const auto& u = unigrams[ui];
            if (ui) cands += "|";
            std::ostringstream os;
            // ContextModel::score 的 state 是 in/out 參考（DP 用來帶狀態），
            // 這裡每次都給一個新的 0 —— 我們要的是單點 PMI，不是路徑狀態。
            double stateL = 0.0;
            double stateR = 0.0;
            os << sanitize(u.value()) << ":" << u.score() << ":"
               << cm.score(leftWord, u.value(), stateL) << ":"
               << cm.score(u.value(), rightWord, stateR) << ":"
               << (u.value() == chosen ? 1 : 0);
            cands += os.str();
          }

          out << sid << "\t" << split << "\t" << kind << "\t" << n << "\t"
              << charStart << "\t" << span << "\t" << sanitize(node->reading())
              << "\t" << sanitize(chosen) << "\t" << sanitize(goldSpan) << "\t"
              << (goldIn ? 1 : 0) << "\t" << unigrams.size() << "\t"
              << goldRank << "\t" << chosenRank << "\t"
              << sanitize(leftWord) << "\t"
              << sanitize(rightWord) << "\t" << sanitize(leftChars) << "\t"
              << sanitize(rightChars) << "\t" << (rightEmpty ? 1 : 0) << "\t"
              << cands << "\n";
          ++emitted;
          if (kind == 1) ++prefixSamples;
        }
        charStart += span;
      }
    }
    if (sid % 5000 == 0) {
      std::cerr << "…" << sid << " 句，" << emitted << " 個節點樣本\n";
    }
  }

  std::cerr << "SENTENCES " << sentences << "\nLEN_MISMATCH " << lenMismatch
            << "\nFEED_FAIL " << feedFail << "\nEMITTED " << emitted
            << "\nPREFIX_SAMPLES " << prefixSamples << "\nGOLD_NOT_IN_CANDS "
            << goldMiss << "\n";
  return 0;
}
