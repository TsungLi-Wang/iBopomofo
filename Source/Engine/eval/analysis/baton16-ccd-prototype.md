# 棒⑯ — Prototype Implementation Report

## 1. Status

**DONE.**

程式建立、模型訓練、checkpoint 產生並重新載入、inference 執行、
end-to-end 評估完成、baseline 比較完成、rescue/damage 量出、真實案例列出、CLI 可用。

## 2. What was actually built

| 檔案 | 內容 |
|---|---|
| `prototype/ccd/data.py` | 樣本層：從既有 node dump 建 candidate-decision 樣本、canonical document fold、leakage audit |
| `prototype/ccd/model.py` | `ContextualCandidateDecision` 模型 ＋ pairwise ranking loss |
| `prototype/ccd/cli.py` | CLI：`train` / `evaluate` / `predict` |
| `prototype/ccd/README.md` | 怎麼在本機跑 |
| `~/laowang-data/baton16-ccd/ccd-v0.1.pt` | checkpoint（3.9 MB，**不進 repo**）|
| `~/laowang-data/baton16-ccd/report-examples.txt` | 完整範例輸出 |

**全部在 `prototype/` 之下，與 production 完全隔離。**
production 端 0 行修改，未被 production 任何檔案 import。

### 本機執行方式

```bash
V=~/laowang-data/baton13-node-homophone/.venv/bin/python
W=~/laowang-data/baton13-node-homophone

# 訓練（約 42 秒）
$V -m prototype.ccd.cli train \
   --nodes $W/data/nodes.tsv --sentences $W/data/sentences.jsonl \
   --out ~/laowang-data/baton16-ccd/ccd-v0.1.pt --epochs 4

# 評估（held-out fold，約 3 秒）
$V -m prototype.ccd.cli evaluate \
   --ckpt ~/laowang-data/baton16-ccd/ccd-v0.1.pt \
   --nodes $W/data/nodes.tsv --sentences $W/data/sentences.jsonl --examples 25

# 單點預測
$V -m prototype.ccd.cli predict \
   --ckpt ~/laowang-data/baton16-ccd/ccd-v0.1.pt \
   --context 我今天想要 --right 一件事情 --reading ㄗㄨㄛˋ --candidates 做,作,坐,座
```

`--help` 可用；缺檔會明確報錯；同一 checkpoint 兩次評估輸出逐位相同（已驗證 md5 相同）。

## 3. Model

* **參數量 964,449**（字表 12,736 × emb 64 為主）
* **架構**：char embedding（脈絡與候選共用）→ 左右各 ±6 的位置線性投影
  → **candidate × context 的四組 element-wise 交互** → MLP → 每個候選一個 scalar
* **四組交互**（這是 ⑭-I 的核心想法，本棒重新實作，**未載入 I2 checkpoint**）：

  | 交互 | 意義 |
  |---|---|
  | `left_last ⊙ candidate` | 緊鄰左字 × 候選 |
  | `candidate ⊙ right_first` | 候選 × 緊鄰右字 |
  | `left_pool ⊙ candidate` | 左視窗摘要 × 候選 |
  | `candidate ⊙ right_pool` | 候選 × 右視窗摘要 |

* **輸入**：左 ±6 字、右 ±6 字、reading、候選字身分、
  候選數值特徵（unigram 分數、左右 PMI、是否為 walk 當下選擇、右側是否為空）
* **輸出**：候選集合中每個候選各自一個 scalar score
* **決策**：純 `argmax`，**沒有任何 threshold**
* **loss**：pairwise logistic（`softplus(-(s_gold − s_neg))`），同一候選集合內比較

## 4. Training

| 項目 | 值 |
|---|---|
| 資料 | `baton13-node-homophone/data/nodes.tsv`（kind=0、span=1、候選數 ≥2）|
| 樣本 | **136,366**（train 110,119 / held-out fold 0 = 26,247）|
| 涵蓋 | 5,155 個相異讀音的全語料節點，**不限作做坐座** |
| 切分 | canonical `sha256("baton14f-fold-v1:{doc_id}")[:8] % 5`，沿用 ⑭，未重新設計 |
| epochs / batch / lr | 4 / 256 / 1e-3（Adam, wd 1e-5）|
| 訓練時間 | **42 秒**（CPU，Mac mini）|
| 推論時間 | **2.9 秒 / 26,247 節點**（含載入）|
| checkpoint | **3.9 MB** |
| 隨機種子 | 20260818（torch 與 numpy 皆固定）|

