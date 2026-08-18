# Prototype-001 — Contextual Candidate Decision

**研究用 prototype，不是 production code。**
不修改 production、不被 production import、不接輸入法、不 merge、不 enable。

把 ⑭-I 證明有價值的「candidate × local context interaction」做成第一個
可訓練、可推論、可觀察的模型。決策是純 `argmax`，沒有 threshold。

完整報告：`Source/Engine/eval/analysis/baton16-ccd-prototype.md`

## 跑起來

```bash
V=~/laowang-data/baton13-node-homophone/.venv/bin/python
W=~/laowang-data/baton13-node-homophone

# 訓練（約 42 秒，CPU）
$V -m prototype.ccd.cli train \
   --nodes $W/data/nodes.tsv --sentences $W/data/sentences.jsonl \
   --out ~/laowang-data/baton16-ccd/ccd-v0.1.pt --epochs 4

# 評估 held-out fold（約 3 秒）
$V -m prototype.ccd.cli evaluate \
   --ckpt ~/laowang-data/baton16-ccd/ccd-v0.1.pt \
   --nodes $W/data/nodes.tsv --sentences $W/data/sentences.jsonl --examples 25

# 單點預測
$V -m prototype.ccd.cli predict \
   --ckpt ~/laowang-data/baton16-ccd/ccd-v0.1.pt \
   --context 我今天想要 --right 一件事情 --reading ㄗㄨㄛˋ --candidates 做,作,坐,座
```

`--help` 可用。checkpoint 不進 repo（3.9 MB），用上面的指令 42 秒重建。

## 注意

`predict` 沒有引擎算的 unigram / PMI，數值特徵以訓練集平均代入，
只反映「脈絡 × 候選」這一半的訊號，與 `evaluate` 條件不同。
