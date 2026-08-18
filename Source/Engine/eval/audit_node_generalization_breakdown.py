import sys, json, collections, math
sys.path.insert(0,'Source/Engine/eval')
import numpy as np
from audit_representation import roc_auc, pr_auc, boot_ci
from audit_node_generalization import FAMILIES, prec_at_override, VARIANTS, MIN_DIR_N
M='/private/tmp/claude-501/-Users-johnny-w-macmini/cea89cfe-14e5-4c59-af23-b4c9950bc97e/scratchpad/m'
S=np.load(M+'/gen.md.scores.npy'); R=json.load(open(M+'/gen.md.rows.json',encoding='utf-8'))
names=list(FAMILIES)
sc={n:S[i] for i,n in enumerate(names)}
y=np.array([r['label'] for r in R]); docs=[r['doc'] for r in R]
ENG='ENG 引擎側數值（字元無關）'
print(f'節點 {len(R):,}　正例 {y.sum():,}（{y.mean():.2%}）\n')

print('## Precision at fixed override rate\n')
print('| 特徵族 | @10% | @20% | @30% | 基準線（隨機＝正例率）|')
print('|---|---|---|---|---|')
for n in names:
    cells=[f'{prec_at_override(sc[n],y,f)[0]:.3f}' for f in (0.10,0.20,0.30)]
    print(f'| {n} | '+' | '.join(cells)+f' | {y.mean():.3f} |')

print('\n\n## 單一特徵基準線（最簡可能的排序器）\n')
print('| 基準線 | ROC-AUC | 說明 |')
print('|---|---|---|')
# chosen_rank 單獨（從 rows 沒存，改用 ENG 的替代：用 n_cands 當 sanity）
print(f'| 全零（隨機）| 0.500 | 下限 |')
print(f'| CTX 上下文字元 ±6（＝⑭-H 的 A-walk 表徵）| {roc_auc(list(sc["CTX 上下文字元 ±6"]),list(y)):.3f} | Baseline 2 |')
print(f'| FULL（＝⑭-I 的 I2 式表徵）| {roc_auc(list(sc["**FULL（＋候選條件化字對）**"]),list(y)):.3f} | Baseline 3 |')
print(f'| **ENG（本棒）** | **{roc_auc(list(sc[ENG]),list(y)):.3f}** | 字元無關數值 |')

print('\n\n## Top-direction contribution：拿掉高頻方向後還在不在\n')
dc=collections.Counter(r['direction'] for r in R if r['label']==1)
top=[d for d,_ in dc.most_common()]
print('| 移除 | 剩餘節點 | 剩餘正例 | ENG AUC | 95% CI |')
print('|---|---|---|---|---|')
for k in (0,10,25,50,100):
    rm=set(top[:k])
    idx=[i for i,r in enumerate(R) if r['direction'] not in rm]
    yy=[y[i] for i in idx]; ss=[sc[ENG][i] for i in idx]; dd=[docs[i] for i in idx]
    lo,hi=boot_ci(ss,yy,dd,n=300)
    print(f'| 前 {k} 個方向 | {len(idx):,} | {sum(yy):,} | **{roc_auc(ss,yy):.3f}** | [{lo:.3f}, {hi:.3f}] |')
# 單一方向家族貢獻
print('\n單一方向對正例的最大佔比：', end='')
tot=y.sum()
print(f'{dc.most_common(1)[0][0]} {dc.most_common(1)[0][1]}／{tot} = {dc.most_common(1)[0][1]/tot:.1%}')

