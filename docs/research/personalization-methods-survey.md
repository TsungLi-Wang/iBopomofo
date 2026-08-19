# 個人化選字機制調查（棒㉒-B）

> **本棒性質**：純研究，**未修改任何 production 程式碼**。
> 目的不是「找到一個方法」，是**比 ⑭–⑲ 更有證據地縮小下一個產品實驗的搜尋空間**。

---

## 1. Executive Conclusion

**既有 user override model（UOM）這個 abstraction 不值得當主路徑救。**
它把三個各自已知會失敗的選擇疊在一起：細 key（稀疏時把證據打散）、
加分而非插值（沒有 `(1-λ)` 這種結構上限）、以及 **從 correction 學偏好**
（correction-only 不是偏好樣本）。

**下一個值得驗證的機制是換訊號，不是換 gate**：
個人化應該吃**已定案的全文**，而不是修正事件 —— 做 recency-weighted cache／PPM，
以**小 λ 插值**進既有分數，並在衝突讀音上**棄權**。

**但這不改變下一個動作。** 這條路的「機制」現在就能做，「淨效應」仍然
**必須等 decision denominator**（[`docs/decisions/0009`](../decisions/0009-下一個產品方向是先讓儀器上線.md)）。
沒有分母，damage 在結構上不可算 —— 而且這次是**文獻上的識別問題**，不是我們的工程問題（見 §9.3）。

> **本棒最大的收穫不是找到方法，是把「用 correction 學排序」整個家族判掉了。**
> 那包含上一版的 per-reading entropy gate、也包含 L1 back-off 的原始動機。

---

## 2. Current Problem

> 要用**使用者自己的歷史偏好**改善注音選字。但可得的回饋訊號只有
> 「使用者出手修正時」的事件，資料稀疏，而且同一讀音的偏好會互相衝突。
> **在這種條件下，怎麼做才不會讓個人化本身造成淨傷害？**

### 2.1 機器驗證過的資料現況

**全部數字由統治局在本機重新量過，不採信任何交班檔裡未經驗證的數字。**
來源：`~/Library/Application Support/iBopomofo/manual-correction.log`（595 可解析事件，
2026-08-04～08-19，單一使用者 15 天）與 `user-override-cache.dat`（93 條目）。

| 量測 | 值 | 意義 |
|---|---|---|
| correction 事件 | 595 | 分子 |
| 相異 (讀音→選字) | 329 種 | — |
| 只出現一次的種類 | **72.9%**（240/329） | 極度長尾 |
| 前 10 種覆蓋率 | **23.7%** | 無集中度可言 |
| 重複事件 | **44.7%**（266/595） | 個人化的理論上界 |
| 重複的中位間隔 | **0.09 天（約 2 小時）** | 衰減不是瓶頸 |
| 重複落在 7 天半衰期內 | **94.7%** | 同上 |
| 相異讀音 | 239 種，平均每讀音 **2.5 筆** | 稀疏 |
| 每讀音 ≥5 筆的比例 | **9.2%**（22/239） | per-reading 統計量估不出來 |
| 衝突讀音（≥2 種選字） | 25.5%（61/239），但**承載 58.3% 事件** | — |
| 重複事件落在衝突讀音的比例 | **73.7%**（196/266） | damage 風險區 |
| 衝突讀音的主流選字佔比 | **中位 0.50** | 擲銅板 |
| 帶 `engine_choice` 的事件 | **35 筆**（v1 可成對 31 ＋ v2 4） | 覆蓋率 5.9% |
| decision denominator | **不存在** | **damage 結構上不可計算** |

### 2.2 三個結構性限制（任何候選方法都必須正面回答）

**L1 — 沒有分母。** 日誌只在修正時寫入；引擎做對的決策一筆都沒有。
rescue 可估，**damage 不可估**，因此 net 不可估。這是 ⑱ 就量到的結論，至今未變。

