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

## 三行同步狀態（2026-08-18 收工 · 棒⑭-F）

1. **切法問題解決了，資源衝突不再是藉口。** document-level 5-fold（seed
   `baton14f-fold-v1`）下，稀有方向的 training signal 完全恢復：
   `做→坐` 0→39–41／fold、`坐→坐` 0→56–63、`做→作` 1→53–57。
   **`坐→坐` damage 62.6% → 7.5%**（CI 完全不重疊），`做→X` 從三方向合計
   0 次出手變成 12 次出手／8 次救回。H1、H2 都支持。
   細節：`Source/Engine/eval/analysis/node-expert-kfold-validation.md`。
2. **但仍不是 GO**：加權 net +0.17%、95% 下界 −3.06%，凍結規則不過。
   五個 fold 的 net 都是正的（+1～+9），只是不夠大。
3. **瓶頸只剩一格**：`作→作` **21 次出手、21 次全錯（damage 15.3%）**。
   棒⑭-D 已證明 global margin hinge 是錯解法（會連 `作→做` 的 rescue 一起壓掉）。
   要動就得是**只作用在該情境**的學習訊號，且必須在 5-fold 下同時報
   `作→作 damage` 與 `作→做/作→座 rescue`。
   `做→座` 五個 fold 都只有 8 筆訓練，維持 insufficient power。

## 前一棒（2026-08-18 · 棒⑭-E）

1. **⑭-E 把 ⑭-D 的資源衝突量清楚了：語料夠，是切法不夠。**
   全語料上限：`做→作 125`、`做→坐 83`、`做→座 30`、`坐→坐 108`。
   固定 dev 切法會一次吃光（A 方向剩 1 個可訓練）；
   **document-level k-fold 下 `做→坐` 有 train 66／dev 83，衝突就解除**。
   唯二補不起來的是 `做→座` 與 `作→坐`（各 30），應永久標 insufficient power。
   細節：`Source/Engine/eval/analysis/node-expert-data-resource-audit.md`。
2. **樣本複雜度有實測曲線了**（R4′ 同模型同 dev、各方向訓練數不同）：
   **59 個 → 94% precision、51 次救回**；21 個 → 學得會對角線「別動」；
   **10 個 → 有害**（39 次出手只對 5 次）；**0 個 → 災難**（坐→坐 67 次改壞）。
   所以每個方向需要 **25–60 個 clean examples**，少於 10 個會主動製造傷害。
3. **下一棒的最小動作已經寫死**：只把 train/dev 換成 document-level k-fold，
   其餘全部凍結，**先只重跑 R4 配方**，看 `坐→坐 damage 67/107` 會不會回到 0。
   那是驗證切法的唯一問題，不要同時測新 recipe。
   contexts pool 已證實補不了關鍵缺口（A 方向只補 1 個），別再花時間在那裡。

## 前一棒（2026-08-18 · 棒⑭-D）

1. **PART A/B/C 都做完，結論是停。** 新 audited dev 建好了（970 筆、三軸分層、
   人工核驗完成、`~/laowang-data/baton14d/`），R4 baseline 也量了
   （加權 net +0.98%、95% 下界 −3.29%，不過凍結規則）。
   完整數字：`Source/Engine/eval/analysis/node-expert-model-dev-baseline.md`
   與 `node-expert-failure-mode-training.md`。
2. **PART C 的兩個變因：A 無法執行、B 不成功。**
   A（讓模型敢動 engine=做 的錯）在排除 dev 文件後只剩 **1 個訓練樣本**；
   B（margin hinge 壓 damage）確實把 作→作·單字 damage 57.9%→0%，
   但**學到的是「全部都別動」**——margin 全面塌到 0，rescue 26.1%→1.7%。
