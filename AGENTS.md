# AGENTS.md

This file provides guidance to AI coding assistants when working with code in this repository.

## Project Overview

iBopomofo (i注音) is a macOS Traditional Chinese Bopomofo input method forked from McBopomofo. It keeps the upstream input engine and adds product features on top: **contextual selection** (corpus word-bigram inside `walk()`, **default on since v2.3.0**), **soft personalization** (user picks feed a private on-device cache into the DP), **neural path rerank** (char-LSTM int8 on sentence-end 定案; architecture family **v2c**, shipping weights **v2d** = 在/再 contrastive micro-tune → `Source/Data/path-char-lstm.bin`), **的/得 particle rule** after walk (`ParticleRuleDisambiguator` + `particle-rules.tsv`), **post-commit delete-and-recompose reselect** (↓ after 定案; verified 1→1 replace since v2.13.3; UOM soft learn since v2.14.0), optional on-device whisper.cpp voice input, and local observability (effective shipping settings + rerank diff log + manual-correction log). The project is built with Swift (UI/state), Objective-C++ (bridge), and C++ (engine), using macOS Input Method Kit (IMK).

The repository still intentionally keeps many upstream identifiers (`McBopomofo` target/module names, bundle id, input source ids, C++ namespaces) because they are tied to IMK registration, user data paths, and upstream merge cost. Prefer product-facing cleanup first; do not rename these internal identifiers without a migration plan.

**Current line:** 現役版本不寫在這裡 —— 見 `CHANGELOG.md` 最上面的已發布段落，或 `Source/McBopomofo-Info.plist`。收工前跑 `./scripts/doc-check.sh` 驗一致性；**發版前**跑 `./scripts/ship-gate.sh`（真實語料不得淨傷害 + 引擎測試 + 實機打字抽驗）。  
**Canonical product rule (v2.13.0+):** 定案 ≠ 送出; post-commit ↓ reselect 1→1; **v2.14.0** post-commit correction also feeds UOM soft personalization (one pick → soft active). **v2.15.0** 的/得 結果補語規則. **v2.16.2** 退掉 v2.16.0/1 的六組同音規則與頻率壓縮；留下 particle + v2d.  
Handoff: `AI_HANDOFF_PROMPT.md` + `CHANGELOG.md` + GitHub Issues（`deadend`／開著的 issue）+ `~/Documents/i注音-傳承交接檔.md`（軍師視角；**產品現況以 CHANGELOG + plist 為準**）。

**Brand vs technical IDs:** User-visible name is **i注音 / iBopomofo**. Internal Xcode target, bundle id `io.ibopomofo.inputmethod.iBopomofo`, install path `~/Library/Input Methods/McBopomofo.app`, and many C++/module names remain for IMK continuity — do not rename those without a migration plan.

**Privacy (local-only plaintext):** `~/Library/Application Support/McBopomofo/rerank-diff.log` (walk→rerank flips) and `manual-correction.log` (user re-picks). Never commit, upload, or attach to crash reports. Toggle/clear via input menu.

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

Triggers (prefs panel): pause (+ms), period, comma — each optional. Enter is **not** a toggle.

## Version traceability (standing rule — every baton)

This is a **permanent** rule, not a one-off cleanup.

1. Any baton that changes product behavior or user-visible content **must** on close-out:
   - (a) Update `CHANGELOG.md` in plain language (what changed, impact on the user);
   - (b) If the baton is a release point: bump version numbers in **both** `Source/McBopomofo-Info.plist` and `Source/Installer/Installer-Info.plist`, create an **annotated** git tag, tag message includes commit range;
   - (c) Record that version’s **commit range** in CHANGELOG.
2. Version numbers must not stagnate: once behavior-changing work accumulates, do not keep shipping under an old label (anti-pattern: months of work still labeled `2.7.0-dogfood`).
3. Pure research / harness / docs batons need not bump the product version, but still leave an **internal** CHANGELOG line with commit hash.
4. **Johnny** decides major/minor; executors propose with rationale only.
5. This rule must not be removed or weakened without Johnny’s explicit approval.

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

**排除的路要寫進 `AI_HANDOFF_PROMPT.md` 的「已排除的路」或 GitHub issue `deadend`**：試過但行不通的方向，要連同**實測數字**一起記下來，否則下一棒會重試一次。

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

**Runtime:** macOS 10.15 (Catalina) or later

**Development:**
- macOS 14.7 or later
- Xcode 15.3 or later
- Python 3.9 (for dictionary data generation)

## Building and Running

### Xcode Project Structure

The project contains these main **targets**:
- `McBopomofo`: Main input method bundle
- `McBopomofoInstaller`: Installer app (recommended for development)
- `Data`: Dictionary data generation
- `McBopomofoTests`: Swift test suite

**Build configurations:** Debug, Release (default when building from command line)

**Available schemes:** McBopomofo, McBopomofoInstaller, Data, plus individual schemes for local packages (BopomofoBraille, CandidateUI, ChineseNumbers, FSEventStreamHelper, InputSourceHelper, NotifierUI, NSStringUtils, OpenCCBridge, SystemCharacterInfo, TooltipUI)

### Primary Development Workflow

1. Open `iBopomofo.xcodeproj` in Xcode
2. Select the **"McBopomofoInstaller"** target
3. Build (⌘+B) and run to install McBopomofo
4. The installer automatically kills and restarts the input method process

**Important:** macOS limits how many times an input method process can be killed in a single login session. If installation stops working after multiple installs, log out and log back in.

### Command-Line Build

```bash
# Build the installer
xcodebuild -project iBopomofo.xcodeproj -target McBopomofoInstaller -configuration Debug build

# Build the main input method. Prefer the shared scheme so SwiftPM nested
# dependencies from local packages (OpenCCBridge/SystemCharacterInfo) resolve
# correctly in command-line builds.
xcodebuild -project iBopomofo.xcodeproj -scheme McBopomofo -configuration Debug build

# Build dictionary data only
xcodebuild -project iBopomofo.xcodeproj -target Data -configuration Debug build
```

### Running Tests

#### Swift Tests
- Target: `McBopomofoTests` in Xcode
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

McBopomofo uses a three-layer architecture (Swift/Objective-C++/C++). For detailed architecture and algorithm documentation, see:
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
| `scripts/ship-gate.sh` | 出貨三關；沒過不准發版 |

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
- Place code in existing namespaces: `McBopomofo`, `Formosa::Gramambular2`, `Formosa::Mandarin`
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
- **出貨驗收：** `./scripts/ship-gate.sh` —— 真實語料驗證集（PTT／X）不得淨傷害 + 引擎 ctest + 實機打字抽驗。改選字機制時**兩份都要跑**（EX1166 + 真實語料），且**驗證來源必須與機制來源不同**（已用 EX1166 自驗兩次翻車）。
- **Live end-to-end typing verification (no human needed):** after changing any
  typing-time behavior (L1 rerank, deferred neural rerank, disambiguator, key
  handling, contextual walk, personalization), run `./scripts/e2e-typing-check.sh "<US key sequence>"` — it types
  real virtual key codes into TextEdit through the installed IME and reports
  the committed text. Full method, bopomofo-to-key tables, and pitfalls (must
  use `key code`, never `keystroke`) in `docs/e2e-typing-verification.md`.
  Unit tests alone have missed real-device failures before (v2.1.1); use this
  before telling the user a typing-time change works.

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
