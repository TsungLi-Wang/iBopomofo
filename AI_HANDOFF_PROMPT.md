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

## 三行同步狀態（2026-08-18 收工 · 棒⑲）

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

## 下一刀

**不要再開第五條選字機制線。** 證據已經很一致：
可爭取空間都在「全語料字位 0.1% 量級」，而真實使用者修正的分布跟 PTT 語料研究的六組**幾乎不重疊**。

下一步的合理選項（依成本排序，**尚未拍板**）：

1. **讓 ⑲ 的 v2 資料累積起來**（零成本，只要繼續用）。目前 552 筆歷史事件是
   `UNKNOWN_ORIGINAL` 無法回填；新事件開始就有 `engine_choice` 與候選集。
2. **決定要不要補「正確率分母」**。沒有它就永遠算不出 net／damage。
   這是產品／隱私決策，不是研究題。
3. 若要再碰模型，證據指向的不是重排器，而是**語言模型本身**
   —— 但 ⑭-T 顯示 73.3% 的錯誤是打分器真的偏好錯的那句，那是大工程。

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
