#!/usr/bin/env python3
# 節點層訓練資料的**方向分布稽核**（棒⑭-A，只讀不改）。
#
# ## 為什麼需要新工具（現有的三支都答不了這題）
#
#   compare_dumps.py            比兩份評測 dump，看的是「題目對不對」
#   node_expert_collateral.py   看誤傷與整句正確率
#   pick_node_expert_tau.py     在 dev 上掃 τ
#
# 三支都作用在**評測輸出**上。這次要問的是**訓練輸入**：
# 同一批節點樣本，在管線的每一道（過濾 → 分層採樣 → train/dev 切分 →
# 難例 ×N 加權）之後，「引擎選 X → 金標 Y」這 12 個方向各自剩下多少。
# 沒有任何現成工具會沿著管線逐段重算分布，所以新增這一支。
#
# ⚠️ 這支**完全不訓練、不改模型、不改 τ、不碰出貨檔**。它只重放
# `train_node_expert.py` 的過濾與採樣邏輯（直接 import 同一份程式碼，
# 不重寫，免得稽核的是另一條管線）。
#
# 用法：
#   python3 audit_node_directions.py --nodes <nodes.tsv> --sentences <sentences.jsonl> \
#       --out <報告目錄> [--nat-items ... --nat-dump ...] [--x-items ... --x-dump ...]

import argparse
import collections
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_node_expert import (DE_READING, MAX_CANDS,  # noqa: E402
                               load_rows, load_split_override)

GROUP = ['作', '做', '坐', '座']
GROUP_SET = set(GROUP)
FIRE_READING = 'ㄗㄨㄛˋ'


class Args:
    """load_rows 只用到 args 的欄位存在與否，這裡給個最小殼。"""
    pass


def target_pair(reading, chosen, gold):
    """取出節點裡 ㄗㄨㄛˋ 那一格的（引擎選的字, 金標字）。

    節點可能是多字詞（例如「坐在」，讀音 ㄗㄨㄛˋ-ㄗㄞˋ），所以要先找到
    ㄗㄨㄛˋ 是第幾個音節，再取該位置的字。長度對不上就回 None ——
    寧可不算，也不要製造一個對不齊的統計。
    """
    syls = reading.split('-')
    if FIRE_READING not in syls:
        return None
    i = syls.index(FIRE_READING)
    if len(chosen) != len(syls) or len(gold) != len(syls):
        return None
    c, g = chosen[i], gold[i]
    if c not in GROUP_SET or g not in GROUP_SET:
        return None
    return c, g


def matrix(rows, weights=None):
    """回傳 (engine, gold) → 次數。weights 為 None 時每筆算 1。"""
    m = collections.Counter()
    for i, r in enumerate(rows):
        p = target_pair(r['reading'], r['chosen'], r['gold'])
        if p is None:
            continue
        m[p] += 1 if weights is None else weights[i]
    return m


def fmt_matrix(m, title, fh):
    tot = sum(m.values())
    diag = sum(m[(c, c)] for c in GROUP)
    print(f'\n### {title}', file=fh)
    print(f'（總計 {tot:,}；引擎選對 {diag:,}（{100 * diag / tot:.1f}%）、'
          f'選錯 {tot - diag:,}（{100 * (tot - diag) / tot:.1f}%））\n', file=fh)
    print('| ENGINE＼GOLD | ' + ' | '.join(GROUP) + ' | 小計 |', file=fh)
    print('|---|' + '---|' * (len(GROUP) + 1), file=fh)
    for e in GROUP:
        row = [m[(e, g)] for g in GROUP]
        cells = []
        for g, v in zip(GROUP, row):
            cells.append(f'**{v:,}**' if e == g else f'{v:,}')
        print(f'| **{e}** | ' + ' | '.join(cells) + f' | {sum(row):,} |', file=fh)
    col = [sum(m[(e, g)] for e in GROUP) for g in GROUP]
    print('| **小計** | ' + ' | '.join(f'{v:,}' for v in col) +
          f' | {tot:,} |', file=fh)


