#!/usr/bin/env python3
# Representation 稽核（棒⑭-H）：現在的表徵到底缺什麼資訊？
#
# ⚠️ **這是 representation diagnostic，不是 model training result。**
# 這裡訓練的是「診斷用的簡單線性分類器」，不是 Node Expert，
# 也不會產生任何可上線的權重。τ、架構、production 全部沒動。
#
# ## 要分辨的目標
#
#   neg（不該出手）：engine=作 ∧ span=1 ∧ gold=作
#   pos（該出手）  ：engine=作 ∧ span=1 ∧ gold∈{做,座,坐}
#
# ## 三個 feature family（全部只用推論時拿得到的資訊）
#
#   A 上下文字元（±k，k 由參數掃）
#   B 詞彙／節點邊界（左右詞長度、是否多字詞、位置、句長…）
#   C 引擎信心（候選 unigram 分數、top1−top2、排名、候選數、熵、PMI…）
#
# **沒有任何 feature 使用金標、人工標註、或未來的正確輸出。**
# 逐項來源與「推論時是否可得」列在報告裡。
#
# ## 評估
#
# document-level 5-fold（沿用 baton14f-fold-v1），診斷分類器在 4 個 fold 上
# 訓練、在第 5 個上預測，把 out-of-fold 預測接起來算 AUC。
# CI 用 **以文件為單位的 bootstrap**（同一份文件的節點不獨立）。

import argparse
import collections
import json
import math
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FIRE = 'ㄗㄨㄛˋ'
GROUP = set('作做坐座')


def roc_auc(score, label):
    pos = [s for s, l in zip(score, label) if l == 1]
    neg = [s for s, l in zip(score, label) if l == 0]
    if not pos or not neg:
        return float('nan')
    a = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    rk, i = {}, 0
    while i < len(a):
        j = i
        while j < len(a) and a[j][0] == a[i][0]:
            j += 1
        for k in range(i, j):
            rk[k] = (i + j + 1) / 2
        i = j
    s = sum(rk[k] for k in range(len(a)) if a[k][1] == 1)
    return (s - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def pr_auc(score, label):
    order = np.argsort(-np.asarray(score))
    y = np.asarray(label)[order]
    tp = np.cumsum(y)
    prec = tp / np.arange(1, len(y) + 1)
    rec = tp / max(y.sum(), 1)
    ap, prev = 0.0, 0.0
    for p, r in zip(prec, rec):
        ap += p * (r - prev)
        prev = r
    return ap


def boot_ci(score, label, docs, n=1000, seed=0):
    """以**文件**為單位重抽（同一份文件的節點不獨立）。"""
    rng = np.random.default_rng(seed)
    by = collections.defaultdict(list)
    for i, d in enumerate(docs):
        by[d].append(i)
    keys = list(by)
    out = []
    for _ in range(n):
        pick = rng.choice(len(keys), len(keys), replace=True)
        idx = [i for k in pick for i in by[keys[k]]]
        s = [score[i] for i in idx]
        l = [label[i] for i in idx]
        if 0 < sum(l) < len(l):
            out.append(roc_auc(s, l))
    if not out:
        return (float('nan'), float('nan'))
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)))


def load(nodes, sents, tag, folds):
    sid2doc, sid2text = {}, {}
    with open(sents, encoding='utf-8') as fh:
        for i, line in enumerate(fh, start=1):
            j = json.loads(line)
            sid2doc[i], sid2text[i] = j['doc_id'], j['text']
    out = []
    with open(nodes, encoding='utf-8') as fh:
        head = next(fh).rstrip('\n').split('\t')
        for line in fh:
            c = dict(zip(head, line.rstrip('\n').split('\t')))
            if int(c['kind']) != 0 or int(c['span']) != 1:
                continue
            syls = c['reading'].split('-')
            if FIRE not in syls or len(syls) != 1:
                continue
            e, g = c['chosen'], c['gold']
            if e != '作' or g not in GROUP:
                continue
            cands = []
            for part in c['cands'].split('|'):
                q = part.split(':')
                if len(q) == 5:
                    cands.append((q[0], float(q[1]), float(q[2]), float(q[3])))
            cands.sort(key=lambda x: -x[1])
            if len(cands) < 2:
                continue
            sid = int(c['sid'])
            out.append({
                'src': tag, 'doc': sid2doc[sid], 'text': sid2text[sid],
                'pos': int(c['char_start']), 'engine': e, 'gold': g,
                'left_word': c['left_word'], 'right_word': c['right_word'],
                'left': c['left_chars'], 'right': c['right_chars'],
                'right_empty': c['right_empty'] == '1', 'cands': cands,
                'fold': folds.get(sid2doc[sid], 0),
                'label': 0 if g == '作' else 1,
            })
    return out


