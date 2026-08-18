#!/usr/bin/env python3
# 在新的 audited model-dev 上量一顆 checkpoint（棒⑭-D PART B：只量測，不訓練）。
#
# ## 統計方法（寫清楚，因為棒⑭-B 就是死在這裡）
#
# 這份 dev 是**分層抽樣**，各 cell 抽樣率差很多（IPW 從 1.0 到 43.9）。
# 所以 aggregate 一律用分層估計：
#
#     p̂ = Σ_h w_h · p̂_h        w_h = N_h / N（N_h = 該 cell 母體）
#     Var(p̂) = Σ_h w_h² · (1 − f_h) · p̂_h(1−p̂_h) / (n_h − 1)      f_h = n_h/N_h
#
# `(1 − f_h)` 是有限母體修正。**這一項不能省**：本 dev 有多個 cell 是普查
# （n_h = N_h，例如 坐→坐·單字 23/23），那些 cell 的抽樣變異數是 0 ——
# 我們不是在估計它，是已經數完了。
#
# 事件數為 0 時常態近似會塌掉，所以改用「變異數配對」的有效樣本數再套 Wilson：
#
#     n_eff = 1 / Σ_h [ w_h² · (1 − f_h) / n_h ]
#
# 這是把 Var 寫成 p(1−p)/n_eff 反解出來的（假設各 cell 的 p 相近）。
# 全部普查時 n_eff → ∞，符合直覺。
#
# ⚠️ **不要**用「逐 cell Wilson 上界加權相加」—— 那是聯集界，不是 aggregate CI，
# 會過度保守（棒⑭-D 途中犯過，差點誤判 dev 不可用）。
#
# ## 人工金標的使用規則
#
# `human_confidence = uncertain` 一律**不進**任何需要人工金標的分母，
# 但仍然要報「模型在那些題目上出手幾次」—— 人都判不了的地方，專家應該棄權。
#
# 用法：
#   python3 eval_model_dev.py --annotated <...tsv> --meta <model-dev-meta.json> \
#       --ckpt <R4.pt> --tau 0.5 --nodes <nodes.tsv> --nodes2 <ctx-nodes.tsv> \
#       --out <報告.md>

import argparse
import collections
import json
import math
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_node_expert import MAX_CANDS, NodeExpert, encode  # noqa: E402

FIRE = 'ㄗㄨㄛˋ'
GROUP = ['作', '做', '坐', '座']
GSET = set(GROUP)