## 5. Evaluation

held-out fold 0，**26,247 個單字節點**（文件級切分，與訓練不重疊）。

| Metric | R4 / 現行引擎 | Prototype-001 |
|---|---:|---:|
| top-1 accuracy | 0.7975 | **0.8563** |
| top-2 accuracy | — | 0.9374 |
| top-3 accuracy | — | 0.9627 |
| rescue | — | **2,443** |
| damage | — | **900** |
| **net** | — | **+1,543** |
| precision | — | 0.6306 |
| override | — | 3,874 |
| candidate_absent | 15 | 同左（v0.1 不負責救）|
| gold 超出 `MAX_CANDS=32` | 10 | 同左 |

### ⚠️ 這個 0.7975 不是「輸入法的正確率」

母體是**單字節點且候選數 ≥2** —— 也就是「引擎真的要做選擇」的那些位置，
已經排除了多字詞節點（那些通常是對的）。
與 ⑭ 系列的 D2（全語料字位、95.7% 逐字正確率）**分母完全不同，NOT COMPARABLE**。
本表只在「候選決策」這個問題上比較，不得外推成系統正確率或 production 效果。


## 6. Rescue examples（25 筆；held-out fold，真實語料）

```
  Context : 八點檔演員[?]凱日前奏是
  Reading : ㄨㄤˋ
  Cands   : 望/忘/旺/妄/王/朢/迋/莣
  Engine  : 望    Prototype: 王    Gold: 王
  Ranking : 王:+6.72 望:+0.99 忘:-2.07 妄:-2.51 旺:-3.74
  -> RESCUE

  Context : 演員望凱日前[?]是
  Reading : ㄗㄡˋ
  Cands   : 奏/驟/揍
  Engine  : 奏    Prototype: 驟    Gold: 驟
  Ranking : 驟:+2.78 奏:+0.41 揍:-3.02
  -> RESCUE

  Context : 因為打電話[?]想
  Reading : ㄏㄨㄟˇ
  Cands   : 毀/悔/誨/虫/燬/虺/會/賄 …
  Engine  : 毀    Prototype: 會    Gold: 會
  Ranking : 會:+7.60 毀:-0.68 虫:-2.12 檓:-2.43 譭:-2.72
  -> RESCUE

  Context : 功夫女[?]
  Reading : ㄗㄨˊ
  Cands   : 族/足/卒/崒/嗾/捽/踿/哫 …
  Engine  : 族    Prototype: 足    Gold: 足
  Ranking : 足:+5.31 族:+2.58 卒:-0.84 捽:-5.94 傶:-6.17
  -> RESCUE

  Context : 在高雄發生謝[?]男模陳詩租屋
  Reading : ㄒㄧㄥˋ
  Cands   : 性/幸/姓/杏/倖/悻/行/興 …
  Engine  : 幸    Prototype: 姓    Gold: 姓
  Ranking : 姓:+5.06 杏:+2.96 幸:+2.20 性:-3.93 荇:-5.27
  -> RESCUE

  Context : 生謝幸男模陳[?]租屋處的命案
  Reading : ㄕ
  Cands   : 師/失/施/詩/獅/濕/屍/噓 …
  Engine  : 詩    Prototype: 屍    Gold: 屍
  Ranking : 屍:+2.60 詩:+2.40 噓:+0.42 失:-0.45 施:-0.88
  -> RESCUE

  Context : 爐[?]在律師
  Reading : ㄖㄨˇ
  Cands   : 乳/辱/汝/女/擩/侞
  Engine  : 乳    Prototype: 女    Gold: 女
  Ranking : 女:+1.74 乳:+0.31 汝:-2.80 辱:-6.26 擩:-7.94
  -> RESCUE

  Context : 如今亞馬遜[?]努力減少
  Reading : ㄓㄥ
  Cands   : 爭/徵/掙/征/蒸/睜/箏/癥 …
  Engine  : 徵    Prototype: 正    Gold: 正
  Ranking : 正:+2.92 徵:+1.97 掙:-2.27 爭:-2.39 征:-2.99
  -> RESCUE

  Context : [?]色油量的東坡
  Reading : ㄐㄧㄤˋ
  Cands   : 將/降/醬/漿/匠/彊/強/絳 …
  Engine  : 降    Prototype: 醬    Gold: 醬
  Ranking : 醬:+4.54 降:+3.12 將:+2.99 強:-0.47 絳:-0.84
  -> RESCUE

  Context : 飯[?]得力力分明
  Reading : ㄔㄠˇ
  Cands   : 吵/炒/眧
  Engine  : 吵    Prototype: 炒    Gold: 炒
  Ranking : 炒:+6.82 吵:+6.11 眧:-6.32
  -> RESCUE

  Context : 除了[?]賞法院求償
  Reading : ㄍㄨˋ
  Cands   : 故/顧/固/雇/僱/錮/梏/估 …
  Engine  : 固    Prototype: 告    Gold: 告
  Ranking : 告:+7.01 固:+1.62 故:+1.14 雇:+0.20 顧:-0.76
  -> RESCUE

  Context : 除了固[?]法院求償
  Reading : ㄕㄤˇ
  Cands   : 賞/晌/上
  Engine  : 賞    Prototype: 上    Gold: 上
  Ranking : 上:+12.23 賞:-1.37 晌:-2.57
  -> RESCUE

  Context : [?]原本可能一個
  Reading : ㄑㄧㄤ
  Cands   : 槍/腔/鏘/羌/蹌/鎗/蜣/嗆 …
  Engine  : 槍    Prototype: 將    Gold: 將
  Ranking : 將:+7.64 嗆:+1.59 槍:-0.80 搶:-2.33 瑲:-2.61
  -> RESCUE

  Context : 塔形式林[?]特製醬汁
  Reading : ㄕㄤˇ
  Cands   : 賞/晌/上
  Engine  : 賞    Prototype: 上    Gold: 上
  Ranking : 上:+8.68 賞:-2.91 晌:-5.60
  -> RESCUE

  Context : [?]空攻擊彈藥
  Reading : ㄓˋ
  Cands   : 至/制/治/製/致/置/志/智 …
  Engine  : 制    Prototype: 滯    Gold: 滯
  Ranking : 滯:+5.15 制:+4.58 稚:+3.97 智:+3.95 質:+2.89
  -> RESCUE

  Context : [?]歷史新天價並
  Reading : ㄩㄢˊ
  Cands   : 員/原/元/園/源/圓/援/緣 …
  Engine  : 員    Prototype: 元    Gold: 元
  Ranking : 元:+4.42 員:+2.69 圓:+2.19 原:+1.29 園:+1.00
  -> RESCUE

  Context : 陳[?]奇感嘆
  Reading : ㄆㄟˋ
  Cands   : 配/佩/沛/珮/轡/霈/旆/姵 …
  Engine  : 佩    Prototype: 珮    Gold: 珮
  Ranking : 珮:+5.64 佩:+5.51 沛:+2.99 配:+2.39 霈:+0.70
  -> RESCUE

  Context : 陳佩[?]感嘆
  Reading : ㄑㄧˊ
  Cands   : 其/期/奇/旗/齊/騎/歧/祇 …
  Engine  : 奇    Prototype: 騏    Gold: 騏
  Ranking : 騏:+3.53 奇:+2.47 期:+1.44 其:+1.25 騎:+0.93
  -> RESCUE

  Context : 大[?]推什麼
  Reading : ㄔㄤˇ
  Cands   : 場/廠/敞/昶/氅/鋹
  Engine  : 場    Prototype: 廠    Gold: 廠
  Ranking : 廠:+3.59 場:+0.37 敞:-4.18 昶:-4.57 氅:-5.52
  -> RESCUE

  Context : 個下午就這樣[?]在湖邊野餐
  Reading : ㄗㄨㄛˋ
  Cands   : 作/做/座/坐/祚/酢/柞/鑿 …
  Engine  : 做    Prototype: 坐    Gold: 坐
  Ranking : 坐:+5.25 做:+4.92 作:+2.21 座:+1.64 祚:-4.02
  -> RESCUE

  Context : [?]一個業者公布
  Reading : ㄗㄞˋ
  Cands   : 在/再/載
  Engine  : 在    Prototype: 再    Gold: 再
  Ranking : 再:+4.22 在:+1.08 載:-2.88
  -> RESCUE

  Context : 在[?]個業者公布的
  Reading : ㄧ
  Cands   : 一/醫/依/衣/伊/ㄧ/壹/漪 …
  Engine  : 一    Prototype: 依    Gold: 依
  Ranking : 依:+6.85 一:+4.60 醫:+1.89 ㄧ:-0.80 伊:-1.15
  -> RESCUE

  Context : 在一[?]業者公布的方
  Reading : ㄍㄜˋ
  Cands   : 個/各/箇/鉻/虼
  Engine  : 個    Prototype: 各    Gold: 各
  Ranking : 各:+4.96 個:-0.72 箇:-4.11 鉻:-5.11 虼:-9.19
  -> RESCUE

  Context : 日累計至本期[?]本期淨利
  Reading : ㄓˇ
  Cands   : 只/指/止/紙/址/旨/祉/趾 …
  Engine  : 只    Prototype: 止    Gold: 止
  Ranking : 止:+6.36 指:+2.89 只:+2.09 址:-0.42 紙:-1.22
  -> RESCUE

  Context : 記者陳[?]朋
  Reading : ㄒㄧㄢˋ
  Cands   : 現/見/線/縣/限/獻/憲/陷 …
  Engine  : 現    Prototype: 献    Gold: 献
  Ranking : 献:+5.93 獻:+3.90 線:+3.37 現:+3.02 縣:+2.65
  -> RESCUE
```


