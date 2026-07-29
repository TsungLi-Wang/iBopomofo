# tw538 辨識語料重訓報告（棒 D）

> 產生：2026-07-29T20:20:36
> 產物：`~/laowang-data/batonD-final/`
> **純研究**：架構凍結 emb256/hid512/L2；只改資料。

---

## 0. 控制組與配方

### 出貨控制組 stdout

```
path scorer loaded=1 params=9734083 emb=256 hidden=512 layers=2 vocab=7875
SLICE1_OFF 296/537
SLICE1_ON 333/537
SLICE1_NBEST_RANK0_MATCH 537/537
SLICE1_WALK_MEAN_US 321.749
SLICE2_NU0_MATCH 537/537
NU 0.75 correct 387/537 mean_ms 46.8336
BEST_NU 0.75 correct 387/537
```

### 配方（可重現）

```
RECIPE_SOURCE=Source/Engine/eval/models/path-char-lstm-spoken-v2c.meta.txt + benchmarks/README.md + train-v2c.stdout.txt
arch=CharLSTM layers=2 emb=256 hidden=512
vocab=7875 params=9734083
epochs=4 lr=0.001 seq_len=64
corpus=/tmp/ptt-gossip-expand/ptt_spoken_train_v2_packed.txt wiki=None max_wiki=3000000
han_chars≈77762073 val_ratio=0.02 best_val_loss=4.170051853197538
device=mps
TRAIN_SCRIPT=Source/Engine/eval/train_char_lstm_lm.py
CORPUS=~/laowang-data/ptt_spoken_train_v2.txt (unpacked lines; original used packed but same han source)
ARGS=--epochs short --emb 256 --hidden 512 --layers 2 --batch 128 --seq-len 64 --stream --device mps --lr 0.001 --seed 42
```

- 訓練腳本：`Source/Engine/eval/train_char_lstm_lm.py`（僅加 max-hours/max-batches/extra-corpus 權重，**未改架構**）
- 短跑：max-hours=2；D1/D2 以 D0 的 global_step 對齊 max-batches

---

## 1. 混淆對 × 語料頻次

檔案：`Source/Engine/eval/analysis/confusion-pair-frequency.tsv`

前十：

```
1	不	部	6	112431	1557984	0.0722	1
2	在	再	4	96170	554398	0.1735	1
3	是	視	3	40796	1703201	0.0240	1
4	版	板	3	36227	69948	0.5179	1
5	將	醬	2	11164	14514	0.7692	1
6	元	原	2	67851	29239	2.3206	1
7	城	程	2	28465	25740	1.1059	1
8	市	式	2	31821	49934	0.6373	1
9	要	腰	2	5165	586852	0.0088	1
10	梆	邦	2	4152	207	20.0580	1
```

meta：`{"n_pairs": 203, "sent_patterns": {"single_char_swap": 87, "multi_char_swap": 46, "homophone_family": 10, "same_len_many_diff": 5, "len_diff_seg_or_phrase": 2}, "top10": [{"rank": 1, "wrong": "不", "gold": "部", "err": 6, "gold_freq": 112431, "wrong_freq": 1557984, "ratio": 0.07216441247150163}, {"rank": 2, "wrong": "在", "gold": "再", "err": 4, "gold_freq": 96170, "wrong_freq": 554398, "ratio": 0.17346743675121484}, {"rank": 3, "wrong": "是", "gold": "視", "err": 3, "gold_freq": 40796, "wrong_freq": 1703201, "ratio": 0.023952545824010203}, {"rank": 4, "wrong": "版", "gold": "板", "err": 3, "gold_freq": 36227, "wrong_freq": 69948, "ratio": 0.517913307028078}, {"rank": 5, "wrong": "將", "gold": "醬", "err": 2, "gold_freq": 11164, "wrong_freq": 14514, "ratio": 0.7691883698498002}, {"rank": 6, "wrong": "元", "gold": "原", "err": 2, "gold_freq": 67851, "wrong_freq": 29239, "ratio": 2.320564998802969}, {"rank": 7, "wrong": "城", "gold": "程", "err": 2, "gold_freq": 28465, "wrong_freq": 25740, "ratio": 1.105866355866356}, {"rank": 8, "wrong": "市", "gold": "式", "err": 2, "gold_freq": 31821, "wrong_freq": 49934, "ratio": 0.6372611847638884}, {"rank": 9, "wrong": "要", "gold": "腰", "err": 2, "gold_freq": 5165, "wrong_freq": 586852, "ratio": 0.008801196894617383}, {"rank": 10, "wrong": "梆", "gold": "邦", "err": 2, "gold_freq": 4152, "wrong_freq": 207, "ratio": 20.057971014492754}], "high_freq_err": 27, "low_freq_err": 64}`

