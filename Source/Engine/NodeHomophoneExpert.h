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

#ifndef SRC_ENGINE_NODEHOMOPHONEEXPERT_H_
#define SRC_ENGINE_NODEHOMOPHONEEXPERT_H_

#include <array>
#include <memory>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "CorpusBigramContextModel.h"
#include "gramambular2/reading_grid.h"

namespace iBopomofo {

// 節點層同音專家：在 walk 之後、節點**既有候選**裡改選，或棄權。
//
// ## 職位
//
// 輸入：一個 walk 節點的讀音、引擎給的候選（含 unigram 分數與 PMI）、
//       walk 決定的左右詞與左右字、右邊是不是空的。
// 輸出：候選上的分數。只有最高分不是引擎原判、而且分差大於 τ 時才改選。
//
// **預測單位是節點，不是字窗。** 字窗只當特徵。棒⑫ 把兩者都當字窗，
// 結果自然語料淨 −28、3,409 句在目標字以外被改 —— 那份已作廢，不要重來。
//
// ## 這不是什麼
//
// * 不是路徑重排器（棒 C 死在那裡：判別分數變不成可用的 N-best 重排）
// * 不是 next-char LM，不取代 `NeuralLMPathScorer` / `path-char-lstm.bin`
// * 不生成新字：只走 `selectOverrideUnigram`，引擎級保證只能在既有 unigram 裡改選
//
// ## 安全設計（一開始就有，不是失敗後補的）
//
// 1. **開火白名單**：預設只對「作做坐座」那個讀音（ㄗㄨㄛˋ）的節點出手。
//    模型本身學得比較廣，但程式開關預設只開這一組；加開別組是另一個 GO/NO-GO。
// 2. **ㄉㄜ˙ 永遠不開火**，即使有人把它加進白名單也一樣（見 .cpp 的硬擋）。
//    PTT 上「該寫得」有很大比例寫成「的」，那組神經路線已死（dead-ends D），
//    現役規則 `ParticleRuleDisambiguator` 留著，不准這顆去搶。
// 3. **棄權是預設**：分差沒過 τ 就完全不動，引擎維持原判。
// 4. **使用者手選／別人覆寫過的節點永不被蓋**（沿用 0007 第三條）。
// 5. **不呼叫 UOM observe**（`docs/engine-node-override.md` R1）——
//    這個類別只碰 grid，不碰 UOM；呼叫端也不准替它補上 observe。
class NodeHomophoneExpert {
 public:
  using ReadingGrid = Formosa::Gramambular2::ReadingGrid;

  bool load(const std::string& path);
  [[nodiscard]] bool isLoaded() const { return loaded_; }
  [[nodiscard]] size_t parameterCount() const;

  // τ：log-softmax 分差門檻。**只准在抽取資料自己切出來的 held-out 上定**，
  // 不准看 EX1166、不准看兩份真實驗證集、不准看 benchmark 調（dead-ends B）。
  void setTau(double tau) { tau_ = tau; }
  [[nodiscard]] double tau() const { return tau_; }

  // 開火白名單（音節字串，例如 "ㄗㄨㄛˋ"）。節點讀音的任一音節命中才考慮出手。
  void setFireReadings(const std::unordered_set<std::string>& readings) {
    fireReadings_ = readings;
  }
  [[nodiscard]] const std::unordered_set<std::string>& fireReadings() const {
    return fireReadings_;
  }

  // PMI 特徵要跟抽取時同一個來源，沒設就以 0 餵（會與訓練不一致，所以
  // rescoreWalk 在沒設時直接不出手，寧可什麼都不做）。
  void setContextModel(CorpusBigramContextModel* cm) { contextModel_ = cm; }

  // 走一次 walk 結果。回傳有沒有真的改過節點。
  bool rescoreWalk(const ReadingGrid::WalkResult& walk);
  void reset() { applied_.clear(); }

  // 統計（給報告用）：考慮過幾個節點、出手幾次、棄權幾次。
  struct Counters {
    long considered = 0;
    long fired = 0;
    long abstained_tau = 0;
    long abstained_same = 0;
    long skipped_user_override = 0;
  };
  [[nodiscard]] const Counters& counters() const { return counters_; }
  void resetCounters() { counters_ = Counters(); }

  // 單點打分（測試與 parity 用）：回傳每個候選的 log-softmax 分。
  std::vector<float> scoreCandidates(
      const std::vector<std::string>& leftChars,
      const std::vector<std::string>& rightChars,
      const std::vector<std::string>& readingSyllables, bool rightEmpty,
      const std::vector<std::string>& candValues,
      const std::vector<std::array<float, 4>>& candFeatures) const;

 private:
  bool loaded_ = false;
  int emb_ = 0, sylEmb_ = 0, hid_ = 0, nChar_ = 0, nSyl_ = 0;
  int ctxChars_ = 0, candChars_ = 0, maxCands_ = 0;
  double tau_ = 0.0;
  CorpusBigramContextModel* contextModel_ = nullptr;
  std::unordered_set<std::string> fireReadings_{"ㄗㄨㄛˋ"};
  Counters counters_;

  std::vector<std::string> itos_, stos_;
  std::unordered_map<std::string, int> ctoi_, stoi_;
  std::vector<float> charEmb_, sylEmbW_;
  std::vector<float> ctx0W_, ctx0B_, ctx1W_, ctx1B_;
  std::vector<float> cand0W_, cand0B_, cand1W_, cand1B_;
  std::vector<float> head0W_, head0B_, head1W_, head1B_;

  std::unordered_map<ReadingGrid::Node*, std::weak_ptr<ReadingGrid::Node>>
      applied_;
  [[nodiscard]] bool isAppliedByUs(const ReadingGrid::NodePtr& node) const;
};

}  // namespace iBopomofo

#endif  // SRC_ENGINE_NODEHOMOPHONEEXPERT_H_