**L2 — correction-only selection bias。** 日誌依定義只含「使用者不滿意」的事件，
會系統性高估「與引擎預設相反」的那個選字。若某讀音上引擎 95% 都合使用者意，
使用者只在想寫少數字時出手 → 日誌裡**少數字反而是壓倒性多數**。
任何從這份日誌歸納出來的 per-reading 統計量（包含熵、主流選字、偏好強度）
都帶著這個偏斜，而個人化加權會作用在**所有**出現位置，包括引擎本來就選對的那些。
→ **偏斜正好落在會被誤傷的那一側。**
小樣本佐證：在僅有的 23 個帶 `engine_choice` 的讀音裡，**26.1%（6/23）**
加入引擎選字後相異字數變多 —— 只看 `chosen` 會把它們誤判成乾淨讀音。
（n=35 事件，**方向性證據，不是定論**；但偏斜來自資料產生機制本身，方向是確定的。）

**L3 — 稀疏。** 平均每讀音 2.5 筆。要有足夠歷史才敢出手，但有足夠歷史的就已經不是長尾。
**這是個人化在本專案的內建張力，不是可以調參數繞過的。**

---

## 3. Existing Dead Ends（本專案自己的證據，外部方法必須與之相容）

完整清單見 [`docs/dead-ends.md`](../dead-ends.md)。與本題直接相關的：

| 已封閉 | 證據 | 對本題的意義 |
|---|---|---|
| 全域重排器（權重或 learned） | ⑮-B 掃遍 `a·unigram+b·pmi+c·rnn` 5,022 組＝**整個線性家族的上界只有 +85 字（0.114% 字位）** | 全域排序這條路是量到上界關掉的，不是放棄的 |
| 通用 Node Expert | ⑭-N **條件 AUC 0.459（低於隨機）** | 「預測這一個決策是不是錯的」在節點層已經失敗過 |
| 方向專屬 Node Expert | ⑭-K 系統貢獻 0.082% of D2 | 逐方向做不可攤提（NODE 家族有 1,132 個方向）|
| 加大模型／詞庫／換 LM 架構／上 LLM | 全部量過全負 | **這是同音消歧問題，不是語言生成問題** |
| Prototype-001（candidate×context） | document-held-out +1,543 → **跨語料 −266**；ablation 拿掉核心設計反而更好 | held-out 層級必須對應要泛化的層級 |

**方法論鐵則（違反即退件）**

1. **AUC / MRR / pairwise 只能當診斷，GO 判準一律用 cross-fitted rescue / damage / net。**（連續踩四次）
2. **總體 aggregate 會被 base rate 撐起來，出手決策要看「同一個決策點之內」的條件比較。**
3. **驗證來源 ≠ 機制來源。** 在 A 分布歸納的判準，拿到 B 分布用會得到精確但錯的數字。（踩過九次）
4. **新規則必須自帶反例考卷**（gold ＝「不該改」的句子）。`b=0` 不等於證明無害。
5. **分析工具的第一個測試，是它的輸出逐句等於 production 的輸出。**

**⚠️ 本棒特別提醒**：限制 L2（selection bias）就是鐵則 3 的第十次換皮 ——
上一版提案（per-reading entropy gate）把它從「評估端」修好了，卻讓它在**閘門本身**又長了一次。
外部方法若依賴 correction-only 訊號，必須明確說明怎麼處理這個偏斜。

---

## 4. 現有個人化實作（提案前必讀：這些**已經有了**）

`dead-ends` E 節：*「當專家的提案聽起來很厲害，先確認它是不是在描述已經存在的東西。」*

| 元件 | 現況 | 位置 |
|---|---|---|
| hard user memory | LRU，容量 500（**目前用 19%，容量不是瓶頸**），key = **context trigram**（前前詞、前詞、當前 (讀音,值)）| `Source/Engine/UserOverrideModel.cpp` `FormObservationKey` |
| soft user memory | key = (前詞值, 當前讀音, 詞)，分數 `min(cap, log(1+count))·decay`，經 `mu_user` 餵進 **walk 的 DP** | 同上 `SoftL0Key` / `userScore` |
| 出手門檻 | `kMinSoftCount = 2` | `UserOverrideModel.h` |
| 衰減 | 半衰期 **7 天**，20 個半衰期後歸零 | `LanguageModelManager.mm:36` |
| **粗粒度 back-off** | **已設計、已預留、關閉**：`kBeta1 = 0.0 // L1 reserved, disabled`；`userScore` 內註明「L0 miss 就回 0，不查較粗的 key」| `UserOverrideModel.h:53`、`.cpp:301` |
| 硬路徑出手範圍 | 限 `forceHighScoreOverride`（多字詞競爭），單字同跨度靠 soft DP | `KeyHandler.mm:840` |
| 學習閘 | `currentUnigram().score() > -8` 才 `observe()` —— **罕用字不進記憶，而罕用字正是長尾** | `KeyHandler.mm:405` |
| observe/suggest key 對不齊 | issue #10：斷詞修正時 observe 錨在 after-walk、suggest 錨在 current-walk，兩者永不相遇；已加 pre-break key 窄修 | `UserOverrideModel.cpp:126–143` |
| 個人化是否在跑 | **是**。cache 93 條目、今日 10:56 剛寫 | `user-override-cache.dat` |
| **但** | **80%（74/93）的條目 `obs_count = 1`**，而門檻是 2 → **八成的記憶產生零分數** | 本棒實測 |