## 7. Damage examples（25 筆）

```
  Context : 所以盡可能[?]把下位者
  Reading : ㄉㄜ˙
  Cands   : 的/得/地
  Engine  : 的    Prototype: 地    Gold: 的
  Ranking : 地:+5.79 的:+3.12 得:-10.99
  -> DAMAGE

  Context : [?]進帳都超興奮
  Reading : ㄐㄧㄣ
  Cands   : 今/金/津/斤/筋/巾/襟/矜 …
  Engine  : 金    Prototype: 今    Gold: 金
  Ranking : 今:+3.56 金:+3.38 筋:+0.71 津:-0.63 禁:-0.70
  -> DAMAGE

  Context : 天在高雄發生[?]幸男模陳詩租
  Reading : ㄒㄧㄝˋ
  Cands   : 謝/洩/械/卸/蟹/屑/瀉/懈 …
  Engine  : 謝    Prototype: 蟹    Gold: 謝
  Ranking : 蟹:+2.06 謝:+1.03 卸:-1.43 屑:-1.57 瀉:-1.73
  -> DAMAGE

  Context : 認為[?]能在
  Reading : ㄊㄚ
  Cands   : 他/她/它/牠/塌/祂/褟/禢
  Engine  : 他    Prototype: 它    Gold: 他
  Ranking : 它:+3.43 他:+2.98 她:+2.96 祂:+0.18 牠:-0.11
  -> DAMAGE

  Context : 做伙食[?]菜單
  Reading : ㄊㄤˊ
  Cands   : 堂/糖/唐/塘/棠/醣/膛/螳 …
  Engine  : 堂    Prototype: 唐    Gold: 堂
  Ranking : 唐:+3.19 糖:+2.34 堂:+0.67 塘:-0.80 棠:-1.34
  -> DAMAGE

  Context : 我們必須立即[?]所有客戶停用
  Reading : ㄨㄟˋ
  Cands   : 位/為/未/味/衛/謂/胃/慰 …
  Engine  : 為    Prototype: 未    Gold: 為
  Ranking : 未:+6.97 味:+6.93 位:+5.85 為:+5.55 魏:+5.20
  -> DAMAGE

  Context : 的所有存取[?]
  Reading : ㄑㄩㄢˊ
  Cands   : 全/權/泉/詮/拳/銓/痊/蜷 …
  Engine  : 權    Prototype: 全    Gold: 權
  Ranking : 全:+2.60 權:+1.93 卷:+0.61 拳:+0.59 泉:-0.24
  -> DAMAGE

  Context : 你也有[?]已喜歡做的工
  Reading : ㄗˋ
  Cands   : 自/字/漬/孳/恣/胾/眥/剚 …
  Engine  : 自    Prototype: 字    Gold: 自
  Ranking : 字:+4.21 自:+3.93 孳:-4.46 恣:-4.60 漬:-6.93
  -> DAMAGE

  Context : 外有二點還要[?]觀察
  Reading : ㄗㄞˋ
  Cands   : 在/再/載
  Engine  : 再    Prototype: 在    Gold: 再
  Ranking : 在:+5.49 再:+3.93 載:-14.35
  -> DAMAGE

  Context : 會主動聯繫師[?]前來認領
  Reading : ㄓㄨˇ
  Cands   : 主/煮/矚/囑/貯/拄/渚/麈 …
  Engine  : 主    Prototype: 著    Gold: 主
  Ranking : 著:+4.75 煮:+4.65 主:+3.62 矚:+0.73 屬:-1.69
  -> DAMAGE

  Context : 過去[?]的債現在要還
  Reading : ㄑㄧㄢˋ
  Cands   : 欠/歉/嵌/茜/倩/塹/芡/蒨 …
  Engine  : 欠    Prototype: 歉    Gold: 欠
  Ranking : 歉:+1.36 欠:+0.60 塹:-0.37 嵌:-0.84 茜:-1.37
  -> DAMAGE

  Context : 政策市長金融[?]遭刑事舉報
  Reading : ㄈㄢˋ
  Cands   : 範/飯/犯/販/泛/范/氾/梵 …
  Engine  : 範    Prototype: 飯    Gold: 範
  Ranking : 飯:+4.37 範:+3.45 犯:+2.77 泛:+2.07 販:+0.68
  -> DAMAGE

  Context : 轎車後車廂位[?]上路
  Reading : ㄍㄨㄢ
  Cands   : 關/觀/官/棺/矜/莞/綸/倌 …
  Engine  : 關    Prototype: 觀    Gold: 關
  Ranking : 觀:+3.61 關:+3.28 官:+2.64 棺:+1.49 鰥:+0.63
  -> DAMAGE

  Context : 紋解鎖也順暢[?]
  Reading : ㄉㄜ˙
  Cands   : 的/得/地
  Engine  : 的    Prototype: 地    Gold: 的
  Ranking : 地:+5.83 的:+5.38 得:-10.13
  -> DAMAGE

  Context : 轉行找品[?]工程或是品檢
  Reading : ㄅㄠˇ
  Cands   : 保/寶/堡/飽/葆/褓/鴇/怉 …
  Engine  : 保    Prototype: 堡    Gold: 保
  Ranking : 堡:+2.36 保:+2.04 飽:-1.02 葆:-3.26 寶:-5.27
  -> DAMAGE

  Context : 料中心槍的槍[?]
  Reading : ㄉㄧㄢˋ
  Cands   : 電/店/殿/墊/甸/奠/澱/佃 …
  Engine  : 電    Prototype: 店    Gold: 電
  Ranking : 店:+4.71 電:+2.33 墊:+2.03 殿:+0.53 澱:-2.18
  -> DAMAGE

  Context : 能使該公司的[?]值提升
  Reading : ㄍㄨ
  Cands   : 估/孤/姑/辜/菇/咕/鈷/箍 …
  Engine  : 估    Prototype: 家    Gold: 估
  Ranking : 家:+7.13 估:+6.38 菇:+0.89 姑:+0.05 孤:-0.61
  -> DAMAGE

  Context : 作伙食[?]價目表
  Reading : ㄊㄤˊ
  Cands   : 堂/糖/唐/塘/棠/醣/膛/螳 …
  Engine  : 堂    Prototype: 唐    Gold: 堂
  Ranking : 唐:+1.56 糖:+1.42 堂:+0.02 醣:-0.30 塘:-2.15
  -> DAMAGE

  Context : 一月單月自接[?]
  Reading : ㄕㄨˇ
  Cands   : 屬/署/數/鼠/暑/薯/蜀/黍 …
  Engine  : 數    Prototype: 屬    Gold: 數
  Ranking : 屬:+2.57 數:+2.30 薯:+2.10 暑:+1.52 署:+1.10
  -> DAMAGE

  Context : 在於[?]操上面跟累積
  Reading : ㄕˊ
  Cands   : 時/十/實/什/食/石/拾/蝕 …
  Engine  : 實    Prototype: 碩    Gold: 實
  Ranking : 碩:+7.12 實:+6.73 時:+6.10 什:+4.05 食:+3.30
  -> DAMAGE

  Context : [?]延伸至下游雲
  Reading : ㄗㄞˋ
  Cands   : 在/再/載
  Engine  : 再    Prototype: 在    Gold: 再
  Ranking : 在:+6.14 再:+2.49 載:-3.12
  -> DAMAGE

  Context : 人類直接用組[?]
  Reading : ㄩˇ
  Cands   : 與/語/雨/予/宇/羽/嶼/禹 …
  Engine  : 語    Prototype: 與    Gold: 語
  Ranking : 與:+6.09 宇:+2.76 語:+1.99 予:-0.52 雨:-1.37
  -> DAMAGE

  Context : 紅酒燉牛肉有[?]三個配菜和一
  Reading : ㄈㄨˋ
  Cands   : 負/父/復/富/副/付/附/婦 …
  Engine  : 附    Prototype: 復    Gold: 附
  Ranking : 復:+4.24 附:+3.31 腹:+2.18 傅:+1.11 婦:+0.65
  -> DAMAGE

  Context : 悍將[?]槍穿上
  Reading : ㄇㄣˊ
  Cands   : 們/門/捫/穈/鍆/樠/菛/虋 …
  Engine  : 們    Prototype: 門    Gold: 們
  Ranking : 門:+2.94 們:+2.62 捫:-2.47 樠:-4.88 鍆:-5.76
  -> DAMAGE

  Context : [?]菲做使用
  Reading : ㄡ
  Cands   : 歐/毆/鷗/謳/ㄡ/嘔/區/甌 …
  Engine  : 歐    Prototype: 區    Gold: 歐
  Ranking : 區:+6.20 歐:+4.28 鷗:-1.96 毆:-2.51 謳:-3.10
  -> DAMAGE
```


