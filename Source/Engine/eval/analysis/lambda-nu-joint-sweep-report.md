# λ/ν 聯合重掃（rerank ON, N=10）— 結論

**日期**：2026-07-24  
**性質**：純 harness，不動 app / 出貨配置  
**模型**：shipping `path-char-lstm.bin`（v2c int8, params=9734083）  
**評測**：tw538-northstar.tsv（537）

## A-2 開棒確認

| 項目 | 結論 |
|---|---|
| 死亡名單「融合公式優化 ≤+1」 | 指 `len_char` / `len_word` / `zscore` / `minmax`（`tw538_fusion_variants.cpp`），**不是** λ/ν 權重係數聯合搜索 |
| 既有掃描 | `nbest_n_nu_scan` / `tw538_nu_right_scan` / `nbest_path_rerank` 均 **鎖死 λ**，只掃 N 或 ν → **非重複工，本掃合法** |

## A-4 控制組

```text
CONTROL lambda=0.75 nu=0.75 correct 387/537
CONTROL_OK YES got=387 expected=387
in_pool 470/537
```

（stdout：`lambda-nu-control.stdout.txt`）

## A-3 結構與成本

- 外層 λ：重跑 walk + walkNBest(10) + `scoreNBest`  
- 內層 ν：純 `walk + ν·LSTM` 重加權  
- 31 × ~23s ≈ **12 min**（&lt; 2hr 停損）  
- harness：`eval/benchmarks/lambda_nu_joint_sweep.cpp`

## 結果摘要

| 指標 | 值 |
|---|---|
| 出貨格 (0.75, 0.75) | **387/537**，池 470 |
| **全表最佳** | **λ=0.70, ν=0.50 → 391/537**（**+4**） |
| 次佳（多格） | 390（3 格）、389（7 格）、388（15 格）；≥388 共 26 格 |

### 池覆蓋 vs λ（N=10）

| λ | in_pool/537 |
|---|---|
| 0.00 | 434 |
| 0.55 | **473（峰）** |
| 0.70 | 472 |
| 0.75 | 470 |
| 1.50 | 429 |

**待驗假設**（λ 過強擠出池）：高 λ（→1.5）確實池變小；但 **λ→0 池更差（434）**，峰在 **0.5–0.7 附近**，不是「越低越好」。曲線：`lambda-pool-coverage-vs-lambda.tsv`。

## 結論（給 Johnny 拍板）

1. **不是 ≤+1 噪音**：最佳 **+4 句**（391），且多格 ≥388，座標下降未鎖死在 (0.75, 0.75)。  
2. **本棒不改出貨**：依棒規只回報；改 (λ,ν) 會連動 387、CHANGELOG、Release 文案。  
3. **建議候選**（若日後要動配置）：`λ=0.70, ν=0.50`（391），或在 0.60–0.75 / ν≈0.5–0.7 高原帶細掃。  
4. **不寫入「維持 0.75/0.75」死亡名單**（該條款僅適用增益 ≤+1）。

## 產物

| 檔 | 內容 |
|---|---|
| `lambda-nu-joint-sweep.tsv` | 全表 (λ,ν,correct,total,in_pool) |
| `lambda-pool-coverage-vs-lambda.tsv` | 池覆蓋 vs λ |
| `lambda-nu-control.stdout.txt` | 控制組 |
| `lambda-nu-joint-sweep.stdout.txt` | 全掃原始 stdout |
