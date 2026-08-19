# i注音 交班：現況與下一刀

你是 **i注音（iBopomofo）** 的後續協作開發 AI —— macOS 原生繁體中文注音輸入法，
repo `TsungLi-Wang/iBopomofo`。

> **這份只寫「現在到哪了」與「下一刀」，目標一頁。** 其他東西各有自己的家（見下表），
> 版本號一律不寫在這裡 —— 見 `CHANGELOG.md` 最上面的已發布段落。

## 進場讀什麼（全部在 repo 內）

| 順序 | 讀什麼 | 為什麼 |
|---|---|---|
| 1 | **本檔** | 到哪了、下一刀 |
| 2 | **`docs/dead-ends.md`** | 已證明無效的路。**動手前必讀**，兩頁 |
| 3 | `AGENTS.md` | 建置、關卡、commit 規則、產品 UX、**收工清單** |
| 4 | `CHANGELOG.md` 最上段 | 現役版本與每版改了什麼 |
| 5 | `docs/decisions/` | 為什麼這樣做、試過什麼。**要動該領域時才讀** |
| — | `Source/Data/AGENTS.md`／`algorithm.md` | 改詞庫／深算法時 |

```bash
gh issue list --label deadend --state all   # 已歸檔的死路（新的寫進 docs/dead-ends.md）
gh issue list --label needs-johnny          # Johnny 卡著什麼
gh issue list                               # 目前開著的工作
```

歷史交班日誌在 `AI_HANDOFF_ARCHIVE.md`（**只當歷史，不要照著動手**；真正的歷史是 `git log`）。

---

## 三行同步狀態（2026-08-19 收工 · 棒⑳ decision gate）

1. **⑭–⑮：四條選字機制線全部量到上限，全部關閉。** 分母是 D2 ＝ 自然驗證集
   74,649 字位中的 3,192 個 walk 錯字（4.28%）。通用 Node Expert **DROP**
   （⑭-N 條件 AUC 0.459，低於隨機）；方向專屬 Node Expert **DROP**
   （⑭-K 系統貢獻 0.082% of D2）；固定 top-10 重排 **DROP**
   （⑮-B 掃遍整個線性家族的上界只有 +85 字＝0.114% 字位，⑭-R +69、⑭-S +53 都在其下）；
   放寬 beam 降為次要（⑮-A 上限 +41 字＝0.055%）。
   **共同原因**：`walkScore` 對 gold 的中位 Δ 是 −1.06，打分器把 gold 擋在
   出貨的前 10 條重排視窗外，搜尋找得再多也沒用。完整表在 `docs/dead-ends.md` E 節。

2. **⑯–⑰：Prototype-001 做出來了，然後被自己的 ablation 否掉。**
   `prototype/ccd/` 可訓練可推論（964k 參數、CPU 42 秒、4 MB）。
   在訓練語料 document-held-out 上 net +1,543，**但跨語料變 −266**；
   而且拿掉它的核心設計（candidate × context interaction）**net 反而上升**。
   真正在做事的是引擎原本就算好的 unigram/PMI。**NO-GO，不進工程整合。**

3. **⑱–⑲：改往產品側，已補上 instrumentation。**
   ⑱ 從真實 `manual-correction.log` 建 benchmark：584 筆只有 15 筆可完整 replay，
   **六組研究目標只佔真實修正的 12.4%，87.6% 在六組外**；
   而且日誌只在修正時寫入，**正確率在結構上不可計算**。
   ⑲ 補上 schema v2，讓 composing 路徑第一次記得下「引擎原本選什麼」
   （擷取點必須在 `overrideCandidate` **之前**，見 `Source/Engine/eval/analysis/baton19-product-instrumentation.md`），
   並順手把 log writer 改成真正 fail-open。既有測試 165 項全綠、行為未變、未發版。