## 8a. KEEP-OK — 原本對、prototype 沒亂改（5 筆）

```
  Context : 說本人不會[?]也不喜歡中國
  Reading : ㄇㄞˇ
  Cands   : 買/嘪/鷶
  Engine  : 買    Prototype: 買    Gold: 買
  Ranking : 買:+4.14 嘪:-6.50 鷶:-8.23
  -> KEEP-OK（原本對，prototype 沒亂改）

  Context : [?]一堆能在家上
  Reading : ㄍㄨㄤ
  Cands   : 光/胱/洸/桄/珖/炚/茪/銧 …
  Engine  : 光    Prototype: 光    Gold: 光
  Ranking : 光:+5.77 胱:-3.15 洸:-3.31 茪:-4.97 炚:-5.00
  -> KEEP-OK（原本對，prototype 沒亂改）

  Context : 光一堆[?]在家上班的職
  Reading : ㄋㄥˊ
  Cands   : 能/薴/儜
  Engine  : 能    Prototype: 能    Gold: 能
  Ranking : 能:+2.48 儜:-6.35 薴:-7.41
  -> KEEP-OK（原本對，prototype 沒亂改）

  Context : 堆能在家上班[?]職缺就屌打飲
  Reading : ㄉㄜ˙
  Cands   : 的/得/地
  Engine  : 的    Prototype: 的    Gold: 的
  Ranking : 的:+5.59 地:-7.36 得:-8.96
  -> KEEP-OK（原本對，prototype 沒亂改）

  Context : 家上班的職缺[?]屌打飲食業啥
  Reading : ㄐㄧㄡˋ
  Cands   : 就/究/舊/救/鷲/舅/咎/臼 …
  Engine  : 就    Prototype: 就    Gold: 就
  Ranking : 就:+4.87 舊:-0.48 鷲:-0.74 救:-3.17 究:-3.18
  -> KEEP-OK（原本對，prototype 沒亂改）
```


