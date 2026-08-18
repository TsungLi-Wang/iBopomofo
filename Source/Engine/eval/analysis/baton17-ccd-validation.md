# 棒⑰ — Prototype-001 Validation & Ablation

> **不修改 production、不 merge、不 enable、不接輸入法、不跑正式 ship test。**
> 本棒只驗證 ⑯ 已經做出來的 Prototype-001。

## 事前判定（在看到結果之前寫定，未事後修改）

**GO** 需同時成立：① FULL 明顯優於 NO-INTERACTION ② FULL 的改善不能完全由 numeric
features 解釋 ③ RESCUE/DAMAGE 結構合理 ④ candidate identity sanity check 通過
⑤ 獨立驗證集若可用，FULL 沒有明顯崩潰 ⑥ inference cost 合理。

**NO-GO** 任一成立：FULL ≈ NO-INTERACTION ／ 效果完全來自 numeric features ／
independent validation 明顯失效 ／ damage ≥ rescue ／ 發現 leakage 或 protocol 問題。

---

## 0. 判定：🔴 **NO-GO**

三個事前 NO-GO 條件同時命中：

| NO-GO 條件 | 實測 | 命中 |
|---|---|---|
| FULL ≈ NO-INTERACTION | FULL net **+1,543** vs NO-INTERACTION **+1,633** —— **交互不但沒幫忙，還略微有害** | ✅ |
| independent validation 明顯失效 | 跨語料評估 FULL net **−266**（由 +1,543 翻負）| ✅ |
| damage ≥ rescue | 獨立集上 FULL rescue 77 / damage 343 | ✅ |

---

## PART 1 — 完整重現⑯

用完全相同的 dataset、canonical fold、feature pipeline、checkpoint、protocol。

| 指標 | ⑯ 報告 | 本棒重跑 | 一致 |
|---|---|---|---|
| top-1（engine / proto）| 0.7975 / 0.8563 | 0.7975 / 0.8563 | ✅ |
| top-2 | 0.9374 | 0.9374 | ✅ |
| rescue | 2,443 | 2,443 | ✅ |
| damage | 900 | 900 | ✅ |
| net | +1,543 | +1,543 | ✅ |
| precision | 0.6306 | 0.6306 | ✅ |
| override | 3,874 | 3,874 | ✅ |
| candidate_absent | 15 | 15 | ✅ |
| 推論耗時 | 2.9 s | 3.6 s（含載入，機器負載差異）| ✅ |

**逐項重現，無需修正。** 進入 ablation。

---

## PART 2–4 — 核心 Ablation

四個版本共用同一份 dataset、canonical 5-fold document split、training samples、
evaluation population、random seed（20260818）、optimizer（Adam lr 1e-3 wd 1e-5）、
training budget（4 epochs / batch 256）、stopping rule、inference protocol（純 argmax）。
**沒有為任何一個版本調過 hyperparameter。**

### 訓練語料 held-out fold 0（26,247 個單字節點）

| Metric | Engine | **FULL** | NO-INTERACTION | NO-NUMERIC | CONTEXT-ONLY |
|---|---:|---:|---:|---:|---:|
| top-1 | 0.7975 | 0.8563 | **0.8597** | 0.8090 | 0.6967 |
| top-2 | — | 0.9374 | **0.9383** | 0.9148 | 0.7610 |
| rescue | — | 2,443 | 2,272 | **2,673** | 509 |
| damage | — | 900 | **639** | 2,371 | 3,155 |
| **net** | — | +1,543 | **+1,633** | +302 | **−2,646** |
| precision | — | 0.6306 | **0.6657** | 0.4462 | 0.1074 |
| override | — | 3,874 | 3,413 | 5,991 | 4,741 |
| candidate_absent | 15 | 15 | 15 | 15 | 15 |
| 推論（含載入）| — | 3.6 s | 3.4 s | 3.6 s | 3.3 s |

`CONTEXT-ONLY` 因為所有候選同分，argmax 落在第 0 個候選 ——
候選依 unigram 分數排序，所以它等同「永遠取詞頻第一名」這個基準。

### 三個直接答案

* **candidate × context interaction 貢獻 = 負的。**
  拿掉四組交互後 net 從 +1,543 **上升**到 +1,633、precision 從 0.631 上升到 0.666。
