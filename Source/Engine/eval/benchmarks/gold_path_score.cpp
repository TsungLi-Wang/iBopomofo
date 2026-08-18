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

// path_score_dump — 棒⑭-Q：把 top-10 每一條路徑的**現有 production 融合分數**
// 與它的組成倒出來，用來量「現有 scoring 分不分得出 gold path」。
//
// ## 融合公式（照抄 reading_grid.cpp 的 walk() rerank 分支）
//
//     finalScore = walkScore + adjust + nu * rnn
//
//   walkScore  DP 分數 ＝ unigram 總和 ＋ λ·PMI（ContextModel）
//   rnn        PathScorer（NeuralLMPathScorer）對整句的分數
//   nu         0.75（出貨值）
//   adjust     同音頻率先驗壓縮。本工具**不設** confusionAlphas_
//              （出貨的 confusion-alphas.tsv 條目已清空，見 docs/decisions/0004），
//              所以 adjust 恆為 0 —— 與出貨路徑一致。
//
// ## 為什麼不能直接讀 RankedPath::pathScore
//
// `walkNBest()` **不填** pathScore；它只在 `walk()` 的 rerank 分支裡被算在
// 一份區域性的複本上，然後丟掉。所以本工具自己呼叫 `scoreNBest` 重算一次，
// 並且**驗證重算的 argmax 等於 walk() 實際輸出的整句** —— 那就是 provenance 檢查。
//
// ## 洩漏
//
// 路徑、候選、分數全部由推論產生，不涉及金標。金標只用來
// (a) 數每條路徑錯幾個字、(b) 標哪一條是 gold path。
//
// 用法：
//   path_score_dump <sentences.jsonl> <data.txt> <word-bigrams.tsv>
//                   <path-char-lstm.bin> <out.tsv> [nbest=10] [all=0]
//
// all=1 連**解對的句子**也倒（棒⑭-R 的對稱誤傷分析需要）。
// 預設 0 ＝ 只倒解錯的句子，與棒⑭-Q 的輸出逐位相同。

// gold_path_score — 棒⑭-T：把 gold path 強制構造出來，用**出貨公式**打分。
//
// ## 這一支要解開的 ambiguity
//
// ⑭-P 量到「43.1% of D2 的正解連 top-200 都沒有」，但 `walkNBest()` **不是
// exact k-best** —— 它是 beam DP（`reading_grid.h` `kNBestHypK = 8`，每個
// (位置, 前一個詞) 狀態只留 8 個 hypothesis）。實測 81.8% 的錯字位根本
// 拿不到 200 條路徑。所以「不在 top-200」**不能**直接讀成
// 「打分器把 gold 排到第 201 名以後」—— 它可能壓根沒被枚舉。
//
// 本工具繞過搜尋，直接問：
//
//     如果 gold path 存在，出貨打分器會給它多少分？
//
// ## gold path 怎麼構造
//
// 不經過 ReadingGrid。直接對「讀音序列 × 金標字串」做一次受限 DP：
// 只允許那些 value **恰好等於對應金標子字串**的 unigram。
// 因為 ⑭-O 已證每個金標字在自己的單音節讀音下都查得到（LEXICON = 0），
// 全單字斷詞必然可行，所以 gold path **永遠存在**。
// DP 每個狀態保留 kGoldK 個 hypothesis（比出貨的 8 寬），
// 取出多條 gold 斷詞後全部用 RNN 打分，取 fused 最大者 ——
// 因此回報值是 gold path 最佳分數的**下界**。
//
// ## 出貨公式（照抄 reading_grid.cpp）
//
//     walkScore = Σ unigram.score() + Σ contextModel->scoreWithReading(...)
//     fused     = walkScore + ν · rnn        （ν=0.75、λ=0.75、adjust=0）
//
// ## 洩漏
//
// gold 只用來**構造被測量的 counterfactual 物件**與判定命中，
// **不進入任何 feature、不影響任何分數的計算方式**。
//
// 用法：
//   gold_path_score <sentences.jsonl> <data.txt> <word-bigrams.tsv>
//                   <path-char-lstm.bin> <out.tsv>

#include <algorithm>
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
    "sid\tpath_idx\tn_err\tis_walk\tis_gold\tengine_correct\twalk_score\t"
    "unigram_sum\tpmi\trnn\tfused\n";

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




