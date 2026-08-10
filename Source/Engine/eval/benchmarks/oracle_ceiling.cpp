// oracle_ceiling.cpp — 重排器的天花板在哪？
//
// 要回答的問題：現在選錯的那些題目，**正確答案到底有沒有出現在候選裡**？
//
//   有 → 問題是「排序」，換更好的重排器（例如專門的神經模型）就有機會修
//   沒有 → 正確答案根本沒被產生出來，再強的重排器也救不回來，
//          該修的是候選生成／詞圖，不是重排
//
// 這個數字決定「中文警察」那條路值不值得走，而且不用訓任何模型就能算。
//
// 量三個層次的上界（由鬆到緊）：
//
//   O1  10-best 路徑上界：十條候選路徑裡，有沒有哪一條在目標位置是正解？
//       → 現行架構（v2c 對 N=10 重排）的天花板
//
//   O2  節點內改選上界：走出來的那條路徑上，蓋住目標位置的那個節點，
//       能不能改選成別的候選字而讓目標位置變成正解？
//       → ParticleRuleDisambiguator 這類「只在節點內重選」的機制的天花板
//          （現行文法規則層就是這一類）
//
//   O3  200-best 路徑上界：把 N 從 10 放大到 200 還撈不撈得到正解？
//       → 用來看「N 開大有沒有用」。**這不是絕對天花板** ——
//          它仍然只看分數前 200 名的路徑，而正解那條可能排在更後面。
//          實測 O3 有時候比 O2 還低，就是這個原因（O2 允許在既定斷詞下
//          改選節點內的候選，那條路徑不見得進得了前 200 名）。
//
// 用法（參數與 newstar_homophone_eval 前四個相同）：
//   oracle_ceiling <items.jsonl> <data.txt> <word-bigrams.tsv> <v2c.bin> [nbest]

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iostream>
#include <map>
#include <string>
#include <vector>

#include "CorpusBigramContextModel.h"
#include "NeuralLMPathScorer.h"
#include "ParselessLM.h"
#include "gramambular2/reading_grid.h"

using Formosa::Gramambular2::ReadingGrid;
using McBopomofo::CorpusBigramContextModel;
using McBopomofo::NeuralLMPathScorer;
using McBopomofo::ParselessLM;

namespace {

std::vector<std::string> utf8Chars(const std::string& s) {
  std::vector<std::string> out;
  size_t i = 0;
  while (i < s.size()) {
    unsigned char c = static_cast<unsigned char>(s[i]);
    size_t len = (c & 0x80) == 0      ? 1
                 : (c & 0xE0) == 0xC0 ? 2
                 : (c & 0xF0) == 0xE0 ? 3
                 : (c & 0xF8) == 0xF0 ? 4
                                      : 1;
    if (i + len > s.size()) break;
    out.push_back(s.substr(i, len));
    i += len;
  }
  return out;
}

std::string jsonStr(const std::string& line, const std::string& key) {
  const std::string pat = "\"" + key + "\"";
  size_t k = line.find(pat);
  if (k == std::string::npos) return "";
  size_t q1 = line.find('"', line.find(':', k + pat.size()) + 1);
  if (q1 == std::string::npos) return "";
  size_t q2 = q1 + 1;
  while (q2 < line.size() && !(line[q2] == '"' && line[q2 - 1] != '\\')) ++q2;
  return line.substr(q1 + 1, q2 - q1 - 1);
}

int jsonInt(const std::string& line, const std::string& key, int dflt) {
  const std::string pat = "\"" + key + "\"";
  size_t k = line.find(pat);
  if (k == std::string::npos) return dflt;
  size_t i = line.find(':', k + pat.size()) + 1;
  while (i < line.size() && line[i] == ' ') ++i;
  size_t j = i;
  if (j < line.size() && line[j] == '-') ++j;
  while (j < line.size() && isdigit(static_cast<unsigned char>(line[j]))) ++j;
  return j > i ? std::stoi(line.substr(i, j - i)) : dflt;
}

std::vector<std::string> splitSyllables(const std::string& readings) {
  std::string norm;
  for (char c : readings) {
    if (c == ' ' || c == '\t') {
      if (!norm.empty() && norm.back() != '-') norm.push_back('-');
    } else {
      norm.push_back(c);
    }
  }
  std::vector<std::string> out;
  size_t start = 0;
  for (size_t i = 0; i <= norm.size(); ++i) {
    if (i == norm.size() || norm[i] == '-') {
      if (i > start) out.push_back(norm.substr(start, i - start));
      start = i + 1;
    }
  }
  return out;
}

struct Item {
  std::string pair_id, split, sentence, target_char, full_reading;
  int target_index = -1;
};

// 這條路徑在 target_index 這個字級位置上是哪個字？
std::string charAtIndex(const std::vector<std::string>& words, int index) {
  int seen = 0;
  for (const std::string& w : words) {
    std::vector<std::string> cs = utf8Chars(w);
    if (index < seen + static_cast<int>(cs.size())) {
      return cs[index - seen];
    }
    seen += static_cast<int>(cs.size());
  }
  return "";
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 5) {
    std::cerr << "Usage: oracle_ceiling <items.jsonl> <data.txt> "
                 "<word-bigrams.tsv> <v2c.bin> [nbest]\n";
    return 1;
  }
  const size_t nbest = argc > 5 ? std::stoul(argv[5]) : 10;
  // 第 6 個參數：逐題診斷輸出。給了就寫出每一題的分層資訊，
  // 讓 error_taxonomy.py 判斷「這個錯誤是哪一層造成的」。
  const std::string diagPath = argc > 6 ? argv[6] : "";

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
  cm.setLambda(0.75);
  NeuralLMPathScorer scorer;
  bool hasScorer = scorer.load(argv[4]);

