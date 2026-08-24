# AGENTS.md

This file provides guidance to AI coding assistants when working with code in this repository.

## Project Overview

iBopomofo (i注音) is a macOS Traditional Chinese Bopomofo input method forked from McBopomofo. It keeps the upstream input engine and adds product features on top: **contextual selection** (corpus word-bigram inside `walk()`, **default on since v2.3.0**), **soft personalization** (user picks feed a private on-device cache into the DP), **neural path rerank** (char-LSTM int8 on sentence-end 定案; architecture family **v2c**, shipping weights **v2d** = 在/再 contrastive micro-tune → `Source/Data/path-char-lstm.bin`), **的/得 particle rule** after walk (`ParticleRuleDisambiguator` + `particle-rules.tsv`), **post-commit delete-and-recompose reselect** (↓ after 定案; verified 1→1 replace since v2.13.3; UOM soft learn since v2.14.0), optional on-device whisper.cpp voice input, and local observability (effective shipping settings + rerank diff log + manual-correction log). The project is built with Swift (UI/state), Objective-C++ (bridge), and C++ (engine), using macOS Input Method Kit (IMK).

Internal identifiers were unified to `iBopomofo` on 2026-08-12 (baton 6), taken while the project still had exactly one (developer) user, so the migration cost was near zero. Deliberately kept as-is: upstream copyright attribution, the dictionary on-disk format magic string, and historical archives. **General rule:** if changing a string would also require changing its reader and regenerating data, KEEP it — that is a file-format change, not a rename.

**Current line:** 現役版本不寫在這裡 —— 見 `CHANGELOG.md` 最上面的已發布段落，或 `Source/McBopomofo-Info.plist`。收工前跑 `./scripts/doc-check.sh` 驗一致性；**發版前**跑 `./scripts/ship-gate.sh`（**CORE＝離線語料＋單元測試**；預設**不**跑實機打字。實機要 `SHIP_GATE_E2E=1`，人在螢幕前自願跑。禁止為「選不到輸入法」重試多輪）。  

### ⛔ 出貨關卡分類鐵則（2026-08-12 · 禁止再混）

| 種類 | 是什麼 | 需要 GUI／輸入法？ | 誰該跑 |
|------|--------|-------------------|--------|
| **CORE**（關卡 1＋2） | 真實語料淨傷害＋引擎 ctest | **否**（純離線） | 每次發版／改選字必跑 |
| **E2E**（關卡 3） | TextEdit 模擬打字 | **是** | 僅 `SHIP_GATE_E2E=1` 且有人在場 |

- `SHIP_GATE_STATUS=CORE`＝可出貨依據（語料齊且 1＋2 過）。  
- `FULL`＝CORE＋E2E 都過。`FAIL`＝CORE 掛，或你強制 E2E 卻掛。  
- **AI 禁止**：因 E2E 選不到 i注音而改腳本／重試／開 TextEdit 纏鬥。那是環境問題，不是選字 bug。  

#### 改了什麼 → 用哪把尺（2026-08-13 補 · 別再拿錯）

| 你改了 | 判準 |
|---|---|
| 規則表／詞庫 | `./scripts/ship-gate.sh` → `SHIP_GATE_STATUS=CORE` |
| **`Source/Data/path-char-lstm.bin`（換神經權重）** | CORE **必要但不足** —— 另跑 `./scripts/model-ab.sh <舊> <新> --items <兩份真實語料>`，看逐題配對（McNemar） |
| UOM 行為 | 隔離的單元測試（自建 `UserOverrideModel` 實例，**不碰全域 cache 檔**） |

⛔ **`ship-gate.sh` 比的是「規則開 vs 規則關」，兩邊用同一個 `path-char-lstm.bin` ——
換權重它抓不到。** 2026-08-13 那個在真實語料上淨傷害 −36（p=4.4e-05）的模型，
照樣跑出 `SHIP_GATE_STATUS=CORE`，數字還跟前一版一模一樣。
**CI 綠燈與 CORE 都不是換模型的判準。**

**Canonical product rule (v2.13.0+):** 定案 ≠ 送出; post-commit ↓ reselect 1→1; **v2.14.0** post-commit correction also feeds UOM soft personalization (one pick → soft active). **v2.15.0** 的/得 結果補語規則. **v2.16.2** 退掉 v2.16.0/1 的六組同音規則與頻率壓縮；留下 particle + v2d.  
Handoff: `AI_HANDOFF_PROMPT.md`（現況、一頁）+ `docs/dead-ends.md`（**動手前必讀**）+ `CHANGELOG.md` + GitHub Issues（`deadend`／開著的 issue）。要動某個領域之前再讀 `docs/decisions/`（為什麼這樣做、試過什麼）。**全部在 repo 內** —— 必看文件不得住在 repo 外（2026-08-13 起）。

**Brand vs technical IDs:** User-visible name is **i注音 / iBopomofo**. Internal Xcode target, bundle id `io.ibopomofo.inputmethod.iBopomofo`, install path `~/Library/Input Methods/iBopomofo.app`. Renamed in baton 6; see CHANGELOG.

**Privacy (local-only plaintext):** `~/Library/Application Support/iBopomofo/rerank-diff.log` (walk→rerank flips) and `manual-correction.log` (user re-picks). Never commit, upload, or attach to crash reports. Toggle/clear via input menu.

## Product UX (canonical — do not reintroduce soft-finalize-as-定案)