* **numeric features 貢獻 = 決定性。**
  拿掉後 net 從 +1,543 掉到 **+302**（−80%），damage 從 900 暴增到 2,371。
* **candidate-independent 完全不可行。** CONTEXT-ONLY net **−2,646**。

⚠️ 本棒的 evaluation population 與 ⑭ 系列的 D2 不同，
**net 不得與 ⑭-R（+69）／⑭-S（+53）直接比較**：`NOT COMPARABLE`。


---

## PART 5 — FULL 的 RESCUE / DAMAGE 實際長什麼樣

**等距抽樣（step = 總數 // N），不是人工挑選。**


### RESCUE（25 筆）

```
  Context : 八點檔演員[?]凱日前奏是
  Reading : ㄨㄤˋ   Cands: 望/忘/旺/妄/王/朢/迋/莣
  Engine  : 望   Proto: 王   Gold: 王
  Scores  : 王:+6.72 望:+0.99 忘:-2.07 妄:-2.51 旺:-3.74

  Context : 看到違規當作[?]看到
  Reading : ㄇㄛˋ   Cands: 末/莫/默/墨/漠/寞/陌/沫 …
  Engine  : 默   Proto: 沒   Gold: 沒
  Scores  : 沒:+3.95 末:+0.61 默:+0.14 磨:-2.00 沫:-2.68

  Context : 本名[?]兼課
  Reading : ㄓㄥˋ   Cands: 政/正/證/症/鄭/幀/掙/証
  Engine  : 正   Proto: 鄭   Gold: 鄭
  Scores  : 鄭:+7.13 證:+3.20 政:+2.95 幀:+2.94 正:+2.31

  Context : 一口氣大漲[?]
  Reading : ㄩˊ   Cands: 於/魚/餘/漁/于/余/愉/娛 …
  Engine  : 於   Proto: 逾   Gold: 逾
  Scores  : 逾:+5.54 於:+4.34 魚:+4.19 于:+1.27 愉:+1.03

  Context : 一位妹子導遊[?]待我
  Reading : ㄌㄞˋ   Cands: 賴/睞/瀨/籟/癩/來/賚/藾 …
  Engine  : 賴   Proto: 來   Gold: 來
  Scores  : 來:+9.18 賴:+2.70 睞:-0.17 癩:-0.31 賚:-0.33

  Context : 刷[?]為但
  Reading : ㄐㄧㄤˋ   Cands: 將/降/醬/漿/匠/彊/強/絳 …
  Engine  : 將   Proto: 醬   Gold: 醬
  Scores  : 醬:+5.47 降:+3.47 將:+2.83 漿:+2.14 絳:-0.53

  Context : 在比賽[?]
  Reading : ㄉㄧˋ   Cands: 地/第/弟/帝/遞/締/蒂/諦 …
  Engine  : 地   Proto: 第   Gold: 第
  Scores  : 第:+5.45 地:+4.68 帝:+3.30 弟:+3.27 的:+2.85

  Context : 他們都必須學[?]找到自己與自
  Reading : ㄓㄨˇ   Cands: 主/煮/矚/囑/貯/拄/渚/麈 …
  Engine  : 主   Proto: 著   Gold: 著
  Scores  : 著:+5.38 主:+5.36 煮:+2.60 屬:+1.72 矚:+1.56

  Context : 大未來應建立[?]成熟的校長責
  Reading : ㄍㄥ   Cands: 耕/庚/羹/賡/焿/更/粳/浭 …
  Engine  : 耕   Proto: 更   Gold: 更
  Scores  : 更:+9.62 庚:-2.73 耕:-3.43 羹:-4.31 焿:-4.32

  Context : 對[?]來得
  Reading : ㄅㄟˋ   Cands: 被/備/背/貝/輩/倍/臂/焙 …
  Engine  : 備   Proto: 貝   Gold: 貝
  Scores  : 貝:+2.75 背:+1.94 備:+1.84 被:+1.27 倍:+0.37

  Context : 建立[?]火災警示
  Reading : ㄘㄨㄥ   Cands: 聰/匆/蔥/囪/璁/從/樅/瑽 …
  Engine  : 蔥   Proto: 從   Gold: 從
  Scores  : 從:+6.59 蔥:+3.93 聰:-1.86 囪:-2.51 熜:-3.32

  Context : [?]台鐵東山車站
  Reading : ㄘㄨㄥ   Cands: 聰/匆/蔥/囪/璁/從/樅/瑽 …
  Engine  : 蔥   Proto: 從   Gold: 從
  Scores  : 從:+7.12 蔥:-2.18 鍐:-3.06 囪:-4.30 聰:-4.32

  Context : [?]前師父跟老闆
  Reading : ㄅㄢˇ   Cands: 版/板/闆/阪/坂/舨/鈑/粄 …
  Engine  : 版   Proto: 板   Gold: 板
  Scores  : 板:+3.67 版:+2.99 阪:+0.39 坂:-1.73 舨:-2.19

  Context : 盟大使一具酸[?]
  Reading : ㄅㄠˋ   Cands: 報/暴/抱/爆/鮑/豹/刨/趵 …
  Engine  : 報   Proto: 爆   Gold: 爆
  Scores  : 爆:+3.47 報:+2.97 抱:+0.09 暴:-0.54 鮑:-0.66

  Context : 現在球隊成績[?]
  Reading : ㄕㄤˇ   Cands: 賞/晌/上
  Engine  : 賞   Proto: 上   Gold: 上
  Scores  : 上:+6.64 晌:-2.16 賞:-8.46

  Context : 是未來每個月[?]辦一場跟求職
  Reading : ㄏㄨㄟˇ   Cands: 毀/悔/誨/虫/燬/虺/會/賄 …
  Engine  : 毀   Proto: 會   Gold: 會
  Scores  : 會:+8.25 毀:+0.40 悔:-2.19 虫:-3.49 誨:-3.51

  Context : 資人千萬不要[?]長線多頭邏輯
  Reading : ㄑㄧㄤ   Cands: 槍/腔/鏘/羌/蹌/鎗/蜣/嗆 …
  Engine  : 槍   Proto: 將   Gold: 將
  Scores  : 將:+4.56 搶:+2.37 槍:+0.99 腔:-2.15 鏘:-3.45

  Context : [?]氣與食環傳奇
  Reading : ㄕㄤˋ   Cands: 上/尚/爙/姠/仩/↑/🔼/⬆️ …
  Engine  : 上   Proto: 尚   Gold: 尚
  Scores  : 尚:+4.82 上:+4.51 仩:-3.60 爙:-7.38 ☝︎:-7.87

  Context : [?]火鍋吃到飽
  Reading : ㄘㄨㄥ   Cands: 聰/匆/蔥/囪/璁/從/樅/瑽 …
  Engine  : 蔥   Proto: 從   Gold: 從
  Scores  : 從:+6.11 蔥:+1.32 聰:-3.30 鍐:-3.51 棇:-3.78

  Context : 麵包[?]吃完還會詢問
  Reading : ㄇㄛˋ   Cands: 末/莫/默/墨/漠/寞/陌/沫 …
  Engine  : 末   Proto: 沒   Gold: 沒
  Scores  : 沒:+3.59 末:+1.46 陌:-3.01 墨:-3.54 寞:-3.79

  Context : 還有三樓特展[?]
  Reading : ㄕˋ   Cands: 是/事/市/式/示/視/世/士 …
  Engine  : 是   Proto: 室   Gold: 室
  Scores  : 室:+5.23 是:+4.32 式:+3.88 事:+3.32 市:+3.03

  Context : [?]語法比
  Reading : ㄓㄚ   Cands: 扎/渣/喳/查/楂/齇/柤/皻 …
  Engine  : 渣   Proto: 查   Gold: 查
  Scores  : 查:+2.10 扎:-2.51 渣:-2.81 喳:-3.91 楂:-6.90

  Context : [?]心存除無須為
  Reading : ㄓㄤˇ   Cands: 掌/漲/長/仉/鞝
  Engine  : 掌   Proto: 長   Gold: 長
  Scores  : 長:+3.50 漲:-0.33 掌:-2.57 仉:-6.74 鞝:-8.21

  Context : 口水[?]的麻辣很開胃
  Reading : ㄐㄧ   Cands: 機/基/積/激/績/雞/跡/蹟 …
  Engine  : 機   Proto: 雞   Gold: 雞
  Scores  : 雞:+6.91 基:+6.49 機:+5.75 嘰:+4.64 磯:+3.07

  Context : 而是[?]券商軟體做股
  Reading : ㄎㄢ   Cands: 刊/堪/勘/戡/龕/看/嵁
  Engine  : 刊   Proto: 看   Gold: 看
  Scores  : 看:+8.34 刊:+1.61 堪:+0.53 勘:-0.12 戡:-0.98
```


