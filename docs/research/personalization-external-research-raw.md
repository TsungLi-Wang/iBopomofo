> **這是外勤（grok）棒㉒-B 的原始文獻回報，原樣歸檔。**
> 統治局的採納判斷、抽驗結果與補充風險在
> [`personalization-methods-survey.md`](personalization-methods-survey.md)。
> 抽驗過的承重引用：Adhikary & Vertanen 2023、Wang et al. 2019（皆逐項吻合）。
> **未逐條下載核對的引用仍應視為待驗。**

---

# 棒㉒-B 回報 · 低資料量下「安全的」IME 個人化選字機制

寫回：臨時安全警衛 grok　2026-08-19
範圍：只做派遣票第 3 節外部研究。不碰 repo 現況、不重推第 1 節數字、不宣稱任何 net / rescue / damage。

一句話結論先放這裡，細節在第 6 節：

> 文獻與業界 production 系統幾乎從不靠「correction-only 事件 → 細 key 加分表」當主路徑。
> 安全做法是：(1) 用已定案全文做 recency-weighted cache／PPM，再與全域模型做小 λ 插值；(2) 證據不足或互相衝突時 backoff／shrink 回全域，而不是硬加分；(3) 決策當下允許棄權。
> 既有 user override model 這個 abstraction **不值得救成主路徑**。需要的也不是更聰明的 gate 研究，而是換訊號與換介入單位。

---

## 0. 輸入假設（不重推）

派遣票第 1 節視為定案：

- 單一使用者、15 天、595 筆 correction、329 種 (讀音→選字)、極度長尾
- 衝突讀音主流佔比中位 0.50；≥5 筆的讀音只有 9.2%
- 沒有 decision denominator；correction-only 會系統性高估「與引擎預設相反」的選字
- 已有 UOM：hard＝context trigram LRU；soft＝(前詞, 讀音, 詞) + `min(cap, log(1+count))*decay`，門檻 2；backoff 預留但關
- 已封閉：全域重排器、節點層神經專家、加大模型／詞庫／LLM、AUC/MRR/pairwise 當 GO

本票問的是：在這種條件下，**文獻與業界怎麼做才不會讓個人化本身造成淨傷害**。

---

## 1. 領域掃描

每一條外部證據都用固定格式。標「未能確認」的不進前三名。

### 1.A Personalized LM / interpolation / online adaptation

**我們要的答案：** 權重怎麼定？稀疏怎麼辦？怎麼避免壓過全域模型？

#### 發現 A1 — 線性插值是這類問題的預設安全閥，不是裝飾

產業與學術的共同寫法是：

\[
P(w\mid h) = \lambda\,P_{\text{user}}(w\mid h) + (1-\lambda)\,P_{\text{global}}(w\mid h)
\]

λ 不是「記憶在不在」的開關，而是「允許使用者模型最多偏離全域多少」的硬上限。稀疏時 λ 必須小；資料變多再升。動態版本讓 λ 依上下文可靠度變（高階 n-gram 看過 → λ 大；沒看過 → λ 近 0）。

這跟「存一筆記憶然後加分」的差別：插值保證使用者分數**不能單獨決定排序**，全域模型永遠保有 \((1-\lambda)\) 的票。加分表沒有這層保證——一筆 count=2 的 soft 分數可以在 mu_user 夠大時壓過全域。

**外部證據**

標題 / 作者 / 年份 / venue / URL
`Statistical language model adaptation: review and perspectives` / Jérôme R. Bellegarda / 2004 / Speech Communication / https://doi.org/10.1016/j.specom.2003.08.002
它實際證明了什麼：把 LM adaptation 整理成插值、cache、mixture 三大家族，並指出 adaptation 資料遠少於背景語料時，必須把使用者模型當「有限偏移」而不是替代品。
它沒有證明什麼：沒有在 correction-only、也沒有在中文同音消歧上量過淨傷害。

標題 / 作者 / 年份 / venue / URL
`Language Model Adaptation using mixtures and an exponentially decaying cache` / Philip R. Clarkson, Anthony J. Robinson / 1997 / ICASSP / https://doi.org/10.1109/ICASSP.1997.596075　（作者頁 PDF：https://tonyrobinson.com/_media/ClarksonRobinson97.pdf）
它實際證明了什麼：mixture 插值在 adaptation 資料有限時可降 perplexity（文中報告 mixture 約 24%）；指數衰減 cache 處理 recency。
它沒有證明什麼：量的是語音辨識 perplexity，不是 IME 選字；訊號是完整文本，不是 correction。

標題 / 作者 / 年份 / venue / URL
`Three Approaches for Personalization with Applications to Federated Learning` / Yishay Mansour, Mehryar Mohri, Jae Ro, Ananda Theertha Suresh / 2020 / arXiv / https://arxiv.org/abs/2002.10619
它實際證明了什麼：個人化可收斂成三種可分析形式——user clustering、data interpolation、model interpolation；後兩者本質上都是「全域與個人的凸組合」，並給出學習理論界。
它沒有證明什麼：沒有處理 implicit-feedback selection bias，也沒有給出 IME 的 λ 設定處方。

#### 發現 A2 — 線上微調全域模型可以傷害一部分使用者；業界因此加 gate，不是加力道

Gboard 在數千萬使用者上做過 on-device fine-tune。平均可以漲，但學習率一大，**平均變成負的**，而且分佈左尾很重。他們自己的結論是：個人化模型只在「對這個使用者變好」時才部署。

這直接打臉「有資料就微調」——稀疏、非 IID、單機資料少時，fine-tune 是過擬合機器，不是個人化機器。

**外部證據**

標題 / 作者 / 年份 / venue / URL
`Federated Evaluation of On-device Personalization` / Kangkang Wang, Rajiv Mathews, Chloé Kiddon, Hubert Eichner, Françoise Beaufays, Daniel Ramage / 2019 / arXiv / https://arxiv.org/abs/1910.10252
它實際證明了什麼：Gboard next-word CIFG 在 >500,000 客戶端上，B=5、L=0.1 平均 accuracy +0.024（相對約 +14.5%）；同一設定 L=1.0 變成 **−0.019**。使用者之間的 delta 是寬分佈，不是全體受惠。作者明確寫：必須「derive and impose conditions under which a personalized model is deployed if and only if it makes the user's experience better」，並提出 gating。
它沒有證明什麼：他們的訓練／測試切分用的是**裝置上完整打字 cache**（80/20 時間切），不是 correction-only；也沒有公開 gate 的最終上線規則。

