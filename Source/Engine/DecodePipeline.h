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

#ifndef SRC_ENGINE_DECODEPIPELINE_H_
#define SRC_ENGINE_DECODEPIPELINE_H_

#include <string>

namespace McBopomofo {

// 「這一次選字，實際上會經過哪幾層」的組態。
//
// ## 為什麼要有這個東西
//
// 這些層原本是 `KeyHandler::_walk` 裡五個獨立的 if，各自讀不同的偏好、
// 再各自呼叫 `_grid->setXxx()`。結果是：**沒有任何地方能一眼看出這次用了哪些層。**
//
// 2026-08-11 抓到的 `chosenValueAt` bug 潛伏了一整個版本，就是因為這個 ——
// 規則層讀到的字跟使用者看到的不一樣，但組態散在五處，沒有一份「目前生效的設定」
// 可以印出來對照。
//
// 這個結構體不改變任何行為，它只是把「決定」與「套用」分開：
//
//     Preferences ＋ 輸入模式  →  DecodePipeline（純資料，可印、可測）
//                                       ↓
//                                 套用到 ReadingGrid
//
// 好處：
//   * `describe()` 可以直接寫進 log 或測試斷言
//   * 單元測試可以直接建構組態，不必碰 Preferences 或 IMK
//   * 新增一層時，只會改這裡跟套用函式，不會再多一個散落的 if
struct DecodePipeline {
  // 情境 bigram 動態規劃（EnableContextualWalk）。關掉時走純詞頻快路徑，
  // 結果與加這層之前逐位相同。
  bool contextModel = false;

  // 使用者個人化（UOM 軟分數）。純注音模式一律關閉。
  bool userModel = false;

  // 神經路徑重排（EnableNeuralPathRerank）。只在定案／預覽那幾次 walk 開，
  // 每次按鍵的組字 walk 不付這個成本。
  bool neuralRerank = false;
  double rerankNu = 0.0;
  size_t rerankNBest = 10;

  // 同音頻率壓縮（confusion-alphas.tsv）。
  // ⚠️ 它只在 N-best 融合那一段生效，所以 neuralRerank 關掉時它自動失效 ——
  //    這是**刻意**的相依，不是意外：沒有重排就沒有多條路徑可以比。
  bool confusionAlphas = false;

  // 文法規則（homophone-rules.tsv）。純注音模式一律關閉。
  bool grammarRules = false;

  // 決策軌跡。預設關，只有評估工具與 debug 模式打開。
  bool decisionTrace = false;

  // 純注音模式：所有「智慧」層一律關掉。使用者選這個模式就是不要任何介入。
  static DecodePipeline plainBopomofo() { return DecodePipeline{}; }

  // 一行摘要，給 log 與測試斷言用。
  [[nodiscard]] std::string describe() const {
    std::string s = "pipeline[";
    auto add = [&s](const char* name, bool on) {
      if (on) {
        if (s.back() != '[') s += " ";
        s += name;
      }
    };
    add("context", contextModel);
    add("user", userModel);
    add("rerank", neuralRerank);
    add("alphas", confusionAlphas);
    add("rules", grammarRules);
    add("trace", decisionTrace);
    if (s.back() == '[') s += "unigram-only";
    s += "]";
    if (neuralRerank) {
      s += " nu=" + std::to_string(rerankNu).substr(0, 4) +
           " nbest=" + std::to_string(rerankNBest);
    }
    return s;
  }

  // 這一組設定是否等同「完全沒有任何智慧層」——
  // 對照實驗時用來斷言「關掉之後行為跟加這些層之前一樣」。
  [[nodiscard]] bool isPlain() const {
    return !contextModel && !userModel && !neuralRerank && !confusionAlphas &&
           !grammarRules;
  }
};

}  // namespace McBopomofo

#endif  // SRC_ENGINE_DECODEPIPELINE_H_
