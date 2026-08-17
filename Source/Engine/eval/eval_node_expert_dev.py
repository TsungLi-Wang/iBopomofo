#!/usr/bin/env python3
# 在 **audited dev**（人工核驗過的金標）上評一顆 Node Expert checkpoint。
#
# ## 跟 pick_node_expert_tau.py 的差別
#
# 那一支比的是「模型 vs 語料金標」，而語料金標未經人工核。這一支比的是
# **模型 vs 人工金標**，所以「救／壞」是真的救、真的壞。
#
# ## 三件刻意的處理
#
# 1. **UNCERTAIN 不進正確率分母**，但單獨報「模型在人都判不了的題目上出手幾次」
#    —— 好的專家在那裡應該棄權，這是它自己的一項指標。
# 2. **單字 / 多字詞分開報**。棒⑭-A 量到錯誤有 75% 在單字節點，
#    合在一起看會被多字詞的高正確率蓋掉。
# 3. **抽樣是刻意偏斜的**（錯誤格被過抽），所以整體數字同時報未加權與
#    母體回加權兩種，不能只報一種。
#
# 用法：
#   python3 eval_node_expert_dev.py --dev <audited-dev.tsv> --ckpt <...pt> \
#       [--taus 0,1,2,3,4,6,8] [--meta <sampling-meta.json>] [--out <報告.md>]

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


def load_dev(path):
    L = open(path, encoding='utf-8').read().rstrip('\n').split('\n')
    h = L[0].split('\t')
    out = []
    for ln in L[1:]:
        c = dict(zip(h, ln.split('\t')))
        syls = c['reading'].split('-')
        if FIRE not in syls:
            continue
        ti = syls.index(FIRE)
        chosen, gold = c['chosen'], c['gold']
        if len(chosen) != len(syls) or len(gold) != len(syls):
            continue
        cands = []
        for part in c['cands'].split('|'):
            q = part.split(':')
            if len(q) == 5:
                cands.append((q[0], float(q[1]), float(q[2]), float(q[3]),
                              q[4] == '1'))
        cands.sort(key=lambda x: -x[1])
        cands = cands[:MAX_CANDS]
        if len(cands) < 2:
            continue
        out.append({
            'reading': c['reading'], 'chosen': chosen, 'gold': gold,
            'cands': cands, 'left': c['left_chars'], 'right': c['right_chars'],
            'right_empty': c['right_empty'] == '1',
            'gi': next((k for k, x in enumerate(cands) if x[0] == gold), -1),
            'ti': ti, 'span': int(c['span']),
            'engine_char': chosen[ti], 'corpus_char': gold[ti],
            'human': c['human_gold'], 'sample_id': c['sample_id'],
            'hard': chosen != gold,
        })
    return out


