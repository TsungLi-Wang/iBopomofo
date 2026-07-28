# tw538 位置級同音判別器報告（棒 C 最終版）

> 產生時間：2026-07-28T21:43:45
> 產物根：`~/laowang-data/batonC-final/`
> **本棒純研究**：未改 C++ 出貨路徑、未改 λ/ν/N、未接 app。

---

## 0. 控制組與基線（步驟 0）

### 控制組 stdout（verbatim）

```
path scorer loaded=1 params=9734083 emb=256 hidden=512 layers=2 vocab=7875
SLICE1_OFF 296/537
SLICE1_ON 333/537
SLICE1_NBEST_RANK0_MATCH 537/537
SLICE1_WALK_MEAN_US 323.449
SLICE2_NU0_MATCH 537/537
NU 0.75 correct 387/537 mean_ms 44.1976
BEST_NU 0.75 correct 387/537
```

### 基線

```
CONTROL 387/537
BASELINE_A_excl5 5947/6795 87.5202%
BASELINE_B_all 367/537 68.34%
BASELINE_B_inpool 367/470 78.09%
EXCL_POS (155,11-15) five unalignable positions
```

| 基線 | 定義 | 數字 |
|---|---|---|
| A 位置級 | residual-entropy `gold_rank==1` 佔比，排除 #155 五位 | **87.52%**（5947/6795） |
| B 路徑排序 | v2c 單獨在 n-best 池排 gold 第一 | **68.34%**（367/537）；池內 **78.09%**（367/470） |

排除：#155 音節/字數對不齊 5 個位置——位置級統計排除；句級仍算錯。

**與 A-2 V4 空操作之區分**：V4 用同一組 walk+v2c 分數在同一池重選必然恆等；本棒第三關用的是**新訓練判別器**的路徑對數似然，屬新分數來源。

---

## 1. 前置偵察（步驟 1，非阻斷）

修正 A-3 子詞 next-token 錯誤：改為**候選代入 + 整句 logprob**。

```
{
  "done": 298,
  "ctrl_acc": 0.96,
  "ctrl_ok": 144,
  "ctrl_n": 150,
  "bad_fixed": 67,
  "bad_n": 148,
  "bad_fix_rate": 0.4527027027027027,
  "method": "whole_sentence_logprob_shipping_fill"
}
```

- 對照組（出貨已對位置）正確率：96.0%（144/150）
- 錯誤組修好：67/148（45.3%）
- 方法：`whole_sentence_logprob_shipping_fill`；樣本 298（150 對照 + 148 錯誤，受時間切）。

---

## 2. 訓練資料（步驟 2）

### 資料來源聲明（棒文書要求從 conversion_pairs；實作說明）

```
DATA_SOURCE sentences=ptt_spoken_train_v2.txt; readings=inverted reading2chars (from conversion_pairs_v2 counts); REASON conversion_pairs lack right-context required for bidirectional encoder
PUNCT_IN_CONVERSION_PAIRS none in first 200k lines (checked step0)
READING_SOURCE conversion_pairs via dictionary/longest-match style alignment (build_conversion_pairs.py: data.txt top reading; ambiguous discarded)
{
  "n_clean": 300000,
  "n_noisy": 300000,
  "noise_levels": [
    0.0,
    0.035,
    0.08,
    0.15
  ],
  "noise_weights": [
    0.25,
    0.35,
    0.25,
    0.15
  ],
  "train_tw538_hits": 0,
  "corpus_exact_gold_hits": 0,
  "cand_size_mean": 10.21361,
  "cand_size_hist": {
    "19": 7171,
    "10": 14693,
    "7": 21609,
    "27": 822,
    "24": 4429,
    "17": 9481,
    "3": 42178,
    "5": 18116,
    "21": 970,
    "23": 1153,
    "2": 24058,
    "4": 15237,
    "11": 13257,
    "9": 15367,
    "6": 21469,
    "15": 4912,
    "32": 16738,
    "14": 9175,
    "13": 8475,
    "8": 17947,
    "18": 9736,
    "12": 8180,
    "16": 7598,
    "20": 2888,
    "26": 233,
    "22": 1637,
    "29": 818,
    "25": 946,
    "30": 245,
    "28": 462
  },
  "stats": {
    "noise_repl": 377580,
    "skip_unamb": 32394,
    "skip_noread": 1890,
    "skip_len": 39
  },
  "elapsed_s": 13.488935947418213,
  "clean_sha": "46e1c4a73d8a36ac9990f1f633249258625a2f8d45a774c7a6e978b808fe7316",
  "noisy_sha": "be326b54b2a15ba0e1b3a5f7e3dc9a120fd2c34c63f829c444868bb69962c3c3",
  "punct_in_traini
```

