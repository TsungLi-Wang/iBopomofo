# 老王注音(McBopomofo + AI 整句修正)

在 [小麥注音(McBopomofo)](https://github.com/openvanilla/McBopomofo) 之上,加一條 **AI 整句修正**岔路:
打完一句注音後按 **⌘ + Return**,把注音引擎依字詞頻率猜出來的整句 + 游標前文丟給 LLM,
回傳修正後的整句(挑對同音字、平翹舌、鄰鍵手誤),直接塞回輸入區。

> 本專案是 McBopomofo 的 fork,**不改動原本的注音引擎**,只在 input controller 層多掛一條 AI 修正路徑。
> 原專案以 MIT 授權釋出,版權與授權見 [`LICENSE.txt`](LICENSE.txt) 與 [`README.markdown`](README.markdown)。

## 功能

- **熱鍵**:`⌘ + Return` 在有輸入內容時觸發整句修正。
- **多後端可即時切換**(輸入法選單):
  | 後端 | 說明 |
  |---|---|
  | Codex CLI | 走本機 `codex` 執行檔,免 API key,較慢 |
  | Claude Haiku | Anthropic API,快 |
  | Claude Opus | Anthropic API,最準 |
  | 本地 Ollama | 離線、免 API key,需自行裝 Ollama 與模型 |
- **針對注音的校正 prompt**:只修同音字 / 平翹舌 / 鄰鍵手誤,不改寫語氣、不增刪內容。

## 設定(所有金鑰與端點都從 UI 填,不必改原始碼)

輸入法選單 →「**AI 修正設定…**」開啟設定視窗,可填:

| 項目 | 預設值 | 說明 |
|---|---|---|
| Claude API key | (無) | **加密存進 macOS Keychain**,不會寫進設定檔、不會進 git |
| Claude 端點 | `https://api.anthropic.com/v1/messages` | 可改走代理 / 相容端點 |
| Claude Haiku 模型 | `claude-haiku-4-5` | |
| Claude Opus 模型 | `claude-opus-4-8` | |
| Ollama 端點 | `http://localhost:11434/api/chat` | |
| Ollama 模型 | `gemma4:12b` | 需先 `ollama pull` 對應模型 |
| Codex 執行檔路徑 | `/opt/homebrew/bin/codex` | Intel Mac 或自訂安裝請改這裡 |

留空的欄位會自動使用預設值。要用 Claude 後端,**只需填 API key**,其餘留空即可。

## 建置

```bash
xcodebuild -project McBopomofo.xcodeproj -scheme McBopomofo -configuration Debug build
```

完整建置 / 安裝步驟同上游,見 [`README.markdown`](README.markdown) 與 `AGENTS.md`。

## 現況

可用的原型(MVP)。已知限制:**延遲**——所有後端(含本地模型)觸發後到回填都還偏慢,
拿來日常用體感仍不夠即時,屬待優化項目。

## 致謝

- 注音引擎與整套輸入法框架:[openvanilla/McBopomofo](https://github.com/openvanilla/McBopomofo)(MIT)
- 前文擷取做法參考:[azooKey-Desktop](https://github.com/ensan-hcl/azooKey-Desktop)
