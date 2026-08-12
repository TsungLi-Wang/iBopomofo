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

#ifndef SRC_ENGINE_DECISIONTRACE_H_
#define SRC_ENGINE_DECISIONTRACE_H_

#include <cstddef>
#include <string>
#include <vector>

namespace iBopomofo {

// 記錄「這次選字，每一層各做了什麼決定」。
//
// ## 為什麼引擎要自己吐這個
//
// 2026-08-11 做錯誤分層時發現：剩下的錯誤有六七種來源，而其中最大宗的
// 「整句解碼錯」（43%）根本不是選字問題。但**程式裡沒有任何地方對應這個分層**，
// 診斷只能靠外部工具把引擎重跑一遍再事後推論。
//
// 事後推論有兩個問題：
//   1. 推論會錯 —— 第一版把「整句解碼錯」誤判成「神經模型偏」，
//      直到看了斷詞才發現整句都解碎了
//   2. 推論很慢 —— 剪一輪規則要重跑整個題庫
//
// 所以把分層變成引擎裡的型別：**誰做的決定，就由誰記下來**。
//
// ## 開銷
//
// 預設關閉（`enabled == false` 時所有 record 都是一個 branch 就返回）。
// 只有評估工具與 debug 模式會打開。
class DecisionTrace {
 public:
  // 一個位置的最終用字，是被哪一層決定的。
  //
  // ⚠️ 順序有意義：由內而外，後面的層可以覆蓋前面的。
  // 報表時取「最後一個動過這個位置的層」。
  enum class Layer {
    kUnigram,        // 純詞頻（沒有情境模型時的快路徑）
    kContextModel,   // 情境 bigram 的動態規劃選了非最高頻候選
    kPathRerank,     // 神經路徑重排換掉了整條路徑
    kConfusionAlpha, // 同音頻率壓縮改變了融合後的勝出路徑
    kGrammarRule,    // 文法規則在節點內改選
    kUserOverride,   // 使用者手選或 UOM 覆寫（最高優先，誰都不准蓋）
  };

  struct Entry {
    size_t charIndex = 0;   // 字級位置
    std::string value;      // 這一層決定之後該位置是什麼字
    Layer layer = Layer::kUnigram;
    std::string detail;     // 例如規則名稱、被換掉的排名
  };

  void setEnabled(bool on) { enabled_ = on; }
  [[nodiscard]] bool enabled() const { return enabled_; }

  void clear() { entries_.clear(); }

  void record(size_t charIndex, std::string value, Layer layer,
              std::string detail = "") {
    if (!enabled_) {
      return;
    }
    entries_.push_back({charIndex, std::move(value), layer, std::move(detail)});
  }

  // 整條路徑層級的事件（例如「重排把第 3 條換上來」），charIndex 用 kWholePath。
  static constexpr size_t kWholePath = static_cast<size_t>(-1);

  [[nodiscard]] const std::vector<Entry>& entries() const { return entries_; }

  [[nodiscard]] static const char* layerName(Layer l) {
    switch (l) {
      case Layer::kUnigram: return "詞頻";
      case Layer::kContextModel: return "情境模型";
      case Layer::kPathRerank: return "神經重排";
      case Layer::kConfusionAlpha: return "頻率壓縮";
      case Layer::kGrammarRule: return "文法規則";
      case Layer::kUserOverride: return "使用者";
    }
    return "?";
  }

  // 一行一個事件，給 log 與評估工具用。
  [[nodiscard]] std::string describe() const {
    std::string out;
    for (const Entry& e : entries_) {
      out += layerName(e.layer);
      out += "\t";
      out += (e.charIndex == kWholePath ? std::string("*")
                                        : std::to_string(e.charIndex));
      out += "\t";
      out += e.value;
      if (!e.detail.empty()) {
        out += "\t";
        out += e.detail;
      }
      out += "\n";
    }
    return out;
  }

 private:
  bool enabled_ = false;
  std::vector<Entry> entries_;
};

}  // namespace iBopomofo

#endif  // SRC_ENGINE_DECISIONTRACE_H_
