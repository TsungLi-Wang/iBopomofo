# 版本更新歷程

本檔記錄i注音的版本變更。格式參考 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)，版本號遵循 [語意化版本](https://semver.org/lang/zh-TW/)。

正式發佈與 DMG 下載位於 [GitHub Releases](https://github.com/TsungLi-Wang/iBopomofo/releases)。

**版本可追溯（常設）**：每個正式版本段落必須標 **commit 範圍** 與（若有）**tag**。打字行為或使用者可見改動的棒，收尾須更新本檔人話條目；發布點須遞增版本號並打 annotated tag。詳見交接檔卷一「版本可追溯鐵則」、`AGENTS.md`。

## [Unreleased]

### 內部（棒⑨ · 2026-08-13）：文件架構重整。**零程式碼變更、不發版**

多個 AI 輪流開發同一個專案時，文件架構是成敗關鍵。這一棒把它按**變動頻率**分層，
並拔掉「必看文件住在 repo 外」這個結構性問題。

- **新增 `docs/dead-ends.md`** —— 已證明無效的路全部集中（原本散在交接檔、
  軍師檔、GitHub Issues、CHANGELOG 退版段），每次進場都要讀，控制在兩頁內。
- **新增 `docs/decisions/`** —— 決策脈絡（為什麼這樣做、試過什麼）第一次在 repo 裡有家。
  五篇：同音消歧不是語言生成／新北極星的尺／真人校正是下一段燃料／天花板與錯誤分層／
  規則層盲區已查清單。
- **`AI_HANDOFF_PROMPT.md` 1,093 行 → 一頁**：只留三行同步狀態、下一刀、進場讀什麼。
  歷史敘事全部移進 `AI_HANDOFF_ARCHIVE.md`。
- **刪除 repo 外的「軍師交接檔」**（`~/Documents/i注音-傳承交接檔.md`）。
  它被三份文件列為必讀卻不在 repo 裡 —— 派外部 AI（`--cwd` ＝ repo 根）看不到、CI 看不到，
  而且 2026-08-13 真的被丟進垃圾桶沒人察覺。內容已拆解入庫；
  對特定個人工作習慣的觀察那節**刻意不進 repo**（本 repo 是公開的）。
- **`doc-check` 的 `~/` 豁免收窄成可列舉的白名單**。原本是「CI 上所有家目錄路徑都跳過」，
  那個豁免的存在只是為了讓上面那份 repo 外的必讀檔過關 —— **一條必須關掉才能通過的規則
  等於沒有規則**。現在白名單外的家目錄路徑在本機與 CI 都會 fail，並新增「必讀不得指向
  repo 外」的檢查。
- **移除 `llama-runtime/`**：本機 llama 路線在 v2.7.0 已退役，Xcode 的
  「Copy Llama Runtime」build phase 早已刪除、grep 計數 0。相關文件標為歷史。
- 專案內派工緩衝艙 `.ai-handoff/`（已 gitignore，永不入 git）取代原本的家目錄版本。
- **「字面版零家目錄豁免」已否決**（Johnny 裁定，`docs/decisions/0006`）：把路徑改寫成散文
  只是讓檢查器看不見，例外沒消失；而且「必讀不得指向 repo 外」那條檢查也靠反引號，
  改成散文反而更弱。維持四項可列舉的白名單。

## [2.17.1] — 2026-08-13

**build 2325 · tag `v2.17.1` · commit 範圍 `f8cf0486…e2dd474a`（v2.17.0 之後 → 本版）**

### 修復：測試與 CI 品質閘門

> patch bump 的理由：**沒有任何使用者可見的行為變更**。打字、選字、詞庫、
> 個人化、語音全部未動。改的是「測試怎麼隔離」與「GitHub Actions 怎麼跑起來」。

**人話**：這一版你不會感覺到任何差別。修的是自動化檢查——它先前一直是紅燈，
紅燈久了就沒人看，等於白裝一個品質閘門。現在它會真的守門了。

三件事：

1. **「你好」被誤判成「妳好」的測試污染**（不是產品 bug，詳見下方內部段落）。
2. **Build workflow 缺 `whisper-server`**：語音引擎的執行檔不進 git，
   但打包步驟需要它 → 自動檢查每次都在編譯階段就死掉，測試根本沒跑到。
3. **Build workflow 權限不足**：貼覆蓋率統計那步 403，讓整條變紅燈
   （編譯與測試其實全過）。

### 內部（你好／妳好 測試隔離 · 2026-08-12）

- **根因**：`ㄋㄧˇ ㄏㄠˇ` 在**冷 UOM** 下引擎與詞頻仍穩定選「你好」（phrase −5.18 > 妳好 −6.09）。
  CI／本機 KeyHandlerBopomofoTests 變成「妳好」是因為：
  1. `CommitContractGoldenTests` G17/G18 對手選 `candidates[1]`（對 su3cl3 常為「妳好」）
     寫入全域 soft 個人化，並曾 `saveUserOverrideCache` 污染磁碟；
  2. 測試宿主 `AppDelegate` 會 `loadUserOverrideCache`，把開發者本機
     `user-override-cache.dat`（含多次「妳好」soft）灌進單元測試。
- **修復**（不改測試 expectation、不改詞庫／ranking 本體）：
  - XCTest 環境不 load／不 save UOM 檔；
  - `LanguageModelManager.clearUserOverrideModelForTesting`；
  - `KeyHandlerBopomofoTests`／`CommitContractGoldenTests` setUp/tearDown 清冷 UOM。
- **產品**：無 soft 證據時預設仍為「你好」。若本機 soft 已學會「妳好」，需自行清
  `~/Library/Application Support/iBopomofo/user-override-cache.dat` 或對應條目
  （個人化機制本身未廢）。

### 內部（驗收腳本 · 2026-08-12）

- **出貨關卡強制拆開 CORE／E2E**（Johnny 明令：禁止再為「選不到輸入法」纏鬥）：
  - `ship-gate.sh` 預設只跑離線關卡 1＋2 → `SHIP_GATE_STATUS=CORE` 即可作出貨依據。
  - 實機打字（關卡 3）預設**不跑**；要跑才設 `SHIP_GATE_E2E=1`。
  - `type-as-user.sh` 若打出英文鍵序（`ao6g42k7…`）→ 立刻 `FAIL(harness-latin-keys)` 整輪中止，不重試。
- **E2E 根因修復（2026-08-12 晚）**：`TISEnableInputSource` 對**已啟用**的來源會把前台搶成「系統設定」，
  導致 TextEdit 仍用 ABC、打出 `su3cl3`。`select-ibopomofo-ime.swift` 改為**僅未啟用時才 Enable**，
  否則只 `TISSelect`；`e2e-typing-check.sh` 送鍵前確認前台仍是文字編輯。
  實測：`你好`→中文（選字可能為「妳好」）、`我的前女友`→✅；不再出英文鍵序。
- **CI scheme 舊名**：`.github/workflows` 的 `McBopomofo`／`McBopomofoInstaller` →
  `iBopomofo`／`iBopomofoInstaller`（棒⑥ 漏改導致 Build 自改名後一直紅）。
- **Release 自動化**：新增 `.github/workflows/release.yml`（僅 `vX.Y.Z` tag 觸發）＋
  `scripts/extract-changelog-section.sh`。流程：tag==plist → doc-check → ctest →
  Xcode test → ship-gate **SUBSET** → `package-dmg.sh` → GitHub Release
  （`iBopomofo.dmg` + versioned 副本）。普通 push 不發版。
- **doc-check CI**：在 `CI`／`GITHUB_ACTIONS` 下不因 `~/`／`$HOME` 本機路徑不存在而 fail
  （語料、ai-handoff 等）；plist／CHANGELOG／repo 內路徑檢查不變。
- **Build CI 補 whisper-server 取得步驟（2026-08-13）**：`whisper-runtime/bin/whisper-server`
  不進 git，但 iBopomofo target 的「Copy Whisper Runtime」phase 需要它 →
  Build workflow 每次 `xcodebuild test` 都 `cp: No such file or directory` → exit 65。
  `release.yml` 已於 `7a05fd79` 補過同一步且註解預告「既有 Build CI 也會踩同一洞」，
  當時未一併補。現加上 `WHISPER_FETCH_BIN_ONLY=1 ./whisper-runtime/fetch-runtime.sh`
  （只取 bin，不下載 574MB 模型）。

## [2.17.0] — 2026-08-12

**build 2324 · tag `v2.17.0` · commit 範圍 `391a5a6c…v2.17.0`（棒⑥ C1 之前 → 本版）**

### 品牌統一：McBopomofo → iBopomofo

> minor bump 的理由：bundle ID、安裝路徑、資料目錄都變了，屬於**使用者可見的
> 封裝／身分變更**，照「版本可追溯鐵則」不能只 patch bump。
> 沒有引擎或解碼行為變更，因此不是 major。

**人話**：這一版把輸入法的「內部身分」從上游繼承的 McBopomofo 換成自己的 iBopomofo。
你會看到的差別只有一個 —— 輸入法選單裡的**「i注音」是新的那個**；
舊的「小麥注音」可以移除。打字行為、選字、詞庫、個人化設定**完全沒動**，
既有偏好與 548MB 個人資料（含語音模型、校正紀錄）都已原樣搬到新位置，舊的沒刪。



- **內部識別符全面改名 McBopomofo → iBopomofo**。趁專案只有一位開發者使用、
  遷移成本≈0 的窗口一次改乾淨；再有第二位使用者這扇門就關了。

  | | 舊 | 新 |
  |---|---|---|
  | Bundle ID | `org.openvanilla.inputmethod.McBopomofo` | `io.ibopomofo.inputmethod.iBopomofo` |
  | 安裝路徑 | `…/Input Methods/McBopomofo.app` | `…/iBopomofo.app` |
  | 資料目錄 | `…/Application Support/McBopomofo/` | `…/iBopomofo/` |
  | C++ namespace／target／專案檔 | McBopomofo | iBopomofo |

  五階段 commit（`2ce9ecb9` namespace → `7ef06df2` 專案檔 → `185195f5` bundle ID →
  `071c1693` 路徑與偏好 → `c448024d` 文件 → `7c243a6c` install.sh 補漏），每階段 build 綠。

  **資料遷移一律 copy 不是 move，舊的全部保留**：548MB 資料目錄逐檔 SHA256 與行數核對一致；
  偏好因 UserDefaults 以 bundle ID 為 domain 會整組孤兒化，40 鍵逐鍵搬移並驗值相等
  （`PREFS_MIGRATION=PASS`）。

  **KEEP（改到反而是錯）**：上游 Copyright 署名、詞庫 on-disk 格式魔術字串
  `# format org.openvanilla.mcbopomofo.sorted`、歷史封存檔。由此立通則：
  **凡改一個字串要連帶「改讀取端＋重產資料」的一律 KEEP —— 那是改檔案格式，不是改名。**

  ⚠️ **版號未 bump**：使用者可見的封裝／身分變更照鐵則應 minor bump，**major/minor 由 Johnny 決定**。

- **上線（2026-08-12 下午）**：新版已安裝、啟用，成為目前使用中的輸入法
  （`io.ibopomofo.inputmethod.iBopomofo.iBopomofo.Bopomofo`，GitRevision `f2b8eda0`）。
  舊 `McBopomofo.app` 保留但停用。

  **兩個 app 的 zh-Hant 顯示名原本都是「i注音」**（品牌名早於識別符改名），
  在系統設定裡分不出誰是誰。已把舊版顯示名改為「小麥注音（舊）」（僅改本機安裝的
  bundle，非 repo 內容；改後需重新 ad-hoc 簽名）。

  活體層驗收：偏好逐鍵 40/40 **PASS**；實機打字 **9/10**（唯一失敗句已用舊版
  跑同一組鍵序對照、輸出相同，確認非本次迴歸）；校正迴路 (a) 新路徑有寫入、
  (c) 舊路徑零變動皆 **PASS**，**(b) 同前文重打記不住 FAIL** ——
  已查明 `UserOverrideModel` 邏輯此次一字未動（diff 只有 namespace 兩行），
  根因是 `observe()` 的 `breakingUp` 分支用校正後的 walk 組鍵 → **issue #10**。
  尚缺 grok 123 項清單對照。

- **改名漏改補丁**（`7cedea3f`、`72ce840b`）：C4 沒掃到驗收與打包腳本 ——
  `e2e-typing-check.sh` / `type-as-user.sh` 的輸入法檢查與 `pkill` 目標、
  `package-dmg.sh` 的 scheme 與產物路徑。**驗收工具壞掉時不會報錯，只會安靜地不驗。**

  順帶修好 `type-as-user.sh` 本身既有的三個問題：依賴只存在於 `/tmp` 的
  `e2e_slow.sh`（重開機即失效，且錯誤被 `2>/dev/null` 吞掉 → 整輪不印任何東西仍 exit 0）、
  音節間多送空白鍵、TextEdit 既有文件內容混入「實際出字」。 <!-- doc-check-ignore -->

- **獨立驗證方（grok）第二階段對照**：拿改名前產出的 123 項盲測清單對照實改，
  判定 `ZERO_GAP=NO`，補改兩處會**靜默壞**的東西 ——

  1. 安裝器 `kTargetBundle` 還是 `McBopomofo.app`，但同檔其他常數已是新名 →
     **DMG 安裝會把 app 裝成舊名**，然後用新名去檢查／kill／註冊，全部對不上。
     build 綠、測試也抓不到。
  2. `Source/Data/Makefile` 的詞庫部署仍指舊 app 路徑，且用已不存在的
     `-scheme McBopomofo`。

  另補一批「敘述與現況打架」的文件（README／AGENTS／交班檔／algorithm 圖／
  runtime 說明／使用者可見診斷字串）。其中兩處還白紙黑字寫著「不更名內部識別符」。

  grok 誤報而**維持不改**的：`McBopomofoLM.cpp`、`McBopomofoTests/`、
  CMake `McBopomofoLMLib`、`McBopomofo-Bridging-Header.h`、`McBopomofo-Info.plist`
  —— 這些名字現在仍是真的，文件照實描述，改了才會錯。

- **三個住在 `/tmp` 的產物搬進 repo**（重開機會被系統清掉）：
  新增 `scripts/build-eval.sh` 把 ship-gate 的評分機建到 `bin/`；
  `ship-gate.sh` 與 README-newstar 預設路徑一併改。
  README-newstar 的編譯指令原本漏了 `ParticleRuleDisambiguator.cpp`，照抄會失敗，一併補。
  **不放 `build/`** —— `clean-build-dirs.sh` 會把整個 `build/` 刪掉，那只是換一種方式蒸發。

- **兩個「安靜失敗」的驗收工具修好**：`type-as-user.sh` 的計數困在 pipeline subshell 裡，
  全部打錯與全部打對的 exit code 一樣是 0；`ship-gate.sh` 的 ctest 關卡在
  PATH 沒有 cmake 時也印「有測試失敗」。兩者都改成能分辨「沒跑到」與「跑了沒過」。

### 內部（棒⑤ · 2026-08-12 · 可重現性止血 ＋ 定案契約 golden）

- **行為零變更**：未改規則表、模型、alpha、pipeline 預設、KeyHandler 出貨邏輯。
- **A1 評測路徑參數化**：`IBOPOMOFO_CORPUS_DIR` / `IBOPOMOFO_EVAL_BIN`（及
  `IBOPOMOFO_EVAL_MODELS`）；repo 內掃掉 `johnny.w_macmini` 絕對路徑。
- **A2 `ship-gate.sh` 三態**：`FULL` / `SUBSET` / `FAIL`；最後一行
  `SHIP_GATE_STATUS=…`。`SUBSET` 明確標「不足以作為出貨依據」。
- **A3 研究模型搬出**：`Source/Engine/eval/models/*.bin` →
  `~/laowang-data/eval-models/`（SHA256 逐檔一致）；repo 只留 `.sha256`/`.meta.txt`
  索引。**未重寫 git 歷史**。
- **B 定案契約 golden**：`McBopomofoTests/CommitContractGoldenTests.swift` 24 案
  （定案≠送出、period/comma、1→1 reselect、手選壓過、caret 可讀/不可讀），
  每案附 mutation check 會紅；產品碼已還原。
- 回報：`~/ai-handoff/20260812-baton5-report.md`

## [2.16.3] — 2026-08-12

- **版本標記**：`CFBundleShortVersionString` = **2.16.3**；`CFBundleVersion` = **2323**
- **tag**：`v2.16.3`（annotated）
- **commit 範圍**：`2873ac4a..HEAD`

### 這一版使用者會感覺到什麼

打「ㄉㄜ˙」時，引擎多了一個**只在很有把握時才出手**的「的／得警察」。
它絕大多數時候什麼都不做（棄權），只有在少數句法明確的情況才把「的」改成「得」，
例如「哭**得**像豬頭一樣」「喝**得**津津有味」「省**得**開掛過頭」。
設計上寧可漏修也不誤改，所以你原本打對的字不會被它動到。

### 產品改動

- **的／得 警察 v1（棒④）**：以句法規則取代 v0 字元查表。`Source/Data/police-de-v1.tsv`
  （v1得像／v1得津津／v1省得／v1來得好），KeyHandler 改載 v1；v0 檔保留作對照。
  新硬門檻 `de_negative_probe.tsv`（120 句，gold=的）**誤殺=0**；MAIN 全尺 **b=0**、
  的得 **c=5**（1637→1642／**1663**，修資料地基後分母）。τ=HIGH。
  回報 `~/ai-handoff/20260811-baton4-report.md`。
  - ⚠️ **已知且已接受的誤殺（Johnny 2026-08-11 拍板，不是 bug、不要「順手修掉」）**：
    `v1得像` 會把「他畫**的**像很傳神」改成「畫**得**像」。根因是**畫／寫／拍這類動詞
    會拿「像」當受詞**，「V＋的＋像(名詞)」與「V＋得＋像(比較)」在字元層同形，
    而 `v1得像` 的 `L1∈謂語清單` 是**寬鬆正面表列**，擋不住。
    已權衡：保留此條換取「哭得像豬頭一樣」該題（c 由 4→5）。
    重現：見 `~/ai-handoff/20260811-baton4-evidence.md` 的 holdout 測法。
    後續若要收窄，做法是改成**窄白名單**（哭／笑／累／睡／活…不可能帶「像」受詞者），
    不是再往黑名單加字。
- **的／得 警察 v0（棒③ · 已由 v1 取代出貨掛載）**：原 `police-de-v0.tsv` 四條在
  反例探針上全會誤殺（E1：8／15 句）；MAIN 的 b=0 對其中三條無反例可證偽（E2）。
  機制可運作但證據力不足。回報 `~/ai-handoff/20260811-baton3-report.md`。

### 內部 / 開發者改動

- **出貨關卡 `ship-gate.sh` 修三個洞（2026-08-12，發版前抓到）**：
  1. 出貨側只掛 `particle-rules.tsv`，**沒掛 `police-de-v1.tsv`** ——
     等於用「沒有警察」的配置去驗「有警察」的版本，關卡會綠燈但什麼都沒驗到。
     已改為與 `KeyHandler.mm` 載入清單一致，並加註「加規則表時兩邊都要改」。
  2. 語料檔讀不到時原本印「⚠️ 跳過」然後**整支腳本仍印綠燈** ——
     「找不到考卷就自動及格」的關卡比沒有關卡更危險。改為缺料一律 FAIL。
  3. 評分機失敗時不檢查 exit code，`/tmp/gate-*.tsv` 會沿用**上一次**的結果算出
     一個看似正常、實則無關的數字。改為先刪暫存檔 + 檢查 exit code 與非空。
- **MAIN 資料地基（棒④ · 2026-08-11）**：24 筆 `sentence_target_mismatch`（sentence 存
  錯誤形式）改回 gold 可計分；REJECTED 24→0、ITEMS 3371→3395、的得 1647→1663。
  備份 `~/laowang-data/main-scale/backups/MAIN_SCALE.jsonl.pre-baton4`；真實錯誤另存
  `~/laowang-data/observed-errors/OBSERVED_ERRORS.jsonl`（24 筆 heldout，含的得 16）。
  **棒①–③ 在舊分母上的正確率不可與新基線直接比**。
- **棒② 較叫 v2d 式微調（研究 · FAIL · 2026-08-11）**：自 float v2d 只解凍較／叫、
  EX1166 較叫 train×2 對比微調。MAIN in-group `b=7 c=0 FLOOR_PASS=False`；全尺
  3218→3212／3371 顯著淨傷害；`b_other=0`。EX1166 train 較叫升、heldout／MAIN 降。
  **未覆蓋** `Source/Data/path-char-lstm.bin`；候選權重在
  `~/laowang-data/baton2-jiaojiao/`。回報 `~/ai-handoff/20260811-baton2-report.md`。
- **死名單登錄（2026-08-11）**：EX1166-only 當新組 v2d 訓練源 = NO-GO（過擬合考卷、傷
  MAIN）。後續 v2d 訓練源必須與 MAIN 切開；前錢/吧八巴/較叫 v2d-逐組暫停待真實校正資料。
  亦寫入 `AI_HANDOFF_PROMPT.md` 已排除的路、`~/ai-handoff/DEADLIST.md`、傳承交接檔。
- **棒① 歸因儀器／雙尺（eval only，2026-08-11）**：新增
  `Source/Engine/eval/benchmarks/floor_pass.py`（單尾 exact FLOOR；非 compare_dumps）、
  `main_scale_dedup.py`（FP_train exact+8-gram → MAIN_SCALE）、
  `run_dual_scale_baseline.sh`。`newstar_homophone_eval` 增 LINES_READ 與
  rejects 側車檔。定版主尺與基準 dump 在 `~/laowang-data/main-scale/`（不進
  git）。出貨引擎／權重未改。回報：`~/ai-handoff/20260811-baton1-report.md`。
- **文件同步（2026-08-11）**：以本機／git 現役 **v2.16.2** 為準，修正 README、
  AGENTS、AI_HANDOFF_PROMPT 內矛盾敘事（仍寫 tw538 gate、路線 A/B「已出貨」、
  出貨＝純 v2c、EX1166 未建齊等）；README-newstar 改指向出貨 `path-char-lstm.bin`
  （v2d int8）；eval README 標 tw538 為 archive；`path-char-lstm.meta.txt` 更正
  過期的 emb64 描述。產品 code／引擎未改。
- **北極星 EX1166 第一版題庫建成**：6 組 1,410 題（在再/的得/吧八巴/作做坐座/前錢/較叫），
  句子由 grok 生成、機器篩選、詞庫自動標音。工具全在 `Source/Engine/eval/benchmarks/`。
  **首份成績：整體約五成**（的/得 51.1%、吧八巴 47.1%、作做坐座 48.5%、前錢 58.2%、
  在再 64.0%、較叫 66.2%）。分側後規律一致：**高頻字接近滿分、低頻字約兩三成**
  （的 98.3% vs 得 6.6%、做 92.3% vs 坐 18.4%）。
- **自動標音取代人工貼小麥**：`auto_annotate.py` 用引擎詞庫最長匹配標音。
  跟人工貼小麥的 406 句比對，**2,553 音節只差 2 個（0.08%），而且那 2 個是小麥標錯**。
  人工那一步因此拿掉。
- **修掉一個從 v2.15.0 就存在的靜默 bug**：`ParticleRuleDisambiguator::rescoreWalk`
  把路徑攤平成字元時用 `node->value()`，但實際輸出用的是 `chosenValueAt()`。
  後者的優先序是「節點覆寫 > 情境模型 DP 選的 > `value()`」—— `value()` 是
  **最低優先序**。開了情境 walk 與神經重排之後 DP 常常選的不是最高頻候選，
  這時規則看到的字跟使用者看到的**不一樣**，該出手的不出手。

  例：使用者看到「醫師再開藥」（錯），規則看到「醫師在開藥」（已對），於是不動。

  影響：出貨中的「的／得」規則一直在讀錯的文字。修完之後規則層在封存集
  多修 17 題（+53 → +70），誤判還從 7 題降到 6 題。

  **怎麼抓到的**：模擬器（讀真實輸出）與真引擎（讀 `value()`）的數字對不起來 ——
  兩套獨立實作互相對照才逼出來。只有一套的話這個 bug 會一直躺著且看起來正常。

- **同音字文法規則引擎**（`ParticleRuleDisambiguator` 改成讀規則表）：
  封存集 **63.1% → 67.7%**，76 題改對、6 題改壞（出手準確率 92.7%），p<1e-6。
  **六組全部顯著**：的得 56.9%→63.3%、在再 67.3%→71.8%、吧八巴 57.6%→64.7%、
  作做坐座 48.9%→55.6%、較叫 71.7%→73.8%、前錢 68.2%→71.1%。
  規則表 `Source/Data/homophone-rules.tsv`，格式與 `try_rules.py` 相同。
  舊的「的／得」表在載入時合成成通用規則，引擎只留一套判斷路徑。

  **規則有兩條來源，實測互補**：
  * `induce_rules.py` 從 train 統計歸納 —— 贏在 在再／吧八巴／前錢（規律是搭配，數得出來）
  * 派 grok 做語法分析 —— 贏在 作做坐座／較叫（規律是結構：姿勢補語、量詞、祈使句型）
  * 作做坐座 那組統計方法在支持度門檻拉高後一條規則都不剩，完全靠語法分析

  **支持度門檻是 12，不是 5。** 5 的版本 train 出手準確率 98%、封存集掉到 85%
  （低支持度規則過擬合），而且實機打「轉彎前要坐穩」會被一條 support=8 的規則
  改成「要做穩」。門檻提到 12 之後封存集少賺 1.6 分、準確率回到 89.8%。
  把使用者本來打對的字改壞，比沒修好還糟。

- **新工具（`Source/Engine/eval/benchmarks/`）**：
  * `induce_rules.py` — 從 train 挖規則，三種收規則準則
  * `try_rules.py` — 不編譯引擎就能試跑規則表，幾秒鐘報救回／改壞
  * `compare_dumps.py` — 兩份逐題結果做 McNemar 配對檢定
  * 評分機加第 10 參數（規則表），dump 加 `segments` 欄（walk 斷詞）

- **`scripts/e2e-typing-check.sh` 的已知限制**：一次送出所有按鍵，長句會被輸入法漏掉
  （14 鍵的句子出「先去澳奧啊」，ㄅ／ㄉ被吃掉）。要逐音節送、中間 delay 0.35s。

- **讀了〈中文混淆字集應用於別字偵錯模板自動產生〉（2009）**，逐項評估寫在
  `README-newstar.md`。結論：同形字那半不適用（我們是注音輸入法）；
  根號檢定的洞見對但公式在我們的尺度會變鬆（實測 88% vs 98%）；
  斷詞過濾在我們身上分不出好壞（救回與改壞的跨邊界比例只差 7~9 個百分點）。

- **題庫擴到 5,646 題（封存集 1,521），路線 A 因此得以證實**：
  第一版 1,410 題的封存集只有 301 題、雜訊 ±3%，跟要量的改進一樣大 ——
  這正是舊北極星 tw538 死掉的病根。擴充後改用逐題比對＋McNemar 配對檢定。

  **同音頻率先驗壓縮（路線 A）確認有效**（`ReadingGrid::setConfusionAlphas`
  ＋`Source/Data/confusion-alphas.tsv`，跟著 `EnableNeuralPathRerank` 預設開啟）：
  封存集 **59.9% → 62.6%**（84 題改對、43 題改錯，p=0.0004）。
  **效果集中在兩組** —— 在再 55.0%→67.3%、作做坐座 40.0%→48.9%（皆 p≈0.0004）；
  前錢是雜訊、的得幾乎無效果（壓縮解不了「的／得」，只有文法規則有效）。
  `ㄐㄧㄠˋ`（較叫）兩邊都是負的，已從表中移除。
  跑對照組（不給 alphas）確認與加這段程式之前逐位相同。
- **評分機新增兩個參數**：第 8 個是 alphas 表路徑（不給就完全不套用），
  第 9 個是逐題結果輸出檔。**兩次結果比對才知道「淨進步 N 題」底下是
  「+50/−9」還是「+300/−259」** —— 只看總分會把這兩件事當成一樣。
- **題庫不再砍到每字等量**（`assemble_newstar_batch.py --balance keep-all`）。
  剔掉送分題之後「作」只剩 31 句 —— 那是語言事實（該字幾乎只出現在固定詞裡），
  硬要等量會讓 8,255 句塌到 3,000。代價：成績要看**每字準確率的平均**（macro）。
- **封存集零汙染**：`make_newstar_jsonl.py --train-only` 把「調機制時看過的句子」
  釘在 train。現在封存集 100% 是規則凍結之後才生成的句子。
- **簡體字硬擋**：生成端偶爾會漏（一輪 5,652 句混進 5 句）。詞庫是純繁體，
  拿它當篩子最準，不必外掛 opencc。
- **組別定義修正**：原本從詞庫「讀音→字」表建組，會把罕用讀音的字湊成一組。
  已刪 那/哪（不同音：那 ㄋㄚˋ、哪 ㄋㄚˇ）、前/錢/乾 縮成 前/錢（乾讀 ㄍㄢ）、
  覺/較/教/叫 縮成 較/叫（覺得讀 ㄐㄩㄝˊ、教書讀一聲）。
  `screen_newstar_batch.py --reading` 現在會在配注音**之前**擋掉讀音對不上的句子。

## [2.16.2] - 2026-08-11

**退掉 v2.16.0／v2.16.1 加進去的同音字機制。** 它們在我們自己出的考卷上
看起來有效，在真實文字上是淨傷害。

### 為什麼

那份 5,646 題的考卷是 AI 生成的，而機制（規則、頻率壓縮）又是從那份考卷
歸納出來的 —— 等於用同一個模型的語言直覺自我驗證。

補做兩份**真實語料**驗證（PTT 5,905 題、X 2,678 題，來源與考卷無關）之後：

| 機制 | 自己出的考卷 | 兩份真實語料合計 |
|---|---|---|
| 歸納規則（六組 70 條）| 救 134、壞 1 | **救 3、壞 27** |
| 頻率壓縮（四個讀音）| 大幅進步 | **沒有一個站得住** |

實際會遇到的錯誤：

```
前女友        → 錢女友        沒事的我找到診所 → 沒事得
信長的全盛時期 → 信長得        都在找哪間飯店   → 都再找
我們結婚吧到底 → 結婚巴        根本沒在畫圖     → 沒再畫圖
```

輸入法本來全都是對的，是那些機制把它們改壞的。

### 這一版留下什麼

- **「的／得」文法規則**（v2.15.0 那條）：從 85 萬句真實語料抽 40 例人工核對
  出來的，在兩份真實語料**一次都沒誤開火**
- **v2d 模型**（只重訓「在／再」兩個字的 1,538 個參數）：兩份真實語料都正向
  （PTT +6、X +4）

留下來的兩樣，共通點是**驗證來源與製作來源不同**。

### 新增：出貨關卡

`scripts/ship-gate.sh` —— 三關沒過就 `exit 1`，打包腳本不會執行：

1. 真實語料不得淨傷害（兩個獨立語域）
2. 引擎單元測試全過
3. 實機打字抽驗全過

**難題考卷的分數只印出來參考，不當關卡。**

## [2.16.1] - 2026-08-11

**修正 v2.16.0 在日常打字上的退步。**

v2.16.0 用 5,646 題難題考卷驗證，數字很漂亮。但那份考卷**刻意排除了
「詞庫就分得開」的送分題**，而日常打字裡送分題佔絕大多數 ——
所以它量不到「本來就對的字被改壞」這件事。

補做了 5,905 題**真實語料**驗證（來源與難題考卷完全無關），發現 v2.16.0
的規則層在日常文本上是**淨負面**的，而且錯得很明顯：

```
前女友        → 錢女友
前世因果      → 錢世因果
信長的全盛時期 → 信長得
到底是多爛的人 → 多爛得人
我們結婚吧到底 → 結婚巴
裝睡的人叫不醒 → 較不醒
```

引擎本來全都是對的，是規則把它們改壞的。

### 這一版做了什麼

拿掉 6 條「在難題考卷有效、在日常文本造成可見傷害」的規則。

|  | v2.16.0 | v2.16.1 |
|---|---|---|
| 日常文本（未參與修剪的 2,986 題）| 92.46%　救 39 / **壞 39** | **92.67%**　救 28 / **壞 22** |
| 難題考卷（EX1166 封存集）| 68.8% | 66.5% |

日常打字從淨零轉為淨正，可見傷害少了 44%。代價是難題考卷少修約 35 題。
**這個交換是刻意的**：把「前女友」改成「錢女友」是使用者一眼看到、
會失去信任的錯；沒修好一個難題則是無感的（使用者本來就得自己改）。

被拿掉的規則裡有一條在難題考卷貢獻 +62 題 —— 但它在日常文本壞 10 題、
一題也沒救到。

判準是「**任何規則在自然文本上不得淨傷害**」。選這條不是因為它剪得多，
而是因為**它不需要挑門檻** —— 試過「壞 ≥3」「沒救到且壞 ≥2」，
每次都有某句剛好卡在門檻下活下來，那就變成對個別例句調參。

而且修剪必須**反覆做到收斂**：規則是「先命中的贏」，剪掉一條之後下一條會
遞補上來做同樣的事。只剪一輪時「我的前女友 → 錢女友」還在。跑了 3 輪才收斂。

### 錯誤分層表（新工具）

`Source/Engine/eval/benchmarks/error_taxonomy.py` 把剩餘錯誤按「哪一層造成的」分類。
EX1166 封存集剩下的 510 個錯誤：

| 類別 | 佔比 | 該修哪一層 |
|---|---|---|
| **整句解碼錯** | **43.1%** | 目標字被連坐，要修的是整句解碼不是排序 |
| 神經模型偏 | 30.6% | 對比訓練或調 ν |
| 頻率先驗壓制 | 11.4% | 壓縮頻率或節點內改選 |
| 上下文不足 | 8.0% | 加大 N-best |
| 候選沒進來 | 3.1% | 詞庫／候選生成 |
| 斷詞錯 | 3.1% | walk 斷詞 |
| 規則誤開火 | 0.6% | 剪規則 |

**四成三的錯誤根本不是選字問題**（例：「先寄的初稿」被解成「先記得初稿」，
整句都解碎了，目標字只是被連坐）。這類錯不管選字機制做得多好都修不到。

先前說「節點層天花板 95.9%、還有 28 分可拿」是**高估**的 ——
那個數字把整句解碼錯也算成「正解在候選裡只是排序不對」。

### 給後續維護者

**改任何選字機制，兩份考卷都要跑。** 難題考卷量「難題能力」，
真實語料驗證集量「日常體感與誤報率」。兩份都在
`~/Documents/i注音-語料/EX1166-題庫/`。

## [2.16.0] - 2026-08-10

**同音字選字大幅改善。** 用一份 5,646 題的新考卷（封存集 1,521 題）量，
六組常見同音字整體正確率 **59.9% → 68.8%**，每一項都做過對照實驗與配對檢定。

### 打字會感覺到的差別

- **在／再**：55.0% → **79.1%**。「醫師在開藥」「窗簾在送洗」「我明天再去」這類
  以前常選錯的句子現在會對。
- **吧／八／巴**：57.6% → 65.9%。「先去報到吧」不再變成「報到八」。
- **的／得**：56.9% → 63.3%。「看得懂／養得起」那半原本就有規則，
  這次補上統計歸納的部分。
- **作／做／坐／座**：48.9% → 55.6%。「轉彎前要坐穩」不會被改成「要做穩」。
- **較／叫**：71.7% → 73.8%。**前／錢**：68.2% → 71.1%。

### 三層機制（互相獨立，各自量過）

1. **同音頻率先驗壓縮**（`confusion-alphas.tsv`）：同音字之間的詞頻差可到上百倍，
   壓平之後上下文才有機會決定。封存集 59.9% → 63.1%（p=0.0004）。
2. **文法規則**（`homophone-rules.tsv` ＋ `ParticleRuleDisambiguator`）：
   走完路徑後用「只看前後幾個字」的規則修正。63.1% → 67.7%（p<1e-6）。
   規則有兩條來源且實測互補 —— 統計歸納贏在在再／吧八巴／前錢，
   語法分析贏在作做坐座／較叫。
3. **同音字對比微調**（模型 v2d）：只重訓「在／再」兩個字的 1,538 個參數
   （全模型 0.016%），訓練目標從「這句順不順」改成「這兩個字哪個對」。
   67.7% → 68.8%（p=0.00014），其他五組完全不受影響。

### 修掉的 bug

- **`rescoreWalk` 一直在讀錯的文字**（v2.15.0 就存在）：把路徑攤平成字元時用了
  `node->value()`，但實際輸出用的是 `chosenValueAt()`，後者優先序更高。
  開了神經重排之後兩者常常不同 —— 規則看到的字跟使用者看到的不一樣，該出手時不出手。
  修完規則層在封存集多修 17 題。

### ⚠️ 這些數字量的是「難題上的能力」

上面的百分比全部來自 EX1166 —— 那份考卷刻意排除了「詞庫就分得開」的送分題，
所以它量的是難題能力，不是日常打字的體感。

另外曾用 1,635 題真實語料估過日常體感，得到「+0.8」—— **那個數字是錯的**。
2026-08-11 把樣本擴到 5,905 題後方向翻轉為 **−0.2**（救 68、壞 80）。
1,635 題的信賴區間太寬，當時不該拿它下結論。已於 v2.16.1 修正。

**兩個數字都是真的，量的是不同東西。** 詳見 `AI_HANDOFF_PROMPT.md` 第一節。

### 內部

- 新考卷 EX1166 v2：5,646 題、封存集 1,521 題，取代作廢的 tw538
- **獨立驗證集**：1,635 題真實語料句，用來量日常體感與誤報率
- `ParticleRuleDisambiguatorTest` 補 4 個 `rescoreWalk` 測試（含「使用者手選之後
  規則不准改回去」——那段防護程式一直沒有測試涵蓋）
- 新工具：規則探勘、規則試跑器、配對檢定、oracle 上界、語料乾淨度審計、
  模型讀寫與對比微調（全在 `Source/Engine/eval/`）
- 驗證：引擎測試 145 項、doc-check 97 項、e2e 實機打字

## [2.15.0] — 2026-08-10

- **版本標記**：`CFBundleShortVersionString` = **2.15.0**；`CFBundleVersion` = **2313**
- **tag**：`v2.15.0`（annotated）
- **commit 範圍**：tag `v2.14.0` → 本版 tag

### 使用者可感知的改動

- **「的／得」文法自動修正**：打「看的懂」「養的起」「打的過」會自動變成「看得懂」「養得起」「打得過」。

  為什麼要做：輸入法原本只看字詞常不常用，而「的」比「得」常見約 180 倍，所以只要兩個字都合法，永遠選「的」。實測**該打「得」的句子只選對 12%**。這不是模型不夠聰明——是引擎裡沒有「這樣不合文法」這個概念，再多統計層都追不回 180 倍的差距。

  怎麼修：在走完選字路徑之後加一道文法檢查，規則是「動詞 ＋ ㄉㄜ˙ ＋ 結果補語 → 得」。真實語料抽 40 個實際案例，**39 個正確**；平均每打一萬字出手一次。

  **不會亂改**：「我的書」「真的很好」「唱的歌」都不動；你自己手選過的字、個人化偏好選過的字一律不碰；沒把握就完全不出手。

### 內部 / 開發者改動

- 新增 `Source/Engine/ParticleRuleDisambiguator.{h,cpp}` ＋ `Source/Data/particle-rules.tsv`（324 個動詞／形容詞、10 個結果補語、46 個禁改詞、579 個名詞護欄）。掛在 `KeyHandler._walk` 之後，只用 `selectOverrideUnigram` 在節點既有候選裡改選（不生成新字）、不碰 `isOverridden()` 的節點、不回寫 UOM。表檔壞行略過不丟例外。
- 資料來源全部可重現、授權乾淨：動詞取自詞庫自己的「X得」詞條；補語與名詞護欄用無歧義錨點從語料挖（「很/太/超 + X」→ X 是形容詞；量詞 + X → X 是名詞）。**沒有用語料的「的/得」用字當標準答案**——實測語料裡「跑的很快」643 次 vs「跑得很快」875 次，四成的人寫錯，拿它當 gold 會學到錯的。
- **刻意只做「結果補語」半邊**（得到／得住／得起／得懂／得過／得贏／得上／得及）。程度副詞半邊（得很／得超／得太）實測誤判兩成 —— 「這種**的**很陽春」「原始林裡**的**超兇宅」會被改壞，因為那個「的」是把前面變成名詞用的，光看前後幾個字分不出來。留到有詞性判斷再說。
- **神經模型解不了這題（已驗證，別再試）**：把詞頻優勢拿掉、只問 v2c「整句哪個順」，59 句測出 66%，該打「得」的只對 9/29 且錯的全選「的」。根因是 v2c 的 PTT 訓練語料本身就有四成寫錯，模型忠實學會了錯的分布。**要修得有乾淨語料，而那不存在。**
- 新增 `ParticleRuleDisambiguatorTest.cpp`（9 個 gtest）。
- 新增新北極星出題管線工具：`profile_group_usage.py`（算某組同音字的真實用法帶）、`screen_newstar_batch.py`、`assemble_newstar_batch.py`、`make_newstar_jsonl.py`（含詞級破音字檢查、決定性 held-out 切分）、`eval/particle_rule.py`（規則原型與清單推導過程）。

### 內部 / 開發者改動（承上，本版一併發布）

- **新北極星評分機骨架**（eval only，引擎／產品未改）：`Source/Engine/eval/benchmarks/newstar_homophone_eval.cpp` + `newstar_sample.jsonl` + `README-newstar.md`。字級同音消歧、pair 頻率加權、train/heldout 分報；出貨 scorer（λ=0.75 ν=0.75 v2c）且 UOM 關閉；與 tw538 並存。
- **README-newstar 固化跑法**（文件）：絕對路徑一行指令、最終出題管線（AI 句→小麥注音→JSONL）、held-out／詞級／worst-first 現況說明。

## [2.14.0] — 2026-08-06

- **版本標記**：`CFBundleShortVersionString` = **2.14.0**；`CFBundleVersion` = **2312**
- **tag**：`v2.14.0`（annotated）
- **commit 範圍**：tag `v2.13.3`（`f4df30b9`）→ 本版 tag（含其後 docs `271d74fb`）
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **定案後改的同音字會被記住**：刪回重組成功後寫入個人化 soft 表（一次達生效門檻）；下次同前文＋同讀音會偏向你改過的字。
- **校正 log 補全**：`manual-correction.log` 記錄左前文、被換掉的錯字、新字（schema v1）；組字中手選 wrong_char 留空。

### 內部 / 開發者改動

- `UserOverrideModel.noteSoftObservationStrong`（合成 observation key，可 save/load）；`LanguageModelManager.noteSoftPersonalization`。
- `completeShadowRecomposePick` 成功後 best-effort 學 UOM（失敗不影響已替換的字）。
- 文件對齊 v2.13.3 條目仍見 git 歷史 `271d74fb`。

## [2.13.3] — 2026-08-05

- **版本標記**：`CFBundleShortVersionString` = **2.13.3**；`CFBundleVersion` = **2311**
- **tag**：`v2.13.3`（annotated）@ **`f4df30b9`**
- **commit 範圍**：tag `v2.13.2`（`66e50f4f`）→ **`f4df30b9`**
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **定案後重選不再「越改越長」**：選同音字時舊字必須先被移除／置換成功才插入新字；刪除失敗則 beep、不插新字（不兩字並排）。
- **四條置換路徑**（驗證成功才算）：atomic `insertText(new, range)` 讀回＝新字 → pull-to-mark → empty-delete 讀回舊字消失再插 → CGEvent 刪除 + ~50ms 讀回驗證；全敗 abort。
- 讀不到 document range 的 app（多數 LINE／Telegram 欄位）：**預期降級**（beep、不改、不疊字），非 regression。
- ↓ 只開同音清單；置換在選字當下完成。

### 內部 / 開發者改動

- **根因**：`ShadowDelete` 對 `insertText("", range)` 無條件回 success；pick 又用 `replacementRange=NSNotFound` 插入 → 舊字留、新字疊。
- pick 改走 `PostCommitReselect.replacePendingCharacter`（含驗證）；`completeShadowRecomposePick`。

## [2.13.2] — 2026-08-05

- **版本標記**：`CFBundleShortVersionString` = **2.13.2**；`CFBundleVersion` = **2310**
- **tag**：`v2.13.2`（annotated）
- **commit 範圍**：tag `v2.13.1`（`de83fb07`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **定案後 ←／→ 不再被吃掉**（LINE／Telegram 等）：`selectedRange` 讀不到或不對齊影子時，方向鍵**全部放行**給 app 原生游標。
- ↓ 重選維持；進重選前不霸佔左右鍵。失準仍 disarm、不誤刪。

### 內部 / 開發者改動

- `tryHandleShadowReselect`：←／→ 預設 `return false`；`canAlignArrowKeysWithHostCaret` 僅作對齊閘門；↓ 時 `mapCaretFromDocumentLocation`。

## [2.13.1] — 2026-08-05

- **版本標記**：`CFBundleShortVersionString` = **2.13.1**；`CFBundleVersion` = **2309**
- **tag**：`v2.13.1`（annotated）
- **commit 範圍**：tag `v2.13.0`（`3fe2b8ae`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **句號／逗號觸發點真正生效**：勾選後打 。／，＝與停頓相同（改字＋收底線、不送出、標點一併輸出）。
- 修正標準注音鍵位：。對應 `>`、，對應 `<`（舊偵測只認 `.`／`,`／字串內「。」，永遠 miss）。

### 內部 / 開發者改動

- `_handlePunctuation`：以 reading 後綴（`.`/`>`/`,`/`<`）＋ top unigram ＋ 組字末字辨識句末標點；finalize 統一走 `hardCommitSentence`。

## [2.13.0] — 2026-08-05

- **版本標記**：`CFBundleShortVersionString` = **2.13.0**；`CFBundleVersion` = **2308**
- **tag**：`v2.13.0`（annotated）
- **commit 範圍**：tag `v2.12.1`（`b3f770a6`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動（行為總則＝唯一真源）

**改字／收底線／送出是三件事。**

| 事件 | 改字 | 收底線(定案) | 送出 |
|------|------|--------------|------|
| 啟用的觸發點（停頓／。／，） | ✅ | ✅ | ❌ |
| Enter（畫面還有底線） | ✅ | ✅ | ❌ |
| Enter（已無底線／已定案） | ❌ | — | ✅ |

- 句子結束＝改字＋hard commit（底線消失、字入 app），**不**觸發搜尋／聊天送出。
- 真正送出＝定案後**再按一次 Enter**。
- 定案後改字＝刪回重組（↓；句尾預設最後一字；失準停用；刪不動 beep）。

### 內部 / 開發者改動

- 作廢 2.12.0/2.12.1 互相打架的停頓語意；`autoRerankComposingSentence` 移除。
- Enter 有底線：`hardCommit` + **return YES**（吃掉 Enter）；無底線：return NO（送出）。
- 停頓／。／，啟用時一律 `hardCommitSentence`。

## [2.12.1] — 2026-08-05

- **版本標記**：`CFBundleShortVersionString` = **2.12.1**；`CFBundleVersion` = **2307**
- **tag**：`v2.12.1`（annotated）
- **commit 範圍**：tag `v2.12.0`（`5a2d872c`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **停頓 ≠ 定案（修正 2.12.0 誤解）**：停頓逾時只做**自動改字（rerank）**，**底線留著、不送出**；可繼續改。
- **Enter 才收底線＋定案＋送出**（一下完成）。
- **。／，預設**只輸入標點、不動底線；可選「觸發一次自動改字」（仍不 hard commit）。prefs schema → **4**（強制 period/comma 預設關）。
- 送出後刪回重組（arm / 句尾 ↓ / 影子單一真源）沿用 2.12.0。

### 內部 / 開發者改動

- 新增 `autoRerankComposingSentence`；pause／。／，改呼叫此 API，不再 hard commit。
- 設定面板文案改為「組字中自動改字」語意。

## [2.12.0] — 2026-08-04

- **版本標記**：`CFBundleShortVersionString` = **2.12.0**；`CFBundleVersion` = **2306**
- **tag**：`v2.12.0`（annotated）
- **commit 範圍**：tag `v2.11.0`（`bf1ce31f`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **單一路徑 β**：取消 soft-finalize「藏底線當定案」中間態。停頓／。／，／Enter → **立刻 hard commit（無底線）**；Enter **一下**送出（文字入 app ＋ 把 Enter 交給 app）。
- **改字只留刪回重組**：有底線＝組字中原生行為；無底線後 ↓ 一律影子讀音刪回重組。不再「有時原生、有時新路」。
- **句尾直接 ↓ 改最後一字**（不必先 ←）；中間字用 ←／→ 移影子游標後再 ↓。
- **刪不動的 app**：beep ＋ log，明確回饋「不支援就地改字」，不再靜默。
- **失準安全**：滑鼠點別處／失焦／新組字／對齊不確定 → disarm，**絕不合成刪除**。

### 內部 / 開發者改動

- P0-a：`armShadowFromLastHardCommit` 改走 `NSArray`／`NSDictionary` 解析，修 `as? [[String:String]]` cast 失敗永不 arm。
- P0-b：↓ 無 pending 時預設 target = 游標左／句尾前一字；CGEvent fallback 句尾用 backspace。
- P1：影子 caret 為單一真源；移除 `syncFromClientCaret` 覆寫影子 + `postArrowKey` 雙軌。
- `hardCommitSentence` 取代 soft-finalize 定案；`softFinalizeSentence` 永 NO。
- PostCommit clawback stub 維持 no-op。

### 內部 / 開發者改動（延續 Unreleased 研究條）

- repo 衛生：擴充 `.gitignore`（Python venv/pyc、訓練產物 `*.ckpt/*.pt/*.pth/*.bin`、實驗 log/out、`dd-*/` DerivedData 模式）；**未**重寫歷史、**未**移除版控中檔案。體積稽核：`.git` ≈ 241 MiB，HEAD 檔案總和 ≈ 238 MiB，粗算歷史殭屍 ≈ 3 MiB（pack 壓縮使差值偏小；最大 blob 多為仍在 HEAD 的模型權重）。
- 同音判別線 GO/NO-GO 量測（純研究）：`eval/tools/measure_homophone_entropy.py` + `homophone_measure.cpp`；`reading2chars` 自 conversion_pairs；tw538 殘餘熵 + 單點翻字 oracle。**結論 NO-GO**（第 2 輪淨增益 −45；出貨仍 387）。報告 `eval/analysis/tw538-single-flip-oracle.md`。
- 同音翻字閘門掃描（棒 A-2，純分析）：全提案 dump + Δ×H 曲面 + 五變體 split-half；V4（walk 融合）對 n-best 空操作；V5 半 oracle held-out ~+8。**判定仍 NO-GO**。產物 `tw538-flip-gate-*.md/tsv`、四格/Fano/位置剖面/句難度。
- 代理判別器上限（棒 A-3）：Qwen2.5-7B-Instruct-4bit（MLX）作上限代理；**有效性閘門未過**（出貨已對位置 75.6% ≪ 96%），T2/T3 依規未跑。結論：通用 instruct LLM **不能**當有效上限代理。報告 `tw538-proxy-judge-report.md`。
- 位置級同音判別器（棒 C 最終版，純研究）：BiLSTM ~13.3M、純淨／混合噪聲各 30 萬筆；四關評估 + split-half + 延遲。**主判準（n-best 重排 held-out）與次判準（單點翻字）皆 NO-GO**；路徑排序遠遜基線 B，重排延遲 ~1.9s/句 ≫45ms。提案 A（判別器路線）正式死亡。報告 `eval/analysis/tw538-position-judge-report.md`；腳本 `position_judge_batonC.py` / `position_judge_eval_fast.py`；權重與資料在 `~/laowang-data/batonC-final/`（不入 app）。
- 辨識語料重訓（棒 D，純研究）：凍結 v2c 架構（emb256/hid512/L2），只換資料；D0 短跑重訓控制 **380/537**；困難樣本加權 2×/5×/10×。最佳 **D1_w2 = 385（相對 D0 +5）→ 判定邊際**；5×/10× 反而掉分。合成跳過。報告 `eval/analysis/tw538-disambig-corpus-report.md`、混淆對表 `confusion-pair-frequency.tsv`；產物 `~/laowang-data/batonD-final/`（不入 app）。

## [2.11.0] — 2026-08-04

- **版本標記**：`CFBundleShortVersionString` = **2.11.0**；`CFBundleVersion` = **2305**
- **tag**：`v2.11.0`（annotated）
- **commit 範圍**：tag `v2.10.1`（`99d644f2`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **刪回重組字重選（hard commit 後也能改）**：hard commit 時記錄每字**實際注音**影子表；↓ 對游標右方字模擬刪除（先 `insertText("", range)`，失敗再 CGEvent forward-delete，需**輔助使用**權限）→ 拉回讀音 → 只開同音清單 → 選完就地插入。
- **失準安全**：滑鼠／焦點／游標離開被追蹤句／開始新打字 → 影子作廢，**絕不合成刪除**。
- 組字中 soft-finalize（停頓／。／，／第一下 Enter）仍可用原生 ←／→／↓ 改字；第二下 Enter 送出（2.10.1）。

### 內部 / 開發者改動

- `KeyHandler.snapshotCharacterShadowUnits` / `lastHardCommitShadowUnits` / `beginRecompose(reading:)`。
- `ShadowReselectSession` + `ShadowDelete`；CGEvent 需 Accessibility（`AXIsProcessTrusted`）。

## [2.10.1] — 2026-08-04

- **版本標記**：`CFBundleShortVersionString` = **2.10.1**；`CFBundleVersion` = **2304**
- **tag**：`v2.10.1`（annotated）
- **commit 範圍**：tag `v2.10.0`（`060d935d`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **Enter 兩下（Option B 正確版）**：
  - **第一下**（組字中）：soft-finalize —— **立刻清底線**、智慧選字、字仍 marked 可編輯、**不送出**、app 收不到 Enter。
  - **第二下**（已定案）：hard commit 文字給 app ＋ **把 Enter 交給 app**（搜尋／聊天送出／換行）。
- 停頓／句號／逗號定案後，**下一次 Enter 即送出**（已在定案狀態）。
- 與舊 bug 差異：舊 bug 是第一下底線沒清；現在第一下必須清底線，只是「送出」在第二下。

### 內部 / 開發者改動

- `_handleEnter`：`!softFinalized` → `softFinalizeSentence`（return YES）；`softFinalized` → commit + return NO。

## [2.10.0] — 2026-08-04

- **版本標記**：`CFBundleShortVersionString` = **2.10.0**；`CFBundleVersion` = **2303**
- **tag**：`v2.10.0`（annotated）
- **commit 範圍**：tag `v2.9.8`（`70a4cd53`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **Option B：送出前字都留在輸入法**。停頓／句號／逗號＝soft-finalize（智慧選字、底線淡化、**仍 marked 可編輯**）。
- **定案後改字**走原生組字區：←／→ 移游標（右方一字反白）、↓ 開同音候選、↑ 不攔截為「上移」慣例（組字中吸收）。**不再** post-commit clawback。
- **Enter（2.10.0 初版誤為一下 hard commit；**2.10.1 改為兩下**）：見 [2.10.1]。
- 失焦／`commitComposition` 仍 hard commit 目前 marked 文字。

### 內部 / 開發者改動

- 廢棄 2.9.5–2.9.8 post-commit 攔截（`tryHandlePostCommitReselect` 永 false）。
- NSTextView 腳本驗證 soft-mark 內改字 1→1 與 Enter commit。

## [2.9.8] — 2026-08-04

- **版本標記**：`CFBundleShortVersionString` = **2.9.8**；`CFBundleVersion` = **2302**
- **tag**：`v2.9.8`（annotated）
- **commit 範圍**：tag `v2.9.7`（`417afff7`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **修重選疊字**：進重選時用 `setMarkedText(..., replacementRange: 該字 committed range)` **把舊字從 committed 拉進 marked**；確認候選時 `insertText` 替換 mark（一換一）。若拉 mark 失敗則 delete+insert，刪不掉就**不插入**（寧可不動、不多字）。
- 不再依賴「對 committed 文字直接 replacementRange 插入」（多數 app 會忽略而變純插入）。

### 內部 / 開發者改動

- `PostCommitReselect.replacePendingCharacter` / `pullCommittedIntoMark`；NSTextView（TextEdit 同文字系統）腳本驗證 1→1。

## [2.9.7] — 2026-08-04

- **版本標記**：`CFBundleShortVersionString` = **2.9.7**；`CFBundleVersion` = **2301**
- **tag**：`v2.9.7`（annotated）
- **commit 範圍**：tag `v2.9.6`（`a9a62812`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **修重選後舊字沒被取代**：選同音後改為 `insertText(chosen, replacementRange: 待修改字元實際 range)`（優先 `markedRange()`，否則開候選時現查的 document range），**一換一、字數不變**。
- 選完走 `EmptyIgnoringPreviousState`，避免 `Empty` 再把舊 composingBuffer commit 一次（那是「變兩個字」的根因）。

### 內部 / 開發者改動

- `ChoosingCandidate` 記錄 `postCommitDocLocation/Length`；2.9.6 方向鍵行為與 Enter hard commit 不動。

## [2.9.6] — 2026-08-04

- **版本標記**：`CFBundleShortVersionString` = **2.9.6**；`CFBundleVersion` = **2300**
- **tag**：`v2.9.6`（annotated）
- **commit 範圍**：tag `v2.9.5`（`5193f15f`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **修回歸：定案後方向鍵亂動**：post-commit armed 時不再攔截 ←／→／↑。一般導覽 100% 交還 app。
- **重選進入方式**：僅在 **↓** 時進入重選（仍需剛 hard commit 後 armed）；重選中才用 ←／→ 移待修改字元區、↓ 開同音。
- 定位一律 `selectedRange()` 現查，不維護會漂的內部游標。

### 內部 / 開發者改動

- 病灶：① armed 過廣攔截方向鍵（主因）；② 自管位置易 desync（次因）。修法：Empty+armed 只攔 ↓；←／→／↑ 直接 `return false`。

## [2.9.5] — 2026-08-04

- **版本標記**：`CFBundleShortVersionString` = **2.9.5**；`CFBundleVersion` = **2299**
- **tag**：`v2.9.5`（annotated）
- **commit 範圍**：tag `v2.9.4`（`dfd3326b`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **Enter 維持即時 hard commit**（反轉 2.9.4 的 Enter 軟定案）：按一下智慧選字並**直接送出**，底線一次消失。
- **定案後重選字（post-commit）**：hard commit 之後，用 **←／→** 把游標移到錯字左邊（游標右方一字＝待修改區，反白標示），按 **↓** 開同音候選並替換；**↑** 不攔截（仍可上移一行）。替換寫入 `manual-correction.log`。
- **實作**：`NSTextInputClient`／`IMKTextInput` 周邊文字讀取 + 刪除重插；**app-dependent**（TextEdit／多數 Cocoa 欄位通常可用；部分 Electron／網頁框可能不支援 → 不 crash、該 app 只能刪打）。

### 內部 / 開發者改動

- 新增 `PostCommitReselect`、`InputState.PostCommitHighlight`、`LanguageModelManager.homophoneCandidates(forCharacter:)`。
- 停頓／句號／逗號的軟定案路徑保留（組字中）；與 Enter hard commit 分離。
- 註：交接棒原文版號 2.9.3 已占用，本棒 **2.9.5**。

## [2.9.4] — 2026-08-04

- **版本標記**：`CFBundleShortVersionString` = **2.9.4**；`CFBundleVersion` = **2298**
- **tag**：`v2.9.4`（annotated）
- **commit 範圍**：tag `v2.9.3`（`c743a8e2`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **Stage 2 定案後重選字**：停頓／句號／逗號／**Enter** 定案後（底線消失、字仍在組字區）可用 **←／→** 移游標；**游標右方一字**為待修改區（反白標示），按 **↓** 開該字同音候選並替換；**↑** 維持上移一行。每次手動重選寫入 `manual-correction.log`。
- **Enter 改回軟定案（仍只按一下）**：按一下智慧選字並隱藏底線，**不** hard commit；**嚴禁兩段式**（第二下 Enter 不會送出）。真送出改由點到別處／失焦／app 強制 commit。
- **與聊天 app 的衝突（產品取捨）**：IMK 下「保留可重選」與「Enter 即時送出訊息」**互斥**；本版優先 Stage 2 可重選。LINE 等需 Enter 送出時，須先點出組字區讓文字 hard commit，再送出——若要改行為請 Johnny 另棒拍板。

### 內部 / 開發者改動

- soft-finalized 時 `actualCandidateCursorIndex` 強制「游標右側」語意；手動選字後維持 softFinalized 以便連續改字。
- 註：交接棒原文寫 2.9.3，但 `v2.9.3` 已用於選單入口熱修，本棒以 **2.9.4** 出貨。

## [2.9.3] — 2026-08-04

- **版本標記**：`CFBundleShortVersionString` = **2.9.3**；`CFBundleVersion` = **2297**
- **tag**：`v2.9.3`（annotated）
- **commit 範圍**：tag `v2.9.2`（`7dd31e1e`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版不改引擎）

### 使用者可感知的改動

- **定案設定找得到了**：輸入法選單新增 **「定案設定…」**，一點就打開偏好並跳到定案分頁（停頓／毫秒／標點／Enter／手動改字 log）。偏好工具列標籤改為「定案設定」。

### 內部 / 開發者改動

- 偏好視窗統一走 `AppDelegate` 實例，避免 IMK 與 App 各開一扇、工具列不一致。

## [2.9.2] — 2026-08-04

- **版本標記**：`CFBundleShortVersionString` = **2.9.2**；`CFBundleVersion` = **2296**
- **tag**：`v2.9.2`（annotated）
- **commit 範圍**：tag `v2.9.1`（`f51d5b1e`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **Enter 改回一下到底**：按一下 Enter 即智慧選字（若已開）並 **hard commit 送出**；不再兩段式（第一下軟定案、第二下才送出）。想定案後改字請用**停頓／句號／逗號**（仍為軟定案）。
- **句子結束設定搬進偏好視窗**：選單不再塞一整排「句子結束：…」與手動改字 log；偏好工具列新增 **「定案」** 分頁——停頓勾選＋毫秒欄、逗號／句號／Enter 勾選、手動改字樣本開關與清除、顯示生效設定。樣式與其它偏好一致（非 NSAlert）。

### 內部 / 開發者改動

- pref key 沿用（`SentenceEndPauseEnabled` / `SentenceEndPauseMs` / 標點與 Enter 觸發／`EnableManualCorrectionLog`）；schema 不升。

## [2.9.1] — 2026-08-04

- **版本標記**：`CFBundleShortVersionString` = **2.9.1**；`CFBundleVersion` = **2295**
- **tag**：`v2.9.1`（annotated）
- **commit 範圍**：tag `v2.9.0`（`e97ed272`）→ 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **句子結束：停頓**改為可自訂（與 Enter／句號／逗號並列）：
  - **開關**：預設 **開**；關掉後純停頓不再自動定案，標點／Enter 不受影響。
  - **毫秒**：選單「停頓毫秒…」可自填，單位 ms，**預設 800**，**下限 200**。

### 內部 / 開發者改動

- 設定鍵：`SentenceEndPauseEnabled`（default true）；`SentenceEndPauseMs` 讀寫時 clamp ≥200。
- `prefsSchemaVersion` → **3**。

## [2.9.0] — 2026-08-03

- **版本標記**：`CFBundleShortVersionString` = **2.9.0**；`CFBundleVersion` = **2294**
- **tag**：`v2.9.0`（annotated）
- **commit 範圍**：tag `v2.8.0` 之後 → 本版 tag
- **打分**：tw538 仍 **387/537**（本版**不改**選字引擎 walk/v2c）

### 使用者可感知的改動

- **句子結束 → 自動智慧選字定案（軟定案）**：
  - **停頓**（基礎、恆開）：停止輸入超過預設 **800ms**（偏好 `SentenceEndPauseMs` 可調）後，對整段組字做與 Enter 同一條神經重排，定案後**底線消失**但字仍在組字區，還能改。
  - **句號（。）／Enter／逗號（，）** 三個**獨立開關**（狀態列選單可切）：開啟時命中即進入同一套定案。預設：句號開、Enter 開、逗號關。
  - Enter 第一次＝軟定案；**再按一次 Enter**＝真的送出文字。
- **定案後改字**：底線消失後文字仍在組字區；游標移到錯字左前，空白或 ↓ 重選。
- **手動改字回饋**：每次手動選字寫入本機 `~/Library/Application Support/McBopomofo/manual-correction.log`（可關、可清）。

### 內部 / 開發者改動

- 必查結論：舊 Enter 定案＝`insertText` 真 commit；為支援定案後改字，本版定案改為**軟定案**（composing 保留、無底線）。
- 設定鍵：`SentenceEndTriggerEnter/Period/Comma`、`SentenceEndPauseMs`、`EnableManualCorrectionLog`；`prefsSchemaVersion` → 2。

## [2.8.0] — 2026-07-27

- **版本標記**：`CFBundleShortVersionString` = **2.8.0**；`CFBundleVersion` = **2293**
- **tag**：`v2.8.0`（annotated）
- **commit 範圍**：tag `v2.7.0`（`549e4637`）之後 → 本版 tag
- **打分**：tw538 仍 **387/537**（本版不改引擎）

### 使用者可感知的改動

- **品牌更名**：產品對外名稱由「老王注音 / LaoWang Zhuyin」改為 **「i注音 / iBopomofo」**（選單、關於、安裝器、文件）。
- **正式公開開源**：repository 以 MIT 公開；保留上游 McBopomofo 授權與著作權，並新增 [NOTICE](NOTICE) 說明衍生關係。
- **安裝體驗文案**同步為 i注音（內部安裝路徑／bundle id 為相容性**刻意保留**，見 README 技術備註）。

### 內部 / 開發者改動

- 全歷史機密掃描（gitleaks + 人工高風險字樣）：**零真實金鑰入庫**；Claude 時代 API key 僅 Keychain，未 commit。
- 強化 `.gitignore`（`.env`、憑證、`rerank-diff.log`、`.gguf` 等）。
- 公開 README 重寫；版本可追溯鐵則持續適用。

## [2.7.0] — 2026-07-27

- **版本標記**：`CFBundleShortVersionString` = **2.7.0**（去掉 `-dogfood`）；`CFBundleVersion` = **2292**
- **tag**：`v2.7.0`（annotated）
- **commit 範圍**：`v2.6.0`（`51c930c0`）之後 → 本版 tag 所指 commit（含正式正名本棒）
- **產品主線摘要**（行為變更的棒）：
  - `0d9540b6` — 大掃除 + Tab 神經預覽（原 dogfood）
  - `7ee58726` — 內部整頓（打分路徑整理；打字體感不變）
  - `72405791` — 偏好遷移 + 生效設定 + Enter-only 重排差異 log
  - 本版正名 commit — 版本號／CHANGELOG／追溯鐵則（行為不變）
- **打分**：tw538 仍 **387/537**（λ=0.75、ν=0.75）；本系列不改引擎參數

### 使用者可感知的改動

- **記憶體大幅變輕**：拿掉整套本機 llama（Qwen 等）與 Claude 雲端 AI。以前常駐可能吃掉約 **3GB**；現在一般使用落在約 **50MB** 級。活動監視器不應再看到 `llama-server`。
- **刪掉一堆你可能已忘記的 AI 選單項**：AI 候選建議、句末自動校正、⌘Return 整句 AI、AI 神經候選重排、同音消歧、「AI 修正模型」等。**不再**為了這些功能連網或本機跑大模型。
- **Tab 變成「重排預覽」**：組字中按 Tab，用與 Enter **同一條**神經重排看整句會變成什麼，**底線還在、字還沒送出**；不滿意可繼續改，滿意再 Enter。連按第二次不會亂閃。非組字時 Tab 仍交給 App（跳欄位等）。
- **Enter 仍是「重排後送出」**（與 v2.6 出貨線相同）。
- **保留**：情境化選字、神經路徑重排（開關）、語音輸入、輸出簡體／半形標點／聯想詞。
- **選單「顯示目前生效設定…」**：一眼看到版本號、build、GitRevision，以及重排有沒有開、ν、模型指紋等——不必靠手感猜「重排到底有沒有在跑」。
- **選單「記錄重排差異」／「清除重排差異 log」**：只有 **Enter 送出且重排真的改了字** 時，才在本機記一行（walk → 改後）。**Tab 預覽不記**。檔案在  
  `~/Library/Application Support/McBopomofo/rerank-diff.log`  
  （純本機、不上傳；可關可清）。
- **升級更乾淨**：啟動會清掉已移除 AI 功能的舊偏好殘渣，並用可累加的偏好 schema 遷移，降低「舊版 OFF 蓋掉新預設 ON」那類烏龍（v2.6 曾發生過）。

### 內部 / 開發者改動

- 產品 walk 僅走 `scoreNBest`；`scoreSentence` 標為 TEST-ORACLE，並有 nbest≡sequential 的 engine ctest。
- 拆掉已證實幾乎沒槓桿的融合公式／α 掃描可執行面；研究 harness 退役集硬閘（非 537 句 abort）。
- λ/ν 聯合重掃（研究）：控制組仍 387；表上最佳 **391@λ0.70/ν0.50**——**出貨參數未改**，待 Johnny 拍板。
- `prefsSchemaVersion` 可累加遷移（v1 = orphan AI 鍵 purge）；生效設定含 version + GitRevision。
- **Stamp Git Revision**：正式 build 在「產品 tree 乾淨」時不再因 `build-test` 等 cache 髒檔誤加 `+`；完整乾淨標記做法見 `AGENTS.md`。
- **版本可追溯鐵則**寫入交接檔卷一與本 repo 常設文件（本棒）。

### 建議版本號說明（供 Johnny 核可）

- **採用 2.7.0 的理由（本版已依此落地）**：dogfood 本來就叫 `2.7.0-dogfood`，正式化是拿掉尾綴、定錨同一條產品線，不是另開一輪 minor。
- **若改採 2.8.0 的理由**：從 tag `v2.6.0` 算起，中間還疊了制度下沉（diff log／遷移／可觀測）與內部整頓，可視為「2.7 dogfood 之後又一整段」。若 Johnny 要強調這段，可下一棒改號 + retag（不重寫歷史）。
- **最終 major/minor 決定權在 Johnny**；本版以 **2.7.0 / build 2292** 作為建議預設。

## [2.6.0] — 2026-07（tag `v2.6.0`，commit `51c930c0`）

### 使用者可感知的改動

- **神經路徑重排出貨**：Enter 送出時用 v2c 口語 LSTM（int8）重排整句；預設開啟。
- 北極星考卷 tw538 上約 **333 → 387 / 537** 正解（實驗室數字；實機還受個人詞庫影響）。
- 選單可關「神經路徑重排」以回退到只靠情境化選字。

### 內部 / 開發者改動

- 接線候選 A：commit-time gating、`scoreNBest`、override 存活測試 32/32。
- 詳見當日 release 說明與 `analysis/v2.6.0-shipping-wiring.md`。

---

## 更早條目（研究與歷史，濃縮保留）

### 研究里程碑（未全部進 app 出貨）

- **口語 LSTM 階梯**：v1 356 → v2a 362 → v2b 374 → **v2c 387@ν0.75**（停放大）。
- **CondConverter / CondProposer 研究線**：mix 397、約束 400、雙票 401、beam **402**——研究封存，**未**取代出貨 v2c 387 線。
- **char-Transformer 對照**：ppl 更好但 tw538 僅 332——注意力 LM 未贏 PathScorer 融合。

### 北極星 tw538

- **`tw538-northstar.tsv`（537 句）** 為現行唯一裁判。
- 基準：walk OFF **296** / walk ON **333**；出貨 rerank **387@ν0.75**。
- 來源：PTT 生活板真人正文；禁 Gossiping（訓練同源）與 C_Chat。

### v2.3.x–v2.5.x 摘要

- **v2.3**：情境化選字 + UOM 個人 soft 預設出貨。
- **v2.4–v2.5**：n-best / PathScorer 基建；實驗 LSTM 預設關。
- 隱私：個人化檔只在  
  `~/Library/Application Support/McBopomofo/`，不進安裝包、不上傳。

---

## 歷史研究與實驗詳細紀錄（archive，未全部出貨）

### 北極星切換（評測集）

- **`tw538-northstar.tsv`（537 句）** 取代 `tw538-northstar.tsv`成為預設北極星。
 - 來源：PTT 十個生活板實爬正文（Stock / PC_Shopping / Tech_Job / WomenTalk / movie / Food / Lifeismoney / Soft_Job / MobileComm / car）；**禁** Gossiping（訓練同源）與 C_Chat（圈內梗）。
 - 過濾：大陸／港澳用語、板規殘片、政治、NSFW 等；Johnny 人工逐句終審。
  - **tw538 基準線（2026-07-14）**：walk OFF **296/537**；walk ON **333/537**；口語 LSTM n-best best ν=0.5 **356/537**；約束重搜 fusion **335/537**（BREAKTHROUGH_GREEDY=3）。

### 實驗 / 診斷（未發版）— LSTM 階梯 + Transformer 對照（2026-07-14→15）

- **口語 LSTM 階梯**（Gossiping han≈77.8M；N=10）：v1 **356** → v2a **362** → v2b **374** → **v2c 387@ν0.75**（9.73M，~730ms）。容量斜率遞減，停放大。
- **REGRESS-26 驗屍**（v1 對、v2b 錯 → v2c）：**11/26 自癒**、**15 仍錯**（80% single_char，全 in-pool）。

### 實驗 / 診斷（未發版）— CondConverter v2：conditional 重排翻案（2026-07-17）

- **形態**：conditional P(漢字 | 讀音, 上下文)，讀音為硬約束編碼輸入（zenz 式），非通用 LM。emb256/hid512/L1 = **11.68M params**，全量 **42.9M 對齊對**（重建自公開 zake7749 語料,漂移 <1%,見 `analysis/cond-corpus-v2-rebuild-drift.json`）,1 epoch,val_ppl≈1.25。
- **tw538**：cond 單獨最佳 **383@ν0.75**（僅差 v2c 4 句）；**三項混合 `walk + 0.5·v2c + 0.25·cond` → 397/537（+10 over 387）**。conditional 與通用 LM **互補**——與同量級 char-TF（通用 LM）換架構失敗（332）形成對照。
- **歸因**：+10 全 A 類（in-pool 83→73）；B 類池外 **67 兩者不變**（reranker 定位）；single_char_swap 69→65。
- 權重 `models/cond-converter-v2.bin`；復現與完整表見 `analysis/cond-converter-v2-tw538.md`。app／flag／出貨權重未動。

### 實驗 / 診斷（未發版）— CondProposer 約束重搜打 B 類（2026-07-17）

- **問題**：397 的 +10 全在 A 類（池內），B 類 67 句 path_locked 正解在 N=10 池外,rerank 結構上碰不到。唯一能改切詞/路徑 = Zenzai 約束重搜。
- **做法**：CondConverter v2 當**提案器**（非通用打分器）——draft 差節點逐候選算 `P(字|讀音,左文)` → prefix-lock override → 再 walk() 重搜 → 讀音鐵律+節點 unigram 檢查 → 入池 → 對全池取三項 `walk+0.5·v2c+0.25·cond` argmax（保守採納,防退步）。
- **tw538**（`5 8 0.5 0.25 0.5 -2.5`）：BASE397 控制 **397**（精確重現）→ **ZENZAI 400（net +3；gains 4/regress 1）**；**B_CLASS_FIXED 4/67**（果之→果汁、耐衰→耐摔、灣到的灣度→彎道的彎度、很好其→很好奇）；**READING_FIDELITY_FAIL 0/537**。到達 7 句 B 類、保守選路採納 4（另 3 被 walk 項否決:擋片/點擊/豔紅色）。網格更高覆蓋不改善（瓶頸在選路非提案）。
- 復現 `analysis/cond-proposer-constrained-search-tw538.md`。app／flag／權重未動。

### 實驗 / 診斷（未發版）— 池外採納準則掃描（2026-07-17）

- **問題**：保守三項採納到達 7 句 B 類只收 4、否決 3（擋片/點擊/豔紅色）。調池外採納能吃回幾句?
- **做法**：pool 一次算好快取,記憶體掃變體(pool 建置是唯一貴步驟)。(A) 池外 walk 降權 α;(B) 神經雙票制(v2c 與 cond 同時偏好、margin m,walk 只平手裁決)。紅線:不動提案器/讀音鐵律/不重訓。
- **結果**（`5 8 0.5 0.25 0.5 -2.5`,α=1 重現 400、base397 397、fidelity 0）：
 - **A(walk 降權)撞牆**:α≤0.75 全崩(259/241,退步 145/163),吃回全部 7 句 B 類卻灌進 145+ 退步——walk 是讓池外路徑誠實的錨,拿掉=precision-recall 全有全無。
 - **B(神經雙票)穿牆**:**m=1.0 → 401/537**(net +4,gains 5,regress 1,B_CLASS_FIXED 5/7 到達)。最佳。
- **殘餘地圖**:B 類 67 句只有 **7 句被提案到達,60 句從未到達** → 天花板從「採納」移到「提案到達」。復現 `analysis/cond-proposer-acceptance-sweep-tw538.md`。app／flag／權重未動。
- **小型 char-Transformer 對照**（6L d256 h4 ffn1024 ctx128，**8.81M**，同語料）：
 - val_ppl **58.8**（優於 v2c 64.7）
 - tw538 最佳正 ν：**332@0.25**（**低於 walk ON 333**；ν∈{0.25..1} 全 ≤332）
 - A=138、**single_char 殘餘 94**（**差於 v2c 的 68**）
 - 結論：**注意力 LM 在 PathScorer 融合上未贏 LSTM**；ppl 優 ≠ 路徑排序優。
 - 產物：`train_char_transformer_lm.py`、`NeuralTFPathScorer`、`path-char-tf-spoken.bin`。
- **新 harness 最佳仍 v2c 387**（flag OFF）。
- **Zenzai** 封存、本棒不碰。

### 實驗 / 診斷（未發版）— 60 句沉默診斷 + 多位置提案 beam（2026-07-21）

- **問題**：B 類 67 句只有 7 句被提案到達,60 句沉默。是**機制**(單位置/搜索寬度,可修)還是**模型知識**(cond 分佈不偏好 gold,修機制無用)?
- **T1 沉默診斷**（`zenzai_silence_diag.cpp`,複用 401 harness 的 reached 判定）：對 60 句逐分歧位置量 (a) gold 字在 cond 單音候選的排名(teacher-forced gold 左文)、(b) 全路徑 cond gold vs draft、(c) v2c gold vs draft。分桶(綁定約束優先 KNOW>VETO_RISK>MECH)：
 - **MECH 24**(top3=20)：每個分歧位置 gold 可達 ≤top-5 且雙票皆偏好 → 加寬提案可救。
 - **VETO_RISK 22**：可達但至少一票反對 gold → 雙票(m>0)擋(採納牆殘餘)。
 - **KNOW 14**(1 lattice miss)：某分歧位置 gold 不在 cond top-5 → 需重訓/詞庫,機制無解。
 - **軸 a**：161 個分歧位置,**84% gold 在 cond top-3**(top1 75/top2-3 59)。模型幾乎都認得字;失敗在「多位置聯合到達」與「採納」,非知識。
 - **關鍵**：24 句 MECH **全是多分歧(2-7 位)**,0 單分歧 → 單位置提案器結構上組不出。停棒條款(KNOW≥40)**未觸發**。
- **T2 多位置 cond beam**（`zenzai_multiproposer.cpp`,fork 401 harness,`beam_width=0` 精確重現 401）：單位置提案後,對最差 `beam_pos` 音位 beam-decode cond top-k、留 `beam_width` 條、逐條重搜入池。**只擴池,雙票採納制不動**。
 - `8 3 8`：**到達 B 類 7→11**(+4,全是多分歧 MECH:硬邦邦/是帶點油嫩/沒事…有沒有事/爛鍋配爛蓋),雙票 m=1.0 **→ 402/537**(net +5,gains 6,**regress 1**,fidelity **0**);MEAN_MS 3.8k→19k。
 - 新到達 4 句雙票只採納 1(其餘 3 被 m=1 擋)——**綁定約束從「到達」移回「採納」**。
- **讀法/建議**：機制便宜勝(402)已入袋;其餘 ~44/60 卡採納(VETO_RISK 22+新到達否決)或知識(14),都不吃 beam。B 類線近便宜天花板;續攻須「更強 reranker(非 reweight)」或「知識(2-epoch 重訓/詞庫補 KNOW 14)」——皆較大投資。復現 `analysis/cond-proposer-silence-diag-tw538.md`(+`.tsv`)。app／flag／權重未動。

### 實驗 / 診斷（未發版）— 出貨延遲債:精度-延遲 Pareto（2026-07-23）

- **戰略**：顧問層拍板 B 類研究線收隊封存(cond 6hr 重訓維持封存)。新主戰場=出貨債:研究最佳 402 但出貨 app 仍 walk ON **333(62%)**,神經 rerank(v2c 387)一直被當「~730ms 不可出貨」。問題:輸入法 commit 延遲預算(甲級 ≤100ms/乙級 ≤160ms,N=10)內能拿幾分?
- **T1 免訓練壓縮**（`rerank_opt.cpp`,rerank 引擎同款 `walkNBest(10)`,只換 scorer）：兩把工程刀——(1) **前綴 trie 狀態共享**(10 條候選共享整句前綴,每個相異前綴的 LSTM step+softmax 只算一次,非逐候選從 BOS 重跑);(2) **Accelerate BLAS**(cblas_sgemv 打 4H×in 閘與 V×H 輸出投影)。
 - **v2c 387 @ ~44ms**(nbest ~5.6 + rerank ~38),對照 per-candidate 基線 **723ms → ~16×**,精度 **零損**(fp32 trie/BLAS 只重排浮點加法)。**甲級達標**,推翻「不可出貨」前提。
 - 全 Pareto(全 tw538 實測,皆甲級):v2c 387@44ms / v2b 374@14ms / v1 356@9ms。nbest 列舉本身 ~5.6ms(與模型無關,任何 rerank 的地板)。
 - nu 穩健(v2c opt):0.25→375、0.5→386、**0.75→387**、1.0→385;延遲 47–48ms 全程。
- **權重 int8(全張量,per-row 對稱,round-trip 全量重測)**：精度 v2c **387→387(零損)**、v2b 374→372(−2)、v1 356→353(−3)。大模型 int8 更穩,要出貨的 v2c 無損。**int8 此處無延遲增益**(dequant 走同 float sgemv),角色是**體積**:v2c 38.9MB→**9.9MB(3.9×)**。
- **T2 蒸餾——依 T1 條款降為驗證**（T1 已 ≥380@甲級）：**未跑蒸餾**。理由不只是跳過:能直接出 teacher(v2c 47ms/9.9MB int8),student 打不過自己的天花板 387;而更小體積點(v2b 372@4.1MB、v1 353@1.3MB)**已是現成訓練模型**,不花訓練就在檯面上;bundle 預算充裕(dmg 31MB+9.9MB=41MB,可內嵌)。KD-vs-scratch 對照僅在「硬性 <1MB 上限」時才需要,現無此需求。
- **T3 出貨候選**（app/flag/權重仍全未動,接線=下一棒）：**A(建議)v2c int8+trie+BLAS = 387 @ ~44ms / +9.9MB,對現出貨 333 = +54**;B(精簡)v2b int8 = 372 @ ~14ms / +4.1MB(−15 vs A)。
- 復現 + 證據 SHA256:`analysis/shipping-latency-pareto-tw538.md`。app／flag／權重／模型未動。

## [2.6.0] - 2026-07-23

**整句選字準確率大幅提升——神經網路重排首次進出貨版。**

### 新增 / 變更

- **整句智慧選字（神經路徑重排，預設開啟）**：送出整句時，內建的字元級神經網路
 語言模型會重新評估最可能的整句寫法，修正單靠詞頻猜錯的同音字。以 537 句台灣
 真實語料實測，整句全對率從 **62%（333/537）提升到 72%（387/537）**——約每三句
 就多對一句先前會選錯的。
 - 例：「百貨們是不是用」→「百貨門市不適用」、「瘋狂財源」→「瘋狂裁員」、
 「緊張分為」→「緊張氛圍」、「理公碩」→「理工碩」。
 - **打字當下零延遲**：重排只在**送出整句時**做一次（約 45 毫秒，感覺不到），
 逐鍵組字維持原本的即時反應（約 0.1 毫秒），完全不變慢。
 - **你手動選的字永遠算數**：重排絕不會蓋掉你親手挑過的字。
 - 模型以 int8 壓縮內嵌（約 9.9MB），離線運作、不連網。
 - 想關掉：輸入法選單 → **Neural Path Rerank (Experimental)** 取消勾選，即刻
 回到舊版選字行為。

### 技術細節（工程）

- 引擎 `NeuralLMPathScorer` 新增批次化重排 `scoreNBest`：N=10 候選共享整句前綴的
 LSTM 狀態（前綴 trie），輸出投影與閘走 Accelerate BLAS；v2c 模型 723ms →
 **~45ms（~16×）**，tw538 分數不變（387）。
- int8 磁碟格式 `LWLSTM8`（per-row 對稱量化 + 載入時反量化）：v2c 精度**零損**
 （387→387），檔案 38.9MB → 9.9MB；載入 16ms、常駐約 45MB。
- 平行性驗收：引擎路徑（`reading_grid`→`scoreNBest`）與 eval harness **完全一致
 387/537 @ ~45ms**。手選 override 存活驗證 32/32。
- 復現與 Pareto：`Source/Engine/eval/analysis/shipping-latency-pareto-tw538.md`、
 接線細節 `v2.6.0-shipping-wiring.md`。

## [v2.5.0] - 2026-07-09

**真神經路徑重排**：以 **char-LSTM LM** 取代 v2.4.0 的 char-trigram PathScorer（v2.4.0 違規用統計 n-gram 頂替 RNN，本版糾正）。

### 新增 / 變更

- **NeuralLMPathScorer（真 LSTM）**：2 層 char-LSTM，emb=64、hidden=128、vocab=4524、**參數 1,104,556**；權重 `path-char-lstm.bin`（~4.4MB 內嵌）。訓練腳本 `Source/Engine/eval/train_char_lstm_lm.py`（PyTorch），語料 = 台灣打字句 + zh-TW 維基 Han 抽樣（真實語料，非 LLM 合成頻率）。C++ 純前向推理（無 PyTorch runtime）：每步 embed → LSTM gates → FC logits → log-softmax 累加 log10 P(char|history)。
- **選型**：未找到可商用、繁中、≤200MB 且能在 CPU ≤80ms 內對 N=10 路徑算句 log-prob 的現成小權重；故 **自訓** 上述 LSTM（仍是神經網路，符合任務）。
- **ν 網格**（harness `nbest_path_rerank`）：`0→174, 0.1→177, 0.25→178, 0.5→179, 0.75→178, 1.0→176`；**BEST ν=0.5 → [retired-set score removed]**。對比 v2.4.0 char-ngram 最佳 **[retired-set score removed]**：**真 LSTM 贏 +4 句**。mean latency ≈ **30.7ms**（N=10，預算 80ms 內）。
- 偏好預設仍 **關**（`EnableNeuralPathRerank=NO`）；開啟後 `NeuralPathRerankNu` 預設 **0.5**。三 Guard 不退：OFF 164、ON 功能關 174。

## [v2.4.0] - 2026-07-09

**實驗性路徑重排骨架（n-best + PathScorer 介面）。** 預設關閉。**勘誤**：本版 PathScorer 實作為字元 trigram（非神經）；真 LSTM 見 v2.5.0。

### 新增

- **n-best 路徑抽取**（`ReadingGrid::walkNBest`，每狀態 K=8 hypotheses，N=10）與融合公式 `final = walk_score + ν · scoreSentence`。
- **CharNGramPathScorer**（統計 char trigram，已由 v2.5.0 神經版取代為主路徑 scorer；檔案可留作對照）。
- **偏好** `EnableNeuralPathRerank`（預設 **NO**）+ 選單「神經路徑重排（實驗）」。

## [v2.3.1] - 2026-07-09

修復 v2.3.0 的功能性 bug：**開啟情境化選字後，Shift+, / Shift+. 等標點與部分字母會被誤翻**（例如逗號變成 ︽、句號變成 ︾）。已安裝 v2.3.0 的使用者請更新到 v2.3.1。

### 修正

- **ContextModel DP 對標點／字母 reading 強制只走 top unigram**：`_punctuation_*`、`_half_punctuation_*`、`_ctrl_punctuation_*`、`_letter_*` 不參與多候選路徑重選。根因是同分多候選（如 `，〈《︿︽`）在 expanded DP 下可能選到非 top，導致預設開啟情境化後 Shift+, 打出 ︽ 而非 ，。Ctrl+, 因單候選而未中招。北極星 tw cold 不退：**[retired-set score removed]**（OFF）、**[retired-set score removed]**（ON λ=0.75）。

## [v2.3.0] - 2026-07-09

**預設啟用情境化選字 + 個人化。** 新安裝／未改過偏好的使用者一開箱就走語料 bigram walk；手動選字會記住並軟影響之後同上下文的選字。個人化資料只存本機。

### 新增

- **情境化選字預設開啟**：`EnableContextualWalk` 預設由 NO → **YES**。語料詞 bigram（`CorpusBigramContextModel`，λ=0.75）參與 `walk()` 路徑競爭。選單改稱「情境化選字」（拿掉「實驗」）。仍可在選單關閉。北極星 tw benchmark cold（空個人化 cache）walk ON **44.1%（[retired-set score removed]）**、walk OFF **41.5%（[retired-set score removed]）**——新使用者沒教過任何字也不會比 v2.2.x 差。
- **cache LM 個人化（roadmap 第 4 步 B，§1.4 軟加分主導）**：使用者手動選字偏好以**軟加分**進入 `walk()` DP，不再靠全面 hard override 硬塞。優先序寫死：`當下手選（硬）> 個人偏好軟加分（count 門檻 + decay，非強制）> 全域 bigram (λ·PMI) > top unigram`。
 - **為何改軟、不走硬覆寫**：硬覆寫會在錯上下文亂套。軟加分 + `C_min=2` + L0 精確 key（prev 值 × 讀音 × 字）才能「教過的上下文聽話、沒教的不亂套」。
 - **先加後減**：切片 A 先把 `μ_user·userScore` 疊進 DP；切片 B 再把 post-walk hard suggest **限縮為僅 `forceHighScoreOverride`**（多字詞競爭例外）。
 - **公式**：`userScore = min(4, log(1+count)) × decay`；`C_min=2`；L1 backoff 預留 `β1=0`；`μ_user=4.0`。同上下文選同一字 **2 次以上**才開始加分；約 **7 天**半衰期衰減。
 - **隱私**：`~/Library/Application Support/McBopomofo/user-override-cache.dat`（user data folder；`.gitignore`；**不進 bundle、不外傳**）。

### 修正

- **§1.2 UOM context key 對齊修復**：`FormObservationKey` 改讀 `WalkResult::chosenValueAt(i)`，與 contextual walk 螢幕顯示值對齊，避免 DP 翻字後髒學習外溢。

### 備註

- 25MB `word-bigrams.tsv` 照 v2.2.x 一樣內嵌出貨、本版不瘦身。
- 若曾手動 `defaults write … EnableContextualWalk -bool NO`，升級後仍維持關閉（偏好已寫入的值優先於新預設）。

## [v2.2.1] - 2026-07-09

修復 v2.2.0 的功能性 bug：**開啟 `EnableContextualWalk`（情境化 Walk）後無法手動選字**。已安裝 v2.2.0 且開了此實驗功能的使用者請更新到 v2.2.1。

### 修正
