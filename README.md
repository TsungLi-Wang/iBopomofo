# 老王注音(McBopomofo + AI 整句修正)

在 [小麥注音(McBopomofo)](https://github.com/openvanilla/McBopomofo) 之上,加一條 **AI 整句修正**岔路:
打完一句注音後按 **⌘ + Return**,把注音引擎依字詞頻率猜出來的整句 + 游標前文丟給 LLM,
回傳修正後的整句(挑對同音字、平翹舌、鄰鍵手誤),直接塞回輸入區。

**預設後端是本機 AI——離線、免 API key、免裝任何外部程式。**
推理引擎(`llama-server`)打包在 app 內;模型(Qwen3-4B-Instruct-2507,~2.9GB)於**首次使用時自動下載一次**
(讓安裝包維持輕量、可直接從 GitHub 下載),之後永久離線。

> 本專案是 McBopomofo 的 fork,**不改動原本的注音引擎**,只在 input controller 層多掛一條 AI 修正路徑。
> 原專案以 MIT 授權釋出,版權與授權見 [`LICENSE.txt`](LICENSE.txt) 與 [`README.markdown`](README.markdown)。

## 功能

- **熱鍵**:`⌘ + Return` 在有輸入內容時觸發整句修正。
- **多後端可即時切換**(輸入法選單 →「AI 修正模型」):
  | 後端 | 說明 |
  |---|---|
  | **本機 AI(內建・離線)** | **預設**。內嵌 `llama-server`;模型 Qwen3-4B-Instruct-2507 首次使用自動下載(~2.9GB,一次性),之後離線、免 API key、校正約 0.3 秒 |
  | Claude Haiku | Anthropic API,快;同音字等語意難題最準 |
  | Claude Opus | Anthropic API,最準 |
  | Codex CLI | 走本機 `codex` 執行檔,免 API key,較慢(需自行裝 codex) |
- **針對注音的校正 prompt**:只修同音字 / 平翹舌 / 鄰鍵手誤,不改寫語氣、不增刪內容。

## 下載與安裝

到[發佈頁](https://github.com/TsungLi-Wang/laowang-bopomofo/releases)下載 `LaoWangBopomofo.dmg`,掛載後:

1. 雙擊 dmg 內的 **`安裝.command`**(會自動清除 Gatekeeper quarantine 並複製到 `~/Library/Input Methods/`)。
2. 到「系統設定 → 鍵盤 → 文字輸入 → 輸入法 → 編輯」加入「老王注音」。
3. **首次**按 `⌘ + Return` 使用本機 AI 時,會自動下載模型(~2.9GB,需連網,一次性,會跳進度通知);
   下載完成後即可使用並永久離線。不想等可先在選單切到 Claude 雲端後端(需自備 API key)。
   模型存於 `~/Library/Application Support/McBopomofo/AIModel/`。

> ⚠️ 本 app **未經 Apple 公證(notarize)**。下載來的 app 會被 macOS 標記 quarantine,
> **若不清除,內嵌的 `llama-server` 一啟動就會被 Gatekeeper 直接 SIGKILL**(本機 AI 後端會無聲失效)。
> `安裝.command` 已代為處理;若想手動,見 dmg 內的「安裝說明.txt」(`xattr -dr com.apple.quarantine`)。

## 設定(所有金鑰與端點都從 UI 填,不必改原始碼)

本機 AI 後端**不需要任何設定**。只有用 Claude / Codex 後端時才需要下列項目。

輸入法選單 →「**AI 修正設定…**」開啟設定視窗,可填:

| 項目 | 預設值 | 說明 |
|---|---|---|
| Claude API key | (無) | **加密存進 macOS Keychain**,不會寫進設定檔、不會進 git |
| Claude 端點 | `https://api.anthropic.com/v1/messages` | 可改走代理 / 相容端點 |
| Claude Haiku 模型 | `claude-haiku-4-5` | |
| Claude Opus 模型 | `claude-opus-4-8` | |
| Codex 執行檔路徑 | `/opt/homebrew/bin/codex` | Intel Mac 或自訂安裝請改這裡 |

留空的欄位會自動使用預設值。要用 Claude 後端,**只需填 API key**,其餘留空即可。

## 從原始碼建置

```bash
xcodebuild -project McBopomofo.xcodeproj -scheme McBopomofo -configuration Debug build
```

推理 runtime(`llama-server` + dylib)不入 git;clone 後先補齊(**建置只需 `bin/`**,模型由 app 執行時自行下載):

```bash
cd llama-runtime && ./fetch-runtime.sh   # 取得 llama-server 與 dylib(也會下載模型供本機開發測試,建置非必需)
```

打包可發佈的 dmg:`./package-dmg.sh`(模型不打包,dmg 僅約 18MB)。完整建置 / 安裝步驟同上游,見 [`README.markdown`](README.markdown) 與 `AGENTS.md`。

## 現況

可日常使用。本機 AI 後端離線即時(校正約 0.3 秒);首次使用一次性下載模型(~2.9GB)後永久離線。

已知限制:**「在/再」這類純語意同音字**,所有本地小模型(含 7B)都不易判對——這是本地模型對雲端的先天差距。
追求極準時可在選單切到 Claude 後端(需填 API key)。

## 致謝

- 注音引擎與整套輸入法框架:[openvanilla/McBopomofo](https://github.com/openvanilla/McBopomofo)(MIT)
- 前文擷取做法參考:[azooKey-Desktop](https://github.com/ensan-hcl/azooKey-Desktop)
- 內嵌推理:[llama.cpp](https://github.com/ggml-org/llama.cpp)(MIT)、模型 [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)(Apache-2.0)