### DAMAGE（25 筆）

```
  Context : 所以盡可能[?]把下位者
  Reading : ㄉㄜ˙   Cands: 的/得/地
  Engine  : 的   Proto: 地   Gold: 的
  Scores  : 地:+5.79 的:+3.12 得:-10.99

  Context : 晶圓[?]忍一時判
  Reading : ㄉㄧㄢˋ   Cands: 電/店/殿/墊/甸/奠/澱/佃 …
  Engine  : 電   Proto: 店   Gold: 電
  Scores  : 店:+2.52 電:+2.20 墊:-0.33 澱:-2.73 殿:-2.81

  Context : [?]期望界引入中
  Reading : ㄩㄢˊ   Cands: 員/原/元/園/源/圓/援/緣 …
  Engine  : 原   Proto: 元   Gold: 原
  Scores  : 元:+3.54 原:+3.43 援:+1.89 員:+1.62 園:+1.01

  Context : 子兵法爛熟污[?]
  Reading : ㄒㄧㄣ   Cands: 心/新/辛/欣/薪/馨/鑫/莘 …
  Engine  : 心   Proto: 新   Gold: 心
  Scores  : 新:+2.89 薪:+2.60 心:+2.31 芯:+0.84 辛:+0.42

  Context : [?]握壽司
  Reading : ㄕㄡˇ   Cands: 手/首/守/掱/艏
  Engine  : 手   Proto: 首   Gold: 手
  Scores  : 首:+3.55 手:+3.42 守:+3.35 艏:-7.23 掱:-7.56

  Context : 立法院後生毀[?]財團法人後生
  Reading : ㄐㄧˊ   Cands: 及/即/集/級/極/擊/急/藉 …
  Engine  : 及   Proto: 吃   Gold: 及
  Scores  : 吃:+4.79 及:+2.59 極:+2.50 吉:+2.47 急:+0.81

  Context : 者設違反美國[?]中港澳地區的
  Reading : ㄉㄨㄟˋ   Cands: 對/隊/兌/懟/碓/譈/濧/薱 …
  Engine  : 對   Proto: 隊   Gold: 對
  Scores  : 隊:+6.19 對:+4.19 譈:-4.70 兌:-5.02 懟:-5.50

  Context : 不是非黑[?]白
  Reading : ㄐㄧˊ   Cands: 及/即/集/級/極/擊/急/藉 …
  Engine  : 即   Proto: 吃   Gold: 即
  Scores  : 吃:+6.51 即:+3.67 吉:+2.57 急:+1.83 脊:+1.55

  Context : 搭配一個小點[?]一杯飲料
  Reading : ㄐㄧˊ   Cands: 及/即/集/級/極/擊/急/藉 …
  Engine  : 及   Proto: 吃   Gold: 及
  Scores  : 吃:+4.83 及:+4.59 即:+2.60 急:+1.75 集:+0.99

  Context : 較下個人更新[?]金木雕握
  Reading : ㄕㄤˇ   Cands: 賞/晌/上
  Engine  : 賞   Proto: 上   Gold: 賞
  Scores  : 上:+7.09 晌:+0.57 賞:-0.61

  Context : 若[?]看兄弟隊使
  Reading : ㄓˇ   Cands: 只/指/止/紙/址/旨/祉/趾 …
  Engine  : 只   Proto: 址   Gold: 只
  Scores  : 址:+3.74 只:+3.59 指:+2.64 止:+2.14 紙:-0.57

  Context : 發生一個[?]讓我笑死的狀
  Reading : ㄎㄨㄞˋ   Cands: 快/塊/筷/檜/膾/劊/儈/會 …
  Engine  : 快   Proto: 會   Gold: 快
  Scores  : 會:+6.94 快:+4.25 塊:-0.29 膾:-2.22 筷:-3.30

  Context : [?]比歐知道這項
  Reading : ㄌㄨˇ   Cands: 魯/滷/擄/虜/櫓/鹵/擼/艣 …
  Engine  : 魯   Proto: 滷   Gold: 魯
  Scores  : 滷:+2.37 魯:+2.24 虜:-3.38 擄:-3.90 鹵:-4.14

  Context : 手機[?]的悠遊卡坐車
  Reading : ㄌㄧˇ   Cands: 理/裡/李/禮/里/哩/鯉/鋰 …
  Engine  : 裡   Proto: 李   Gold: 裡
  Scores  : 李:+2.58 裡:+2.29 里:+1.82 禮:-0.12 理:-2.32

  Context : 敲出[?]外野安打後一
  Reading : ㄧㄡˋ   Cands: 又/右/幼/誘/佑/祐/釉/柚 …
  Engine  : 右   Proto: 又   Gold: 右
  Scores  : 又:+4.71 右:+1.43 祐:-1.26 宥:-1.42 誘:-1.97

  Context : [?]出張南明下幾
  Reading : ㄔㄚˊ   Cands: 查/察/茶/碴/搽/槎/茬/鍤 …
  Engine  : 查   Proto: 茶   Gold: 查
  Scores  : 茶:+3.52 查:+2.82 察:+0.90 碴:-2.54 槎:-2.93

  Context : 灣及羹湯家烏[?]的實味效果
  Reading : ㄘㄨˋ   Cands: 促/醋/猝/簇/蹴/槭/蹙/趨 …
  Engine  : 醋   Proto: 錯   Gold: 醋
  Scores  : 錯:+2.44 醋:+2.39 猝:-0.44 卒:-1.12 蹙:-1.72

  Context : [?]哲西則因故事
  Reading : ㄌㄧㄣˊ   Cands: 林/臨/鄰/琳/淋/麟/遴/霖 …
  Engine  : 林   Proto: 淋   Gold: 林
  Scores  : 淋:+1.84 林:+0.93 臨:-0.75 麟:-0.95 鄰:-1.28

  Context : 卡[?]卡里崔
  Reading : ㄕˊ   Cands: 時/十/實/什/食/石/拾/蝕 …
  Engine  : 什   Proto: 時   Gold: 什
  Scores  : 時:+3.66 十:+2.60 什:+2.59 提:+2.33 食:+2.11

  Context : 完天魚[?]
  Reading : ㄨ   Cands: 屋/污/烏/巫/汙/嗚/ㄨ/鄔 …
  Engine  : 屋   Proto: 於   Gold: 屋
  Scores  : 於:+5.16 屋:+2.94 烏:+0.64 巫:+0.37 污:-0.70

  Context : 根據台中[?]院判決紀錄
  Reading : ㄉㄧˋ   Cands: 地/第/弟/帝/遞/締/蒂/諦 …
  Engine  : 地   Proto: 第   Gold: 地
  Scores  : 第:+5.01 地:+3.23 帝:+0.75 弟:-0.45 遞:-1.89

  Context : [?]的也不是自己
  Reading : ㄎㄨㄟ   Cands: 虧/窺/盔/鞹/闚/悝/噅/刲 …
  Engine  : 虧   Proto: 窺   Gold: 虧
  Scores  : 窺:+1.72 虧:+1.25 盔:-1.08 巋:-2.76 鞹:-3.05

  Context : 現行[?]交稅是一
  Reading : ㄑㄧˊ   Cands: 其/期/奇/旗/齊/騎/歧/祇 …
  Engine  : 期   Proto: 其   Gold: 期
  Scores  : 其:+4.69 期:+0.71 奇:+0.19 齊:-1.68 祈:-2.72

  Context : 嗯[?]一般般普通好
  Reading : ㄐㄧㄡˋ   Cands: 就/究/舊/救/鷲/舅/咎/臼 …
  Engine  : 就   Proto: 舊   Gold: 就
  Scores  : 舊:+5.26 就:+5.07 救:-1.27 咎:-2.51 究:-2.52

  Context : 去做正確的[?]
  Reading : ㄕˋ   Cands: 是/事/市/式/示/視/世/士 …
  Engine  : 事   Proto: 是   Gold: 事
  Scores  : 是:+7.27 事:+6.00 市:+4.46 試:+1.41 勢:+1.25
```


