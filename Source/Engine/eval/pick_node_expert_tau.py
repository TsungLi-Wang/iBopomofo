#!/usr/bin/env python3
# 在**抽取資料自己切出來的 held-out** 上定棄權門檻 τ。
#
# ## 為什麼一定要在這裡定
#
# 在兩份 i注音真實語料上掃 τ、挑最高的報出去，就是 docs/dead-ends.md B 節那條
# 「同一份資料選參數又報成績」—— 那個錯誤在這個專案換皮出現過五次，
# 同一機制數字差三倍。所以：**τ 在這支定，定完就不准再動**，然後拿去真實語料
# 量一次就算數。
#
# ## 這支模擬的是「真的會發生什麼事」
#
# 只看 dev 裡**開火白名單命中**的節點（預設 ㄗㄨㄛˋ），對每個 τ 數：
#   救 = 引擎選錯、專家改成金標
#   壞 = 引擎選對、專家改掉
#   多餘出手 = 引擎選錯、專家也改錯（改成第三個字）
# 淨 = 救 − 壞。出手精準率 = 救 /（救＋壞＋多餘出手）。
#
# 挑 τ 的原則寫死在這裡：**先要精準，再要量**。改錯的代價不對稱 ——
# 把使用者本來對的字改掉，比什麼都不做糟得多（六組同音規則就是這樣翻車的）。

import argparse
import collections
import json
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_node_expert import (NodeExpert, encode, load_rows,  # noqa: E402
                               load_split_override)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--ckpt', required=True)
    ap.add_argument('--readings', default='ㄗㄨㄛˋ',
                    help='開火白名單，逗號分隔（與引擎端預設相同）')
    ap.add_argument('--taus', default='0,0.5,1,1.5,2,3,4,5,6,8,10')
    ap.add_argument('--min-precision', type=float, default=0.75,
                    help='低於這個出手精準率的 τ 一律不考慮')
    ap.add_argument('--sentences', default='',
                    help='與訓練時同一份、同一個 dev-frac，否則 τ 是在模型看過的資料上定的')
    ap.add_argument('--dev-frac', type=float, default=0.20)
    ap.add_argument('--out', default='')
    args = ap.parse_args()

    ck = torch.load(args.ckpt, map_location='cpu')
    itos, stos = ck['itos'], ck['stos']
    model = NodeExpert(**ck['cfg'])
    model.load_state_dict(ck['model'])
    model.eval()

    sid_split = (load_split_override(args.sentences, args.dev_frac)
                 if args.sentences else None)
    rows, stats, _, _ = load_rows(args.nodes, itos, stos, args, sid_split)
    fire = {r for r in args.readings.split(',') if r}
    dev = [r for r in rows
           if r['split'] == 'dev' and (set(r['reading'].split('-')) & fire)]
    if not dev:
        sys.exit('dev 裡沒有白名單讀音的節點 —— 無法定 τ')
    print(f'dev 白名單節點 {len(dev):,} 個'
          f'（引擎選對 {sum(1 for r in dev if not r["hard"]):,}、'
          f'選錯 {sum(1 for r in dev if r["hard"]):,}）')

    ci = {c: i for i, c in enumerate(itos)}
    si = {s: i for i, s in enumerate(stos)}
    enc = encode(dev, ci, si)
    with torch.no_grad():
        logits = model(
            torch.from_numpy(enc['left'].astype(np.int64)),
            torch.from_numpy(enc['right'].astype(np.int64)),
            torch.from_numpy(enc['syl'].astype(np.int64)),
            torch.from_numpy(enc['rempty']),
            torch.from_numpy(enc['cchars'].astype(np.int64)),
            torch.from_numpy(enc['cfeat']),
            torch.from_numpy(enc['cmask']))
        lsm = torch.log_softmax(logits.masked_fill(
            ~torch.from_numpy(enc['cmask']), -1e4), dim=-1).numpy()

    chosen_idx = np.array(
        [next((k for k, c in enumerate(r['cands']) if c[0] == r['chosen']), -1)
         for r in dev])
    gold_idx = enc['gold']
    best = lsm.argmax(1)
    margin = lsm[np.arange(len(dev)), best] - lsm[np.arange(len(dev)),
                                                  np.clip(chosen_idx, 0, None)]
    valid = chosen_idx >= 0

    table = []
    for tau in [float(t) for t in args.taus.split(',')]:
        fired = valid & (best != chosen_idx) & (margin > tau)
        saved = int((fired & (chosen_idx != gold_idx) & (best == gold_idx)).sum())
        broke = int((fired & (chosen_idx == gold_idx)).sum())
        wasted = int((fired & (chosen_idx != gold_idx) &
                      (best != gold_idx)).sum())
        n_fire = saved + broke + wasted
        prec = saved / n_fire if n_fire else 0.0
        table.append(dict(tau=tau, fired=n_fire, saved=saved, broke=broke,
                          wasted=wasted, net=saved - broke,
                          precision=round(prec, 3)))

    print(f'\n{"τ":>5} {"出手":>6} {"救":>5} {"壞":>5} {"多餘":>5} '
          f'{"淨":>6} {"出手精準率":>9}')
    for t in table:
        print(f'{t["tau"]:>5} {t["fired"]:>6} {t["saved"]:>5} {t["broke"]:>5} '
              f'{t["wasted"]:>5} {t["net"]:>+6} {t["precision"]:>9.3f}')

    ok = [t for t in table if t['precision'] >= args.min_precision
          and t['fired'] > 0]
    if not ok:
        print(f'\n❌ 沒有 τ 的出手精準率達到 {args.min_precision}。'
              f'\n   這顆模型在這一組上不夠準，**不要**降門檻硬上 ——'
              f'\n   降到「勉強不虧」正是六組同音規則翻車的做法。')
        chosen = None
    else:
        chosen = max(ok, key=lambda t: (t['net'], t['precision']))
        print(f'\n✅ 選 τ = {chosen["tau"]}'
              f'（淨 {chosen["net"]:+d}，出手精準率 {chosen["precision"]:.3f}）'
              f'\n   定完就不准再動。接下來拿去兩份真實語料量**一次**。')

    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            json.dump({'table': table, 'chosen': chosen,
                       'dev_nodes': len(dev),
                       'readings': sorted(fire),
                       'min_precision': args.min_precision}, fh,
                      ensure_ascii=False, indent=2)
        print(f'→ {args.out}')
    if chosen is None:
        sys.exit(1)


if __name__ == '__main__':
    main()
