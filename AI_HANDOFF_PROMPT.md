# i注音後續 AI 接棒 Prompt

你是 **i注音（iBopomofo）** 的後續協作開發 AI。這是 macOS 原生繁體中文注音輸入法，repo 為 `TsungLi-Wang/iBopomofo`。對外品牌為 i注音；內部仍保留 McBopomofo target、bundle id、input source id、C++ namespace 與安裝路徑以維持 IMK 相容。不要更名這些內部識別符，除非另有完整使用者資料遷移方案。

> **現役版本不寫在這裡** —— 見 `CHANGELOG.md` 最上面的已發布段落。
> 本檔只寫「現在的狀況」與「試過不行的路」；歷史交班日誌已搬到 `AI_HANDOFF_ARCHIVE.md`。

## 先讀文件

1. `AGENTS.md`（版本鐵則、Current line、產品 UX 總表、**收工清單**）
2. `CHANGELOG.md`（每版人話 + commit 範圍）
3. **本檔**（讀「三行同步狀態」即可；再往下是歷史日誌）
4. `~/Documents/i注音-傳承交接檔.md`（軍師視角：研究脈絡、死亡名單、判斷經驗。**產品現況不以此為準**）
5. 改詞庫：`Source/Data/AGENTS.md`；深算法：`algorithm.md`

> ⚠️ 舊文件曾指向 `~/Documents/i注音-總交接檔-v5.md`，**該檔不存在**（另有 `~/Downloads/i注音-總交接檔-v6.md` 但停在 v2.8.0，亦不可信）。已改為上面第 4 項。 <!-- doc-check-ignore -->

### 版本可追溯鐵則（常設）

見 `AGENTS.md`。有行為改動 → CHANGELOG 人話；發布點 → 兩 plist + annotated tag + commit 範圍。

---

## 三行同步狀態（2026-08-10）

1. **發版**：**v2.15.0**（build **2313**，tag **`v2.15.0`**）。新增 **的/得 文法規則消歧**（`ParticleRuleDisambiguator`，掛在 `_walk` 之後）：打「看的懂／養的起／打的過」自動修成「得」。真實語料抽 40 例 39 正確；每萬字出手一次；「我的書／真的很好／唱的歌」不受影響。已實機 e2e 驗證。
2. **公開**：https://github.com/TsungLi-Wang/iBopomofo — Releases **Latest = v2.15.0**。
3. **下一刀**：新北極星 EX1166 題庫（目前只有 9 組共 499 句生成句，未過小麥注音、未成題庫）。**注意：tw538 已作廢，目前沒有制度化的引擎驗收門檻**——改引擎要在 CHANGELOG 寫清楚你用什麼資料、怎麼量的。

### v2.15.0 已排除的路（別重試）

- **神經模型解不了的/得**：拿掉詞頻優勢、只問 v2c 哪句順，59 句 66%，該打「得」的只對 9/29 且錯的全選「的」。根因是 v2c 的 PTT 訓練語料本身四成寫錯。
- **的/得 的程度副詞半邊（得很／得超／得太）**：五種寫法都試過，誤改率地板 20%。「你說的超展開」「你問的太平島」跟「你說得很誇張」在前後三字內完全同形，要看懂整句結構才分得出來。
- **舊的 在/再 混淆表（`confusion-pairs.tsv`，v2.7.0 刪除）**：取回實測 **93% → 90.25%（變差）**。它是 v2c 成為主力前訓的（913 句合成語料），現在會跟 v2c 搶決定。**七月那次刪除是對的，不是誤刪。** <!-- doc-check-ignore -->
- **補 v2c 的視野死角**：實測 400 題只有 **1.2%** 是「正確答案沒進十條候選」，天花板太低。真正的錯（23/28）是「看到了還選錯」。

### tw538 基準線

| 系統 | correct/537 | 備註 |
|------|-------------|------|
| walk OFF / ON | 296 / **333** | |
| **v2c LSTM（出貨）** | **387 @ ν0.75** | 9.73M；進程內 ~45ms 級 |
| char-TF 6L/256 | **332 @ ν0.25** | 封存 |
| 約束 fusion | 335+ | 研究線，非出貨 |