標題 / 作者 / 年份 / venue / URL
`DeepType: On-Device Deep Learning for Input Personalization Service with Minimal Privacy Concern` / Mengwei Xu, Feng Qian, Qiaozhu Mei, Kang Huang, Xuanzhe Liu / 2018 / IMWUT (UbiComp) / https://doi.org/10.1145/3287075　（作者 PDF：https://feng-qian.github.io/paper/deeptype_ubicomp19.pdf）
它實際證明了什麼：從公開語料預訓練全域模型，再到裝置上用**該使用者全部輸入歷史**做增量訓練，相對非個人化模型提升約 20% 輸入效率；沒有全域初始化的個人模型明顯較差。
它沒有證明什麼：資料是完整輸入 log（數百萬使用者規模），不是 595 筆 correction；沒有報告「個人化讓哪些使用者變差」。

**A 對本題的含義**

- 權重怎麼定：先當超參數，上限要小；有 denominator 之後才能用 held-out 調。沒有分母時，λ 只能用先驗保守值，不能用 correction 頻率去「學」λ。
- 稀疏怎麼辦：不要 fine-tune 權重；用插值 + 使用者模型本身再平滑。
- 怎麼避免壓過全域：插值的 \((1-\lambda)\) 是結構保證。加分表沒有。

---

### 1.B Hierarchical / back-off / multi-level user memory

**我們要的答案：** 證據不足時怎麼退避？證據衝突時誰贏？

#### 發現 B1 — 證據不足時退避到較粗上下文，是 n-gram 四十年的標準答案

Katz backoff、Jelinek–Mercer 插值、Stupid Backoff、Kneser–Ney，做的都是同一件事：高階上下文沒看過（或看太少）→ 不要發明機率，把質量交回低階／全域。Chen & Goodman 的大規模比較還指出：**小資料時插值通常優於純 backoff**。

這跟「細 key 存一筆、count<2 就丟」相反。後者是把稀疏證據直接扔掉；前者是把它**折進較粗、較穩的估計**。

**外部證據**

標題 / 作者 / 年份 / venue / URL
`An Empirical Study of Smoothing Techniques for Language Modeling` / Stanley F. Chen, Joshua Goodman / 1996（會議）／1999（期刊擴寫） / ACL 1996；Computer Speech & Language 13(4) / https://aclanthology.org/P96-1041/　https://arxiv.org/abs/cmp-lg/9606011
它實際證明了什麼：在多種語料、多種訓練量、bigram/trigram 上系統比較 Jelinek–Mercer、Katz、Church–Gale 等；資料少時平滑方法之間差距大，插值類通常較穩；並引出後來常勝的 modified Kneser–Ney。
它沒有證明什麼：比較的是完整語料上的 cross-entropy，不是使用者 correction；沒有處理「同一上下文兩個值各半」的衝突決策規則。

標題 / 作者 / 年份 / venue / URL
`Estimation of probabilities from sparse data for the language model component of a speech recognizer` / Slava M. Katz / 1987 / IEEE TASSP / https://doi.org/10.1109/TASSP.1987.1165125
它實際證明了什麼：高階 n-gram 計數不足時，Good–Turing 打折並 backoff 到低階，是稀疏資料下可用的機率估計。
它沒有證明什麼：沒有說 backoff 能校正 selection bias；也沒有給「兩個值打平」時該選誰。

標題 / 作者 / 年份 / venue / URL
`Large Language Models in Machine Translation` / Thorsten Brants, Ashok C. Popat, Peng Xu, Franz J. Och, Jeffrey Dean / 2007 / EMNLP-CoNLL / https://aclanthology.org/D07-1090.pdf
它實際證明了什麼：Stupid Backoff（看過就用相對頻率，沒看過就乘一個常數 α 往下退）在超大語料上接近 Kneser–Ney，而且實作極便宜。
它沒有證明什麼：作者自己寫它是為**大量**資料設計的便宜近似，不是為每讀音 2.5 筆的使用者記憶設計的。小樣本時它不會自動變安全。

#### 發現 B2 — 證據衝突時，文獻的預設贏家是「較粗、較多觀察的那一層」，不是「最新的那一筆細 key」

階層記憶的衝突規則大致是：

1. 同一層兩個值頻率接近 → **不要在這一層做決定**，退到下一層（或退回全域）。
2. 細層觀察少、粗層觀察多 → 粗層贏。
3. 只有在細層又多又一面倒時，細層才許壓過粗層。

這恰好打在本題的病上：80% cache 條目 count=1（永遠到不了門檻），而重複事件的 73.7% 落在主流佔比中位 0.50 的衝突讀音。階層規則會說：**這兩種情況都該棄權或退回全域**，不是等第二次出現就加分。

PPM（見 1.E）把「自適應上下文長度」做成演算法：從最長上下文往下退，直到有足夠計數。這是 B 與 E 的交界。

**B 對本題的含義**

- 既有 UOM 已預留粗粒度 backoff 且 β₁=0。文獻立場是：在本題這種稀疏＋衝突體制，**關 backoff 才是不正常的**。
- 但只開 backoff 不夠——若餵進去的仍是 correction-only，粗層一樣會被「與預設相反的選字」汙染，只是汙染範圍更大。

---

### 1.C Utility-driven / selective personalization

**我們要的答案：** 怎麼判斷「這一筆記憶在**這個決策**上值不值得出手」？

#### 發現 C1 — 選擇性預測／棄權：先定可接受風險，再決定覆蓋率

這家族的核心不是「記憶存不存在」，而是「這次預測夠不夠有把握才許出口」。Geifman & El-Yaniv 把這整理成 risk–coverage 曲線：允許棄權之後，留下的那些決策可以把風險壓到預先指定的水平。

換成 IME 語言：個人化模組是一個**可以說「這題我不管」的專家**。不管的時候，全域 walk 原樣出線。

**外部證據**

標題 / 作者 / 年份 / venue / URL
`Selective Classification for Deep Neural Networks` / Yonatan Geifman, Ran El-Yaniv / 2017 / NeurIPS / https://arxiv.org/abs/1705.08500
它實際證明了什麼：給定已訓練模型與任意信心分數，可以構造一個選擇性分類器，使風險不超過使用者指定的上限；用的是對信心排序後設閾值。
它沒有證明什麼：信心分數要校準；他們的實驗是影像／標準分類，不是 IME；沒有處理「信心來自有偏的 correction 樣本」。

#### 發現 C2 — Contextual bandit 回答的是「出手的期望效用」，但前提是每次決策都看得到報酬

LinUCB 這類方法：每個手臂（候選字）有一個不確定度，只在 UCB 顯示「值得偏離預設」時才偏離。這在概念上最接近本題要的「這一筆記憶在這個決策上值不值得」。

致命前提：bandit 的報酬必須在**每一次出示**後觀察到（點了／沒點、用了／沒用）。Correction-only 恰好缺這一半——引擎做對、使用者沒出手時，報酬沒被記錄。沒有這一半，就沒有 regret、沒有 UCB 的分母。

**外部證據**