  std::ifstream in(argv[1]);
  std::vector<Item> items;
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty() || line[0] == '#') continue;
    Item it;
    it.pair_id = jsonStr(line, "pair_id");
    it.split = jsonStr(line, "split");
    it.sentence = jsonStr(line, "sentence");
    it.target_char = jsonStr(line, "target_char");
    it.full_reading = jsonStr(line, "full_reading");
    it.target_index = jsonInt(line, "target_index", -1);
    if (it.target_index >= 0 && !it.target_char.empty()) items.push_back(it);
  }
  std::cout << "ORACLE items=" << items.size() << " nbest=" << nbest
            << " scorer=" << (hasScorer ? 1 : 0) << "\n";

  struct Agg {
    int n = 0, top1 = 0, o1 = 0, o2 = 0, o3 = 0;
  };
  std::map<std::string, Agg> per;   // split|pair
  std::map<std::string, Agg> tot;   // split
  std::ofstream diag;
  if (!diagPath.empty()) {
    diag.open(diagPath);
    diag << "sentence\tpair\tsplit\tgold\tchosen\tin_node\tin_10best\t"
            "in_200best\tnode_len\tscore_gap\tsegments\n";
  }

  for (const Item& it : items) {
    ReadingGrid grid(std::shared_ptr<Formosa::Gramambular2::LanguageModel>(
        &lm, [](Formosa::Gramambular2::LanguageModel*) {}));
    grid.setReadingSeparator("-");
    bool fed = true;
    for (const std::string& syl : splitSyllables(it.full_reading)) {
      grid.setCursor(grid.length());
      if (!grid.insertReading(syl)) {
        fed = false;
        break;
      }
    }
    if (!fed) continue;
    grid.setContextModel(&cm);
    if (hasScorer) {
      grid.setPathScorer(&scorer);
      grid.setPathRerankNu(0.75);
      grid.setPathRerankNBest(nbest);
    }

    Agg* a = &per[it.split + "|" + it.pair_id];
    Agg* t = &tot[it.split];
    a->n++;
    t->n++;

    // 出貨路徑（含 v2c 重排）
    auto w = grid.walk();
    std::string out;
    for (size_t i = 0; i < w.nodes.size(); ++i) out += w.chosenValueAt(i);
    bool ok = (charAtIndex({out}, it.target_index) == it.target_char);
    if (ok) {
      a->top1++;
      t->top1++;
    }

    // O1：10-best 任一條路徑
    bool inNBest = ok;
    if (!inNBest) {
      auto paths = grid.walkNBest(nbest);
      for (const auto& p : paths) {
        if (charAtIndex(p.words, it.target_index) == it.target_char) {
          inNBest = true;
          break;
        }
      }
    }
    if (inNBest) {
      a->o1++;
      t->o1++;
    }

    // O2：出貨路徑上蓋住目標位置的節點，能不能改選出正解
    bool repick = ok;
    if (!repick) {
      int seen = 0;
      for (size_t ni = 0; ni < w.nodes.size(); ++ni) {
        std::vector<std::string> cs = utf8Chars(w.chosenValueAt(ni));
        int len = static_cast<int>(cs.size());
        if (it.target_index < seen + len) {
          size_t off = static_cast<size_t>(it.target_index - seen);
          for (const auto& ug : w.nodes[ni]->unigrams()) {
            std::vector<std::string> uc = utf8Chars(ug.value());
            if (uc.size() == cs.size() && off < uc.size() &&
                uc[off] == it.target_char) {
              repick = true;
              break;
            }
          }
          break;
        }
        seen += len;
      }
    }
    if (repick) {
      a->o2++;
      t->o2++;
    }

    // O3：詞圖裡任何一條路徑（用很大的 N 逼近）
    bool anyPath = inNBest;
    if (!anyPath) {
      auto paths = grid.walkNBest(200);
      for (const auto& p : paths) {
        if (charAtIndex(p.words, it.target_index) == it.target_char) {
          anyPath = true;
          break;
        }
      }
    }
    if (anyPath) {
      a->o3++;
      t->o3++;
    }

    if (diag) {
      // 目標位置所在節點的長度，以及「被選中的候選」與「正解候選」的分數差。
      // 分數差就是頻率先驗的落差 —— 它是判斷「是不是被詞頻壓死」的關鍵。
      int seen = 0;
      size_t nodeLen = 0;
      double gap = 0.0;
      std::string chosen;
      std::string segs;
      for (size_t ni = 0; ni < w.nodes.size(); ++ni) {
        if (ni) segs += "|";
        segs += w.chosenValueAt(ni);
      }
      for (size_t ni = 0; ni < w.nodes.size(); ++ni) {
        std::vector<std::string> cs = utf8Chars(w.chosenValueAt(ni));
        int len = static_cast<int>(cs.size());
        if (it.target_index < seen + len) {
          nodeLen = cs.size();
          size_t off = static_cast<size_t>(it.target_index - seen);
          chosen = cs[off];
          double chosenScore = 0.0, goldScore = 0.0;
          bool haveC = false, haveG = false;
          for (const auto& ug : w.nodes[ni]->unigrams()) {
            std::vector<std::string> uc = utf8Chars(ug.value());
            if (uc.size() != cs.size() || off >= uc.size()) continue;
            if (!haveC && uc[off] == chosen) { chosenScore = ug.score(); haveC = true; }
            if (!haveG && uc[off] == it.target_char) { goldScore = ug.score(); haveG = true; }
          }
          if (haveC && haveG) gap = chosenScore - goldScore;
          break;
        }
        seen += len;
      }
      diag << it.sentence << "\t" << it.pair_id << "\t" << it.split << "\t"
           << it.target_char << "\t" << chosen << "\t" << (repick ? 1 : 0)
           << "\t" << (inNBest ? 1 : 0) << "\t" << (anyPath ? 1 : 0) << "\t"
           << nodeLen << "\t" << gap << "\t" << segs << "\n";
    }
  }

  auto pct = [](int x, int n) {
    return n ? 100.0 * x / n : 0.0;
  };
  for (const std::string& sp : {std::string("heldout"), std::string("train")}) {
    if (!tot.count(sp)) continue;
    const Agg& g = tot[sp];
    std::cout << "\n=== " << sp << " ===\n";
    printf("%-10s %6s %9s %9s %9s %9s\n", "組", "題數", "現況", "O1(10best)",
           "O2(節點內)", "O3(200best)");
    printf("%-10s %6d %8.1f%% %8.1f%% %8.1f%% %8.1f%%\n", "總計", g.n,
           pct(g.top1, g.n), pct(g.o1, g.n), pct(g.o2, g.n), pct(g.o3, g.n));
    for (const auto& kv : per) {
      if (kv.first.rfind(sp + "|", 0) != 0) continue;
      const Agg& x = kv.second;
      printf("%-10s %6d %8.1f%% %8.1f%% %8.1f%% %8.1f%%\n",
             kv.first.substr(sp.size() + 1).c_str(), x.n, pct(x.top1, x.n),
             pct(x.o1, x.n), pct(x.o2, x.n), pct(x.o3, x.n));
    }
  }
  return 0;
}