## 8b. CANDIDATE_ABSENT — gold 不在候選集（5 筆）

```
  Context : 雜誌時是處的[?]範都加入了松
  Reading : ㄉㄨㄥˋ
  Cands   : 動/洞/凍/棟/恫/胴/挏/戙 …
  Engine  : 動    Prototype: 凍    Gold: 丼
  Ranking : 凍:+2.43 動:+1.84 洞:+0.96 棟:-0.28 恫:-2.54
  -> CANDIDATE_ABSENT（gold 不在候選集，prototype 不負責救）

  Context : 大在做火[?]包
  Reading : ㄍㄨㄚˋ
  Cands   : 掛/卦/褂/挂/罣/罫/絓/詿 …
  Engine  : 掛    Prototype: 掛    Gold: 刈
  Ranking : 掛:+1.80 褂:-5.96 罣:-6.08 卦:-6.59 挂:-8.50
  -> CANDIDATE_ABSENT（gold 不在候選集，prototype 不負責救）

  Context : 作火[?]包
  Reading : ㄍㄨㄚˋ
  Cands   : 掛/卦/褂/挂/罣/罫/絓/詿 …
  Engine  : 掛    Prototype: 掛    Gold: 刈
  Ranking : 掛:+1.24 卦:-3.76 褂:-5.05 罣:-6.54 挂:-7.45
  -> CANDIDATE_ABSENT（gold 不在候選集，prototype 不負責救）

  Context : 點鮭魚[?]飯還有附上一
  Reading : ㄉㄨㄥˋ
  Cands   : 動/洞/凍/棟/恫/胴/挏/戙 …
  Engine  : 動    Prototype: 洞    Gold: 丼
  Ranking : 洞:+2.47 動:+2.42 凍:-1.16 恫:-2.43 棟:-3.75
  -> CANDIDATE_ABSENT（gold 不在候選集，prototype 不負責救）

  Context : 作火[?]包
  Reading : ㄍㄨㄚˋ
  Cands   : 掛/卦/褂/挂/罣/罫/絓/詿 …
  Engine  : 掛    Prototype: 掛    Gold: 刈
  Ranking : 掛:+1.24 卦:-3.76 褂:-5.05 罣:-6.54 挂:-7.45
  -> CANDIDATE_ABSENT（gold 不在候選集，prototype 不負責救）
```