### KEEP-OK（10 筆）

```
  Context : 說本人不會[?]也不喜歡中國
  Reading : ㄇㄞˇ   Cands: 買/嘪/鷶
  Engine  : 買   Proto: 買   Gold: 買
  Scores  : 買:+4.14 嘪:-6.50 鷶:-8.23

  Context : 顯示民眾[?]
  Reading : ㄉㄨㄟˋ   Cands: 對/隊/兌/懟/碓/譈/濧/薱 …
  Engine  : 對   Proto: 對   Gold: 對
  Scores  : 對:+6.41 隊:+1.98 兌:-3.16 懟:-3.99 濧:-7.06

  Context : [?]力供應鏈已成
  Reading : ㄙㄨㄢˋ   Cands: 算/蒜/筭
  Engine  : 算   Proto: 算   Gold: 算
  Scores  : 算:+4.94 蒜:-2.95 筭:-7.86

  Context : 也是很多人[?]去拍照的重點
  Reading : ㄧㄠ   Cands: 要/邀/腰/妖/喲/么/夭/吆 …
  Engine  : 要   Proto: 要   Gold: 要
  Scores  : 要:+2.76 邀:+1.59 妖:-2.81 腰:-3.33 喓:-4.71

  Context : 如果答案是否[?]的
  Reading : ㄉㄧㄥˋ   Cands: 定/訂/錠/碇/啶/釘/萣/飣 …
  Engine  : 定   Proto: 定   Gold: 定
  Scores  : 定:+4.56 訂:+2.32 錠:-1.62 釘:-2.01 萣:-3.78

  Context : 星期六[?]中午時刻慢慢
  Reading : ㄉㄜ˙   Cands: 的/得/地
  Engine  : 的   Proto: 的   Gold: 的
  Scores  : 的:+7.28 地:-6.32 得:-10.09

  Context : 論反被設南打[?]
  Reading : ㄆㄚ   Cands: 趴/啪/葩/蚆/舥
  Engine  : 趴   Proto: 趴   Gold: 趴
  Scores  : 趴:+6.08 啪:-1.89 葩:-3.57 舥:-7.00 蚆:-8.65

  Context : 終是搜尋體驗[?]一部分
  Reading : ㄉㄜ˙   Cands: 的/得/地
  Engine  : 的   Proto: 的   Gold: 的
  Scores  : 的:+7.98 地:-4.06 得:-6.74

  Context : 家去面對最後[?]接
  Reading : ㄉㄜ˙   Cands: 的/得/地
  Engine  : 的   Proto: 的   Gold: 的
  Scores  : 的:+4.48 地:-5.39 得:-10.72

  Context : 元發生明身後[?]神隱
  Reading : ㄖㄥˊ   Cands: 仍/礽/陾
  Engine  : 仍   Proto: 仍   Gold: 仍
  Scores  : 仍:+0.80 礽:-6.88 陾:-10.07
```