---

## 目前真相（v2.13.3）— 換手必讀

| 項目 | 狀態 |
|------|------|
| 產品版 | **2.13.3** / build **2311** / tag **`v2.13.3`** / **`f4df30b9`** |
| plist | `Source/McBopomofo-Info.plist` + `Source/Installer/Installer-Info.plist`（一起 bump） |
| master | 應與 `origin/master` = tag `v2.13.3` 對齊 |
| 北極星 | tw538 **387/537**；引擎 walk/v2c **不得擅自改** |
| 安裝路徑 | `~/Library/Input Methods/McBopomofo.app`（顯示名 i注音） |
| Commit 作者 | `老王 LaoWang <laowang@users.noreply.github.com>` |

### 行為總則（唯一真源 — 三件事分開）

| 動作 | 含義 |
|------|------|
| **改字** | 智慧選字／rerank（scoreNBest + pin） |
| **收底線＝定案** | hard commit：底線消失、字交給 app |
| **送出** | app 自己的動作（搜尋／聊天／換行）— **必須**在底線已消失後再按 Enter |

| 事件 | 改字 | 收底線 | 送出 |
|------|------|--------|------|
| 啟用觸發點：停頓／。／， | ✅ | ✅ | ❌ |
| Enter（畫面**還有**底線） | ✅ | ✅ | ❌（return YES 吃掉鍵） |
| Enter（**已無**底線／Empty） | ❌ | — | ✅（return NO 交給 app） |

- 觸發點在**偏好「句子結束」**：停頓（+毫秒）、句號、逗號，各自可勾。
- Enter **不是**觸發點開關；語意見上表。
- 標準注音：。＝鍵 **`>`**，，＝鍵 **`<`**（v2.13.1 修偵測）。

### 定案後改字＝刪回重組（v2.13.3 置換；v2.14.0 學習）

1. 定案後 armed 影子讀音表；↓ 開**該字讀音**的同音**單字**清單（不重跑模型；純手動逐字替換）。
2. **選字後必須 1→1**：先確認舊字被移除／置換成功，才算完成；失敗 → **beep、不插新字**（絕不可兩字並排、句子變長）。
3. **v2.14.0**：置換成功後 **best-effort** 寫入 UOM soft（`noteSoftObservationStrong`：prev=左方字、reading、chosen；一次達 count≥2）；失敗不影響已換上的字。組字中 `fixNode→observe` 路徑不變、不雙算同一次動作。
4. **校正 log schema v1**：`schemaVer \t ISO8601 \t reading \t left_context \t wrong_char \t chosen`（`manual-correction.log`；純紀錄、不回灌）。
5. **讀不到游標／range 的 app**：beep 不改、不學、不寫壞 log；**不是 bug**。
6. 定案後 **←／→ 一律放行**；失準 disarm，**絕不誤刪**。

### 四鍵（定案後、重選語境）

| 鍵 | 行為 |
|----|------|
| **待修改字** | 游標**右方**那一個字（句尾無右方字時 ↓ 預設改**最後一字**） |
| **←／→** | **app 原生**移游標（不攔截）；↓ 當下再 map 影子 |
| **↑** | 放行；shadow disarm（不追跨行） |
| **↓** | 開同音單字清單 → 選字 → 驗證 1→1 置換 |

（組字中、有底線時：仍是一般注音 ←／→／↓ 原生候選行為，與定案後路徑不同。）

### 版本／commit 對照（v2.8 後產品 UX 主線）