## 8c. Demo：手動 `predict`（context → candidates → prototype → gold）

⚠️ **手動 predict 沒有引擎算的 unigram / PMI / is_walk_choice**，
數值特徵以訓練集平均代入 —— 所以它只反映「脈絡 × 候選」這一半的訊號，
與 §5 的 evaluate（完整特徵）**條件不同**。

```
$ prototype.ccd.cli predict --context 我今天想要 --right 一件事情 \
      --reading ㄗㄨㄛˋ --candidates 做,作,坐,座
  坐  0.968   做 0.021   座 0.009   作 0.002      Top-1: 坐    期望 做   ✗

$ ... --context 請你先 --right 在這裡等
  座  0.900   做 0.098   坐 0.002   作 0.000      Top-1: 座    期望 坐   ✗

$ ... --context 他是一位 --right 家
  做  0.875   座 0.094   作 0.029   坐 0.003      Top-1: 做    期望 作   ✗

$ ... --context 訂了兩個 --right 位
  做  0.828   坐 0.075   作 0.057   座 0.039      Top-1: 做    期望 座   ✗
```

**手造的四個作做坐座案例 0/4。** 這是誠實的結果，不是挑出來的。
它與 §5 的 +1,543 net 並不矛盾：evaluate 有完整的引擎數值特徵，
predict 沒有。**要分清楚貢獻來自「脈絡 × 候選交互」還是「引擎數值特徵」，
需要 ablation —— 依本棒規則不做，記入 §11 Deferred。**