標題 / 作者 / 年份 / venue / URL
`A Contextual-Bandit Approach to Personalized News Article Recommendation` / Lihong Li, Wei Chu, John Langford, Robert E. Schapire / 2010 / WWW / https://arxiv.org/abs/1003.0146
它實際證明了什麼：Yahoo 首頁新聞推薦上，LinUCB 用上下文特徵 + 置信上界，在線上流量上勝過非情境 bandit 與 context-free 方法；探索與利用被放在同一個決策規則裡。
它沒有證明什麼：他們有完整的出示與點擊 log（有 denominator）；沒有證明 bandit 能在「只記錄不滿意事件」的 log 上無偏學習。

**C 對本題的含義**

- 「值不值得出手」是對的問題，比「這筆記憶存不存在」對。
- 現有資料能做的，是**保守的、非學習的棄權規則**（夠不夠集中、夠不夠新、是不是衝突讀音），不是 LinUCB。
- 有 denominator 之後，才能畫 risk–coverage，或跑 bandit。

---

### 1.D Production IME / 鍵盤

**我們要的答案：** 業界怎麼處理稀疏歷史、drift、overfitting、隱私、低延遲、有限記憶體。

#### 發現 D1 — Gboard 的生產架構是「全域模型 + 使用者歷史 n-gram」，不是 correction 加分表

2018 年以前 Gboard 英文主 LM 是 Katz 平滑、Bayesian 插值的 5-gram（約 125 萬 n-gram）。上面再疊：

- personalized user history
- contacts
- email n-gram

這些都是**已送出／已存在的文本**，不是「使用者改錯字」事件。神經 next-word 後來用聯邦學習在裝置上訓練，但那是在學**族群**模型，不是單機 595 筆 correction。延遲預算寫死在約 20 ms。

後來的 DP-FL 論文進一步把「用使用者資料訓練」限制在有形式化差分隱私的聯邦平均，而且評估指標是 prediction picked ratio 這種**有分母**的線上指標。

**外部證據**

標題 / 作者 / 年份 / venue / URL
`Federated Learning for Mobile Keyboard Prediction` / Andrew Hard, Kanishka Rao, Rajiv Mathews, Swaroop Ramaswamy, Françoise Beaufays, Sean Augenstein, Hubert Eichner, Chloé Kiddon, Daniel Ramage / 2018 / arXiv / https://arxiv.org/abs/1811.03604
它實際證明了什麼：Gboard 當時的主路徑是 Katz 5-gram FST，並「Personalized user history, contacts, and email n-gram models augment the primary LM」；CIFG 聯邦訓練可在不匯出原文的情況下提升 next-word recall。延遲目標約 20 ms，模型量化後約 1.4 MB。
它沒有證明什麼：沒有把個人化寫成 correction-only override；沒有報告單機數百筆 correction 的淨傷害；聯邦學的是跨使用者的全域模型。

標題 / 作者 / 年份 / venue / URL
`Advances in private training for production on-device language models` / Google Research Blog（工程文章，非同行評審） / 2024 / https://research.google/blog/advances-in-private-training-for-production-on-device-language-models/
它實際證明了什麼（以工程宣告論）：Gboard 所有 next-word 神經 LM 都以 FL+DP 訓練；上線用的是 prediction picked／accuracy 這類有分母的效用指標。
它沒有證明什麼：這是 blog，沒有給單機稀疏 correction 的實驗；DP 保證的是隱私不是選字安全。

標題 / 作者 / 年份 / venue / URL
`Effects of Language Modeling and its Personalization on Touchscreen Typing Performance` / Andrew Fowler, Kurt Partridge, Ciprian Chelba, Xiaojun Bi, Tom Ouyang, Shumin Zhai / 2015 / CHI / https://doi.org/10.1145/2702123.2702503
它實際證明了什麼：模擬觸控打字上，空間模型+LM 把 WER 從 38.4% 降到 5.7%；再加 **unigram cache 個人化** 降到 4.6%。這是鍵盤領域少數真正量到「個人化有淨增益」的受控實驗。
它沒有證明什麼：個人化吃的是該使用者過去 30 天**完整 email**，不是 correction；模擬使用者是理想觀察者，沒有「只在不滿意時留下資料」的偏差。

#### 發現 D2 — Apple 把個人化的**超參數**拿到聯邦評估裡調，並公開警告「只拿使用者修正當標註會嚴重偏斜」

這是本票最接近的業界自白。Apple 的 FE&T 系統不是在雲端重訓個人模型，而是：裝置上用只存在裝置上的資料跑個人化演算法，把「個人化開／關、或不同超參數」的評估指標送回伺服器做聚合。他們明確寫：

> 若只在使用者手動改自動轉寫時記錄 ground truth，「evaluation data would be highly skewed towards such user caught and corrected error cases」。

這幾乎是派遣票第 1 節 selection bias 的業界版。

**外部證據**

標題 / 作者 / 年份 / venue / URL
`Federated Evaluation and Tuning for On-Device Personalization: System Design & Applications` / Matthias Paulik, Matt Seigel, Henry Mason, Dominic Telaar, Joris Kluivers, Rogier van Dalen, et al. / 2021 / arXiv / https://arxiv.org/abs/2102.08503
它實際證明了什麼：Apple 用聯邦評估／調參來設定 on-device 個人化演算法的**全域超參數**（不是把使用者原文送上車）；並把「correction-only 當 ground truth 會偏斜」寫進「The Challenge of Ground Truth」一節。ASR 個人化吃的是裝置上的個人詞彙／文法，評估要另想辦法（他們用 word confidence 等 proxy）。
它沒有證明什麼：論文沒有公開最終 λ／cache 大小等數字；也不是注音 IME。

#### 發現 D3 — 中日 IME 的生產個人化，公開看得到的是「轉換歷史 + 使用者詞典」，不是 correction 表

- **Mozc / Google 日文輸入**：開源碼裡有 `UserHistoryPredictor`，吃的是使用者**轉換／確定**過的詞，用頻率與新近度排序；另有明確的使用者詞典。這是 cache + 明示記憶，不是從「按↓改字」反推偏好。
- **中文拼音神經 IME 論文**（Moon IME、OpenIME）：線上更新的是詞彙／關聯，訊號是使用者實際輸入的拼音→漢字，同樣是完整轉換，不是只記修正。
- **Sogou / 微信輸入法 / Apple 日文使用者詞典**：公開文件只承認「使用者詞典／雲端詞庫／個人化開關」。**未能確認**其內部是否另有 correction 模型——沒有找到可核對的技術論文，不臆測。

**外部證據**

標題 / 作者 / 年份 / venue / URL
`Open Vocabulary Learning for Neural Chinese Pinyin IME` / Zhuosheng Zhang, Yafang Huang, Hai Zhao / 2019 / ACL / https://aclanthology.org/P19-1154/　https://arxiv.org/abs/1811.04352
它實際證明了什麼：神經拼音→漢字模型加上線上更新詞彙與抽樣機制，可跟隨使用者新詞；評估用的是標準語料與「true inputting history」。
它沒有證明什麼：沒有處理同音字在稀疏、互相衝突時的安全出手規則；也不是 correction-only。

