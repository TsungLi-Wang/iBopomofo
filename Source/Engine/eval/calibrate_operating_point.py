#!/usr/bin/env python3
# I2 的 operating-point 校準（棒⑭-J）。**不重訓、不改表徵、不改架構。**
# 唯一可動的是推論門檻 τ。
#
# ## 事前規則（在看到任何曲線之前寫死；程式照著跑，不是事後挑）
#
# 通過條件（四層全部要滿足）：
#   L1  加權 net 的 95% CI 下界 > 0
#   L2  作→作·單字 damage rate ≤ 10%，且 Wilson 95% 上界 ≤ 20%
#       （R4 @ τ=0.5 是 15.3%，被本專案判定為 catastrophic，所以要求優於它）
#   L3  作→做 rescue 次數 ≥ R4 @ τ=0.5 的 80%（R4 = 23 → 門檻 19）
#       （棒⑭-G 的 Gate B 就是死在保留率 30%／22%）
#   L4  作→座 rescue 次數 ≥ R4 @ τ=0.5 的 80%（R4 = 17 → 門檻 14）
#
# 若多個 τ 同時通過，**不准挑 net 最大的那個**。選法（保守優先）：
#   S1  取 override precision 最高者
#   S2  平手時取 damage rate 較低者
#   S3  再平手時取 **較大的 τ**（更保守）
#
# ## 統計
# 沿用棒⑭-D PART B 的分層估計（含有限母體修正）與 n_eff，
# 公式見 eval_model_dev.py，**不重新發明**。

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

# ── 事前門檻（寫死）──
L2_DAMAGE_MAX = 0.10
L2_UPPER_MAX = 0.20
L3_MIN_RESCUE = 19          # R4@0.5 的 作→做 rescue 23 × 0.8
L4_MIN_RESCUE = 14          # R4@0.5 的 作→座 rescue 17 × 0.8


def build_rows(ann, feats, assign):
    rows = []
    for a in ann:
        f = feats.get((a['source'], a['node_id']))
        if f is None:
            continue
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
            continue
        rows.append({
            'reading': f['reading'], 'chosen': f['chosen'], 'gold': f['gold'],
            'cands': cands, 'left': f['left_chars'], 'right': f['right_chars'],
            'right_empty': f['right_empty'] == '1',
            'gi': next((k for k, x in enumerate(cands) if x[0] == f['gold']), -1),
            'ti': ti, 'span': int(f['span']), 'cell': a['cell'],
            'engine': f['chosen'][ti], 'human': a['human_gold'],
            'fold': assign.get(a['doc_id'], 0), 'doc': a['doc_id'],
            'det': a['human_confidence'] in ('high', 'medium')
                   and a['human_gold'] in GSET,
        })
    return rows


def score_all(rows, ckdir):
    """逐 fold 用該 fold 的模型打分；每 fold assert 文件不重疊。"""
    out = [dict(r) for r in rows]
    for fi in range(5):
        idx = [i for i, r in enumerate(out) if r['fold'] == fi]
        if not idx:
            continue
        tr_docs = {r['doc'] for r in out if r['fold'] != fi}
        te_docs = {out[i]['doc'] for i in idx}
        assert not (tr_docs & te_docs), f'fold {fi} 文件重疊'
        ck = torch.load(os.path.join(ckdir, f'fold{fi}', 'node-expert.pt'),
                        map_location='cpu')
        m = NodeExpert(**ck['cfg'])
        m.load_state_dict(ck['model'])
        m.eval()
        ci = {c: i for i, c in enumerate(ck['itos'])}
        si = {s: i for i, s in enumerate(ck['stos'])}
        sub = [out[i] for i in idx]
        enc = encode(sub, ci, si)
        with torch.no_grad():
            lg = m(torch.from_numpy(enc['left'].astype(np.int64)),
                   torch.from_numpy(enc['right'].astype(np.int64)),
                   torch.from_numpy(enc['syl'].astype(np.int64)),
                   torch.from_numpy(enc['rempty']),
                   torch.from_numpy(enc['cchars'].astype(np.int64)),
                   torch.from_numpy(enc['cfeat']),
                   torch.from_numpy(enc['cmask']))
            lsm = torch.log_softmax(
                lg.masked_fill(~torch.from_numpy(enc['cmask']), -1e4),
                dim=-1).numpy()
        for j, i in enumerate(idx):
            r = out[i]
            chi = next((k for k, c in enumerate(r['cands'])
                        if c[0] == r['chosen']), -1)
            best = int(lsm[j].argmax())
            r['margin'] = float(lsm[j, best] - lsm[j, max(chi, 0)])
            v = r['cands'][best][0]
            sy = r['reading'].split('-')
            r['new'] = v[r['ti']] if len(v) == len(sy) else None
            r['changes'] = bool(chi >= 0 and best != chi)
    return out


