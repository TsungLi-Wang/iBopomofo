# L1 神經重排整合設計：從 PoC harness 到 AICandidateReranker

> ⚠️ **歷史文件（已作廢）。** 本文描述的本機 llama／雲端 AI 路線在 v2.7.0 已整批移除，
> `llama-runtime/` 也於 2026-08-13 從 repo 刪除。現役的神經重排是進程內 char-LSTM
> （`Source/Data/path-char-lstm.bin`），與本文的架構無關。保留供查閱設計脈絡，**不要照著操作**。

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

(2026-07-07 更新:skeleton 已落地,見交班日誌;第 1 點的 eval 變體因加速決策暫被跳過,右文問題升級為最高優先,見第 8 節。)

## 8. 右文不足的根治方案:延遲全局重審(deferred global re-rank)

R1 升級為最高優先(Johnny 拍板:不接受用 fallback 掩蓋)。本節是根因分析與根治設計。

### 8.1 根本原因:右文為空時「全局」與「local」在數學上是同一個東西

Causal LM 打分 = Σ logP(token | 前綴)。兩個候選句共享 focus 之前的所有 token,分數差 =

```
Δ = [logP(c1|left) - logP(c2|left)] + Σ_right [logP(r_i|left,c1,…) - logP(r_i|left,c2,…)]
```

第二項(右文在不同候選條件下的機率差)才是全局打分的全部優勢——harness 救回的 12 筆,鑑別訊號全在那裡(「說一次」支持「再」、「這裡」支持「在」)。右文為空時第二項不存在,Δ 塌縮成第一項,**與 local left-to-right scoring 完全等價**——不是效果下降,是同一個計算。此時模型只剩詞頻 prior,而詞頻 prior 正是引擎 unigram 已編碼的東西;更糟的是模型 raw prior 可能與語料統計打架(seed-4:Qwen 對「我」之後的「再」raw logprob 略高於「在」),神經打分反而引入退步。

「讓模型想像右文再打分」救不了:對所有可能未來取期望,由全機率公式塌縮回 P(c|left),零新資訊;生成式 lookahead 只是 MAP 近似,注入的是模型自己的偏好而非使用者意圖,且倍增延遲。**缺的資訊只有一個來源——使用者接下來真的會打的字。所以解法不是改打分方式,是改決策時機。**

### 8.2 主方案 A:把決策點從「候選窗瞬間」搬到「右文出現之後」

架構定位:**神經版 ConfusionPairDisambiguator**,即 `docs/engine-node-override.md` 的 Phase 機制換神經打分器。注音是連續輸入,右文不是「沒有」,是「還沒到」——晚 2-4 個按鍵就到了。

流程:

1. **追蹤**:每次 walk 後,對讀音在混淆集合(現有 ambiguous/confusion-pair 接縫)且節點內有 ≥2 合法 unigram 的位置登記為「懸置歧義位置」。
2. **暫決**:當下維持引擎(+查表消歧)結果,打字零停頓。
3. **重審**:某懸置位置的右文累積 ≥2 字(或出現句末標點)→ debounce → 對該節點合法 unigram 逐一代入整句做 global preview(此時就是 harness 的條件——右文存在,即 100%/50 那個世界)→ margin 超過門檻才動作。
4. **套用**:override-without-observe soft override(Phase A 全套護欄現成:`kOverrideValueWithScoreFromTopUnigram` 不改切詞、使用者手動選字讓位、每次 walk 重評可自我撤回、不汙染 UOM)→ 從 walk 重建 Inputting。

這正是「隱形中文警察」的原始願景(邊打邊用上下文修正「現階段」句子),Johnny 已拍板高信心直接改 OK。

### 8.3 輔方案 B:候選窗路徑的證據門檻(懸置,不是 fallback)

`NeuralCandidateRescorer` 增加右文檢查:focus span 之後 ≥2 字(preceding 不算,commit 過的文字不能再改)→ 全局打分照舊(regime A「回頭選字」——最常見的修錯流程,右文天然存在,現有 skeleton 的全部收益保留);右文不足 → 該位置**懸置**——維持引擎排序(不是退 n-gram;n-gram 同樣只有左文,重排同樣是瞎猜),並把位置掛進 A 的追蹤清單。語義是「證據還沒到,決策延後」,不是「放棄治療」。

### 8.4 補充 C(第二階段):commit 前終審

句末標點 / commit 邊界時整句必然完整,對殘留懸置位置做最後一輪 global 檢查。必須非阻塞(打字停頓時 A 多半已完成,C 只是保底);不可讓 commit 等 HTTP。

### 8.5 否決的方向(與理由)

- **生成式 lookahead**(每候選生成未來再打分):期望上塌縮回 P(c|left);MAP 近似注入模型偏好;延遲倍增。
- **Chat prompt 問答**(「哪個字對?」):PoC 已實測,4B 上 20% acc,退回 prompt 工程死路。
- **換雙向模型(MLM)/更大模型**:右文不存在時,任何模型都沒有右文可看——資訊缺失不是模型能力問題。

### 8.6 優缺點與量化影響

