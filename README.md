# i注音（iBopomofo）

macOS 上的**繁體中文注音輸入法**。在成熟的開源注音引擎之上，加上**台灣語料情境選字**與**進程內神經路徑重排**——打字當下完全離線，不送雲端。

| | |
|---|---|
| **產品名** | i注音（英文／ASCII：**iBopomofo**） |
| **目前版本** | **2.13.3**（build **2311**） |
| **授權** | MIT（衍生自 [McBopomofo](https://github.com/openvanilla/McBopomofo)；見 [LICENSE](LICENSE) 與 [NOTICE](NOTICE)） |
| **平台** | macOS 10.15+（開發建議 14.7+ / Xcode 15.3+） |

## 這是什麼、給誰用

- **給誰**：在 Mac 上打繁體中文注音、希望「整句更像台灣人會寫的字」、又在意隱私的人。
- **不是什麼**：不是雲端 AI 聊天輸入法，也不是簡體拼音輸入法。

## 核心特色

1. **在地化注音引擎**  
   音節 lattice + Viterbi walk；可開**情境化選字**（語料 bigram，看前文選同音字）。

2. **進程內神經路徑重排（完全離線）**  
   **句子結束定案**時（停頓／。／，若啟用，或組字中 Enter）對整句 N-best 用內嵌 char-LSTM（v2c int8）重打分後 **hard commit**（底線消失、字進 app），**當下不送出**。  
   實驗室北極星 **tw538**：**387 / 537** 正解（λ=0.75、ν=0.75）。實機還會受個人詞庫影響。

3. **定案 ≠ 送出**  
   底線消失後**再按 Enter** 才觸發搜尋／聊天送出／換行。偏好可開：停頓、句號、逗號。

4. **定案後改字（刪回重組）**  
   ↓ 開同音字 → 選字時**驗證舊字已置換**才完成（失敗 beep、不疊字）。←／→ 為 app 原生移游標。

5. **可觀測與本機差異 log**  
   - 選單「顯示目前生效設定…」：版本、GitRevision、重排開關、ν、模型指紋等。  
   - 可選：定案且重排真的改字時，本機 append  
     `~/Library/Application Support/McBopomofo/rerank-diff.log`（不上傳；可關可清）。

6. **語音（可選）**  
   連按兩下右 Shift：本機 whisper.cpp 聽寫（首次需模型；與注音引擎路徑獨立）。

## 高階架構（一句話）

```
注音鍵入 → lattice walk（可選 contextual bigram + 個人 soft）
         → 定案觸發：walkNBest(N=10) + 神經 scoreNBest → hard commit（不送出）
         → 再按 Enter → app 送出；定案後 ↓ → 刪回重組改同音
```

硬約束：只在合法同音字裡選，不自由生成；使用者手選優先於神經分數。

## 安裝

### 從 Release（推薦）

1. 到 [Releases](https://github.com/TsungLi-Wang/iBopomofo/releases) 下載 `iBopomofo.dmg`。  
2. 執行「安裝 i注音」；若 Gatekeeper 擋住，可用：

```bash
curl -fsSL https://raw.githubusercontent.com/TsungLi-Wang/iBopomofo/master/scripts/install.sh | bash
```

3. **系統設定 → 鍵盤 → 文字輸入 → 輸入法 → 編輯**，加入「**i注音**」。

> **技術備註**：內部 bundle id / 安裝路徑仍為上游繼承的  
> `org.openvanilla.inputmethod.McBopomofo` 與  
> `~/Library/Input Methods/McBopomofo.app`，避免與舊安裝斷裂。  
> **畫面上**顯示的是 i注音 / iBopomofo。

### 從原始碼 build

```bash
git clone https://github.com/TsungLi-Wang/iBopomofo.git
cd iBopomofo
xcodebuild -project McBopomofo.xcodeproj -scheme McBopomofo \
  -configuration Release -derivedDataPath build/dd-rel build
# 覆蓋安裝（會重啟輸入法進程）
killall McBopomofo 2>/dev/null || true
ditto build/dd-rel/Build/Products/Release/McBopomofo.app \
  "$HOME/Library/Input Methods/McBopomofo.app"
xattr -dr com.apple.quarantine "$HOME/Library/Input Methods/McBopomofo.app"
"$HOME/Library/Input Methods/McBopomofo.app/Contents/MacOS/McBopomofo" install
open "$HOME/Library/Input Methods/McBopomofo.app"
```

或建 `McBopomofoInstaller` scheme，用安裝器流程。

## 給 AI 協作者

這份 repo 是**真人 + AI 協作**的產品庫。若你是接棒的 AI：

1. 先讀 **[AGENTS.md](AGENTS.md)**（含**版本可追溯鐵則**、build/test、隱私紅線）。  
2. 再讀 **[AI_HANDOFF_PROMPT.md](AI_HANDOFF_PROMPT.md)**（目前真相、下一刀、交班日誌）。  
3. 變更歷程：**[CHANGELOG.md](CHANGELOG.md)**。  
4. 更深算法與評測：`Source/Engine/eval/`、`algorithm.md`（若有）。  
5. Johnny 本機另有完整交接檔（三卷制）；公開 repo 以本目錄文件為準。

**協作模式摘要**：改產品行為必須更新 CHANGELOG 人話；發布點須 bump 兩份 Info.plist + annotated tag；major/minor 由維護者拍板。**勿**把本機 `rerank-diff.log`、UOM cache、API key、`.env` commit 進來。

## 隱私

- 注音主路徑與神經重排：**離線、進程內**。  
- 個人化：`~/Library/Application Support/McBopomofo/`（不進安裝包、不上傳）。  
- 重排差異 log：可選、本機、可清除。  
- 檢查更新可能連 GitHub Releases（僅版本資訊）。

## 授權與來源

- **上游**：McBopomofo，MIT，Copyright (c) 2011–2026 Mengjuei Hsieh et al.  
- **本專案**：i注音 / iBopomofo，MIT 衍生作品；見 [NOTICE](NOTICE)。  
- 請保留 LICENSE 與原始著作權標頭；新增貢獻同樣以 MIT 釋出，除非檔案另有說明。

## 版本與追溯

| 版本 | 說明 |
|------|------|
| 2.6.0 | 神經路徑重排出貨 |
| 2.7.0 | 大掃除（去雲端/llama）+ 可觀測 / diff log + 版本可追溯鐵則 |
| 2.8.0 | 正式公開開源 + 品牌更名 i注音 / iBopomofo |
| 2.9–2.12 | 定案／重選探索（多版迭代；細節見 CHANGELOG） |
| **2.13.0** | **行為總則：定案 ≠ 送出** |
| 2.13.1–2.13.2 | 句號／逗號觸發；定案後方向鍵放行 |
| **2.13.3** | **定案後重選 1→1 驗證置換（不疊字）** |

完整條目見 [CHANGELOG.md](CHANGELOG.md)。Latest tag：`v2.13.3`。

## 已知取捨（開源後）

- **tw538** 評測集隨 repo 公開後，未來外部模型可能將其納入訓練，削弱其作為「乾淨裁判」的長期價值——這是公開的已知代價。  
- 內部 target / C++ namespace / bundle id 仍含歷史名 `McBopomofo`，以維持安裝與 IMK 相容；**品牌層**已統一為 i注音。
