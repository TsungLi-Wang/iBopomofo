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

## 三行同步狀態（2026-08-19 收工 · 棒㉕）

1. **選字機制研究線全部關閉。** ⑭–⑰ 四條線量到上限（可爭取空間都在全語料字位
   0.1% 量級），⑱–㉒-B 進一步判掉「用 correction 學排序」**整個家族**
   —— 沒有 propensity 就是識別條件不成立。**別再開第五條。**
   完整表在 `docs/dead-ends.md` B／E 節。

2. **儀器已上線，資料正在累積。** 棒㉓ 把 ⑲ instrumentation ＋ 新的 decision census
   裝進日常使用的 build；棒㉔–㉕ 確認分母與分子都由真實使用證實、語意逐筆核對正確、
   無測試污染。錯誤率第一次有分母。判定與數據見 `docs/decisions/0010`。

3. **下一個方向已收斂，但 WAIT。** 候選是「吃已定案全文的 recency cache／PPM ＋
   小 λ 插值 ＋ 衝突讀音棄權」（`docs/research/personalization-methods-survey.md`）。
   **資料不到門檻不准開工。**

## 下一刀

# 等資料。這一棒沒有工程要做。

```
門檻   ≥300 筆 TRUE_CORRECTION 或滿 21 天（先到者為準）
進度   見 ./scripts/correction-census.sh
起算   2026-08-19
```

**真實資料起點 `2026-08-19T05:06:35Z`。在此之前的 census 與 v2 correction
全是測試／自動化產物，分析時一律排除**（明細見 `docs/decisions/0010` §3）。

達標後才做：M5 的 **cross-fitted rescue / damage / net** 評估
（規格見 [`docs/decisions/0009`](docs/decisions/0009-下一個產品方向是先讓儀器上線.md) §10–12）。
**判準只能用 net，不能用 AUC／MRR／pairwise**（已連續誤導四次）。

**停止條件**：打字延遲或穩定度退步 → 立刻退回舊 build。
滿 21 天且 `TRUE_CORRECTION` < 100 → 回頭檢討 `docs/decisions/0003` 的賭注本身。

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
