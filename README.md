# i注音（iBopomofo）

macOS 上的**繁體中文注音輸入法**。在成熟的開源注音引擎之上，加上**台灣語料情境選字**與**進程內神經路徑重排**——打字當下完全離線，不送雲端。

| | |
|---|---|
| **產品名** | i注音（英文／ASCII：**iBopomofo**） |
| **目前版本** | 見 [CHANGELOG.md](CHANGELOG.md) 最上方已發布段落，或 `Source/McBopomofo-Info.plist`（本機現役為 **2.16.3**／build **2323**） |
| **授權** | MIT（衍生自 [McBopomofo](https://github.com/openvanilla/McBopomofo)；見 [LICENSE](LICENSE) 與 [NOTICE](NOTICE)） |
| **平台** | macOS 10.15+（開發建議 14.7+ / Xcode 15.3+） |

## 這是什麼、給誰用

- **給誰**：在 Mac 上打繁體中文注音、希望「整句更像台灣人會寫的字」、又在意隱私的人。
- **不是什麼**：不是雲端 AI 聊天輸入法，也不是簡體拼音輸入法。

## 核心特色

1. **在地化注音引擎**  
   音節 lattice + Viterbi walk；可開**情境化選字**（語料 bigram，看前文選同音字）。

2. **進程內神經路徑重排（完全離線）**  
   **句子結束定案**時（停頓／。／，若啟用，或組字中 Enter）對整句 N-best 用內嵌 char-LSTM 重打分後 **hard commit**（底線消失、字進 app），**當下不送出**。  
   架構家族仍是 **v2c**（emb256／hid512／路徑層 N-best）；出貨權重為 **v2d**：在 v2c 上只針對「在／再」微調 1,538 個參數後的 int8（`Source/Data/path-char-lstm.bin`）。

3. **的／得 文法規則（節點層）**  
   定案前在既有候選內修正「動詞＋的＋結果補語」→「得」（`particle-rules.tsv`）。程度副詞半邊（得很／得超）**不做**。

4. **定案 ≠ 送出**  
   底線消失後**再按 Enter** 才觸發搜尋／聊天送出／換行。偏好可開：停頓、句號、逗號。

5. **定案後改字（刪回重組）**  
   ↓ 開同音字 → 選字時**驗證舊字已置換**才完成（失敗 beep、不疊字）。成功後可寫入本機個人化（UOM）。←／→ 為 app 原生移游標。

6. **可觀測與本機差異 log**  
   - 選單「顯示目前生效設定…」：版本、GitRevision、重排開關、ν、模型指紋等。  
   - 可選：定案且重排真的改字時，本機 append  
     `~/Library/Application Support/McBopomofo/rerank-diff.log`（不上傳；可關可清）。

7. **語音（可選）**  
   連按兩下右 Shift：本機 whisper.cpp 聽寫（首次需模型；與注音引擎路徑獨立）。

## 高階架構（一句話）

```
注音鍵入 → lattice walk（可選 contextual bigram + 個人 soft）
         → 定案觸發：walkNBest(N=10) + 神經 scoreNBest → particle 規則 → hard commit（不送出）
         → 再按 Enter → app 送出；定案後 ↓ → 刪回重組改同音
```

硬約束：只在合法同音字裡選，不自由生成；使用者手選優先於神經分數與規則。

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
xcodebuild -project iBopomofo.xcodeproj -scheme McBopomofo \
  -configuration Release -derivedDataPath build/dd-rel build
# 覆蓋安裝（會重啟輸入法進程；勿 rm -rf 安裝路徑）
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

1. 先跑 `gh issue list --label deadend --state all` 與 `gh issue list`（現況／死亡路在 Issues）。  
2. 讀 **[AGENTS.md](AGENTS.md)**（建置、UX 總則、**收工清單**、隱私紅線）。  
3. 讀 **[AI_HANDOFF_PROMPT.md](AI_HANDOFF_PROMPT.md)**（目前真相、試過不行的路、下一棒）。  
4. 變更歷程：**[CHANGELOG.md](CHANGELOG.md)**（版本號真源）。  
5. 軍師視角（本機）：`~/Documents/i注音-傳承交接檔.md`——**產品現況不以它為準**。  
6. 評測：`Source/Engine/eval/benchmarks/README-newstar.md`；出貨前 **`./scripts/ship-gate.sh`**。

**協作模式摘要**：改產品行為必須更新 CHANGELOG 人話；發布點須 bump 兩份 Info.plist + annotated tag + `doc-check`／`ship-gate`；major/minor 由維護者拍板。**勿**把本機 `rerank-diff.log`、UOM cache、API key、`.env` commit 進來。

## 隱私

- 注音主路徑與神經重排：**離線、進程內**。  
- 個人化：`~/Library/Application Support/McBopomofo/`（不進安裝包、不上傳）。  
- 重排差異 log／手動校正 log：可選、本機、可清除。  
- 檢查更新可能連 GitHub Releases（僅版本資訊）。

## 授權與來源

- **上游**：McBopomofo，MIT，Copyright (c) 2011–2026 Mengjuei Hsieh et al.  
- **本專案**：i注音 / iBopomofo，MIT 衍生作品；見 [NOTICE](NOTICE)。  
- 請保留 LICENSE 與原始著作權標頭；新增貢獻同樣以 MIT 釋出，除非檔案另有說明。

## 版本與追溯

| 版本 | 說明 |
|------|------|
| 2.6.0 | 神經路徑重排出貨（v2c 家族） |
| 2.7.0 | 大掃除（去雲端/llama）+ 可觀測 / diff log + 版本可追溯鐵則 |
| 2.8.0 | 正式公開開源 + 品牌更名 i注音 / iBopomofo |
| 2.9–2.12 | 定案／重選探索（多版迭代；細節見 CHANGELOG） |
| **2.13.0** | **行為總則：定案 ≠ 送出** |
| 2.13.1–2.13.3 | 句號／逗號觸發；方向鍵放行；重選 1→1 驗證 |
| **2.14.0** | 定案後改的同音字寫入個人化（UOM） |
| **2.15.0** | 「的／得」結果補語自動修正 |
| 2.16.0–2.16.1 | 同音規則／頻率壓縮實驗（後以真實語料驗證為淨傷害） |
| **2.16.2** | **退掉上述有害機制**；留下 的／得 規則 + **v2d（在／再）**；`ship-gate` 出貨關卡 |
| **2.16.3** | **的／得警察 v1**（句法規則 + 強棄權，反例考卷誤殺 0）；MAIN 資料地基修復；`ship-gate` 補三個洞 |

完整條目見 [CHANGELOG.md](CHANGELOG.md)。Latest tag：以 `git tag`／GitHub Releases 為準（本機錨：**v2.16.3**）。

## 已知取捨（開源後）

- 舊句級集 **tw538** 已作廢、只當歷史；難題集 EX1166 與真實語料驗證集用途不同——**不得拿 EX1166 分數對使用者宣稱**。  
- 內部 target / C++ namespace / bundle id 仍含歷史名 `McBopomofo`，以維持安裝與 IMK 相容；**品牌層**已統一為 i注音。
