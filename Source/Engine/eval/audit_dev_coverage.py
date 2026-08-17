#!/usr/bin/env python3
# Dev 覆蓋率稽核：為什麼 audited dev 預估 +19.9／1,000，正式 Natural 卻是 −10？
#（棒⑭-C，只讀不改：不訓練、不改 R4、不改 τ、不跑新的正式判準）
#
# ## 這支要回答的三件事
#
# 1. **正式測試的失敗模式矩陣**：每個 X→Y 方向，母體多少、引擎錯多少、
#    R4 出手／救／壞／棄權各多少。
# 2. **dev 對測試的覆蓋率**：同一套方向，dev 有沒有樣本、R4 在 dev 上有沒有出手。
#    「做→坐 在 dev 上出手 0 次」到底是沒樣本、還是有樣本但不出手。
# 3. **不確定性**：每個方向的救／壞比率都要附信賴區間。
#    **「觀察到 0 次改壞」不等於「傷害率 = 0」** —— 棒⑭-B 就是這樣誤判的
#    （dev 127 個引擎正確節點觀察到 0 次改壞，正式測試量到 3.4%）。
#
# 用法：
#   python3 audit_dev_coverage.py --dev <audited-dev.tsv> --ckpt <R4.pt> \
#       --test-nodes <nat-nodes.tsv> --test-items <自然驗證集.jsonl> \
#       --off <nat_off.tsv> --on <nat_on.tsv> --tau 0.5 --out <報告.md>

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
    """Wilson 區間。0/n 也給得出上界 —— 這正是棒⑭-B 缺的那一塊。"""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def target_pair(reading, chosen, gold):
    syls = reading.split('-')
    if FIRE not in syls:
        return None
    i = syls.index(FIRE)
    if len(chosen) != len(syls) or len(gold) != len(syls):
        return None
    if chosen[i] not in GSET or gold[i] not in GSET:
        return None
    return i, chosen[i], gold[i]


def load_nodes(path, human=None):
    """讀 nodes.tsv（或 audited-dev.tsv）→ 特徵 dict。"""
    L = open(path, encoding='utf-8').read().rstrip('\n').split('\n')
    h = L[0].split('\t')
    out = []
    for ln in L[1:]:
        c = dict(zip(h, ln.split('\t')))
        if int(c.get('kind', 0)) != 0:
            continue
        tp = target_pair(c['reading'], c['chosen'], c['gold'])
        if tp is None:
            continue
        ti, e, g = tp
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
            'sid': c['sid'], 'reading': c['reading'], 'chosen': c['chosen'],
            'gold': c['gold'], 'cands': cands, 'left': c['left_chars'],
            'right': c['right_chars'], 'right_empty': c['right_empty'] == '1',
            'gi': next((k for k, x in enumerate(cands) if x[0] == c['gold']), -1),
            'ti': ti, 'span': int(c['span']), 'engine_char': e,
            'corpus_char': g, 'n_cands': len(cands),
            'human': c.get('human_gold', ''),
            'sample_id': c.get('sample_id', ''),
        })
    return out


