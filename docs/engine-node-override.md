# 引擎節點覆寫：風險評估與分階段設計（不動碼）

- 最後更新：2026-07-01T17:30:00+08:00
- 狀態：**設計/風險評估**。本文刻意不改任何程式碼，先把地基與決策點定清楚。
- 相關約束：見 `AGENTS.md`（不繞 `KeyHandler` / `InputState`、Swift 不直碰 C++、L1 只重排不生成）與 `AI_HANDOFF_PROMPT.md` 交班日誌「AI 隱形中文警察」。

## 1. 為什麼需要這條路

目前三條 AI 路徑都無法做到「邊打邊隱形修正而不干擾使用者」：

- **L1 候選重排**：只改候選視窗排序，使用者要開候選視窗才受益；沒開視窗時看不到。
- **L2 句末自動校正**：非破壞性，只跳低調提示（`pendingAISuggestion` / `aiTooltipMessage`），要按 Tab 才套用。
- **L2 `⌘Return` 整句修正**：直接改字，但只能在 **commit 邊界**套用（會改讀音、丟回引擎當自由文字）。

早期曾嘗試用 `setMarkedText` 從 Swift 端直接把修正後文字塞進組字區——已移除。原因記在 `CHANGELOG.md` [v1.8.0] 與 `InputMethodController+AIAutoCorrection.swift` 註解：**注音引擎是讀音驅動的**，Swift 端塞進去的自由文字不會更新引擎狀態，會被下一個按鍵或送出時以原文蓋回（假修正），也違反「只在引擎狀態裡操作」原則。

真正「邊打邊隱形修正」的唯一正確做法，是**在引擎的讀音格子（reading grid）上覆寫節點**，讓引擎自己在既有合法候選裡改選，然後照正常路徑重建組字區。

## 2. 引擎已經有這個原語（重點）

覆寫節點不是要新造機制——**候選選字本來就是走這條**：

- `Source/Engine/gramambular2/reading_grid.h`
  - `bool overrideCandidate(size_t loc, const Candidate& candidate, OverrideType = kOverrideValueWithHighScore);`
  - 「Adds weight to the node ... An overridden node would influence the grid walk to favor walking through it.」
- `Source/KeyHandler.mm`
  - `- (void)fixNodeWithReading:value:originalCursorIndex:useMoveCursorAfterSelectionSetting:` → 呼叫 `_grid->overrideCandidate(...)` → `_walk` 重走 → 更新 UOM → 還原游標。
  - 使用者從候選視窗選字，最終就是走到這裡（`KeyHandler.mm:887`）。

### 2.1 這給了我們兩個天然安全性質

1. **只重排不生成（引擎級保證）**：`overrideCandidate(loc, value)` 只能選中「該讀音位置已存在的 unigram」。header 明說字串版若多個 span 有同值不保證選哪個。也就是說——**它無法改讀音、無法生成新字**，只能在既有合法候選裡改選。這正好把「隱形警察絕不改你原意」從自律變成引擎級硬保證。
2. **可鎖定同音錯字**：因為只能改同讀音候選，天生只適用「讀音對、選字錯」的同音／近音錯字：
   - `在 / 再`（都讀 ㄗㄞˋ）
   - `的 / 得 / 地`（都讀 ˙ㄉㄜ）
   - `知 / 資`（都讀 ㄓ）等
   - 這些正是 L1 n-gram 最難翻、也是使用者最痛的一類。
   - 反面：**打錯讀音的錯字（例如注音打錯）救不了**，那不在本路徑範圍。

> 註：n-gram 實驗「在→再翻不動」是**打分器排序**問題，不是覆寫機制問題。覆寫機制能翻；難的是「決定該翻成哪個」。本路徑把「能不能翻」解決掉，留「該翻成哪個」給打分／模型。

## 3. 風險清單（依嚴重度）

### R1（最尖銳）UOM 汙染 —— 隱形修正不該像手動選字一樣訓練引擎

`fixNodeWithReading:...` 在覆寫後會呼叫 `_userOverrideModel->observe(prevWalk, latestWalk, ...)`。這是**手動選字才該有的學習訊號**：它會讓引擎日後在同語境持續偏好這個選擇。

若隱形修正直接複用這條，等於**AI 每次偷改都在偷偷訓練使用者的覆寫模型**，行為會靜默漂移，且使用者不知情、難回溯。

- **對策**：新增一條 **不呼叫 `observe` 的覆寫路徑**（override-without-observe）。隱形修正走這條；只有使用者「明確確認」某次修正時才餵 UOM。
- **決策點**：預設「隱形修正不進 UOM」。是否提供「我接受這次修正 → 才學習」留待 Phase C。

### R2 跨層邊界 —— 必須經 KeyHandler，不可 Swift 直碰 C++

Swift 端不得直接呼叫 `_grid`。需在 `KeyHandler.mm` 新增一個 bridge 方法（例如 `overrideNodeAt:withReading:value:observe:`），並在 `McBopomofo-Bridging-Header.h` 宣告。**這是本路徑唯一要動的 L0 相鄰程式碼**，改動面要小、要可回退、要有 C++ gtest 覆蓋。