Three actions (never collapse them):

| 動作 | 含義 |
|------|------|
| **改字** | Smart reselect / rerank (scoreNBest + pin) |
| **收底線＝定案** | Hard commit: underline gone, text to host app |
| **送出** | Host action (search / chat send / newline) via **another** Enter after 定案 |

| 事件 | 改字 | 收底線 | 送出 |
|------|------|--------|------|
| Enabled trigger: pause / 。 / ， | ✅ | ✅ | ❌ |
| Enter while underlined (composing) | ✅ | ✅ | ❌ (consume key) |
| Enter after 定案 (Empty) | ❌ | — | ✅ (pass key to host) |

**定案後改字 (v2.13.3):** only **delete-and-recompose** — ↓ opens homophone list; on pick, **verified 1→1 replace** (atomic / mark / delete-verify / CGEvent+verify). Fail → beep, **no insert** (never grow the sentence). LINE/Telegram when `selectedRange` unreadable: expected degrade (beep, no edit), not a bug. ←/→ after 定案 always pass-through to the app.

Triggers (prefs panel): pause (+ms, 預設 800), period, comma — each optional. Enter is **not** a toggle.
標準注音鍵位：。＝ `>`，，＝ `<`（v2.13.1 修偵測）。

### 定案後的四個鍵（重選語境）

| 鍵 | 行為 |
|----|------|
| **待修改字** | 游標**右方**那一個字（句尾無右方字時 ↓ 預設改**最後一字**） |
| **←／→** | **app 原生**移游標（不攔截）；↓ 當下再 map 影子 |
| **↑** | 放行；shadow disarm（不追跨行） |
| **↓** | 開該字讀音的同音**單字**清單（不重跑模型）→ 選字 → 驗證 1→1 置換 |

組字中（有底線）仍是一般注音的 ←／→／↓ 原生候選行為，與定案後路徑不同。

置換成功後 **best-effort** 寫入 UOM soft（`noteSoftObservationStrong`：prev＝左方字、
reading、chosen；一次達 count≥2）；寫入失敗不影響已換上的字。組字中的
`fixNode→observe` 路徑不變、不雙算同一次動作。

**校正 log schema v1**（`manual-correction.log`，純紀錄、不回灌）：
`schemaVer \t ISO8601 \t reading \t left_context \t wrong_char \t chosen`

### 重選／定案的程式入口

| 用途 | 檔案 |
|------|------|
| 定案 hard commit | `KeyHandler.mm` → `hardCommitSentence` / `_handleEnter` |
| 停頓觸發 | `InputMethodController.swift` → `fireSentenceEndIdleTimer` |
| 影子 armed / ↓ | `InputMethodController+ShadowReselect.swift`、`ShadowReselect.swift` |
| 選字 1→1 置換 | `PostCommitReselect.replacePendingCharacter` + CandidateDelegate pick |
| 偏好觸發點 | `Preferences.swift` / `PreferencesWindowController` 句子結束分頁 |

### 對使用者說明時的用語

用「定案＝底線消失、字已進 app」「送出＝再按一次 Enter」。**不要**說「停頓只改字留底線」
或「Enter 一下就送出」—— 那是已作廢的 2.12.x 語意。定案後改錯字＝↓ 重選；
改失敗 beep ＝正常 fail-closed，不是 bug。講版本一律去看 `CHANGELOG.md` 最上面那段。

## Version traceability (standing rule — every baton)

This is a **permanent** rule, not a one-off cleanup.

1. Any baton that changes product behavior or user-visible content **must** on close-out:
   - (a) Update `CHANGELOG.md` in plain language (what changed, impact on the user);
   - (b) If the baton is a release point: bump version numbers in **both** `Source/McBopomofo-Info.plist` and `Source/Installer/Installer-Info.plist`, create an **annotated** git tag, tag message includes commit range;
   - (c) Record that version’s **commit range** in CHANGELOG.
2. Version numbers must not stagnate: once behavior-changing work accumulates, do not keep shipping under an old label (anti-pattern: months of work still labeled `2.7.0-dogfood`).
3. Pure research / harness / docs batons need not bump the product version, but still leave an **internal** CHANGELOG line with commit hash.
4. The **maintainer** decides major/minor; executors propose with rationale only.
5. This rule must not be removed or weakened without the maintainer’s explicit approval.

### 收工必更新清單（2026-08-10 新增 — 這條是為了止住「版本敘事漂移」）

**為什麼有這條**：2026-08-10 用一個完全沒有前文的 AI 實測交接文件，發現現役版本在五個檔案裡有四種說法（`CLAUDE.md` 寫 v2.7.0、`AGENTS.md` 寫 v2.14.0、`AI_HANDOFF_PROMPT.md` 自己頂部寫 v2.14.0 但內文寫 v2.13.3、`README.md` 寫 v2.13.3），實際是 v2.15.0。根因是**舊規則只強制更新 CHANGELOG 和 plist，沒有任何一條要求同步「現況」那一層**，所以那一層一路漂。 <!-- doc-check-ignore -->

**發版棒收工時，下列每一項都要更新，缺一不可：**