def feat_A(r, k, vocab, source='walk'):
    """A：上下文字元（±k）。

    `source='walk'`：用 nodes.tsv 的 left_chars／right_chars ——
      那是**引擎 walk 解出來的字**，推論時真的拿得到。抽取器只寫 ±6，
      所以 walk 版只有 ±6。**這是唯一無洩漏的版本。**
    `source='gold'`：用語料原文。推論時**拿不到**（原文就是答案所在的那個句子），
      只用來當「上下文資訊量的樂觀上界」，以及量出兩者差距。
    """
    v = np.zeros(len(vocab) * 2, dtype=np.float32)
    if source == 'walk':
        left, right = r['left'][-k:], r['right'][:k]
    else:
        left = r['text'][max(0, r['pos'] - k):r['pos']]
        right = r['text'][r['pos'] + 1:r['pos'] + 1 + k]
    for ch in left:
        if ch in vocab:
            v[vocab[ch]] += 1
    for ch in right:
        if ch in vocab:
            v[len(vocab) + vocab[ch]] += 1
    return v


def feat_B(r):
    """B：詞彙／節點邊界。全部來自引擎的 walk 與斷詞。"""
    lw, rw = r['left_word'], r['right_word']
    return np.array([
        len(lw), len(rw), 1.0 if len(lw) > 1 else 0.0, 1.0 if len(rw) > 1 else 0.0,
        1.0 if not lw else 0.0, 1.0 if not rw else 0.0,
        1.0 if r['right_empty'] else 0.0,
        r['pos'], len(r['text']) - r['pos'] - 1, len(r['text']),
    ], dtype=np.float32)


def feat_C(r):
    """C：引擎信心。全部由既有 candidate lattice 直接算得，不新增評分。"""
    u = np.array([c[1] for c in r['cands']], dtype=np.float64)
    names = [c[0] for c in r['cands']]
    p = np.exp(u - u.max())
    p = p / p.sum()
    ent = float(-(p * np.log(p + 1e-12)).sum())
    ue = next((c[1] for c in r['cands'] if c[0] == '作'), u[0])
    rank = names.index('作') + 1 if '作' in names else len(names) + 1
    def gap(ch):
        s = next((c[1] for c in r['cands'] if c[0] == ch), None)
        return (ue - s) if s is not None else 99.0
    pl = next((c[2] for c in r['cands'] if c[0] == '作'), 0.0)
    pr_ = next((c[3] for c in r['cands'] if c[0] == '作'), 0.0)
    return np.array([
        u[0], u[1], u[0] - u[1], ue, float(rank), float(len(u)), ent,
        gap('做'), gap('座'), gap('坐'), pl, pr_,
        float(p[0]), float(p[0] - p[1]),
    ], dtype=np.float32)


def fit_lr(X, y, l2=1.0, steps=400):
    """固定容量的 L2 正則化 logistic regression（診斷用，不是產品模型）。"""
    Xt = torch.tensor(X, dtype=torch.float32)
    yt = torch.tensor(y, dtype=torch.float32)
    w = torch.zeros(X.shape[1], requires_grad=True)
    b = torch.zeros(1, requires_grad=True)
    opt = torch.optim.LBFGS([w, b], max_iter=steps, line_search_fn='strong_wolfe')

    def closure():
        opt.zero_grad()
        z = Xt @ w + b
        loss = torch.nn.functional.binary_cross_entropy_with_logits(z, yt)
        loss = loss + l2 * (w * w).sum() / len(y)
        loss.backward()
        return loss
    opt.step(closure)
    return w.detach().numpy(), float(b.detach())


