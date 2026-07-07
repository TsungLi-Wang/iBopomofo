# L1 神經重排整合設計：從 PoC harness 到 AICandidateReranker

最後更新：2026-07-07T14:30:00+08:00

本文件把 `Source/Engine/eval/llm_rerank_poc.py` 已驗證的「focus position global full-sentence preview」邏輯,對應到真實 L1(`AICandidateReranker` / `AIAssistCoordinator`)的整合方案。**尚未動程式碼**,先定架構與風險,待拍板後實作。

PoC 現況:50 筆真實案例 100% 正確、mean latency ~38-43ms、0 regressions;global re-rank 在 local-only 模擬中救回 12/50(在/再、的/得/地 這類需要整句語意的 case)。

## 1. 關鍵簡化:真實 L1 不需要 beam search,也不需要 logit_bias

Harness 之所以要 position-level constrained beam search + logit_bias + char→token map,是因為它在**無引擎**的環境下必須自己把非 focus 位置一格一格填出來。真實 app 裡這件事引擎已經做完了:

- 候選視窗開啟時,`composingBuffer` 就是引擎 walk 的 top-1 整句 = harness 裡的 `baseline_rest`。
- focus position = 候選視窗正在選的那個 reading span(由 `cursorIndex` 決定),`allowed` = 該 span 的候選清單(`context.candidates`),引擎保證全部合法。
- 既有的 `AICandidateNGramScorer.contextText(replacingWith:in:)` 已經會做「把候選代入 buffer 中的 focus span、前面接 preceding」——正是 harness 裡 `preview_full` 的組句邏輯,連 cursorIndex 定位都處理好了。

因此整合後的核心只剩:

```
for candidate in candidates(≤8, 過符號閘門):
    text = contextText(replacingWith: candidate.value)   # preceding + buffer 代入後整句
    score[candidate] = full_sentence_logprob(text)        # 一次 /completion 呼叫
選 score 最高者 → 走既有 applyAICandidateRerankResult 路徑
```

這同時把 PoC 的三大不穩定來源(char→token 映射、logit_bias 對 top_logprobs 無效、beam 剪枝掉正解)整個排除——只保留 harness 中被證明有效的那一半(`score_full_sentence_logprob`),丟掉只為 harness 存在的另一半(`expand_one_position` 一系)。

多字詞候選(如 公司/工司)也自然涵蓋:focus span 代入的是整個詞,不必逐字。這比 PoC 的逐字 focus 更一般化。

## 2. 觸發時機:與 collision 偵測、confusion table 的分層協作

不新增觸發層,neural 是 **L1 既有閘門後面換一顆打分器**:

| 層 | 觸發 | 成本 | 角色 |
|----|------|------|------|
| ConfusionPairDisambiguator(C++) | 每次 walk,查表 | ~0 | 打字當下隱形改選,不開候選窗也生效;只覆蓋表內 pair(現為 在/再) |
| L1 rerank(本設計) | 候選窗開啟 + `needsSemanticRerank` + 150ms debounce | N 次 localhost 呼叫 | 候選窗排序;neural 覆蓋所有同音/近音 collision,不限表內 pair |
| L2 | ⌘Return / 句末 | 整句生成 | 事後整句校正 |

Neural 啟用條件(全部成立才走 neural,否則走現有 n-gram):

1. `Preferences.enableGlobalNeuralRerank`(新偏好,實驗,預設關)。
2. `AICandidateReranker.shouldSchedule(for:)` 已通過(= 現有 collision 偵測,不改)。
3. 過符號閘門後仍有 ≥2 個相異候選值(等同 harness 的 |allowed| > 1;只剩 1 個時連 n-gram 都不必)。
4. `LlamaServerManager.shared.isReady`(server 未就緒 → 直接用 n-gram,不等暖機;暖機通知沿用既有策略)。

ConfusionPairDisambiguator 與 neural 的關係:消歧器先在 walk 內改選,neural 打分時 buffer 已含其輸出,方向一致不衝突。但兩者同開時 eval 歸因要分開跑(見 R5)。

## 3. 最小整合 skeleton(修改點清單)

設計原則:**Coordinator 與 controller 一行都不用改**。`CandidateRescorer` 協議與注入點(`AIAssistCoordinator.init` 的 `rescorer:`)是現成的,serial / debounce / buffer 過期丟棄 / 套用路徑全部沿用。

1. `Source/Preferences.swift`:新增 `enableGlobalNeuralRerank`(Bool,預設 false)+ toggle;選單項「AI 神經候選重排(實驗)」+ 三語 strings。
2. 新檔 `Source/AINeuralCandidateRescorer.swift`(pbxproj 新 ID 從 **FACE0108+**;FACE0105~0107 已被 WhisperServerManager 與 Copy Whisper Runtime 用掉):

```swift
struct NeuralCandidateRescorer: CandidateRescorer {
    let fallback = NgramCandidateRescorer()

    func shouldRescore(_ context: AICandidateRerankContext) -> Bool {
        fallback.shouldRescore(context)   // 觸發閘門完全沿用
    }

    func rescore(context: AICandidateRerankContext) async -> Result<String, AICorrectionError> {
        guard Preferences.enableGlobalNeuralRerank,
              LlamaServerManager.shared.isReady,
              distinctNonSymbolCandidateCount(context) >= 2
        else { return await fallback.rescore(context: context) }

        // 逐候選組整句 → /completion 打分(帶總預算 timeout)
        // 任一失敗 / 逾時 / 分數全無效 → fallback n-gram
    }
}
```