5. **㉒-B：個人化方法調查（派 grok 外部研究，統治局抽驗＋裁決）。**
   **既有 UOM 這個 abstraction 判 DROP（不當主路徑）**，`用 correction 學排序` **整個家族判掉**
   —— 沒有 propensity 就是識別條件不成立（`dead-ends` B 節新條目）。
   下一個值得驗的機制換了訊號：**吃已定案全文**做 recency cache／PPM ＋ 小 λ 插值 ＋ 衝突讀音棄權，
   外加統治局補的負向記憶護欄。**但沒有任何一個判 GO** —— 全部卡在同一個地方：沒有分母算不出 damage。
   文件：`docs/research/personalization-methods-survey.md`。

4. **⑳：decision gate，不寫模型、不改行為。** 三個候選方向拍板（見下），
   並查出六個「文件說的 ≠ 機器上的」落差，最重要的是 **D1：⑲ 的儀器根本沒裝上**。
   本棒只動文件。

## 下一刀

**棒㉓ 已經把儀器裝上了（2026-08-19）。分母從今天開始累積，不要再重做這件事。**

```
安裝中的 build  GitRevision = 5ba17a96（棒㉓ 最後一個動到程式碼的 commit；之後只有文件 commit）
分母            ~/Library/Application Support/iBopomofo/decision-census.log
分子            manual-correction.log 的 schema v2
查看            ./scripts/correction-census.sh
```

**⚠️ 三件會咬人的事**

1. **版本號分不出新舊 build。** 安裝的是 2.17.1 / 2325，跟官方發布版**號碼相同**。
   要確認哪個 build 在跑，看已安裝 app bundle 內 Info.plist 的 GitRevision 欄位，或
   `strings … | grep DecisionCensusLog`。**若重裝官方 DMG 會換回沒有儀器的 build，
   而版本號看不出差別。**
2. **schema v2 至今沒有任何一筆真實使用者資料。** ⑲ 文件裡那 4 筆「實機驗證」
   與棒㉓ 測試中產生的 2 筆，**全部是 XCTest 產物**（已補防護，不會再發生）。
   分析時 **2026-08-19T04:21 之前的 v2 事件一律排除**。
3. **census 的分子是「使用者手選次數」，不是「引擎錯誤數」。** 沒察覺的錯不在分子裡。
   **這仍然不是引擎正確率。**
4. **真實資料起點 = `2026-08-19T05:06:35Z`**（棒㉔ 健檢確認）。在此之前的
   census 與 v2 correction 全是測試／自動化產物，分析時一律排除。
5. **管線兩端都已由 production 證實（棒㉕）**，累積期間不需要盯任何東西，
   下次檢查直接看數量。分子／分母交叉驗證通過：census 的 composing 手選數
   ＝ 真實 v2 事件數（兩個獨立寫入點數到同一個數字）。
   進度：**`TRUE_CORRECTION` 1 / 300、第 1 / 21 天**。
6. **分母用 census 的 `n_nodes`，分子用 correction log 的 v2 事件（兩種 source 都算）。**
   census 自帶的 `n_user_picks` **只涵蓋 composing 路徑** —— 定案後的 reselect 修正
   寫進 correction log，但那次定案的 census 行早就寫出去了。它不是完整分子。

**下一棒該做的是等，不是做。** 累積到
**≥ 300 筆 TRUE_CORRECTION 或滿 21 天（先到者為準）** 才開始分析，產出第一版
Product Error Map（規格見 [`docs/decisions/0009`](docs/decisions/0009-下一個產品方向是先讓儀器上線.md) §11）。
在那之前**不要開新的研究線**。

分析時的方向已由棒㉒-B 收斂（[`docs/research/personalization-methods-survey.md`](docs/research/personalization-methods-survey.md)）：
**不要用 correction 學排序**（整個家族已 DROP），候選機制是
「吃已定案全文的 recency cache／PPM ＋ 小 λ 插值 ＋ 衝突讀音棄權 ＋ 負向記憶護欄」。

**停止條件**：打字延遲或穩定度退步 → 立刻退回舊 build。
滿 21 天且 `TRUE_CORRECTION` < 100 → 回頭檢討 `docs/decisions/0003` 的賭注本身。

