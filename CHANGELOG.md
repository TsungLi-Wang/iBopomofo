# 版本更新歷程

本檔記錄老王注音的版本變更。格式參考 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)，版本號遵循 [語意化版本](https://semver.org/lang/zh-TW/)。

正式發佈與 DMG 下載位於 [GitHub Releases](https://github.com/TsungLi-Wang/laowang-zhuyin/releases)。

## [Unreleased]

### 北極星切換（評測集）

- **`tw538-northstar.tsv`（537 句）** 取代 `tw-sentences.tsv`（395）成為預設北極星。
  - 來源：PTT 十個生活板實爬正文（Stock / PC_Shopping / Tech_Job / WomenTalk / movie / Food / Lifeismoney / Soft_Job / MobileComm / car）；**禁** Gossiping（訓練同源）與 C_Chat（圈內梗）。
  - 過濾：大陸／港澳用語、板規殘片、政治、NSFW 等；Johnny 人工逐句終審。
  - 舊 `tw-sentences.tsv` **保留存檔**（歷史對照），`build-and-run.sh` 預設改指 tw538。
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
- **ν 網格**（harness `nbest_path_rerank`）：`0→174, 0.1→177, 0.25→178, 0.5→179, 0.75→178, 1.0→176`；**BEST ν=0.5 → 179/395**。對比 v2.4.0 char-ngram 最佳 **175/395**：**真 LSTM 贏 +4 句**。mean latency ≈ **30.7ms**（N=10，預算 80ms 內）。
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

- **ContextModel DP 對標點／字母 reading 強制只走 top unigram**：`_punctuation_*`、`_half_punctuation_*`、`_ctrl_punctuation_*`、`_letter_*` 不參與多候選路徑重選。根因是同分多候選（如 `，〈《︿︽`）在 expanded DP 下可能選到非 top，導致預設開啟情境化後 Shift+, 打出 ︽ 而非 ，。Ctrl+, 因單候選而未中招。北極星 tw cold 不退：**164/395**（OFF）、**174/395**（ON λ=0.75）。

## [v2.3.0] - 2026-07-09

**預設啟用情境化選字 + 個人化。** 新安裝／未改過偏好的使用者一開箱就走語料 bigram walk；手動選字會記住並軟影響之後同上下文的選字。個人化資料只存本機。

### 新增

- **情境化選字預設開啟**：`EnableContextualWalk` 預設由 NO → **YES**。語料詞 bigram（`CorpusBigramContextModel`，λ=0.75）參與 `walk()` 路徑競爭。選單改稱「情境化選字」（拿掉「實驗」）。仍可在選單關閉。北極星 tw benchmark cold（空個人化 cache）walk ON **44.1%（174/395）**、walk OFF **41.5%（164/395）**——新使用者沒教過任何字也不會比 v2.2.x 差。
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

- **修好「開啟情境化 Walk 後選字上不了屏」**：v2.2.0 開啟 `EnableContextualWalk` 後，候選選單能開、能算候選，但從選單手動選字沒反應、選的字上不了屏。根因在 `walk()` 的 ContextModel DP：DP 依每個候選的原始 unigram 分數（`u.score()`）自行重挑路徑，**完全沒讀節點的使用者 override**（override 是靠 `node->score()` 回傳 `kOverridingScore` 生效的，只有無 ContextModel 的快路徑會讀），`chosenValueAt` 又回傳 DP 的選擇蓋掉使用者選的字，導致手動選字被靜默丟棄。修法：DP 遍歷候選時，若該節點被 override（`isOverridden()`）就只認被 override 的候選、計分改用 `node->score()`（與快路徑同一來源，正確 encode `kOverridingScore` 與各 override 型別），其餘候選跳過——讓 override 在快路徑與 DP 路徑行為一致。**沒有 override 的一般自動選字完全不受影響**：北極星 benchmark walk ON `lambda 0.75` 仍 **44.1%（174/395）**、walk OFF 仍 **41.5%（164/395）**，整條 lambda 曲線與 v2.2.0 逐點相同。
  - **補上先前缺的測試缺口**：新增 `OverrideIsHonoredWithContextModel`（ContextModel 開啟時 override 必須被尊重，修前紅、修後綠）與對照 `OverrideIsHonoredOnFastPath`（快路徑本就尊重 override）。此 bug 先前 harness 與五句 e2e 都沒抓到，因為它們只驗「walk 自動選出的字對不對」，從不模擬「使用者手動覆蓋」×「ContextModel 開啟」。

## [v2.2.0] - 2026-07-09

情境化 Walk（實驗功能，預設關閉）：引擎 `walk()` 首度讓上下文（真實語料詞 bigram）參與打字當下的路徑競爭。**預設關閉**，需自行開啟：輸入法選單「情境化 Walk（實驗）」，或 `defaults write org.openvanilla.inputmethod.McBopomofo EnableContextualWalk -bool YES`。

### 新增

- **情境化 Walk（實驗功能，預設關閉）**：引擎 `walk()` 新增可選的詞 bigram `ContextModel`，讓上下文參與**打字當下的路徑競爭**（不是事後重寫），只在節點既有的 unigram 裡改選——不生成新字、不改讀音。開啟後由真實語料詞 bigram（`CorpusBigramContextModel`）對每個候選加 `lambda * PMI(前詞, 詞)`。北極星 benchmark（395 句台灣句、`walk` 整句 top-1 字準確率）：baseline **41.5%（164/395）→ lambda 0.75 時 44.1%（174/395）**，+10 句、lambda=0 零退步；lambda 0.75 由 benchmark 網格搜索決定（非手調）。「他跑得很快」在完全不 force 下自然翻對（bigram 讓 walk 偏好 `他/跑得/很快` 的斷詞而非 `他/跑/的/很快`）。
  - 新偏好 `EnableContextualWalk` + 選單「情境化 Walk（實驗）」（三語）。預設關閉時 grid 走原本的 unigram 快路徑，出貨行為完全不變。
  - **語料表 `Source/Data/word-bigrams.tsv`（隨 app 內建，約 25MB）**：只用真實語料統計，來源 zh-TW 維基（約 8,500 萬詞），OpenCC `s2twp` 轉台灣詞形，斷詞單位與引擎詞庫同構（用引擎 unigram 做 Viterbi 斷詞，非 jieba/CKIP）。表存 PMI（`log P(詞|前詞) - log P(詞)`），與 lambda 無關故可不重建就網格搜索。建表管線 `Source/Engine/eval/build_word_bigram_table.py`；北極星 harness `Source/Engine/eval/benchmarks/`（`tw_benchmark.cpp` + `build-and-run.sh`，395 句、baseline 與網格搜索）。
  - 表以延遲載入（`dispatch_once`）且跨 KeyHandler 實例共用,只有第一次真正使用該功能時才載入,預設關閉路徑零啟動成本。

### 修正

- **修好 `feature/contextual-walk-v1` 的編譯/連結破洞**：前一批 commit 宣稱「Syntax clean」但實際 app target 無法編譯（`KeyHandler.mm` 多處 `node` 未宣告、一處 `-Wshadow`）也無法連結（`WalkResult::chosenValueAt` 只宣告沒定義）。已補齊。
- **`walk()` 的 ContextModel DP 改寫為精確 bigram Viterbi**：原「展開式 DP」用 lossy beam（K=8）+ 浮點 hash 狀態重組 + 指標回溯，在 lambda=0（等同純 unigram）時與原 Viterbi 相差約 50 句、淨少 5 句——即上下文模型的基座本身就有 bug。改為以「(位置, 末詞) 為狀態」的精確 DP（不剪枝），lambda=0 還原 unigram 結果，bigram 效果可乾淨量測。預設關閉時 grid 走完全未動的原快路徑。
- **`AINeuralCandidateRescorerTests` 平行競態修正**：該 suite 會改共用的 `EnableGlobalNeuralRerank` 偏好卻沒標 `.serialized`，Swift Testing 預設平行執行下偶發互踩（設 false 的測試讀到別的測試設的 true）。比照 `PreferencesTests`/`ServiceProviderTests` 補 `.serialized`。

### 文件

- **實機端到端打字驗證方法固化**：新增 `docs/e2e-typing-verification.md`（AppleScript `key code` 送真實鍵碼進 TextEdit 的完整方法、注音→鍵序→鍵碼對照、陷阱清單）與一鍵腳本 `scripts/e2e-typing-check.sh`；`AGENTS.md` Testing 節加入指引。改打字當下行為（L1/延遲重審/消歧器）必跑，單元測試全綠不足以代表實機行為（v2.1.1 教訓）。
- `Source/Engine/eval/benchmarks/README.md`：北極星 benchmark 與情境化 walk 重現步驟、before/after 數字、建表管線。KenLM 作為 `ContextModel` 未來可選升級（正確 backoff、升級 trigram 只換資料不換碼）延後、非否決；觸發條件＝TSV 版經 harness 證明有 lift 且需 trigram/正確 backoff 時。placeholder 抓取腳本（假 commit）先擱置不補完。

## [v2.1.1] - 2026-07-08

### 修正

- **神經延遲重審修好多字詞節點（v2.1.0 實測零翻字的主因之一）**：「慢慢的」「我的」「開心地」這類組合在詞典裡是整個詞（多字詞節點），「的」被吞進節點內，v2.1.0 只列舉單字節點所以完全翻不動。現在比照「在/再」消歧器的孿生詞邏輯：節點內存在「只差該字」的孿生 unigram（詞典同時有 慢慢的/慢慢地）就能在節點內軟覆寫改選。實機驗證（真鍵盤事件端到端）：「慢慢的走過來」→「慢慢**地**走過來」、「跑的很快」→「跑**得**很快」自動翻轉。
- 新增隱藏診斷開關 `NeuralDeferredDiagnostics`（defaults 設 YES 後延遲重審每個決策點寫入 `~/Library/Logs/laowang-neural-deferred.log`；預設關、零成本）。IME 的 NSLog 在系統 log 撈不到，固定檔才可靠。
- 新增引擎級橋接測試 `NeuralDeferredBridgeTests`（真鍵序打字驗 snapshot 列舉與軟覆寫，共 3 測試；全套 128 tests）。

### 備註

- 延遲重審需要歧義字與其右文**在同一個組字 buffer 內**（送出後的字輸入法無法再改）。逐詞送出的打字習慣看不到翻轉；整句打完再送出才會觸發。

## [v2.1.0] - 2026-07-08

AI 神經候選重排（實驗功能，預設關閉）首次落地。開啟後由本機 AI 模型（llama-server，與本機 AI 修正共用）用「整句機率」重審同音歧義字，分兩條路徑：候選窗開啟時重排候選順序；打字過程中對「的/得/地」等歧義位置在右文出現後隱形改選（延遲全局重審）。「在/再」仍由既有混淆表負責（分工制，神經層不推翻表的決定）。

### 新增

- **AI 神經候選重排（實驗，預設關）**：新偏好 `EnableGlobalNeuralRerank` + 選單「AI 神經候選重排（實驗）」（三語）。兩條路徑：
  - **候選窗路徑**（`AINeuralCandidateRescorer`）：focus span 右文 ≥2 字才由神經打分重排（θ=1.0 margin 才翻）；右文不足＝懸置（維持引擎排序，交給延遲層），不退 n-gram——整句打分的優勢全部來自右文，右文為空時神經與 local 打分數學等價，沒有新資訊。偏好關閉時維持既有 n-gram 行為。
  - **延遲全局重審**（`InputMethodController+NeuralDeferred` + `KeyHandler` 橋）：右文不足的根治。打字停頓 0.6s 後對 walk 上的歧義節點（右文已累積 ≥2 字）做整句打分，margin 過門檻就以 override-without-observe 軟覆寫隱形改選（不改切詞、不進使用者覆寫模型、使用者手動選字永遠優先、免 re-walk）。出貨模型實測：「慢慢地走過來」「跑得很快」「吃得很開心」「字寫得很漂亮」正確翻轉，「我的手機」不誤翻。
  - **分工制**：神經層字集刻意排除「在/再/載」——sim 顯示 4B 模型對「在」有系統性偏好，會推翻混淆表已翻對的「再」；ㄗㄞˋ 由表（92.3% 翻轉精確率）獨家負責。
- **`AISentenceScorer`：真整句機率打分器**（兩條路徑共用）：鏈式法則逐 token 打分，logit_bias 探針（目標 token +100 → greedy 必中 → 回報的 logprob 實測為 raw 值）一次呼叫取得精確機率、無 top-k 損失；哨兵起點修正 BPE 邊界合併的比較不公平；`cache_prompt` 巢狀前綴增量解碼。
- llama-server 生命週期改為「任一需要者持有」：神經重排開啟時會暖 server（模型未裝觸發首次下載），切走本機修正後端不再停 server。
- eval：`deferred_rerank_sim.py` 增量打字模擬（真實鏈式打分）：右文 0 字瞬時準確率 76% → 右文 ≥3 字 88%，證實「等右文再判」方向；θ sweep 與翻字次數統計。
- 測試：12 個純邏輯測試（focusSplit、右文 gate、懸置語義、margin 決策、符號閘門；mock scorer 不起 server）。

### 修正

- **重要勘誤：PoC harness 的「50 筆 100%、mean 38ms」是量測假象**。llama-server `/completion` 在 `n_predict=0` 時不回 prompt logprobs（會生成一個 token 並回報該 token 的機率），PoC 打的分數是 P(下一字|句子) 而非 P(句子)；100% 來自「打分全部平手時保持 allowed[0]」而該資料集 allowed[0]=expected。本版的 `AISentenceScorer` 與 sim 數字（76%/88%）才是真實水位。`llm_rerank_poc.py` 的舊打分函式保留供歷史參考，新實驗一律用 `deferred_rerank_sim.py`。

### 文件

- `docs/l1-neural-rerank-integration.md`：整合設計（第 1-7 節）＋右文不足根治設計與實測結果（第 8 節，含 8.8 最終落地架構）。

## [v2.0.0] - 2026-07-07

架構大精簡＋語音輸入全面換引擎。三個使用者可見的重點：語音輸入改為內嵌 whisper.cpp 本機辨識（離線、免 API key、首次自動下載模型）；AI 修正模型只留 Claude Opus 與本機 AI 兩選；「在/再」智慧消歧補上雙字元語境證據，「我再說一次」這類「再＋說」句型現在翻得動。

### 變更

- **語音輸入改為內嵌 whisper.cpp 本機辨識（取代原三來源）**：錄完整段後由 app 內嵌的 `whisper-server`（靜態編譯，`whisper-runtime/fetch-runtime.sh` 從固定 tag v1.9.1 原始碼建置）在本機辨識，模型 `large-v3-turbo-q5_0`（約 574MB）首次使用時從 HuggingFace 下載並驗 SHA256，之後永久離線。只需麥克風權限，不再需要系統「聽寫」、Speech 授權或 OpenAI API key。模型以固定 benchmark（`say` 生成 zh-TW 測試音訊）與 `ggml-small` 同條件對比後選定（turbo 錯 1 句 vs small 錯 2 句）；server 以繁體 prompt 偏置輸出，殘餘簡體由 OpenCC 安全網轉換。錄音期間 server 背景暖機，app 結束時回收子程序。
- **移除語音三來源選單**：Apple 原生（離線）、Apple + AI 修正、OpenAI Whisper（雲端）三條路徑與 `VoiceInputSource` 偏好全數移除；`VoiceInputManager`（Apple Speech）刪除，`NSSpeechRecognitionUsageDescription` 與相關字串一併清除。
- **AI 修正模型精簡為兩選**：移除 Codex CLI 與 Claude Haiku 後端（`CodexAICorrector` 刪除），只留 Claude Opus（雲端）與本機 AI；歷史偏好值 0/1 一律視為本機 AI，編號 2/3 不重排。設定視窗同步瘦身（拿掉 Codex 路徑、Haiku 模型、OpenAI 語音 key/模型欄位）。
- **「在/再」消歧表格式擴充：雙字元證據＋單字退避（v6 表隨版內建）**：單一鄰字分不開「我在說話」與「我再說一遍」——鑑別訊號在更外一格（話 vs 一）。表新增 `LB`/`RB` 雙 token 行，打分先查雙字元、查不到退回單字元；C++ 端從整條 walk 的字元序列取語境（跨節點邊界）。配套：建表腳本 `--min-bigram-count`（預設 2）、masked eval 同步、新增 233 句補充語料 `zai-corpus-v3-supplement.tsv`（進 repo）。數字對出貨 v2c 表：舊 eval 65→71/99、v2 留出集 miss 集合完全相同、seed cases 不變、「我再說一次」0→1、既往實機驗證句 8/8、遮蔽翻轉精確率 90.3%→92.3%。

### 移除

- 死碼清理：`AICorrectionPrompt` 的 LLM rerank prompt 三件組（v1.7.5 起 L1 已改進程內 n-gram，殘留未用）、`AIAssistCoordinator` 從未讀取的暖機通知旗標與 retry work item、三語系孤兒字串。

### 文件

- **在/再 real eval 收集管線**：新增 `Source/Engine/eval/real-zai-eval.tsv` 與 README「Real eval」節。同日補記：使用者確定不自行收句，首筆 miss 已改以雙字元證據根治（見上），收集檔保留供日後真實錯選句累積。

## [v1.9.1] - 2026-07-06

### 修正

- **消歧查表載入防呆**：`ConfusionPairDisambiguator::load` 的數值解析由 `std::stod` 改為不丟例外的嚴格解析（整欄需為有限數值），格式壞掉的行直接略過。載入發生在 `KeyHandler` 初始化，先前表檔若有一行毀損會讓輸入法啟動即崩潰；現在最壞情況只是該行證據失效。補 2 個壞表 gtest。（源自新酷音 Rust 重寫回顧一文的 fuzzing 邊界教訓）

## [v1.9.0] - 2026-07-06

「在/再」智慧消歧模組首次隨版內建（實驗功能，預設關閉）。開啟輸入法選單「同音字智慧消歧（實驗）」後，打字當下引擎會用左右文機率查表，把選錯的「在/再」就地改選——已實機驗證「我再問一次」「做完再弄」等句正確翻轉、「我在家等你」不誤翻。保守設計：證據不足時維持引擎原判（例如「我再說一次」目前不翻，待真實語料校準）。

### 新增

- **「在/再」智慧消歧模組（引擎節點覆寫 Phase A，實驗，預設關）**：新增 `ConfusionPairDisambiguator`（C++，`Source/Engine/`），在每次 lattice walk 之後，對讀音含 ㄗㄞˋ 的節點用「左右鄰字 log-odds 查表」重新在**節點內既有 unigram** 裡挑字——覆蓋單字節點（在/再）與詞典孿生詞節點（我在/我再），採 soft override（`kOverrideValueWithScoreFromTopUnigram`），不改切詞、不生成新字、不進使用者覆寫模型（override-without-observe，見 `docs/engine-node-override.md`）；使用者手動選字與 UOM 建議永遠優先。掛點在 `KeyHandler.mm` 的 `_walk`，由實驗偏好「同音字智慧消歧（實驗）」控制（預設關），且需 bundle 內存在 `confusion-pairs.tsv` 查表檔才生效（本版未附表，等真實語料訓練並通過 real eval 才會內建）。查表框架對其他混淆對（的/得/地、做/作…）開放。
- **建表與驗證工具**：`Source/Engine/eval/build_confusion_pair_table.py`（從語料統計左右鄰字 log-odds，含人工 review 清單與 coverage）、`masked_eval_confusion_pair.py`（遮蔽測試 + threshold sweep）；`rerank_eval` harness 新增第三條「disambiguated」線，直接量正式出貨路徑。合成語料 smoke 數字：遮蔽測試 baseline 50% → 查表 95%；引擎級整句 40/99 → 75/99、零退步。
- C++ gtest 新增 `ConfusionPairDisambiguatorTest`（10 tests：翻轉、孿生詞節點、尊重使用者覆寫、上下文變更撤回、soft override 不影響路徑分數等）。

### 變更

- **「在/再」查表已內建（`Source/Data/confusion-pairs.tsv`）**：v2 正式表（680 句訓練、threshold 0.5、524 條）已加入 McBopomofo target Resources，安裝後開啟實驗偏好「同音字智慧消歧（實驗）」即可使用；預設仍關閉，不影響既有行為。真實錯選句 real eval 仍待收集，用於後續校準門檻與語料。
- **建表腳本方法修正 + v2 語料訓練完成**：`build_confusion_pair_table.py` 的 L/R 證據改為類別條件似然比（合成語料的在/再配比不再滲入證據），prior 改可從引擎詞典推導（`--prior-from-data`，在/再為 -0.912，天然偏「在」）。以 v2 合成語料（600 句、12 類含陷阱類）+ 舊語料共 680 句訓出正式表（threshold 0.5、524 條、8.2KB）：留出集翻「再」精確率 90.3%、舊 eval 零誤翻；引擎級「在/再字位」56/120 → 70/120（修對 15、改壞 1）。表尚未進 bundle，待真實錯選句 eval 或使用者拍板。數字與重跑指令見 `Source/Engine/eval/README.md`。

## [v1.8.1] - 2026-07-01

### 新增

- **關於視窗顯示 git 版本碼**：「關於老王注音」現在顯示 `版本 (build · git 短碼)`，讓使用者與維護者能精確辨識目前執行的是哪一份原始碼，即使版本號未變也不會混淆。git 短碼由 build phase「Stamp Git Revision」在建置時寫入。

### 變更

- **L2 句末自動校正改走低調隱形提示**：修正建議改為掛在 `InputState.Inputting` 已預留的 `pendingAISuggestion` / `aiTooltipMessage` 欄位（顯示的單一真相來源），提示文字收斂為低調的「建議 …（Tab）」；採用（Tab）仍由 Coordinator 持有的真相來源決定，行為維持非破壞性、實驗開關預設不變。

### 文件

- 新增 `docs/engine-node-override.md`：引擎節點覆寫（真正「邊打邊隱形修正」）的風險評估與分階段設計；不動碼，先定地基與決策點（UOM 汙染、跨層邊界、使用者自主權為最尖銳風險）。
- 新增 `docs/l2-autocorrect-verification.md`：L2 句末自動校正 + 低調提示的實機驗證清單。
- 清除 `CHANGELOG.md` 與程式註解中對已棄用 `~/Documents/` 設計文件的殘留引用，改指向 `AI_HANDOFF_PROMPT.md` 與 `docs/`。

## [v1.8.0] - 2026-06-26

AI 隱形中文警察重構階段一：把 L1/L2 的狀態與決策集中到單一 Coordinator，並把 L2 句末自動校正改回非破壞性行為。架構重整為主，行為向後相容。

### 新增

- AI 隱形中文警察重構：新增 `AIAssistCoordinator.swift`，集中 L1/L2 的狀態、排程、serial 與 accept 決策，成為單一真相來源。
- 定義 `CandidateRescorer` / `SentenceCorrector` 協議，讓 L1 明確為快速 n-gram 層。
- 在 InputState 預留 `pendingAISuggestion`、`aiTooltipMessage` 等欄位，為低調隱形 UI 準備。
- 補上 `AIAssistCoordinator` 純決策的單元測試（accept 配對、consume bump serial、reset）。

### 變更

- L2 句末自動校正維持「只跳低調提示、按 Tab 才套用」的非破壞性行為；採用走既有 commit 出口。
- serial 過期判斷與 accept 配對由 Coordinator 擁有，Controller 只負責把結果套到 state；清理散落的 ai* 直接存取與死碼。
- 保留階段性開關（`enableAICandidateRerank` / `enableAIAutoCorrection`），預設不變。

### 修正

- 移除 L2 早期版本用 `setMarkedText` 直接覆蓋組字區的「假修正」：注音引擎為讀音驅動，該做法不更新引擎狀態，會被下一個按鍵或送出蓋回原文，且違反「只在引擎狀態裡操作」原則。

### 備註

- 這是「AI 隱形中文警察」設計報告階段一的重構基礎。L1 仍只重排候選、不生成；行為向後相容。
- 真正的「邊打邊隱形修正」需走引擎節點覆寫（僅適用讀音不變的同音/近音錯字），待 Coordinator 穩定後另行設計；改讀音的整句校正本質上只能在 commit 邊界套用。
- 詳細交班與後續提示見 `AI_HANDOFF_PROMPT.md` 交班日誌;引擎節點覆寫的風險評估見 `docs/engine-node-override.md`。

## [v1.7.5] - 2026-06-26

即時候選重排改為本機 n-gram scorer,並補齊 rescorer eval / training 工具。

### 變更

- **L1 候選重排不再呼叫本機 llama-server**:打字當下的候選建議改為進程內 character n-gram scorer,只在引擎已產生的合法候選裡重排,不生成新文字。
- **候選上下文更精準**:L1 rerank context 新增 composing buffer 的 cursor index,用目前候選所在位置替換評分,避免把候選誤接在 buffer 尾端。
- **避免無效重建候選窗**:若 scorer 選中的本來就是第一候選,直接清掉提示狀態,不重建相同候選列表。

### 新增

- `Source/Engine/eval/cases.tsv`:把 rescorer seed cases 從 C++ 程式碼抽成 TSV,方便追加 Johnny 的真實錯選測資。
- `Source/Engine/eval/train_char_ngram.py`:可從純文字或 `.bz2` 維基 dump 訓練 character unigram / bigram / trigram TSV 模型,支援 `--max-text-chars` 用部分語料快速實驗。
- `Source/Engine/eval/fetch_zhwiki_corpus.sh`:下載 / resume 中文維基 dump 到 ignored corpus 目錄。
- `Source/Engine/eval/README.md`:記錄 baseline、外部語料訓練、generated model 與 app fallback 行為。

### 備註

- 目前尚未把外部語料模型包進 app;app 若找不到 bundled `rescorer-char-ngrams.tsv`,會從既有 `data.txt` 建立小型 fallback model。
- 部分維基語料已證實可訓練與評測,但目前 10M / 50M 字實驗沒有改善 8 筆 seed case 的整體分數,因此不作為正式模型發佈。

## [v1.7.4] - 2026-06-26

語音輸入新增「辨識來源」三選一(實驗功能)。

### 新增

- **語音辨識來源可切換(輸入法選單)**,三選一:
  - **Apple(離線)**:系統內建辨識,離線、零成本(預設,即原行為)。
  - **Apple + AI 修正**:Apple 辨識後再過一次目前選的 AI 後端修正錯字與標點,離線。AI 修正失敗時自動退回原文,不卡語音。
  - **OpenAI Whisper(雲端)**:錄完整段上傳 OpenAI transcription API 辨識,辨識力最強;需使用者自備 OpenAI API key(按量付費、需連網),輸出統一過 OpenCC 轉繁。
- 「AI 修正設定…」新增 OpenAI 語音 API key(存 Keychain)與語音模型欄位(預設 `whisper-1`)。

### 備註

- OpenAI Whisper 來源為雲端可選後端,與 ChatGPT/Codex 訂閱不同,需另備 OpenAI Platform API key。
- 語音相關仍屬實驗功能;Whisper 錄音與上傳路徑尚待更廣泛實機驗證。

## [v1.7.3] - 2026-06-26

語音輸入收尾:辨識自動結束提示、使用說明文件、清理未使用字串。

### 新增

- **辨識器自行結束時補上提示**:當語音辨識偵測到句尾或達到時間上限而自行結束（非使用者主動雙擊停止）時,出字後會顯示「語音這段已自動結束,請再連按兩下右 Shift 重新開始」,避免麥克風被靜默關閉、使用者仍對著已結束的 session 繼續說話卻不自知。
- **README 新增「語音輸入(實驗)」使用說明區段**:含前置設定（開啟系統聽寫）、首次兩段式授權、操作步驟與常見狀況排查。

### 移除

- 清除未使用的「辨識中…(Recognizing…)」在地化字串（Base / en / zh-Hant 三語）。

## [v1.7.2] - 2026-06-25

語音輸入穩定性與首次授權流程修正。

### 修正

- **修正首次語音授權後輸入法可能跳回 ABC**:macOS 權限視窗會暫時改變前景程序與輸入源;現在只在授權前確實是老王注音時記住輸入源,授權完成後若目前仍停在 Apple 鍵盤 layout,會把輸入源恢復回老王注音。若使用者已切到其他第三方輸入法則不強制切回。
- **修正語音啟動時可能因 AVAudioEngine tap 格式崩潰**:新增 Objective-C 安全包裝攔截 `installTap` 例外,並依序嘗試 input/output/standard/nil audio format,避免 CoreAudio 格式不相容時讓 IME crash 後被 macOS fallback 到 ABC。
- **修正首次授權後立刻開始錄音的 UX**:第一次雙擊右 Shift 只處理語音辨識與麥克風授權;授權完成後顯示提示,使用者需再雙擊右 Shift 才開始錄音。
- **修正語音通知重疊**:停止錄音後若沒聽到內容或發生錯誤,只顯示對應提示;只有成功辨識並提交文字後才顯示「語音輸入已結束」。

### 變更

- 已授權狀態下,雙擊右 Shift 後以短緩衝啟動錄音,不再使用首次授權流程需要的長延遲。
- 移除本次診斷用的固定檔寫入 log,正式版不再寫入 `~/Library/Logs/laowang-voice-auth-diagnosis.log`。

## [v1.7.1] - 2026-06-25

語音輸入體驗微調:換熱鍵避開系統聽寫衝突,並補上辨識回饋。

### 變更

- **語音輸入熱鍵由「連按兩下 Control」改為「連按兩下右 Shift」**:macOS 內建聽寫常把「連按兩下 Control」綁為啟動快捷鍵,會與本功能搶麥克風。改用系統預設沒有綁定的右 Shift,**永久零衝突,使用者不必更動任何系統設定**。

### 新增

- **辨識回饋**:雙擊結束後到文字出現之間(on-device 收尾辨識有零點幾到數秒空窗),顯示「辨識中…」避免像沒反應;若沒聽到任何內容,顯示「沒聽到內容」。

## [v1.7] - 2026-06-25

新增 Phase 3「語音輸入」:對著麥克風講話,直接把字送進輸入欄。離線、用 Apple 內建語音辨識,零內嵌模型。

### 新增

- **L3 語音輸入(Phase 3,實驗功能)**:用 Apple 內建 `SFSpeechRecognizer`(繁體中文 zh-TW,優先 on-device 離線辨識)把語音轉成文字,辨識結果走既有 commit 出口落地,不繞 `KeyHandler` / `InputState`、不碰打字流程。零內嵌模型、可離線使用。
- **連按兩下 Control 的 push-to-talk**:連按兩下 Control 開始聆聽、再連按兩下 Control 結束並出字,全程不必離開鍵盤去點選單。為避免和 Ctrl+C 等快捷鍵混淆,只認「兩次乾淨的 Control 單擊」(兩擊之間不夾其他按鍵、不同時按其他修飾鍵)。輸入法選單的「語音輸入(實驗)」項仍可作為備援觸發。
- **聽寫未開啟時的引導提示**:on-device 離線辨識需要系統「聽寫」開啟;未開啟時會提示前往「系統設定 ▸ 鍵盤 ▸ 聽寫」開啟,而非只報失敗。

### 備註

- 已實機驗證:macOS 輸入法(input method)程序確實能取得麥克風授權並穩定錄音、辨識、出字(這是 Phase 3 最大的技術風險,現已排除)。
- 首次使用需在「系統設定 ▸ 鍵盤 ▸ 聽寫」開啟聽寫並允許麥克風 / 語音辨識授權;第一次開啟聽寫會下載離線語音模型(需一次性網路),之後可離線使用。

## [v1.6] - 2026-06-25

新增 Phase 2「句末自動校正」實驗功能,並強化 AI 對在/再、的/得/地的判別。

### 新增

- **L2 句末自動校正(Phase 2 MVP,實驗功能,預設關閉)**:開啟後,打到句末標點(。！？!?…)時自動在背景用本機模型校正整句。第一版刻意保守:**只跳建議提示、不自動改字**,使用者按 Tab 才採用;手動 ⌘Return 的「直接套用」行為維持不變。觸發比 L1 更克制(句末標點 + 長度達門檻 + 游標在句尾才觸發,逗號頓號不觸發),且非阻塞、過期結果丟棄。可在輸入法選單「AI 句末自動校正(實驗)」開關。

### 變更

- **AI 校正提示詞強化「在/再、的/得/地」判別**:L2 整句校正與 L1 候選重排的本機模型提示詞補上這兩組同音虛字的判別規則與對比例句。實測本機模型在「再/在」與平翹舌、鄰鍵錯字命中率提升且無退步;「得/地」這類仍受小模型能力限制,待後續領域微調處理。

## [v1.5.4] - 2026-06-24

品質修復版:修好開發測試流程,並讓 L1 候選建議更克制。

### 修正

- **完整 `xcodebuild test` 不再卡死**：以往整包測試會永久停住,根因有二且皆已修正。
  - 測試以 app 當 test host 啟動時不再 spawn 內嵌 llama-server、不再連網檢查更新(以 `XCTestConfigurationFilePath` 偵測測試環境)。
  - `VersionUpdateApiTests` 在未設定更新端點時不再因 continuation 永不 resume 而卡死。
  - 現況:110 個測試 / 9 個 suite 約 4 秒全綠並乾淨結束。

### 變更

- **L1 AI 候選建議觸發條件收緊**:`hasPhraseAlternativeCollision` 由「候選裡有任兩個不同的多字詞就觸發」改為「多字候選彼此近似同音(音節數相同、僅差一個音節)才觸發」,降低過度觸發、減少不必要的本機推理。

## [v1.5.3] - 2026-06-24

### 新增

- **終端機一鍵安裝** `scripts/install.sh`：不需打開 `.app`，完全避開 Gatekeeper。
- DMG 內附 `若 Gatekeeper 擋住請看這裡.txt` 說明。

## [v1.5.2] - 2026-06-24

修正安裝流程過於混亂的問題。

### 變更

- DMG 內**只保留一個**「安裝老王注音.app」，移除其他檔案。
- 安裝完成後自動開啟「系統設定 → 鍵盤 → 輸入法」，並顯示逐步加入輸入法的說明。

### 移除

- DMG 內多餘的「老王注音.app」「拖曳到這個資料夾.app」「安裝說明.txt」（造成使用者不知道該點哪個）。

## [v1.5.1] - 2026-06-24

安裝體驗大幅簡化。

### 新增

- DMG 改為圖形化 **「安裝老王注音」** 安裝精靈（取代 `安裝.command`）。
- **「拖曳到這個資料夾」** 捷徑：一鍵開啟輸入法安裝位置，支援拖曳安裝。
- 輸入法啟動時自動清除 macOS quarantine（拖曳安裝後本機 AI 可自動就緒）。

### 變更

- 安裝精靈安裝完成後自動清除 quarantine。
- README 與 DMG 內說明改寫為標準 Mac 安裝流程。

### 移除

- DMG 內的 `安裝.command`（易遭 Gatekeeper 阻擋且不像一般軟體）。

## [v1.5] - 2026-06-24

L1 候選語意重排（Phase 1）首次發佈。

### 新增

- **L1 AI 候選建議**：候選字容易混淆時，依前後文重排候選順序；可按 Tab 採用建議。
- 150ms debounce、本機 server 暖機後自動重試（最多 6 次）。
- 觸發條件：候選同音（相同注音、不同字）+ 歧義字 + 多候選差異判斷。
- 輸入法選單與偏好設定「進階」分頁可切換「AI 候選建議」。

### 變更

- `AICandidateRerankContext` 改為帶入候選注音；rerank prompt 會附上 `(注音)` 輔助判斷。
- L1 測試補強：水果店、資道、同音候選等 golden case。

## [v1.4] - 2026-06-24

### 變更

- 品牌名由 bopomofo 改為 zhuyin,與中文「老王注音」對齊:
  - GitHub repo 由 `laowang-bopomofo` 更名為 `laowang-zhuyin`(舊網址自動轉址)。
  - 英文產品名 `LaoWang Bopomofo` 改為 `LaoWang Zhuyin`(About、偏好設定、選單、安裝器等顯示文字)。
  - 發佈 DMG 檔名由 `LaoWangBopomofo.dmg` 改為 `LaoWangZhuyin.dmg`。
- 不更動:功能字「Bopomofo / 注音」、上游 `McBopomofo` 內部識別(target/bundle id/input source id/module/namespace/資料路徑)。

## [v1.3] - 2026-06-24

AI 後端錯誤回饋、單元測試與文案清理。

### 新增

- AI 後端改用結構化錯誤(`AICorrectionError`):修正失敗時顯示具體原因與處置建議,取代過去單一的「AI 修正失敗」。可分辨缺 API key、端點無效、逾時、連線失敗、401、429、其他 HTTP 錯誤、回應無法解析、本機 server 未就緒、codex 未登入/起不來等。
- 修正結果與原句相同時顯示「AI 未更動:整句看起來已正確」,避免按 ⌘Enter 像沒反應。
- `AICorrectionPrompt` 的 prompt 組裝、標記解析與輸出清理新增單元測試。

### 變更

- 版本紀錄從 README 拆出為獨立的 `CHANGELOG.md`。
- 使用者可見的英文文案統一為 LaoWang Bopomofo(僅顯示值,保留內部識別)。
- app 內部顯示版本由上游遺留的 `3.0` 對齊為 `1.3`(About 對話框;不影響更新檢查)。
- `package-dmg.sh` 移除對唯讀掛載來源無效的 quarantine 清除指令。

## [v1.2] - 2026-06-24

AI 架構重構與 README 產品化。

### 變更

- 將 AI 校正邏輯從 `InputMethodController.swift` 拆出；新增獨立的 prompt、Claude、Codex、本機 server corrector 檔案。
- `InputMethodController` 現在只保留觸發、狀態檢查與回填流程。
- README 重寫為正式開源產品格式，加入系統需求、安裝、AI 後端、版本更新歷程、專案結構與重構路線。
- 手動檢查更新改導向老王注音 GitHub Releases，不再導向 OpenVanilla 發佈通道。

### 清理

- 清理使用者可見的小麥注音殘留文案，安裝器與 issue template 改為老王注音語境。

## [v1.1] - 2026-06-24

本機 AI 發佈流程穩定版。

### 新增

- 本機 AI server 加入就緒狀態與暖機提示，避免模型載入中時靜默失敗。
- AI 修正加入逾時保護，避免 Claude、本機 server 或 Codex 卡住輸入流程。
- AI 修正結果回來時會檢查目前組字內容，避免過期結果覆蓋使用者新的輸入。
- 首次下載模型後加入 SHA256 完整性驗證。

### 修正

- DMG 打包腳本可直接執行，會先 Release build 再產出 `dist/LaoWangBopomofo.dmg`。
- 修正命令列 build 的 SwiftPM package 依賴解析。

## [v1.0] - 2026-06-18

注音 + 離線 AI 整句修正，首次正式 GitHub Release。

### 新增

- 本機 AI 模型改為首次使用時下載，下載後可離線使用。
- 內嵌 `llama-server` runtime，使用者不需要自行安裝 Ollama。
- DMG 內附 `安裝.command` 與安裝說明，處理未 notarize app 的 quarantine 問題。

### 變更

- 發佈包改為不內含模型，DMG 從約 2.9GB 降到約 18-19MB。

## 早期開發里程碑

正式 GitHub Release 之前的開發階段：

- 接入 AI 整句修正熱鍵（⌘Return）+ 使用者可設定金鑰／端點／模型。
- 加入 Claude、Codex、本機推理後端。
- 導入 Qwen3-4B-Instruct-2507 Q5_K_M 作為本機預設模型。
- 建立自架 DMG 打包流程。

[v1.9.1]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.9.1
[v1.9.0]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.9.0
[v1.8.1]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.8.1
[v1.8.0]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.8.0
[v1.5.3]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.5.3
[v1.5.2]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.5.2
[v1.5.1]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.5.1
[v1.5]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.5
[v1.4]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.4
[v1.3]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.3
[v1.2]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.2
[v1.1]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.1
[v1.0]: https://github.com/TsungLi-Wang/laowang-zhuyin/releases/tag/v1.0

## [Unreleased] - Full Expert Plan: Bigram in Walk + EM (2026-07-08)

### Added
- Full per-unigram DP expansion in ReadingGrid::walk() (expert design): when ContextModel set, uses Hypothesis (unigramIndex, score, prev, lmState, word) per position. Relaxation with context->score, recombination on lmState, top-K prune. Fallback to original node-Viterbi otherwise.
- WalkResult: selectedUnigramIndices + chosenValueAt(i).
- EM tool (em_reestimate.py) updated for --corpus; ran with generated 3395-line Taiwanese corpus → new_unigram table.
- Synthetic starter corpus (~3395 lines, pattern-based from benchmark + homophone templates) in project and ~/Documents/tw_corpus.txt.
- KeyHandler updates: all buffer/flatText loops now use _latestWalk.chosenValueAt(i) (not node->value()).
- Demo in benchmark validates full DP: context affects choice inside walk (e.g. "跑得" vs "跑的").

### Changed
- Walk now expands search space so context (bigram) participates in path/choice competition during DP (not post-fix approximation).
- Baseline on 395-sentence TW benchmark established at 41.5%.
- Core now strictly follows expert: context inside walk for right-context correction (deferred can retire with real scorer).

### Notes
- KenLM skeleton ready. Full scorer, cache LM, neural reposition, real corpus, KeyHandler wiring, full tests next.
- Risk accepted on feature/contextual-walk-v1.

