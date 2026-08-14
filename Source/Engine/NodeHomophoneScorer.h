// Copyright (c) 2026 and onwards The McBopomofo Authors.
//
// Permission is hereby granted, free of charge, to any person
// obtaining a copy of this software and associated documentation
// files (the "Software"), to deal in the Software without
// restriction, including without limitation the rights to use,
// copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the
// Software is furnished to do so, subject to the following
// conditions:
//
// The above copyright notice and this permission notice shall be
// included in all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
// EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
// OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
// NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
// HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
// WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
// FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
// OTHER DEALINGS IN THE SOFTWARE.

#ifndef SRC_ENGINE_NODEHOMOPHONESCORER_H_
#define SRC_ENGINE_NODEHOMOPHONESCORER_H_

#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#include "gramambular2/reading_grid.h"

namespace iBopomofo {

using ReadingGrid = Formosa::Gramambular2::ReadingGrid;

// 「看注音、選同音」的節點層打分器（docs/decisions/0008）。
//
// 職位：**這個音在這句裡該出哪個候選**。
//   輸入 = 目標位置的注音（帶調）+ 左右文字元 + 候選集合
//   輸出 = 候選上的分數
//
// 跟 NeuralLMPathScorer 是**不同的職位**，兩個並存不衝突：
//   NeuralLMPathScorer  猜下一個漢字，對 N-best 路徑重排（路徑層）
//   本類別              P(字|注音,左右文)，在節點既有候選裡改選（節點層）
//
// 為什麼是節點層：路徑層 oracle 85.3%、節點層 95.9%（docs/decisions/0004、0007）。
// 接線位置選錯不是效果差一點，是上限被架構鎖死。
//
// 安全設計（沿用 0007 的四條，一條都不放寬）：
//   * 只用 selectOverrideUnigram —— 只能在節點既有候選裡改選，不會生成新字。
//   * **棄權＝不 override**：最高分沒有比引擎原判高過門檻就完全不動。
//     沒有棄權的專家會把「不確定」變成「亂改」，那正是六組同音規則翻車的樣態。
//   * 使用者手選／UOM 覆寫過的節點永不被蓋。
//   * 一次只換節點裡的一個字，其餘不動。
class NodeHomophoneScorer {
 public:
  bool load(const std::string& path);
  [[nodiscard]] bool isLoaded() const { return loaded_; }
  [[nodiscard]] size_t parameterCount() const;

  // 分差門檻（log-softmax 差）。門檻只准在 dev 上定，不准在真實驗證集上挑
  // —— 那就是「同一份資料選參數又報成績」（docs/dead-ends.md B 節）。
  void setMargin(double m) { margin_ = m; }
  [[nodiscard]] double margin() const { return margin_; }

  // 逐字掃過 walk，在節點既有候選裡改選。回傳有沒有動過任何節點。
  bool rescoreWalk(const ReadingGrid::WalkResult& walk);
  void reset() { applied_.clear(); }

  // 單點打分（給評測／單元測試用）：回傳候選字 → log-softmax 分。
  // leftChars/rightChars 由近而遠不重要，傳入時就是正常閱讀順序。
  std::vector<std::pair<std::string, float>> scoreCandidates(
      const std::vector<std::string>& leftChars,
      const std::vector<std::string>& rightChars, const std::string& reading,
      const std::vector<std::string>& candidates) const;

  // 這個讀音在模型的候選表裡有幾個字（<2 就沒得選，直接跳過）。
  [[nodiscard]] size_t candidateCountForReading(const std::string& reading) const;

 private:
  static constexpr size_t kWindow = 10;  // 與 build_node_homophone_data.py 相同

  bool loaded_ = false;
  int emb_ = 0, hidden_ = 0, layers_ = 0, readEmb_ = 0, merge_ = 0;
  int nChar_ = 0, nReading_ = 0;
  double margin_ = 0.0;

  std::vector<std::string> itos_;
  std::unordered_map<std::string, int> stoi_;
  std::vector<std::string> readings_;
  std::unordered_map<std::string, int> rtoi_;
  std::vector<std::vector<int>> cand_;  // reading id → 候選字 id

  std::vector<float> charEmb_, readEmbW_;
  // [方向][層]，方向 0 = 左文順讀、1 = 右文逆讀
  std::vector<std::vector<float>> wIh_[2], wHh_[2], bIh_[2], bHh_[2];
  std::vector<float> m0W_, m0B_, m1W_, m1B_, outW_, outB_;

  std::unordered_map<ReadingGrid::Node*, std::weak_ptr<ReadingGrid::Node>>
      applied_;
  [[nodiscard]] bool isAppliedByUs(const ReadingGrid::NodePtr& node) const;

  void lstmStep(int dir, int layer, const float* x, const float* hPrev,
                const float* cPrev, float* hOut, float* cOut) const;
  // 跑完一個方向的 LSTM，回傳最後一層最後一步的 h（長度 hidden_）。
  void runSide(int dir, const std::vector<int>& ids,
               std::vector<float>* out) const;
  void hiddenState(const std::vector<int>& leftIds,
                   const std::vector<int>& rightIds, int readingId,
                   std::vector<float>* out) const;
};

}  // namespace iBopomofo

#endif  // SRC_ENGINE_NODEHOMOPHONESCORER_H_
