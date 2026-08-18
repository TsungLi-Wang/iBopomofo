# -*- coding: utf-8 -*-
"""Prototype-001：Contextual Candidate Decision model。

**prototype code，不是 production code。**

## 設計來源

⑭-H 量到局部 context ±6 含有可用的判別訊號；
⑭-I 量到把「候選 × 局部脈絡」做成明確的 interaction，
比單純把 context 與 candidate 串接再送 MLP 好（診斷 ROC-AUC 0.792，五個 fold 都 >= 0.76）。

本檔重新實作那個核心想法 —— **不載入 I2 checkpoint**，
只沿用架構概念。

## 明確要表達的東西

不是：

    concat(context_emb, candidate_emb) -> MLP

而是讓模型能直接表示 **candidate x context**：

    left_last  (*) candidate          相鄰左字與候選的交互
    candidate  (*) right_first        候選與相鄰右字的交互
    left_pool  (*) candidate          視窗左側整體與候選的交互
    candidate  (*) right_pool         候選與視窗右側整體的交互

(*) = element-wise product。

再加上候選本身的身分、讀音、以及引擎在推論時就算好的
數值特徵（unigram 分數、左右 PMI、是否為 walk 當下的選擇）。

## 輸出

對候選集合中**每一個候選各自**輸出一個 scalar score。
v0.1 的決策就是 `argmax`，**不引入任何 threshold**。
"""

import torch
import torch.nn as nn

WIN = 6
CAND_FEATS = 5  # unigram, pmi_left, pmi_right, is_walk_choice, right_empty


# 棒⑰ ablation 變體。四者共用同一份 protocol，只切掉輸入區塊。
#   full            原版
#   no-interaction  拿掉四組 candidate x context 交互
#   no-numeric      拿掉候選數值特徵（unigram / PMI / is_walk_choice / right_empty）
#   context-only    candidate-independent 對照：不看候選身分、不看候選數值、無交互
#                   → 同一節點內所有候選同分，argmax 落在第 0 個候選
#                     （候選依 unigram 分數排序，等同「永遠取詞頻第一名」）
VARIANTS = ("full", "no-interaction", "no-numeric", "context-only")


class ContextualCandidateDecision(nn.Module):
    def __init__(self, n_char, n_reading, emb=64, rd_emb=32, hid=128,
                 variant="full"):
        super().__init__()
        assert variant in VARIANTS, variant
        self.variant = variant
        self.use_inter = variant in ("full", "no-numeric")
        self.use_numeric = variant in ("full", "no-interaction")
        self.use_cand = variant != "context-only"
        self.emb = emb
        self.char = nn.Embedding(n_char, emb, padding_idx=0)
        self.reading = nn.Embedding(n_reading, rd_emb, padding_idx=0)

        # 局部脈絡編碼：左右各 WIN 個字，位置各自有權重
        self.left_proj = nn.Linear(emb * WIN, emb)
        self.right_proj = nn.Linear(emb * WIN, emb)

        # candidate x context 的四組 element-wise 交互 -> 4 * emb
        d = emb * 2 + rd_emb                       # 左右脈絡摘要 + 讀音（永遠有）
        if self.use_inter:
            d += emb * 4
        if self.use_cand:
            d += emb                               # 候選身分
        if self.use_numeric:
            d += CAND_FEATS
        self.mlp = nn.Sequential(
            nn.Linear(d, hid), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(hid, hid // 2), nn.ReLU(),
            nn.Linear(hid // 2, 1),
        )

    def forward(self, left, right, reading, cand, feats, mask):
        """
        left   (B, WIN)      左側 ±6 的 char id（最後一個 = 緊鄰目標）
        right  (B, WIN)      右側 ±6 的 char id（第一個 = 緊鄰目標）
        reading(B,)          讀音 id
        cand   (B, C)        候選 char id
        feats  (B, C, F)     候選的數值特徵
        mask   (B, C)        候選是否存在
        回傳   (B, C)        每個候選的 scalar score
        """
        B, C = cand.shape
        le = self.char(left)                       # B, WIN, E
        re = self.char(right)
        lp = torch.tanh(self.left_proj(le.reshape(B, -1)))    # B, E
        rp = torch.tanh(self.right_proj(re.reshape(B, -1)))   # B, E
        l_last = le[:, -1, :]                      # 緊鄰左字
        r_first = re[:, 0, :]                      # 緊鄰右字
        rd = self.reading(reading)                 # B, R

        ce = self.char(cand)                       # B, C, E

        def ex(v):
            return v.unsqueeze(1).expand(B, C, v.shape[-1])

        blocks = []
        if self.use_inter:
            blocks += [
                ex(l_last) * ce,     # 左鄰字 x 候選
                ce * ex(r_first),    # 候選 x 右鄰字
                ex(lp) * ce,         # 左視窗摘要 x 候選
                ce * ex(rp),         # 候選 x 右視窗摘要
            ]
        if self.use_cand:
            blocks.append(ce)
        blocks += [ex(lp), ex(rp), ex(rd)]
        if self.use_numeric:
            blocks.append(feats)
        ctx = torch.cat(blocks, dim=-1)
        s = self.mlp(ctx).squeeze(-1)              # B, C
        return s.masked_fill(~mask, -1e4)


def pairwise_loss(scores, gold_idx, mask):
    """pairwise logistic ranking loss：gold 要贏過同一個候選集合裡的其他候選。"""
    B, C = scores.shape
    idx = gold_idx.unsqueeze(1)
    gold_s = scores.gather(1, idx)                 # B, 1
    neg = mask.clone()
    neg.scatter_(1, idx, False)
    diff = gold_s - scores                         # B, C
    loss = torch.nn.functional.softplus(-diff)
    loss = (loss * neg).sum(dim=1) / neg.sum(dim=1).clamp(min=1)
    return loss.mean()