**已量到的病根**：不是容量（19%）、不是衰減（94.7% 的重複在一個半衰期內），
而是 **key 粒度太細 → 證據被打散在大量 count=1 的格子上，累積不起來**。

**但粗 key 不是答案**：context-free 退避的安全區只有重複事件的 26.3%，
其餘 73.7% 落在中位 50/50 的衝突讀音上。

### 4.1 ⚠️ UOM **不是壞掉的**，別去抓蟲

`UserOverrideModelTest.cpp` 有 observe→suggest 的來回測試
（`BreakingUpCorrectionIsRetrievableOnNextWalk`、`SingleCharCorrectionStillRetrievable`），
而且**兩個都綠**。但看它們怎麼寫的：`observe` 與 `suggest` 用的是**同一個 grid**
（`walkGrid` 同參數呼叫兩次）—— 測的是「**完全相同的脈絡再次出現**」。

這正是設計本身：key 是 context trigram，所以只有脈絡逐字重現才會命中。

而我們量到的真實重複是在 **(讀音→選字)** 這一層，不是 context trigram 這一層
（80% 的 cache 條目 count=1 就是這件事的直接證據）。

> **結論：機制沒有 bug，它完全照規格運作；限制在規格本身。**
> 下一棒不要去抓蟲、不要去修 issue #10 的延伸 —— 要換的是 abstraction，不是修 bug。

---

## 5. ⑲ instrumentation 的實際部署狀態（文件 ≠ 機器）

| 項目 | 文件說 | 機器上 |
|---|---|---|
| schema v2（`engine_choice`／`event_type`／候選集）| 已實作、測試全綠 | ✅ 程式碼屬實 |
| 是否在收資料 | 交班檔寫「零成本，只要繼續用」 | ❌ **安裝中的是 build 2325（2026-08-14），`strings` 搜 `appendV2` 命中 0**；v2 事件僅 4 筆，全是測試 host 產生 |
| 實際累積速率 | — | **0 筆／天**（而使用者每天仍產約 40 筆舊格式事件）|
| decision denominator | 已知缺 | ❌ 仍缺，規格見 [`docs/decisions/0009`](../decisions/0009-下一個產品方向是先讓儀器上線.md) 第 10 節 |

→ **凡是「AFTER INSTRUMENTATION」的候選，等的是這個動作，不是等時間。**

---

## 6. External Research（外勤：grok，統治局逐條抽驗）

完整文獻回報 26 條引用，每條附作者／年份／venue／URL 與「它**沒有**證明什麼」。

**抽驗結果（統治局自行下載原文核對，非採信轉述）**

| 承重引用 | 宣稱 | 核對結果 |
|---|---|---|
| Adhikary & Vertanen 2023, Interspeech | PPM/RNN 個人化；混合權重大部分留給背景 LM | ✅ 原文表：`BG + PPM-12 = 0.75, 0.25` —— **使用者模型權重正是 0.25**。摘要證實 44 位模擬使用者、KS +9.9% 相對、WER −36% 相對 |
| Wang et al. 2019, arXiv:1910.10252 | `B=5,L=0.1 → +0.024`；`B=5,L=1.0 → −0.019`；>500,000 clients；主張 gating | ✅ **表 1 精確吻合到小數點**，baseline 0.166±0.001（故 +14.5% 相對正確），原文確有 "deployed if and only if it makes the user's experience better" |

其餘 24 條的作者群、venue、年份經辨識均為真實文獻（如 Fowler et al. 2015 CHI 的
共同作者 Chelba/Bi/Ouyang/Zhai 完全正確）。**未發現捏造引用。**