標題 / 作者 / 年份 / venue / URL
Mozc 原始碼與專案說明 / Google / 持續維護 / 開源工程產物（非論文） / https://github.com/google/mozc
它實際證明了什麼：生產級日文 IME 把使用者歷史預測器與使用者詞典當成一等公民；歷史來自轉換確定。
它沒有證明什麼：開源碼不是受控實驗，不能當「這樣做有淨增益」的數字證據。

**D 對本題的含義**

業界在低延遲、有限記憶體、隱私約束下，共同選擇是：

| 業界實際做的 | 本題目前的 UOM |
|---|---|
| 吃已定案／已轉換全文 | 只吃 correction |
| 使用者模型是 n-gram／cache／詞典 | 細 key 加分表 |
| 與全域插值或 FST 疊加 | 直接加進 DP |
| 用有分母的線上指標（picked ratio、WER）決定上不上 | 沒有分母 |
| 個人化超參數用聯邦評估／held-out 調 | 門檻 2 是先驗 |

稀疏、drift、overfitting 的業界答案是：**短視窗 recency、小容量、插值、能關**。不是把門檻從 2 調到 3。

---

### 1.E 傳統 adaptive LM：cache / PPM / adaptive n-gram / recency / class-based

**我們要的答案：** 有沒有更簡單、更便宜、可解釋、真的量到 net gain 的做法？

有。而且這是本票裡**唯一一族被多次獨立量到正向淨增益**的方法。前提幾乎都一樣：吃的是完整近期文本，不是 correction。

#### 發現 E1 — Cache LM：第一次認錯沒關係，之後同一詞變容易。這是為「重複」而生的

Kuhn & De Mori 1990 的經典場景：稀有詞第一次會錯，但一旦進 cache，後續同詞被救回來。這對本題的「44.7% 事件是重複、(讀音→選字) 中位間隔 2 小時」是對得上的——**如果重複的是同一個字**。對衝突讀音（中位 0.50）cache 只會在兩種值之間來回甩。

指數衰減 cache（Clarkson 1997）處理 drift：舊觀察自動過期。半衰期是結構，不是事後加的 decay 補丁。

**外部證據**

標題 / 作者 / 年份 / venue / URL
`A Cache-Based Natural Language Model for Speech Recognition` / Roland Kuhn, Renato De Mori / 1990 / IEEE TPAMI / https://doi.org/10.1109/34.56193
它實際證明了什麼：把近期出現過的詞提高機率（硬體 cache 類比），可捕捉文件內短程詞彙突發，降低語音辨識困惑度。
它沒有證明什麼：假設「出現過 ≈ 以後還會出現」且目標詞穩定；沒有處理「同一讀音兩個字各半」；訊號是完整轉寫。

標題 / 作者 / 年份 / venue / URL
`Improving Neural Language Models with a Continuous Cache` / Edouard Grave, Armand Joulin, Nicolas Usunier / 2017 / ICLR / https://arxiv.org/abs/1612.04426
它實際證明了什麼：把近期隱狀態當 cache、用點積取出，可在不重訓參數的情況下適應近期歷史，降低困惑度。
它沒有證明什麼：這是神經 LM 的複製機制，不是 IME 同音消歧；仍假設完整 token 序列。

#### 發現 E2 — PPM 是「自適應上下文長度的 cache」，鍵盤上量過，而且比 unigram cache 強

Adhikary & Vertanen 2023 在 Fowler 公開的 Enron 個人化資料上，用 PPM 與 RNN 重做實驗：相對靜態背景 LM，最好的組合相對 keystroke savings +9.9%、相對 WER −36%。混合物權重裡，背景 12-gram 仍拿 0.75、PPM-12 只拿 0.25——又是小 λ。他們也報告：Fowler 原論文裡指數衰減 cache 與普通 unigram cache 差不多，所以他們沒再上衰減。

**外部證據**

標題 / 作者 / 年份 / venue / URL
`Language Model Personalization for Improved Touchscreen Typing` / Jiban Adhikary, Keith Vertanen / 2023 / Interspeech / https://www.isca-archive.org/interspeech_2023/adhikary23_interspeech.pdf
它實際證明了什麼：在 44 名使用者、每人固定 1520 詞 priming + 1520 詞評估的受控模擬上，PPM／RNN 個人化優於 unigram cache；混合物把大部分權重留在背景 LM。
它沒有證明什麼：用的是完整 email 文本與理想模擬使用者；不是 correction-only，也不是中文同音。

標題 / 作者 / 年份 / venue / URL
`Data Compression Using Adaptive Coding and Partial String Matching` / John G. Cleary, Ian H. Witten / 1984 / IEEE Trans. Communications / https://doi.org/10.1109/TCOM.1984.1096090
它實際證明了什麼：PPM 用最長已見過的上下文預測下一個符號，沒見過就退一階——這就是「自適應上下文長度」。
它沒有證明什麼：這是壓縮論文，不是 IME；Dasher 後來把它用在輔助溝通輸入，那是另一條工程線。

#### 發現 E3 — Class-based n-gram 用「類」對抗稀疏，但幫不到本題的衝突讀音

Brown et al. 1992 把詞聚成類，用類轉移平滑詞轉移。這對「沒見過的詞對」有用。本題的病不是沒見過，而是**見過兩個相反的字、次數差不多**。把「在／再」收進同一個類，只會讓衝突更糊。

**外部證據**

標題 / 作者 / 年份 / venue / URL
`Class-based n-gram models of natural language` / Peter F. Brown, Peter V. deSouza, Robert L. Mercer, Vincent J. Della Pietra, Jenifer C. Lai / 1992 / Computational Linguistics / https://aclanthology.org/J92-4003/
它實際證明了什麼：詞類 n-gram 可降低稀疏造成的困惑度。
它沒有證明什麼：類是為沒見過的組合而設，不是為同音衝突而設。

**E 對本題的含義**

- 有更簡單、更便宜、可解釋、且**在完整文本上量過淨增益**的做法：unigram／衰減 cache、PPM、小 λ 插值。
- 這些方法的淨增益**不能直接搬到 correction-only**。搬過去會把「使用者討厭的那個預設」當成「使用者喜歡的那個字」來 cache。

---

## 2. 失敗研究（專門找翻車）

少於 5 條視為未完成。以下 8 條。一個方法為什麼失敗，和為什麼成功一樣重要。

### F1. 個人化可以讓平均變差，不是只讓長尾變差

Wang et al. 2019（見 A2）：同一套 on-device fine-tune，學習率從 0.1 改 1.0，平均 accuracy delta 從 +0.024 變成 **−0.019**。小 batch + 高學習率讓「很大一部分使用者」遇到模型退化。失敗原因：把個人化當成必定非負的微調，沒把「過擬合單機資料」當一等風險。

### F2. 只拿使用者修正當標註，評估與學習都會偏