---

## PART 6 — Candidate Identity Sanity Check

保留 context、候選集結構、數值特徵與 mask，**只把候選的字身分換成隨機字**（seed 20260818），破壞身分與其餘資料的對應。

| 條件 | 選中 gold 所在 slot 的比例 |
|---|---|
| FULL（原始候選身分）| **0.8571** |
| 候選身分隨機替換 | **0.7627** |
| 兩者選同一個 slot 的比例 | 0.8073 |
（母體：gold 在候選集內的 26,222 筆）


**判讀**：破壞身分後，選中 gold slot 的比例從 0.857 掉到 0.763（−9.4pp），且有 80.7% 的情形仍然選同一個 slot。
→ **candidate identity 確實有被用到，但不是主力** —— 即使身分完全是亂的，靠掛在 slot 上的數值特徵仍能答對 76%。這與 §PART 2 的 ablation 一致：主力是 numeric features。


---

## PART 7 — 效果是否集中在少數模式

| 讀音 | 節點 | rescue | damage | net | 佔總 net |
|---|---|---|---|---|---|
| ㄕㄤˇ | 146 | 125 | 3 | **+122** | 7.9% |
| ㄏㄨㄟˇ | 154 | 118 | 3 | **+115** | 7.5% |
| ㄑㄧㄤ | 108 | 90 | 2 | **+88** | 5.7% |
| ㄎㄢ | 87 | 70 | 1 | **+69** | 4.5% |
| ㄌㄞˋ | 85 | 70 | 2 | **+68** | 4.4% |
| ㄘㄨㄥ | 77 | 63 | 1 | **+62** | 4.0% |
| ㄨ | 88 | 63 | 10 | **+53** | 3.4% |
| ㄇㄛˋ | 77 | 50 | 3 | **+47** | 3.0% |
| ㄨㄤˋ | 56 | 41 | 1 | **+40** | 2.6% |
| ㄍㄥ | 76 | 37 | 1 | **+36** | 2.3% |
| **其餘 856 個讀音** | 25,293 | — | — | **+843** | **54.6%** |

