# 版本更新歷程

本檔記錄i注音的版本變更。格式參考 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)，版本號遵循 [語意化版本](https://semver.org/lang/zh-TW/)。

正式發佈與 DMG 下載位於 [GitHub Releases](https://github.com/TsungLi-Wang/laowang-zhuyin/releases)。

**版本可追溯（常設）**：每個正式版本段落必須標 **commit 範圍** 與（若有）**tag**。打字行為或使用者可見改動的棒，收尾須更新本檔人話條目；發布點須遞增版本號並打 annotated tag。詳見交接檔卷一「版本可追溯鐵則」、`AGENTS.md`。

## [Unreleased]

### 內部 / 開發者改動

- repo 衛生：擴充 `.gitignore`（Python venv/pyc、訓練產物 `*.ckpt/*.pt/*.pth/*.bin`、實驗 log/out、`dd-*/` DerivedData 模式）；**未**重寫歷史、**未**移除版控中檔案。體積稽核：`.git` ≈ 241 MiB，HEAD 檔案總和 ≈ 238 MiB，粗算歷史殭屍 ≈ 3 MiB（pack 壓縮使差值偏小；最大 blob 多為仍在 HEAD 的模型權重）。
- 同音判別線 GO/NO-GO 量測（純研究）：`eval/tools/measure_homophone_entropy.py` + `homophone_measure.cpp`；`reading2chars` 自 conversion_pairs；tw538 殘餘熵 + 單點翻字 oracle。**結論 NO-GO**（第 2 輪淨增益 −45；出貨仍 387）。報告 `eval/analysis/tw538-single-flip-oracle.md`。
- 同音翻字閘門掃描（棒 A-2，純分析）：全提案 dump + Δ×H 曲面 + 五變體 split-half；V4（walk 融合）對 n-best 空操作；V5 半 oracle held-out ~+8。**判定仍 NO-GO**。產物 `tw538-flip-gate-*.md/tsv`、四格/Fano/位置剖面/句難度。
- 代理判別器上限（棒 A-3）：Qwen2.5-7B-Instruct-4bit（MLX）作上限代理；**有效性閘門未過**（出貨已對位置 75.6% ≪ 96%），T2/T3 依規未跑。結論：通用 instruct LLM **不能**當有效上限代理。報告 `tw538-proxy-judge-report.md`。
- 位置級同音判別器（棒 C 最終版，純研究）：BiLSTM ~13.3M、純淨／混合噪聲各 30 萬筆；四關評估 + split-half + 延遲。**主判準（n-best 重排 held-out）與次判準（單點翻字）皆 NO-GO**；路徑排序遠遜基線 B，重排延遲 ~1.9s/句 ≫45ms。提案 A（判別器路線）正式死亡。報告 `eval/analysis/tw538-position-judge-report.md`；腳本 `position_judge_batonC.py` / `position_judge_eval_fast.py`；權重與資料在 `~/laowang-data/batonC-final/`（不入 app）。
- 辨識語料重訓（棒 D，純研究）：凍結 v2c 架構（emb256/hid512/L2），只換資料；D0 短跑重訓控制 **380/537**；困難樣本加權 2×/5×/10×。最佳 **D1_w2 = 385（相對 D0 +5）→ 判定邊際**；5×/10× 反而掉分。合成跳過。報告 `eval/analysis/tw538-disambig-corpus-report.md`、混淆對表 `confusion-pair-frequency.tsv`；產物 `~/laowang-data/batonD-final/`（不入 app）。

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
