#!/usr/bin/env python3
# 用 document-level k-fold 的 5 顆模型，評人工核驗的 970 筆（棒⑭-F）。
#
# ## 為什麼這樣評是乾淨的
#
# 每一筆核驗樣本只落在**一個** fold 的 dev 裡，而那個 fold 的模型訓練時
# 整份文件都被排除。所以把 5 個 fold 的預測接起來，就得到
# **970 筆全量、零洩漏**的評估 —— 這正是固定切法做不到的
# （固定切法要嘛洩漏 32.7%，要嘛把稀有方向的訓練資料全吃光）。
#
# 統計沿用棒⑭-D PART B 的分層估計（含有限母體修正），公式寫在 eval_model_dev.py。
#
# 用法：
#   python3 eval_kfold_dev.py --annotated <...tsv> --meta <model-dev-meta.json> \
#       --folds <folds.json> --ckpt-dir <目錄> --tau 0.5 \
#       --nodes <nodes.tsv> --nodes2 <ctx-nodes.tsv> --out <報告.md>

import argparse
import collections
import json
import math
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_model_dev import load_node_features, wilson  # noqa: E402
from train_node_expert import MAX_CANDS, NodeExpert, encode  # noqa: E402

FIRE = 'ㄗㄨㄛˋ'
GROUP = ['作', '做', '坐', '座']
GSET = set(GROUP)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--annotated', required=True)
    ap.add_argument('--meta', required=True)
    ap.add_argument('--folds', required=True)
    ap.add_argument('--ckpt-dir', required=True)
    ap.add_argument('--tau', type=float, default=0.5)
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--nodes2', default='')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    L = open(args.annotated, encoding='utf-8').read().rstrip('\n').split('\n')
    h = L[0].split('\t')
    ann = [dict(zip(h, x.split('\t'))) for x in L[1:]]
    meta = json.load(open(args.meta, encoding='utf-8'))
    cells_meta = meta['cells']
    fj = json.load(open(args.folds, encoding='utf-8'))
    assign, K = fj['assign'], fj['k']
    feats = load_node_features([('train-src', args.nodes),
                                ('contexts', args.nodes2)])

    rows, missing, nofold = [], 0, 0
    for a in ann:
        f = feats.get((a['source'], a['node_id']))
        if f is None:
            missing += 1
            continue
        fold = assign.get(a['doc_id'])
        if fold is None:
            # contexts 來源的文件不在訓練語料的 fold 表裡 → 它從未進過任何
            # fold 的訓練集，所以每個 fold 的模型看它都是乾淨的。指派給 fold 0。
            fold = 0
            nofold += 1
        syls = f['reading'].split('-')
        ti = syls.index(FIRE)
        cands = []
        for part in f['cands'].split('|'):
            q = part.split(':')
            if len(q) == 5:
                cands.append((q[0], float(q[1]), float(q[2]), float(q[3]),
                              q[4] == '1'))
        cands.sort(key=lambda x: -x[1])
        cands = cands[:MAX_CANDS]
        if len(cands) < 2:
            missing += 1
            continue
        rows.append({
            'reading': f['reading'], 'chosen': f['chosen'], 'gold': f['gold'],
            'cands': cands, 'left': f['left_chars'], 'right': f['right_chars'],
            'right_empty': f['right_empty'] == '1',
            'gi': next((k for k, x in enumerate(cands) if x[0] == f['gold']), -1),
            'ti': ti, 'span': int(f['span']), 'fold': fold,
            'engine': f['chosen'][ti], 'corpus': f['gold'][ti],
            'human': a['human_gold'], 'conf': a['human_confidence'],
            'cell': a['cell'], 'sample_id': a['sample_id'],
        })

    # 逐 fold 用該 fold 的模型打分
    for fi in range(K):
        idx = [i for i, r in enumerate(rows) if r['fold'] == fi]
        if not idx:
            continue
        ck = torch.load(os.path.join(args.ckpt_dir, f'fold{fi}',
                                     'node-expert.pt'), map_location='cpu')
        model = NodeExpert(**ck['cfg'])
        model.load_state_dict(ck['model'])
        model.eval()
        ci = {c: i for i, c in enumerate(ck['itos'])}
        si = {s: i for i, s in enumerate(ck['stos'])}
        sub = [rows[i] for i in idx]
        enc = encode(sub, ci, si)
        with torch.no_grad():
            logits = model(
                torch.from_numpy(enc['left'].astype(np.int64)),
                torch.from_numpy(enc['right'].astype(np.int64)),
                torch.from_numpy(enc['syl'].astype(np.int64)),
                torch.from_numpy(enc['rempty']),
                torch.from_numpy(enc['cchars'].astype(np.int64)),
                torch.from_numpy(enc['cfeat']),
                torch.from_numpy(enc['cmask']))
            lsm = torch.log_softmax(
                logits.masked_fill(~torch.from_numpy(enc['cmask']), -1e4),
                dim=-1).numpy()
        for j, i in enumerate(idx):
            r = rows[i]
            chi = next((k for k, c in enumerate(r['cands'])
                        if c[0] == r['chosen']), -1)
            best = int(lsm[j].argmax())
            mar = lsm[j, best] - lsm[j, max(chi, 0)]
            v = r['cands'][best][0]
            syls = r['reading'].split('-')
            newc = v[r['ti']] if len(v) == len(syls) else None
            r['fire'] = bool(chi >= 0 and best != chi and mar > args.tau)
            r['margin'] = float(mar)
            r['new'] = newc
            r['final'] = newc if r['fire'] else r['engine']
            r['det'] = r['conf'] in ('high', 'medium') and r['human'] in GSET

    det = [r for r in rows if r['det']]

    def strat(num, den, pool):
        per = {}
        for c, m in cells_meta.items():
            sub = [r for r in pool if r['cell'] == c and den(r)]
            if not sub:
                continue
            per[c] = (sum(1 for r in sub if num(r)), len(sub), m['population'])
        N = sum(v[2] for v in per.values())
        if not N:
            return 0.0, 0.0, 0, 0
        p = sum((v[2] / N) * (v[0] / v[1]) for v in per.values())
        inv = 0.0
        for k, nh, Nh in per.values():
            w = Nh / N
            f = min(nh / Nh, 1.0)
            if nh and f < 1.0:
                inv += w * w * (1 - f) / nh
        return (p, (1 / inv) if inv else float('inf'),
                sum(v[0] for v in per.values()), sum(v[1] for v in per.values()))

    out = []
    w = out.append
    w('# Document-level 5-fold · R4 baseline（棒⑭-F）\n')
    w(f'seed = `{fj["seed"]}`　k = {K}　τ = {args.tau}　**只換切法，recipe 未動**\n')
    w(f'\n核驗樣本 {len(rows)}／{len(ann)}（接不上 {missing}；'
      f'contexts 來源不在 fold 表、指派 fold 0 的有 {nofold}）\n')
    w(f'可判定 {len(det)}、uncertain {len(rows) - len(det)}\n')

    # 每 fold
    w('\n## 每 fold 指標（該 fold 模型只評自己 dev 側的核驗樣本）\n')
    w('| fold | 核驗樣本 | 可判定 | 引擎正確率 | 專家正確率 | override | rescue | damage | net |')
    w('|---|---|---|---|---|---|---|---|---|')
    for fi in range(K):
        d = [r for r in det if r['fold'] == fi]
        if not d:
            continue
        e = sum(1 for r in d if r['engine'] == r['human'])
        fn = sum(1 for r in d if r['final'] == r['human'])
        fr = [r for r in d if r['fire']]
        rs = sum(1 for r in fr if r['engine'] != r['human'] and r['new'] == r['human'])
        dm = sum(1 for r in fr if r['engine'] == r['human'] and r['new'] != r['human'])
        w(f'| {fi} | {sum(1 for r in rows if r["fold"] == fi)} | {len(d)} | '
          f'{100 * e / len(d):.1f}% | {100 * fn / len(d):.1f}% | {len(fr)} | '
          f'{rs} | {dm} | {rs - dm:+d} |')

    # 合併
    fr = [r for r in det if r['fire']]
    rs = [r for r in fr if r['engine'] != r['human'] and r['new'] == r['human']]
    dm = [r for r in fr if r['engine'] == r['human'] and r['new'] != r['human']]
    pe, ne_e, _, _ = strat(lambda r: r['engine'] == r['human'], lambda r: True, det)
    pf, ne_f, _, _ = strat(lambda r: r['final'] == r['human'], lambda r: True, det)
    pr, ne_r, kr, nr = strat(lambda r: r['fire'] and r['new'] == r['human'],
                             lambda r: r['engine'] != r['human'], det)
    pd_, ne_d, kd, nd = strat(lambda r: r['fire'] and r['new'] != r['human'],
                              lambda r: r['engine'] == r['human'], det)
    p_err, _, _, _ = strat(lambda r: r['engine'] != r['human'], lambda r: True, det)
    lo_r, hi_r = wilson(pr * ne_r, ne_r)
    lo_d, hi_d = wilson(pd_ * ne_d, ne_d)

    w('\n## 合併（5 folds 接起來＝全量 970，零洩漏）\n')
    w('| 量 | 未加權 | **加權（IPW）** | 95% CI | n_eff |')
    w('|---|---|---|---|---|')
    w(f'| 引擎正確率 | {sum(1 for r in det if r["engine"] == r["human"])}/{len(det)} '
      f'| **{100 * pe:.2f}%** | — | {ne_e:.0f} |')
    w(f'| 專家正確率 | {sum(1 for r in det if r["final"] == r["human"])}/{len(det)} '
      f'| **{100 * pf:.2f}%** | — | {ne_f:.0f} |')
    w(f'| rescue rate | {kr}/{nr} = {100 * kr / max(nr, 1):.1f}% | **{100 * pr:.2f}%** '
      f'| [{100 * lo_r:.2f}, {100 * hi_r:.2f}] | {ne_r:.0f} |')
    dtxt = (f'observed 0，**上界 {100 * hi_d:.2f}%**' if kd == 0
            else f'**{100 * pd_:.2f}%**　[{100 * lo_d:.2f}, {100 * hi_d:.2f}]')
    w(f'| damage rate | {kd}/{nd} = {100 * kd / max(nd, 1):.2f}% | {dtxt} | — | {ne_d:.0f} |')
    net = p_err * pr - (1 - p_err) * pd_
    w(f'| **加權 net** | — | **{100 * net:+.2f}%** | '
      f'下界 **{100 * (p_err * lo_r - (1 - p_err) * hi_d):+.2f}%** | — |')
    w(f'\noverride {len(fr)}／{len(det)}（{100 * len(fr) / len(det):.1f}%）、'
      f'rescue {len(rs)}、damage {len(dm)}、'
      f'precision {100 * len(rs) / max(len(fr), 1):.1f}%（未加權）')

    # failure-mode matrix
    w('\n## Failure-mode matrix（合併）\n')
    w('| 方向 | dev n | override | rescue | damage | abstain | damage/rescue rate 95% CI |')
    w('|---|---|---|---|---|---|---|')
    for e in GROUP:
        for g in GROUP:
            sub = [r for r in det if r['engine'] == e and r['human'] == g]
            if not sub:
                continue
            f_ = [r for r in sub if r['fire']]
            r_ = sum(1 for r in f_ if r['new'] == g)
            d_ = sum(1 for r in f_ if e == g and r['new'] != g)
            if e == g:
                lo, hi = wilson(d_, len(sub))
                ci = (f'damage 0，上界 {100 * hi:.1f}%' if d_ == 0
                      else f'damage {100 * d_ / len(sub):.1f}% [{100 * lo:.1f}, {100 * hi:.1f}]')
            else:
                lo, hi = wilson(r_, len(sub))
                ci = f'rescue {100 * r_ / len(sub):.1f}% [{100 * lo:.1f}, {100 * hi:.1f}]'
            w(f'| {e}→{g} | {len(sub)} | {len(f_)} | {r_} | {d_} | '
              f'{len(sub) - len(f_)} | {ci} |')

    # 坐→坐 逐 fold
    w('\n## `坐→坐` 逐 fold（本棒的核心問題）\n')
    w('| fold | dev n | override | damage | damage rate | 95% CI |')
    w('|---|---|---|---|---|---|')
    for fi in range(K):
        sub = [r for r in det if r['fold'] == fi and r['engine'] == '坐'
               and r['human'] == '坐']
        if not sub:
            continue
        f_ = [r for r in sub if r['fire']]
        d_ = sum(1 for r in f_ if r['new'] != '坐')
        lo, hi = wilson(d_, len(sub))
        w(f'| {fi} | {len(sub)} | {len(f_)} | {d_} | {100 * d_ / len(sub):.1f}% | '
          f'[{100 * lo:.1f}, {100 * hi:.1f}] |')
    allz = [r for r in det if r['engine'] == '坐' and r['human'] == '坐']
    dz = sum(1 for r in allz if r['fire'] and r['new'] != '坐')
    lo, hi = wilson(dz, len(allz))
    w(f'| **合併** | **{len(allz)}** | '
      f'{sum(1 for r in allz if r["fire"])} | **{dz}** | '
      f'**{100 * dz / len(allz):.1f}%** | [{100 * lo:.1f}, {100 * hi:.1f}] |')

    text = '\n'.join(out) + '\n'
    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write(text)
    print(text)


if __name__ == '__main__':
    main()
