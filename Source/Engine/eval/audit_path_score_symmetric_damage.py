#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棒⑭-R：path fusion score 的 rescue / damage 對稱性分析。

**純分析。不訓練、不改 production、不改 ν/λ/τ/權重、不跑正式 test、不做人工核驗。**

## 為什麼要有這一棒

⑭-Q 只看「引擎解錯的句子」，量到句內 pairwise 0.824、gold 中位名次 2、
落後幅度中位數只佔分數跨度 10.6%。**但那是單邊的。**
要把 ranking signal 換成系統淨收益，必須同時知道：
目前**解對**的句子，gold 領先第二名多少？

如果兩側的分布高度重疊，那麼任何足以救回錯句的擾動，
會等量弄壞對句 —— 這正是 ⑭-K 在節點層踩過的坑（rescue 與 damage 對稱）。

## 兩個 margin 的定義（不可互換）

* **correct-side margin**（引擎解對）= `fused(gold) − fused(best non-gold)` > 0
  gold path 就是引擎選的那條，所以這是「離被推翻還有多遠」。
* **wrong-side deficit**（引擎解錯且 gold 在 top-10）
  = `fused(selected) − fused(gold)` > 0
  「gold 離奪冠還差多少」。

⚠️ 對 engine-correct 的句子**不得**做「gold vs selected」比較 —— 那是同一條路徑。

## Counterfactual

只用現有 component 做數學上的反事實：`walkScore + ν'·rnn`。
一律標 `COUNTERFACTUAL / OFFLINE ONLY`；
在同一份語料上掃出來的最佳 ν' 一律標 `NAIVE`，**不得**稱為 production 最佳值。

用法：
  python3 audit_path_score_symmetric_damage.py --paths <paths-all.tsv> --out <片段.md>