總 net +1543；前 10 個讀音佔 45.4%，長尾佔 54.6%。
相異讀音 866 個。


**判讀**：前 10 個讀音佔 net 的 45.4%，其餘 856 個讀音佔 54.6%。**沒有由少數高頻模式獨撐**，分佈算健康。
（本項只做這一個確認，未建立 ⑭-N 式的大型 direction-held-out 研究。）

---

## PART 8 — 獨立驗證集 1,657 題

### Provenance check（做完才用）

| 檢查 | 結果 |
|---|---|
| 資料來源 | `獨立驗證集-真實語料.jsonl`，domain 全為 `ptt-real`、source `corpus-audited` |
| 與 **prototype 訓練語料** 重疊 | **0 / 1,657（0.00%）** ✅ |
| 與 prototype held-out fold 重疊 | 不適用（不同語料，整份都在訓練外）|
| 與 **ship-gate 自然驗證集** 重疊 | ⚠️ **1,657 / 1,657（100%）—— 它是那份正式測試集的子集** |
| 與 ship-gate X 驗證集重疊 | 0 |
| 格式可直接用 | ✅ 讀音與句長 1,657/1,657 相符 |

**必須講清楚的一點**：這份語料**不是第三方獨立語料**，
它 100% 落在 ship-gate 自然驗證集之內。
所以它能提供的是「**跨語料（訓練語料 → PTT 驗證語料）的泛化檢查**」，
**不是**產品意義上的 independent validation。