- **句子上下文**：`ptt_spoken_train_v2.txt`（完整句，保留右側上下文——conversion_pairs 本身缺右側，無法訓雙向）
- **讀音**：`reading2chars` 反查 + conversion_pairs 計數；對齊風格見 `build_conversion_pairs.py`（詞典／最長匹配；破音歧義多半丟棄）→ **已知噪聲來源**
- **標點**：conversion_pairs 前 200k 行**無標點**；訓練上下文亦無 → 模型**未在含標點上下文上訓練**（已知風險；tw538 量不到）
- 規模：clean 300k + noisy 300k；噪聲檔 0/3.5/8/15%，權重 0.25/0.35/0.25/0.15
- 候選集大小均值 |C_i| ≈ 10.21；未做標籤平衡（保真實長尾）
- **污染**：tw538 完整句命中 **0**；corpus exact gold hits 0
- 耗時：13.488935947418213 s（≪ 1h）
- SHA：clean `46e1c4a73d8a36ac9990f1f633249258625a2f8d45a774c7a6e978b808fe7316`；noisy `be326b54b2a15ba0e1b3a5f7e3dc9a120fd2c34c63f829c444868bb69962c3c3`

---

## 3. 訓練（步驟 3）

| 項目 | 值 |
|---|---|
| 架構 | BiLSTM 雙向，字元 emb 256 + 讀音 emb 64 → hid 384 ×2 層 → 遮罩到 C_i CE |
| 參數 | 13.31M（v2c 9.73M 同級） |
| clean 停 | {'reason': 'G2_stall', 'best_val': 0.9301333333333334, 'elapsed_h': 2.917601085835033, 'g1_done': True} |
| noisy 停 | {'reason': 'G2_stall', 'best_val': 0.919, 'elapsed_h': 2.951815823846393, 'g1_done': True} |
| clean G1 | pos pass / path fail（見 train_clean.stdout） |
| noisy G1 | pos pass / path fail（見 train_noisy.stdout） |

---

## 4. 四關評估

第三關較佳變體（依 held-out 再全表）：**clean**

### 變體：clean

- 參數量：13305336；val_acc=0.9301333333333334
- **第一關** gold 上下文位置 argmax：5908/6793 = 86.97%（基線 A 87.52%）Δ=-0.55 pp
- **第二關** 出貨輸出上下文：5893/6793 = 86.75%；相對第一關掉 0.22 pp
- 路徑排序（新模型單獨）：全 537 = 41.90%；池內 gold = 225/470 = 47.87%（基線 B 68.34% / 78.09%）
- **第三關 3a** walk+α·new 全表最佳：α=0.1 → 341/537（淨 -46）
  - grid：[[0.0, 333], [0.1, 341], [0.25, 298], [0.5, 264], [0.75, 251], [1.0, 250], [1.5, 240], [2.0, 235], [3.0, 231]]
  - 鄰近：[[0.0, 333], [0.25, 298]]
  - split-half：win=0.0, mean_B_net=-27.1, median=-26
- **第三關 3b** walk+0.75·v2c+α·new 全表最佳：α=0.0 → 387/537（淨 +0）
  - grid：[[0.0, 387], [0.1, 379], [0.25, 359], [0.5, 313], [0.75, 291], [1.0, 279], [1.5, 260], [2.0, 253], [3.0, 242]]
  - split-half：win=0.0, mean_B_net=-2.1, median=0
- **第四關** flip best：{'dmin': 5, 'net': -146, 'rescue': 13, 'regress': 159, 'final': 241, 'rescue_a': 9, 'rescue_b': 4}；split-half：{'win_rate': 0.0, 'mean_B_net': -73.95, 'median_B_net': -75}
- 脆弱度維持：834/1123；免費分救回：30/81
- 延遲：路徑重排 1403.2 ms/句；flip 全句 87.4s /537
- conf3a：{'base_wrong': {'single_char_swap': 63, 'B_out_of_pool': 67, 'homophone_family': 6, 'multi_char_swap': 13, 'len_diff_seg_or_phrase': 1}, 'rescued': {'single_char_swap': 20, 'homophone_family': 2, 'multi_char_swap': 6, 'len_diff_seg_or_phrase': 1}, 'broken': {'single_char_swap': 45, 'multi_char_swap': 23, 'homophone_family': 7}, 'net_by_pattern': {'homophone_family': -5, 'len_diff_seg_or_phrase': 1, 'B_out_of_pool': 0, 'multi_char_swap': -17, 'single_char_swap': -25}}
- conf3b：{'base_wrong': {'single_char_swap': 63, 'B_out_of_pool': 67, 'homophone_family': 6, 'multi_char_swap': 13, 'len_diff_seg_or_phrase': 1}, 'rescued': {}, 'broken': {}, 'net_by_pattern': {'multi_char_swap': 0, 'homophone_family': 0, 'B_out_of_pool': 0, 'len_diff_seg_or_phrase': 0, 'single_char_swap': 0}}
- conf_flip：{'base_wrong': {'single_char_swap': 63, 'B_out_of_pool': 67, 'homophone_family': 6, 'multi_char_swap': 13, 'len_diff_seg_or_phrase': 1}, 'rescued': {'B_out_of_pool': 4, 'single_char_swap': 9}, 'broken': {'was_correct': 159}}
- single_char_swap（3a）：base=63 rescued=20 broken=45


