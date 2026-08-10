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

#ifndef SRC_ENGINE_PARTICLERULEDISAMBIGUATOR_H_
#define SRC_ENGINE_PARTICLERULEDISAMBIGUATOR_H_

#include <functional>
#include <istream>
#include <memory>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "gramambular2/reading_grid.h"

namespace McBopomofo {

// 「的／得」文法規則消歧。
//
// 為什麼需要這個：引擎的語言模型只看字詞出現頻率，而「的」比「得」常見約
// 180 倍。所以只要兩個字都合法，「的」永遠贏 —— 實測「該打得的句子」引擎
// 只選對 12%。再多的統計層都追不回這個先天差距，因為它們做的都是同一件事
// （算分數）。缺的是「這樣不合文法」這個概念。
//
// 規則（只做「的→得」一個方向）：
//
//     動詞／形容詞  +  ㄉㄜ˙  +  結果補語   →   得
//
//     看的懂 → 看得懂　　養的起 → 養得起　　打的過 → 打得過
//
// 為什麼只收結果補語，不收程度副詞：
//   「看得懂／養得起」後面接的一定是動作結果，不可能是名詞，判斷幾乎不會錯
//   （真實語料抽 40 個，39 個正確）。
//   「跑得很快」那種後面接程度副詞的，可能是補語（跑得很快 ✓），也可能是
//   「…的東西」（這種的很陽春 ✗、原始林裡的超兇宅 ✗），光看前後幾個字分不
//   出來，實測誤判兩成，所以不放進來。
//
// 安全設計：
//   * 只用 selectOverrideUnigram，只能在節點既有候選裡改選，不會生成新字。
//   * 使用者手選過、或 UOM 覆寫過的節點一律不碰。
//   * 沒命中就完全不動，維持引擎原本的選擇。改錯的代價不對稱 ——
//     把使用者本來對的「的」改成「得」，比維持現狀糟得多。
class ParticleRuleDisambiguator {
 public:
  // 判斷一個字串是不是詞庫裡的詞。用來擋「便當／方法／動作／冷氣」這種
  // 「第一個字剛好是補語、但整段是名詞」的誤判。由呼叫端接進語言模型。
  using DictionaryLookup = std::function<bool(const std::string&)>;

  ParticleRuleDisambiguator() = default;

  // 從 particle-rules.tsv 載入。壞行會被略過，不丟例外 ——
  // 表檔毀損不該讓輸入法起不來。
  bool load(std::istream& input);
  bool load(const std::string& path);

  [[nodiscard]] bool isLoaded() const { return loaded_; }

  // 換句子時呼叫，清掉「這些節點是我改的」的紀錄。
  void reset() { applied_.clear(); }

  void setDictionaryLookup(DictionaryLookup lookup) {
    dictionaryLookup_ = std::move(lookup);
  }

  bool empty() const { return heads_.empty() || tails_.empty(); }

  // 在走完的路徑上套規則。有改動回傳 true。
  bool rescoreWalk(const Formosa::Gramambular2::ReadingGrid::WalkResult& walk);

  // 給測試用：直接對一串字判斷第 index 個位置該不該改。
  bool shouldFlip(const std::vector<std::string>& chars, size_t index) const;

 private:
  bool isAppliedByUs(
      const Formosa::Gramambular2::ReadingGrid::NodePtr& node) const {
    return applied_.find(node.get()) != applied_.end();
  }

  bool loaded_ = false;
  std::string reading_;   // ㄉㄜ˙
  std::string from_;      // 的
  std::string to_;        // 得
  std::unordered_set<std::string> heads_;       // 左邊可以接補語的字
  std::unordered_set<std::string> tails_;       // 右邊的結果補語
  std::unordered_set<std::string> neverWords_;  // 真的／有的／似的…
  std::unordered_set<std::string> neverHeads_;  // 我／你／他／真／有…
  std::unordered_set<std::string> nouns_;       // 下場／出路／過法：開頭是補語字的名詞

  DictionaryLookup dictionaryLookup_;
  std::unordered_map<const Formosa::Gramambular2::ReadingGrid::Node*,
                     std::weak_ptr<Formosa::Gramambular2::ReadingGrid::Node>>
      applied_;
};

}  // namespace McBopomofo

#endif  // SRC_ENGINE_PARTICLERULEDISAMBIGUATOR_H_