| 方案 | 正確率 | 延遲 | 風險 |
|------|--------|------|------|
| A 延遲重審 | 右文到位後 = harness 條件(50/50);使用者停在句尾不再打的殘餘 case = 現狀(引擎+表),不劣化 | 不在按鍵關鍵路徑;debounce 後每位置 2-4 次呼叫(warm 10-50ms);每歧義位置最多重審 1-2 次(里程碑:右文達 2 字、句末) | 翻字閃爍(對策:margin 門檻 + 已翻位置僅在右文再增時重評);Swift↔C++ 橋工程量(Phase A 清單已定義);R6 靜默改字自主權(實驗開關 + 高信心門檻) |
| B 證據門檻 | regime B 不再錯翻(≥引擎 baseline);regime A 收益全保留 | 成本趨零(少打無效請求) | 幾乎無;語義上要與 A 綁定,否則就只是不作為 |
| C commit 終審 | 保證出手前整句審過 | commit 邊界時序需小心,不可阻塞 | 與使用者送出的 race;第二階段再做 |

### 8.7 推進順序

1. **Harness 先驗證 A 的核心假設**(純 Python):把 50 筆造成「增量打字序列」,模擬「focus 當下右文 0 字 → 每多 1-2 字重審一次」,量最終準確率 + 翻字次數(flip count)。這就是原第 7 節欠的右文截斷 eval,重新框成 deferred 模擬。數字要接近整句版才動 app。
2. B:小改 `NeuralCandidateRescorer`(右文字數 gate,懸置語義)。
3. A:Phase A 橋(override-without-observe bridge、per-position 合法 unigram 讀取、Coordinator serial+walk 世代守門、重建 Inputting)+ 神經重審排程(復用 L2 auto-correction 的 Inputting 排程接縫)。
4. C 視 A 實機表現決定。

### 8.8 實測結果與最終落地架構(2026-07-08,v2.1.0)

上面 1→3 已全部做完並隨 v2.1.0 出貨。過程中有兩個推翻前提的發現,以及據此修訂的設計:

**發現一:PoC 的整句打分從來不是整句打分。** llama-server `/completion` 在
`n_predict=0` 時不回 prompt logprobs——它生成一個 token 並回報那個 token 的機率。
PoC 的 `score_full_sentence_logprob` 量的是 P(下一字|句子) 這個弱代理;先前
「50 筆 100%、mean 38ms」是資料集假象(打分全部平手時保持 allowed[0],而該資料集
allowed[0]=expected)。**真整句分數要用鏈式法則逐 token 取**,而精確取法是
**logit_bias 探針**:目標 token bias +100 讓 greedy 必中,回報的 logprob 實測
(build b9692,與無偏 top_logprobs 全精度吻合)是 raw 值——一次呼叫、無 top-k
損失。公平性陷阱:BPE 會把「我再」併成單 token 而「我/載」不併,只從共同前綴
起算會偏袒合併的候選;必須從哨兵起整句打分(見 `AISentenceScorer` 與
`deferred_rerank_sim.py` 註解)。

**發現二(真實數字):右文效應成立,但模型有系統性「在」偏好。**
`deferred_rerank_sim.py`(50 筆、精確打分):右文 0 字時瞬時 argmax 76%、右文
≥3 字 88%——**+12 個百分點來自等右文,deferred 假設成立**。殘餘 miss 全部是
「再→在」單方向(4B 對「在」的先驗過強,右文也拉不回),而這正是混淆表以
92.3% 精確率覆蓋的 pair,且 sim 顯示神經會把表翻對的「再」翻回去。

**因此最終架構加了「分工制」**:混淆表擁有 ㄗㄞˋ(在/再/載,神經字集刻意排除),
神經層負責表沒覆蓋的 pair(的/得/地、平翹舌、語意對;字集
`neuralDeferredCharacters`)。在非「在/再」子集上 θ=1.0:引擎本來對的**零誤翻**,
引擎錯的救回約 26-27/30。

**落地元件**:
- `AISentenceScorer.swift`:鏈式法則 + logit_bias 探針打分器(候選窗與延遲層共用);
  `decide(scores:current:margin:)` margin 決策。
- `NeuralCandidateRescorer`(候選窗路徑=方案 B):右文 ≥2 字才打分,不足=懸置
  (回引擎 top,不退 n-gram);θ=1.0;偏好關閉時走既有 n-gram 不受影響。
- `KeyHandler` 橋(方案 A):`neuralRerankSnapshot`(列舉 span-1 歧義節點+攤平
  字串)與 `applyNeuralOverride`(override-without-observe 軟覆寫,
  `kOverrideValueWithScoreFromTopUnigram`,不 re-walk、不進 UOM,使用者覆寫讓位,
  weak_ptr 登記防位址重用)。
- `InputMethodController+NeuralDeferred.swift`:Inputting 更新 → debounce 0.6s →
  snapshot(攤平字串==buffer 的對齊守門)→ 右文 ≥2 字的位置打分 → margin 過門檻
  → 軟覆寫+重建畫面;serial+buffer 雙守門丟過期結果;「位置:buffer」鍵避免同語境
  重複打分。
- 出貨模型 live-check(θ=1.0,引擎預設「的」情境):慢慢**地**走過來、跑**得**很快、
  吃**得**很開心、字寫**得**很漂亮、他高興**地**說著 翻對;我的手機不見了 正確不動;
  開心地笑了 margin 0.9 差 0.1 保守不翻(已知 miss,不是錯翻)。

**尚未做 / 已知限制**:方案 C(commit 前終審)未做;多字詞孿生節點(span>1)不在
神經 v1 範圍;`llm_rerank_poc.py` 的舊打分函式仍是壞的(僅供歷史參考,新實驗一律
用 `deferred_rerank_sim.py` 的 `ChainRuleScorer`);延遲層字集是人工挑的,擴充前
先用 sim 對新 pair 出數字。
