# 老王注音

老王注音是 macOS 注音輸入法，基於 McBopomofo 的成熟注音引擎，加入「AI 整句修正」與產品化發佈流程。

使用方式很單純：照平常打注音，在組字中的一句話按 **Command + Return**，老王注音會依上下文修正常見錯字，例如同音字、平翹舌混淆、鄰鍵手誤，然後把修正後的整句送回輸入區。

預設後端是本機 AI：離線、免 API key、免安裝 Ollama。推理程式 `llama-server` 會打包在 app 內，模型第一次使用時自動下載一次，之後可離線使用。

## 重點功能

- 注音輸入：沿用 McBopomofo 的注音引擎、詞庫、候選字與使用者詞彙機制。
- AI 整句修正：組字中按 **Command + Return** 觸發。
- 語音輸入（實驗）：**連按兩下右 Shift** 開始、再連按兩下結束出字，用 Apple 內建語音辨識（繁中、優先離線）。用法與前置設定見下方「語音輸入（實驗）」一節。
- 本機 AI 預設開啟：內建 `llama-server`，模型首次使用自動下載到使用者資料夾。
- 雲端後端可切換：支援 Claude Haiku、Claude Opus 與 Codex CLI。
- 前文輔助判斷：修正時會讀取游標前方文字作為語意參考。
- 發佈包輕量：DMG 不內含 2.9GB 模型，目前約 19MB。

## 系統需求

| 項目 | 需求 |
|---|---|
| 作業系統 | macOS 11.0 或以上 |
| CPU | Apple Silicon 建議；Intel 可安裝，但本機 AI 效能未作為主要優化目標 |
| 網路 | 首次使用本機 AI 需下載模型，之後可離線 |
| 磁碟空間 | app 約數十 MB；本機 AI 模型約 2.9GB |

本 app 目前未經 Apple notarize，雙擊 `.app` 時 macOS 可能顯示「無法驗證開發者」。**建議用終端機一鍵安裝**（不需打開任何 `.app`）：

```bash
curl -fsSL https://raw.githubusercontent.com/TsungLi-Wang/laowang-zhuyin/master/scripts/install.sh | bash
```

## 下載與安裝

### 方式 A：終端機一鍵安裝（推薦）

1. 打開「終端機」(Terminal)。
2. 貼上上方 `curl … | bash` 指令，按 Enter。
3. 到「系統設定」→「鍵盤」→「文字輸入」→「輸入法」→「編輯」，加入「老王注音」。

### 方式 B：DMG 圖形安裝