Paulik et al. 2021（見 D2）把這寫成系統設計的核心挑戰：correction-only ground truth「highly skewed towards such user caught and corrected error cases」。失敗原因：把「使用者不滿意時留下的資料」當成「系統表現的樣本」。這與派遣票第 1 節 26.1% 的小樣本佐證同類。

### F3. Implicit feedback 不是完整偏好，是 MNAR

標題 / 作者 / 年份 / venue / URL
`Unbiased Recommender Learning from Missing-Not-At-Random Implicit Feedback` / Yuta Saito, Suguru Yaginuma, Yuta Nishino, Hayato Sakata, Kazuhide Nakata / 2020 / WSDM / https://arxiv.org/abs/1909.03601
它實際證明了什麼：點擊等 implicit feedback 同時有正例未標（沒看到 ≠ 不喜歡）與 MNAR（熱門／常被推薦的更容易被點）；忽略 MNAR 的方法會系統性偏。他們的 IPS／clipped IPS 在半合成與真實資料上優於未校正基線，尤其對稀有物品。
它沒有證明什麼：校正需要 propensity 模型；沒有 propensity 就退回有偏。不是 IME 論文。

失敗含義：把 correction 當正例、把沒出現的 (讀音, 字) 當負例，會同時犯 PU 與 MNAR 兩種錯。引擎常選的字更少出現在 correction log 裡——這不是因為使用者不喜歡它，是因為做對了就不會留下紀錄。

### F4. 位置／呈現偏差會讓「被選到的」看起來像「被偏好的」

標題 / 作者 / 年份 / venue / URL
`Unbiased Learning-to-Rank with Biased Feedback` / Thorsten Joachims, Adith Swaminathan, Tobias Schnabel / 2017 / WSDM / https://arxiv.org/abs/1608.04468
它實際證明了什麼：搜尋點擊被位置強烈扭曲；直接拿 implicit feedback 訓 LTR 會得到次優排序。IPS（用 click model 當 propensity）可在查詢不重複時仍做無偏 LTR。
它沒有證明什麼：沒有 propensity（或 propensity 模型）就沒有無偏性。IME 候選清單的「第一名被略過、第三名被點」是同一種呈現偏差。

### F5. 閉環會自我強化：系統出示什麼，之後就只學到什麼

標題 / 作者 / 年份 / venue / URL
`Degenerate Feedback Loops in Recommender Systems` / Ray Jiang, Silvia Chiappa, Tor Lattimore, András György, Pushmeet Kohli / 2019 / arXiv / https://arxiv.org/abs/1902.10730
它實際證明了什麼：推薦→曝光→回饋→再訓練的閉環，會讓模型往極端走，觀測到的行為偏離真實興趣。
它沒有證明什麼：這是推薦系統模擬，不是 IME。類比成立的部分是：若個人化只從「使用者改掉的字」學習，下一次更容易再推那個字，於是更常被改或更常被確認——兩種方向都會自我強化，而你分不出來。

相關：Mansour / Chaney 一線（回饋迴路造成經驗同質化）在推薦裡被反覆觀察。IME 若用 correction 加分，等價於「只強化少數被改過的路徑」。

### F6. IPS / 反事實學習在沒有 logging policy 時不是「校正按鈕」

標題 / 作者 / 年份 / venue / URL
`Counterfactual Risk Minimization: Learning from Logged Bandit Feedback` / Adith Swaminathan, Thorsten Joachims / 2015 / ICML / https://arxiv.org/abs/1502.02362
它實際證明了什麼：從已記錄的 bandit 回饋做批次學習，必須用 propensity 加權；並提出 CRM（對 IPS 估計量的變異做懲罰）以避免高權重樣本把模型拉飛。
它沒有證明什麼：propensity 未知時，整個框架沒有理論保證。Correction-only log **沒有記錄當時的出示策略**，也沒有記錄沒被改的決策，propensity 估不出來。

標題 / 作者 / 年份 / venue / URL
`Recommendations as Treatments: Debiasing Learning and Evaluation` / Tobias Schnabel, Adith Swaminathan, Ashudeep Singh, Navin Chandak, Thorsten Joachims / 2016 / ICML / https://arxiv.org/abs/1602.05352
它實際證明了什麼：把推薦當處理（treatment），用因果推論處理選擇偏差；IPS 與 doubly robust 可同時去偏學習與評估。
它沒有證明什麼：同樣要求已知或可估的處理指派機率。沒有「為什麼這次被記錄」的模型，去不了偏。

### F7. 高方差 IPS 會把稀疏資料弄得更糟

Saito et al. 2020 自己分析了無偏估計量的方差，並提出 clipped IPS：完全無偏的 IPS 在小 propensity 時方差爆炸，clipping 用一點偏差換穩定。本題每讀音平均 2.5 筆，若再乘上「1 / 被記錄機率」，少數幾筆 correction 會拿到極大權重——這是災難性個人化的標準配方。

失敗含義：就算將來有了半套 propensity，未加 clip、未加 CRM 變異懲罰的 IPS，在 595 筆這個量級上仍會翻車。

### F8. 多出來的個人化機器不一定贏簡單 cache

Adhikary & Vertanen 2023 引用 Fowler 2015：指數衰減 cache 與普通 unigram cache 表現相近，所以他們沒採用。失敗（弱）含義：在已經很小、已經很近的使用者歷史上，多加一個「看起來更對」的機制（衰減、類、神經 cache）常常量不到好處。複雜度要用淨增益買，不能用故事買。

（已封閉方向不再展開：全域重排器、節點神經專家、加大模型／LLM、AUC/MRR 當 GO。）

---

## 3. 本票最關鍵：selection bias

### 3.1 這個訊號是什麼

Correction / 使用者改選 / implicit feedback，在本題裡**不是完整決策分佈**。它是：

> 只在「使用者不滿意到願意出手」時留下的資料。

統計上這是 sample selection（Heckman 型）、也是 MNAR、也是 positive-unlabeled：沒被記錄的決策裡，混著「引擎做對」「使用者沒注意」「使用者懶得改」。派遣票第 1 節已經用 23 個帶 engine_choice 的讀音給了方向性佐證（26.1% 加入引擎選字後相異字數變多）。

Apple 2021 用幾乎同一句話描述 ASR：只記使用者手動修改，資料會嚴重偏向「被抓到的錯誤」。

### 3.2 文獻有沒有處理過 implicit-feedback selection bias

有，而且是成熟領域。三條主線：

| 主線 | 代表 | 它校正的是什麼 | 最小必要訊號 |
|---|---|---|---|
| 反事實 LTR / IPS | Joachims, Swaminathan, Schnabel 2015–2017 | 位置／呈現偏差：被排前面的比較容易被點 | 每次出示的排序 + 點／沒點 + propensity \(P(\text{observe}\mid\text{position, context})\) |
| MNAR 推薦 | Saito et al. 2020 | 沒點 ≠ 不喜歡，且缺失與熱門程度有關 | 曝光紀錄，或可估的 \(P(\text{observed}\mid\text{item, user})\) |
| 把推薦當處理 | Schnabel et al. 2016 | 系統決定讓你看到什麼，造成選擇偏差 | 處理指派機率（logging policy） |