def score(model, rows, itos, stos):
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
    ch_idx = np.array([next((k for k, c in enumerate(r['cands'])
                             if c[0] == r['chosen']), -1) for r in rows])
    best = lsm.argmax(1)
    margin = np.array([lsm[i, best[i]] - lsm[i, max(ch_idx[i], 0)]
                       for i in range(n)])
    newchar = []
    for i in range(n):
        v = rows[i]['cands'][best[i]][0]
        syls = rows[i]['reading'].split('-')
        newchar.append(v[rows[i]['ti']] if len(v) == len(syls) else None)
    return ch_idx, best, margin, newchar


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dev', required=True)
    ap.add_argument('--ckpt', required=True)
    ap.add_argument('--test-nodes', required=True)
    ap.add_argument('--test-items', required=True)
    ap.add_argument('--tau', type=float, default=0.5)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    ck = torch.load(args.ckpt, map_location='cpu')
    itos, stos = ck['itos'], ck['stos']
    model = NodeExpert(**ck['cfg'])
    model.load_state_dict(ck['model'])
    model.eval()

    # ── 測試側：Natural 的節點。金標＝人工核驗過的驗證集答案 ──
    items = {}
    for line in open(args.test_items, encoding='utf-8'):
        r = json.loads(line)
        if r.get('pair_id') == '作做坐座':
            items[r['sentence_id']] = r
    tnodes = load_nodes(args.test_nodes)
    # nat-sentences.jsonl 的 doc_id 就是 sentence_id，sid 是行號 → 對回去
    order = [json.loads(l)['doc_id'] for l in
             open(os.path.join(os.path.dirname(args.test_nodes),
                               'nat-sentences.jsonl'), encoding='utf-8')]
    for r in tnodes:
        r['sentence_id'] = order[int(r['sid']) - 1]

    # 只留「該句的目標字」所在的節點 —— 驗證集一句只評一個位置
    keep = []
    for r in tnodes:
        it = items.get(r['sentence_id'])
        if not it:
            continue
        r['gold_human'] = it['target_char']
        keep.append(r)
    tnodes = keep

    ch_t, best_t, mar_t, new_t = score(model, tnodes, itos, stos)
    fire_t = (ch_t >= 0) & (best_t != ch_t) & (mar_t > args.tau)

    dnodes = load_nodes(args.dev)
    ch_d, best_d, mar_d, new_d = score(model, dnodes, itos, stos)
    fire_d = (ch_d >= 0) & (best_d != ch_d) & (mar_d > args.tau)

    out = []
    w = out.append
    w('# Dev 覆蓋率稽核（棒⑭-C）\n')
    w('> 只讀。沒有重新訓練、沒有改 R4、沒有改 τ、沒有跑新的正式判準。\n')
    w(f'\nR4 @ τ={args.tau}；測試側節點 {len(tnodes)}、dev 節點 {len(dnodes)}\n')

    def matrix(rows, fire, newc, goldkey, title):
        agg = collections.defaultdict(lambda: collections.Counter())
        for i, r in enumerate(rows):
            g = r[goldkey]
            if g not in GSET:
                continue
            k = (r['engine_char'], g)
            a = agg[k]
            a['n'] += 1
            if fire[i]:
                a['fire'] += 1
                if r['engine_char'] != g and newc[i] == g:
                    a['save'] += 1
                elif r['engine_char'] == g and newc[i] != g:
                    a['damage'] += 1
                else:
                    a['waste'] += 1
            else:
                a['abstain'] += 1
        return agg

    tm = matrix(tnodes, fire_t, new_t, 'gold_human', 'test')
    dm = matrix(dnodes, fire_d, new_d, 'human', 'dev')

    # ── A. 正式測試失敗模式矩陣 ──
    w('\n## A. Natural formal test：失敗模式矩陣\n')
    w('| 方向 | 母體 | 引擎錯 | R4 出手 | 救 | 壞 | 多餘 | 棄權 |')
    w('|---|---|---|---|---|---|---|---|')
    for e in GROUP:
        for g in GROUP:
            a = tm.get((e, g))
            if not a:
                continue
            err = a['n'] if e != g else 0
            tag = f'{e}→{g}' + ('（引擎選對）' if e == g else '')
            w(f'| {tag} | {a["n"]} | {err} | {a["fire"]} | {a["save"]} | '
              f'{a["damage"]} | {a["waste"]} | {a["abstain"]} |')

    # ── B. coverage ──
    w('\n## B. Natural vs audited dev 覆蓋率\n')
    w('| 方向 | Natural 母體 | Natural 引擎錯 | Dev 母體 | Dev 引擎錯 | '
      'Dev R4 出手 | Test R4 出手 | 覆蓋判定 |')
    w('|---|---|---|---|---|---|---|---|')
    gaps = []
    for e in GROUP:
        for g in GROUP:
            if e == g:
                continue
            t = tm.get((e, g), collections.Counter())
            d = dm.get((e, g), collections.Counter())
            verdict = '✅'
            if t['n'] and not d['n']:
                verdict = '❌ dev 完全沒樣本'
            elif t['n'] and d['n'] and d['fire'] == 0 and t['fire'] > 0:
                verdict = '⚠️ dev 有樣本但 0 出手'
            elif t['n'] >= 20 and d['n'] < 5:
                verdict = '⚠️ dev 樣本過少'
            if verdict != '✅':
                gaps.append((f'{e}→{g}', t['n'], d['n'], d['fire'], t['fire'],
                             verdict))
            w(f'| {e}→{g} | {t["n"]} | {t["n"]} | {d["n"]} | {d["n"]} | '
              f'{d["fire"]} | {t["fire"]} | {verdict} |')

    # ── C. 做→坐 深入診斷 ──
    for key in [('做', '坐'), ('作', '坐'), ('作', '座')]:
        e, g = key
        w(f'\n## C. `{e}→{g}` 深入診斷\n')
        for name, rows, fire, mar, newc, gk in (
                ('audited dev', dnodes, fire_d, mar_d, new_d, 'human'),
                ('Natural test', tnodes, fire_t, mar_t, new_t, 'gold_human')):
            idx = [i for i, r in enumerate(rows)
                   if r['engine_char'] == e and r.get(gk) == g]
            if not idx:
                w(f'* **{name}**：0 個節點')
                continue
            has_gold = sum(1 for i in idx
                           if any(c[0][rows[i]['ti']] == g
                                  for c in rows[i]['cands']
                                  if len(c[0]) == len(rows[i]['reading'].split('-'))))
            m = sorted(mar[i] for i in idx)
            picks = collections.Counter(newc[i] for i in idx)
            fired = sum(1 for i in idx if fire[i])
            spans = collections.Counter(rows[i]['span'] for i in idx)
            nc = sorted(rows[i]['n_cands'] for i in idx)
            w(f'* **{name}**：{len(idx)} 個節點；候選含正解 {has_gold}'
              f'（{100 * has_gold / len(idx):.0f}%）；'
              f'τ={args.tau} 下出手 {fired}')
            w(f'  * margin 分位：min {m[0]:.2f}、25% {m[len(m)//4]:.2f}、'
              f'中位 {m[len(m)//2]:.2f}、75% {m[3*len(m)//4]:.2f}、max {m[-1]:.2f}')
            w(f'  * 模型 argmax 選了：'
              + '、'.join(f'{k} {v}' for k, v in picks.most_common()))
            w(f'  * 跨度：' + '、'.join(f'{k}字 {v}' for k, v in sorted(spans.items()))
              + f'；候選數中位 {nc[len(nc)//2]}')

    # ── F. 不確定性 ──
    w('\n## F. 逐方向的比率與信賴區間（Wilson 95%）\n')
    w('**「觀察到 0 次改壞」不是「傷害率 = 0」** —— 看上界。\n')
    w('\n| 方向 | 來源 | n | 救 | 救回率 [95% CI] | 壞 | 傷害率 [95% CI] |')
    w('|---|---|---|---|---|---|---|')
    for e in GROUP:
        for g in GROUP:
            for name, mm in (('dev', dm), ('test', tm)):
                a = mm.get((e, g))
                if not a or not a['n']:
                    continue
                if e != g:
                    lo, hi = wilson(a['save'], a['n'])
                    w(f'| {e}→{g} | {name} | {a["n"]} | {a["save"]} | '
                      f'{100 * a["save"] / a["n"]:.1f}% [{100 * lo:.1f}, {100 * hi:.1f}] '
                      f'| — | — |')
                else:
                    lo, hi = wilson(a['damage'], a['n'])
                    w(f'| {e}→{g}（選對） | {name} | {a["n"]} | — | — | '
                      f'{a["damage"]} | {100 * a["damage"] / a["n"]:.2f}% '
                      f'[{100 * lo:.2f}, **{100 * hi:.2f}**] |')

    # 整體傷害率
    w('\n### 整體「引擎本來就對」的傷害率\n')
    for name, mm in (('audited dev', dm), ('Natural test', tm)):
        n = sum(a['n'] for (e, g), a in mm.items() if e == g)
        dmg = sum(a['damage'] for (e, g), a in mm.items() if e == g)
        lo, hi = wilson(dmg, n)
        w(f'* **{name}**：{dmg}/{n} = {100 * dmg / max(n, 1):.2f}%'
          f'　95% CI [{100 * lo:.2f}%, **{100 * hi:.2f}%**]')

    # ── 分布對照 ──
    w('\n## 分布對照（dev vs test）\n')
    w('| 指標 | audited dev | Natural test |')
    w('|---|---|---|')
    for label, fn in (('節點數', lambda rs: len(rs)),
                      ('單字節點佔比', lambda rs: f'{100 * sum(1 for r in rs if r["span"] == 1) / len(rs):.1f}%'),
                      ('候選數中位', lambda rs: sorted(r['n_cands'] for r in rs)[len(rs) // 2]),
                      ('右邊為空佔比', lambda rs: f'{100 * sum(1 for r in rs if r["right_empty"]) / len(rs):.1f}%')):
        w(f'| {label} | {fn(dnodes)} | {fn(tnodes)} |')
    dj = [r for r in dnodes if r['human'] in GSET]
    w(f'| 引擎正確率 | '
      f'{100 * sum(1 for r in dj if r["engine_char"] == r["human"]) / len(dj):.1f}% | '
      f'{100 * sum(1 for r in tnodes if r["engine_char"] == r["gold_human"]) / len(tnodes):.1f}% |')

    text = '\n'.join(out) + '\n'
    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write(text)
    print(text)


if __name__ == '__main__':
    main()