3. **本棒最重要的發現是資源衝突，不是配方問題**：稀有方向在語料裡只有
   100–200 個節點，**dev 要 power 就得吃掉它們，training 也需要同一批**。
   對照組 R4′ 就是證據：只差排除清單變大，`坐→坐` damage 就從 2/71 爆成
   67/107。**在這個衝突解決前，同一份語料上的 recipe 比較都會被污染。**
   三個可能方向（擴語料／k-fold／縮開火條件）列在報告第 9 節，都需要你點頭。

## 前一棒（2026-08-17 · 棒⑭ A/B/C）

1. **⑭-C 查清楚了「dev 預估 +19.9／1,000、正式 −10」的原因，而且不是原本以為的那個。**
   `做→坐` **不是**覆蓋漏洞（dev 有 18 個樣本，且 dev 與 test 一致地顯示模型
   幾乎不出手、margin 四分位全 0.00）。真正的漏洞是**結構子群**：
   `作→作` 在 dev 只有 2 個單字節點、測試有 53 個，而 **37 次改壞裡 34 次（92%）
   就在單字節點**（傷害率 10.06%）。dev 那側 36 個節點的 Wilson 上界 9.64%，
   **數學上就偵測不到**。細節：`Source/Engine/eval/analysis/node-expert-dev-coverage-audit.md`。
2. **下一步是先建 dev，不是先訓練。** 新 dev 要加第三軸分層
   （engine choice × 方向 × 節點跨度），四個對角線單字格各 ≥120 筆、整份約 900–1,100 筆
   （現在 263）。凍結規則改成「預估淨值 95% 下界 > 0」。
   沒有這一步，任何新模型都無法在事前判斷會不會過。
3. **模型現況（別重複已排除的）**：R4 @ τ=0.5 在 Natural 淨 −10（p 0.26）、X +2。
   救回全部來自 作→做（14）與 作→座（11）；傷害全部在對角線。
   **凡引擎選「做」的錯，模型一律不動**（做→坐 73 個錯只出手 2 次）——
   那是天花板所在。hard 權重、單字結構權重、方向有界權重、context filtering
   都掃過了，別再掃一次。

## 前一棒（2026-08-14 收工 · 棒⑬）

1. **棒⑭ 兩段都做完，結論仍是 NO-GO，未合 master、未開預設、未接 app。**
   ⑭-A：人工核驗 263 筆，**語料金標乾淨（母體回加權 99.6%）**，棒⑬ 不是被髒標籤
   訓壞的。⑭-B：淘汰 hard ×12、改 loss 權重之後，自然 **−28→−10**（p 0.26）、
   X **−5→+2**、整句逐字正確率 −31 字→−9 字。方向對了，但沒過。
   完整數字：`Source/Engine/eval/analysis/node-expert-recipe-experiments.md`。
2. **最該記住的一條是方法，不是模型**：audited dev 在 τ=0.5 觀察到「27 次出手、
   0 次改壞」，我拿這個**點估計**去預估淨 +19.9／1,000；正式測試的真實傷害率是
   3.4%。127 個引擎正確節點根本分辨不出 0% 與 3%。
   **以後凍結規則要用區間下界**（「預估淨值 95% 下界 > 0」才准進正式測試），
   而且 audited dev 的規模要按「模型會出手的引擎正確節點數」算。
3. **兩個被資料修正的假設**（別再照舊說法傳下去）：
   ×12 **不會**扭曲方向比例（它對所有難例一視同仁），扭曲方向的是分層採樣；
   「多字詞佔據 training signal」在筆數上成立、在 **loss 上不成立**，
   所以單字節點加權反而讓模型更保守、結果更差。

## 前一棒（2026-08-14 收工 · 棒⑬）

1. **棒⑬ NO-GO，未合進 master、未發版、預設關。** `0007` 那個位置第一次真的開做：
   節點層封閉集合打分器（2.6M 參數／10.4MB），只在 walk 節點既有候選裡改選、
   預設棄權、只開「作做坐座」。兩份真實語料上 **自然 救10壞38（p=9.7e-05）、
   X 救1壞6** → 停。完整數字在 **`docs/decisions/0008`**，三條新死路已進 `dead-ends`。
   `path-char-lstm.bin` sha256 未變；不設 `IBOPOMOFO_NODE_EXPERT` 就完全不掛。