1. 到 [GitHub Releases](https://github.com/TsungLi-Wang/laowang-zhuyin/releases) 下載 `LaoWangZhuyin.dmg` 並掛載。
2. 雙擊「安裝老王注音」→ 按「同意安裝」。
   - 若被 Gatekeeper 擋住：看 DMG 內的 `若 Gatekeeper 擋住請看這裡.txt`，或改用法 A。
   - 或對圖示 **右鍵 → 打開 → 再打開**（只需一次）。
3. 到系統設定加入「老王注音」輸入法。

安裝後，組字中按 **Command + Return** 可使用 AI 整句修正。

首次使用本機 AI 時會下載模型，約 2.9GB。模型下載完成後會存放在：

```text
~/Library/Application Support/McBopomofo/AIModel/
```

這個路徑暫時保留 `McBopomofo` 名稱，避免破壞既有輸入法資料與 macOS IMK 註冊行為。

## AI 後端

| 後端 | 預設 | 說明 |
|---|---:|---|
| 本機 AI(內建・離線) | 是 | 使用內嵌 `llama-server` 與 Qwen3-4B-Instruct-2507 Q5_K_M。免 API key，首次下載模型後可離線。 |
| Claude Haiku | 否 | 需要 Anthropic API key。速度快，語意判斷通常比本機小模型穩。 |
| Claude Opus | 否 | 需要 Anthropic API key。準確度優先。 |
| Codex CLI | 否 | 透過本機 `codex` 執行檔呼叫，延遲較高，主要保留作為備援與實驗路徑。 |

從輸入法選單的「AI 修正模型」可以切換後端。

## 設定

本機 AI 不需要設定。Claude 與 Codex 相關設定在輸入法選單的「AI 修正設定...」中調整。

| 項目 | 預設值 | 說明 |
|---|---|---|
| Claude API key | 無 | 存入 macOS Keychain，不寫入 repo 或設定檔明文 |
| Claude 端點 | `https://api.anthropic.com/v1/messages` | 可改成代理或相容端點 |
| Claude Haiku 模型 | `claude-haiku-4-5` | 速度優先 |
| Claude Opus 模型 | `claude-opus-4-8` | 準確度優先 |
| Codex 執行檔路徑 | `/opt/homebrew/bin/codex` | Homebrew Apple Silicon 預設路徑 |

## 語音輸入（實驗）

用講的輸入中文：辨識後的文字會直接送進游標所在的輸入框。採用 Apple 內建語音辨識（繁體中文、優先離線 on-device），不連雲端、不需額外安裝模型。

### 開始前（只需設定一次）

1. 開啟系統「聽寫」：**系統設定 → 鍵盤 → 聽寫**，打開。
   - 離線辨識需要這項；沒開啟時觸發會跳出「語音輸入需要『聽寫』」提示。
   - 這與「語音控制（Voice Control）」是不同功能，別搞混。
2. 首次觸發時，macOS 會分別要求「語音辨識」與「麥克風」兩項權限，請都允許。
   - 授權完成後只會提示「請再連按兩下右 Shift 開始說話」，**這一次還不會錄音**，要再連按一次才開始。之後不必再授權，重開機也會記得。

### 怎麼用

| 動作 | 操作 |
|---|---|
| 開始 | **連按兩下右 Shift**，看到「聆聽中…」即可說話 |
| 結束出字 | **再連按兩下右 Shift**，辨識文字會一次送進輸入框 |
| 備用入口 | 輸入法選單的「語音輸入（實驗）／停止語音輸入」 |

說話過程中不會逐字顯示，辨識完成才一次出字。出來的文字直接落入輸入框，不進注音組字區、不需選字。只有右 Shift 會觸發，左 Shift 不會。

### 常見狀況

- **跳出「需要聽寫」**：到系統設定開啟聽寫（見上）。
- **顯示「沒聽到內容」**：這次沒有收到語音，再連按兩下右 Shift 重試即可。
- **文字自己跑出來、好像停止聆聽了**：辨識器偵測到句尾或達到時間上限時會自行結束這一段，此時會提示「語音這段已自動結束」，再連按兩下右 Shift 即可重新開始。

## 目前限制

- 本機小模型對純語意同音字仍有限制，例如「在 / 再」這類情境不一定能穩定判對。
- 首次本機 AI 需下載 2.9GB 模型，下載失敗時需要連網重試。
- 目前未 notarize，因此發佈包仍需要清除 quarantine。
- 內部 target、bundle id、module、部分資料路徑仍保留 McBopomofo 命名；完整更名需要規劃使用者資料遷移。

## 版本更新歷程

完整版本變更請見 [CHANGELOG.md](CHANGELOG.md)。正式發佈與 DMG 下載位於 [GitHub Releases](https://github.com/TsungLi-Wang/laowang-zhuyin/releases)。

## 從原始碼建置

### 開發需求

- macOS 14.7 或以上
- Xcode 15.3 或以上
- Python 3.9
- `llama-runtime/bin/` 內需有 `llama-server` 與相關 dylib

### 取得本機推理 runtime

```bash
cd llama-runtime
./fetch-runtime.sh
```

這個腳本會取得 `llama-server`、必要 dylib 與本機開發測試用模型。正式 app build 只需要 `llama-runtime/bin/`，模型會由 app 首次使用時下載。

### Build app

```bash
xcodebuild -project McBopomofo.xcodeproj -scheme McBopomofo -configuration Debug build
```

Release build:

```bash
xcodebuild -project McBopomofo.xcodeproj -scheme McBopomofo -configuration Release -derivedDataPath build/dd-rel build
```

### 打包 DMG

```bash
./package-dmg.sh
```

輸出位置：

```text
dist/LaoWangZhuyin.dmg
```

## 專案結構

| 路徑 | 說明 |
|---|---|
| `Source/` | macOS 輸入法 app、IMK controller、偏好設定、AI 整合 |
| `Source/Engine/` | C++ 注音引擎與語言模型 |
| `Source/Data/` | 詞庫與資料生成工具 |
| `Packages/` | 本地 Swift Package 依賴 |
| `llama-runtime/` | 內嵌本機推理 runtime 與重建腳本 |
| `McBopomofoTests/` | Swift 測試 |
| `package-dmg.sh` | Release build 與 DMG 打包腳本 |

## 重構路線

目前的重構策略是先產品化，再做內部更名。

已完成或正在進行：

- 使用者可見文字改為老王注音。
- README、issue template、安裝器文字產品化。
- GitHub Release + DMG 作為正式發佈入口。
- 停止讓更新檢查導向 OpenVanilla 發佈通道。
- 拆分 AI 校正程式碼:prompt、Claude、Codex、本機 server 與 controller 流程已分檔。
- AI 後端改用結構化錯誤（`AICorrectionError`），失敗時顯示具體原因與處置建議。
- `McBopomofoInstaller` target 確認保留作為開發與正式 DMG 安裝流程（自動 kill/restart 輸入法）；正式發佈走 `package-dmg.sh` 打包「安裝老王注音.app」。
- app 顯示版本由上游遺留的 3.0 對齊為 1.x 產品版本。

下一步：

- 評估 bundle id、input source id、資料路徑與 app name 的完整更名方案。

## 問題回報

請使用 GitHub Issues：

- 功能異常、無法輸入、安裝失敗：使用 bug report template。
- AI 修正不準、想增加後端、想調整使用流程：使用 feature request template。

回報 AI 修正問題時，請盡量附上：

- 原本輸出的句子
- 你期待的正確句子
- 當時使用的 AI 後端
- macOS 版本與老王注音版本

## 授權與致謝

老王注音基於 [openvanilla/McBopomofo](https://github.com/openvanilla/McBopomofo)。原始注音引擎與輸入法框架依 MIT License 釋出，本 repo 保留原始授權與版權聲明，詳見 [LICENSE.txt](LICENSE.txt)。

主要依賴與參考：

- McBopomofo：注音引擎、輸入法框架、詞庫流程
- azooKey-Desktop：前文擷取做法參考
- llama.cpp：內嵌本機推理 runtime
- Qwen3-4B-Instruct-2507：本機 AI 校正模型