| # | 檔案 | 要改什麼 |
|---|------|---------|
| 1 | `CHANGELOG.md` | 新版段落（人話 + 版號 + build + tag + commit 範圍） |
| 2 | `Source/McBopomofo-Info.plist` | `CFBundleShortVersionString` + `CFBundleVersion` |
| 3 | `Source/Installer/Installer-Info.plist` | 同上（**兩份都要**，漏掉這份是歷史上最常犯的） |
| 4 | `AI_HANDOFF_PROMPT.md` | 「三行同步狀態」＋下一刀＋（若有）「已排除的路」 |
| 5 | `README.md` | 版本歷程表加一列 |
| 6 | — | ~~CLAUDE.md / AGENTS.md 版本行~~ **已不需要**：它們不再抄版本號 |
| 7 | `./scripts/doc-check.sh` | 跑一次，要全綠 |
| 8 | git | annotated tag（訊息含 commit 範圍）＋ push |

**非發版棒**（研究、harness、文件）只要第 1 項的 internal 條目，其餘不動。

**發版時 `package-dmg.sh` 會自動先跑 `doc-check.sh`，沒過就不打包**（要跳過：`DOC_CHECK_SKIP=1`）。非發版棒收工也建議自己跑一次。它 —— 它會自動抓：現況版本宣稱是否寫死在文件裡、
兩份 plist 是否同步、CHANGELOG 頂部是否對得上 plist、文件提到的檔案是否真的存在、
pbxproj 新檔 ID 起點是否過時、被 git 追蹤的建置產物是否髒了。
上面表格第 4~7 項因此**不用手動維護**：文件不再抄版本號，改成指向 CHANGELOG。

**引擎行為改動額外要求**：在 CHANGELOG 條目裡寫清楚**用什麼資料、怎麼量的、數字多少**。tw538 已作廢。EX1166（難題考卷）與兩份真實語料驗證集已在 `~/Documents/i注音-語料/EX1166-題庫/`；**出貨硬關卡是 `./scripts/ship-gate.sh`**（真實語料不得淨傷害）。EX1166 分數只當難題能力參考，**不得**當唯一驗收或對外宣稱。研究棒仍應在 CHANGELOG 自述量測方法。

**排除的路要寫進 `docs/dead-ends.md`（或 GitHub issue `deadend`）**：試過但行不通的方向，要連同**實測數字**一起記下來，否則下一棒會重試一次。那份是每次進場都要讀的，所以**一條一到三行**，超過兩頁就沒人讀 —— 加新條目時順手砍過期的。

### Clean `GitRevision` on formal builds

The Xcode “Stamp Git Revision” phase writes `GitRevision` = short HEAD hash, and appends `+` only if the **product tree** is dirty (ignores regenerable `Source/Engine/build-test`, `build/`, `dd-test*`).

For a **clean** stamp (no trailing `+`), matching tag `vX.Y.Z`:

```bash
git checkout vX.Y.Z   # or clean master at the release commit
git status            # must show clean for product files
# build Release with a dedicated -derivedDataPath
#
# ⚠️ 用完請跑 ./scripts/clean-build-dirs.sh --yes
# 每個 derivedDataPath 約 1.2GB。2026-08-12 因為沒人清，build/ 底下累積了
# 43 個 dd-* 目錄共 50GB，把 228GB 的碟吃到只剩 6.6GB 跳出系統警告。
```

Menu **「顯示目前生效設定…」** shows `version` + `build` + `GitRevision` from the running bundle.

### 安裝研究 build 當日常輸入法（2026-08-19 棒㉓ 起）

- **就地 `ditto` 覆蓋，絕不 `rm -rf` 再放** —— 會被踢出輸入法選單列
  （`docs/dead-ends.md` F 節）。`scripts/install.sh` 走的是 DMG＋`rm -rf`，
  **不能拿來裝研究 build**。
- **版本號分不出新舊**：研究 build 與已發布版同為當前版號。
  要確認哪個 build 在跑，看已安裝 bundle 內 Info.plist 的 `GitRevision`，
  或 `strings … | grep DecisionCensusLog`。
- ⚠️ **重裝官方 DMG 會靜默換回沒有 instrumentation 的 build，而版本號看不出差別。**

## 架構鐵則：誰做什麼（任何 AI 接手都一樣）

```
維護者說要改什麼
    → AI（Codex / Grok / Claude…）：理解、改碼、本機必要檢查
    → git commit + git push
    → GitHub Actions（寫死、每次一樣）：Build / Test / CodeQL …
    → （下一階才做）tag → Package DMG → GitHub Release
```

| 角色 | 該做 | 不准做 |
|------|------|--------|
| **AI** | 思考、改 code、本機最低驗證、commit、push、**查** CI 結果並照實回報 | 自己決定「今天要不要跑 CI」；把 push 成功說成 CI 通過；未受命就發版 |
| **GitHub Actions** | push／PR 後**固定**跑 workflow 裡寫死的步驟 | 依賴 AI 當下心情 |
| **本機 ship-gate** | 發版前／改選字時的產品尺（CORE） | 拿來替代 CI；E2E 預設不跑 |

**寫死的對應：**

- `push`（改到程式）→ Actions **Build + Test**（+ 條件符合時 CodeQL）—— **不**建 Release
- `tag vX.Y.Z`（且 tag 版號 = plist）→ Actions **Release**（`.github/workflows/release.yml`）→ DMG + GitHub Release

任何新進 AI：**先讀本節 +「同步到 Git」+「正式發布」**；流程不因換模型而變。

## 同步到 Git（sync）—— 標準流程

