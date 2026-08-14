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

## 三行同步狀態（2026-08-14 收工 · 棒⑫）

1. **棒⑫ NO-GO，引擎與出貨檔零變更、未發版。** 訓了一顆「看注音、選同音」的
   節點層模型（P(字|注音,左右文)，15.4M 參數／61.6MB）。規格與完整數字在
   **`docs/decisions/0008`**；三條新死路已進 `docs/dead-ends.md`。
   `Source/Data/path-char-lstm.bin` sha256 未變；節點層打分器**預設完全不掛**
   （不設 `IBOPOMOFO_NODE_SCORER` ＝ 行為逐位相同）。
2. **這一棒留下三樣以後都用得到的東西**：`scripts/node-scorer-ab.sh`（掛 vs 不掛
   的逐題配對）、`scripts/node-scorer-parity.sh`（**換模型的第一道關卡：C++ 與
   PyTorch 逐題同分**，匯出錯一個位元組不會報錯，只會讓後面所有數字是假的）、
   `node_scorer_collateral.py`（**整句逐字正確率**）。
3. **最重要的一課**：現有三支尺全都只看「目標那一個字」。那顆模型在自然驗證集
   目標字只有 −28（看起來像雜訊），同一批卻改了 3,409 句的目標字**以外**、
   共 5,522 個字，整句逐字正確率 95.8%→89.6%。
   **以後任何節點層機制都要同時報整句逐字正確率。**

## 前一棒（2026-08-13 收工）

1. **棒⑧** 已發版（版號見 CHANGELOG 最上段），內容全為測試隔離與 CI 修復，
   **使用者可見行為零變更**；選字邏輯一行未動。
2. **Build workflow（GitHub Actions）已恢復綠燈** —— 兩個根因都修了：
   `whisper-server` 不進 git 但 Build workflow 缺 fetch 步驟；`Create commit comment`
   需要 `contents: write` 權杖。
3. **棒⑪ 已收**（引擎零變更、未發版）：`docs/decisions/0007` 定了神經消歧專家的
   接線位置（節點候選，不是 N-best；**只定位置不開做**）；`scripts/model-ab.sh`
   補上「換權重」的判準（`--self` 在 sample 與兩份真實語料都 0／0）；
   `scripts/correction-census.sh` 普查校正 log；
   `Source/Engine/eval/analysis/real-corpus-error-layers.md` 是第一張**真實語料**
   的錯誤分層地圖。
   前情：棒⑩ #10 已修、#9 作做坐座淨傷害已還原、#11 假綠燈收斂；
   Johnny 已裁句單保留「你先坐這裡等一下」、吧八巴先不做、
   `doc-check` 字面版零豁免否決（`docs/decisions/0006`），這幾條別再重開。

## 下一刀

**沒有阻塞項。** 棒⑫ 之後，節點層神經專家這條路**還沒被推翻，是接法被推翻**：
不要把模型加大、也不要換門檻，要換的是它跟引擎的接法 ——
跟節點分數融合（像路徑層的 ν），或只在引擎候選接近平手時才出手。
細節見 `docs/decisions/0008` 最後一節。 動過詞庫／ranking／規則表／模型的棒，收工前仍必須本機跑
`./scripts/ship-gate.sh` 到 `SHIP_GATE_STATUS=CORE`；換權重另做模型對模型逐題配對
（`ship-gate` 比的是規則開／關，抓不到換模型，見 dead-ends）。

**棒⑪ 量出來、下一棒該知道的三件事**（都寫在
`Source/Engine/eval/analysis/real-corpus-error-layers.md`）：

1. 真實語料上最大宗的錯仍是**整句解碼錯**（自然 47.8%、X 36.9%）——
   節點層與路徑層機制**都修不到**那一半，別在那裡投資。
2. **「的／得」在真實語料上不是瓶頸**（現況 96.4%／98.6%，錯誤只有 14／9 題）。
   考卷把它放大了。不要再當主線。
3. 真實語料上最弱的是**作做坐座**（84.9%／82.2%），而它 O1 93.5% vs O2 98.6%
   —— 要出手該接**節點層**。棒⑩ 已實測**路徑層**對比訓練對這組是淨傷害。

**校正迴路**：真正換了字的校正事件只有 **11 筆**（`./scripts/correction-census.sh`）。
`docs/decisions/0003` 那條路**現在談群眾層太早**。
`wrong_char` 空白**不是 bug**：組字中手選一律寫空（`KeyHandler.mm:379`），
只有定案後 ↓ 重選才填（`InputMethodController+ShadowReselect.swift:222`）。
所以那 11 筆就是「定案後重選」的全部次數 —— 訊號是對的，量太少。

可選後備（不要自己開做）：
- **#9 吧八巴**：先驗比作做坐座好；要做從 `~/laowang-data/eval-models/path-char-lstm-spoken-v2d.bin` 起訓，不是 v2c。
- **真實語料進 CI**：只有「常常沒人跑本機 CORE 就當可發版」變成常態時才需要。
  現成 `ship-gate` 搬上 Actions 也守不住換模型。三條路都還沒做：私有語料 repo／加密附檔／去識別子集。

#11 句單已裁保留。中途掉線的最小提案寫在 issue，**沒實作**（驗證需要 `SHIP_GATE_E2E=1`）。

> **whisper-server fetch 這個洞已經補過三次**（`release.yml` `7a05fd79` →
> Build workflow v2.17.1 → `codeql.yml` 2026-08-13 / issue #12）。
> 新增任何會 build `iBopomofo` target 的 workflow，**第一件事就是加 fetch 步驟**：
> `WHISPER_FETCH_BIN_ONLY=1 ./whisper-runtime/fetch-runtime.sh`。
> 漏了會 exit 65，而且症狀看起來像「程式壞了」，不像「少一個檔」。

## 已排除的路

全部集中在 **`docs/dead-ends.md`**。**動手前先讀那份**，別在這裡找。

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