---

## 上一刀（棒⑳ 拍板，已由棒㉓ 執行完畢）

**不要再開第五條選字機制線。** 證據已經很一致：可爭取空間都在「全語料字位 0.1% 量級」，
而真實使用者修正的分布跟 PTT 語料研究的六組**幾乎不重疊**。

**棒⑳ 已經把三個候選方向拍板了 —— 判定寫在
[`docs/decisions/0009`](docs/decisions/0009-下一個產品方向是先讓儀器上線.md)，動手前讀那份。**

```
A 讓 v2 資料累積 ＋ B 補正確率分母  →  GO（合併成同一個 build）
C 動語言模型本身                    →  WAIT
SEI（本棒指令提出，repo 內零記錄）  →  WAIT
```

**拍板的關鍵是一個文件與機器的落差**：⑲ 的 instrumentation 寫好、測綠了，
**但從來沒進到實際在用的輸入法**（安裝中的是 2.17.1 / build 2325，`strings` 搜 `appendV2` 命中 0，
log 內 v2 只有 4 筆測試事件）。所以「零成本，只要繼續用」實際上是 **0 筆／天**——
而使用者每天真的在產約 **40 筆**修正，全被記成沒有 `engine_choice` 的舊格式。
**資料不是沒有，是格式錯；每過一天就再損失約 40 筆。**

**下一棒要做的事（規格在 0009 第 10 節，已寫到可直接開工）**：

1. 實作分母計數器（在 `Source/` 下新增 DecisionCensusLog.swift，**尚未存在**；純計數、零文字），
   掛在 `KeyHandler.mm` 三處現成的 `snapshotCharacterShadowUnits` 之後。
   **刻意不在 commit 路徑上呼叫 `candidatesAt()`**（會加 O(n) lattice 查詢）。
2. 補 `scripts/correction-census.sh` 認得 schema v2（現在把 v2 行歸到「舊格式」）。
3. 全測試 ＋ `e2e-typing-check.sh` ＋ `ship-gate.sh` ＋ 量 commit 延遲。
4. **請 Johnny 拍板**是否把這個 build 裝成日常輸入法（研究分支上線 = 他的決定）。
5. 裝上後**等資料**。滿 300 筆 `TRUE_CORRECTION` 或 21 天才開始分析，
   **在那之前不要開新的研究線**。

**停止條件**：打字延遲或穩定度退步 → 立刻退版。
滿 21 天且 `TRUE_CORRECTION` < 100 → 回頭檢討 `docs/decisions/0003` 的賭注本身，
**不要再換一種記錄方式**。

**全系列產物**：`Source/Engine/eval/analysis/`（`baton15-product-improvement.md` 起共 12 份）、
`node-expert-*.md`、`full-*.md`、`path-*.md`、`gold-path-forced-score.md`。
分支 `baton13-node-homophone`，**未 merge、未 enable、未發版**。

---

## 工作方式（Johnny 明確指正過的兩件事）

**該派給 grok／codex 的活不要自己扛。** 判準見 `~/.claude/CLAUDE.md` 的五級通行驗證；
粗略地說：**會產出可逐項驗收的清單、而且不是改 code 本身 → 派出去。**
派之前跑 dispatch-guard（機密硬掃），派工票與回報寫在 `.ai-handoff/`（本 repo 已 gitignore）。

**收外部回報要逐項核對再採信。** 上一票 grok 把「刻意保留的真名」
（`McBopomofoLM.cpp`、`McBopomofoTests/`、CMake `McBopomofoLMLib`）報成漏改。

**動手順序**（2026-08-10/11 連續兩次發版又退版的根因不是判斷力，是順序）：

```
① 先寫下：我要用什麼證據判斷這東西有效？   ← 不要跳過
② 確認那份證據的來源 ≠ 機制的來源
③ 才開始做
④ ./scripts/ship-gate.sh 過了才發版
```

**誠信**：數字必須真跑；三狀態分報（app build / harness / deliverables）；
文件與改動同棒更新。