它們共同的數學起點：無偏估計長這樣

\[
\hat{R} = \frac{1}{n}\sum_{i:\,O_i=1}\frac{\ell_i}{\hat{p}_i}
\]

其中 \(O_i=1\) 表示這筆被觀察到，\(\hat{p}_i = P(O_i=1\mid x_i, a_i)\)。沒有 \(p_i\)，這個和不是目標風險的估計量。

### 3.3 沒有完整 denominator 時，這些校正能不能用？

**不能。** 不是「效果比較差」，是**識別條件不成立**。

原因：

1. Propensity \(P(\text{這次決策被寫進 log})\) 在本題裡 ≈ \(P(\text{使用者出手修正}\mid\text{引擎選擇}, \text{正確字}, \text{情境})\)。這正是未知量。沒有「引擎做對」的紀錄，估不出來。
2. IPS 的和只對「被觀察到的」加權。沒有未觀察樣本的計數（分母），連 self-normalized IPS（SNIPS）都沒有正規化常數。
3. Doubly robust 需要一個結果模型 **加上** propensity；少一個就退回有偏。
4. 隨機探索（ε-greedy 偶爾打亂候選）可以**製造**已知 propensity，但那是新的實驗設計，不是對舊 log 的事後校正。

### 3.4 最小額外訊號是什麼

要讓 IPS／反事實方法開始有資格被討論，最少要其一：

| 最小訊號 | 能做什麼 | 還不能做什麼 |
|---|---|---|
| **A. 每次定案都記一筆**：讀音、引擎第一名、使用者最終字、是否改過 | 有 denominator；可算傷害、可估 \(P(\text{改}\mid\text{引擎選})\)；可做最粗的 IPS | 仍沒有「其他候選被看到沒有」 |
| **B. 記候選清單與位置**（使用者有沒有打開同音表） | 呈現偏差可建模，Joachims 型 IPS 才對得上 | 沒打開清單的接受，仍是弱監督 |
| **C. 已知的隨機探索**（例如 1% 決策打亂前兩名） | 得到已知 propensity，反事實評估才有理論 | 探索本身有 UX 成本 |
| **D. 只加「引擎當時選了什麼」**（比 A 更小） | 足夠做 McNemar／配對比較「改寫規則前後」；仍不是無偏偏好估計 | 不能把 correction 當正例去訓個人模型 |

**D 是現在就能做、也最該做的儀器**，但它**不能**讓你把舊的 595 筆校正成無偏偏好。它只能讓你以後不再盲目。

沒有 A–C 之前，任何「用 correction 學一個會改排序的模型」在文獻上都屬於 **有偏、不可評估傷害的閉環**。安全的反應不是找更好的估計量，是**不要用這個訊號去改排序**，或只允許它在極窄、可手動檢查的規則下出手。

---

## 4. 候選方法八格

以下每個方法都填滿八格。只靠感覺的不進前三名。

### M1. 全域–使用者線性／動態插值（Jelinek–Mercer / Mansour data interpolation）

1. **核心機制**：使用者模型與全域模型做凸組合，λ 是偏離上限。不是「有記憶就加分」，是「最多把這麼多機率質量從全域挪走」。
2. **為什麼可能適合**：稀疏時 λ 可以極小；結構上避免使用者模型獨裁；Gboard 的 Bayesian interpolated 5-gram、Adhikary 的 0.75/0.25 混合物都是這個形狀。
3. **為什麼可能翻車**：λ 若用 correction 頻率來調，會把偏差寫進唯一的安全閥；衝突讀音上 \(P_{\text{user}}\) 本身就是銅板。
4. **支持證據**：Bellegarda 2004；Clarkson & Robinson 1997；Mansour et al. 2020；Adhikary & Vertanen 2023 混合物權重。
5. **衝突證據**：本題沒有 denominator，無法用 held-out 調 λ；correction-only 會讓 \(P_{\text{user}}\) 偏向反預設。
6. **需要什麼資料**：要一個使用者分佈。完整定案文本最好；只有 correction 時 \(P_{\text{user}}\) 有偏。**不 strictly 需要 denominator 才能跑，但需要 denominator 才能安全地調 λ。**
7. **最小可否證實驗**：時間切分：前 10 天估 \(P_{\text{user}}\)（就算有偏），後 5 天看「插值 vs 純全域」在**有記引擎選擇的那些位置**上誰對。λ ∈ {0, 0.05, 0.1, 0.2}。
8. **什麼結果就 DROP**：任何 λ>0 在後段的配對錯誤數 ≥ 純全域；或只在 correction 位置變好、在未校正位置（若已開始記）變差。

### M2. 階層 backoff／插值使用者記憶（開 β、粗 key 先說話）

1. **核心機制**：細 key（前詞+讀音+詞）沒有足夠、夠一面倒的證據時，退到（讀音+詞）或（讀音）。跟「存一筆就在那個 key 上等第二次」不同：證據被折進較穩的層，而不是被門檻丟掉。
2. **為什麼可能適合**：80% 條目 count=1 是細 key 把證據打散的直接症狀；這正是 Katz／JM／Stupid Backoff 要解的問題。
3. **為什麼可能翻車**：correction-only 的偏差在粗層會**擴散**——一個常被改的讀音會讓粗層全面偏向反預設字。衝突讀音中位 0.50，粗層也無法決勝負。
4. **支持證據**：Katz 1987；Chen & Goodman 1996/1999；Brants et al. 2007。
5. **衝突證據**：本題 73.7% 重複落在衝突讀音；Chen & Goodman 沒處理 MNAR。派遣票自己的資料顯示粗層也不乾淨。
6. **需要什麼資料**：計數表即可。**不需要 denominator 就能跑。** 需要 denominator 才能知道粗層有沒有在幫倒忙。
7. **最小可否證實驗**：同一份時間切分，比較 (a) 現況細 key + k=2 (b) 開 backoff 到讀音層、僅當該層熵低（例如主流佔比 ≥ 0.8 且 n≥3）才允許覆寫。
8. **什麼結果就 DROP**：開 backoff 之後，在「該讀音有 ≥2 個不同選字」的位置，與引擎預設相反的字被選中的次數上升（在已有 engine_choice 的子集上可看）。

### M3. 決策時棄權／選擇性出手（本票 C 的可落地版）

