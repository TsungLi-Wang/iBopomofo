#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棒⑭-S：固定 top-10 候選集上的 learned path reranker（一次性研究實驗）。

**禁止 merge / enable / 接 app / 跑正式 test / 改 production。**
本檔訓練的是**研究用**權重，不匯出任何可上線的格式。

## 唯一問題

候選集**完全固定**為 production `walkNBest(10)` 已經產生的 10 條路徑。
本棒測的是 **RERANKING CAPABILITY**，不是 SEARCH CAPABILITY ——
不重新搜尋、不加深到 20/200、不動候選生成。

    learned scorer 能不能突破 ⑭-R 的
    CROSS-FITTED COUNTERFACTUAL BASELINE = **+69 字**？

## 紀律（本棒只有一組設定，失敗就記錄失敗）

* 一個模型（單隱藏層 MLP）、一組 feature、一個 objective（pairwise logistic）、
  一個 5-fold protocol。**不因結果不好而回頭改任何一項。**
* 決策規則是純 `argmax`，**不引入任何 threshold**。
* fold ＝ canonical `sha256(f'baton14f-fold-v1:{doc_id}')[:8] % 5`，
  與 ⑭-F 起沿用的同一套，不重新設計。
* normalization 只在 training fold 上 fit。

## Feature 紀律

全部由**推論時就在手上的 10 條路徑**算出來：各 component 的原始分數、
句內相對量（減最大值、z 分數、名次）、長度正規化、DP 名次。
**沒有任何 gold 相關量** —— gold 只用來造 training pair 與評分，不進 feature。
`gold_rank` 這類 offline-only 欄位一律不用。

用法：
  python3 train_path_reranker.py --paths <paths-all.tsv> --items <語料.jsonl> \\
      --out <報告片段.md>
