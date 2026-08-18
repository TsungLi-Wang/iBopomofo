import sys, hashlib, statistics
sys.path.insert(0,'Source/Engine/eval')
from audit_path_score_symmetric_damage import load, counterfactual, summarize, fold, K
M='/private/tmp/claude-501/-Users-johnny-w-macmini/cea89cfe-14e5-4c59-af23-b4c9950bc97e/scratchpad/m'
sents=load(M+'/paths-all.tsv')
TOT=74649
cur=sum(next(p['n_err'] for p in ps if p['is_walk']) for ps in sents.values())

def cf(alpha,nu):
    """固定 top-10 清單上的反事實：score = α·unigram + PMI + ν·rnn。
    ⚠️ 清單本身是在 α=1 之下產生的 —— α≠1 只在清單內重排，
    不代表真的改權重會得到同一批候選。"""
    out={}
    for sid,ps in sents.items():
        key=lambda p: alpha*p['unigram_sum']+p['pmi']+nu*p['rnn']
        best=max(ps,key=key); c=next(p for p in ps if p['is_walk'])
        out[sid]=(c['n_err'],best['n_err'])
    return out
def agg(o):
    r=sum(max(0,a-b) for a,b in o.values()); d=sum(max(0,b-a) for a,b in o.values())
    return r,d,r-d
folds={s:fold(s) for s in sents}
def xfit(grid,make):
    pre={g:make(g) for g in grid}
    R=D=0; picks=[]
    for k in range(K):
        tr=[s for s in sents if folds[s]!=k]; te=[s for s in sents if folds[s]==k]
        bg=max(grid,key=lambda g: sum(pre[g][s][0]-pre[g][s][1] for s in tr))
        r=sum(max(0,pre[bg][s][0]-pre[bg][s][1]) for s in te)
        d=sum(max(0,pre[bg][s][1]-pre[bg][s][0]) for s in te)
        R+=r; D+=d; picks.append(bg)
    return R,D,R-D,picks

print('## 密網格：ν′ 在 0.75–1.25 之間有沒有「安全區」\n')
print('| ν′ | 救 | 壞 | 淨 | precision |')
print('|---|---|---|---|---|')
for nu in [0.75,0.80,0.85,0.90,0.95,1.00,1.10,1.25]:
    o=cf(1.0,nu); r,d,n=agg(o)
    p=f'{r/(r+d):.3f}' if r+d else '—'
    print(f'| {nu:.2f} | {r} | {d} | **{n:+d}** | {p} |')
print('\n→ 沒有「damage 幾乎不動而 rescue 上升」的區段：damage 從 ν′ 一離開 0.75 就同步出現。')

print('\n\n## McNemar：cross-fitted 的淨值是不是雜訊\n')
R,D,N,picks=xfit([x/100 for x in range(0,301,5)], lambda nu: cf(1.0,nu))
chi=(R-D)**2/(R+D) if R+D else 0
import math
pval=math.erfc(math.sqrt(chi/2))
print(f'cross-fitted：救 {R}、壞 {D}、淨 **{N:+d}** 字；'
      f'McNemar χ²={chi:.1f}，p≈{pval:.1e}')
print(f'換算：字級正確率 {100*(1-cur/TOT):.3f}% → {100*(1-(cur-N)/TOT):.3f}%'
      f'（**+{100*N/TOT:.3f}pp**）；佔 D2 {N/cur:+.1%}')

print('\n\n## 2-D 反事實：壓低詞頻先驗權重 α（`COUNTERFACTUAL`，清單固定於 α=1）\n')
print('| α | 最佳 ν′（naive）| 救 | 壞 | 淨 |')
print('|---|---|---|---|---|')
nug=[x/100 for x in range(0,301,5)]
for a in (1.0,0.9,0.8,0.7,0.6,0.5):
    best=max(nug,key=lambda nu: agg(cf(a,nu))[2])
    r,d,n=agg(cf(a,best))
    print(f'| {a:.1f} | {best:.2f} | {r} | {d} | **{n:+d}** |')
print('\n（naive，同一份語料掃出；不得當 production 建議。）')
Ra,Da,Na,pk=xfit([(a,nu) for a in (1.0,0.9,0.8,0.7,0.6,0.5) for nu in nug],
                 lambda g: cf(g[0],g[1]))
print(f'\n**CROSS-FITTED（同時掃 α 與 ν′）**：救 {Ra}、壞 {Da}、淨 **{Na:+d}** 字'
      f'（佔 D2 {Na/cur:+.1%}、字級 +{100*Na/TOT:.3f}pp）')
print(f'逐 fold 選出的 (α, ν′)：'+'、'.join(f'({a:.1f},{n:.2f})' for a,n in pk))
print(f'\n對照：只掃 ν′ 的 cross-fitted 淨 {N:+d} 字。'
      f'多掃一個維度只多 {Na-N:+d} 字 —— 詞頻權重不是缺口所在。')
