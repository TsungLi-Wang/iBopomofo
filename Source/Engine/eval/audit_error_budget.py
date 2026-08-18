#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棒⑭-L：系統錯誤預算與 ROI 盤點。

**不訓練、不讀模型、不跑引擎、不碰 production。**
只把既有已凍結報告裡的數字放進同一個分母體系，讓「某個機制值多少」可以互相比較。

所有輸入都在 `FROZEN` 裡，每一筆標明出處檔案與節次。本檔不產生新的實驗結果，
只做除法；任何「這是估計、不是實測」的地方都在輸出裡標出來。

用法：python3 audit_error_budget.py
"""

# ── 凍結輸入：全部來自既有報告，不得在此改寫 ────────────────────────────────
FROZEN = {
    # real-corpus-error-layers.md §一（自然驗證集 PTT，5,976 題，全部 heldout）
    'natural_items': 5976,
    'natural_acc': 0.922,          # 現況（含規則）
    'natural_O1': 0.973,           # 十條路徑內改選
    'natural_O2': 0.990,           # 節點內改選
    'natural_O3': 0.977,           # 兩百條路徑
    # real-corpus-error-layers.md §二（分類表，先命中先算 → 互斥）
    'natural_classes': [
        ('整句解碼錯', 209), ('神經模型偏', 148), ('上下文不足', 58),
        ('候選沒進來', 13), ('斷詞錯', 7), ('頻率先驗壓制', 2),
        ('規則誤開火', 0),
    ],
    # real-corpus-error-layers.md §二 逐組（只列了各組前二～三大類）
    'natural_groups': {
        # 組: (題數, 現況, O1, O2, 分類到的錯誤數, 整句解碼, 神經模型偏)
        '作做坐座': (1308, 0.849, 0.935, 0.986, 186, 80, 57),
        '在再':     (1024, 0.896, 0.975, 0.985, 101, 43, 46),
        '吧八巴':   (1307, 0.960, 0.990, 0.995,  52, 34, 13),
        '較叫':     ( 586, 0.920, 0.973, 0.978,  47, 28, 15),
        '前錢':     (1031, 0.963, 0.991, 0.994,  37, 20, 11),
        '的得':     ( 720, 0.964, 0.985, 0.999,  14,  4,  6),
    },
    # 0008 §D 整句逐字正確率（對真人原文）—— 這是唯一的「全語料字級」分母
    'natural_chars': 73756,
    'natural_char_acc': 0.95773,
    'x_chars': 33665,
    'x_char_acc': 0.97297,
    # X 驗證集
    'x_items': 2678, 'x_acc': 0.963, 'x_classified': 84,
    # node-expert-feasibility.md（棒⑭-K，凍結）
    'k_cross_fitted_net': 0.0027,      # audited dev 上的 cross-fitted net
    'k_ci': (0.0003, 0.0056),
    'k_envelope': 0.0059,
    'k_group_ceiling': 0.1110,         # p_err，作做坐座組內理論上限
    'k_capture': 0.024,                # cross-fitted / group ceiling
    'k_node_reachable': 106,           # 186 − 80（整句解碼錯不可觸及）
}


def pct(x):
    return f'{100 * x:.1f}%'


def main():
    F = FROZEN
    N, acc = F['natural_items'], F['natural_acc']
    obs_err = round(N * (1 - acc))
    clf = sum(n for _, n in F['natural_classes'])
    ch_err = round(F['natural_chars'] * (1 - F['natural_char_acc']))
    x_ch_err = round(F['x_chars'] * (1 - F['x_char_acc']))

    print('# 三個分母，不可互換\n')
    print('| 分母 | 定義 | 大小 | 出處 |')
    print('|---|---|---|---|')
    print(f'| **D1 六組目標字錯誤** | 自然驗證集 {N:,} 題，只看每題那一個目標字 '
          f'| **{obs_err}** | real-corpus-error-layers §一（{acc:.1%}）|')
    print(f'| D1′ 其中已分類 | 分類表合計（互斥） | {clf} '
          f'（佔 D1 {clf/obs_err:.1%}，未分類 {obs_err-clf}）| 同上 §二 |')
    print(f'| **D2 全語料字級錯誤** | 同一批句子 {F["natural_chars"]:,} 字，'
          f'逐字對真人原文 | **{ch_err:,}** | 0008 §D（{F["natural_char_acc"]:.3%}）|')
    print(f'| D3 X 驗證集字級錯誤 | {F["x_chars"]:,} 字 | {x_ch_err:,} '
          f'| 0008 §D（{F["x_char_acc"]:.3%}）|')
    print(f'\n**D1 只佔 D2 的 {obs_err/ch_err:.1%}。** '
          f'六組以外的 {ch_err-obs_err:,} 個錯字（{1-obs_err/ch_err:.1%}）'
          f'**從未被任何既有報告分類過**。\n')

    print('\n# 錯誤預算（D1′ = 已分類的 437 個六組目標字錯誤）\n')
    print('| 錯誤類別 | 數量 | 佔 D1′ | 佔 D1 | 佔 D2 | Node Expert 可觸及？ |')
    print('|---|---|---|---|---|---|')
    reach = {'整句解碼錯': '❌ 不可觸及（定義上目標字以外也錯）',
             '神經模型偏': '✅ 可觸及（正解在節點候選內）',
             '上下文不足': '✅ 可觸及（正解在節點內、分數差不大）',
             '候選沒進來': '❌ 不可觸及（搜尋問題，正解不在候選）',
             '斷詞錯': '❌ 不可觸及（正解不在當前斷詞的節點內）',
             '頻率先驗壓制': '✅ 可觸及',
             '規則誤開火': '—（本語料 0 例）'}
    for name, n in F['natural_classes']:
        print(f'| {name} | {n} | {n/clf:.1%} | {n/obs_err:.1%} | {n/ch_err:.1%} '
              f'| {reach[name]} |')
    print(f'| *未分類* | {obs_err-clf} | — | {(obs_err-clf)/obs_err:.1%} '
          f'| {(obs_err-clf)/ch_err:.1%} | 不知道 |')
    print(f'| *六組以外的字* | {ch_err-obs_err:,} | — | — '
          f'| **{(ch_err-obs_err)/ch_err:.1%}** | **從未分類** |')

    ok = sum(n for k, n in F['natural_classes'] if reach[k].startswith('✅'))
    print(f'\nNode Expert 原則上可觸及者合計 **{ok}**'
          f'（佔 D1′ {ok/clf:.1%}、佔 D2 {ok/ch_err:.1%}）—— '
          f'這是**全六組**的上限，且假設一個完美的節點專家對六組全部出手。')

    print('\n\n# 逐組：錯誤池、天花板、可觸及\n')
    print('| 組 | 題數 | 現況 | O1 路徑層 | O2 節點層 | 觀察錯誤 | 已分類 | '
          '整句解碼（不可觸及） | 非整句解碼（可觸及上界） | O2−現況 |')
    print('|---|---|---|---|---|---|---|---|---|---|')
    for g, (n, a, o1, o2, c, ws, nb) in F['natural_groups'].items():
        oe = round(n * (1 - a))
        print(f'| {g} | {n:,} | {a:.1%} | {o1:.1%} | {o2:.1%} | {oe} | {c} '
              f'| {ws}（{ws/c:.0%}）| **{c-ws}** | +{100*(o2-a):.1f}pp |')

    print('\n\n# Node Expert 放回三個分母\n')
    print('| 指標 | 值 | 定義／分母 |')
    print('|---|---|---|')
    print(f'| cross-fitted net | **+{100*F["k_cross_fitted_net"]:.2f}%** '
          f'（CI [{100*F["k_ci"][0]:+.2f}, {100*F["k_ci"][1]:+.2f}]）'
          f'| audited dev 的 6,253 節點母體上，每個作做坐座節點的期望淨改善 |')
    print(f'| 組內理論上限 | +{100*F["k_group_ceiling"]:.2f}% '
          f'| 同上母體，全救回零誤傷 |')
    print(f'| 捕獲率 | {100*F["k_capture"]:.1f}% | cross-fitted ÷ 組內上限 |')
    nr = F['k_node_reachable']
    print(f'| 節點層上限（佔 D1′）| {nr/clf:.1%} | {nr}/{clf}，'
          f'作做坐座扣掉整句解碼錯 |')
    sys_d1 = nr / clf * F['k_capture']
    print(f'| **目前系統級貢獻（佔 D1′）** | **{sys_d1:.2%}** '
          f'| {nr/clf:.1%} × {100*F["k_capture"]:.1f}%（⑭-K 報的 ≈0.58%）|')
    print(f'| **同一件事，佔 D2** | **{nr*F["k_capture"]/ch_err:.3%}** '
          f'| 約 {nr*F["k_capture"]:.1f} 個字 ÷ {ch_err:,} 個錯字 |')
    print(f'| 節點層上限（佔 D2）| {nr/ch_err:.1%} | 完美節點專家、只做作做坐座 |')

    print('\n\n# N-best 擴張的邊際報酬\n')
    print('| 路徑數 | 自然驗證集 oracle | 相對現況 |')
    print('|---|---|---|')
    for lbl, v in (('現況', acc), ('O1 = 10 條', F['natural_O1']),
                   ('O3 = 200 條', F['natural_O3'])):
        print(f'| {lbl} | {v:.1%} | {100*(v-acc):+.1f}pp |')
    print(f'\n10 → 200 條只多 {100*(F["natural_O3"]-F["natural_O1"]):+.1f}pp。'
          f'**加大 N-best 這條路已接近耗盡**，剩下的要靠更好的解碼／語言模型本身。')


if __name__ == '__main__':
    main()