def oof_scores(rows, featfn, dim, l2):
    """document-level 5-fold 的 out-of-fold 預測。"""
    X = np.stack([featfn(r) for r in rows])
    mu, sd = X.mean(0), X.std(0) + 1e-6
    y = np.array([r['label'] for r in rows], dtype=np.float32)
    s = np.zeros(len(rows))
    for fi in range(5):
        te = np.array([i for i, r in enumerate(rows) if r['fold'] == fi])
        tr = np.array([i for i, r in enumerate(rows) if r['fold'] != fi])
        if not len(te) or not len(tr):
            continue
        Xtr = (X[tr] - mu) / sd
        w, b = fit_lr(Xtr, y[tr], l2=l2)
        s[te] = ((X[te] - mu) / sd) @ w + b
    return s, y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--sentences', required=True)
    ap.add_argument('--nodes2', default='')
    ap.add_argument('--sentences2', default='')
    ap.add_argument('--folds', required=True)
    ap.add_argument('--l2', type=float, default=2.0)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    fj = json.load(open(args.folds, encoding='utf-8'))
    rows = load(args.nodes, args.sentences, 'train-src', fj['assign'])
    if args.nodes2:
        rows += load(args.nodes2, args.sentences2, 'contexts', fj['assign'])
    seen = set()
    ded = []
    for r in rows:
        k = (r['doc'], r['text'], r['pos'])
        if k in seen:
            continue
        seen.add(k)
        ded.append(r)
    rows = ded

    cnt = collections.Counter()
    for ch in ''.join(r['text'] for r in rows):
        cnt[ch] += 1
    vocab = {ch: i for i, (ch, n) in enumerate(
        c for c in cnt.most_common() if c[1] >= 3)}

    docs = [r['doc'] for r in rows]
    out = []
    w = out.append
    w('# Representation 稽核（棒⑭-H）\n')
    w('> **這是 representation diagnostic，不是 model training result。**\n')
    w('> 這裡訓練的是診斷用的 L2 logistic regression，不是 Node Expert；')
    w('> τ、架構、特徵管線、production 全部沒動，沒有產生任何可上線的權重。\n')
    n1 = sum(1 for r in rows if r['label'] == 1)
    w(f'\n診斷集：engine=作 ∧ 單字節點 ∧ gold∈作做坐座，'
      f'共 **{len(rows)}**（該出手 {n1}、不該出手 {len(rows) - n1}）；'
      f'涵蓋 {len(set(docs))} 份文件。**標籤用語料金標**'
      f'（人工核驗證實母體加權 99.4–99.6% 正確）。\n')
    w(f'\n上下文字元表：出現 ≥3 次的字 {len(vocab)} 個。'
      f'診斷分類器容量固定（同一組 vocab、同一個 L2={args.l2}），只有窗口在變。\n')

    sets = []
    sets.append(('**A-walk ±6（無洩漏）**',
                 lambda r: feat_A(r, 6, vocab, 'walk')))
    for k in (6, 10, 15):
        sets.append((f'A-gold ±{k}（樂觀上界）',
                     lambda r, k=k: feat_A(r, k, vocab, 'gold')))
    sets.append(('B：詞彙／邊界', feat_B))
    sets.append(('C：引擎信心', feat_C))
    sets.append(('A-walk±6 + B', lambda r: np.concatenate([feat_A(r, 6, vocab, 'walk'), feat_B(r)])))
    sets.append(('A-walk±6 + C', lambda r: np.concatenate([feat_A(r, 6, vocab, 'walk'), feat_C(r)])))
    sets.append(('B + C', lambda r: np.concatenate([feat_B(r), feat_C(r)])))
    sets.append(('**A-walk±6 + B + C**', lambda r: np.concatenate(
        [feat_A(r, 6, vocab, 'walk'), feat_B(r), feat_C(r)])))
    sets.append(('A-gold±15 + B + C（樂觀）', lambda r: np.concatenate(
        [feat_A(r, 15, vocab, 'gold'), feat_B(r), feat_C(r)])))

    w('\n## 結果（out-of-fold，document-level 5-fold）\n')
    w('| Feature set | 維度 | ROC-AUC | 95% CI（文件 bootstrap） | PR-AUC |')
    w('|---|---|---|---|---|')
    store = {}
    for name, fn in sets:
        s, y = oof_scores(rows, fn, None, args.l2)
        a = roc_auc(s, y)
        lo, hi = boot_ci(list(s), list(y), docs)
        store[name] = (s, y)
        w(f'| {name} | {len(fn(rows[0]))} | **{a:.3f}** | [{lo:.3f}, {hi:.3f}] | '
          f'{pr_auc(s, y):.3f} |')

    w('\n## 逐 pairwise（作→作 vs 各組）\n')
    w('| Feature set | vs 作→做 | vs 作→座 | vs 作→坐 |')
    w('|---|---|---|---|')
    for name, _ in sets:
        s, y = store[name]
        cells = []
        for g in ('做', '座', '坐'):
            idx = [i for i, r in enumerate(rows) if r['gold'] in ('作', g)]
            sc = [s[i] for i in idx]
            lb = [1 if rows[i]['gold'] == g else 0 for i in idx]
            dd = [rows[i]['doc'] for i in idx]
            a = roc_auc(sc, lb)
            lo, hi = boot_ci(sc, lb, dd, n=400)
            cells.append(f'{a:.3f} [{lo:.2f}, {hi:.2f}]')
        w(f'| {name} | ' + ' | '.join(cells) + ' |')

    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out) + '\n')
    print('\n'.join(out))


if __name__ == '__main__':
    main()