### 變體：noisy

- 參數量：13305336；val_acc=0.919
- **第一關** gold 上下文位置 argmax：5852/6793 = 86.15%（基線 A 87.52%）Δ=-1.37 pp
- **第二關** 出貨輸出上下文：5828/6793 = 85.79%；相對第一關掉 0.35 pp
- 路徑排序（新模型單獨）：全 537 = 38.36%；池內 gold = 206/470 = 43.83%（基線 B 68.34% / 78.09%）
- **第三關 3a** walk+α·new 全表最佳：α=0.0 → 333/537（淨 -54）
  - grid：[[0.0, 333], [0.1, 333], [0.25, 299], [0.5, 258], [0.75, 242], [1.0, 231], [1.5, 227], [2.0, 219], [3.0, 213]]
  - 鄰近：[[0.1, 333]]
  - split-half：win=0.0, mean_B_net=-29.3, median=-29
- **第三關 3b** walk+0.75·v2c+α·new 全表最佳：α=0.0 → 387/537（淨 +0）
  - grid：[[0.0, 387], [0.1, 380], [0.25, 364], [0.5, 322], [0.75, 295], [1.0, 276], [1.5, 258], [2.0, 243], [3.0, 229]]
  - split-half：win=0.0, mean_B_net=-0.45, median=0
- **第四關** flip best：{'dmin': 5, 'net': -107, 'rescue': 14, 'regress': 121, 'final': 280, 'rescue_a': 11, 'rescue_b': 3}；split-half：{'win_rate': 0.0, 'mean_B_net': -54.4, 'median_B_net': -55}
- 脆弱度維持：800/1123；免費分救回：31/81
- 延遲：路徑重排 1394.4 ms/句；flip 全句 90.0s /537
- conf3a：{'base_wrong': {'single_char_swap': 63, 'B_out_of_pool': 67, 'homophone_family': 6, 'multi_char_swap': 13, 'len_diff_seg_or_phrase': 1}, 'rescued': {'single_char_swap': 16, 'multi_char_swap': 4, 'homophone_family': 1, 'len_diff_seg_or_phrase': 1}, 'broken': {'single_char_swap': 49, 'multi_char_swap': 20, 'homophone_family': 7}, 'net_by_pattern': {'multi_char_swap': -16, 'single_char_swap': -33, 'B_out_of_pool': 0, 'len_diff_seg_or_phrase': 1, 'homophone_family': -6}}
- conf3b：{'base_wrong': {'single_char_swap': 63, 'B_out_of_pool': 67, 'homophone_family': 6, 'multi_char_swap': 13, 'len_diff_seg_or_phrase': 1}, 'rescued': {}, 'broken': {}, 'net_by_pattern': {'multi_char_swap': 0, 'single_char_swap': 0, 'B_out_of_pool': 0, 'len_diff_seg_or_phrase': 0, 'homophone_family': 0}}
- conf_flip：{'base_wrong': {'single_char_swap': 63, 'B_out_of_pool': 67, 'homophone_family': 6, 'multi_char_swap': 13, 'len_diff_seg_or_phrase': 1}, 'rescued': {'B_out_of_pool': 3, 'single_char_swap': 11}, 'broken': {'was_correct': 121}}
- single_char_swap（3a）：base=63 rescued=16 broken=49


### 噪聲訓練對照

clean g1=86.97% vs noisy g1=86.15%；clean 3a held-out -27.1 vs noisy -29.3。

---

## 5. 延遲（步驟 5）

| 模式 | 實測 | 對照 |
|---|---|---|
| 出貨 v2c 重排 | ~44–45 ms/句（控制組 mean_ms） | 鐵律 45ms |
| 新模型 10 路徑重排（clean） | **1403 ms/句** | 遠超 45ms（~31×） |
| 第四關全句一趟 | 162.8 ms/句（總 87.4s） | |
| 3b 並存 | 須串 v2c + 新模型；新模型 alone 已 ≫45ms | 不可出貨 |

