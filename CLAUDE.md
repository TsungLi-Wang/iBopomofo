# CLAUDE.md

給 Claude Code 的專案指引。**這份是入口與速查，不是全文**——詳細規範在 `AGENTS.md`，
分領域的細節在 `.claude/rules/`（動到對應路徑時才自動載入）。

> **現役版本不寫在這裡。** 看 `CHANGELOG.md` 最上面的已發布段落，或 `Source/McBopomofo-Info.plist`。
> 說明文件一律不抄版本號 —— 抄了就會漂（2026-08-10 曾漂到五個檔案四種說法）。
> 收工前跑 `./scripts/doc-check.sh` 會自動抓這類不一致。

進來先讀（照順序）：

1. **AI_HANDOFF_PROMPT.md** — 目前狀態與下一棒優先事項（一頁）
2. **docs/dead-ends.md** — 已證明無效的路，**動手前必讀**（兩頁內）
3. **AGENTS.md** — 建置、測試、commit 署名、隱私、引擎規則、收工清單
   - 「同步到 Git」→ AGENTS「同步到 Git」（commit→push→查 CI，分 Stage 回報）。
   - 「正式發布 vX.Y.Z」→ AGENTS「正式發布」（確認 plist／CHANGELOG → annotated tag → push tag → Release workflow）。**禁止**用同步動作去打 tag。
4. **CHANGELOG.md** — 每一版實際改了什麼
5. **docs/decisions/** — 為什麼這樣做、試過什麼。**要動該領域時才讀**
6. **Source/Data/AGENTS.md** — 只有要動 `Source/Data/` 詞庫時才需要

---

## 指令速查

```bash
# 安裝到本機當日常輸入法（開發首選：Installer target 會自動 kill + 重啟輸入法程序）
xcodebuild -project iBopomofo.xcodeproj -target iBopomofoInstaller -configuration Debug build

# 主 target。用 shared scheme，不要用 -target —— 否則 local package 的巢狀
# SwiftPM 依賴（OpenCCBridge／SystemCharacterInfo）在命令列 build 解不出來
xcodebuild -project iBopomofo.xcodeproj -scheme iBopomofo -configuration Debug build

# C++ 引擎測試（configure 一定要帶 -DENABLE_TEST=ON，否則 gramambular2_test 不會生成）
cd Source/Engine && mkdir -p build && cd build && cmake -DENABLE_TEST=ON .. && make && ctest

# Swift 測試（target 名 iBopomofoTests，原始檔目錄刻意仍叫 McBopomofoTests/）
xcodebuild test -project iBopomofo.xcodeproj -scheme iBopomofo

# 收工／發版關卡
./scripts/doc-check.sh          # 文件一致性（版本漂移、repo 外路徑）
./scripts/ship-gate.sh          # 真實語料淨傷害 → 非零就不准打包
./scripts/clean-build-dirs.sh   # 每個 derivedDataPath ≈1.2GB，用完就清
```

**沒有 lint target。** 格式規範是 `.swift-format`（Swift）與既有 C++ 風格，靠 review 不靠工具。

---

## 非顯而易見的坑（跨領域；分領域的在 `.claude/rules/`）

- **`Source/Engine/build-test/` 是被 git 追蹤的 build 產物**：跑過 C++ 測試就會弄髒工作樹。
  發版前要 `git restore` 它，否則 `GitRevision` 會被戳成 dirty（短碼後面多一個 `+`）。
- **不要對同一個 DerivedData 併發跑測試**：PCH 會髒。症狀怪就 `rm -rf` 該 dd 目錄重跑。
- **驗測試輸出不要 `| tail`**：真正的失敗訊息常在中間，尾巴只看得到彙總。
- **測試偶發失敗（輸出全空、字串串到上一句）先重跑一次**再下結論，不要當成回歸擋發版。
- **macOS 限制同一個登入 session 能 kill 輸入法程序的次數**。裝到後來裝不動了 → 登出再登入。
- **重裝輸入法絕對不要 `rm -rf` 舊的 `.app` 再放新的**：app 被刪那一瞬間 macOS 會把輸入源
  踢出選單列（系統設定裡看得到、選單列不見它、`TISSelectInputSource` 會退回 ABC）。
  用 Installer target，或 `ditto`／`rsync` **就地覆蓋**。已經踢掉了 → 重開機。
- **`pbxproj` 新增檔案的 UUID 從 `FACE0123` 起往上取**，沿用既有慣例別亂生。
- **repo 外的必看文件一律不存在**：2026-08-13 起所有必讀都在 repo 內，`doc-check` 會擋
  白名單外的家目錄路徑（白名單只有 `~/Library/`、`~/Documents/i注音-語料/`、
  `~/laowang-data/`、`~/.claude/`，理由寫在 `scripts/doc_check.py`）。
- **`.ai-handoff/` 只放現役派工票與回報**（已 gitignore）。收工時歸檔或刪除，不留隔夜信；
  結論寫進 CHANGELOG／`docs/dead-ends.md`。

---

## 改名之後刻意保留的舊名

內部識別符已於 2026-08-12（棒⑥）統一為 iBopomofo：bundle id `io.ibopomofo.inputmethod.iBopomofo`、安裝路徑 `~/Library/Input Methods/iBopomofo.app`、C++ namespace `iBopomofo`、target／專案檔 `iBopomofo`。

**刻意保留舊名的三類，改到反而是錯**：上游 Copyright 署名（The McBopomofo Authors）、詞庫 on-disk 格式魔術字串（`# format org.openvanilla.mcbopomofo.sorted`）、歷史檔（`AI_HANDOFF_ARCHIVE.md`、CHANGELOG 舊版條目）。
**通則**：凡改一個字串要連帶「改讀取端＋重產資料」的，一律 KEEP —— 那不是改名，是改檔案格式。

---

## 研究線的現況（避免重開已關閉的路）

- **「改善選字」的四條機制線在棒⑭–⑮ 已全部量到上限並關閉，別再開第五條。**
  共同死因：`walkScore` 對 gold 的中位 Δ 是 −1.06，打分器把 gold 擋在出貨的前 10 條
  重排視窗外，搜尋找得再多都沒用。完整表在 `docs/dead-ends.md` B／E 節。
- **六組研究目標只佔真實使用者修正的 12.4%**，87.6% 在六組外（棒⑱，來自真實
  `manual-correction.log`）。拿六組的分數推日常體感是錯的。
- 「現代 IME 應該有 X」這類建議**大多已經有了**（lattice、Viterbi、neural LM、
  context model、personal model、hybrid 加權、規則層、用語正規化）。
  對照表在 AGENTS「選字的四個角色」與 `docs/dead-ends.md`，先查再動手。

---

## 工作方式

- 動手順序：① 先寫下「我要用什麼證據判斷這東西有效」② 確認證據來源 ≠ 機制來源
  ③ 才開始做 ④ `./scripts/ship-gate.sh` 過了才發版。
