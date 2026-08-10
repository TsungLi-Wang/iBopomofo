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
//
// ── 2026-08-10：改成通用規則引擎 ──
//
// 原本這裡只寫死「的／得」一組。改成讀規則表之後，同一套機制可以掛任意組
// （吧八巴、前錢…），不必為每一組再寫一次 C++。
//
// 規則表格式與 `Source/Engine/eval/benchmarks/try_rules.py` **完全相同**，
// 所以流程是：先用 try_rules.py 在 5,646 題上幾秒鐘試出一版規則，
// 確定「救回多、改壞少」再把同一個檔案丟進來 —— 不必為了試規則重編引擎。
//
//     GROUP    的得
//     READING  ㄉㄜ˙
//     LIST     HEAD   看
//     RULE     結果補語   的   得   L1=HEAD;R1=TAIL;!L1=NEVERHEAD
//
// 條件只准看目標字前後幾個字（L1/L2/L3/R1/R2/R3/LW2/RW2/L1T/TR1）加上句首句尾旗標。
// 這個限制是刻意的：規則要能在打字當下用常數時間判斷，而且要能一眼看懂為什麼。
class ParticleRuleDisambiguator {
 public:
  // 一條規則的一個條件。
  struct Condition {
    enum class Slot {
      kL1, kL2, kL3, kR1, kR2, kR3,   // 左右第 1、2、3 個字
      kLW2, kRW2,           // 左邊兩字、右邊兩字合成的詞
      kL1T, kTR1,           // 左1+目標、目標+右1
      kAtEnd, kAtStart,     // 位置旗標（不看清單）
    };
    Slot slot = Slot::kL1;
    bool negated = false;
    // 指向 lists_ 裡的集合；位置旗標與 @DICT 時為 nullptr。
    const std::unordered_set<std::string>* list = nullptr;
    bool useDictionary = false;   // 這個條件查的是詞庫（@DICT）
  };

  struct Rule {
    std::string name;
    std::string from;   // 引擎選的那個字；不是它就完全不碰
    std::string to;     // 要改成的字
    std::vector<Condition> conditions;   // 全部成立才出手
  };

  // 判斷一個字串是不是詞庫裡的詞。用來擋「便當／方法／動作／冷氣」這種
  // 「第一個字剛好是補語、但整段是名詞」的誤判。由呼叫端接進語言模型。
  using DictionaryLookup = std::function<bool(const std::string&)>;

  ParticleRuleDisambiguator() = default;

  // 從規則表載入。舊格式（HEAD/TAIL/NEVER/NEVERHEAD/NOUN，只有的／得）與
  // 新格式（GROUP/LIST/RULE，任意組）都吃。壞行會被略過，不丟例外 ——
  // 表檔毀損不該讓輸入法起不來。
  //
  // 可以呼叫多次載入多個檔案，規則會累加（不同組放不同檔比較好維護）。
  bool load(std::istream& input);
  bool load(const std::string& path);

  [[nodiscard]] bool isLoaded() const { return loaded_; }

  [[nodiscard]] size_t ruleCount() const { return rules_.size(); }

  // 換句子時呼叫，清掉「這些節點是我改的」的紀錄。
  void reset() { applied_.clear(); }

  void setDictionaryLookup(DictionaryLookup lookup) {
    dictionaryLookup_ = std::move(lookup);
  }

  bool empty() const { return rules_.empty(); }

  // 在走完的路徑上套規則。有改動回傳 true。
  bool rescoreWalk(const Formosa::Gramambular2::ReadingGrid::WalkResult& walk);

  // 給測試用：直接對一串字判斷第 index 個位置該不該改。
  // 沿用「的→得」的語意（回傳「這裡要不要改成得」），現在改成問通用規則。
  bool shouldFlip(const std::vector<std::string>& chars, size_t index) const;

  // 通用版：這個位置該改成什麼？沒有規則出手就回空字串。
  [[nodiscard]] std::string replacementFor(
      const std::vector<std::string>& chars, size_t index) const;

 private:
  [[nodiscard]] bool conditionHolds(const Condition& cond,
                                    const std::vector<std::string>& chars,
                                    size_t index) const;
  // 取得（必要時建立）具名清單。回傳裸指標給 Condition 用 ——
  // 所以 lists_ 的值必須是 unique_ptr，rehash 才不會讓那些指標失效。
  std::unordered_set<std::string>* listNamed(const std::string& name);
  bool parseCondition(const std::string& text, Condition* out);

  bool isAppliedByUs(
      const Formosa::Gramambular2::ReadingGrid::NodePtr& node) const {
    return applied_.find(node.get()) != applied_.end();
  }

  bool loaded_ = false;
  // 清單用 unique_ptr 存，因為 Condition 直接指向集合。用 map 的話
  // rehash 會讓那些指標失效 —— 載入多個檔案時就會踩到。
  std::unordered_map<std::string,
                     std::unique_ptr<std::unordered_set<std::string>>> lists_;
  std::vector<Rule> rules_;

  DictionaryLookup dictionaryLookup_;
  std::unordered_map<const Formosa::Gramambular2::ReadingGrid::Node*,
                     std::weak_ptr<Formosa::Gramambular2::ReadingGrid::Node>>
      applied_;
};

}  // namespace McBopomofo

#endif  // SRC_ENGINE_PARTICLERULEDISAMBIGUATOR_H_