1. **核心機制**：個人化模組對**每一次決策**輸出「覆寫或棄權」。棄權 = 全域原樣。判斷的是「這次值不值得碰」，不是「這筆記憶在不在」。
2. **為什麼可能適合**：中位主流佔比 0.50 的讀音，正確答案就是棄權。Wang 2019 在真正的鍵盤個人化上證明「平均變好、一部份人變差」，並要求 gate。
3. **為什麼可能翻車**：gate 特徵若用 correction 頻率本身，會把偏差做成門；過嚴則個人化永遠不開火，等於沒做；過寬則回到加分表。
4. **支持證據**：Geifman & El-Yaniv 2017；Wang et al. 2019 的 gating 主張與 L=1.0 的負平均。
5. **衝突證據**：沒有 denominator 就畫不出真實 risk–coverage，只能用代理規則（佔比、n、新近、是否衝突）。代理規則可能與真實風險錯位。
6. **需要什麼資料**：現有 correction 計數就能做**保守規則版**。要校準閾值需要 denominator。**規則版 NOW；校準版 AFTER INSTRUMENTATION。**
7. **最小可否證實驗**：規則：僅當 (同一讀音下單一選字佔比 ≥ 0.8) ∧ (n≥3) ∧ (最近一次觀察在半衰期內) 才允許 soft/hard 覆寫，其餘棄權。時間切分看：開火位置的下一筆是否仍選同一字；棄權位置不要變差。
8. **什麼結果就 DROP**：開火位置的「下一筆同讀音」選了別的字的比例 ≥ 0.5（等於在銅板上出手）；或開火次數趨近 0（規則無操作空間）。

### M4. Contextual bandit（LinUCB 等）

1. **核心機制**：每個候選是手臂，用上下文估計期望報酬與不確定度；只在「偏離預設的 UCB 高於預設」時出手。跟加分表不同：它顯式做探索／利用，且每次都更新報酬。
2. **為什麼可能適合**：概念上最貼「這一決策的效用」。
3. **為什麼可能翻車**：沒有每次決策的報酬就不是 bandit。Correction-only 會把「沒被改」當成「沒發生」，探索項會瘋。
4. **支持證據**：Li et al. 2010 LinUCB。
5. **衝突證據**：Li et al. 有完整出示與點擊；本題沒有。Swaminathan & Joachims 2015 證明離線學 bandit 必須有 propensity。
6. **需要什麼資料**：**需要 denominator**（每次出示的選擇與是否被改／被用）。沒有則 NOT FEASIBLE。
7. **最小可否證實驗**：先有 A 類日誌至少數週，再在模擬器裡用 logging policy 做 off-policy 評估；線上 ε 探索是下一步。
8. **什麼結果就 DROP**：off-policy 下任何非零探索的估計傷害區間跨過 0 且下限為負；或 propensity 小到 IPS 權重爆掉（見 F7）。

### M5. Recency-weighted cache / PPM，吃已定案全文，小 λ 插值

1. **核心機制**：不學「使用者喜歡哪個同音字」的偏好表。只做一件事：最近用過的詞／字，機率暫時升高。PPM 再依當前上下文長度自動退避。跟加分表不同：沒有「這是偏好」的語義，只有「這是最近的世界狀態」。
2. **為什麼可能適合**：44.7% 事件是重複、中位間隔 2 小時——這是 cache 的主場。Fowler / Adhikary / Kuhn / Clarkson / Gboard user history 都量過或部署過。可解釋、便宜、記憶體就是一個小視窗。
3. **為什麼可能翻車**：若 cache 改吃 correction，會變成「最近改過的反預設字」放大器。衝突讀音上 cache 會在兩個字之間振盪。長尾 hapax（72.9% 只出現一次）進 cache 幾乎沒有第二次被救的機會。
4. **支持證據**：Kuhn & De Mori 1990；Clarkson & Robinson 1997；Fowler et al. 2015（5.7%→4.6% WER）；Adhikary & Vertanen 2023（相對 KS +9.9%、相對 WER −36%）；Hard et al. 2018 的 user history n-gram。
5. **衝突證據**：上述全部吃完整文本。Fowler 自己發現衰減 cache ≈ unigram cache。本題衝突讀音中位 0.50 是 cache 的天敵。
6. **需要什麼資料**：執行期 IME **已經看得到已定案文本**，不必等研究用 log。評估淨效應需要 denominator。**機制 NOW；宣稱淨增益 AFTER INSTRUMENTATION。**
7. **最小可否證實驗**：裝置上對已定案字做 unigram cache（視窗＝數小時到 1–2 天），只對「該讀音在視窗內只出現過一個字」的位置加很小的 λ；衝突讀音不加。用新日誌（含引擎選擇）做前後配對。
8. **什麼結果就 DROP**：在「視窗內該讀音只出現一值」的位置，下一筆同讀音仍對不上的比例不低於基線；或任何衝突讀音被 cache 改寫後錯誤上升。

### M6. On-device 微調全域神經模型（DeepType / Wang FPE）

1. **核心機制**：從全域參數出發，用裝置上的使用者文本做 SGD。跟加分表不同：改的是整個分佈，不是一條 key。
2. **為什麼可能適合**：DeepType 報告約 20% 效率提升；Wang 在部分超參數下平均 +14.5%。
3. **為什麼可能翻車**：Wang 證明超參數錯了平均就是負的。本題是 595 筆 correction、不是數百萬 token。已封閉「加大模型／換神經架構」。單使用者、無聯邦評估基礎設施，也做不到 Wang 那種「先在影子模式看分佈再決定部署」。
4. **支持證據**：Xu et al. 2018 DeepType；Wang et al. 2019。
5. **衝突證據**：兩者都用完整輸入 cache，且資料量比本題大幾個數量級；Wang L=1.0 平均為負。本題已量過節點神經專家條件 AUC 0.459。
6. **需要什麼資料**：大量已定案文本 + held-out。Correction-only **不夠**。
7. **DROP 條件（先驗即可）**：在本題資料量與已封閉神經線的前提下，**現在就該 DROP**，不必再做。

### M7. IPS / 反事實 LTR / MNAR 校正後再學個人模型

1. **核心機制**：先估計「這筆 correction 被觀察到的機率」，再把損失除以該機率，試圖還原完整風險。跟加分表不同：它承認樣本不是總體。
2. **為什麼可能適合**：問題診斷完全正確——本題就是 selection bias。
3. **為什麼可能翻車**：沒有 propensity、沒有未觀察樣本，公式不能用。硬估 \(p\) 會在 2.5 筆／讀音上方差爆炸（F6、F7）。
4. **支持證據**：Joachims et al. 2017；Swaminathan & Joachims 2015；Schnabel et al. 2016；Saito et al. 2020。
5. **衝突證據**：上述每一篇都把「已知或可估的 propensity／logging policy」當前提。本題沒有。
6. **需要什麼資料**：**需要 denominator + 出示紀錄，最好再加一點隨機探索。** 否則 NOT FEASIBLE。
7. **最小可否證實驗**：先做第 3.4 節的儀器 A 或 C，再在新資料上比較 IPS 與未加權。舊 595 筆**不要**拿來估 propensity。
8. **什麼結果就 DROP**：propensity 模型在校準圖上遠離對角線；或 IPS 權重的 99 分位 > 某個預先寫死的上限（例如 20）且 clip 前後結論相反。