**觸發語**：維護者說「幫我更新／同步到 Git」「推上去」＝ **commit → push → 查 CI**，三件一組。

⛔ **同步不是發布。** 一句「同步」**不准** bump 版號、不准打 tag、不准跑 `package-dmg` 當發版、不准建 GitHub Release。

### 三階段（回報必須分開講）

| Stage | 做什麼 | 「完成」的意思 |
|-------|--------|---------------|
| **1 本地驗證** | 看 diff、選檔、跑最低必要檢查 | 可以 commit 了 |
| **2 推上去** | commit + push 到 `origin master` | **只代表程式碼上了 GitHub** |
| **3 CI 查核** | `gh run list` / `gh run watch` | 過了這階段才叫「CI 通過」 |

⛔ **Stage 2 成功 ≠ Stage 3 通過。** 禁止把 push 成功說成「已更新完成」「CI 通過」「沒問題了」。
Stage 3 還在跑或沒查，就照實說「執行中」／「未查」。

### 操作清單

```bash
# ---- Stage 1：看清楚要送什麼 ----
git status
git diff                       # 未 staged
git diff --staged              # 已 staged
git log --oneline -5

# 最低必要驗證（依改到什麼而定）
./scripts/doc-check.sh         # 動到文件：必跑，要全綠
# 動到選字／引擎：另跑相關 Swift／ctest；發版前才跑 ./scripts/ship-gate.sh（預設只 CORE）

git add <明確路徑> …           # 逐檔指定，禁止 git add . / -A
git commit -m "type(scope): 中文說明"   # Conventional Commits，見上面那節

# ---- Stage 2：推上去 ----
git push origin master         # 預設分支是 master，不是 main

# ---- Stage 3：查 CI ----
gh run list --limit 5
gh run watch <run-id>          # 失敗時：gh run view <run-id> --log-failed
```

### 哪些改動觸發哪支 CI（路徑過濾）

| Workflow | 檔案 | 何時跑 |
|----------|------|--------|
| **Build**（build + test，macos-15／macos-26 雙矩陣） | `continuous-integration-workflow-xcode-latest.yml` | push／PR 且改到 `*.swift`／`*.cpp`／`*.mm`／`*.m`／`*.h`／`*.xcodeproj/**`（**排除** `Source/Data/**`） |
| **CodeQL Advanced**（swift／cpp／python） | `codeql.yml` | push／PR 到 `master` 且改到上述原始碼或 `*.py`；另每週日排程 |
| **Build phrase database**（`make check` + `make`） | `continuous-build-data.yml` | 改到 `Source/Data/**` |
| **Claude Code Review** | `claude-code-review.yml` →`claude-review-reusable.yml` | 開／更新 PR 時自動 review（fork PR 會跳過） |
| **Claude Code** | `claude.yml` | PR 留言提到 `@claude` 時 |

**只改 `.md` 文件時，上面前三支都不會跑。** 這時 Stage 3 的誠實說法是
**「未觸發任何 workflow」**，不是「CI 通過」。

### GitHub Actions 的定位：品質閘門，不是部署工具

本專案的 Actions **不是 deployment 管道**，而是回歸閘門：每次 push／PR 自動把整套
regression suite 跑一遍，確保先前修好的東西沒被弄壞。目標是「**紅燈＝真的有問題**」
的可信度，不是有跑就好。

**現況（別再說要「導入」）**：`continuous-integration-workflow-xcode-latest.yml`（名稱 "Build"）
就是這個閘門——3 組 C++ 引擎測試 + 6 個 Swift 套件測試 + 完整 Xcode 單元測試
+ Release 編譯 ×2 + 詞庫檢查，macos-15／macos-26 並行，約 10 分鐘。

**唯一缺口**：`ship-gate.sh` 的「真實語料不得淨傷害」關卡**進不了 CI** —— 兩份語料在
維護者本機（未進 repo，隱私紅線），CI 只能跑 SUBSET。**選字品質目前沒有被自動守住**，
仍靠本機跑 ship-gate。這是下一個值得補的洞。

→ 所以 CI 紅了要當回事、當場修到綠，不要放著累積成「反正它一直紅」。

### 安全規則（要違反就先停手問維護者）

- 禁 `git push --force` / `--force-with-lease`（master 是共用歷史）
- 禁 `git reset --hard`、`git clean -fd`、`git checkout -- .`：會吃掉還沒存的工
- 禁 `git add .` / `git add -A`：逐檔指定，避免掃進 build 產物、log、cache
- **永不 commit**：`user-override-cache.dat`、`rerank-diff.log`、`manual-correction.log`、
  `.env`、任何 token 或金鑰（隱私紅線見上面 Privacy 節）
- CI 紅燈 → **回報，不要開「自動改碼再推」的循環**。最多分析原因＋提案，動手要維護者點頭。
- 只在被要求時建 PR；平常直接推 `master`（本專案現行習慣）

### 三態回報文案（照抄，不要美化）

- **綠**：「已 push 到 origin/master（`<hash>`）。CI：Build 通過／CodeQL 通過（run: `<URL>`）。」
- **黃**：「已 push 到 origin/master（`<hash>`）。**CI 執行中，尚未通過**（run: `<URL>`）。」
  ／「本次只改文件，**未觸發任何 workflow**。」
- **紅**：「已 push 到 origin/master（`<hash>`）。**CI 失敗**：`<哪個 job、哪一行>`（run: `<URL>`）。要我分析原因嗎？」