### R3 span 歧義與 loc 定位

字串版 `overrideCandidate(loc, value)` 在「多個不同 spanning length 的節點有同值」時不保證選哪個。**必須用 `Candidate{reading, value}` 版本**並算對 `loc`（對齊 `actualCandidateCursorIndex` 的既有邏輯），避免改錯節點或改到相鄰詞。

### R4 非同步時序 —— buffer 可能已變

AI 決策是非同步的。結果回來時組字區可能已被後續按鍵改變。**必須沿用既有 serial + composingBuffer 比對**（見 `AIAssistCoordinator`），過期就丟棄，絕不對已變更的 buffer 施加覆寫。覆寫＋重走只能在主執行緒、且目前仍是同一 `InputState.Inputting` 時進行。

### R5 組字區重建 —— 要走正路

覆寫＋`_walk` 後，Swift 的 `InputState.Inputting` 必須**從新的 walk 結果重建**（沿用 KeyHandler 既有的 buildInputtingState 路徑），不可用 `setMarkedText` 塞字。游標要還原到使用者實際位置。

### R6 使用者自主權 —— 偷改要能輕鬆反悔

覆寫節點在後續 walk 會「黏著」。若 AI 把 `在`→`再` 改錯：

- 使用者要能輕鬆改回（重新開候選視窗選字 = 再覆寫回去，天然可行）。
- 高風險：**靜默改字若沒有任何提示，使用者可能沒注意到被改**。建議至少對被改節點做「短暫、極低調」的視覺標記（沿用 `pendingAISuggestion` 欄位的顯示層）。
- 只在**高信心**時才覆寫；信心不足退回 L2 的「提示不改」。

### R7 與 L1/L2 打架

節點覆寫是**第三個**在 reading-grid 層動手的機制。要明確分工，避免同一位置被 L1（候選排序）、L2（commit 邊界）、節點覆寫三方重複處理或互相回捲。建議：節點覆寫啟用時，L2 句末自動校正對「同音單字」類讓位給它，L2 專責「改讀音的整句」。

### R8 退格／編輯語意

被覆寫節點在 backspace、移動游標、插入時的行為需實測（正常應與手動選字後一致，因為走同一 `overrideCandidate`，但要驗）。

### R9 測試可觀測性

引擎級行為難從 Swift 單元測試。需要：
- **C++ gtest**（`McBopomofoLMLibTest`）覆蓋 override-without-observe 的節點行為；
- **eval harness**（`Source/Engine/eval/`）量 before/after 命中率；
- Swift 端只能測純決策（要不要覆寫、選哪個候選），不測引擎內部。

## 4. 分階段設計（每階段都可獨立驗收、可回退）

- **Phase 0（本文）**：風險評估。不動碼。✓
- **Phase A：最小可行覆寫**
  - `KeyHandler.mm` 新增 override-without-observe bridge（R1、R2）。
  - 用 `Candidate{reading, value}` 版本、算對 loc（R3）。
  - Coordinator 端：serial + buffer 守門（R4），覆寫後從 walk 重建 Inputting（R5）。
  - 藏在**新的實驗偏好**（例如 `enableAIEngineNodeOverride`，預設關）。
  - 只處理**單節點、同讀音**替換。
  - 驗收：C++ gtest 綠 + 既有 129 tests 不破壞 + eval harness 有 before/after 數字。
- **Phase B：白名單收斂爆炸半徑**
  - 只對**策展過的同音字組**（在/再、的/得/地、知/資…）啟用。
  - 用 seed cases + zaizai synthetic eval + Johnny 真實錯選句三組固定 A/B 量測。
  - 沒有明確提升不進下一階段（Johnny 硬性要求）。
- **Phase C：信心閾值 + 低調標記 + 易反悔**（R6）
  - 信心不足退回 L2 提示。
  - 被改節點短暫視覺標記；提供「這次修正才學習」的明確確認才餵 UOM。
- **Phase D：擴大**
  - 視 real eval 表現逐步放寬白名單。

## 5. 硬性「不做」清單

- 不從 Swift 直呼 `_grid` / C++（R2）。
- 不複用會 `observe` 的 `fixNodeWithReading` 當隱形修正路徑（R1）。
- 不用 `setMarkedText` 塞自由文字（讀音驅動引擎的假修正，已驗證會被蓋回）。
- 不改讀音、不生成新字——只在既有 unigram 候選裡改選（引擎級已保證，但決策層也不得繞過）。
- 不動 McBopomofo 內部識別符（bundle id / input source id / module / 資料路徑）。
- 沒有 before/after 數字不算完成。

## 6. 一句話結論

引擎已有 `overrideCandidate` 原語且候選選字本來就走它，**機制風險低**；真正要小心的是 **UOM 汙染（R1）** 與 **靜默改字的使用者自主權（R6）**。建議走 Phase A→B 的最小、白名單、可回退路線，先在 C++ gtest + eval harness 拿到數字，再談要不要對使用者開這個實驗開關。
