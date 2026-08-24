---
paths:
  - "Source/Engine/**"
  - "Source/*.mm"
  - "Source/*.h"
---

# C++ 引擎（動到 `Source/Engine/` 才載入）

## 測試分兩個 runner，兩個都要跑

- `McBopomofoLMLibTest` — 語言模型／詞庫那一層
- `gramambular2_test` — `reading_grid` 直屬。**configure 沒帶 `-DENABLE_TEST=ON` 就不會生成**，
  很容易「以為全綠」其實根本沒編出來。

`Source/Engine/build-test/` 是被 git 追蹤的產物：跑完測試工作樹會髒，發版前 `git restore`。

## `walk()` 有兩條路徑，改任何一條都要想另一條

- **快路徑**（沒有 ContextModel）：`reading_grid.cpp` 的舊 Viterbi，用 `node->score()`，
  override 時回 `kOverridingScore`，所以天生尊重使用者選字。
- **DP 路徑**（`EnableContextualWalk` 開啟，以 `(位置, 末詞)` 為狀態的精確 bigram Viterbi）：
  遍歷每個候選。v2.2.0 曾在這裡用原始 `u.score()`、完全沒讀 override，
  加上 `chosenValueAt` 用 DP 的 `selectedUnigramIndices` 蓋掉 `node->value()`，
  結果**使用者手動選的字被靜默丟棄、選了上不了屏**。
  修法：node `isOverridden()` 時只認被 override 的候選、計分用 `node->score()`，其餘 `continue`。

**教訓**：benchmark 與 e2e 都沒抓到那個 bug，因為它們只驗「自動選字對不對」，
從不模擬「手動覆蓋 × ContextModel 開啟」。新機制要問一次：**它跟 override 互動嗎？**
迴歸測試 `OverrideIsHonoredWithContextModel` / `OverrideIsHonoredOnFastPath` 就是為這件事留的。

## 鐵則

- 只在**節點既有的 unigram 裡改選**（soft override）：不改切詞、不改讀音、不生成新字。
- 讀音驅動的引擎**不可以從 Swift 的 `setMarkedText` 塞自由文字**進去。
- 換表、換權重的驗收方式固定：**新表 vs 現用表跑同一份 tw benchmark，不退步才收**。
- instrumentation 的分子**不可以用 `Node::isOverridden()`**（棒㉓ 踩過，理由見 AGENTS）。

## 分析／replay 工具

新寫的 replay 或分析工具，**第一個測試永遠是「逐句重現 production 輸出」**，報 N/N；
沒過這關算出來的任何數字都不能用。已經靜默錯過四次，全部是這三類：
**預設參數沒設**（漏 `cm.setLambda(0.75)`）、**排序假設沒驗**、**狀態被就地修改**
（`WalkResult` 持 `shared_ptr`，override 是就地改 node，擷取點差一行整批事件就被誤標）。
還有一次是拿 `walkNBest(200)` 的 argmax 當 top-1，但出貨走的是 `setPathRerankNBest(10)`。