## 9. Leakage / safety

| 檢查項 | 結果 | 判定 |
|---|---|---|
| context 來源 | node dump 的 `left_chars` / `right_chars`（walk 的 `chosenValueAt`）| **PASS** |
| context 是否含目標位置本身 | 6 / 136,366 命中啟發式 | **PASS（誤報）** |
| gold 是否進入 feature | `featurize()` 不接收 gold；gold 只產生 `gold_idx` label | **PASS** |
| 候選數值特徵 | unigram 分數 / 左右 PMI / is_walk_choice，皆由引擎在推論時算出 | **PASS** |
| 同一 doc 跨 fold | 0 筆 | **PASS** |
| gold 是否用於挑 threshold | v0.1 決策是純 argmax，沒有 threshold | **PASS** |
| feature 正規化 | mean/std 只在 training fold 上 fit，再套用到 held-out | **PASS** |
| 字表 / 讀音表 | 只用 training fold 建，held-out 的未見字走 UNK | **PASS** |

**那 6 筆「可疑」是我的啟發式誤報**：判準是「左鄰字 ＝ 右鄰字 ＝ gold」，
在重複字（例如「看**看**看」）會誤命中。
C++ 端的 `left_chars` 取 `[charStart−6, charStart)`、
`right_chars` 取 `[charStart+span, …)` —— **目標位置在結構上被排除**，不可能洩漏。