## 7. Production / IME Precedents

- **Gboard**：user-history n-gram 疊在主 LM 上（Hard et al. 2018；Google Research Blog 2024）
- **Apple**：federated evaluation / tuning（Paulik et al. 2021），並明確指出只記使用者手動修改會使資料嚴重偏向「被抓到的錯誤」
- **Mozc**（Google 日文輸入，開源）：明示使用者詞典
- **中文拼音 IME**：Zhang, Huang & Zhao 2019 (ACL) open-vocabulary neural pinyin IME

共同形狀：**個人化以插值／疊加於全域模型，權重小且保守；並且都吃完整輸入歷史，不是修正事件。**

## 8. Candidate Intervention Families

外勤提出 M1–M8：全域–使用者插值、階層 backoff、決策時棄權、contextual bandit、
recency cache/PPM、on-device 微調、IPS/反事實 LTR、明示使用者詞典。

## 9. Failure Modes（本節與本專案 dead-ends 高度共振）

F1 個人化會讓**平均**變差（Wang 2019：`L=1.0` 時 −0.019，且使用者間 delta 是寬分佈，非全體受惠）。
F2 只拿使用者修正當標註，學習與評估都會偏（Apple 2021 同一句話）。
F3 implicit feedback 是 **MNAR**，不是完整偏好（Saito et al. 2020）。
F4 位置／呈現偏差讓「被選到的」看起來像「被偏好的」（Joachims et al. 2017）。
F5 閉環自我強化（Jiang et al. 2019）。
F6 **IPS 在沒有 logging policy 時不是校正按鈕**（Swaminathan & Joachims 2015）。
F7 高方差 IPS 會把稀疏資料弄得更糟。
F8 多出來的個人化機器不一定贏簡單 cache（Fowler et al. 2015：衰減 cache ≈ unigram cache）。

### 9.3 ⚠️ 本棒最重要的一條：沒有分母時，反事實校正**不是效率問題，是識別問題**

無偏估計式 `R̂ = (1/n)·Σ_{i:O_i=1} ℓ_i / p̂_i` 需要 propensity
`p̂_i = P(這次決策被寫進 log)`。在本題裡那等於
`P(使用者出手修正 | 引擎選擇, 正解, 情境)` —— **正是未知量**。

因此：
- 沒有「引擎做對」的紀錄 → 估不出 propensity
- 連 self-normalized IPS 都沒有正規化常數
- doubly robust 需要 propensity **加上** outcome model，少一個就退回有偏
- 隨機探索能**製造**已知 propensity，但那是新的實驗設計，不是對舊 log 的事後校正

> **結論：安全的反應不是找更好的估計量，是不要用 correction 這個訊號去改排序。**
> 這一條同時判掉了 per-reading entropy gate 與 L1 back-off 的原始動機。

## 10. Comparison Matrix

| 方法 | 訊號 | 稀疏 | 衝突處理 | selection bias | 棄權 | 實作成本 | 最大風險 |
|---|---|---|---|---|---|---|---|
| 現行 UOM | correction | ✗ 打散 | 無 | **✗ 有偏** | 僅 count 門檻 | 已有 | 八成記憶零分數 |
| context-free L1 | correction | 部分 | 無 | **✗ 有偏** | 無 | 低 | 安全區僅 26.3% |
| entropy-gated L1 | correction | ✗ 每讀音 2.5 筆 | 有 | **✗ 閘門本身有偏** | 有 | 中 | §2.2 L2 |
| **M5 recency cache/PPM** | **已定案全文** | PPM 自動退避 | 棄權 | **✓ 繞開** | 有 | 低–中 | 強化未察覺的錯字（§11.1）|
| M3 決策時棄權 | 任意 | — | 核心即棄權 | 不引入 | 核心 | 低 | 覆蓋率低 |
| M1+M2 保守插值+階層 | 已定案全文 | backoff | 低熵層才說話 | ✓（若不吃 correction）| 有 | 中 | 較像使用者 LM，易過擬合 |
| M7 IPS/反事實 | correction | — | — | **識別不成立** | — | 高 | §9.3 |

## 11. Top 1–3 Candidates（統治局採納外勤排序，並加註）

