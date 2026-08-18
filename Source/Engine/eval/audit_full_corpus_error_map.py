#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棒⑭-M：全語料字級錯誤地圖。

輸入是 `bin/full_corpus_error_map` 倒出來的**每一個 walk 節點**（含單候選節點）。
本檔把它重組回整句、逐字比對真人原文，然後對每一個錯字自動分類。

**不訓練、不標註、不碰 production。** 所有分類都是 heuristic，
由 inference-time 可得的欄位推導 —— **不是人工真值**，報告裡必須這樣寫。

只用推論時可得的資訊：節點的 reading／candidates／span／walk 選的左右字。
金標只用來「判定哪裡錯了」與「金標在不在候選裡」，
**不作為特徵**；任何只有離線才拿得到的欄位都標 offline-only。

用法：
  python3 audit_full_corpus_error_map.py --nodes <all-nodes.tsv> \\
      --items <自然驗證集.jsonl> --out <報告片段.md>
"""

import argparse
import collections
import json

# 目前已研究的六個混淆組（real-corpus-error-layers.md）
SIX = {'作做坐座': set('作做坐座'), '前錢': set('前錢'), '吧八巴': set('吧八巴'),
       '在再': set('在再'), '的得': set('的得'), '較叫': set('較叫')}
SIX_CHARS = set().union(*SIX.values())


def load_nodes(path):
    sent = collections.defaultdict(list)
    with open(path, encoding='utf-8') as fh:
        head = next(fh).rstrip('\n').split('\t')
        for line in fh:
            c = dict(zip(head, line.rstrip('\n').split('\t')))
            if c['kind'] != '0':      # 只用完整句，不用前綴樣本
                continue
            sent[c['sid']].append(c)
    return sent


def build(sent, meta):
    """回傳逐錯字的紀錄。每個錯字帶它所在節點的候選資訊。"""
    errs, tot_chars, tot_sents, skipped = [], 0, 0, 0
    for sid, ns in sent.items():
        ns.sort(key=lambda x: int(x['char_start']))
        chosen = ''.join(n['chosen'] for n in ns)
        gold = ''.join(n['gold'] for n in ns)
        if len(chosen) != len(gold):
            skipped += 1
            continue
        tot_sents += 1
        tot_chars += len(gold)
        wrong = [i for i in range(len(gold)) if chosen[i] != gold[i]]
        if not wrong:
            continue
        wset = set(wrong)
        # 節點索引：每個字位屬於哪個節點
        owner = {}
        for n in ns:
            s = int(n['char_start'])
            for k in range(s, s + int(n['span'])):
                owner[k] = n
        m = meta.get(sid, {})
        for i in wrong:
            n = owner[i]
            # run 長度：這個錯字所在的「連續錯字段」有多長
            a = i
            while a - 1 in wset:
                a -= 1
            b = i
            while b + 1 in wset:
                b += 1
            errs.append({
                'sid': sid, 'pos': i, 'gold': gold[i], 'chosen': chosen[i],
                'reading': n['reading'], 'span': int(n['span']),
                'gold_in_cands': n['gold_in_cands'] == '1',
                'n_cands': int(n['n_cands']),
                'gold_rank': int(n['gold_rank']),
                'chosen_rank': int(n['chosen_rank']),
                'node_chosen': n['chosen'], 'node_gold': n['gold'],
                'run_len': b - a + 1,
                'sent_len': len(gold),
                'sent_errs': len(wrong),
                'domain': m.get('domain', ''), 'pair_id': m.get('pair_id', ''),
                'is_target': m.get('target_index', -1) == i,
            })
    return errs, tot_chars, tot_sents, skipped


def family(e):
    """八分類（§九）。先命中先算，互斥。"""
    if not e['gold_in_cands']:
        if e['n_cands'] <= 1:
            return '6 lattice：該節點只有一個候選'
        if e['span'] > 1:
            return '5 多字節點·金標不在候選'
        return '3 單字節點·金標不在候選'
    if e['span'] > 1:
        return '4 多字節點·金標在候選'
    if e['gold'] in SIX_CHARS:
        return '1 已知六組·單字·金標在候選'
    return '2 單字節點·金標在候選（六組以外）'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--items', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    meta = {}
    with open(args.items, encoding='utf-8') as fh:
        for i, line in enumerate(fh, start=1):
            if line.strip():
                meta[str(i)] = json.loads(line)

    sent = load_nodes(args.nodes)
    errs, tot_chars, tot_sents, skipped = build(sent, meta)
    N = len(errs)
    out, w = [], None
    out_lines = []
    w = out_lines.append

    w('## D2 重現\n')
    w(f'* 句數 **{tot_sents:,}**（長度不等而略過 {skipped}）')
    w(f'* 字位 **{tot_chars:,}**')
    w(f'* 錯字 **{N:,}** → 逐字正確 **{100*(1-N/tot_chars):.3f}%**')
    w('* 對照 `docs/decisions/0008` §D：73,756 字 / 95.773% / 3,118 錯字')
    w(f'* 差異 +{tot_chars-73756} 字、+{N-3118} 錯字、'
      f'{100*(1-N/tot_chars)-95.773:+.3f}pp')
    w('\n**這是 observed，不是 inferred。** 每一個錯字都是逐字比對出來的位置。\n')

    # ── 孤立 vs 連鎖 ──
    iso = [e for e in errs if e['run_len'] == 1]
    w('\n## 孤立單字錯 vs 連鎖錯\n')
    w('| 連續錯字段長度 | 錯字數 | 佔 D2 |')
    w('|---|---|---|')
    rl = collections.Counter(e['run_len'] for e in errs)
    for k in sorted(rl):
        lbl = '**1（孤立）**' if k == 1 else (f'{k}' if k < 6 else f'{k}')
        if k <= 5:
            w(f'| {lbl} | {rl[k]:,} | {rl[k]/N:.1%} |')
    big = sum(v for k, v in rl.items() if k > 5)
    if big:
        w(f'| ≥6 | {big:,} | {big/N:.1%} |')
    w(f'\n孤立單字錯 **S = {len(iso):,}**（佔 D2 {len(iso)/N:.1%}）；'
      f'連鎖錯 {N-len(iso):,}（{1-len(iso)/N:.1%}）。')

    # ── 候選覆蓋 ──
    w('\n\n## 候選覆蓋（金標在不在該節點的候選裡）\n')
    w('| | 金標在候選 | 金標不在候選 | 合計 |')
    w('|---|---|---|---|')
    for lbl, sub in (('孤立單字錯', iso), ('連鎖錯', [e for e in errs if e['run_len'] > 1]),
                     ('**全部**', errs)):
        a = sum(1 for e in sub if e['gold_in_cands'])
        w(f'| {lbl} | {a:,}（{a/len(sub):.1%}）| {len(sub)-a:,} | {len(sub):,} |')

    C = [e for e in iso if e['gold_in_cands']]
    w(f'\n### 核心 KPI\n')
    w(f'* N（D2 全部錯字）= **{N:,}**')
    w(f'* S（孤立單字錯）= **{len(iso):,}**')
    w(f'* C（孤立單字錯 ∧ 金標在候選）= **{len(C):,}**')
    w(f'* **C / N = {len(C)/N:.1%}**')
    w(f'* C / S = {len(C)/len(iso):.1%}')

    # ── 三軸矩陣 ──
    w('\n\n## 三軸矩陣（六組？ × 孤立？ × 金標在候選？）\n')
    w('| 是否六組 | 候選 | 孤立單字錯 | 連鎖／多字 | 合計 |')
    w('|---|---|---|---|---|')
    for six in (True, False):
        for gic in (True, False):
            a = sum(1 for e in errs if (e['gold'] in SIX_CHARS) == six
                    and e['gold_in_cands'] == gic and e['run_len'] == 1)
            b = sum(1 for e in errs if (e['gold'] in SIX_CHARS) == six
                    and e['gold_in_cands'] == gic and e['run_len'] > 1)
            w(f'| {"六組內" if six else "六組外"} | '
              f'{"金標在候選" if gic else "金標不在候選"} | {a:,} | {b:,} | {a+b:,} |')

    # ── 八分類 ──
    w('\n\n## 八分類錯誤家族（互斥，先命中先算）\n')
    fam = collections.Counter(family(e) for e in errs)
    famiso = collections.Counter(family(e) for e in iso)
    w('| 家族 | 錯字數 | 佔 D2 | 其中孤立 | Node 層可觸及？ |')
    w('|---|---|---|---|---|')
    reach = {'1 已知六組·單字·金標在候選': '✅ 是（1＋2 級）',
             '2 單字節點·金標在候選（六組以外）': '✅ 是（1＋2 級）',
             '4 多字節點·金標在候選': '⚠️ 候選可及，但要整個詞換掉',
             '3 單字節點·金標不在候選': '❌ 否（候選內沒有正解）',
             '5 多字節點·金標不在候選': '❌ 否',
             '6 lattice：該節點只有一個候選': '❌ 否（詞庫／lattice 問題）'}
    for k in sorted(fam):
        w(f'| {k} | {fam[k]:,} | {fam[k]/N:.1%} | {famiso.get(k,0):,} | {reach[k]} |')

    # ── 六組內外 ──
    w('\n\n## 六組內 vs 六組外\n')
    inn = [e for e in errs if e['gold'] in SIX_CHARS]
    outn = [e for e in errs if e['gold'] not in SIX_CHARS]
    tgt = [e for e in errs if e['is_target']]
    w('| 切面 | 錯字數 | 佔 D2 | 孤立 | 孤立∧金標在候選 |')
    w('|---|---|---|---|---|')
    for lbl, sub in (('六組字（任何位置）', inn), ('**六組以外的字**', outn),
                     ('題庫指定的目標位置', tgt)):
        i2 = [e for e in sub if e['run_len'] == 1]
        c2 = [e for e in i2 if e['gold_in_cands']]
        w(f'| {lbl} | {len(sub):,} | {len(sub)/N:.1%} | {len(i2):,} | '
          f'**{len(c2):,}**（佔 D2 {len(c2)/N:.1%}）|')

    # ── Top 30 ──
    w('\n\n## Top 20 金標字（依錯字數）\n')
    w('| 金標 | 錯字數 | 佔 D2 | 孤立 | 金標在候選 | 孤立∧在候選 | 六組？ |')
    w('|---|---|---|---|---|---|---|')
    for ch, n in collections.Counter(e['gold'] for e in errs).most_common(20):
        sub = [e for e in errs if e['gold'] == ch]
        i2 = [e for e in sub if e['run_len'] == 1]
        c2 = [e for e in i2 if e['gold_in_cands']]
        w(f'| {ch} | {n} | {n/N:.2%} | {len(i2)} | '
          f'{sum(1 for e in sub if e["gold_in_cands"])} | **{len(c2)}** | '
          f'{"✅" if ch in SIX_CHARS else ""} |')

    w('\n\n## Top 20 引擎→金標方向\n')
    w('| 引擎選 → 金標 | 錯字數 | 佔 D2 | 孤立∧在候選 | 同讀音？ |')
    w('|---|---|---|---|---|')
    d = collections.Counter((e['chosen'], e['gold']) for e in errs)
    for (c, g), n in d.most_common(20):
        sub = [e for e in errs if e['chosen'] == c and e['gold'] == g]
        c2 = sum(1 for e in sub if e['run_len'] == 1 and e['gold_in_cands'])
        same = sum(1 for e in sub if e['span'] == 1)
        w(f'| {c} → {g} | {n} | {n/N:.2%} | **{c2}** | {same}/{n} 單字節點 |')

    # ── 節點 span / 候選數 ──
    w('\n\n## 節點 span 與候選數\n')
    w('| 節點 span | 錯字數 | 佔 D2 | 金標在候選 |')
    w('|---|---|---|---|')
    for s in sorted(collections.Counter(e['span'] for e in errs)):
        sub = [e for e in errs if e['span'] == s]
        if len(sub) < 5 and s > 4:
            continue
        w(f'| {s} | {len(sub):,} | {len(sub)/N:.1%} | '
          f'{sum(1 for e in sub if e["gold_in_cands"])/len(sub):.1%} |')
    w('\n金標在候選時的名次分布（offline-only 欄位，僅供診斷）：\n')
    w('| gold_rank | 錯字數 | 佔「金標在候選」 |')
    w('|---|---|---|')
    gi = [e for e in errs if e['gold_in_cands']]
    rk = collections.Counter(min(e['gold_rank'], 10) for e in gi)
    for k in sorted(rk):
        lbl = f'{k}' if k < 10 else '≥10'
        w(f'| {lbl} | {rk[k]:,} | {rk[k]/len(gi):.1%} |')

    # ── domain ──
    w('\n\n## 語料組成（corpus-level evidence，非 production traffic）\n')
    w('| domain | 句數 | 錯字 | 佔 D2 | 孤立∧在候選 佔該 domain |')
    w('|---|---|---|---|---|')
    dm = collections.Counter(e['domain'] for e in errs)
    sdm = collections.Counter(m.get('domain', '') for m in meta.values())
    for k, n in dm.most_common():
        sub = [e for e in errs if e['domain'] == k]
        c2 = sum(1 for e in sub if e['run_len'] == 1 and e['gold_in_cands'])
        w(f'| {k} | {sdm.get(k,0):,} | {n:,} | {n/N:.1%} | {c2/n:.1%} |')

    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out_lines) + '\n')
    print('\n'.join(out_lines))


if __name__ == '__main__':
    main()
