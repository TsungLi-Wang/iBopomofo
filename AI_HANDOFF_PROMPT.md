# i注音 交班：現況與下一刀

你是 **i注音（iBopomofo）** 的後續協作開發 AI —— macOS 原生繁體中文注音輸入法，
repo `TsungLi-Wang/iBopomofo`。

> **這份只寫「現在到哪了」與「下一刀」，目標一頁。** 其他東西各有自己的家（見下表），
> 版本號一律不寫在這裡 —— 見 `CHANGELOG.md` 最上面的已發布段落。

## 進場讀什麼（全部在 repo 內）

| 順序 | 讀什麼 | 為什麼 |
|---|---|---|
| 1 | **本檔** | 到哪了、下一刀 |
| 2 | **`docs/dead-ends.md`** | 已證明無效的路。**動手前必讀**，兩頁 |
| 3 | `AGENTS.md` | 建置、關卡、commit 規則、產品 UX、**收工清單** |
| 4 | `CHANGELOG.md` 最上段 | 現役版本與每版改了什麼 |
| 5 | `docs/decisions/` | 為什麼這樣做、試過什麼。**要動該領域時才讀** |
| — | `Source/Data/AGENTS.md`／`algorithm.md` | 改詞庫／深算法時 |

```bash
gh issue list --label deadend --state all   # 已歸檔的死路（新的寫進 docs/dead-ends.md）
gh issue list --label needs-johnny          # Johnny 卡著什麼
gh issue list                               # 目前開著的工作
```

歷史交班日誌在 `AI_HANDOFF_ARCHIVE.md`（**只當歷史，不要照著動手**；真正的歷史是 `git log`）。

---

## 三行同步狀態（2026-08-13 收工）

1. **棒⑧** 已發版（版號見 CHANGELOG 最上段），內容全為測試隔離與 CI 修復，
   **使用者可見行為零變更**；選字邏輯一行未動。
2. **Build workflow（GitHub Actions）已恢復綠燈** —— 兩個根因都修了：
   `whisper-server` 不進 git 但 Build workflow 缺 fetch 步驟；`Create commit comment`
   需要 `contents: write` 權杖。
3. **棒⑩ 已收**：#10 拆詞校正已修；#9 作做坐座淨傷害已還原；#11 假綠燈收斂。
   Johnny 2026-08-13 續裁：句單**保留**「你先坐這裡等一下」（當以後模型變強的指標）；
   吧八巴**先不做**，排進之後的優化。未發版、未 bump、未打 tag。
   `doc-check` 字面版零豁免已否決（`docs/decisions/0006`），別再提。

## 下一刀

**沒有阻塞項。** 動過詞庫／ranking／規則表／模型的棒，收工前仍必須本機跑
`./scripts/ship-gate.sh` 到 `SHIP_GATE_STATUS=CORE`；換權重另做模型對模型逐題配對
（`ship-gate` 比的是規則開／關，抓不到換模型，見 dead-ends）。

可選後備（不要自己開做）：
- **#9 吧八巴**：先驗比作做坐座好；要做從 `~/laowang-data/eval-models/path-char-lstm-spoken-v2d.bin` 起訓，不是 v2c。
- **真實語料進 CI**：只有「常常沒人跑本機 CORE 就當可發版」變成常態時才需要。
  現成 `ship-gate` 搬上 Actions 也守不住換模型。三條路都還沒做：私有語料 repo／加密附檔／去識別子集。

#11 句單已裁保留。中途掉線的最小提案寫在 issue，**沒實作**（驗證需要 `SHIP_GATE_E2E=1`）。

> **whisper-server fetch 這個洞已經補過三次**（`release.yml` `7a05fd79` →
> Build workflow v2.17.1 → `codeql.yml` 2026-08-13 / issue #12）。
> 新增任何會 build `iBopomofo` target 的 workflow，**第一件事就是加 fetch 步驟**：
> `WHISPER_FETCH_BIN_ONLY=1 ./whisper-runtime/fetch-runtime.sh`。
> 漏了會 exit 65，而且症狀看起來像「程式壞了」，不像「少一個檔」。

## 已排除的路

全部集中在 **`docs/dead-ends.md`**。**動手前先讀那份**，別在這裡找。

---

## 工作方式（Johnny 明確指正過的兩件事）

**該派給 grok／codex 的活不要自己扛。** 判準見 `~/.claude/CLAUDE.md` 的五級通行驗證；
粗略地說：**會產出可逐項驗收的清單、而且不是改 code 本身 → 派出去。**
派之前跑 dispatch-guard（機密硬掃），派工票與回報寫在 `.ai-handoff/`（本 repo 已 gitignore）。

**收外部回報要逐項核對再採信。** 上一票 grok 把「刻意保留的真名」
（`McBopomofoLM.cpp`、`McBopomofoTests/`、CMake `McBopomofoLMLib`）報成漏改。

**動手順序**（2026-08-10/11 連續兩次發版又退版的根因不是判斷力，是順序）：

```
① 先寫下：我要用什麼證據判斷這東西有效？   ← 不要跳過
② 確認那份證據的來源 ≠ 機制的來源
③ 才開始做
④ ./scripts/ship-gate.sh 過了才發版
```

**誠信**：數字必須真跑；三狀態分報（app build / harness / deliverables）；
文件與改動同棒更新。
