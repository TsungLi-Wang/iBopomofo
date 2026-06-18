# llama-runtime — 內嵌本機 AI 推理

老王注音的「本機 AI（內建・離線）」後端：把 llama.cpp 的 `llama-server`（OpenAI 相容 HTTP）
連同精簡 dylib 與量化模型一起打包進 app，由 `LlamaServerManager` 自動啟動／關閉。
使用者裝 app 就能離線用，**不必自己裝 Ollama、不必開任何外部伺服器**。

## 內容（皆由腳本重建，不入 git）

| 路徑 | 是什麼 |
|------|--------|
| `bin/llama-server` + `lib*.dylib` | llama.cpp 官方 release `b9692`，精簡到 server 真正依賴的 10 個 dylib（`@loader_path`，adhoc 簽） |
| `models/model.gguf` | Qwen3-4B-Instruct-2507 Q4_K_M（apache-2.0，~2.5GB） |

## 取得 / 重建

```bash
cd llama-runtime
./fetch-runtime.sh
```

Xcode 的「Copy Llama Runtime」build phase 會把這兩者 ditto 進
`McBopomofo.app/Contents/Resources/llama/`（模型大小相同則跳過複製）。

## 模型選型脈絡

Phase 0 用 9 句注音校正測試集（同音字／平翹舌／鄰鍵手誤 + 勿改句）實測比較：

- Qwen2.5-1.5B：太弱。
- Qwen2.5-3B Q5：堪用，但會吐格式標籤、偶有幻覺、輸出简體（曾為預設）。
- Qwen2.5-7B：硬傷案例沒比 3B 好，且 16GB Mac 會 GPU OOM、8GB 不能跑。
- Llama-3.2-**Taiwan**-3B：繁體對但愛聊天、不聽校正格式，出局。
- **Qwen3-4B-Instruct-2507 Q4_K_M ← 目前採用**：指令遵循最佳、原生繁體、零格式洩漏、
  apache-2.0 授權乾淨可發佈。延遲約 0.25s（Apple Silicon）。

> 「在/再」這類最難的語意，所有本地小模型（含 7B）都解不了——追求極致準確度時，
> 使用者可從選單切到 Claude／雲端後端。本機模型定位是「零設定、離線、夠用的預設」。

## Phase 2 待辦

- 模型改 **Git LFS** 進 repo（取代本腳本下載）。
- runtime 從 `Resources/` 移到合規位置（如 `Contents/Helpers/`）+ **Developer ID 簽章 + notarize**，
  才能做成可公開散布、過 Gatekeeper 的 `.dmg`（`Resources/` 放可執行檔對 notarize 不合規）。