3. `Source/LlamaServerManager.swift`(或新小 client):新增 `scoreLogprob(text:) async -> Double?`——POST `/completion`,`n_predict: 0`、`logprobs: true`、`cache_prompt: true`,回 `completion_probabilities` 的 logprob 總和;欄位缺失回 nil(不是 -1e9,讓呼叫端能區分「失敗」與「低分」)。復用既有 `baseURL` / `isReady`。
4. 注入:`NgramCandidateRescorer()` 換成 `NeuralCandidateRescorer()`(一行)。偏好關閉時行為與現在完全相同,因為內部第一步就 fallback。
5. 測試(純邏輯,不起 server):觸發閘門(偏好關/server 未就緒/候選不足 → 走 fallback)、打分選擇(mock scorer 注入分數 → 選最高)、全部 nil → fallback、符號閘門交互。

## 4. 延遲控制

- **Debounce 150ms 沿用**:neural 不改變「使用者停下來才打分」的節奏。
- **總預算 timeout(建議 300ms)**:N ≤ 8 個候選、每個一次 localhost /completion。共享前綴(preceding + focus 之前的 buffer)讓 `cache_prompt` 命中 KV,warm 時每次 ~5-20ms,總計 <150ms;逾時立即回 n-gram 結果,不留使用者等。
- **循序呼叫 + 可取消**:llama-server 單 slot 序列處理,平行打只會排隊;循序打並在 serial bump / buffer 變更時 cancel URLSession task,避免廢請求堆在 server 上卡到 L2。
- **過期丟棄沿用**:Coordinator serial + `applyAICandidateRerankResult` 的 buffer 比對已擋 commit 級錯誤。

實測 38ms 是 harness warm-cache 數字,實機預期更差(見 R3),所以 timeout + fallback 是硬需求不是保險。

## 5. Server 生命週期(需要拍板的一項)

現狀:llama-server 只在 AI 修正後端 = 本機(index 3)時運行;切到 Opus 會 `stop()` 釋放 ~2GB RAM(`InputMethodController.setAIBackend`)。Neural L1 依賴同一顆 server:

- **選項 A(建議)**:`enableGlobalNeuralRerank` 開啟時也 `startIfNeeded()`;server 改成「任一需要者存活就持有」(後端=本機 或 neural rerank 開啟),兩者都不需要才 stop。代價:Opus 使用者開 neural rerank 後 RAM 常駐 ~2GB。偏好預設關,不影響現有使用者。
- **選項 B**:neural 只在後端=本機時生效。零新常駐,但把兩個無關功能耦合,Opus 使用者永遠用不到 neural L1。

## 6. 風險與已知限制

- **R1 右文不足(seed-4 的一般化,最大的準確率風險)**:harness 案例都是完整句,focus 後面有足夠右文;實機候選窗常在**句中甚至句首**開啟,focus 之後的 baseline rest 很短或為空——此時 global preview 退化成 local left-context scoring,正是 seed-4(「我」+ 在/再,看不到後面的「這裡」)的敗因。**整合前必須先在 harness 加右文截斷變體量化**(對每筆 case 產生 focus 後 0/1/2 字右文的版本),若右文 <2 字時準確率明顯掉,就加「右文長度門檻,不足時走 n-gram」的閘門。
- **R2 logprobs 回報不穩**:PoC 已觀察到 `completion_probabilities` 有時為空、`top_logprobs` 回 raw 分布、欄位名隨 llama-server 版本漂(`n_probs` vs `top_logprobs`)。Swift 端 scoring 失敗必須回 nil 並 fallback n-gram + NSLog,絕不能讓 -1e9 靜默假裝是分數(全 -1e9 時 argmax 會退化成「選第一個」,看起來像沒壞)。升級內嵌 llama-server 版本時此接口要重驗。
- **R3 延遲變異**:38ms 是 warm KV + 無併發的 harness 數字。實機冷 KV、與 L2 / whisper-server 搶資源、4B 模型在低階機器上,p99 可能數百 ms。timeout + fallback 兜底,但代價是這些情況下 neural 命中率下降(退回 n-gram 水準,不是壞掉)。
- **R4 資料集偏差**:50 筆案例 `allowed[0] = expected`(baseline 100%),100% 只證明「不退步」;「救回 12 筆」來自 local-only 模擬而非實測 A/B。且 allowed 順序是資料建構產物,不是引擎真實候選順序。接進 app 前應在 harness 加「打亂 / 依引擎實際順序排 allowed」的模式重量 regression 風險。
- **R5 與消歧表交互**:兩者同開時,消歧器已翻過的字會出現在 neural 打分的 buffer 裡。方向一致(都朝語意正確),但 eval 要分開跑歸因;若 neural 與表意見相左(表翻「再」、neural 選「在」),候選窗重排只影響順序不改 buffer,實害有限,體感需觀察。
- **R6 UX:延遲越高越容易撞使用者操作**:候選窗開啟後重排是既有行為(n-gram 也會),但 neural 較慢,使用者已按數字鍵/方向鍵的機率更高。serial / buffer 檢查擋掉錯誤 commit,但「highlight 被重排重置」的既有小毛病會更常見。
- **R7 RAM**:選項 A 下 server 常駐 ~2GB(見第 5 節)。

## 7. 建議推進順序

1. **Harness 先補兩個 eval 變體**(純 Python,不動 app):右文截斷(R1)、allowed 亂序(R4)。數字不掉再往下。
2. Swift skeleton(第 3 節,約 1 新檔 + 3 小改動)+ 純邏輯測試。
3. 實機低風險驗證:偏好預設關,開啟後觀察延遲與命中,Johnny 純鍵盤驗收。
4. 數字與體感都過,才考慮預設開啟或收掉 n-gram 路徑(n-gram 在可見未來都保留當 fallback)。
