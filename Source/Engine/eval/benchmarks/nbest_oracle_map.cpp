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

// nbest_oracle_map — 棒⑭-P：全語料 N-best oracle coverage。
//
// 對每一個「walk 解錯」的字位，回答：**金標字第一次出現在第幾條 N-best 路徑上？**
//
//   path_rank = 0    出貨路徑本身就有（不會發生 —— 這些是錯字）
//   path_rank = k    第 k+1 條路徑（0-based）第一次出現
//   path_rank = -1   200 條路徑內都沒出現（**只代表 >200，不代表不存在**）
//
// 另外輸出第二個檔（<out>.sent.tsv）：每一句在 top-K 裡**單一最佳路徑**的錯字數。
// 這是必要的對照 —— 逐字 oracle 假設每個字都能挑到最好的路徑，
// 但重排器一句只能選一條，逐字 oracle 因此**不可達**。
//
// ## 為什麼不能用既有的 node 候選 rank 代替
//
// ⑭-M/⑭-O 的 `gold_rank` 是**同一個 walk 節點內、unigram 分數的名次**，
// 它回答的是「換這個節點的值能不能修好」。
// 本棒要回答的是另一個問題：「**正確的整句**在不在搜尋空間裡」——
// 那要看路徑，不是看單一節點。兩者不可互換。
//
// ## 洩漏
//
// `walkNBest` 是純推論（λ=0.75、ν=0.75、N-best 10 的出貨配置），
// **候選與路徑的產生完全不涉及金標**；金標只用來測試「有沒有命中」。
// 因此結果是 **ORACLE / UPPER BOUND**，不是 inference coverage。
//
// 用法：
//   nbest_oracle_map <sentences.jsonl> <data.txt> <word-bigrams.tsv>
//                    <path-char-lstm.bin> <out.tsv> [maxN=200]

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
    "sid\tpos\tchosen\tgold\tpath_rank\tmax_n\n";

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
    std::cerr << "usage: nbest_oracle_map <sentences.jsonl> <data.txt> "
                 "<word-bigrams.tsv> <path-char-lstm.bin> <out.tsv> [maxN]\n";
    return 1;
  }
  const size_t maxN = argc > 6 ? std::stoul(argv[6]) : 200;

  ParselessLM lm;
  if (!lm.open(argv[2])) {
    std::cerr << "FATAL: data.txt\n";
    return 1;
  }
  CorpusBigramContextModel cm;
  if (!cm.load(argv[3])) {
    std::cerr << "FATAL: bigrams\n";
    return 1;
  }
  // 出貨配置。漏掉這一行會讓 lambda_ 留在預設 1.0，解碼結果就不是出貨路徑
  // —— 棒⑭-P 第一次跑就是這樣，錯位數 3,301 而不是 3,192。
  cm.setLambda(0.75);
  NeuralLMPathScorer scorer;
  if (!scorer.load(argv[4])) {
    std::cerr << "FATAL: lstm\n";
    return 1;
  }

  std::ifstream in(argv[1]);
  std::ofstream out(argv[5]);
  if (!in || !out) {
    std::cerr << "FATAL: io\n";
    return 1;
  }
  out << kHeader;
  std::ofstream sout(std::string(argv[5]) + ".sent.tsv");
  if (!sout) {
    std::cerr << "FATAL: sent io\n";
    return 1;
  }
  sout << "sid\tn_chars\twalk_err\tbest1\tbest10\tbest20\tbest200\n";

  long sid = 0, sentences = 0, errPos = 0, hit = 0, lenMismatch = 0;
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty()) continue;
    ++sid;
    const std::string text = jsonStringField(line, "text");
    const std::string readings = jsonStringField(line, "readings");
    if (text.empty() || readings.empty()) continue;
    std::vector<std::string> goldChars = utf8Chars(text);
    std::vector<std::string> syls = splitSyllables(readings);
    if (goldChars.size() != syls.size()) {
      ++lenMismatch;
      continue;
    }
    ++sentences;

    ReadingGrid grid = makeGrid(&lm);
    if (!feed(grid, syls, syls.size())) continue;
    grid.setContextModel(&cm);
    grid.setPathScorer(&scorer);
    grid.setPathRerankNu(0.75);
    grid.setPathRerankNBest(10);
    auto w = grid.walk();

    std::vector<std::string> walkChars;
    for (size_t n = 0; n < w.nodes.size(); ++n) {
      for (const auto& c : utf8Chars(w.chosenValueAt(n))) walkChars.push_back(c);
    }
    if (walkChars.size() != goldChars.size()) continue;

    std::vector<size_t> wrong;
    for (size_t i = 0; i < goldChars.size(); ++i) {
      if (walkChars[i] != goldChars[i]) wrong.push_back(i);
    }
    if (wrong.empty()) continue;
    errPos += static_cast<long>(wrong.size());

    // 一次取 maxN 條路徑，記下每個錯位第一次命中金標的路徑序號。
    auto paths = grid.walkNBest(maxN);
    std::vector<long> rank(goldChars.size(), -1);
    // 每一句在 top-K 裡「單一最佳路徑」的錯字數（K = 1/10/20/200）
    long best[4] = {static_cast<long>(wrong.size()), static_cast<long>(wrong.size()),
                    static_cast<long>(wrong.size()), static_cast<long>(wrong.size())};
    const size_t cut[4] = {1, 10, 20, maxN};
    for (size_t pi = 0; pi < paths.size(); ++pi) {
      std::vector<std::string> pc;
      for (const auto& wd : paths[pi].words) {
        for (const auto& c : utf8Chars(wd)) pc.push_back(c);
      }
      if (pc.size() != goldChars.size()) continue;
      long e = 0;
      for (size_t i = 0; i < goldChars.size(); ++i) {
        if (pc[i] != goldChars[i]) ++e;
      }
      for (int b = 0; b < 4; ++b) {
        if (pi < cut[b] && e < best[b]) best[b] = e;
      }
      for (size_t i : wrong) {
        if (rank[i] < 0 && pc[i] == goldChars[i]) {
          rank[i] = static_cast<long>(pi);
        }
      }
    }
    sout << sid << "\t" << goldChars.size() << "\t" << wrong.size() << "\t"
         << best[0] << "\t" << best[1] << "\t" << best[2] << "\t" << best[3]
         << "\n";

    for (size_t i : wrong) {
      if (rank[i] >= 0) ++hit;
      out << sid << "\t" << i << "\t" << sanitize(walkChars[i]) << "\t"
          << sanitize(goldChars[i]) << "\t" << rank[i] << "\t"
          << paths.size() << "\n";
    }
    if (sid % 1000 == 0) {
      std::cerr << "…" << sid << " 句，" << errPos << " 個錯位，命中 " << hit
                << "\n";
    }
  }
  std::cerr << "SENTENCES " << sentences << "\nLEN_MISMATCH " << lenMismatch
            << "\nERROR_POSITIONS " << errPos << "\nHIT_WITHIN_N " << hit
            << "\n";
  return 0;
}