| 版本 | build | tag/commit 錨 | 要點 |
|------|-------|----------------|------|
| 2.8.0 | 2293 | `v2.8.0` | 公開開源 + 品牌 i注音 |
| 2.9.x | 2294– | `v2.9.0`… | 三段式 soft-finalize／clawback 探索（多已作廢） |
| 2.10.x | … | `v2.10.1` | Option B／Enter 兩段（後由 2.13 總則取代敘事） |
| 2.11.0 | 2305 | `v2.11.0` | 刪回重組 shadow 初版 |
| 2.12.x | 2306–07 | `v2.12.0`… | 路徑 β 試誤（已作廢衝突語意） |
| **2.13.0** | **2308** | `3fe2b8ae` | **行為總則：定案≠送出** |
| 2.13.1 | 2309 | `de83fb07` | 。／，觸發（`>`／`<`） |
| 2.13.2 | 2310 | `66e50f4f` | 定案後 ←／→ 放行 |
| **2.13.3** | **2311** | **`f4df30b9`** | **重選 1→1 驗證刪除** |

完整人話條目：`CHANGELOG.md`。

### 引擎／架構（仍有效）

- **L0** lattice walk：`KeyHandler` / `InputState` 不可繞；`chosenValueAt` 才是 DP 選字。
- **L0+** 情境 bigram λ=0.75 + UOM soft（預設開）；**神經路徑重排**於**定案**（停頓／。／，／有底線 Enter）觸發，非「Tab 當定案」。
- **L1** 候選窗 n-gram 重排（選單可關）。
- **L3** 語音 whisper.cpp（連按兩下右 Shift）。
- 雲端 Claude／常駐 llama：**已移除**（v2.7+）。
- 隱私：`user-override-cache.dat`、`rerank-diff.log`、`manual-correction.log` 只本機。

### 開發約束（摘要）

- 不改 walk/v2c 權重與打分邏輯除非 Johnny 明示；動了必跑 tw538，≠387 即 FATAL。
- 不共用 DerivedData；`xcodebuild test` 不要 `| tail`。
- 不更名 McBopomofo 內部識別符。

### 關鍵程式入口（重選／定案）

| 用途 | 檔案 |
|------|------|
| 定案 hard commit | `KeyHandler.mm` → `hardCommitSentence` / `_handleEnter` |
| 停頓觸發 | `InputMethodController.swift` → `fireSentenceEndIdleTimer` |
| 影子 armed / ↓ | `InputMethodController+ShadowReselect.swift`、`ShadowReselect.swift` |
| 選字 1→1 置換 | `PostCommitReselect.replacePendingCharacter` + CandidateDelegate pick |
| 偏好觸發點 | `Preferences.swift` / `PreferencesWindowController` 句子結束分頁 |

## 下一步建議（接棒用）

1. **真機 dogfood**：TextEdit 定案後連改 3 字、字數不增；LINE／Telegram 方向鍵可動、重選可 beep 降級。
2. （可選）讀不到 range 時的 UX 文案／AX 引導。
3. 手動改字 log 累積後再談重訓；引擎分數線維持 387 維護。
4. 研究線（判別器等）見總交接檔 v5 — **與出貨 UX 分離**。

## 後續 AI 回覆使用者時

- 用「定案＝底線消失、字已進 app」「送出＝再按 Enter」說明，**不要**說「停頓只改字留底線」或「Enter 一下就送出」（那是已作廢的 2.12.x 語意）。
- 定案後改錯字＝↓ 重選；改失敗 beep＝正常 fail-closed。
- **目前正式版 = v2.13.3**，不是 v2.3.0／v2.8.0。

**誠信**：數字必須真跑；三狀態分報（app build / harness / deliverables）；文件與改動同棒更新。

---

## 歷史交班日誌

已搬到 **`AI_HANDOFF_ARCHIVE.md`**（約 970 行）。

**那份只當歷史，不要當現況。** 裡面提到的許多檔案（`AIAutoCorrector.swift`、 <!-- doc-check-ignore -->
`AICorrectionPrompt.swift`、`ConfusionPairDisambiguator.*` 等）**已經被刪除**， <!-- doc-check-ignore -->
路徑也可能失效。要查某個決定的來龍去脈可以翻，但**不要照著它動手**。

真正的歷史在 git：`git log --oneline` 比日誌可靠。
