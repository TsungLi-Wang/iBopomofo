// lexicon_probe — 棒⑭-O：只查詞庫，不跑 walk、不解碼、不評分。
//
// 用途：把「正解到底在不在詞庫裡」與「正解在詞庫裡但這條路徑沒選它」分開。
//   * 若某個字位的單音節讀音查得到金標字 → 那是 **path / segmentation 問題**
//     （字在 lattice 裡，是搜尋沒走到）。
//   * 若查不到 → 那是 **candidate generation / 詞庫問題**。
// 沒有這個區分，就只能把兩者混報成「金標不在該節點候選裡」。
//
// 讀一份每行一個 key（讀音，多音節用 `-` 連）的檔，輸出
//   key<TAB>value1:score1|value2:score2|…
//
// ⚠️ `ParselessLM::getUnigrams` **不排序** —— 排序是 ReadingGrid 內部的
//    `ScoreRankedLanguageModel` 做的。所以輸出順序是詞庫列順序，
//    **不是詞頻名次**。要談名次的下游一定要自己依 score 排序。
//    （棒⑱ 踩過這個坑；棒⑭-O 只用它判斷「在不在」，與順序無關，結論不受影響。）
// 只讀 data.txt，不寫任何東西，不碰 production。
//
// 用法：lexicon_probe <keys.txt> <data.txt> <out.tsv>

#include <fstream>
#include <iostream>
#include <string>

#include "ParselessLM.h"

int main(int argc, char** argv) {
  if (argc < 4) {
    std::cerr << "usage: lexicon_probe <keys.txt> <data.txt> <out.tsv>\n";
    return 1;
  }
  iBopomofo::ParselessLM lm;
  if (!lm.open(argv[2])) {
    std::cerr << "FATAL: data.txt\n";
    return 1;
  }
  std::ifstream in(argv[1]);
  std::ofstream out(argv[3]);
  if (!in || !out) {
    std::cerr << "FATAL: io\n";
    return 1;
  }
  out << "key\tvalues\n";  // values = v:score|v:score|…
  std::string key;
  long n = 0, hit = 0;
  while (std::getline(in, key)) {
    while (!key.empty() && (key.back() == '\r' || key.back() == '\n')) {
      key.pop_back();
    }
    if (key.empty()) continue;
    ++n;
    auto us = lm.getUnigrams(key);
    if (!us.empty()) ++hit;
    out << key << "\t";
    for (size_t i = 0; i < us.size(); ++i) {
      if (i) out << "|";
      out << us[i].value() << ":" << us[i].score();
    }
    out << "\n";
  }
  std::cerr << "KEYS " << n << "\nWITH_UNIGRAMS " << hit << "\n";
  return 0;
}