本棒**沒有跑 ship-gate、沒有跑 model-ab、沒有做任何出貨判定**，
只是拿 ⑯ 已訓練好的 checkpoint 對這些節點打分。
**未重新訓練、未調 hyperparameter、未調 threshold、未修改 feature、未依結果重訓。**

### 結果（5,896 個單字節點，整份使用）

| Metric | Engine | **FULL** | NO-INTERACTION | NO-NUMERIC | CONTEXT-ONLY |
|---|---:|---:|---:|---:|---:|
| top-1 | 0.8862 | 0.8411 | 0.8574 | 0.7692 | 0.7439 |
| top-2 | — | 0.9340 | 0.9354 | 0.8904 | 0.8075 |
| rescue | — | 77 | 61 | 140 | 61 |
| damage | — | 343 | 231 | 830 | 900 |
| **net** | — | **−266** | **−170** | **−690** | **−839** |
| precision | — | 0.1510 | 0.1635 | 0.1193 | 0.0547 |
| override | — | 510 | 373 | 1,174 | 1,115 |
| candidate_absent | 0 | 0 | 0 | 0 | 0 |

### 這是本棒最重要的結果

**四個版本在跨語料評估上全部是淨負的，而且 FULL 的 top-1 比引擎還低
（0.8411 vs 0.8862）。**

同一個 checkpoint：
* 訓練語料的 held-out fold（document-held-out，**同語料同領域**）→ net **+1,543**
* 換一份語料（PTT 驗證語料，**跨語料**）→ net **−266**

⑯ 的 document-level held-out **不足以證明泛化** ——
它防住了「同一份文件跨 train/dev」，但沒有防住「同一個語料分布」。
模型學到的相當一部分是**訓練語料的分布**，換語料就翻負。

---

## PART 9 — 工程可行性