print('\n\n## 逐方向 AUC（n ≥ %d 的 held-out 方向）\n' % MIN_DIR_N)
print('| 方向 | 正例 n | 該方向節點 | ENG AUC | 變體？ |')
print('|---|---|---|---|---|')
usable=[d for d,c in dc.most_common() if c>=MIN_DIR_N]
rows_by_dir=collections.defaultdict(list)
for i,r in enumerate(R): rows_by_dir[r['direction']].append(i)
# 每個方向的 AUC：該方向的正例 vs 同一 engine 字的對角線負例
for d in usable:
    a,b=d.split('→')
    pos=[i for i in rows_by_dir[d] if y[i]==1]
    neg=[i for i in rows_by_dir.get(f'{a}→{a}',[]) if y[i]==0]
    if len(pos)<MIN_DIR_N or len(neg)<10:
        print(f'| {d} | {len(pos)} | — | INSUFFICIENT POWER（負例 {len(neg)}）| |'); continue
    ss=[sc[ENG][i] for i in pos+neg]; yy=[1]*len(pos)+[0]*len(neg)
    v='✅' if (a,b) in VARIANTS else ''
    print(f'| {d} | {len(pos)} | +{len(neg)} 對角負例 | **{roc_auc(ss,yy):.3f}** | {v} |')

print('\n\n## 長尾：依方向在語料中的出現頻次分桶\n')
print('| 該方向的正例數 | 方向數 | 正例合計 | ENG AUC（對同 engine 字的對角負例）|')
print('|---|---|---|---|')
for lo_,hi_,lbl in ((1,1,'1（只出現一次）'),(2,3,'2–3'),(4,9,'4–9'),(10,29,'10–29'),(30,10**9,'≥30')):
    ds=[d for d,c in dc.items() if lo_<=c<=hi_]
    pos=[i for d in ds for i in rows_by_dir[d] if y[i]==1]
    neg=[]
    for d in ds:
        a=d.split('→')[0]
        neg+=[i for i in rows_by_dir.get(f'{a}→{a}',[]) if y[i]==0]
    neg=list(dict.fromkeys(neg))
    if len(pos)<10 or len(neg)<10:
        print(f'| {lbl} | {len(ds)} | {len(pos)} | INSUFFICIENT |'); continue
    ss=[sc[ENG][i] for i in pos+neg]; yy=[1]*len(pos)+[0]*len(neg)
    print(f'| {lbl} | {len(ds)} | {len(pos)} | **{roc_auc(ss,yy):.3f}** |')

print('\n\n## 正字法／風格變體敏感度\n')
print('| 子集 | 節點 | 正例 | ENG AUC | 95% CI |')
print('|---|---|---|---|---|')
for lbl,keep in (('全部',lambda r:True),('**排除變體**',lambda r: not r['variant'])):
    idx=[i for i,r in enumerate(R) if keep(r)]
    yy=[y[i] for i in idx]; ss=[sc[ENG][i] for i in idx]; dd=[docs[i] for i in idx]
    lo,hi=boot_ci(ss,yy,dd,n=300)
    print(f'| {lbl} | {len(idx):,} | {sum(yy):,} | **{roc_auc(ss,yy):.3f}** | [{lo:.3f}, {hi:.3f}] |')
v=[i for i,r in enumerate(R) if r['variant']]
print(f'\n變體節點 {len(v):,}，其中正例 {sum(y[i] for i in v):,}。')

print('\n\n## 其他切面（ENG）\n')
print('| 切面 | 節點 | 正例 | ENG AUC |')
print('|---|---|---|---|')
for lbl,f in (('候選數 2–4',lambda r:r['n_cands']<=4),('候選數 5–9',lambda r:5<=r['n_cands']<=9),
              ('候選數 ≥10',lambda r:r['n_cands']>=10),
              ('domain ptt-natural',lambda r:r['domain']=='ptt-natural'),
              ('domain ptt-minor',lambda r:r['domain']=='ptt-minor')):
    idx=[i for i,r in enumerate(R) if f(R[i])]
    yy=[y[i] for i in idx]; ss=[sc[ENG][i] for i in idx]
    if not (0<sum(yy)<len(yy)): print(f'| {lbl} | {len(idx)} | {sum(yy)} | INSUFFICIENT |'); continue
    print(f'| {lbl} | {len(idx):,} | {sum(yy):,} | **{roc_auc(ss,yy):.3f}** |')