## 正式發布（release）—— 標準流程

**觸發語**：維護者明說「幫我正式發布 vX.Y.Z」／「發版」—— **不是**「同步到 Git」。

```
本機確認 plist = X.Y.Z、doc-check、（建議）ship-gate 有語料時 CORE
    → working tree 乾淨；必要的 release commit 已先同步
    → git tag -a vX.Y.Z -m "…"   # 禁 -f；tag 已存在就停
    → git push origin vX.Y.Z
    → GitHub Actions「Release」workflow
         tag==plist → doc-check → ctest → xcode test(golden) →
         ship-gate SUBSET → package-dmg → GitHub Release
         assets: iBopomofo.dmg + iBopomofo-vX.Y.Z.dmg
```

| 鐵則 | 說明 |
|------|------|
| 版本真源 | **plist**；tag 必須是 `v` + 同一字串。CI **不**改 plist／CHANGELOG 迎合 tag |
| 普通 push | **永不**建 Release |
| FULL 語料 | **不在** Actions 跑；Release notes 必須寫 **NOT RUN IN CI** |
| DMG 檔名 | 固定 `iBopomofo.dmg`（`install.sh`／`releases/latest`）；可另附 versioned 副本 |
| 簽章 | ad-hoc／未公證；notes 照實寫 |
| 禁 force tag | `git tag -f`／`push --force` 一律禁止 |

**AI 發版前檢查清單（缺一停手問維護者）：**

1. `git status` 乾淨（或已明確 commit 完本版）
2. 兩份 plist `CFBundleShortVersionString` = 目標版
3. CHANGELOG 有 `## [X.Y.Z]` 已發布段落（不是只有 Unreleased）
4. `./scripts/doc-check.sh` 全綠
5. （強烈建議）本機有語料時 `./scripts/ship-gate.sh` → `CORE`／`FULL`
6. `git rev-parse vX.Y.Z` 若不存在才 `git tag -a`；已存在 → **停止**
7. `git push origin vX.Y.Z` → `gh run list --workflow=release.yml`
8. 回報分階：tag 已推／Release workflow 執行中或通過／Release URL

Dry-run（不建 Release）：GitHub → Actions → Release → Run workflow，`dry_run=true`，`ref=vX.Y.Z`。

**Runtime:** macOS 10.15 (Catalina) or later

**Development:**
- macOS 14.7 or later
- Xcode 15.3 or later
- Python 3.9 (for dictionary data generation)

## Building and Running

### Xcode Project Structure

The project contains these main **targets**:
- `iBopomofo`: Main input method bundle
- `iBopomofoInstaller`: Installer app (recommended for development)
- `Data`: Dictionary data generation
- `iBopomofoTests`: Swift test suite（原始檔仍在 `McBopomofoTests/` 目錄，目錄名刻意未改）

**Build configurations:** Debug, Release (default when building from command line)

**Available schemes:** iBopomofo, iBopomofoInstaller, Data, plus individual schemes for local packages (BopomofoBraille, CandidateUI, ChineseNumbers, FSEventStreamHelper, InputSourceHelper, NotifierUI, NSStringUtils, OpenCCBridge, SystemCharacterInfo, TooltipUI)

### Primary Development Workflow

1. Open `iBopomofo.xcodeproj` in Xcode
2. Select the **"iBopomofoInstaller"** target
3. Build (⌘+B) and run to install iBopomofo
4. The installer automatically kills and restarts the input method process

**Important:** macOS limits how many times an input method process can be killed in a single login session. If installation stops working after multiple installs, log out and log back in.

### Command-Line Build

```bash
# Build the installer
xcodebuild -project iBopomofo.xcodeproj -target iBopomofoInstaller -configuration Debug build

# Build the main input method. Prefer the shared scheme so SwiftPM nested
# dependencies from local packages (OpenCCBridge/SystemCharacterInfo) resolve
# correctly in command-line builds.
xcodebuild -project iBopomofo.xcodeproj -scheme iBopomofo -configuration Debug build

# Build dictionary data only
xcodebuild -project iBopomofo.xcodeproj -target Data -configuration Debug build
```

### Running Tests

#### Swift Tests
- Target: `iBopomofoTests` in Xcode（目錄仍為 `McBopomofoTests/`）
- Framework: XCTest with Swift `Testing` module
- Run in Xcode with ⌘+U or test navigator

#### C++ Engine Tests
```bash
cd Source/Engine
mkdir build && cd build
cmake -DENABLE_TEST=ON ..
make
ctest
# Or run directly: ./McBopomofoLMLibTest
```

The C++ tests use Google Test framework and are defined in `Source/Engine/CMakeLists.txt`.

### Dictionary Data Generation

Dictionary data must be regenerated when modifying phrase mappings or frequency data:

```bash
cd Source/Data
make all           # Generate data.txt, data-plain-bpmf.txt, associated-phrases-v2.txt
make sort          # Sort all data files using C locale
make check         # Validate data integrity
make tidy          # Clean up formatting
```

**Critical:** Both `BPMFMappings.txt` and `phrase.occ` must be sorted with C locale:
```bash
LC_ALL=C sort -o BPMFMappings.txt BPMFMappings.txt
LC_ALL=C sort -o phrase.occ phrase.occ
```

**For detailed dictionary data documentation**, see `Source/Data/AGENTS.md` which covers file formats, editing workflows, Python tools, and troubleshooting.