| 項目 | 值 |
|---|---|
| FULL 參數 / checkpoint | 964,449 / 4.05 MB |
| NO-INTERACTION | 931,681 / 3.91 MB |
| NO-NUMERIC | 963,809 / 4.04 MB |
| CONTEXT-ONLY | 922,849 / 3.88 MB |
| CPU 訓練時間 | 25–42 秒（Mac mini，4 epochs，110,119 樣本）|
| checkpoint 載入 | 13 ms |
| 批次推論 | 26,247 節點 **0.76 s** = **29 µs/node** |
| 單筆推論（batch 1，含 featurize）| **0.16 ms/node** |
| 峰值記憶體（含資料載入）| ~1.2 GB（推論本身遠低於此，主要是把整份語料讀進來）|

**成本本身完全不是問題**：模型不到 100 萬參數、4 MB、單筆 0.16 ms。
如果效果站得住，工程整合是輕的。**問題出在效果，不在成本。**

---

## PART 12 — 最終報告的八個答案

| # | 問題 | 答案 |
|---|---|---|
| 1 | Prototype-001 能否完整重現？ | **能。** 九項指標逐項相同，無需修正 |
| 2 | candidate × context interaction 貢獻多少？ | **負的。** 拿掉後 net +1,543 → **+1,633**、precision 0.631 → 0.666 |
| 3 | numeric engine features 貢獻多少？ | **決定性。** 拿掉後 net +1,543 → **+302**（−80%），damage 900 → 2,371 |
| 4 | FULL 的 rescue / damage 是否合理？ | 同語料下合理（precision 0.63，救的多半是明顯的脈絡錯字）；**跨語料下不合理**（rescue 77 / damage 343）|
| 5 | candidate identity 是否真的被使用？ | **有，但不是主力。** 破壞身分後選中 gold slot 從 0.857 → 0.763，且 80.7% 仍選同一 slot |
| 6 | independent validation 是否支持？ | **不支持。** 跨語料 net −266，top-1 還低於引擎。且該語料 100% 落在 ship-gate 語料內，本身也不是真正的 independent |
| 7 | inference / training cost 是否可接受？ | **完全可接受。** 964k 參數、4 MB、29 µs/node、訓練 42 秒 |
| 8 | 最終判定 | 🔴 **NO-GO** |

### 一句白話

> **不值得。** Prototype-001 在訓練語料上看起來有效（+1,543），
> 但那個效果換一份語料就變成 **−266**；而且它的核心設計 ——
> candidate × context interaction —— 經 ablation 證實**沒有貢獻，拿掉還更好**。
> 真正在做事的是引擎原本就算好的 unigram / PMI 數值特徵。
> **它現在不值得進入下一階段工程整合。**

---

## Deferred（只記錄，本棒不展開）

- **issue**：⑭-I 的診斷（interaction 讓線性分類器 AUC 0.792）與本棒的 ablation
  （interaction 對訓練好的模型無貢獻）方向相反。
  **impact**：影響「診斷式 representation 研究能不能預測模型效果」這個方法學問題。
  **why deferred**：本棒是驗證既有 prototype，不是重開表徵研究。
- **issue**：document-level held-out 不足以證明跨語料泛化。
  **impact**：⑯ 以前的 prototype 評估協定可能都偏樂觀。
  **why deferred**：屬評估協定設計，不阻礙本棒結論。
- **issue**：「獨立驗證集」100% 落在 ship-gate 自然驗證集內，
  專案目前**沒有**真正的第三方獨立語料。
  **impact**：任何 prototype 都缺一份乾淨的最終驗收語料。
  **why deferred**：屬資料取得決策（⑮ §C 已記錄），不是研究問題。
- **issue**：NO-INTERACTION 在兩份語料上都比 FULL 好，但兩者跨語料都是負的。
  **impact**：即使簡化架構也救不回泛化。
  **why deferred**：判定已是 NO-GO，不再迭代架構。

## 交付

| 項目 | 狀態 |
|---|---|
| production diff | **0**（`git diff` 對既有追蹤檔為空）|
| frozen production files SHA256 | **未變** |
| merge / enable / 接 app / 正式 ship test | **全部 NO** |
| 修改的檔案 | `prototype/ccd/model.py`、`prototype/ccd/cli.py`（加 ablation variant 與 `--all-folds`，皆為 prototype code）|
| 新增的檔案 | `Source/Engine/eval/analysis/baton17-ccd-validation.md` |
| checkpoint | `~/laowang-data/baton16-ccd/ccd-{v0.1,no-interaction,no-numeric,context-only}.pt`（不進 repo）|
