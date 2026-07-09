# 老王注音

老王注音是 macOS 注音輸入法，基於 McBopomofo 的成熟注音引擎，加入**情境化選字**、**個人化**、「AI 整句修正」與產品化發佈流程。

使用方式很單純：照平常打注音即可。引擎會看前文幫你選同音字；你手動選過的字也會慢慢記住。需要整句校正時，在組字中按 **Command + Return**，老王注音會依上下文修正常見錯字（同音字、平翹舌混淆、鄰鍵手誤等），再把修正後的整句送回輸入區。

預設後端是本機 AI：離線、免 API key、免安裝 Ollama。推理程式 `llama-server` 會打包在 app 內，模型第一次使用時自動下載一次，之後可離線使用。

**目前正式版：v2.3.0**（[GitHub Releases](https://github.com/TsungLi-Wang/laowang-zhuyin/releases)）。

## 重點功能

- 注音輸入：沿用 McBopomofo 的注音引擎、詞庫、候選字與使用者詞彙機制。
- **情境化選字（v2.3.0 起預設開啟）**：真實語料詞 bigram 在打字當下參與路徑競爭，只在既有候選裡改選、不亂造字。可在輸入法選單「情境化選字」關閉。
- **個人化（本機）**：同一上下文手動選同一字約 **2 次以上**，之後同類上下文會更偏好該字；約 **7 天**半衰期。資料只存在本機（見下方隱私），不外傳。
- AI 整句修正：組字中按 **Command + Return** 觸發。
- 語音輸入：**連按兩下右 Shift** 開始、再連按兩下結束出字，用內嵌 whisper.cpp 本機辨識（離線、免 API key）。用法見下方「語音輸入」一節。
- 本機 AI 預設開啟：內建 `llama-server`，模型首次使用自動下載到使用者資料夾。
- 雲端後端可切換：支援 Claude Opus。
- 前文輔助判斷：修正時會讀取游標前方文字作為語意參考。
- 發佈包：DMG 約 **31MB**（含語料 bigram 表；不含 2.9GB AI 模型）。
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

## 情境化選字與個人化

| 項目 | 說明 |
|---|---|
| 情境化選字 | **預設開啟**。用內建語料 bigram 看前文選同音字。選單可關。 |
| 個人化 | 手動選字會寫入本機 cache；同上下文選同一字 **≥2 次** 才開始加強；約 **7 天** 半衰期。 |
| 隱私 | 個人化檔：`~/Library/Application Support/McBopomofo/user-override-cache.dat`。**只存本機、不進安裝包、不上傳。** |
| 升級注意 | 若曾手動關閉「情境化 Walk／選字」，升級後仍維持關閉（已寫入的偏好優先於新預設）。刪除該偏好或選單重開即可恢復預設。 |

## AI 後端

| 後端 | 預設 | 說明 |
|---|---:|---|
| 本機 AI(內建・離線) | 是 | 使用內嵌 `llama-server` 與 Qwen3-4B-Instruct-2507 Q5_K_M。免 API key，首次下載模型後可離線。 |
| Claude Opus | 否 | 需要 Anthropic API key。準確度優先。 |

從輸入法選單的「AI 修正模型」可以切換後端。

## 設定

本機 AI 不需要設定。Claude 相關設定在輸入法選單的「AI 修正設定...」中調整。

| 項目 | 預設值 | 說明 |
|---|---|---|
| Claude API key | 無 | 存入 macOS Keychain，不寫入 repo 或設定檔明文 |
| Claude 端點 | `https://api.anthropic.com/v1/messages` | 可改成代理或相容端點 |
| Claude Opus 模型 | `claude-opus-4-8` | 準確度優先 |

## 語音輸入

用講的輸入中文：辨識後的文字會直接送進游標所在的輸入框。採用內嵌 whisper.cpp（`whisper-server` + Whisper large-v3-turbo）在本機辨識，完全離線、免 API key，錄音與音訊都不出機器。

### 開始前（只需設定一次）

1. 首次使用會自動下載辨識模型（約 574MB，一次性），下載完成後永久離線可用。
2. 首次觸發時，macOS 會要求「麥克風」權限，請允許。
   - 授權完成後只會提示「請再連按兩下右 Shift 開始說話」，**這一次還不會錄音**，要再連按一次才開始。之後不必再授權，重開機也會記得。

### 怎麼用

| 動作 | 操作 |
|---|---|
| 開始 | **連按兩下右 Shift**，看到「聆聽中…」即可說話 |
| 結束出字 | **再連按兩下右 Shift**，稍候 1~3 秒辨識文字會一次送進輸入框 |
| 備用入口 | 輸入法選單的「語音輸入／停止語音輸入」 |

錄音是「錄完整段、停止後一次辨識」：說話過程中不會逐字顯示。出來的文字直接落入輸入框，不進注音組字區、不需選字。只有右 Shift 會觸發，左 Shift 不會。

### 常見狀況

- **顯示「沒聽到內容」**：這次沒有收到語音，再連按兩下右 Shift 重試即可。
- **顯示「本機辨識引擎未就緒」**：模型還在載入（首次啟動約數秒），稍候幾秒再試一次。
- **模型下載中斷**：連網後再連按兩下右 Shift 會自動重試。

## 目前限制

- 情境化選字與個人化能改善同音字，但不能保證每句都對；證據不足時維持引擎原判。
- 本機小模型對純語意同音字仍有限制；「在 / 再」另有實驗性查表消歧（預設關）。
- 首次本機 AI 需下載約 2.9GB 模型，下載失敗時需要連網重試。
- 目前未 notarize，因此發佈包仍需要清除 quarantine。
- 內部 target、bundle id、module、部分資料路徑仍保留 McBopomofo 命名；完整更名需要規劃使用者資料遷移。

## 版本更新歷程

最新正式版 **v2.3.0**：預設開啟情境化選字與本機個人化。完整變更見 [CHANGELOG.md](CHANGELOG.md)。下載：[GitHub Releases](https://github.com/TsungLi-Wang/laowang-zhuyin/releases)。

## 從原始碼建置

### 開發需求

- macOS 14.7 或以上
- Xcode 15.3 或以上
- Python 3.9
- `llama-runtime/bin/` 內需有 `llama-server` 與相關 dylib
- `whisper-runtime/bin/` 內需有 `whisper-server`

### 取得本機推理 runtime

```bash
cd llama-runtime && ./fetch-runtime.sh    # AI 修正:llama-server + dylib
cd ../whisper-runtime && ./fetch-runtime.sh    # 語音辨識:clone whisper.cpp 原始碼編譯 whisper-server
```

腳本會取得推理程式與本機開發測試用模型。正式 app build 只需要兩個 `bin/`，模型由 app 首次使用時下載。

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
| `whisper-runtime/` | 內嵌本機語音辨識 runtime 與重建腳本 |
| `McBopomofoTests/` | Swift 測試 |
| `package-dmg.sh` | Release build 與 DMG 打包腳本 |

## 重構路線

目前的重構策略是先產品化，再做內部更名。

已完成或正在進行：

- 使用者可見文字改為老王注音。
- README、issue template、安裝器文字產品化。
- GitHub Release + DMG 作為正式發佈入口。
- 停止讓更新檢查導向 OpenVanilla 發佈通道。
- 拆分 AI 校正程式碼:prompt、Claude、本機 server 與 controller 流程已分檔。
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
- whisper.cpp / OpenAI Whisper large-v3-turbo：內嵌本機語音辨識