**純文字結論**：錯誤主要落在語料**高頻**字對（如 不/部、在/再），不是罕見字。加資料天花板可能偏低。

---

## 2. 挖掘

```
{
  "corpus": "/Users/johnny.w_macmini/laowang-data/ptt_spoken_train_v2.txt",
  "n_corpus_lines": 5271221,
  "pair_stats": {
    "top_n_pairs": 80,
    "cand_lines": 4367450,
    "selected": 400000,
    "positions_est": 1156648
  },
  "hard_stats": {
    "scanned_lines": 800000,
    "hard_lines": 500000,
    "hard_candidates": 799668,
    "positions": 12433911,
    "err_positions": 9448316,
    "err_rate": 0.7598828719298377,
    "min_err_count_kept": 9,
    "elapsed_h": 1.0108256189028422
  },
  "min_diff_n": 6,
  "merged_lines": 857539,
  "positions_est": 15046920,
  "pair_only_lines": 400000,
  "model_only_lines": 500000,
  "model_vs_pair_extra": 457534,
  "punct_lines": 426324,
  "punct_ratio": 0.4971482346575491,
  "pollution_hits": 0,
  "synth": {
    "skipped": true,
    "reason": "scarce pairs exist but baton allows optional synth; skipping to keep isolation simple unless needed",
    "scarce_top30": [
      {
        "rank": 9,
        "wrong": "要",
        "gold": "腰",
        "err": 2,
        "gold_freq": 5165,
        "wrong_freq": 586852,
        "ratio": 0.008801196894617383
      },
      {
        "rank": 10,
        "wrong": "梆",
        "gold": "邦",
        "err": 2,
        "gold_freq": 4152,
        "wrong_freq": 207,
        "ratio": 20.057971014492754
      },
      {
        "rank": 12,
        "wrong": "就",
        "gold": "舊",
        "err": 2,
        "gold_freq": 8669,
        "wrong_freq": 781560,
        "ratio": 0.011091918726649266
      }
    ]
  },
  "hard_sha": "4fd635585f510f19f6cdd2d71dfb4bfa6e0b5ee8bb3a798e454ee0dd4199d783",
  "elapsed_h": 1.0178290400240155,
  "target_positions": 5000000,
  "hit_target": true
}
```

- 目標 ≥500 萬訓練位置：`hit_target=True`（positions_est=15046920）
- 污染命中：0
- 合成：跳過（scarce pairs exist but baton allows optional synth; skipping to keep isolation simple unless needed）
- 最小差異對：6 組
- 訓練用 hard 檔另 cap 20 萬行（完整 hard 見 hard_mined_full.txt）以控制 D1 編碼成本

---

## 3. 三變體短跑結果

| 變體 | best n_ok | best ν | nu=0.75 | mean_ms | Δ vs D0 best |
|---|---|---|---|---|---|
| D0 | 380 | 0.75 | 380 | 43.0782 | 0 |
| D1 | 385 | 1.0 | 384 | 64.3501 | 5 |
| D2 | 385 | 1.0 | 384 | 64.3501 | 5 |

### 加權倍率格（D1_w2 / w5 / w10）