## GitHub Copilot Configuration

GitHub Copilot uses `.github/copilot-instructions.md` for its custom instructions. That file references this AGENTS.md for comprehensive context but includes essential guidelines inline since Copilot cannot automatically load AGENTS.md.

For GitHub Copilot-specific configuration, see:
- `.github/copilot-instructions.md` - Repository-wide Copilot instructions
- `.github/instructions/Data.instructions.md` - Path-specific instructions for Source/Data

## Architecture Overview

iBopomofo uses a three-layer architecture (Swift/Objective-C++/C++).

### 選字的四個角色（誰在什麼時候決定用哪個字）

| 角色 | 是什麼 | 何時跑 |
|------|--------|--------|
| **walk** | 詞圖 lattice ＋ Viterbi ＋ 詞庫 unigram/bigram 情境。以**詞**為單位看前後文，是四十年注音輸入法的地基 | 每一次按鍵 |
| **v2c** | 句末小型 char-LSTM，對 walk 的 n-best **路徑**重排。完全離線、約 45ms、int8 | 定案當下跑一次 |
| **節點層規則** | `ParticleRuleDisambiguator`：走完路徑後在**節點既有候選裡**改選，不碰使用者手選。輸入法選單可關（預設開） | walk 之後 |
| **UOM** | 個人化 soft 偏好，進 DP 打分 | 每一次 walk |

- **v2c 是路徑層模型**：它的天花板是「正解那條路徑進不進得了 N-best」。節點層機制（規則、
  未來的神經專家）才看得到節點內的候選。兩者天花板差很多（85.3% vs 95.9%），
  接線位置選錯就白做 —— 見 `docs/decisions/0001-同音消歧不是語言生成.md`。
- **UOM 參數**：`user-override-cache.dat`，capacity 500 LRU、halflife 7 天、
  soft 門檻 count≥2、cap 4.0、μ_user 1.5，userScore＝log10(1+count)（與 PMI 同底），**key ＝ 前詞＋讀音＋詞**。
  當下 hand-pick 永遠壓過 soft。學習很專一（只在該特定前文生效）。
- **`cond`（zenz 式條件模型，讀音當硬約束）是研究線，不出貨**，而且權重是 epoch-1 殘缺品
  （訓練中途崩、bug 已修但未重訓）。所有 cond 數字都在殘缺權重下量的，日後值得乾淨重訓重量。
- 錯誤集中在**高頻字對**（不→部、在→再、是→視、版→板）。85.7 萬真實 hard 位置存在
  `~/laowang-data/`（gold ＝ 語料原字）；用之前要先查與 v2c 訓練語料（中文維基＋PTT 八卦板）
  不重疊，否則是污染。

