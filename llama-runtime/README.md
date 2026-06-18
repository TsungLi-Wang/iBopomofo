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

## 發佈（自架站 dmg,不公證）

**決定**:不申請 Apple Developer 帳號($99/年),所以不做 Developer ID 簽章 / notarize。
改成自架站讓人下載 `.dmg`,安裝時用一行指令解除 macOS 隔離。

用 `../package-dmg.sh`(repo 根)產出 `dist/LaoWangBopomofo.dmg`(~2.3GB),內含:
- `McBopomofo.app`(含內嵌 4B runtime)
- `安裝.command`(右鍵→打開即可一鍵安裝)
- `安裝說明.txt`(手動 Terminal 指令,最可靠)

### ⚠️ 為什麼安裝一定要清 quarantine(已實測)

下載的檔案會被標 `com.apple.quarantine`。實測(adhoc 簽、未公證)A/B:
- **保留 quarantine** → 內嵌 `llama-server` 一 exec 就被 Gatekeeper **SIGKILL**(log 全空、AI 修正啞掉)。
- **`xattr -dr com.apple.quarantine` 清掉同一份** → server 正常(health 200)。

所以安裝步驟**必須**清 quarantine(`安裝.command` 與手動指令都會做):
```bash
xattr -dr com.apple.quarantine ~/Library/Input\ Methods/McBopomofo.app
```

### 未來若要「免指令、雙擊即用」

唯一乾淨解仍是 **Apple Developer ID 簽章 + notarize**(需付費帳號);屆時 runtime 還要從
`Resources/` 移到合規位置(如 `Contents/Helpers/`,`Resources/` 放可執行檔對 notarize 不合規),
模型可改 **Git LFS**(注意 GitHub 免費 LFS 僅 1GB,2.5GB 模型需付費 data pack——或維持本腳本從 HF 下載)。