"""

import argparse
import collections
import hashlib
import json
import math
import random

import numpy as np
import torch

SALT = 'baton14f-fold-v1'
K = 5
SEED = 20260818
BASELINE_NET = 69          # ⑭-R CROSS-FITTED COUNTERFACTUAL BASELINE
CEILING_CHARS = 1198       # ⑭-P 可達 top-10 oracle = 37.5% of D2
D2 = 3192
TOTAL_CHARS = 74649

COMPS = ['walk_score', 'unigram_sum', 'pmi', 'rnn', 'fused']


def fold_of(doc):
    return int(hashlib.sha256(f'{SALT}:{doc}'.encode()).hexdigest()[:8], 16) % K


def load(paths_tsv, items_jsonl):
    meta = {}
    with open(items_jsonl, encoding='utf-8') as fh:
        for i, line in enumerate(fh, start=1):
            if line.strip():
                d = json.loads(line)
                meta[str(i)] = d
    sents = collections.defaultdict(list)
    with open(paths_tsv, encoding='utf-8') as fh:
        head = next(fh).rstrip('\n').split('\t')
        for line in fh:
            f = dict(zip(head, line.rstrip('\n').split('\t')))
            sents[f['sid']].append({
                'idx': int(f['path_idx']), 'n_err': int(f['n_err']),
                'is_walk': f['is_walk'] == '1', 'is_gold': f['is_gold'] == '1',
                'ok': f['engine_correct'] == '1',
                'walk_score': float(f['walk_score']),
                'unigram_sum': float(f['unigram_sum']),
                'pmi': float(f['pmi']), 'rnn': float(f['rnn']),
                'fused': float(f['fused']),
            })
    out = {}
    for sid, ps in sents.items():
        m = meta.get(sid)
        if m is None:
            continue
        out[sid] = {'paths': sorted(ps, key=lambda p: p['idx']),
                    'doc': m['sentence_id'], 'len': len(m['sentence']),
                    'fold': fold_of(m['sentence_id'])}
    return out


# ── Feature（全部 inference-available，無 gold）────────────────────────────
FEATURE_NAMES = []
for c in COMPS:
    FEATURE_NAMES += [f'{c}', f'{c}_minus_max', f'{c}_z', f'{c}_rank',
                      f'{c}_per_char']
FEATURE_NAMES += ['dp_rank', 'dp_rank_is0', 'log_len', 'n_paths']


def featurize(rec):
    ps = rec['paths']
    L = max(rec['len'], 1)
    n = len(ps)
    cols = {}
    for c in COMPS:
        v = np.array([p[c] for p in ps], dtype=np.float64)
        mx = v.max()
        sd = v.std() + 1e-9
        order = (-v).argsort()
        rank = np.empty(n)
        rank[order] = np.arange(n)
        cols[c] = np.stack([v, v - mx, (v - v.mean()) / sd,
                            rank / max(n - 1, 1), v / L], axis=1)
    extra = np.stack([
        np.array([p['idx'] for p in ps], dtype=np.float64) / max(n - 1, 1),
        np.array([1.0 if p['idx'] == 0 else 0.0 for p in ps]),
        np.full(n, math.log(L)),
        np.full(n, float(n)),
    ], axis=1)
    return np.concatenate([cols[c] for c in COMPS] + [extra], axis=1)


class Scorer(torch.nn.Module):
    def __init__(self, d, hid=32):
        super().__init__()
        self.net = torch.nn.Sequential(
            torch.nn.Linear(d, hid), torch.nn.Tanh(), torch.nn.Linear(hid, 1))

    def forward(self, x):
        return self.net(x).squeeze(-1)


def train_fold(train_recs, d, epochs=60, lr=1e-3, l2=1e-4):
    torch.manual_seed(SEED)
    model = Scorer(d)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=l2)
    rng = random.Random(SEED)
    batches = list(train_recs)
    for ep in range(epochs):
        rng.shuffle(batches)
        for i in range(0, len(batches), 64):
            chunk = batches[i:i + 64]
            loss = 0.0
            cnt = 0
            opt.zero_grad()
            for r in chunk:
                gi = [j for j, p in enumerate(r['paths']) if p['is_gold']]
                ni = [j for j, p in enumerate(r['paths']) if not p['is_gold']]
                if not gi or not ni:
                    continue
                s = model(torch.from_numpy(r['X']).float())
                diff = s[gi].unsqueeze(1) - s[ni].unsqueeze(0)
                loss = loss + torch.nn.functional.softplus(-diff).mean()
                cnt += 1
            if not cnt:
                continue
            (loss / cnt).backward()
            opt.step()
    return model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--paths', required=True)
    ap.add_argument('--items', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    recs = load(args.paths, args.items)
    for r in recs.values():
        r['X'] = featurize(r)
        r['gold_in'] = any(p['is_gold'] for p in r['paths'])
        r['cur'] = next(p for p in r['paths'] if p['is_walk'])

    d = next(iter(recs.values()))['X'].shape[1]
    L, w = [], None
    L = []
    w = L.append

    # ── leakage / feature audit ──
    w('## Feature provenance（只有 available_at_inference = YES 才進模型）\n')
    w('| feature 群 | source | available at inference? | training-only? | '
      'gold-dependent? | leakage risk |')
    w('|---|---|---|---|---|---|')
    for c in COMPS:
        src = {'walk_score': 'ReadingGrid DP 分數', 'unigram_sum': '節點 unigram 總和',
               'pmi': 'CorpusBigramContextModel', 'rnn': 'NeuralLMPathScorer',
               'fused': 'walkScore + ν·rnn（出貨分數）'}[c]
        w(f'| {c}（原始／減最大／z／句內名次／每字）| {src} | **YES** | NO | '
          f'**NO** | 無 —— 只由 10 條路徑本身算出 |')
    w('| dp_rank、dp_rank_is0 | `walkNBest` 回傳順序 | **YES** | NO | **NO** | 無 |')
    w('| log_len、n_paths | 讀音長度、候選數 | **YES** | NO | **NO** | 無 |')
    w(f'\n共 **{d}** 維。**明確排除**：corpus gold、gold 字、gold path 身分、'
      f'`gold_rank`（offline-only）、人工標註、未來字、以 gold 重新斷詞的任何量。\n')
    w('\n`is_gold` 只用於 (a) 造 training pair、(b) 評分，**未進入 feature**。\n')

    trainable = [r for r in recs.values() if r['gold_in']]
    w(f'\n## 資料集\n')
    w(f'* 句子 **{len(recs):,}**（＝文件；一句一個 `doc_id`）')
    ok = sum(1 for r in recs.values() if r['cur']['n_err'] == 0)
    w(f'* ENGINE-CORRECT {ok:,} ／ ENGINE-WRONG {len(recs)-ok:,}')
    w(f'* **gold path ∈ top-10 的 {len(trainable):,} 句可造 pair**；'
      f'其餘 {len(recs)-len(trainable):,} 句標 `GOLD_ABSENT_FROM_TOP10`，'
      f'**不進 training**，只進評估與 ceiling')
    w(f'* fold ＝ `sha256(f"{SALT}:{{doc_id}}")[:8] % {K}`（canonical，未重新設計）')
    w('\n| fold | 句數 | 可訓練句 | ENGINE-WRONG |')
    w('|---|---|---|---|')
    for k in range(K):
        f_ = [r for r in recs.values() if r['fold'] == k]
        w(f'| {k} | {len(f_):,} | {sum(1 for r in f_ if r["gold_in"]):,} | '
          f'{sum(1 for r in f_ if r["cur"]["n_err"]>0):,} |')

    # ── 5-fold cross-fitting ──
    pred = {}
    for k in range(K):
        tr = [r for r in trainable if r['fold'] != k]
        te = [r for sid, r in recs.items() if r['fold'] == k]
        X = np.concatenate([r['X'] for r in tr], axis=0)
        mu, sd = X.mean(0), X.std(0) + 1e-9        # 只在 training fold fit
        for r in tr:
            r['Xn'] = (r['X'] - mu) / sd
        model = train_fold(
            [{'paths': r['paths'], 'X': r['Xn']} for r in tr], d)
        model.eval()
        with torch.no_grad():
            for r in te:
                s = model(torch.from_numpy((r['X'] - mu) / sd).float()).numpy()
                r['pick'] = r['paths'][int(np.argmax(s))]
                r['score'] = s

    # ── 主結果 ──
    def tally(sel):
        rescue = damage = 0
        cur = new = 0
        rs = ds = 0
        for r in recs.values():
            c, n = r['cur']['n_err'], sel(r)['n_err']
            cur += c
            new += n
            rescue += max(0, c - n)
            damage += max(0, n - c)
            if c > 0 and n == 0:
                rs += 1
            if c == 0 and n > 0:
                ds += 1
        return dict(rescue=rescue, damage=damage, net=cur - new, cur=cur,
                    new=new, rs=rs, ds=ds)

    res = tally(lambda r: r['pick'])
    w('\n\n## Cross-fitted 主結果\n')
    w('| 量 | 值 |')
    w('|---|---|')
    w(f'| 現況 walk 錯字（D2）| {res["cur"]:,} |')
    w(f'| reranker 後錯字 | {res["new"]:,} |')
    w(f'| **rescue（字）** | {res["rescue"]:,} |')
    w(f'| **damage（字）** | {res["damage"]:,} |')
    w(f'| **net（字）** | **{res["net"]:+,}** |')
    prec = res['rescue'] / (res['rescue'] + res['damage']) if (res['rescue'] + res['damage']) else float('nan')
    w(f'| rescue precision | {prec:.3f} |')
    w(f'| 字級正確率 | {100*(1-res["cur"]/TOTAL_CHARS):.3f}% → '
      f'**{100*(1-res["new"]/TOTAL_CHARS):.3f}%** |')
    w(f'| 整句由錯轉全對 | {res["rs"]:,} |')
    w(f'| 整句由全對轉錯 | {res["ds"]:,} |')
    w(f'| 佔 D2 | {res["net"]/D2:+.1%} |')

    # ── document-cluster bootstrap ──
    rng = np.random.default_rng(0)
    sids = list(recs)
    per = {s: (recs[s]['cur']['n_err'] - recs[s]['pick']['n_err']) for s in sids}
    boots = []
    for _ in range(2000):
        pick = rng.choice(len(sids), len(sids), replace=True)
        boots.append(sum(per[sids[i]] for i in pick))
    boots.sort()
    lo, hi = boots[50], boots[1949]
    w(f'\n**95% CI（document-cluster bootstrap，2,000 次）：'
      f'[{lo:+,}, {hi:+,}]**')

    # ── 對照 ⑭-R ──
    w('\n\n## 與 ⑭-R 的對照\n')
    w('| | ⑭-R baseline | ⑭-S reranker |')
    w('|---|---|---|')
    w('| 方法 | `CROSS-FITTED COUNTERFACTUAL`（掃 ν′）| `CROSS-FITTED` learned MLP |')
    w(f'| rescue | 177 | {res["rescue"]:,} |')
    w(f'| damage | 108 | {res["damage"]:,} |')
    w(f'| **net** | **+69** | **{res["net"]:+,}** |')
    w(f'| precision | 0.621 | {prec:.3f} |')
    w(f'| char accuracy | 95.799% | {100*(1-res["new"]/TOTAL_CHARS):.3f}% |')
    w(f'| 95% CI | 未算（點估計）| [{lo:+,}, {hi:+,}] |')
    w('\n⚠️ baseline 是 `CROSS-FITTED COUNTERFACTUAL`，**不是 production 結果**。')

    # ── ranking metrics（secondary）──
    w('\n\n## Ranking metrics（secondary，不得取代 net）\n')
    gp = [r for r in recs.values() if r['gold_in']]
    w('| 指標 | 現有 fused | reranker |')
    w('|---|---|---|')
    for lbl, kf in (('top-1 命中 gold', None),):
        pass
    def rank_stats(key):
        t1 = t2 = 0
        mrr = 0.0
        win = tot = 0
        for r in gp:
            v = key(r)
            order = np.argsort(-v)
            gi = {j for j, p in enumerate(r['paths']) if p['is_gold']}
            for pos, j in enumerate(order, start=1):
                if j in gi:
                    t1 += pos == 1
                    t2 += pos <= 2
                    mrr += 1 / pos
                    break
            for j, p in enumerate(r['paths']):
                if p['is_gold']:
                    for j2, p2 in enumerate(r['paths']):
                        if not p2['is_gold']:
                            tot += 1
                            win += v[j] > v[j2]
        n = len(gp)
        return t1 / n, t2 / n, mrr / n, win / tot
    a = rank_stats(lambda r: np.array([p['fused'] for p in r['paths']]))
    b = rank_stats(lambda r: r['score'])
    for i, lbl in enumerate(('top-1 accuracy', 'top-2 accuracy', 'MRR',
                             'pairwise accuracy')):
        w(f'| {lbl} | {a[i]:.3f} | **{b[i]:.3f}** |')
    w(f'\n（母體：gold ∈ top-10 的 {len(gp):,} 句。'
      f'現有 fused 的 top-1 = 引擎解對率，非獨立指標。）')

    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    print('\n'.join(L))
    json.dump({s: {'cur': recs[s]['cur']['n_err'],
                   'new': recs[s]['pick']['n_err'],
                   'fold': recs[s]['fold']} for s in recs},
              open(args.out + '.per-sentence.json', 'w'), ensure_ascii=False)


if __name__ == '__main__':
    main()