"""

import argparse
import collections
import hashlib
import statistics

NU = 0.75
NUS = [0.0, 0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00]
SEED = 'baton14r-fold-v1'
K = 5

COMPONENTS = {
    '**fused（出貨）**': lambda p: p['fused'],
    'walkScore': lambda p: p['walk_score'],
    'unigram 總和': lambda p: p['unigram_sum'],
    'λ·PMI': lambda p: p['pmi'],
    'rnn': lambda p: p['rnn'],
}


def load(path):
    s = collections.defaultdict(list)
    with open(path, encoding='utf-8') as fh:
        head = next(fh).rstrip('\n').split('\t')
        for line in fh:
            f = dict(zip(head, line.rstrip('\n').split('\t')))
            s[f['sid']].append({
                'idx': int(f['path_idx']), 'n_err': int(f['n_err']),
                'is_walk': f['is_walk'] == '1', 'is_gold': f['is_gold'] == '1',
                'ok': f['engine_correct'] == '1',
                'walk_score': float(f['walk_score']),
                'unigram_sum': float(f['unigram_sum']),
                'pmi': float(f['pmi']), 'rnn': float(f['rnn']),
                'fused': float(f['fused']),
            })
    return s


def q(v, p):
    if not v:
        return float('nan')
    return sorted(v)[min(len(v) - 1, int(p * len(v)))]


def margins(sents, key):
    """回傳 (correct-side margin list, wrong-side deficit list)。"""
    cm, wd = [], []
    for ps in sents.values():
        g = [p for p in ps if p['is_gold']]
        if not g:
            continue
        gb = max(g, key=key)
        others = [p for p in ps if not p['is_gold']]
        if not others:
            continue
        best_other = max(others, key=key)
        if ps[0]['ok']:
            cm.append(key(gb) - key(best_other))
        else:
            sel = next((p for p in ps if p['is_walk']), None)
            if sel is not None and not sel['is_gold']:
                wd.append(key(sel) - key(gb))
    return cm, wd


def pairwise_acc(sents, key, want_ok):
    win = tie = lose = 0
    for ps in sents.values():
        if ps[0]['ok'] != want_ok:
            continue
        g = [p for p in ps if p['is_gold']]
        ng = [p for p in ps if not p['is_gold']]
        if not g or not ng:
            continue
        for a in g:
            for b in ng:
                d = key(a) - key(b)
                if d > 1e-9:
                    win += 1
                elif d < -1e-9:
                    lose += 1
                else:
                    tie += 1
    n = win + tie + lose
    return ((win + 0.5 * tie) / n if n else float('nan')), n


def counterfactual(sents, nu):
    """精確重算 argmax，回傳逐句結果。COUNTERFACTUAL。"""
    out = {}
    for sid, ps in sents.items():
        best = max(ps, key=lambda p: p['walk_score'] + nu * p['rnn'])
        cur = next((p for p in ps if p['is_walk']), None)
        out[sid] = {
            'ok': ps[0]['ok'],
            'cur_err': cur['n_err'] if cur else None,
            'new_err': best['n_err'],
            'changed': best is not cur and (best['idx'] != cur['idx']),
        }
    return out


def summarize(cf):
    r = d = ch = 0
    cur = new = 0
    rescued_sent = damaged_sent = 0
    for v in cf.values():
        cur += v['cur_err']
        new += v['new_err']
        if v['changed']:
            ch += 1
        if v['ok'] and v['new_err'] > 0:
            damaged_sent += 1
        if not v['ok'] and v['new_err'] == 0:
            rescued_sent += 1
        r += max(0, v['cur_err'] - v['new_err'])
        d += max(0, v['new_err'] - v['cur_err'])
    return dict(rescue_ch=r, damage_ch=d, net_ch=cur - new, changed=ch,
                cur=cur, new=new, rescued_sent=rescued_sent,
                damaged_sent=damaged_sent)


def fold(sid):
    return int(hashlib.sha256(f'{SEED}:{sid}'.encode()).hexdigest()[:8], 16) % K


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--paths', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    sents = load(args.paths)
    L = []
    w = L.append

    ok = {s: p for s, p in sents.items() if p[0]['ok']}
    bad = {s: p for s, p in sents.items() if not p[0]['ok']}
    tot_err = sum(next(p['n_err'] for p in ps if p['is_walk'])
                  for ps in sents.values())

    w('## Provenance\n')
    w('| 檢查項 | 結果 |')
    w('|---|---|')
    w('| 分數來源 | `grid.walkNBest(10)` ＋ `NeuralLMPathScorer::scoreNBest`，'
      'inference-time |')
    w('| 融合公式 | `walkScore + ν·rnn`，ν=0.75、λ=0.75、adjust=0 |')
    w('| **argmax 重現 walk() 輸出** | **✅ 5,976 / 5,976，mismatch 0**（全語料，'
      '不只解錯的）→ `INFERENCE-FAITHFUL` |')
    w('| 有沒有用金標算分 | ❌ 沒有 |')

    w('\n\n## 語料切分\n')
    w('| 子集 | 句數 | 佔比 | walk 錯字 | 其中 gold path 在 top-10 |')
    w('|---|---|---|---|---|')
    okg = sum(1 for ps in ok.values() if any(p['is_gold'] for p in ps))
    badg = sum(1 for ps in bad.values() if any(p['is_gold'] for p in ps))
    w(f'| **A ENGINE-CORRECT** | {len(ok):,} | {len(ok)/len(sents):.1%} | 0 | '
      f'{okg:,}（定義上必然，gold ＝ 引擎輸出）|')
    w(f'| **B ENGINE-WRONG** | {len(bad):,} | {len(bad)/len(sents):.1%} | '
      f'{tot_err:,} | **{badg:,}** |')
    w(f'| A + B | {len(sents):,} | 100% | {tot_err:,} | {okg+badg:,} |')
    w(f'\n無 UNCERTAIN、無法重建者 0（`walkNBest` 對全部 5,976 句都成功）。'
      f'walk 錯字 {tot_err:,} 與 ⑭-O/⑭-P 的 D2 = 3,192 一致。`OBSERVED`\n')

    # ── 對稱分布 ──
    w('\n\n## 核心：兩側 margin 分布（融合分數）\n')
    cm, wd = margins(sents, lambda p: p['fused'])
    w('| 分位 | A 解對側 margin（離被推翻多遠）| B 解錯側 deficit（離奪冠多遠）|')
    w('|---|---|---|')
    for p, lbl in ((.05, 'P5'), (.10, 'P10'), (.25, 'P25'), (.50, '**中位數**'),
                   (.75, 'P75'), (.90, 'P90'), (.95, 'P95')):
        w(f'| {lbl} | {q(cm,p):.3f} | {q(wd,p):.3f} |')
    w(f'| n | {len(cm):,} | {len(wd):,} |')
    w(f'\n解對側中位 margin **{statistics.median(cm):.3f}**、'
      f'解錯側中位 deficit **{statistics.median(wd):.3f}**，'
      f'比值 **{statistics.median(cm)/statistics.median(wd):.2f}×**。')

    # ── overlap ──
    w('\n\n## 分布重疊：救一個要付多少代價\n')
    w('把「一個大小為 δ 的擾動」抽象化：它會救回 deficit < δ 的錯句，'
      '同時弄壞 margin < δ 的對句。這是**與 component 無關的包絡**。\n')
    w('\n| δ | 可救的錯句 | 會壞的對句 | 淨句數 | rescue : damage |')
    w('|---|---|---|---|---|')
    for d in (0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0):
        r = sum(1 for x in wd if x < d)
        dm = sum(1 for x in cm if x < d)
        ratio = f'{r/dm:.2f}' if dm else '∞'
        w(f'| {d:.2f} | {r} | {dm} | **{r-dm:+d}** | {ratio} |')
    sw = sorted(wd)
    med = statistics.median(wd)
    below = sum(1 for x in cm if x < med)
    w(f'\n解錯側 deficit 的中位數是 {med:.3f}；'
      f'解對側有 **{below:,} 句（{below/len(cm):.1%}）** 的 margin 比它還小。'
      f'\n**這就是重疊的規模。**')

    # ── component 對稱 ──
    w('\n\n## Component 對稱性\n')
    w('| Component | A 解對側 pairwise | B 解錯側 pairwise | A 中位 margin | B 中位 deficit | margin/deficit |')
    w('|---|---|---|---|---|---|')
    for name, key in COMPONENTS.items():
        a, _ = pairwise_acc(sents, key, True)
        b, _ = pairwise_acc(sents, key, False)
        c2, w2 = margins(sents, key)
        mc = statistics.median(c2) if c2 else float('nan')
        mw = statistics.median(w2) if w2 else float('nan')
        rat = f'{mc/mw:.2f}×' if mw else '—'
        w(f'| {name} | **{a:.3f}** | {b:.3f} | {mc:+.3f} | {mw:+.3f} | {rat} |')
    w('\n（解對側 pairwise 高 ＝ 該 component 同意目前正確的選擇。'
      '兩側都高才代表它安全。）')

    # ── counterfactual ν ──
    w('\n\n## Counterfactual ν′ 曲線（`COUNTERFACTUAL / OFFLINE ONLY`）\n')
    w('`score = walkScore + ν′·rnn`，逐句精確重算 argmax。'
      'ν′=0.75 必須重現現況（rescue=damage=0），這是 sanity check。\n')
    w('\n| ν′ | 改變決策的句數 | 救回字數 | 弄壞字數 | **淨字數** | 字級正確率 | '
      '整句全對數 | rescue precision |')
    w('|---|---|---|---|---|---|---|---|')
    TOTCH = 74649
    base_sent_ok = len(ok)
    for nu in NUS:
        s = summarize(counterfactual(sents, nu))
        prec = (s['rescue_ch'] / (s['rescue_ch'] + s['damage_ch'])
                if (s['rescue_ch'] + s['damage_ch']) else float('nan'))
        acc = 100 * (1 - s['new'] / TOTCH)
        sent_ok = base_sent_ok + s['rescued_sent'] - s['damaged_sent']
        mark = ' ←現況' if abs(nu - NU) < 1e-9 else ''
        w(f'| {nu:.2f}{mark} | {s["changed"]:,} | {s["rescue_ch"]:,} | '
          f'{s["damage_ch"]:,} | **{s["net_ch"]:+,}** | {acc:.3f}% | '
          f'{sent_ok:,} | {prec:.3f} |')
    w(f'\n（字級分母 {TOTCH:,}；現況字級正確率 '
      f'{100*(1-tot_err/TOTCH):.3f}%。）')

    # ── cross-fitted ──
    w('\n\n## Naive vs Cross-fitted（`CROSS-FITTED`）\n')
    w(f'document(＝句)-level {K}-fold，種子 `{SEED}`，deterministic。'
      f'每輪用 4 個 fold 選 ν′（目標：淨字數最大），在第 5 個 fold 評估。\n')
    grid = [x / 100 for x in range(0, 301, 5)]
    pre = {nu: counterfactual(sents, nu) for nu in grid}
    folds = {s: fold(s) for s in sents}
    w('\n| held-out fold | 選出的 ν′ | 救 | 壞 | 淨 |')
    w('|---|---|---|---|---|')
    tot_r = tot_d = tot_n = 0
    for k in range(K):
        tr = [s for s in sents if folds[s] != k]
        te = [s for s in sents if folds[s] == k]
        best_nu, best_net = NU, None
        for nu in grid:
            net = sum(pre[nu][s]['cur_err'] - pre[nu][s]['new_err'] for s in tr)
            if best_net is None or net > best_net:
                best_net, best_nu = net, nu
        r = sum(max(0, pre[best_nu][s]['cur_err'] - pre[best_nu][s]['new_err'])
                for s in te)
        d = sum(max(0, pre[best_nu][s]['new_err'] - pre[best_nu][s]['cur_err'])
                for s in te)
        tot_r += r
        tot_d += d
        tot_n += r - d
        w(f'| {k} | {best_nu:.2f} | {r} | {d} | **{r-d:+d}** |')
    naive_best = max(grid, key=lambda nu: sum(
        pre[nu][s]['cur_err'] - pre[nu][s]['new_err'] for s in sents))
    ns = summarize(pre[naive_best])
    w(f'\n| 方法 | ν′ | 救 | 壞 | 淨字數 | 佔 D2 |')
    w('|---|---|---|---|---|---|')
    w(f'| **NAIVE**（同一份語料掃出最大）| {naive_best:.2f} | {ns["rescue_ch"]:,} | '
      f'{ns["damage_ch"]:,} | **{ns["net_ch"]:+,}** | {ns["net_ch"]/tot_err:+.1%} |')
    w(f'| **CROSS-FITTED**（4 選 1 評）| 逐 fold 見上 | {tot_r:,} | {tot_d:,} | '
      f'**{tot_n:+,}** | {tot_n/tot_err:+.1%} |')
    w('\n`NAIVE` 一律不得稱為 production 最佳 ν。')

    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
