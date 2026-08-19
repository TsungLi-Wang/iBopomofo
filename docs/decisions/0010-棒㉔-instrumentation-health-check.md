# 0010 — 棒㉔ Instrumentation Health Check：**HEALTHY**（但資料量幾乎為零）

**決定**：棒㉓ 部署的 instrumentation 運作正常、沒有測試污染、事件語意正確，
**可以進入資料自然累積期**。

**什麼會推翻它**：若之後發現 production log 又出現非使用者來源的事件，
或 census 中斷（有打字但沒有新行），本判定作廢，回到 BLOCKED 重查。

---

## 1. 實際使用的 build

| 項目 | 值 |
|---|---|
| 安裝路徑 | `~/Library/Input Methods/iBopomofo.app` |
| **GitRevision** | **`5ba17a96`**（棒㉓ 最後一個動到程式碼的 commit）|
| 版本 | 2.17.1 / 2325 —— **不足以辨識**，官方發布版同號 |
| binary 時間 | 2026-08-19 12:20:49 |
| IME 進程 | PID 16903，自 12:22:25 持續運行 |
| `DecisionCensusLog` 符號 | 2（舊 build 為 0）|
| `appendV2` / `TRUE_CORRECTION` 符號 | 2（舊 build 為 0）|

## 2. instrumentation 是否存在

**是。** 符號在安裝的二進位裡，而且**有真實產出**（見 §4），不是「source 有、build 沒有」。

## 3. 真實資料起始時間

**`2026-08-19T05:06:35Z`（本地 13:06:35）** —— 第一筆落在所有已知自動化窗口之外的事件。

**在此之前的一律不可信，必須排除：**

| 區間 | 來源 | 數量 |
|---|---|---|
| `2026-08-18T12:21` / `12:22` | ⑲ 的 XCTest host | v2 correction ×4 |
| `2026-08-19T03:55` | 棒㉓ 測試套件（防護前）| v2 correction ×2 |
| `2026-08-19T04:21:05` ~ `04:22:33` | 棒㉓ 的 `e2e-typing-check.sh` / `type-as-user.sh` | census ×2 |

> **schema v2 至今沒有任何一筆真實使用者 correction。** 6 筆全是測試產物。

## 4. Census 統計

| | 筆數 | 節點 | 字 | 手選 |
|---|---:|---:|---:|---:|
| 全部 | 3 | 13 | 22 | 0 |
| 自動化（須排除）| 2 | 10 | 19 | 0 |
| **真實 production** | **1** | **3** | **3** | **0** |

每日（真實）：`2026-08-19` 1 筆定案。

**已驗證的關鍵性質**：那 1 筆是**被動接受引擎輸出**（手選 0），
correction log 同時間沒有增加 —— **分母不只在修正時增加**，
這正是棒㉓ 之前結構上缺的東西。

## 5. Correction v2 統計

總數 6，全部 `TRUE_CORRECTION` / `composing`。
**排除測試產物後：0 筆。**

## 6. 測試污染檢查（本棒最重要的驗收項）

跑完整測試套件（**170 項全綠**），逐檔比對 SHA256：

| 檔案 | 測試前 | 測試後 |
|---|---|---|
| `decision-census.log` | `b8828fa548ad` | **`b8828fa548ad`** |
| `manual-correction.log` | `54f88f38d349` | **`54f88f38d349`** |

**完全未變。** 比行數更強的證據。XCTest 防護（`XCTestConfigurationFilePath`）
在兩個 log 上都在位（`DecisionCensusLog` 2 處、`ManualCorrectionLog` 3 處）。

## 7. 事件語意

- `n_user_picks` **不是** `Node::isOverridden()`（棒㉓ 已改）。
  census 路徑內已無 `isOverridden` 呼叫；計數只在 `fixNodeWithReading`
  真的完成一次手選時 `+1`（`KeyHandler.mm:460`），`clear` 時歸零（`:572`）。
- correction v2 記錄的是**每一次明確的候選手選**，`TRUE_CORRECTION` 是其子集
  （`NOOP_RESELECT` 也會寫入，由 `classify` 區分）。

### ⚠️ 一個要記住的限制（不是 bug）

**post-commit 的 reselect 修正不計入 census 的 `n_user_picks`。**
`InputMethodController+ShadowReselect.swift:224` 只寫 correction log，
而該次定案的 census 行**在定案當下就已寫出**。

→ 分析時：**分母用 census 的 `n_nodes`，分子用 correction log 的 v2 事件**（兩種 source 都算）。
census 自帶的 `n_user_picks` 只是 composing 路徑的便利值，**不是完整分子**。

## 8. 已實機驗證的事件

- ✅ 被動接受引擎輸出 → census +1、correction 不變（真實 production 與自動化各驗過）
- ✅ census 跨多次定案累積
- ✅ `scripts/correction-census.sh` 正確辨識 schema v2 與分母檔

## 9. 尚未實機驗證的事件

- ⬜ 手選候選（composing）
- ⬜ 定案後 reselect
- ⬜ `NOOP_RESELECT`

現有工具（`e2e-typing-check.sh` / `type-as-user.sh`）不支援方向鍵與候選窗操作。
依 `dead-ends` F 節（Johnny 2026-08-12 明令）**不為此蠻幹**，記為尚未驗證。
這三條由 170 項單元測試與程式碼路徑同一性覆蓋，但沒有實機觀察。

## 10. 判定

# INSTRUMENTATION HEALTHY

機制正確、無污染、語意正確、沒有資料遺失。

**但必須同時講清楚：真實資料量目前是 census 1 筆、correction v2 0 筆。**
部署距今約 46 分鐘。**HEALTHY 講的是管線，不是資料量。**

## 11. 下一步（唯一建議）

> **停止改動，讓 production 真實資料自然累積；待資料量達到既定門檻後，
> 再進行 M5 的 cross-fitted rescue / damage / net 評估。**

門檻見 [`0009`](0009-下一個產品方向是先讓儀器上線.md) §11：
**≥ 300 筆 TRUE_CORRECTION 或滿 21 天，先到者為準。**