def mcnemar(b, c):
    """雙尾精確檢定（小樣本用二項式，不用卡方近似）。"""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n) * 2
    return min(1.0, p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dev', required=True)
    ap.add_argument('--ckpt', required=True)
    ap.add_argument('--taus', default='0,1,2,3,4,5,6,8,10')
    ap.add_argument('--meta', default='',
                    help='sampling-meta.json：有它才能把逐格比率回加權成母體預估')
    ap.add_argument('--out', default='')
    ap.add_argument('--label', default='')
    args = ap.parse_args()

    ck = torch.load(args.ckpt, map_location='cpu')
    itos, stos = ck['itos'], ck['stos']
    model = NodeExpert(**ck['cfg'])
    model.load_state_dict(ck['model'])
    model.eval()
    rows = load_dev(args.dev)

    ci = {c: i for i, c in enumerate(itos)}
    si = {s: i for i, s in enumerate(stos)}
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
    chosen_idx = np.array([next((k for k, c in enumerate(r['cands'])
                                 if c[0] == r['chosen']), -1) for r in rows])
    best = lsm.argmax(1)
    margin = np.array([lsm[i, best[i]] - lsm[i, max(chosen_idx[i], 0)]
                       for i in range(n)])
    valid = chosen_idx >= 0

    def char_of(i, k):
        """候選 k 在 ㄗㄨㄛˋ 那一格的字。"""
        v = rows[i]['cands'][k][0]
        syls = rows[i]['reading'].split('-')
        return v[rows[i]['ti']] if len(v) == len(syls) else None

    judged = np.array([r['human'] in GROUP for r in rows])
    human = [r['human'] for r in rows]
    engine_char = [r['engine_char'] for r in rows]

    out = []
    w = out.append
    tag = f'（{args.label}）' if args.label else ''
    w(f'# Audited dev 評估{tag}\n')
    w(f'checkpoint：`{args.ckpt}`\n')
    w(f'\ndev 節點 {n}（可判定 {int(judged.sum())}、'
      f'UNCERTAIN {n - int(judged.sum())}）\n')
    w('\n> 抽樣刻意過抽錯誤格，**整體數字不可直接當母體估計**；'
      '逐格數字才是可以直接看的。\n')

    eng_ok = sum(1 for i in range(n) if judged[i] and engine_char[i] == human[i])
    w(f'\n## 2. 引擎基線（對人工金標）：{eng_ok}/{int(judged.sum())} = '
      f'{100 * eng_ok / max(judged.sum(), 1):.1f}%\n')

    # 3. expert argmax accuracy（不套 τ）
    arg_ok = 0
    for i in range(n):
        if judged[i] and valid[i]:
            c = char_of(i, best[i])
            arg_ok += (c == human[i])
    w(f'## 3. 專家 argmax 正確率（未套 τ）：{arg_ok}/{int(judged.sum())} = '
      f'{100 * arg_ok / max(judged.sum(), 1):.1f}%\n')

    # τ 掃描
    w('\n## 4–9、13. 逐 τ（對人工金標）\n')
    w('| τ | 出手 | 出手率 | 救 | 壞 | 多餘 | 淨 | 出手精準率 | '
      '棄權率 | 在 UNCERTAIN 上出手 | McNemar p |')
    w('|---|---|---|---|---|---|---|---|---|---|---|')
    table = []
    for tau in [float(t) for t in args.taus.split(',')]:
        fired = valid & (best != chosen_idx) & (margin > tau)
        saved = broke = wasted = unc_fire = 0
        for i in range(n):
            if not fired[i]:
                continue
            if not judged[i]:
                unc_fire += 1
                continue
            newc = char_of(i, best[i])
            oldc = engine_char[i]
            if oldc != human[i] and newc == human[i]:
                saved += 1
            elif oldc == human[i] and newc != human[i]:
                broke += 1
            else:
                wasted += 1
        nf = saved + broke + wasted
        prec = saved / nf if nf else 0.0
        p = mcnemar(saved, broke)
        table.append(dict(tau=tau, fired=nf, saved=saved, broke=broke,
                          wasted=wasted, net=saved - broke,
                          precision=round(prec, 3), unc_fire=unc_fire, p=p))
        w(f'| {tau} | {nf} | {100 * nf / max(judged.sum(), 1):.1f}% | {saved} | '
          f'{broke} | {wasted} | {saved - broke:+d} | {prec:.3f} | '
          f'{100 * (1 - nf / max(judged.sum(), 1)):.1f}% | {unc_fire} | '
          f'{p:.3g} |')

    # ── 母體回加權的淨值預估（決定要不要進正式測試的關鍵）──
    #
    # audited dev 是**刻意過抽錯誤格**的：241 題裡有 114 題引擎是錯的（47%），
    # 但真實語料只有約 11%。直接看 dev 的「淨 +18」會嚴重高估 ——
    # 因為真實世界裡「引擎本來就對、被改壞」的機會多得多。
    # 所以把逐格的救／壞比率乘回母體的格子大小，才是對正式測試的預測。
    if args.meta:
        meta = json.load(open(args.meta, encoding='utf-8'))
        pop = meta['population_dir']
        pop_tot = meta['population_total']
        w('\n## 母體回加權的淨值預估（每 1,000 個作做坐座節點）\n')
        w('> dev 過抽錯誤格，直接看 dev 淨值會高估。這一欄把逐格比率乘回母體大小。\n')
        w('\n| τ | 預估救 | 預估壞 | **預估淨** | 預估出手 |')
        w('|---|---|---|---|---|')
        for t in table:
            tau_ = t['tau']
            fired_ = valid & (best != chosen_idx) & (margin > tau_)
            es = eb = ef = 0.0
            for e in GROUP:
                for g in GROUP:
                    key = f'{e}→{g}'
                    popn = pop.get(key, 0)
                    if not popn:
                        continue
                    idx = [i for i in range(n) if judged[i]
                           and engine_char[i] == e and rows[i]['corpus_char'] == g]
                    if not idx:
                        continue
                    sc = bc = fc = 0
                    for i in idx:
                        if not fired_[i]:
                            continue
                        fc += 1
                        newc = char_of(i, best[i])
                        if engine_char[i] != human[i] and newc == human[i]:
                            sc += 1
                        elif engine_char[i] == human[i] and newc != human[i]:
                            bc += 1
                    share = popn / pop_tot * 1000.0
                    es += share * sc / len(idx)
                    eb += share * bc / len(idx)
                    ef += share * fc / len(idx)
            w(f'| {tau_} | {es:.1f} | {eb:.1f} | **{es - eb:+.1f}** | {ef:.1f} |')

    # 10/11. 單字 vs 多字（在最佳淨值的 τ 上）
    bestrow = max(table, key=lambda t: (t['net'], t['precision']))
    tau = bestrow['tau']
    fired = valid & (best != chosen_idx) & (margin > tau)
    w(f'\n## 10–11. 單字 / 多字詞（τ={tau}）\n')
    w('| 類別 | dev 節點 | 引擎正確率 | 專家最終正確率 | 出手 | 救 | 壞 |')
    w('|---|---|---|---|---|---|---|')
    for label, pred in (('單字節點', lambda r: r['span'] == 1),
                        ('多字詞節點', lambda r: r['span'] > 1)):
        idx = [i for i in range(n) if pred(rows[i]) and judged[i]]
        if not idx:
            continue
        e_ok = sum(1 for i in idx if engine_char[i] == human[i])
        f_ok = s = b = 0
        for i in idx:
            final = char_of(i, best[i]) if fired[i] else engine_char[i]
            f_ok += (final == human[i])
            if fired[i]:
                if engine_char[i] != human[i] and final == human[i]:
                    s += 1
                elif engine_char[i] == human[i] and final != human[i]:
                    b += 1
        w(f'| {label} | {len(idx)} | {100 * e_ok / len(idx):.1f}% | '
          f'{100 * f_ok / len(idx):.1f}% | {int(fired[idx].sum())} | {s} | {b} |')

    # 1. overall accuracy after τ
    f_ok = sum(1 for i in range(n) if judged[i] and
               ((char_of(i, best[i]) if fired[i] else engine_char[i]) == human[i]))
    w(f'\n## 1. 套 τ={tau} 後的整體正確率：{f_ok}/{int(judged.sum())} = '
      f'{100 * f_ok / max(judged.sum(), 1):.1f}%'
      f'（引擎基線 {100 * eng_ok / max(judged.sum(), 1):.1f}%）\n')

    # 12. per direction
    w(f'\n## 12. 逐方向（引擎→人工金標，τ={tau}）\n')
    w('| 方向 | dev 節點 | 出手 | 救 | 壞 | 多餘 |')
    w('|---|---|---|---|---|---|')
    dirs = collections.Counter()
    agg = collections.defaultdict(lambda: [0, 0, 0, 0])
    for i in range(n):
        if not judged[i]:
            continue
        k = f'{engine_char[i]}→{human[i]}'
        dirs[k] += 1
        if fired[i]:
            newc = char_of(i, best[i])
            agg[k][0] += 1
            if engine_char[i] != human[i] and newc == human[i]:
                agg[k][1] += 1
            elif engine_char[i] == human[i] and newc != human[i]:
                agg[k][2] += 1
            else:
                agg[k][3] += 1
    for k, cnt in sorted(dirs.items(), key=lambda x: -x[1]):
        a = agg[k]
        w(f'| {k} | {cnt} | {a[0]} | {a[1]} | {a[2]} | {a[3]} |')

    text = '\n'.join(out) + '\n'
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            fh.write(text)
        with open(os.path.splitext(args.out)[0] + '.json', 'w',
                  encoding='utf-8') as fh:
            json.dump({'label': args.label, 'ckpt': args.ckpt,
                       'engine_acc': eng_ok / max(int(judged.sum()), 1),
                       'argmax_acc': arg_ok / max(int(judged.sum()), 1),
                       'judged': int(judged.sum()), 'taus': table,
                       'best': bestrow}, fh, ensure_ascii=False, indent=2)
    print(text)


if __name__ == '__main__':
    main()