**第一名 M5** — 已定案全文上的 recency-weighted cache／PPM ＋ 小 λ 插值，衝突讀音棄權。
**第二名 M3** — 決策時棄權（規則版），可套在既有 UOM 外面當保險，不必先承認 UOM 值得救。
**第三名 M1+M2** — 保守插值 ＋ 階層退避，只在低熵層允許說話。**餵進去的必須是定案全文。**

### 11.1 ⚠️ 統治局補一條外勤漏掉的風險（它自己引了 F5 卻沒套用到自己的第一名）

M5 吃「已定案全文」，而**已定案全文裡含引擎未被使用者察覺的錯字**
（全語料字位錯誤率 4.28%）。cache 會把那些錯字變得更黏 —— 這正是 F5 退化迴圈。

範圍是有界的：composing 路徑的修正發生在定案**之前**，所以定案文本已反映使用者
察覺到的意圖；殘留的只有「沒察覺」那一部分。但方向不利：
**我們最想修的那些讀音，正是使用者最常沒察覺的那些。**

→ 因此 M5 的規格必須加一條**負向記憶護欄**：
*凡使用者曾經在某讀音上修正離開某值，cache 不得在該讀音上增強該值。*
這是現有 correction log 唯一**安全**的用法 —— 只當否決票，不當偏好票。

## 12. GO / WAIT / DROP

| 方法 | 判定 | 可行性 |
|---|---|---|
| **M5 recency cache/PPM（＋§11.1 護欄）** | **WAIT** | 機制 NOW；**淨效應 AFTER INSTRUMENTATION** |
| M3 決策時棄權 | **WAIT** | NOW，但沒有分母就證不出它沒有白白降低覆蓋 |
| M1+M2 | **WAIT** | 結構 NOW；λ 與層門檻須等資料 |
| M4 contextual bandit | **DROP**（現階段）| 沒有每次決策的報酬 |
| M6 on-device 微調 | **DROP** | 資料量不足；神經線已封閉；Wang 證明可傷人 |
| M7 IPS / 反事實 LTR | **DROP**（舊 log）| §9.3 識別不成立 |
| M8 明示使用者詞典 | NOW（窄）| 合法但覆蓋小，只當 hard path 入口，不當主策略 |
| **既有 UOM 當主路徑** | **DROP** | §1 |
| **per-reading entropy gate** | **DROP** | §9.3：閘門本身建在有偏母體上 |

**沒有任何一個 GO。** 這不是找不到方法，是**每一個可信的方法都在同一個地方卡住**：
沒有 decision denominator 就算不出 damage。

## 13. Falsification Experiment

M5 的最小可否證實驗（**須在儀器上線並累積之後**）：

1. 裝置上對已定案字做 unigram/PPM cache，視窗數小時～1–2 天（對齊實測中位重複間隔 2 小時）
2. **只**對「該讀音在視窗內只出現過一個值」的位置加很小的 λ；衝突讀音不加
3. 加上 §11.1 負向記憶護欄
4. 用含 `engine_choice` 的新日誌做**逐題配對（McNemar）**，不用 AUC/MRR
5. **DROP 條件**：衝突讀音被 cache 改寫後錯誤上升；或視窗內單值位置的下一筆同讀音命中率不優於基線

## 14. Recommended Next Product Experiment

**不變**：[`docs/decisions/0009`](../decisions/0009-下一個產品方向是先讓儀器上線.md) 的
「⑲ 儀器上線 ＋ 分母計數器」。本棒是**第四條**獨立推理路徑走到同一個動作上
（方向比較 → damage 母體 → 閘門偏斜 → 文獻識別條件）。

本棒改變的是**儀器上線後要建什麼**：從「修 UOM 的 key」轉向
「已定案全文上的保守 cache ＋ 棄權」。這個轉向現在做比到時候再做便宜。

## 15. Open Questions

1. 已定案全文中「引擎錯字但使用者未察覺」的比例是多少？§11.1 護欄的必要性取決於它。**需要儀器。**
2. 衝突讀音的衝突，有多少是真的偏好搖擺，有多少是 correction-only 偏斜造成的假象？**需要儀器。**
3. `KeyHandler.mm:405` 的 `score() > -8` 學習閘擋掉多少長尾？（純離線可查，本棒未做）
4. 本專案所有數字來自**單一使用者 15 天**。個人化本身是 per-user，故不需跨使用者泛化；
   但「衝突讀音佔比」這類設計參數若換人是否穩定，未知。
