# 內部整頓 2026-07-27

## 開棒控制組
見 `tw538-internal-refactor-control.stdout.txt` → **387/537**。

## A: scoreSentence
- 產品 `reading_grid::walk` 只呼叫 `pathScorer_->scoreNBest`（`reading_grid.cpp`）。
- `scoreSentence` 標 TEST-ORACLE；實作保留供對照。
- 測試：`NeuralLMPathScorerEqualityTest`（engine ctest）。

## B: 死旋鈕
- `tw538_fusion_variants.cpp` → FATAL stub（len/zscore/minmax 旋鈕拆除）。
- `zenzai_constrained_search.cpp`：α 掃描迴圈移除，僅 α=1.0 residual。
- **未碰** ν、N、λ、μ_user。

## C: ⌘Return 測繪（v2.7 已刪，本棒驗屍）

### 依賴圖（刪除前歷史 / 現況）
| 節點 | 狀態 |
|---|---|
| `InputMethodController.handle` `keyCode==36` + ⌘ | **已刪**（v2.7） |
| `triggerAICorrection` / `+AICorrection` | **已刪** |
| `ClaudeAICorrector` → Anthropic | **已刪** |
| `LocalServerAICorrector` / `LlamaServerManager` | **已刪** |
| 選單 Claude / 本機 AI 後端 | **已刪** |
| `AICorrectionError` Claude 文案 | **本棒再清**；型別改只服務 whisper |

### 為何 Johnny 實機「無作用」
v2.7 已移除綁定與後端；按 ⌘Return 走系統/宿主預設（輸入法不攔截）。

### 共用零件
無：AI 句末自動校正亦於 v2.7 刪除。whisper 僅共用錯誤型別名稱殼，已瘦身。

### 仍會觸網的路徑（正式體檢）
| 路徑 | 性質 | 送出組字文字？ |
|---|---|---|
| 檢查更新 → GitHub | 版本 plist | **否** |
| whisper 模型首次下載 → HuggingFace | 按需資產 | **否** |
| whisper-server `127.0.0.1` | 本機語音 | 音訊→本機，非雲端文字上傳 |
| Anthropic / Claude | — | **已不存在** |

## 產物驗收
- tw538 整棒前後 = 387
- equality ctest 綠
- app Release build 綠