### M8. 明示使用者詞典 + 極窄 hard override（業界 CJK 的保守子集）

1. **核心機制**：只有使用者**明示**「這個讀音我要這個詞」（加詞、或連續多次在同一乾淨讀音上選同一字）才寫入硬覆寫。不是從 implicit correction 統計推論偏好。
2. **為什麼可能適合**：Mozc／各家 CJK IME 都把使用者詞典當一等功能；明示訊號沒有 selection bias（使用者知道自己在教系統）。對 26.3% 落在乾淨讀音上的重複，hard path 可能合法。
3. **為什麼可能翻車**：覆蓋率極低（長尾 72.9% hapax）；若把「點過一次同音」當成明示，就退化回 UOM。衝突讀音不該進詞典。
4. **支持證據**：Mozc 開源使用者詞典／歷史預測器（工程產物）；Apple 日文使用者詞典說明（產品文件，非論文）。
5. **衝突證據**：沒有受控實驗證明「明示詞典」在注音同音消歧上有淨增益；覆蓋率可能小到量不到。
6. **需要什麼資料**：明示動作。不需要 denominator 才能實作；需要 denominator 才能知道沒誤傷。
7. **最小可否證實驗**：只對「該讀音歷史上只出現過一個字、且出現 ≥3 次」寫 hard；其餘不寫。看這些讀音的後續是否穩定。
8. **什麼結果就 DROP**：被寫入 hard 的讀音，後續出現第二個不同選字的比例不低（表示「乾淨」是小樣本幻覺）。

---

## 5. 前三名

排序原則：外部證據是否量過淨增益或量過傷害、與本題資料體制是否同一 abstraction、現在能不能做、會不會在沒有分母時偷偷造成不可見傷害。只靠感覺的不進榜。

### 第一名　M5. 已定案全文上的 recency-weighted cache／PPM + 小 λ 插值

**可行性：機制 NOW（執行期已有定案文本）；淨效應 AFTER INSTRUMENTATION**

這是文獻與業界唯一反覆獨立量到正向淨增益、而且機制便宜可解釋的家族。Gboard 今天仍用 user history n-gram 疊在主 LM 上；Fowler / Adhikary 在鍵盤模擬上給了數字；Kuhn / Clarkson 是理論與語音辨識上的祖先。它跟 UOM 的 abstraction 不同：不宣稱「這是偏好」，只宣稱「這是最近的世界」。

八格見 §4 M5。額外約束（否則它會退化成 UOM）：

- **禁止**用 correction 事件填 cache
- 衝突讀音（視窗內出現 ≥2 個不同字）**必須棄權**
- λ 先驗上限要小（Adhikary 的 0.25 已是偏積極；本題應更小）
- 視窗對齊「中位重複間隔 2 小時」這個已給事實，不要用 7 天半衰期去記一次 hapax

### 第二名　M3. 決策時棄權（選擇性出手），規則版

**可行性：NOW**

Wang 2019 是鍵盤個人化領域最接近「個人化會傷人」的生產級證據；Geifman & El-Yaniv 給了「先定風險再定覆蓋」的語言。本題衝突讀音中位 0.50，正確的決策理論答案就是棄權。這直接改的是「出手單位」：從「記憶存在」改成「這次決策允許被碰」。

八格見 §4 M3。它現在就能套在既有 UOM 外面當保險，不必先承認 UOM 值得救。

若與第一名一起做：cache／PPM 負責「最近用過的穩定詞」；棄權規則負責「什麼情況連 cache 都不許說話」。兩者都是保守機制，不是兩個互相競爭的聰明模型。

### 第三名　M1 + M2 的交集：保守插值 + 階層退避（只在低熵層允許說話）

**可行性：結構 NOW；λ 與層門檻 AFTER INSTRUMENTATION 才能調，不能用 correction 調**

這是 A+B 的經典答案，也是 Chen & Goodman、Katz、Mansour、Gboard 5-gram 的共同形狀。它比第一名更「像一個使用者 LM」，因此也更容易在有偏訊號上過擬合——所以排第三，且**餵進去的必須是定案全文（或至少接受+拒絕），不能是 595 筆 correction**。

八格見 §4 M1、M2。合成規則：

- 使用者 LM 用 backoff／插值估計
- 再與全域做小 λ 插值
- 只有該層主流佔比夠高才讓使用者 LM 的質量非零（這是把 M3 嵌進層裡）

未進前三但要標明的：

| 方法 | 標籤 | 理由 |
|---|---|---|
| M4 LinUCB | AFTER INSTRUMENTATION，目前 NOT FEASIBLE | 沒有每次決策報酬 |
| M6 神經微調 | NOT FEASIBLE | 資料量不夠；Wang 證明可傷人；神經線已封閉 |
| M7 IPS／CLTR | AFTER INSTRUMENTATION，舊 log NOT FEASIBLE | 沒有 propensity 識別不出來 |
| M8 明示詞典 | NOW（窄） | 合法但覆蓋小；可當 hard path 的唯一入口，不當主策略 |

---

## 6. 兩句指定回答

**如果你認為既有的 user override model 這個 abstraction 根本不值得救，直接說。**

不值得救成主路徑。細 key + 加分 + correction-only，是把三個已知會單獨失敗的選擇疊在一起：稀疏時細 key 把證據打散（Chen & Goodman / Katz 要你 backoff）、加分沒有 \((1-\lambda)\) 這種結構上限（Bellegarda / Mansour 要你插值）、correction-only 不是偏好樣本（Joachims / Saito / Apple）。Hard LRU 當「明示、乾淨、高頻讀音的窄覆寫」可以留一個角落；soft path 用 correction 計數去推 DP，文獻不支持。

**如果你認為需要的不是更好的 gate，而是根本不需要 gate，也直接說。**

不需要「更好的 gate 研究」。若繼續用 correction 表去改排序，你需要的是近乎殘酷的棄權（第二名），那不是一個值得開題的學習問題，是一張小規則表。若改吃已定案全文並做小 λ 插值（第一名），**插值本身就是保守機制**，不需要再學一個 gate。把精力花在「更聰明的什麼時候開火」上，是在一個不該開火的訊號上找開火理由。

---

## 7. 儀器建議（不是本票決策，只標最小額外訊號）

若統治局要讓以後的個人化研究變得可評估：

1. **每次定案記一筆**：讀音、引擎第一名、最終字、是否改過。沒有這個，傷害在結構上繼續不可算。
2. 不要回填舊 595 筆去估 propensity。
3. 有 (1) 之後，GO 判準用配對錯誤／McNemar，不要用 AUC/MRR。這與已封閉方向一致。

以上是外部研究。repo 現況與最終決策交回統治局。
