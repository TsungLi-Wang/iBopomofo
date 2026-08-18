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

// beam_survival_audit — 棒⑮ 工作流 A：bounded beam / pruning attribution。
//
// ## 唯一問題
//
// ⑭-T 量到：production 選錯的 2,042 句裡，26.7%（545 句）出貨打分器其實更喜歡
// gold path，而其中 **87.9%（479 句）的 gold path 從未被枚舉**。
// 這一支問：**它是在 beam 的哪一個階段被剪掉的？把 K 放寬最多能救回多少？**
//
// ## 方法
//
// 自行複製 `walkNBest()` 的 beam DP（`dp[pos][lastWord]` 每格保留 K 個 hyp），
// 並在每個 hypothesis 上多帶一個 `isGold` 旗標
// （＝該前綴串起來剛好等於金標的前綴）。於是可以直接觀察：
//
//   * gold 前綴活到第幾個字位才被丟掉
//   * 把 K 從出貨的 8 放寬到 16 / 32 / 64，gold 是否活到終點
//   * 活到終點後，它在 walkScore 排序裡是不是進得了出貨的**前 10 條**重排視窗
//   * 進得了的話，出貨的 fused 公式會不會真的選它
//
// **K=8 必須逐句重現出貨輸出** —— 那是本工具的 provenance gate。
//
// ## 紀律
//
// 只做 attribution，**不修改 production**、不改 `kNBestHypK`、不改任何權重。
// 放寬 K 只發生在本工具的記憶體裡，不寫回任何檔案。
//
// 用法：
//   beam_survival_audit <sentences.jsonl> <data.txt> <word-bigrams.tsv>
//                       <path-char-lstm.bin> <out.tsv>

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

constexpr double kNu = 0.75;
constexpr size_t kProdWindow = 10;      // 出貨 setPathRerankNBest(10)
const std::vector<size_t> kKs = {8, 16, 32, 64};

struct Hyp {
  double score = 0.0;
  bool isGold = false;
  size_t prevPos = 0;
  std::string prevWord;
  size_t prevIdx = 0;
  std::string word;
};

// 複製 walkNBest 的 beam：dp[pos][lastWord] 保留 K 個，依分數排序。
struct BeamResult {
  bool goldAlive = false;         // gold 前綴活到終點
  long lastAlivePos = -1;         // gold 前綴最後一次存活的字位（-1 = 從未建立）
  long goldWalkRank = -1;         // gold 在終點依 walkScore 的名次（0-based）
  long edges = 0;
  std::vector<std::vector<std::string>> top;   // 依 walkScore 取前 kProdWindow 條
  std::vector<double> topWalk;
  long goldTopIdx = -1;           // gold 在 top 裡的位置（-1 = 不在）
};

}  // namespace

