import sys, json, collections
sys.path.insert(0,'Source/Engine/eval')
import numpy as np
from audit_representation import roc_auc, boot_ci
from audit_node_generalization import FAMILIES
M='/private/tmp/claude-501/-Users-johnny-w-macmini/cea89cfe-14e5-4c59-af23-b4c9950bc97e/scratchpad/m'
S=np.load(M+'/gen.md.scores.npy'); R=json.load(open(M+'/gen.md.rows.json',encoding='utf-8'))
names=list(FAMILIES); sc={n:S[i] for i,n in enumerate(names)}
y=np.array([r['label'] for r in R])
ENG='ENG 引擎側數值（字元無關）'

def cond_auc(score):
    """條件 c-statistic：隨機取一個「引擎選了 A 卻錯」的節點，與一個
    「引擎也選了 A 而且對」的節點，前者分數較高的機率。
    這是出手決策真正面對的比較 —— 總體 AUC 不是。"""
    by=collections.defaultdict(lambda:([],[]))
    for i,r in enumerate(R):
        by[r['chosen']][y[i]].append(score[i])
    num=den=0.0; per={}
    for a,(neg,pos) in by.items():
        if len(pos)<5 or len(neg)<5: continue
        p=np.array(pos); n=np.array(neg)
        wins=(p[:,None]>n[None,:]).sum()+0.5*(p[:,None]==n[None,:]).sum()
        tot=len(p)*len(n)
        per[a]=(wins/tot, len(p), len(n))
        num+=wins; den+=tot
    return num/den, per

print('## 條件 AUC：同一個引擎選字之內\n')
print('總體 AUC 問的是「錯的節點能不能排在對的節點前面」——')
print('但那包含了「不同字的錯誤率本來就不同」這個 base rate。')
print('出手決策面對的是：**引擎已經選了 A，這一個 A 是不是錯的？**\n')
print('| 特徵族 | 總體 AUC | **條件 AUC（同 engine 字內）** | 差 |')
print('|---|---|---|---|')
for n in names:
    a=roc_auc(list(sc[n]),list(y)); c,_=cond_auc(sc[n])
    print(f'| {n} | {a:.3f} | **{c:.3f}** | {c-a:+.3f} |')

c,per=cond_auc(sc[ENG])
print(f'\n**ENG 的條件 AUC = {c:.3f}**（總體 0.758）。\n')
print('### 逐 engine 字（正例 ≥10 者，依正例數排序）\n')
print('| 引擎選字 | 錯 n | 對 n | 條件 AUC | 判讀 |')
print('|---|---|---|---|---|')
for a,(v,np_,nn) in sorted(per.items(),key=lambda x:-x[1][1])[:20]:
    if np_<10: continue
    j='**反向**' if v<0.45 else ('接近隨機' if v<0.55 else '有訊號')
    print(f'| {a} | {np_} | {nn} | **{v:.3f}** | {j} |')
vals=[v for v,p,n in per.values() if p>=10]
print(f'\n正例 ≥10 的引擎字共 {len(vals)} 個：條件 AUC 中位數 **{np.median(vals):.3f}**、'
      f'≥0.60 的有 **{sum(1 for v in vals if v>=0.60)}** 個、'
      f'<0.50 的有 **{sum(1 for v in vals if v<0.50)}** 個。')

print('\n\n### 為什麼總體 AUC 會被撐起來\n')
er=collections.defaultdict(lambda:[0,0])
for i,r in enumerate(R):
    er[r['chosen']][1]+=1; er[r['chosen']][0]+=y[i]
ms=[(sc[ENG][i]) for i in range(len(R))]
rates=np.array([er[r['chosen']][0]/er[r['chosen']][1] for r in R])
print(f'節點的 ENG 分數與「該引擎選字的整體錯誤率」相關係數 = '
      f'**{np.corrcoef(np.array(ms),rates)[0,1]:.3f}**')
print(f'節點的 ENG 分數與 label 相關係數 = {np.corrcoef(np.array(ms),y)[0,1]:.3f}')
print('\n→ 分數主要在分辨「哪些字容易錯」，不是「這一個是不是錯的」。')