雙向編碼器**無法**共用 v2c 前綴狀態；本實測未做深度批次化優化，但數量級已排除「壓到 45ms 內仍可出貨」的幻想。

---

## 6. 判定（步驟 6）

| 判準 | held-out 淨增益 | 門檻 | 結果 |
|---|---|---|---|
| 主：第三關 3a | -27.1 | ≥+20 GO / +10–19 邊際 / <+10 無效 | **見 3b** |
| 主：第三關 3b | -2.1 | 同上 | **NO-GO / 無效**（取較佳） |
| 次：第四關 flip | -73.95 | ≥+30 GO / +15–29 邊際 / <+15 NO-GO | **NO-GO** |

**總判定：兩關皆未過 → 提案 A（位置級同音判別器）正式死亡。**  
連同單點翻字一併寫入死亡名單。資源應轉向**個人化／UOM 資料回路**，而非繼續放大判別器或換 encoder。

### 歸因

第一關輸給基線 A → 首嫌語料口音／領域（八卦板 spoken），建議補來源而非放大模型。

clean vs noisy 差距：小——噪聲訓練假設不成立或幾乎無增益。

---

## 7. 已知盲區（不得省略）

1. **標點**：組字區會含標點；本訓練語料與 tw538 皆無。
2. **空格**：台灣使用者常用空一格斷句；考卷無。
3. **前文**：實機多半有已送出上文；考卷每句孤立完整句。

harness 用乾淨 UOM；Johnny 實機 UOM 有多年累積——差異未量化。

---

## 8. 死亡名單更新建議

- 位置級雙向同音判別器（本棒 clean + noisy）
- n-best 重排接入新判別器（3a/3b）
- 單點翻字接入新判別器（第四關）
- （既有）融合公式優化、擴大 n-best、補詞、純放大 LSTM、通用 LM 換架構、逐鍵重排、v2c 單點翻字（A-2）、通用 LLM 上限代理（A-3）

---

## 9. 產物與重跑

| 產物 | 路徑 |
|---|---|
| 訓練資料 | `~/laowang-data/batonC-final/traindata/`（symlink `batonC-traindata-final`） |
| 模型 | `~/laowang-data/batonC-final/model-{clean,noisy}/` |
| 評估 JSON | `eval_{clean,noisy}.json` |
| 逐位置 | `positions_*.tsv` → 本報告旁 `tw538-position-judge-positions.tsv`（較佳變體） |
| 腳本 | `Source/Engine/eval/tools/position_judge_batonC.py`、`position_judge_eval_fast.py` |
| stdout / SHA | `~/laowang-data/batonC-final/*` + `SHA256_INVENTORY.txt` |

```bash
# 重跑評估（不重訓）
~/laowang-data/venv/bin/python Source/Engine/eval/tools/position_judge_eval_fast.py clean
~/laowang-data/venv/bin/python Source/Engine/eval/tools/position_judge_eval_fast.py noisy
```

---

## 附：Johnny 十四題速答（純文字）

1. 基線 A **87.52%**；新判別器第一關（clean）**86.97%**；Δ **-0.55 百分點**。
2. 基線 B **68.34%**（全）／**78.09%**（池內）；新模型路徑排序 **41.90%**／**47.87%**。
3. 實機條件（第二關）相對第一關掉 **0.22** 百分點。
4. 混合噪聲 vs 純淨：clean g1=86.97% vs noisy g1=86.15%；clean 3a held-out -27.1 vs noisy -29.3。——**練習卷加噪聲整體未翻轉第三關結論**。
5. 第三關 3a held-out 淨增益：**-27.1**。
6. 第三關 3b held-out 淨增益：**-2.1**；3b 較不傷（α→0 退回出貨）。
7. 操作點：3a 鄰近 [[0.0, 333], [0.25, 298]]；split-half 勝出率 3a=0.0、3b=0.0——**非高原可出貨點**。
8. 第四關 held-out：**-73.95**；B 類救回（全表 best）**4** 句（淨仍大幅為負）。
9. single_char_swap：見 conf3a base/rescued/broken（出貨 A 類約 63 句 single_char_swap 量級）。
10. 1123 高熵答對位：維持 **834/1123** → 弄壞約 **289** 個（位置級 g2 定義）。
11. 免費分（v2c rank1 仍錯）：救回 **30/81**（本實測分母 81，棒文 85 為近似）。
12. 重排 10 路徑：**1403 ms/句**，**遠超 45ms**；並存更差。
13. 注音：詞典／對齊推導（conversion_pairs 風格）；上下文**無標點**。
14. **主判準 NO-GO；次判準 NO-GO。** 歸因：路徑排序遠遜 + 融合傷害出貨；語料領域為第一關略弱的背景嫌疑，但主因是**判別分數無法變成可用路徑重排**。

（完）