def wilson(k, n, z=1.96):
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(max(p * (1 - p), 0) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def load_node_features(paths):
    """node_id（sid#node_index）→ 特徵。兩個來源分開存，用 source 區分。"""
    out = {}
    for tag, path in paths:
        if not path or not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as fh:
            head = next(fh).rstrip('\n').split('\t')
            for line in fh:
                c = dict(zip(head, line.rstrip('\n').split('\t')))
                if int(c['kind']) != 0:
                    continue
                out[(tag, f"{c['sid']}#{c['node_index']}")] = c
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--annotated', required=True)
    ap.add_argument('--meta', required=True)
    ap.add_argument('--ckpt', required=True)
    ap.add_argument('--tau', type=float, default=0.5)
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--nodes2', default='')
    ap.add_argument('--leak-flags', default='',
                    help='sample_id→r4_seen 的旗標檔；給了就只評模型沒看過的子集')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    L = open(args.annotated, encoding='utf-8').read().rstrip('\n').split('\n')
    h = L[0].split('\t')
    ann = [dict(zip(h, x.split('\t'))) for x in L[1:]]
    meta = json.load(open(args.meta, encoding='utf-8'))
    cells_meta = meta['cells']

    feats = load_node_features([('train-src', args.nodes),
                                ('contexts', args.nodes2)])

    seen = set()
    if args.leak_flags:
        for i, ln in enumerate(open(args.leak_flags, encoding='utf-8')):
            if i == 0:
                continue
            sid, flag = ln.rstrip('\n').split('\t')
            if flag == '1':
                seen.add(sid)
        before = len(ann)
        ann = [a for a in ann if a['sample_id'] not in seen]
        print(f'排除模型看過的 {before - len(ann)} 筆 → 乾淨子集 {len(ann)} 筆')

    rows, missing = [], 0
    for a in ann:
        f = feats.get((a['source'], a['node_id']))
        if f is None:
            missing += 1
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
            missing += 1
            continue
        rows.append({
            'reading': f['reading'], 'chosen': f['chosen'], 'gold': f['gold'],
            'cands': cands, 'left': f['left_chars'], 'right': f['right_chars'],
            'right_empty': f['right_empty'] == '1',
            'gi': next((k for k, x in enumerate(cands) if x[0] == f['gold']), -1),
            'ti': ti, 'span': int(f['span']),
            'engine': f['chosen'][ti], 'corpus': f['gold'][ti],
            'human': a['human_gold'], 'conf': a['human_confidence'],
            'cell': a['cell'], 'span_class': a['span_class'],
            'sample_id': a['sample_id'],
        })

    ck = torch.load(args.ckpt, map_location='cpu')
    model = NodeExpert(**ck['cfg'])
    model.load_state_dict(ck['model'])
    model.eval()
    ci = {c: i for i, c in enumerate(ck['itos'])}
    si = {s: i for i, s in enumerate(ck['stos'])}
    enc = encode(rows, ci, si)
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
    n = len(rows)
    chi = np.array([next((k for k, c in enumerate(r['cands'])
                          if c[0] == r['chosen']), -1) for r in rows])
    best = lsm.argmax(1)
    margin = np.array([lsm[i, best[i]] - lsm[i, max(chi[i], 0)] for i in range(n)])
    fire = (chi >= 0) & (best != chi) & (margin > args.tau)
    newc = []
    for i in range(n):
        v = rows[i]['cands'][best[i]][0]
        syls = rows[i]['reading'].split('-')
        newc.append(v[rows[i]['ti']] if len(v) == len(syls) else None)

    for i, r in enumerate(rows):
        r['fire'] = bool(fire[i])
        r['new'] = newc[i]
        r['final'] = newc[i] if fire[i] else r['engine']
        r['det'] = r['conf'] in ('high', 'medium') and r['human'] in GSET

    # ── 分層估計 ──
    def strat(pred_num, pred_den):
        """回傳 (加權比率, n_eff, 未加權 k, 未加權 n, 逐 cell)。"""
        per = {}
        for c, m in cells_meta.items():
            sub = [r for r in rows if r['cell'] == c and pred_den(r)]
            if not sub:
                continue
            k = sum(1 for r in sub if pred_num(r))
            per[c] = (k, len(sub), m['population'])
        N = sum(v[2] for v in per.values())
        if not N:
            return 0.0, 0.0, 0, 0, per
        p = sum((v[2] / N) * (v[0] / v[1]) for v in per.values())
        inv = 0.0
        for k, nh, Nh in per.values():
            w = Nh / N
            f = min(nh / Nh, 1.0)
            if nh > 0 and f < 1.0:
                inv += w * w * (1 - f) / nh
        neff = (1 / inv) if inv > 0 else float('inf')
        return (p, neff, sum(v[0] for v in per.values()),
                sum(v[1] for v in per.values()), per)

    out = []
    w = out.append
    w('# Audited model-dev baseline（棒⑭-D PART B）\n')
    w(f'模型：`{args.ckpt}`（R4，凍結）　τ = {args.tau}　**只量測，未訓練**\n')
    w(f'\n接回節點特徵：{len(rows)}／{len(ann)}（接不上 {missing}）\n')

    det = [r for r in rows if r['det']]
    unc = [r for r in rows if not r['det']]
    w(f'\n## 樣本\n')
    w(f'* total = **{len(ann)}**')
    w(f'* determinable（high/medium）= **{len(det)}**')
    w(f'* uncertain = **{len(unc)}**（不進任何需要人工金標的分母）')
    w(f'* 模型在 uncertain 題目上出手 **{sum(1 for r in unc if r["fire"])}** 次'
      f'（人都判不了的地方，專家應該棄權）')

    w('\n### 各 cell 的 uncertain 數\n')
    w('| cell | audited n | determinable | uncertain |')
    w('|---|---|---|---|')
    for c in sorted(cells_meta, key=lambda x: -cells_meta[x]['population']):
        sub = [r for r in rows if r['cell'] == c]
        if not sub:
            continue
        d = sum(1 for r in sub if r['det'])
        w(f'| {c} | {len(sub)} | {d} | {len(sub) - d} |')

    # ── 主要 metrics ──
    w('\n## 主要 metrics（R4 @ τ=%s）\n' % args.tau)
    eng_ok = sum(1 for r in det if r['engine'] == r['human'])
    fin_ok = sum(1 for r in det if r['final'] == r['human'])
    corp_ok = sum(1 for r in det if r['corpus'] == r['human'])
    fires = [r for r in det if r['fire']]
    rescue = [r for r in fires if r['engine'] != r['human'] and r['new'] == r['human']]
    damage = [r for r in fires if r['engine'] == r['human'] and r['new'] != r['human']]
    waste = [r for r in fires if r not in rescue and r not in damage]

    pe, ne_e, _, _, _ = strat(lambda r: r['engine'] == r['human'], lambda r: r['det'])
    pf, ne_f, _, _, _ = strat(lambda r: r['final'] == r['human'], lambda r: r['det'])
    pc, ne_c, _, _, _ = strat(lambda r: r['corpus'] == r['human'], lambda r: r['det'])
    lo_e, hi_e = wilson(pe * ne_e, ne_e) if math.isfinite(ne_e) else (pe, pe)
    lo_f, hi_f = wilson(pf * ne_f, ne_f) if math.isfinite(ne_f) else (pf, pf)

    w('| metric | 未加權 | **加權（IPW）** | 95% CI（加權） | n_eff |')
    w('|---|---|---|---|---|')
    w(f'| 語料金標正確率 | {corp_ok}/{len(det)} = {100 * corp_ok / len(det):.1f}% '
      f'| **{100 * pc:.2f}%** | — | {ne_c:.0f} |')
    w(f'| **引擎正確率** | {eng_ok}/{len(det)} = {100 * eng_ok / len(det):.1f}% '
      f'| **{100 * pe:.2f}%** | [{100 * lo_e:.2f}, {100 * hi_e:.2f}] | {ne_e:.0f} |')
    w(f'| **專家最終正確率** | {fin_ok}/{len(det)} = {100 * fin_ok / len(det):.1f}% '
      f'| **{100 * pf:.2f}%** | [{100 * lo_f:.2f}, {100 * hi_f:.2f}] | {ne_f:.0f} |')

    w(f'\n* override（出手）＝ **{len(fires)}** / {len(det)}'
      f'（未加權出手率 {100 * len(fires) / len(det):.1f}%）')
    w(f'* abstention（棄權）＝ **{len(det) - len(fires)}**'
      f'（{100 * (1 - len(fires) / len(det)):.1f}%）')
    w(f'* rescue = **{len(rescue)}**、damage = **{len(damage)}**、'
      f'多餘出手 = {len(waste)}、net = **{len(rescue) - len(damage):+d}**（未加權）')
    w(f'* override precision = {len(rescue)}/{len(fires)} = '
      f'**{100 * len(rescue) / max(len(fires), 1):.1f}%**（未加權）')

    # 加權 rescue / damage / net
    pr, ne_r, kr, nr, _ = strat(
        lambda r: r['fire'] and r['new'] == r['human'],
        lambda r: r['det'] and r['engine'] != r['human'])
    pd_, ne_d, kd, nd, _ = strat(
        lambda r: r['fire'] and r['new'] != r['human'],
        lambda r: r['det'] and r['engine'] == r['human'])
    lo_r, hi_r = wilson(pr * ne_r, ne_r) if math.isfinite(ne_r) else (pr, pr)
    lo_d, hi_d = wilson(pd_ * ne_d, ne_d) if math.isfinite(ne_d) else (pd_, pd_)
    p_err, ne_pe, _, _, _ = strat(lambda r: r['engine'] != r['human'],
                                  lambda r: r['det'])

    w('\n### 加權 rescue / damage / net\n')
    w('| 量 | 未加權 | **加權** | 95% CI | n_eff |')
    w('|---|---|---|---|---|')
    w(f'| rescue rate（在引擎錯的節點上） | {kr}/{nr} = {100 * kr / max(nr, 1):.1f}% '
      f'| **{100 * pr:.2f}%** | [{100 * lo_r:.2f}, {100 * hi_r:.2f}] | {ne_r:.0f} |')
    dmg_txt = (f'observed = {kd}，**95% 上界 = {100 * hi_d:.2f}%**' if kd == 0
               else f'{100 * pd_:.2f}%　[{100 * lo_d:.2f}, {100 * hi_d:.2f}]')
    w(f'| damage rate（在引擎對的節點上） | {kd}/{nd} = {100 * kd / max(nd, 1):.2f}% '
      f'| {dmg_txt} | — | {ne_d:.0f} |')
    net = p_err * pr - (1 - p_err) * pd_
    net_lo = p_err * lo_r - (1 - p_err) * hi_d
    w(f'| **加權 net**（每個節點） | — | **{100 * net:+.2f}%** '
      f'| 下界 **{100 * net_lo:+.2f}%** | — |')
    w(f'\n（引擎錯的加權佔比 = {100 * p_err:.2f}%；'
      f'net = p_err × rescue − (1−p_err) × damage，下界用 rescue 下界與 damage 上界）')

    # ── Failure-mode matrix ──
    w('\n## 完整方向矩陣\n')
    w('| 方向 | 母體 | audited n | determinable | uncertain | IPW | '
      '引擎正確率 | override | rescue | damage | abstain | precision | 95% CI |')
    w('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    for e in GROUP:
        for g in GROUP:
            sub = [r for r in rows if r['engine'] == e and r['corpus'] == g]
            pop = sum(m['population'] for c, m in cells_meta.items()
                      if c.startswith(f'{e}→{g}·'))
            if not sub and not pop:
                continue
            d = [r for r in sub if r['det']]
            if not d:
                w(f'| {e}→{g} | {pop} | {len(sub)} | 0 | {len(sub)} | — | — | '
                  f'— | — | — | — | — | 母體 {pop}，無可判定 |')
                continue
            ipw = pop / len(sub) if sub else 0
            eok = sum(1 for r in d if r['engine'] == r['human'])
            fr = [r for r in d if r['fire']]
            rs = sum(1 for r in fr if r['engine'] != r['human'] and r['new'] == r['human'])
            dm = sum(1 for r in fr if r['engine'] == r['human'] and r['new'] != r['human'])
            if e != g:
                lo, hi = wilson(rs, len(d))
                cistr = f'rescue [{100 * lo:.1f}, {100 * hi:.1f}]'
            else:
                lo, hi = wilson(dm, len(d))
                cistr = (f'damage 0，上界 {100 * hi:.1f}%' if dm == 0
                         else f'damage [{100 * lo:.1f}, {100 * hi:.1f}]')
            w(f'| {e}→{g} | {pop} | {len(sub)} | {len(d)} | {len(sub) - len(d)} | '
              f'{ipw:.1f} | {100 * eok / len(d):.1f}% | {len(fr)} | {rs} | {dm} | '
              f'{len(d) - len(fr)} | {100 * rs / max(len(fr), 1):.0f}% | {cistr} |')

    # ── 單字 / 多字 ──
    w('\n## 單字 / 多字詞\n')
    w('| 跨度 | 引擎對 n | damage | damage rate 95% CI | 引擎錯 n | rescue | '
      'rescue rate 95% CI |')
    w('|---|---|---|---|---|---|---|')
    for lab, pred in (('單字', lambda r: r['span'] == 1),
                      ('多字詞', lambda r: r['span'] > 1)):
        cor = [r for r in det if pred(r) and r['engine'] == r['human']]
        wro = [r for r in det if pred(r) and r['engine'] != r['human']]
        dm = sum(1 for r in cor if r['fire'] and r['new'] != r['human'])
        rs = sum(1 for r in wro if r['fire'] and r['new'] == r['human'])
        l1, h1 = wilson(dm, len(cor))
        l2, h2 = wilson(rs, len(wro))
        d1 = (f'observed 0，上界 **{100 * h1:.2f}%**' if dm == 0
              else f'{100 * dm / len(cor):.2f}% [{100 * l1:.2f}, {100 * h1:.2f}]')
        w(f'| {lab} | {len(cor)} | {dm} | {d1} | {len(wro)} | {rs} | '
          f'{100 * rs / max(len(wro), 1):.1f}% [{100 * l2:.1f}, {100 * h2:.1f}] |')

    # ── 作→作 × 單字（前一棒的 hotspot）──
    w('\n## 作→作 × 單字（棒⑭-C 的 damage hotspot）\n')
    sub = [r for r in det if r['cell'] == '作→作·單字']
    fr = [r for r in sub if r['fire']]
    dm = sum(1 for r in fr if r['new'] != r['human'])
    lo, hi = wilson(dm, len(sub))
    w(f'* n（可判定）= **{len(sub)}**、override = **{len(fr)}**、damage = **{dm}**')
    w(f'* damage rate = {100 * dm / max(len(sub), 1):.2f}%　'
      f'Wilson 95% = [{100 * lo:.2f}%, **{100 * hi:.2f}%**]')
    w(f'* 對照正式 Natural test：34/338 單字 damage = 10.06% [7.29, 13.73]')

    # ── engine=做 的錯 ──
    w('\n## engine=做 的錯（R4 在正式 test 上幾乎不推翻）\n')
    w('| 方向 | determinable | override | rescue | abstain | rescue 95% CI |')
    w('|---|---|---|---|---|---|')
    for g in ['作', '坐', '座']:
        sub = [r for r in det if r['engine'] == '做' and r['human'] == g]
        fr = [r for r in sub if r['fire']]
        rs = sum(1 for r in fr if r['new'] == r['human'])
        lo, hi = wilson(rs, len(sub)) if sub else (0, 1)
        w(f'| 做→{g} | {len(sub)} | {len(fr)} | {rs} | {len(sub) - len(fr)} | '
          f'[{100 * lo:.1f}, {100 * hi:.1f}] |')

    text = '\n'.join(out) + '\n'
    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write(text)
    print(text)


if __name__ == '__main__':
    main()