def off_diag(m):
    return {f'{e}→{g}': m[(e, g)] for e in GROUP for g in GROUP
            if e != g and m[(e, g)]}


def audit_real(items_path, dump_path, name, fh):
    """人工核驗過的真實語料：引擎實際選了什麼 vs 金標。"""
    if not (items_path and dump_path and os.path.exists(items_path)
            and os.path.exists(dump_path)):
        print(f'\n### {name}：⚠️ 缺 items 或 dump，略過（不造數字）', file=fh)
        return None
    items = {}
    with open(items_path, encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            items[r['sentence_id']] = r
    out = {}
    with open(dump_path, encoding='utf-8') as f:
        next(f)
        for line in f:
            c = line.rstrip('\n').split('\t')
            if len(c) >= 5:
                out[c[0]] = c[4]
    m = collections.Counter()
    for sid, it in items.items():
        if it.get('pair_id') != '作做坐座' or sid not in out:
            continue
        ti = it['target_index']
        o = out[sid]
        if ti >= len(o):
            continue
        e, g = o[ti], it['target_char']
        if e in GROUP_SET and g in GROUP_SET:
            m[(e, g)] += 1
    fmt_matrix(m, f'{name}（人工核驗過的金標）', fh)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--sentences', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--per-stratum', type=int, default=400)
    ap.add_argument('--hard-weight', type=int, default=12)
    ap.add_argument('--dev-frac', type=float, default=0.20)
    ap.add_argument('--nat-items', default='')
    ap.add_argument('--nat-dump', default='')
    ap.add_argument('--x-items', default='')
    ap.add_argument('--x-dump', default='')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    report = os.path.join(args.out, 'direction-audit.md')
    fh = open(report, 'w', encoding='utf-8')

    print('# 節點層訓練資料 · 方向分布稽核（棒⑭-A）\n', file=fh)
    print('本報告只讀資料，不訓練、不改模型、不改 τ、不碰出貨檔。', file=fh)
    print(f'\n來源：`{args.nodes}`\n', file=fh)
    print(f'重放參數：per_stratum={args.per_stratum}、'
          f'hard_weight={args.hard_weight}、dev_frac={args.dev_frac}'
          f'（＝棒⑬ 實際跑的那組）\n', file=fh)

    # ── S0 RAW：完全不過濾，直接讀原始 TSV ──
    raw = []
    raw_stats = collections.Counter()
    cand_info = []   # 給候選分析用
    with open(args.nodes, encoding='utf-8') as f:
        next(f)
        for line in f:
            c = line.rstrip('\n').split('\t')
            if len(c) < 16:
                continue
            reading, chosen, gold = c[6], c[7], c[8]
            raw_stats['rows'] += 1
            p = target_pair(reading, chosen, gold)
            if p is None:
                continue
            raw.append({'reading': reading, 'chosen': chosen, 'gold': gold})
            cands = []
            for part in c[15].split('|'):
                q = part.split(':')
                if len(q) == 5:
                    cands.append((q[0], float(q[1])))
            cands.sort(key=lambda x: -x[1])
            names = [v for v, _ in cands]
            cand_info.append({
                'dir': p,
                'gold_in_raw': c[9] == '1',
                'n_cands': len(cands),
                'gold_rank': names.index(gold) + 1 if gold in names else -1,
                'gold_truncated': (gold in names
                                   and names.index(gold) >= MAX_CANDS),
                'de': DE_READING in reading.split('-'),
                'kind': int(c[2]),
            })

    m_raw = matrix(raw)
    print('\n## 2. 完整 4×4 confusion matrix（列＝引擎選的，欄＝金標）', file=fh)
    fmt_matrix(m_raw, 'A. 原始所有節點（S0 RAW，未經任何過濾）', fh)

    # ── S1 KEPT：套用 train_node_expert.load_rows 的過濾 ──
    a = Args()
    rows, stats, _, _ = load_rows(args.nodes, ['<pad>', '<unk>'],
                                 ['<pad>', '<unk>'], a)
    m_kept = matrix(rows)
    fmt_matrix(m_kept, 'B-0. 過濾後（S1 KEPT：剔 ㄉㄜ˙／lattice-miss／候選<2／金標被截）', fh)

    hard_rows = [r for r in rows if r['hard']]
    m_hard = matrix(hard_rows)
    fmt_matrix(m_hard, 'B. hard examples（引擎選錯，金標仍在候選裡）', fh)

    # ── S2 STRAT：完全重放分層採樣（同樣的 seed 與順序）──
    rng = random.Random(20260814)
    by_stratum = collections.defaultdict(list)
    for i, r in enumerate(rows):
        by_stratum[(r['reading'], r['gold'])].append(i)
    keep = []
    for k, v in by_stratum.items():
        if len(v) > args.per_stratum:
            v = rng.sample(v, args.per_stratum)
        keep.extend(v)
    keep.sort()
    strat = [rows[i] for i in keep]
    m_strat = matrix(strat)
    fmt_matrix(m_strat, f'B-1. 分層採樣後（每個「讀音×金標」上限 {args.per_stratum}）', fh)

    # ── S3 split ──
    sid_split = load_split_override(args.sentences, args.dev_frac)
    # load_rows 已把 split 寫進 row；這裡用同一個 override 重算
    # （load_rows 沒帶 sid_split，所以 row['split'] 是抽取當下的 8%，
    #  要用 sentences.jsonl 重算成棒⑬ 實際用的 20%）
    sids = []
    with open(args.nodes, encoding='utf-8') as f:
        next(f)
        for line in f:
            c = line.rstrip('\n').split('\t')
            if len(c) >= 16:
                sids.append(int(c[0]))
    # rows 是 load_rows 過濾後的子集，順序與檔案一致 → 需要同樣的過濾走一次 sid
    kept_sids = []
    with open(args.nodes, encoding='utf-8') as f:
        next(f)
        for line in f:
            c = line.rstrip('\n').split('\t')
            if len(c) < 16:
                continue
            if DE_READING in c[6].split('-'):
                continue
            if c[9] != '1':
                continue
            cands = [q.split(':') for q in c[15].split('|')]
            cands = [(q[0], float(q[1])) for q in cands if len(q) == 5]
            if len(cands) < 2:
                continue
            cands.sort(key=lambda x: -x[1])
            names = [v for v, _ in cands[:MAX_CANDS]]
            if c[8] not in names:
                continue
            kept_sids.append(int(c[0]))
    assert len(kept_sids) == len(rows), (len(kept_sids), len(rows))
    strat_sids = [kept_sids[i] for i in keep]
    for r, s in zip(strat, strat_sids):
        r['split'] = sid_split.get(s, r['split'])

    train = [r for r in strat if r['split'] == 'train']
    dev = [r for r in strat if r['split'] == 'dev']
    m_train, m_dev = matrix(train), matrix(dev)
    fmt_matrix(m_train, 'D. train（分層採樣後、依 doc_id 切）', fh)
    fmt_matrix(m_dev, 'E. dev（同上）', fh)

    # ── S4 ×N 加權後的「有效」訓練分布 ──
    w = [args.hard_weight if r['hard'] else 1 for r in train]
    m_eff = matrix(train, w)
    fmt_matrix(m_eff, f'C. ×{args.hard_weight} 加權後的有效訓練分布', fh)

    # ── 3. 三段分布並排 ──
    print('\n## 3. 原始 vs hard-example vs ×%d 後（逐方向）' % args.hard_weight,
          file=fh)
    print('\n只列 12 個「引擎選錯」的方向（對角線是引擎選對，另見第 5 節）。\n',
          file=fh)
    print(f'| 方向 | S0 原始 | S1 過濾後 | hard | S2 分層後 | train | '
          f'**×{args.hard_weight} 有效** | 有效佔比 |', file=fh)
    print('|---|---|---|---|---|---|---|---|', file=fh)
    eff_off_total = sum(v for (e, g), v in m_eff.items() if e != g)
    for e in GROUP:
        for g in GROUP:
            if e == g:
                continue
            ev = m_eff[(e, g)]
            share = 100 * ev / eff_off_total if eff_off_total else 0
            print(f'| {e}→{g} | {m_raw[(e, g)]:,} | {m_kept[(e, g)]:,} | '
                  f'{m_hard[(e, g)]:,} | {m_strat[(e, g)]:,} | '
                  f'{m_train[(e, g)]:,} | **{ev:,}** | {share:.1f}% |', file=fh)
    print(f'| **合計（非對角）** | '
          f'{sum(v for (e, g), v in m_raw.items() if e != g):,} | '
          f'{sum(v for (e, g), v in m_kept.items() if e != g):,} | '
          f'{sum(m_hard.values()):,} | '
          f'{sum(v for (e, g), v in m_strat.items() if e != g):,} | '
          f'{sum(v for (e, g), v in m_train.items() if e != g):,} | '
          f'**{eff_off_total:,}** | 100% |', file=fh)

    # ── 4. Engine bias ──
    print('\n## 4. Engine bias', file=fh)
    for label, m in (('S1 過濾後', m_kept), (f'×{args.hard_weight} 有效', m_eff)):
        tot = sum(m.values())
        print(f'\n### {label}：引擎選了什麼\n', file=fh)
        print('| 引擎選 | 次數 | 佔比 | 其中金標＝作 | ＝做 | ＝坐 | ＝座 | '
              '該選擇的正確率 |', file=fh)
        print('|---|---|---|---|---|---|---|---|', file=fh)
        for e in GROUP:
            row = [m[(e, g)] for g in GROUP]
            n = sum(row)
            acc = m[(e, e)] / n if n else 0
            print(f'| {e} | {n:,} | {100 * n / tot if tot else 0:.1f}% | '
                  + ' | '.join(f'{v:,}' for v in row)
                  + f' | {100 * acc:.1f}% |', file=fh)

    # ── 5. engine == gold 有沒有進訓練 ──
    print('\n## 5. 正確節點（engine == gold）有沒有進 training', file=fh)
    diag_train = {c: m_train[(c, c)] for c in GROUP}
    diag_eff = {c: m_eff[(c, c)] for c in GROUP}
    off_train = sum(v for (e, g), v in m_train.items() if e != g)
    off_eff = sum(v for (e, g), v in m_eff.items() if e != g)
    print(f'\n**有進。** 過濾後保留的每一筆都進訓練，難例只是被額外複製 '
          f'{args.hard_weight} 份。\n', file=fh)
    print('| | 作 | 做 | 坐 | 座 | 合計 | 對 : 錯 |', file=fh)
    print('|---|---|---|---|---|---|---|', file=fh)
    dt = sum(diag_train.values())
    de = sum(diag_eff.values())
    print('| train（未加權） | ' + ' | '.join(f'{diag_train[c]:,}' for c in GROUP)
          + f' | {dt:,} | {dt / off_train:.2f} : 1 |', file=fh)
    print(f'| ×{args.hard_weight} 有效 | '
          + ' | '.join(f'{diag_eff[c]:,}' for c in GROUP)
          + f' | {de:,} | {de / off_eff:.2f} : 1 |', file=fh)

    # ── 6. 候選 / lattice-miss ──
    print('\n## 6. 候選集合與 lattice-miss（逐方向）', file=fh)
    print('\n把「候選裡根本沒有正解」跟「候選裡有、模型選錯」分開 ——'
          '前者是詞庫／候選生成的題，不是這顆模型的題。\n', file=fh)
    print('| 方向 | 節點數 | 金標不在候選 | 佔比 | 候選數中位數 | '
          '金標在候選時的排名中位數 |', file=fh)
    print('|---|---|---|---|---|---|', file=fh)

    def med(v):
        v = sorted(v)
        return v[len(v) // 2] if v else 0

    by_dir = collections.defaultdict(list)
    for c in cand_info:
        by_dir[c['dir']].append(c)
    for e in GROUP:
        for g in GROUP:
            v = by_dir.get((e, g))
            if not v:
                continue
            miss = sum(1 for x in v if not x['gold_in_raw'])
            ranks = [x['gold_rank'] for x in v if x['gold_rank'] > 0]
            tag = f'{e}→{g}' + ('（引擎選對）' if e == g else '')
            print(f'| {tag} | {len(v):,} | {miss:,} | '
                  f'{100 * miss / len(v):.2f}% | {med([x["n_cands"] for x in v])} | '
                  f'{med(ranks)} |', file=fh)
    tot_all = len(cand_info)
    tot_miss = sum(1 for c in cand_info if not c['gold_in_raw'])
    print(f'\n作做坐座節點總計 {tot_all:,}，金標不在候選 {tot_miss:,}'
          f'（{100 * tot_miss / tot_all:.2f}%）。\n', file=fh)
    trunc = sum(1 for c in cand_info if c['gold_truncated'])
    de_n = sum(1 for c in cand_info if c['de'])
    pre_n = sum(1 for c in cand_info if c['kind'] == 1)
    print(f'另：金標排名被 MAX_CANDS={MAX_CANDS} 截掉 {trunc:,} 筆；'
          f'此組節點中讀音含 ㄉㄜ˙ 的 {de_n:,} 筆；前綴樣本 {pre_n:,} 筆。\n',
          file=fh)

    # ── F. 人工核驗過的真實語料 ──
    print('\n## 7. F. 人工核驗過的真實語料（引擎實際選了什麼）', file=fh)
    m_nat = audit_real(args.nat_items, args.nat_dump, '自然驗證集', fh)
    m_x = audit_real(args.x_items, args.x_dump, 'X驗證集', fh)

    # ── 訓練分布 vs 真實需求 ──
    if m_nat:
        print('\n### 訓練有效分布 vs 真實語料實際需求（非對角，佔比）\n', file=fh)
        print('| 方向 | 訓練 ×%d 佔比 | 自然驗證集佔比 | 倍率 |'
              % args.hard_weight, file=fh)
        print('|---|---|---|---|', file=fh)
        nat_off_tot = sum(v for (e, g), v in m_nat.items() if e != g)
        for e in GROUP:
            for g in GROUP:
                if e == g:
                    continue
                tr = 100 * m_eff[(e, g)] / eff_off_total if eff_off_total else 0
                re_ = 100 * m_nat[(e, g)] / nat_off_tot if nat_off_tot else 0
                ratio = (tr / re_) if re_ else float('inf')
                rs = '—' if re_ == 0 else f'{ratio:.2f}×'
                print(f'| {e}→{g} | {tr:.1f}% | {re_:.1f}% | {rs} |', file=fh)

    json_out = {
        'raw': {f'{e}→{g}': m_raw[(e, g)] for e in GROUP for g in GROUP},
        'kept': {f'{e}→{g}': m_kept[(e, g)] for e in GROUP for g in GROUP},
        'hard': {f'{e}→{g}': m_hard[(e, g)] for e in GROUP for g in GROUP},
        'strat': {f'{e}→{g}': m_strat[(e, g)] for e in GROUP for g in GROUP},
        'train': {f'{e}→{g}': m_train[(e, g)] for e in GROUP for g in GROUP},
        'dev': {f'{e}→{g}': m_dev[(e, g)] for e in GROUP for g in GROUP},
        'effective': {f'{e}→{g}': m_eff[(e, g)] for e in GROUP for g in GROUP},
        'natural': ({f'{e}→{g}': m_nat[(e, g)] for e in GROUP for g in GROUP}
                    if m_nat else None),
        'x': ({f'{e}→{g}': m_x[(e, g)] for e in GROUP for g in GROUP}
              if m_x else None),
        'pipeline_stats': dict(stats),
        'params': {'per_stratum': args.per_stratum,
                   'hard_weight': args.hard_weight,
                   'dev_frac': args.dev_frac},
    }
    fh.close()
    with open(os.path.join(args.out, 'direction-audit.json'), 'w',
              encoding='utf-8') as jf:
        json.dump(json_out, jf, ensure_ascii=False, indent=2)
    print(open(report, encoding='utf-8').read())


if __name__ == '__main__':
    main()
