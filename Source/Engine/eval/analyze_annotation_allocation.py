#!/usr/bin/env python3
# 棒⑭-K Q4：人工核驗配置分析。逐層變異數 × 文件叢集 bootstrap 校準的 design effect。
# 不新增任何人工核驗工作，只計算「若要標，該標哪裡、要標多少」。
import sys, json, math
sys.path.insert(0,'Source/Engine/eval')
from calibrate_operating_point import build_rows, score_all, diagonal_cell
from eval_model_dev import load_node_features
D='/Users/johnny.w_macmini/laowang-data/baton14d'; F='/Users/johnny.w_macmini/laowang-data/baton14f'
I='/Users/johnny.w_macmini/laowang-data/baton14i'
meta=json.load(open(D+'/model-dev-meta.json',encoding='utf-8'))['cells']
fj=json.load(open(F+'/folds.json',encoding='utf-8'))
W='/Users/johnny.w_macmini/laowang-data/baton13-node-homophone'
B='/Users/johnny.w_macmini/laowang-data/baton14b'
L=open(D+'/model-dev-audit-annotated.tsv',encoding='utf-8').read().rstrip('\n').split('\n')
h=L[0].split('\t'); ann=[dict(zip(h,x.split('\t'))) for x in L[1:]]
feats=load_node_features([('train-src', W+'/data/nodes.tsv'),('contexts', B+'/partA/ctx-nodes.tsv')])
rows=build_rows(ann, feats, fj['assign'])
det=score_all(rows, I+'/i2')
TAU=1.65; P=0.1110
for r in det: r['fire']= r['changes'] and r['margin']>TAU

def strata(num, den, only_diag):
    per={}
    for c,m in meta.items():
        if only_diag and not diagonal_cell(c): continue
        sub=[r for r in det if r['cell']==c and den(r)]
        if not sub: continue
        per[c]=(sum(1 for r in sub if num(r)), len(sub), m['population'])
    N=sum(v[2] for v in per.values())
    return per, N

perT,NT=strata(lambda r: r['fire'] and r['new']==r['human'], lambda r: r['engine']!=r['human'], False)
perF,NF=strata(lambda r: r['fire'] and r['new']!=r['human'], lambda r: r['engine']==r['human'], True)

def var_side(per,N,extra):
    """extra: {cell: 追加樣本數}。p_h 固定在觀測值，只放大 n_h（受母體上限）。"""
    v=0.0; p=0.0
    for c,(k,nh,Nh) in per.items():
        n=min(nh+extra.get(c,0), Nh); w=Nh/N; ph=k/nh
        p+=w*ph
        f=min(n/Nh,1.0)
        if n>1 and f<1.0: v+=w*w*(1-f)*ph*(1-ph)/(n-1)
    return p, v

pT,vT=var_side(perT,NT,{}); pF,vF=var_side(perF,NF,{})
net=P*pT-(1-P)*pF; sd=math.sqrt(P*P*vT+(1-P)**2*vF)
print(f'對帳：TPR {pT:.4f}　FPR {pF:.4f}　net {net*100:+.2f}%　半寬 ±{1.96*sd*100:.2f}%')
print(f'  → 逐層變異數的半寬 ±{1.96*sd*100:.2f}%，跟核心分析的 CI 一致；')
print(f'    先前用「彙總 p(1−p)/n_eff」算出的 ±0.57% 是低估，已作廢。')
print()
# 各層的邊際變異數貢獻 → Neyman
print('## 變異數來自哪些格（前 8 名）')
print()
print('| 格 | 側 | n | 母體 | p_h | 對 Var(net) 的貢獻 |')
print('|---|---|---|---|---|---|')
contrib=[]
for side,per,N,coef in (('rescue',perT,NT,P),('damage',perF,NF,1-P)):
    for c,(k,nh,Nh) in per.items():
        w=Nh/N; ph=k/nh; f=min(nh/Nh,1.0)
        cv=coef*coef*w*w*(1-f)*ph*(1-ph)/(nh-1) if nh>1 and f<1 else 0.0
        contrib.append((cv,c,side,nh,Nh,ph))
contrib.sort(reverse=True)
tot=sum(c[0] for c in contrib)
for cv,c,side,nh,Nh,ph in contrib[:8]:
    print(f'| {c} | {side} | {nh} | {Nh} | {ph:.3f} | {cv/tot*100:.1f}% |')
print()
def hw(extra): 
    a,va=var_side(perT,NT,extra); b,vb=var_side(perF,NF,extra)
    return 1.96*math.sqrt(P*P*va+(1-P)**2*vb)*100
def alloc(add, mode):
    e={}
    if mode=='now':
        base={c:v[1] for c,v in list(perT.items())+list(perF.items())}
    elif mode=='pop':
        base={c:v[2] for c,v in list(perT.items())+list(perF.items())}
    elif mode=='ney':   # ∝ W_h·sd_h·coef，且只給還有母體餘裕的格
        base={}
        for cv,c,side,nh,Nh,ph in contrib:
            coef=P if side=='rescue' else 1-P
            N=NT if side=='rescue' else NF
            base[c]=coef*(Nh/N)*math.sqrt(max(ph*(1-ph),1e-6))
    else:  # uniform
        base={c:1.0 for c,v in list(perT.items())+list(perF.items())}
    s=sum(base.values())
    for c,b in base.items(): e[c]=int(add*b/s)
    return e
print('## 加標註的四種配置（逐層變異數，p_h 固定在觀測值）')
print()
print('| 新增標註 | 目前比例 | 均勻 | 按母體 | **Neyman** |')
print('|---|---|---|---|---|')
for add in (500,1000,2000,4000):
    print(f'| +{add} | ' + ' | '.join(f'±{hw(alloc(add,m)):.2f}%' for m in ('now','uni','pop','ney')) + ' |')
print()
print('## 反推：達到指定半寬需要多少新增標註（Neyman）')
print()
print('| 目標半寬 | 新增標註 | 工時（4 秒/筆） |')
print('|---|---|---|')
CAP=sum(m['population'] for m in meta.values())-len(det)
for tgt in (2.0,1.5,1.0,0.5):
    ans=None; lo,hi=0,CAP
    while lo<hi:
        mid=(lo+hi)//2
        if hw(alloc(mid,'ney'))<=tgt: hi=mid; ans=mid
        else: lo=mid+1
    if ans is None: print(f'| ±{tgt:.1f}% | **母體不夠**（全庫未標僅 {CAP:,}） | — |')
    else: print(f'| ±{tgt:.1f}% | {ans:,} | {ans*4/3600:.1f} 小時 |')
print()
print(f'（全庫未標節點上限 {CAP:,}；全標完的半寬 ±{hw(alloc(CAP,"ney")):.2f}%）')