def diagonal_cell(c):
    """cell 名形如 `作→作·單字`：引擎與語料金標相同才是對角線。"""
    head = c.split('·')[0]
    a, b = head.split('→')
    return a == b


def strat(rows, cells_meta, num, den, only_diagonal=False):
    """分層估計。

    `only_diagonal=True` 用於 **damage**：damage 的定義是「引擎本來就對卻被改壞」，
    它的母體就是對角線那些格。若不限制，非對角格裡「語料金標錯、人工判定與引擎
    相同」的極少數列（往往只有 1–3 列）會形成幾乎空的分層，
    IPW 會把單一事件放大成整體估計的一半以上 —— 那是估計式的假象，不是真傷害。
    （棒⑭-J 實測：I2 的加權 damage 3.91% 裡有 2.09% 來自一個 **2 列** 的格子。）
    """
    per = {}
    for c, m in cells_meta.items():
        if only_diagonal and not diagonal_cell(c):
            continue
        sub = [r for r in rows if r['cell'] == c and den(r)]
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


def curve(rows, cells_meta, taus):
    det = [r for r in rows if r['det']]
    out = []
    for t in taus:
        for r in det:
            r['fire'] = r['changes'] and r['margin'] > t
        fr = [r for r in det if r['fire']]
        rs = [r for r in fr if r['engine'] != r['human'] and r['new'] == r['human']]
        dm = [r for r in fr if r['engine'] == r['human'] and r['new'] != r['human']]
        wa = [r for r in fr if r not in rs and r not in dm]
        pr, ne_r, _, _ = strat(det, cells_meta,
                               lambda r: r['fire'] and r['new'] == r['human'],
                               lambda r: r['engine'] != r['human'])
        pd_, ne_d, _, _ = strat(det, cells_meta,
                                lambda r: r['fire'] and r['new'] != r['human'],
                                lambda r: r['engine'] == r['human'],
                                only_diagonal=True)
        pe, _, _, _ = strat(det, cells_meta,
                            lambda r: r['engine'] != r['human'], lambda r: True)
        lo_r, hi_r = wilson(pr * ne_r, ne_r)
        lo_d, hi_d = wilson(pd_ * ne_d, ne_d)
        net = pe * pr - (1 - pe) * pd_
        net_lo = pe * lo_r - (1 - pe) * hi_d
        cell = {}
        for g in ('作', '做', '座'):
            sub = [r for r in det if r['engine'] == '作' and r['human'] == g
                   and r['span'] == 1]
            f2 = [r for r in sub if r['fire']]
            r2 = sum(1 for r in f2 if r['new'] == r['human'])
            d2 = sum(1 for r in f2 if r['engine'] == r['human']
                     and r['new'] != r['human'])
            lo2, hi2 = wilson(d2, len(sub)) if sub else (0, 1)
            cell[g] = {'n': len(sub), 'override': len(f2), 'rescue': r2,
                       'damage': d2,
                       'damage_rate': d2 / len(sub) if sub else 0.0,
                       'damage_hi': hi2,
                       'precision': r2 / len(f2) if f2 else 0.0}
        out.append({
            'tau': round(t, 4), 'override': len(fr),
            'abstain': len(det) - len(fr),
            'rescue': len(rs), 'damage': len(dm), 'waste': len(wa),
            'precision': len(rs) / len(fr) if fr else 0.0,
            'u_rescue_rate': len(rs) / max(sum(1 for r in det
                                               if r['engine'] != r['human']), 1),
            'u_damage_rate': len(dm) / max(sum(1 for r in det
                                               if r['engine'] == r['human']), 1),
            'w_rescue': pr, 'w_rescue_ci': (lo_r, hi_r),
            'w_damage': pd_, 'w_damage_ci': (lo_d, hi_d),
            'w_net': net, 'w_net_lo': net_lo,
            'n_eff_r': ne_r, 'n_eff_d': ne_d, 'cells': cell,
            # 全部方向的 作→做／作→座 rescue（不限單字），供 L3/L4 用
            'rescue_zuo_zuo4': sum(1 for r in rs if r['engine'] == '作'
                                   and r['human'] == '做'),
            'rescue_zuo_zuo5': sum(1 for r in rs if r['engine'] == '作'
                                   and r['human'] == '座'),
        })
    return out