2. **壞的是模型，不是接法 —— 這個區別要留著。** 圍堵全部照設計運作：自然驗證集只改
   62 句（棒⑫ 是 3,501 句）、目標外只有 5 句（棒⑫ 是 3,409 句）、整句逐字正確率
   95.773%→95.731%（棒⑫ 掉到 89.58%）、延遲 +0.15ms/句（棒⑫ 是 133ms/句）。
   **白名單＋棄權＋節點層這一套是可以用的**，別因為這次 NO-GO 把它一起丟掉。
3. **根因可診斷**：難例集被「引擎過度偏好『作』」單一方向主導，×12 加權後模型學到
   「往『作』的反方向推」而不是判別；加上 dev 金標是未稽核的 PTT 原文，
   出手精準率 0.630 轉移到稽核過的尺上只剩 0.161。下一刀要動的是**難例怎麼取**，
   不是加大模型、不是改 τ 再報一次。

## 前一棒（2026-08-13 收工）

1. **棒⑧** 已發版（版號見 CHANGELOG 最上段），內容全為測試隔離與 CI 修復，
   **使用者可見行為零變更**；選字邏輯一行未動。
2. **Build workflow（GitHub Actions）已恢復綠燈** —— 兩個根因都修了：
   `whisper-server` 不進 git 但 Build workflow 缺 fetch 步驟；`Create commit comment`
   需要 `contents: write` 權杖。
3. **棒⑪ 已收**（引擎零變更、未發版）：`docs/decisions/0007` 定了神經消歧專家的
   接線位置（節點候選，不是 N-best；**只定位置不開做**）；`scripts/model-ab.sh`
   補上「換權重」的判準（`--self` 在 sample 與兩份真實語料都 0／0）；
   `scripts/correction-census.sh` 普查校正 log；
   `Source/Engine/eval/analysis/real-corpus-error-layers.md` 是第一張**真實語料**
   的錯誤分層地圖。
   前情：棒⑩ #10 已修、#9 作做坐座淨傷害已還原、#11 假綠燈收斂；
   Johnny 已裁句單保留「你先坐這裡等一下」、吧八巴先不做、
   `doc-check` 字面版零豁免否決（`docs/decisions/0006`），這幾條別再重開。

## 下一刀

**沒有阻塞項。** 動過詞庫／ranking／規則表／模型的棒，收工前仍必須本機跑
`./scripts/ship-gate.sh` 到 `SHIP_GATE_STATUS=CORE`；換權重另做模型對模型逐題配對
（`ship-gate` 比的是規則開／關，抓不到換模型，見 dead-ends）。

**棒⑪ 量出來、下一棒該知道的三件事**（都寫在
`Source/Engine/eval/analysis/real-corpus-error-layers.md`）：

1. 真實語料上最大宗的錯仍是**整句解碼錯**（自然 47.8%、X 36.9%）——
   節點層與路徑層機制**都修不到**那一半，別在那裡投資。
2. **「的／得」在真實語料上不是瓶頸**（現況 96.4%／98.6%，錯誤只有 14／9 題）。
   考卷把它放大了。不要再當主線。
3. 真實語料上最弱的是**作做坐座**（84.9%／82.2%），而它 O1 93.5% vs O2 98.6%
   —— 要出手該接**節點層**。棒⑩ 已實測**路徑層**對比訓練對這組是淨傷害。

**校正迴路**：真正換了字的校正事件只有 **11 筆**（`./scripts/correction-census.sh`）。
`docs/decisions/0003` 那條路**現在談群眾層太早**。
`wrong_char` 空白**不是 bug**：組字中手選一律寫空（`KeyHandler.mm:379`），
只有定案後 ↓ 重選才填（`InputMethodController+ShadowReselect.swift:222`）。
所以那 11 筆就是「定案後重選」的全部次數 —— 訊號是對的，量太少。

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