int main(int argc, char** argv) {
  if (argc < 6) {
    std::cerr << "usage: beam_survival_audit <sentences.jsonl> <data.txt> "
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
  out << "sid\tengine_correct\twalk_err\tK\tgold_alive\tlast_alive_pos\tsent_len\t"
         "gold_walk_rank\tgold_in_window\tpick_err\tedges\n";

  long sid = 0, sents = 0, provOK = 0, provBad = 0;
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
    const size_t L = syls.size();

    // 出貨的 walk（用來對帳與算目前錯字數）
    ReadingGrid grid = makeGrid(&lm);
    if (!feed(grid, syls, L)) continue;
    grid.setContextModel(&cm);
    grid.setPathScorer(&scorer);
    grid.setPathRerankNu(kNu);
    grid.setPathRerankNBest(kProdWindow);
    auto w0 = grid.walk();
    std::string walkOut;
    for (size_t n = 0; n < w0.nodes.size(); ++n) walkOut += w0.chosenValueAt(n);
    const bool engineCorrect = (walkOut == text);
    long walkErr = 0;
    {
      std::vector<std::string> wc = utf8Chars(walkOut);
      if (wc.size() != goldChars.size()) walkErr = (long)goldChars.size();
      else for (size_t i2 = 0; i2 < goldChars.size(); ++i2)
             if (wc[i2] != goldChars[i2]) ++walkErr;
    }

    // 預先抓每個 (起點, 跨度) 的候選（含金標子字串是哪一個）
    for (size_t ki = 0; ki < kKs.size(); ++ki) {
      const size_t K = kKs[ki];
      std::vector<std::unordered_map<std::string, std::vector<Hyp>>> dp(L + 1);
      dp[0][std::string()].push_back(Hyp{0.0, true, 0, "", 0, ""});
      BeamResult br;
      std::vector<long> aliveAt(L + 1, 0);
      aliveAt[0] = 1;

      for (size_t i = 0; i < L; ++i) {
        if (dp[i].empty()) continue;
        for (size_t sp = 1; sp <= 6 && i + sp <= L; ++sp) {
          std::string key = syls[i];
          for (size_t k = 1; k < sp; ++k) key += "-" + syls[i + k];
          auto us = lm.getUnigrams(key);
          if (us.empty()) continue;
          std::string goldSpan;
          for (size_t k = 0; k < sp; ++k) goldSpan += goldChars[i + k];
          auto& target = dp[i + sp];
          for (const auto& entry : dp[i]) {
            const std::string& prevWord = entry.first;
            for (size_t hi = 0; hi < entry.second.size(); ++hi) {
              const Hyp& ph = entry.second[hi];
              for (const auto& u : us) {
                double st = 0.0;
                double sc = ph.score + u.score() +
                            cm.scoreWithReading(prevWord, key, u.value(), st);
                ++br.edges;
                Hyp nh;
                nh.score = sc;
                nh.isGold = ph.isGold && (u.value() == goldSpan);
                nh.prevPos = i;
                nh.prevWord = prevWord;
                nh.prevIdx = hi;
                nh.word = u.value();
                auto& cell = target[u.value()];
                cell.push_back(std::move(nh));
              }
            }
          }
          // 每格排序後裁到 K
          for (auto& kv : target) {
            std::stable_sort(kv.second.begin(), kv.second.end(),
                             [](const Hyp& a, const Hyp& b) {
                               return a.score > b.score;
                             });
            if (kv.second.size() > K) kv.second.resize(K);
          }
        }
        for (const auto& kv : dp[i + 1 <= L ? i + 1 : L]) (void)kv;
      }
      for (size_t p = 1; p <= L; ++p) {
        long a = 0;
        for (const auto& kv : dp[p])
          for (const auto& h : kv.second) if (h.isGold) { a = 1; break; }
        aliveAt[p] = a;
        if (a) br.lastAlivePos = (long)p;
      }
      br.goldAlive = aliveAt[L] == 1;

      // 終點依 walkScore 排序，取出前 kProdWindow 條完整路徑
      std::vector<std::pair<double, std::pair<std::string, size_t>>> fin;
      for (const auto& kv : dp[L])
        for (size_t hi = 0; hi < kv.second.size(); ++hi)
          fin.push_back({kv.second[hi].score, {kv.first, hi}});
      std::stable_sort(fin.begin(), fin.end(),
                       [](const auto& a, const auto& b) { return a.first > b.first; });
      auto rebuild = [&](const std::string& lw, size_t hi) {
        std::vector<std::string> ws;
        size_t pos = L; std::string cw = lw; size_t ci = hi;
        while (pos > 0) {
          const Hyp& h = dp[pos].at(cw)[ci];
          ws.push_back(h.word);
          pos = h.prevPos; cw = h.prevWord; ci = h.prevIdx;
        }
        std::reverse(ws.begin(), ws.end());
        return ws;
      };
      for (size_t r = 0; r < fin.size(); ++r) {
        const Hyp& h = dp[L].at(fin[r].second.first)[fin[r].second.second];
        if (h.isGold && br.goldWalkRank < 0) br.goldWalkRank = (long)r;
        if (br.top.size() < kProdWindow) {
          br.top.push_back(rebuild(fin[r].second.first, fin[r].second.second));
          br.topWalk.push_back(fin[r].first);
          if (h.isGold) br.goldTopIdx = (long)br.top.size() - 1;
        }
      }

      long pickErr = walkErr;
      if (!br.top.empty()) {
        std::vector<double> rn = scorer.scoreNBest(br.top);
        size_t bi = 0; double bf = -std::numeric_limits<double>::infinity();
        for (size_t r = 0; r < br.top.size(); ++r) {
          double f = br.topWalk[r] + kNu * rn[r];
          if (f > bf) { bf = f; bi = r; }
        }
        std::string j;
        for (const auto& x : br.top[bi]) j += x;
        std::vector<std::string> jc = utf8Chars(j);
        pickErr = 0;
        if (jc.size() != goldChars.size()) pickErr = (long)goldChars.size();
        else for (size_t i2 = 0; i2 < goldChars.size(); ++i2)
               if (jc[i2] != goldChars[i2]) ++pickErr;
        if (K == 8) { if (j == walkOut) ++provOK; else ++provBad; }
      }

      out << sid << "\t" << (engineCorrect ? 1 : 0) << "\t" << walkErr << "\t"
          << K << "\t" << (br.goldAlive ? 1 : 0) << "\t" << br.lastAlivePos
          << "\t" << L << "\t" << br.goldWalkRank << "\t"
          << (br.goldTopIdx >= 0 ? 1 : 0) << "\t" << pickErr << "\t"
          << br.edges << "\n";
    }
    if (sid % 1000 == 0) std::cerr << "…" << sid << " 句\n";
  }
  std::cerr << "SENTENCES " << sents << "\nK8_REPRODUCES_WALK " << provOK
            << " MISMATCH " << provBad << "\n";
  return 0;
}