namespace {

constexpr size_t kGoldK = 16;      // gold DP 每狀態保留幾個 hyp（>出貨的 8）
constexpr size_t kMaxSpan = 6;     // 詞庫最長詞的保守上限
constexpr double kNu = 0.75;

struct GoldHyp {
  double score = 0.0;
  std::vector<std::string> words;
};

}  // namespace

int main(int argc, char** argv) {
  if (argc < 6) {
    std::cerr << "usage: gold_path_score <sentences.jsonl> <data.txt> "
                 "<word-bigrams.tsv> <path-char-lstm.bin> <out.tsv>\n";
    return 1;
  }
  ParselessLM lm;
  if (!lm.open(argv[2])) { std::cerr << "FATAL: data.txt\n"; return 1; }
  CorpusBigramContextModel cm;
  if (!cm.load(argv[3])) { std::cerr << "FATAL: bigrams\n"; return 1; }
  cm.setLambda(0.75);
  NeuralLMPathScorer scorer;
  if (!scorer.load(argv[4])) { std::cerr << "FATAL: lstm\n"; return 1; }

  std::ifstream in(argv[1]);
  std::ofstream out(argv[5]);
  if (!in || !out) { std::cerr << "FATAL: io\n"; return 1; }
  out << "sid\tengine_correct\twalk_err\ttop1_walk\ttop1_rnn\ttop1_fused\t"
         "gold_found\tgold_walk\tgold_rnn\tgold_fused\tgold_nseg\t"
         "gold_enumerated\tprov_ok\tprov_paths\n";

  long sid = 0, sents = 0, provOK = 0, provTot = 0, goldMiss = 0;
  long top1OK = 0, top1Bad = 0;
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty()) continue;
    ++sid;
    const std::string text = jsonStringField(line, "text");
    const std::string readings = jsonStringField(line, "readings");
    if (text.empty() || readings.empty()) continue;
    std::vector<std::string> goldChars = utf8Chars(text);
    std::vector<std::string> syls = splitSyllables(readings);
    if (goldChars.size() != syls.size()) continue;
    ++sents;

    // ── production walk / walkNBest ──
    ReadingGrid grid = makeGrid(&lm);
    if (!feed(grid, syls, syls.size())) continue;
    grid.setContextModel(&cm);
    grid.setPathScorer(&scorer);
    grid.setPathRerankNu(kNu);
    grid.setPathRerankNBest(10);
    auto w = grid.walk();
    std::string walkOut;
    for (size_t n = 0; n < w.nodes.size(); ++n) walkOut += w.chosenValueAt(n);
    const bool engineCorrect = (walkOut == text);

    auto nbest = grid.walkNBest(200);
    if (nbest.empty()) continue;
    std::vector<std::vector<std::string>> pw;
    for (const auto& rp : nbest) pw.push_back(rp.words);
    std::vector<double> rnns = scorer.scoreNBest(pw);

    // ── provenance：獨立重算 walkScore，必須與 RankedPath::walkScore 相同 ──
    long okHere = 0;
    for (size_t pi = 0; pi < nbest.size(); ++pi) {
      const auto& rp = nbest[pi];
      double re = 0.0;
      std::string prev;
      for (size_t ni = 0; ni < rp.nodes.size(); ++ni) {
        const auto& ug = rp.nodes[ni]->unigrams();
        if (ni >= rp.selectedUnigramIndices.size() ||
            rp.selectedUnigramIndices[ni] >= ug.size()) { re = 1e18; break; }
        double st = 0.0;
        re += ug[rp.selectedUnigramIndices[ni]].score() +
              cm.scoreWithReading(prev, rp.nodes[ni]->reading(),
                                  ug[rp.selectedUnigramIndices[ni]].value(), st);
        prev = ug[rp.selectedUnigramIndices[ni]].value();
      }
      ++provTot;
      if (std::fabs(re - rp.walkScore) < 1e-6) { ++provOK; ++okHere; }
    }

    // production top-1 = fused argmax **只在前 10 條之內**
    // （出貨是 setPathRerankNBest(10)；拿 200 條取 argmax 不是出貨行為）。
    size_t bi = 0; double bf = -std::numeric_limits<double>::infinity();
    const size_t prodN = std::min<size_t>(10, nbest.size());
    for (size_t pi = 0; pi < prodN; ++pi) {
      double f = nbest[pi].walkScore + kNu * rnns[pi];
      if (f > bf) { bf = f; bi = pi; }
    }
    {   // provenance：重算的 top-1 必須逐字等於 walk() 的輸出
      std::string repro;
      for (const auto& x : nbest[bi].words) repro += x;
      if (repro == walkOut) ++top1OK; else ++top1Bad;
    }

    // gold 是否被實際枚舉到
    bool goldEnum = false;
    for (const auto& p : pw) {
      std::string j;
      for (const auto& x : p) j += x;
      if (j == text) { goldEnum = true; break; }
    }

    // ── 受限 DP：只走 value == 對應金標子字串的 unigram ──
    const size_t L = syls.size();
    std::vector<std::vector<GoldHyp>> dp(L + 1);
    dp[0].push_back(GoldHyp{});
    for (size_t i = 0; i < L; ++i) {
      if (dp[i].empty()) continue;
      for (size_t sp = 1; sp <= kMaxSpan && i + sp <= L; ++sp) {
        std::string key = syls[i];
        for (size_t k = 1; k < sp; ++k) key += "-" + syls[i + k];
        std::string target;
        for (size_t k = 0; k < sp; ++k) target += goldChars[i + k];
        auto us = lm.getUnigrams(key);
        double usc = 0.0; bool found = false;
        for (const auto& u : us) {
          if (u.value() == target) { usc = u.score(); found = true; break; }
        }
        if (!found) continue;
        for (const auto& h : dp[i]) {
          double st = 0.0;
          std::string prev = h.words.empty() ? std::string() : h.words.back();
          GoldHyp nh;
          nh.score = h.score + usc + cm.scoreWithReading(prev, key, target, st);
          nh.words = h.words;
          nh.words.push_back(target);
          dp[i + sp].push_back(std::move(nh));
        }
        auto& cell = dp[i + sp];
        std::stable_sort(cell.begin(), cell.end(),
                         [](const GoldHyp& a, const GoldHyp& b) {
                           return a.score > b.score;
                         });
        if (cell.size() > kGoldK) cell.resize(kGoldK);
      }
    }

    bool goldFound = !dp[L].empty();
    double gWalk = 0, gRnn = 0, gFused = 0;
    size_t gN = 0;
    if (!goldFound) {
      ++goldMiss;
    } else {
      std::vector<std::vector<std::string>> gp;
      for (const auto& h : dp[L]) gp.push_back(h.words);
      std::vector<double> grn = scorer.scoreNBest(gp);
      gFused = -std::numeric_limits<double>::infinity();
      for (size_t k = 0; k < dp[L].size(); ++k) {
        double f = dp[L][k].score + kNu * grn[k];
        if (f > gFused) {
          gFused = f; gWalk = dp[L][k].score; gRnn = grn[k];
          gN = dp[L][k].words.size();
        }
      }
    }

    long we = 0;
    {
      std::vector<std::string> wc = utf8Chars(walkOut);
      if (wc.size() != goldChars.size()) we = static_cast<long>(goldChars.size());
      else for (size_t i2 = 0; i2 < goldChars.size(); ++i2)
             if (wc[i2] != goldChars[i2]) ++we;
    }

    out << sid << "\t" << (engineCorrect ? 1 : 0) << "\t" << we << "\t"
        << nbest[bi].walkScore << "\t" << rnns[bi] << "\t" << bf << "\t"
        << (goldFound ? 1 : 0) << "\t" << gWalk << "\t" << gRnn << "\t"
        << gFused << "\t" << gN << "\t" << (goldEnum ? 1 : 0) << "\t"
        << okHere << "\t" << nbest.size() << "\n";

    if (sid % 1000 == 0) std::cerr << "…" << sid << " 句\n";
  }
  std::cerr << "SENTENCES " << sents << "\nPROV_WALKSCORE_MATCH " << provOK
            << " / " << provTot << "\nTOP1_REPRODUCES_WALK " << top1OK
            << " MISMATCH " << top1Bad
            << "\nGOLD_PATH_NOT_CONSTRUCTIBLE " << goldMiss << "\n";
  return 0;
}