**未使用**：corpus gold context、未來字、正式測試答案、人工標註、
`gold_rank` 之類 offline-only 欄位。

## 10. Production impact

| 問題 | 答案 |
|---|---|
| production 是否修改？ | **NO**（`git diff` 對既有追蹤檔為空；frozen files sha256 全未變）|
| merge？ | **NO** |
| enable？ | **NO** |
| 正式 test？ | **NO**（未跑 ship-gate、未跑 model-ab、未碰 X 驗證集）|
| 接 macOS / iOS 輸入法？ | **NO** |
| 新增 production 依賴？ | **NO**（prototype 只用既有 venv 的 torch / numpy）|

新增的都在 `prototype/` 之下，production 沒有任何檔案 import 它。

## 11. Deferred Issues

- **issue**：無法分辨 +1,543 net 有多少來自「脈絡 × 候選交互」、多少來自引擎數值特徵
  （`predict` 模式在手造案例 0/4，`evaluate` 模式 net +1,543）。
  **impact**：影響「這個 representation 本身值多少」的判斷。
  **why it does not block prototype**：prototype 已能訓練、推論、產生排名與 rescue/damage。
  **deferred**。

- **issue**：`MAX_CANDS=32` 截斷，held-out 有 10 筆 gold 落在截斷之外。
  **impact**：0.04% 的樣本，prototype 結構上救不到。
  **why it does not block**：量級可忽略，且屬 candidate generation 範疇。
  **deferred**。

- **issue**：`candidate_absent` 15 筆（gold 根本不在候選集）。
  **impact**：v0.1 明確不負責救這一類。
  **why it does not block**：本棒的切分就是 candidate decision ≠ candidate generation。
  **deferred**。

- **issue**：評估母體是「單字節點且候選數 ≥2」，與 ⑭ 的 D2 分母不同。
  **impact**：不能把 top-1 0.8563 讀成系統正確率，也不能與 ⑭-R/⑭-S 的 net 直接比較。
  **why it does not block**：已在 §5 明確標示 `NOT COMPARABLE`。
  **deferred**。

- **issue**：訓練與評估都在 `train_corpus_decontaminated` 上，未在自然驗證集或真實使用紀錄上量。
  **impact**：`CORPUS-LEVEL EVIDENCE`，不代表 production 或真實輸入。
  **why it does not block**：本棒目標是可執行的 prototype，不是 production ROI。
  **deferred**。

## 12. Commit

見下方回報。