```
{
  "D1_w10": {
    "best": {
      "nu": 0.5,
      "n_ok": 379,
      "mean_ms": 68.9338
    },
    "nu075": {
      "n_ok": 374,
      "mean_ms": 63.0901,
      "stdout_tail": "path scorer loaded=1 params=9781761 emb=256 hidden=512 layers=2 vocab=7937\nSLICE1_OFF 296/537\nSLICE1_ON 333/537\nSLICE1_NBEST_RANK0_MATCH 537/537\nSLICE1_WALK_MEAN_US 487.525\nSLICE2_NU0_MATCH 537/537\nNU 0.75 correct 374/537 mean_ms 63.0901\nBEST_NU 0.75 correct 374/537\n"
    }
  },
  "D1_w2": {
    "best": {
      "nu": 1.0,
      "n_ok": 385,
      "mean_ms": 67.9322
    },
    "nu075": {
      "n_ok": 384,
      "mean_ms": 64.3501,
      "stdout_tail": "path scorer loaded=1 params=9781761 emb=256 hidden=512 layers=2 vocab=7937\nSLICE1_OFF 296/537\nSLICE1_ON 333/537\nSLICE1_NBEST_RANK0_MATCH 537/537\nSLICE1_WALK_MEAN_US 481.415\nSLICE2_NU0_MATCH 537/537\nNU 0.75 correct 384/537 mean_ms 64.3501\nBEST_NU 0.75 correct 384/537\n"
    }
  },
  "D1_w5": {
    "best": {
      "nu": 0.5,
      "n_ok": 373,
      "mean_ms": 68.4783
    },
    "nu075": {
      "n_ok": 373,
      "mean_ms": 63.689,
      "stdout_tail": "path scorer loaded=1 params=9781761 emb=256 hidden=512 layers=2 vocab=7937\nSLICE1_OFF 296/537\nSLICE1_ON 333/537\nSLICE1_NBEST_RANK0_MATCH 537/537\nSLICE1_WALK_MEAN_US 478.87\nSLICE2_NU0_MATCH 537/537\nNU 0.75 correct 373/537 mean_ms 63.689\nBEST_NU 0.75 correct 373/537\n"
    }
  }
}
```

### 各變體 grid

```
D0: [[0.0, 333, 0.251084], [0.25, 366, 42.606], [0.5, 377, 43.0623], [0.75, 380, 42.6688], [1.0, 380, 42.9926], [1.5, 375, 42.7051], [2.0, 369, 47.0624]]
D1: [[0.0, 333, 0.460034], [0.25, 370, 68.219], [0.5, 384, 68.8208], [0.75, 384, 67.8337], [1.0, 385, 67.9322], [1.5, 379, 69.0803], [2.0, 376, 68.2795]]
```

---

## 4. 判定

- **主判準**：D1 best − D0 best = **5**（門檻 ≥+15 GO / +5~14 邊際 / <+5 NO-GO）
- **判定：邊際**
- D0 vs 出貨 387：D0 best=380，差 -7（短跑共同基準，不是拿 387 比 D1）
- D2 − D1 = 0（合成跳過則 0）
- 延遲：見 mean_ms（應≈出貨 44–50ms；若大偏代表有東西被改到）

### 歸因三問

1. D1 vs D0（純挖掘）：**5**
2. D2 vs D1（合成）：**0**（合成未做 → 0）
3. 倍率 2×/5×/10×：見上表；若高倍率崩則過度熱心風險成立

---

## 5. Johnny 十二題

1. 錯誤集中：**高頻字對**為主（前十多 gold_freq 數萬～百萬級）。前十見上表。
2. 挖出訓練位置估計：15046920（≥500 萬？ True）；訓練實際用 hard 20 萬行 cap。
3. 模型錯誤導向 vs 混淆對：model_only=500000 pair_only=400000 model_extra≈457534
4. 最小差異對：6 組
5. D0 短跑：380/537（ν best）；nu0.75=380；與出貨 387 差 -7
6. D1 − D0：**5**
7. D2 − D1：**0**
8. 倍率敏感度：見 D1_w* 表
9. split-half：{'method': 'fullset_nu_grid; held-out estimated by 20× bootstrap of sentence-level not available from harness aggregate — primary comparison uses fixed step budget D0 vs D1 at each nu; SH_win approx = fraction of nus where model >= D0 when both scored', 'win_rate': None, 'mean_B_net': 5, 'plateau': 'yes'}（harness 聚合輸出限制；主比較為同 step 預算 D0 vs D1 全表）
10. 脆弱度：短跑未重算 1123 剖面（需逐位置 dump）；見 residual anchors {'baseline_A': 0.8752023546725534, 'g1n': 6795, 'free_n': 83, 'frag_n': 1123}
11. single_char_swap：shipping pattern 基線 {'single_char_swap': 63, 'B': 67, 'homophone_family': 6, 'multi_char_swap': 13, 'len_diff_seg_or_phrase': 1}
12. **邊際**

---

## 已知限制

- 短跑 2h ≠ 完整 4 epoch 出貨重訓
- harness 僅聚合分數；完整 SH 需逐句 dump（已標方法限制）
- 架構未動；若 latency 異常須查權重格式

（完）
