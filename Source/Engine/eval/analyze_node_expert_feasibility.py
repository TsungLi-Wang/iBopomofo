#!/usr/bin/env python3
# Node Expert 可行性／上限分析（棒⑭-K）。**純分析：不訓練、不改 τ、不碰 production。**
#
# 回答五個問題：
#   Q1 避開 threshold selection bias 後，I2 實際可達的最佳 net（cross-fitted）
#   Q2 從既有 ROC 看的 cost-sensitive empirical upper envelope
#   Q3 節點層 theoretical ceiling，以及對整體錯誤池的貢獻
#   Q4 要多少人工核驗、標在哪些 cell，才真的降得下 CI
#   Q5 語料金標的標籤雜訊會不會壓低 measured AUC
#
# ## 事前寫死的規則（計算前就定，不因結果好看與否更動）
#
#   R1  Q1 的 τ 只能用 calibration folds 選，held-out fold 只評不選。
#       選擇目標＝calibration 上的加權 net 最大；**若最大值 ≤ 0 則選「不啟用」**
#       （τ=∞，override 0）。不得看 held-out 再回頭調。
#   R2  naive max（整份 dev 掃 τ 取最大）只當「樂觀上限／選擇偏誤示範」，
#       絕不當作效果估計。兩者一律分開報。
#   R3  AUC 不換算 net。net 一律由 ROC 上的 (TPR, FPR) 與 p_err 直接算。
#   R4  damage 只在對角線 cell 上估（棒⑭-J 查出的估計式缺陷）。
#   R5  凡樣本不足以支持結論者，一律寫 insufficient evidence，不外推。

import argparse
import collections
import json
import math
import os
import random
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calibrate_operating_point import (build_rows, curve, diagonal_cell,  # noqa
                                       score_all, strat)
from eval_model_dev import load_node_features, wilson  # noqa: E402

GROUP = ['作', '做', '坐', '座']
GSET = set(GROUP)


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


def boot_auc_ci(score, label, docs, n=800, seed=0):
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


def strat_net(det, cells_meta, p_err):
    """回傳這批列在 fire 已定的情況下的 (tpr, fpr, net)。"""
    tpr, _, _, _ = strat(det, cells_meta,
                         lambda r: r['fire'] and r['new'] == r['human'],
                         lambda r: r['engine'] != r['human'])
    fpr, _, _, _ = strat(det, cells_meta,
                         lambda r: r['fire'] and r['new'] != r['human'],
                         lambda r: r['engine'] == r['human'],
                         only_diagonal=True)
    return tpr, fpr, p_err * tpr - (1 - p_err) * fpr


def boot_net_ci(det, cells_meta, p_err, n=800, seed=0):
    """net 的 95% CI，**文件叢集** bootstrap —— 與本檔 AUC 的 CI 同一套。

    為什麼不用 `p_err·TPR_lo − (1−p_err)·FPR_hi`：那是把兩側的 Wilson 界
    同時取最壞角落，是**保守同時下界**，不是 net 的 95% 區間；它也把 n_eff
    當成普通二項 n，而分層估計各層 p_h 差很大時這並不成立
    （實測：作→作·單字 p_h=0.19 貢獻了 Var(net) 的一半）。
    兩個量都保留，但標清楚哪個是哪個。
    """
    rng = random.Random(seed)
    by = collections.defaultdict(list)
    for r in det:
        by[r['doc']].append(r)
    keys = list(by)
    out = []
    for _ in range(n):
        samp = []
        for _ in keys:
            samp += by[rng.choice(keys)]
        out.append(strat_net(samp, cells_meta, p_err)[2])
    out.sort()
    return out[int(0.025 * n)], out[int(0.975 * n)]


