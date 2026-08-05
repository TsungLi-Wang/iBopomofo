# i注音 — 選單功能盤點

> 本檔在 **2026-07-24 稽核棒** 建立（v2.7.0-dogfood 大掃除後）。  
> **2026-08-05**：產品按鍵／定案行為以 **v2.13.3** 為準（見 repo `AI_HANDOFF_PROMPT.md`／`AGENTS.md`）。下表「Tab vs Enter」為 **v2.7 歷史敘事**，**已過時**——現役為：定案＝改字+hard commit 不送出；再 Enter＝送出；定案後 ↓＝刪回重組 1→1。  
> 歷史細節（已刪功能的 code 對照）見 git 歷史中本檔的父版本。

---

## ⚠️ 對外網路（現況）

| 路徑 | 狀態 |
|---|---|
| Claude 雲端整句 | **已移除** |
| llama 模型下載 / 常駐 | **已移除** |
| whisper 首次模型下載 | **保留**（語音，按需） |
| 檢查更新 | **保留**（GitHub） |

---

## 選單總表（v2.7.0-dogfood）

| # | 選單 | 偏好鍵 | 預設 | 模型 | commit 影響 | 分層 | 來源 |
|---|---|---|---|---|---|---|---|
| 1 | 輸出簡體中文 | `ChineseConversionEnabled` | OFF | OpenCC | 是 | 輸出後處理 | 上游 |
| 2 | 半形標點 | `HalfWidthPunctuationEnable` | OFF | 無 | 是 | 輸出 | 上游 |
| 3 | 聯想詞 | `AssociatedPhrasesEnabled` | OFF | 聯想表 | 選後 | UX | 上游 |
| 4 | 情境化選字 | `EnableContextualWalk` | ON | word-bigrams.tsv | 是（逐鍵） | **L0** | fork |
| 5 | 神經路徑重排 | `EnableNeuralPathRerank` | ON | v2c int8 `path-char-lstm.bin` | Enter 是；**Tab 預覽不 commit** | **L0+** | fork |
| 6 | 語音輸入 | （動作） | — | whisper 本機 | 是 | **L3** | fork |

**已移除（v2.7）**：AI 候選建議、AI 句末自動校正、同音字智慧消歧、AI 神經候選重排、Claude/本機 AI 後端選單、⌘Return AI 校正。  
孤兒偏好鍵啟動時由 `Preferences.purgeRemovedFeaturePreferences()` 清除。

---

## Tab vs Enter（L0+）

| 鍵 | 行為 | 重排 | 組字狀態 |
|---|---|---|---|
| **Tab**（組字中） | `scoreNBest` 同 Enter，結果 hard-pin，更新預覽 | 是 | **保持** Inputting |
| **Tab**（非組字） | 不攔截 | — | 放行宿主 |
| **Enter** | 重排後 `Committing` | 是 | 送出 |
| 句尾空白 / 失焦 | 原版 commit，**不**重排 | 否 | 送出 |

釘住實作：`KeyHandler._pinLatestWalkWithHardOverrides`（`kOverrideValueWithHighScore`）。手選 hard override 不被覆寫（與 32/32 invariant 同型）。

---

## 模型

| 資產 | SHA256 / 指紋 | 用途 |
|---|---|---|
| `path-char-lstm.bin`（bundle） | `ebd603195275622570c79127f61e0d37efe56fe17c61048bc0af9f01b59866ba`；LWLSTM8 emb256/hid512 | L0+ Enter/Tab |
| Qwen3-4B GGUF | 已不載入 | — |
| whisper model.bin | Application Support | L3 語音 |

---

## Commit 路徑 × L0+（未變，裁決仍成立）

僅 **Enter**（`_handleEnterWithState`）與 **Tab 預覽**（不 commit）開 `_rerankThisWalk`。  
標點進組字、空白句尾、失焦 force-commit **不**走 L0+（Johnny 拍板不補接）。

---

## 啟動 log

```
ShippingConfig: contextualWalk=ON|OFF neuralPathRerank=ON|OFF nu=0.75 N=10 model=size=…,magic=…
```

見 `Preferences.logShippingConfiguration()`。