def gate(row):
    c = row['cells']['作']
    reasons = []
    if not (row['w_net_lo'] > 0):
        reasons.append('L1 net 下界 ≤ 0')
    if not (c['damage_rate'] <= L2_DAMAGE_MAX and c['damage_hi'] <= L2_UPPER_MAX):
        reasons.append('L2 作→作·單 damage 超標')
    if not (row['rescue_zuo_zuo4'] >= L3_MIN_RESCUE):
        reasons.append('L3 作→做 rescue 不足')
    if not (row['rescue_zuo_zuo5'] >= L4_MIN_RESCUE):
        reasons.append('L4 作→座 rescue 不足')
    return (not reasons), reasons


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

    taus = [i / 100 for i in range(0, 301)]
    res = {}
    for name, d in (('R4', args.r4_dir), ('I2', args.i2_dir)):
        res[name] = curve(score_all(base, d), cells_meta, taus)

    o = []
    w = o.append
    w('# I2 operating-point 校準（棒⑭-J）\n')
    w('> 不重訓、不改表徵／架構／訓練資料／loss；**唯一可動的是 τ**。')
    w('> 沒有跑正式 Natural／X。τ 由 5-fold audited dev 選出，')
    w('> 因此只能稱為 **development-selected threshold**。\n')
    w('\n## 事前規則（在看到曲線之前寫死於腳本）\n')
    w(f'* **L1** 加權 net 95% CI 下界 > 0')
    w(f'* **L2** 作→作·單字 damage ≤ {L2_DAMAGE_MAX:.0%} 且 Wilson 上界 ≤ '
      f'{L2_UPPER_MAX:.0%}（R4@0.5 是 15.3%）')
    w(f'* **L3** 作→做 rescue ≥ **{L3_MIN_RESCUE}**（R4@0.5 的 23 × 80%）')
    w(f'* **L4** 作→座 rescue ≥ **{L4_MIN_RESCUE}**（R4@0.5 的 17 × 80%）')
    w('* 多個 τ 通過時：**S1** 取 precision 最高 → **S2** damage rate 較低 '
      '→ **S3** τ 較大（保守）。**不准挑 net 最大的。**')
    w(f'\nτ 掃描：0.00–3.00，步長 0.01（涵蓋分數全域；margin 實際最大約 2.4）。\n')

    for name in ('R4', 'I2'):
        w(f'\n## {name} operating curve（節錄；完整表在 JSON）\n')
        w('| τ | override | abstain | rescue | damage | 多餘 | precision | '
          '未加權 rescue/damage | **加權 net** | net 95% 下界 |')
        w('|---|---|---|---|---|---|---|---|---|---|')
        for t in (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            r = next(x for x in res[name] if abs(x['tau'] - t) < 1e-9)
            w(f'| {t:.2f} | {r["override"]} | {r["abstain"]} | {r["rescue"]} | '
              f'{r["damage"]} | {r["waste"]} | {100*r["precision"]:.1f}% | '
              f'{100*r["u_rescue_rate"]:.1f}%／{100*r["u_damage_rate"]:.1f}% | '
              f'**{100*r["w_net"]:+.2f}%** | {100*r["w_net_lo"]:+.2f}% |')

    w('\n## Failure-mode curve（作·單字，I2）\n')
    w('| τ | 作→作 n/override/damage（rate, 上界） | 作→做 rescue | 作→座 rescue |')
    w('|---|---|---|---|')
    for t in (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
        r = next(x for x in res['I2'] if abs(x['tau'] - t) < 1e-9)
        c = r['cells']['作']
        w(f'| {t:.2f} | {c["n"]}／{c["override"]}／{c["damage"]}'
          f'（{100*c["damage_rate"]:.1f}%, 上界 {100*c["damage_hi"]:.1f}%） | '
          f'{r["rescue_zuo_zuo4"]} | {r["rescue_zuo_zuo5"]} |')

    w('\n## 相同出手量的比較（PART 9）\n')
    w('| override 目標 | R4 τ | R4 net | R4 precision | I2 τ | I2 net | I2 precision |')
    w('|---|---|---|---|---|---|---|')
    for target in (40, 80, 120, 160, 200):
        def nearest(name):
            return min(res[name], key=lambda r: abs(r['override'] - target))
        a, b = nearest('R4'), nearest('I2')
        w(f'| ~{target} | {a["tau"]:.2f}（{a["override"]}） | '
          f'{100*a["w_net"]:+.2f}% | {100*a["precision"]:.1f}% | '
          f'{b["tau"]:.2f}（{b["override"]}） | {100*b["w_net"]:+.2f}% | '
          f'{100*b["precision"]:.1f}% |')

    w('\n## Gate 判定\n')
    passing = {}
    for name in ('R4', 'I2'):
        ok = [r for r in res[name] if gate(r)[0]]
        passing[name] = ok
        w(f'* **{name}**：通過事前 gate 的 τ 有 **{len(ok)}** 個'
          + (f'，區間 [{min(r["tau"] for r in ok):.2f}, '
             f'{max(r["tau"] for r in ok):.2f}]' if ok else ''))
    for name in ('R4', 'I2'):
        if not passing[name]:
            r5 = next(x for x in res[name] if abs(x['tau'] - 0.5) < 1e-9)
            w(f'\n{name} @ τ=0.5 沒過的原因：' + '、'.join(gate(r5)[1]))

    chosen = None
    if passing['I2']:
        chosen = sorted(passing['I2'],
                        key=lambda r: (-r['precision'],
                                       r['cells']['作']['damage_rate'],
                                       -r['tau']))[0]
        w(f'\n**依 S1→S2→S3 選出 τ = {chosen["tau"]:.2f}**'
          f'（precision {100*chosen["precision"]:.1f}%、'
          f'加權 net {100*chosen["w_net"]:+.2f}%、'
          f'下界 {100*chosen["w_net_lo"]:+.2f}%）')

    w('\n## 判定\n')
    if chosen:
        w('> ## `GO TO FORMAL TEST`\n')
        w(f'凍結 I2 權重 + τ = {chosen["tau"]:.2f}，正式 Natural／X 一次性評測。')
    else:
        w('> ## `NO-GO / CALIBRATION FAILED`\n')
        w('完整掃過 τ = 0.00–3.00，**沒有任何 τ 同時通過四層事前 gate**。')

    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(o) + '\n')
    json.dump(res, open(os.path.splitext(args.out)[0] + '.json', 'w'),
              ensure_ascii=False, default=float)
    print('\n'.join(o))


if __name__ == '__main__':
    main()