def net_at(det, cells_meta, tau, p_err):
    """R3：net 直接由 (TPR, FPR) 與 p_err 算，不經 AUC。"""
    for r in det:
        r['fire'] = r['changes'] and r['margin'] > tau
    tpr, ne_r, _, _ = strat(det, cells_meta,
                            lambda r: r['fire'] and r['new'] == r['human'],
                            lambda r: r['engine'] != r['human'])
    fpr, ne_d, _, _ = strat(det, cells_meta,
                            lambda r: r['fire'] and r['new'] != r['human'],
                            lambda r: r['engine'] == r['human'],
                            only_diagonal=True)
    lo_t, hi_t = wilson(tpr * ne_r, ne_r)
    lo_f, hi_f = wilson(fpr * ne_d, ne_d)
    net = p_err * tpr - (1 - p_err) * fpr
    lo = p_err * lo_t - (1 - p_err) * hi_f   # 保守同時角落，非 95% CI
    hi = p_err * hi_t - (1 - p_err) * lo_f
    fired = [r for r in det if r['fire']]
    rs = sum(1 for r in fired if r['engine'] != r['human'] and r['new'] == r['human'])
    dm = sum(1 for r in fired if r['engine'] == r['human'] and r['new'] != r['human'])
    return dict(tau=tau, tpr=tpr, fpr=fpr, net=net, lo=lo, hi=hi,
                override=len(fired), rescue=rs, damage=dm,
                precision=rs / len(fired) if fired else 0.0,
                ne_r=ne_r, ne_d=ne_d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--annotated', required=True)
    ap.add_argument('--meta', required=True)
    ap.add_argument('--folds', required=True)
    ap.add_argument('--r4-dir', required=True)
    ap.add_argument('--i2-dir', required=True)
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--nodes2', default='')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    L = open(args.annotated, encoding='utf-8').read().rstrip('\n').split('\n')
    h = L[0].split('\t')
    ann = [dict(zip(h, x.split('\t'))) for x in L[1:]]
    cells_meta = json.load(open(args.meta, encoding='utf-8'))['cells']
    assign = json.load(open(args.folds, encoding='utf-8'))['assign']
    feats = load_node_features([('train-src', args.nodes),
                                ('contexts', args.nodes2)])
    base = build_rows(ann, feats, assign)
    scored = {'R4': score_all(base, args.r4_dir),
              'I2': score_all(base, args.i2_dir)}
    taus = [i / 100 for i in range(0, 301)]

    o = []
    w = o.append
    w('# Node Expert 可行性／上限分析（棒⑭-K）\n')
    w('> **純分析。** 沒有訓練、沒有改 τ、沒有改 production、沒有跑正式 '
      'Natural／X、沒有新增人工核驗、沒有合成資料。\n')
    w('\n## 事前規則（計算前寫死於腳本）\n')
    w('* **R1** Q1 的 τ 只能用 calibration folds 選；held-out fold 只評不選。'
      '選擇目標＝calibration 加權 net 最大；**若最大 ≤ 0 則選「不啟用」**。')
    w('* **R2** naive max 只當樂觀上限／選擇偏誤示範，不當效果估計。')
    w('* **R3** AUC 不換算 net；net 一律由 ROC 的 (TPR, FPR) 與 p_err 直接算。')
    w('* **R4** damage 只在對角線 cell 上估（⑭-J 查出的估計式缺陷）。')
    w('* **R5** 樣本不足者一律寫 insufficient evidence，不外推。\n')

    # ── p_err provenance ──
    det_all = [r for r in scored['I2'] if r['det']]
    p_err, ne_pe, k_pe, n_pe = strat(det_all, cells_meta,
                                     lambda r: r['engine'] != r['human'],
                                     lambda r: True)
    w('\n## p_err 的來源與定義\n')
    w(f'* 定義：**加權**（IPW，含有限母體修正）後，作做坐座節點中'
      f'「引擎選擇 ≠ 人工金標」的比例。')
    w(f'* 分母：970 筆人工核驗中可判定的 **{n_pe}** 筆；'
      f'母體＝ model-dev 抽樣的 **6,253** 個節點。')
    w(f'* 值：**p_err = {100*p_err:.2f}%**（未加權 {k_pe}/{n_pe} = '
      f'{100*k_pe/n_pe:.1f}%，因 dev 刻意過抽錯誤格）。')
    w(f'* ⚠️ 這是 **audit 母體**上的值。自然驗證集上引擎在此組的正確率是 '
      f'85.4%（→ p_err 14.6%），兩者母體不同，不可互換。以下一律用 '
      f'{100*p_err:.2f}%，並在敏感度一節檢查 14.6% 的情形。\n')

    # ── Q2：ROC cost-sensitive upper envelope ──
    w('\n## Q2：ROC cost-sensitive empirical upper envelope\n')
    w('net(τ) = p_err × TPR(τ) − (1 − p_err) × FPR(τ)，逐 τ 直接算（**未經 AUC**）。\n')
    w('\n| 模型 | 最佳 τ | TPR | FPR | override | **envelope net** | 95% CI（文件 bootstrap） |')
    w('|---|---|---|---|---|---|---|')
    env = {}
    for name in ('R4', 'I2'):
        det = [r for r in scored[name] if r['det']]
        pts = [net_at(det, cells_meta, t, p_err) for t in taus]
        best = max(pts, key=lambda x: x['net'])
        for r in det:
            r['fire'] = r['changes'] and r['margin'] > best['tau']
        best['blo'], best['bhi'] = boot_net_ci(det, cells_meta, p_err)
        env[name] = (best, pts)
        w(f'| {name} | {best["tau"]:.2f} | {100*best["tpr"]:.2f}% | '
          f'{100*best["fpr"]:.2f}% | {best["override"]} | '
          f'**{100*best["net"]:+.2f}%** | [{100*best["blo"]:+.2f}, '
          f'{100*best["bhi"]:+.2f}] |')
    w('\n⚠️ 這是 **naive max**（在同一份 dev 上掃 τ 取最大），依 R2 '
      '只能當樂觀上限與選擇偏誤的示範，**不是效果估計**。')

    # ── Q1：cross-fitted ──
    w('\n## Q1：Cross-fitted 最佳 net（避開 threshold selection bias）\n')
    w('每一輪：4 個 fold 只用來選 τ，第 5 個 fold 只用來評，完整輪替。'
      '選 τ 的目標是 calibration 上的加權 net 最大；若最大 ≤ 0 則選「不啟用」。\n')
    for name in ('R4', 'I2'):
        rows = scored[name]
        det = [r for r in rows if r['det']]
        w(f'\n### {name}\n')
        w('| held-out fold | 選出的 τ | override | rescue | damage | precision |')
        w('|---|---|---|---|---|---|')
        oof = []
        for fi in range(5):
            cal = [r for r in det if r['fold'] != fi]
            hel = [r for r in det if r['fold'] == fi]
            if not cal or not hel:
                continue
            pts = [net_at(cal, cells_meta, t, p_err) for t in taus]
            best = max(pts, key=lambda x: x['net'])
            tau = best['tau'] if best['net'] > 0 else float('inf')
            for r in hel:
                r['fire'] = r['changes'] and r['margin'] > tau
                r['sel_tau'] = tau
            fired = [r for r in hel if r['fire']]
            rs = sum(1 for r in fired
                     if r['engine'] != r['human'] and r['new'] == r['human'])
            dm = sum(1 for r in fired
                     if r['engine'] == r['human'] and r['new'] != r['human'])
            oof += hel
            w(f'| {fi} | ' + ('不啟用' if tau == float('inf')
                              else f'{tau:.2f}')
              + f' | {len(fired)} | {rs} | {dm} | '
              + (f'{100*rs/len(fired):.1f}%' if fired else '—') + ' |')
        # 合併 OOF（fire 已由各自 fold 的 τ 決定）
        tpr, ne_r, _, _ = strat(oof, cells_meta,
                                lambda r: r['fire'] and r['new'] == r['human'],
                                lambda r: r['engine'] != r['human'])
        fpr, ne_d, _, _ = strat(oof, cells_meta,
                                lambda r: r['fire'] and r['new'] != r['human'],
                                lambda r: r['engine'] == r['human'],
                                only_diagonal=True)
        lo_t, hi_t = wilson(tpr * ne_r, ne_r)
        lo_f, hi_f = wilson(fpr * ne_d, ne_d)
        net = p_err * tpr - (1 - p_err) * fpr
        corner = p_err * lo_t - (1 - p_err) * hi_f   # 保守同時下界，非 CI
        lo, hi = boot_net_ci(oof, cells_meta, p_err)
        fired = [r for r in oof if r['fire']]
        rs = sum(1 for r in fired
                 if r['engine'] != r['human'] and r['new'] == r['human'])
        dm = sum(1 for r in fired
                 if r['engine'] == r['human'] and r['new'] != r['human'])
        w(f'\n**{name} cross-fitted OOF**：override {len(fired)}、rescue {rs}、'
          f'damage {dm}、precision '
          + (f'{100*rs/len(fired):.1f}%' if fired else '—')
          + f'；TPR {100*tpr:.2f}%、FPR {100*fpr:.2f}%；'
          f'**加權 net {100*net:+.2f}%**，'
          f'95% CI（文件 bootstrap）**[{100*lo:+.2f}, {100*hi:+.2f}]**；'
          f'保守同時下界 {100*corner:+.2f}%'
          f'（n_eff：rescue {ne_r:.0f}、damage {ne_d:.0f}）')
        env[name + '_cf'] = net

    # ── Q3-A ──
    w('\n## Q3-A：節點層 theoretical ceiling\n')
    b_r4, _ = env['R4']
    b_i2, _ = env['I2']
    w('| 量 | 值 |')
    w('|---|---|')
    w(f'| 作做坐座 node 母體（audit 抽樣母體） | 6,253 |')
    w(f'| 加權 engine error rate（p_err） | **{100*p_err:.2f}%** |')
    w(f'| **理論最大 net**（全救回、零誤傷） | **+{100*p_err:.2f}%** |')
    w(f'| I2 naive best net（envelope） | {100*b_i2["net"]:+.2f}% |')
    w(f'| **I2 cross-fitted net** | **{100*env["I2_cf"]:+.2f}%** |')
    w(f'| I2 @ τ=0.5 | {100*net_at([r for r in scored["I2"] if r["det"]], cells_meta, 0.5, p_err)["net"]:+.2f}% |')
    w(f'| R4 cross-fitted net | {100*env["R4_cf"]:+.2f}% |')
    cap_naive = b_i2['net'] / p_err
    cap_cf = env['I2_cf'] / p_err
    w(f'\n**捕獲率**：naive envelope 只有理論上限的 **{100*cap_naive:.1f}%**；'
      f'cross-fitted 為 **{100*cap_cf:.1f}%**。')

    # ── Q5 ──
    w('\n## Q5：語料金標的標籤雜訊是否壓低 measured AUC\n')
    sub = [r for r in scored['I2'] if r['det'] and r['engine'] == '作'
           and r['span'] == 1]
    sc = [r['margin'] for r in sub]
    dd = [r['doc'] for r in sub]
    lab_c = [1 if r['gold'][r['ti']] != '作' else 0 for r in sub]
    lab_h = [1 if r['human'] != '作' else 0 for r in sub]
    disagree = sum(1 for a, b in zip(lab_c, lab_h) if a != b)
    a_c = roc_auc(sc, lab_c)
    a_h = roc_auc(sc, lab_h)
    lo_c, hi_c = boot_auc_ci(sc, lab_c, dd)
    lo_h, hi_h = boot_auc_ci(sc, lab_h, dd)
    w(f'同一批 **{len(sub)}** 筆（engine=作 ∧ 單字 ∧ 可判定）、同一組 I2 分數、'
      f'同一切分，**只換標籤**。兩種標籤不一致的有 **{disagree}** 筆。\n')
    w('\n| 標籤 | ROC-AUC | 95% CI（文件 bootstrap） |')
    w('|---|---|---|')
    w(f'| 語料金標 | {a_c:.3f} | [{lo_c:.3f}, {hi_c:.3f}] |')
    w(f'| **人工金標** | **{a_h:.3f}** | [{lo_h:.3f}, {hi_h:.3f}] |')
    w(f'| 差 | {a_h - a_c:+.3f} | — |')

    json.dump({'p_err': p_err, 'env_naive': {k: v[0]['net'] for k, v in env.items()
                                             if not k.endswith('_cf')},
               'cross_fitted': {k: v for k, v in env.items() if k.endswith('_cf')},
               'auc_corpus': a_c, 'auc_human': a_h,
               'auc_ci_corpus': [lo_c, hi_c], 'auc_ci_human': [lo_h, hi_h],
               'label_disagree': disagree, 'n_sub': len(sub)},
              open(os.path.splitext(args.out)[0] + '.json', 'w'),
              ensure_ascii=False, default=float)
    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(o) + '\n')
    print('\n'.join(o))


if __name__ == '__main__':
    main()