For detailed architecture and algorithm documentation, see:
- `algorithm.md`: Comprehensive technical documentation (Chinese)
- [Wiki: 程式架構](https://github.com/openvanilla/McBopomofo/wiki/程式架構): Program architecture
- [Wiki: Gramambular 演算法](https://github.com/openvanilla/McBopomofo/wiki/程式架構_Gramambular): Gramambular algorithm

## Key Files Reference

| File | Purpose |
|------|---------|
| `Source/InputMethodController.swift` | Main IMK entry point, coordinates candidate menus and preferences |
| `Source/InputState.swift` | State machine base and all state implementations |
| `Source/KeyHandler.mm` | Objective-C++ bridge; `_walk` mounts CompositeContextModel |
| `Source/LanguageModelManager.mm` | LM + UOM + load/save `user-override-cache.dat` |
| `Source/Engine/UserOverrideModel.{h,cpp}` | Hard suggest + soft personalization index / persist |
| `Source/Engine/CompositeContextModel.{h,cpp}` | `λ·PMI + μ·userScore` for walk DP |
| `Source/Engine/CorpusBigramContextModel.{h,cpp}` | Shipped word-bigram PMI table scorer |
| `Source/Engine/McBopomofoLM.cpp` | Core language model logic and unigram processing |
| `Source/Engine/Mandarin/Mandarin.cpp` | Bopomofo syllable processing and keyboard layouts |
| `Source/Engine/gramambular2/` | Text segmentation algorithms (HMM-based) |
| `Source/Data/Makefile` | Dictionary data build system |
| `Source/Data/AGENTS.md` | Comprehensive dictionary data documentation |
| `algorithm.md` | Detailed algorithm explanation (Chinese) |
| `McBopomofoTests/PreferencesTests.swift` | Example Swift Testing suite patterns |
| `Source/Engine/eval/llm_rerank_poc.py` | Historical PoC harness; its sentence scorer is known-broken (measures next-token probability). Use deferred_rerank_sim.py for new experiments |
| `Source/Engine/eval/deferred_rerank_sim.py` | Deferred neural re-rank simulation with true chain-rule scoring (logit_bias probe); source of truth for L1 neural numbers |
| `Source/Engine/ParticleRuleDisambiguator.{h,cpp}` | 的/得 文法規則消歧（v2.15.0+）；掛在 `KeyHandler._walk` 之後，只在節點既有候選裡改選 |
| `Source/Data/particle-rules.tsv` | 的/得 結果補語規則（**仍出貨**）；六組同音歸納規則已移至 `Source/Engine/eval/artifacts/homophone-rules-failed.tsv` |
| `Source/Data/path-char-lstm.bin` | 出貨神經權重（**v2d int8**；架構 v2c） |
| `Source/Data/confusion-alphas.tsv` | 頻率先驗壓縮表（機制仍在；**條目已清空**，2026-08-11 停用） |
| `scripts/ship-gate.sh` | 出貨 CORE（語料＋ctest）；E2E 預設關。`SHIP_GATE_STATUS=CORE` 可出貨 |
| `Source/ManualCorrectionLog.swift` | 修正事件（分子）：schema v2 帶 `engine_choice`／`event_type`／候選集 |
| `Source/DecisionCensusLog.swift` | 決策普查（**分母**）：每次定案一行純計數，零文字。沒有它錯誤率不可計算 |
| `scripts/correction-census.sh` | 兩個 log 的彙總普查（只印次數與字對，**永不印原文**） |
| `docs/dead-ends.md` | **已證明無效的路，動手前必讀**（兩頁內） |
| `docs/research/` | 外部文獻／方法調查與外勤原始回報。要選下一個機制時才讀 |
| `docs/decisions/` | 決策脈絡：為什麼這樣做、試過什麼。要動該領域時才讀 |
| `Source/Engine/eval/benchmarks/出題管線.md` | 新北極星題庫怎麼生（prompt＋轉換腳本契約） |

## Development Guidelines

### General

- **Never use emoji** in code, comments, documentation, or generated content outside `Source/Data/`. Emoji are permitted only within dictionary data files in `Source/Data` where mappings include emoji.
- **Language restriction:** Use only English or Traditional Chinese. Simplified Chinese is prohibited in all documentation, comments, and reviews.
- **Date/time format:** When noting "last updated" or timestamps in documentation, always use full ISO 8601 datetime in UTC+8 timezone (e.g., `2025-10-12T14:30:00+08:00`). Use the `date` command to get the current system time and adjust to UTC+8 if needed

### Conventional Commits

- **MUST use Conventional Commits format** for all git commits and pull requests
- Format: `type(scope): description`
- Common types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
- Examples:
  - `feat(input): add new keyboard layout support`
  - `fix(engine): correct syllable composition for edge case`
  - `docs(readme): update installation instructions`
  - `refactor(state): simplify state transition logic`
- Keep descriptions concise and in present tense
- **Commit author for this fork (fixed):** `老王 LaoWang <laowang@users.noreply.github.com>`
- See: https://www.conventionalcommits.org/

### Build / DerivedData

- Do **not** run concurrent `xcodebuild` / CMake builds against the **same** DerivedData directory (PCH races). Prefer isolated paths such as `dd-test/`, `dd-rel/`, `build/dd-rel/`.
- Do **not** pipe `xcodebuild test` to `| tail` (hides the real exit / `** TEST SUCCEEDED **` line).
- New `project.pbxproj` file IDs for this fork: **下一個可用是 FACE033A+**（已見最高 FACE0339）。加新檔前先 `grep -o "FACE0[0-9A-F]\{3\}" iBopomofo.xcodeproj/project.pbxproj | sort -u | tail -1` 確認，撞號會讓專案檔開不起來。
### Swift & AppKit

- Use `Preferences` static properties and property wrappers instead of direct `UserDefaults` access
- Localize all UI strings with `NSLocalizedString("…", comment: "")` and update `.strings` files in `Base.lproj`, `en.lproj`, `zh-Hant.lproj`
- Perform UI work on main thread; use existing helpers/notifications rather than ad-hoc dispatch queues
- Interact with engine through `KeyHandler`/`LanguageModelManager` bridges, not directly
- Keep AppKit/IMKit work in Swift classes with `private`/`fileprivate` scope

### State Machine

- Treat `InputState` subclasses as immutable; always create new state objects on transitions
- Funnel all key handling through `KeyHandler` for consistent state transitions
- Derive UI and candidate lists from state object, not scattered flags
- Extend by adding new `InputState` subclasses with explicit transitions, not booleans

### Objective-C++ Bridge

- Manage C++ object lifetimes in `.mm` files with proper `init`/`dealloc`
- Use `std::shared_ptr` when passing to C++ APIs
- Surface engine capabilities by extending bridge classes and declaring in `McBopomofo-Bridging-Header.h`
- Convert between `NSString` and `std::string` using `UTF8Helper`/`NSStringUtils`, not manual conversion
- Keep bridge methods small: forward to engine, return Foundation types

### C++ Engine

- Follow C++17 style with `std::vector`, `std::unordered_map`, `std::optional`, `std::string_view`
- Place code in existing namespaces: `iBopomofo`, `Formosa::Gramambular2`, `Formosa::Mandarin`
- Reuse blob readers (`KeyValueBlobReader`, `ParselessPhraseDB`, `PhraseReplacementMap`)
- Keep algorithms deterministic and side-effect free; logging stays in Objective-C++ layer
- After a `ContextModel` walk, read path text only via `WalkResult::chosenValueAt(i)` (DP does not mutate nodes)
- User personalization: soft scores in DP (`CompositeContextModel` + `UserOverrideModel::userScore`); private file `user-override-cache.dat` under the user data folder only — **never** bundle, never commit, never upload

### Testing

- **Swift tests:** Use Swift `Testing` module with `@Suite`, `@Test`, `#expect` macros in `McBopomofoTests/`
- **C++ tests:** Add to `Source/Engine/CMakeLists.txt` in `McBopomofoLMLibTest` target, use GoogleTest
- **Mixed tests:** Use Objective-C++ (`.mm`) with bridging header for Swift-C++ interop
- Snapshot/restore `UserDefaults` in tests (see `PreferencesTests.swift`)
- **⚠️ 舊北極星 tw538 已作廢（2026-08），不得再當 gate。** 舊參考值（walk ON 333/537、v2c 387/537）只當歷史。
- **難題尺 EX1166**（`~/Documents/i注音-語料/EX1166-題庫/`，約 5,646 題）：字級同音消歧、pair 加權、train/heldout。工具：`newstar_homophone_eval` + `profile_group_usage.py` / `screen_newstar_batch.py` / `assemble_newstar_batch.py` / `make_newstar_jsonl.py` / `error_taxonomy.py` / `oracle_ceiling`。**分數只量難題能力，不是日常體感。**
- **出貨驗收：** `./scripts/ship-gate.sh` —— **CORE**：真實語料（PTT／X）不得淨傷害 + 引擎 ctest。實機打字是可選 E2E（`SHIP_GATE_E2E=1`），與 CORE 無關。改選字機制時**兩份真實語料都要跑**，且**驗證來源必須與機制來源不同**（已用 EX1166 自驗兩次翻車）。
- **Live end-to-end typing verification (no human needed):** after changing any
  typing-time behavior (L1 rerank, deferred neural rerank, disambiguator, key
  handling, contextual walk, personalization), run `./scripts/e2e-typing-check.sh "<US key sequence>"` — it types
  real virtual key codes into TextEdit through the installed IME and reports
  the committed text. Full method, bopomofo-to-key tables, and pitfalls (must
  use `key code`, never `keystroke`) in `docs/e2e-typing-verification.md`.
  Unit tests alone have missed real-device failures before (v2.1.1); use this
  before telling the user a typing-time change works.

### ⛔ 新增「會寫使用者資料檔」的程式碼（2026-08-19 棒㉓ 踩過）

單元測試會驅動真的 `KeyHandler` commit／選字路徑，所以 log 的寫入端**在 XCTest 下照樣開火**。
棒㉓ 一次測試就往真實檔寫了 17 筆假定案＋2 筆假 correction；回頭查才發現
⑲ 標為「實機驗證」的 4 筆 v2 事件也是測試產物。

**規則**：任何新增寫使用者資料檔的程式碼，第一件事是加防護 ——
`getenv("XCTestConfigurationFilePath")`（既有寫法見 `LanguageModelManager.mm`
的 `LTIsRunningUnitTests`；Swift 側見 `ManualCorrectionLog` / `DecisionCensusLog`
的 `isRunningUnitTests`）。

**驗收方式不是「測試綠」，是比對測試前後檔案的 SHA256 未變。**

### ⛔ instrumentation 的分子不可用 `Node::isOverridden()`（2026-08-19 棒㉓ 踩過）

它對 `kOverrideValueWithHighScore` / `kOverrideValueWithScoreFromTopUnigram`
**兩種都回 true**，所以引擎自己施加的覆寫（UOM 的 `forceHighScoreOverride`、
associated phrases、prefix candidate）也會被算成使用者修正 ——
純被動打字實測跑出 100% 的「修正率」。
要數使用者手選，就在 `fixNodeWithReading` 真的完成手選時明確計數。

**這類語意錯誤只有實機才看得出來，單元測試全綠。**

### Dictionary Data Modifications

For dictionary data modifications, see [Wiki: 詞庫開發說明](https://github.com/openvanilla/McBopomofo/wiki/詞庫開發說明) or `Source/Data/AGENTS.md` for detailed workflows.

## Things to Avoid

- Don't replace AppKit windows with SwiftUI or Combine; runtime depends on NSWindow/XIB
- Don't bypass the Objective-C++ bridge to access engine from Swift directly
- Don't hardcode paths to user data; use preference APIs
- Don't modify large dictionary blobs unless specifically targeting them
- Don't add generic development practices or obvious instructions
- Don't commit `user-override-cache.dat` or any per-user typing memory
- Don't attach a zero-contribution ContextModel when both global table and user soft evidence are inactive (breaks bit-identical fast path)

## Local Packages

The `Packages/` directory contains local Swift Package dependencies:
- `BopomofoBraille`: Taiwanese Braille conversion support for both Unicode and ASCII formats
- `CandidateUI`: Candidate window rendering
- `ChineseNumbers`: Chinese numeral conversion
- `FSEventStreamHelper`: File system monitoring
- `InputSourceHelper`: Input source management
- `NotifierUI`: User notifications
- `NSStringUtils`: String utility functions
- `OpenCCBridge`: Traditional/Simplified Chinese conversion (wraps SwiftyOpenCC)
- `SystemCharacterInfo`: Character information lookup (uses SQLite.swift) <!-- doc-check-ignore -->
- `TooltipUI`: Tooltip display

These are referenced directly by Xcode project, not through Package.swift.

### External Package Dependencies

The project also depends on these external Swift packages (resolved automatically by Xcode):
- `swift-toolchain-sqlite` (1.0.4): Low-level SQLite bindings from Swift toolchain
- `SQLite.swift` (0.15.4): Swift wrapper for SQLite3 <!-- doc-check-ignore -->
- `SwiftyOpenCC` (2.0.0-beta): Swift wrapper for OpenCC (Chinese text conversion)
