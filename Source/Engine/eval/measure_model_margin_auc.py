#!/usr/bin/env python3
# 棒⑭-K 補充計算：Q3-B 全系統換算所需的「模型自己的 margin AUC」。
# 對照 ⑭-I 的 0.792 —— 那是診斷 LR 餵 I2 式特徵，不是 I2 訓練出來的排序。
import sys, json, collections, math, os
sys.path.insert(0,'Source/Engine/eval')
import numpy as np, torch
from audit_representation import load as load_diag, roc_auc, boot_ci
from train_node_expert import NodeExpert, encode, MAX_CANDS
from eval_model_dev import wilson
W='/Users/johnny.w_macmini/laowang-data/baton13-node-homophone'
B='/Users/johnny.w_macmini/laowang-data/baton14b'
D='/Users/johnny.w_macmini/laowang-data/baton14d'
F='/Users/johnny.w_macmini/laowang-data/baton14f'
I='/Users/johnny.w_macmini/laowang-data/baton14i'
fj=json.load(open(F+'/folds.json',encoding='utf-8'))
rows=load_diag(W+'/data/nodes.tsv',W+'/data/sentences.jsonl','t',fj['assign'])
rows+=load_diag(B+'/partA/ctx-nodes.tsv',B+'/partA/ctx-sentences.jsonl','c',fj['assign'])
seen=set(); ded=[]
for r in rows:
    k=(r['doc'],r['text'],r['pos'])
    if k in seen: continue
    seen.add(k); ded.append(r)
rows=ded
print(f'=== 補查：模型自己的 margin 在 544 診斷集上的 AUC ===')
print(f'診斷集 {len(rows)}（該出手 {sum(r["label"] for r in rows)}）')
for name,ck_dir in (('R4',F),('I2',I+'/i2')):
    for fi in range(5):
        idx=[i for i,r in enumerate(rows) if r['fold']==fi]
        if not idx: continue
        ck=torch.load(f'{ck_dir}/fold{fi}/node-expert.pt',map_location='cpu')
        m=NodeExpert(**ck['cfg']); m.load_state_dict(ck['model']); m.eval()
        ci={c:i for i,c in enumerate(ck['itos'])}; si={s:i for i,s in enumerate(ck['stos'])}
        sub=[]
        for i in idx:
            r=rows[i]
            cd=[(c[0],c[1],c[2],c[3],False) for c in r['cands']][:MAX_CANDS]
            sub.append({'reading':'ㄗㄨㄛˋ','chosen':'作','gold':r['gold'],'cands':cd,
                        'left':r['left'],'right':r['right'],'right_empty':r['right_empty'],
                        'gi':next((k for k,x in enumerate(cd) if x[0]==r['gold']),0)})
        enc=encode(sub,ci,si)
        with torch.no_grad():
            lg=m(torch.from_numpy(enc['left'].astype(np.int64)),torch.from_numpy(enc['right'].astype(np.int64)),
                 torch.from_numpy(enc['syl'].astype(np.int64)),torch.from_numpy(enc['rempty']),
                 torch.from_numpy(enc['cchars'].astype(np.int64)),torch.from_numpy(enc['cfeat']),
                 torch.from_numpy(enc['cmask']))
            lsm=torch.log_softmax(lg.masked_fill(~torch.from_numpy(enc['cmask']),-1e4),dim=-1).numpy()
        for j,i in enumerate(idx):
            chi=next((k for k,c in enumerate(sub[j]['cands']) if c[0]=='作'),0)
            rows[i][name]=float(lsm[j].max()-lsm[j,chi])
    sc=[r[name] for r in rows]; y=[r['label'] for r in rows]; dc=[r['doc'] for r in rows]
    a=roc_auc(sc,y); lo,hi=boot_ci(sc,y,dc,n=500)
    pw=[i for i,r in enumerate(rows) if r['gold'] in ('作','做')]
    apw=roc_auc([sc[i] for i in pw],[1 if rows[i]['gold']=='做' else 0 for i in pw])
    print(f'  {name} 自己的 margin：AUC {a:.3f} [{lo:.3f}, {hi:.3f}]   作→作 vs 作→做 {apw:.3f}')
print('  （對照 ⑭-I：診斷 LR 用 I2 式特徵是 0.792；那是「特徵含多少資訊」，')
print('    這裡是「I2 訓練出來的排序實際多好」——兩者不同）')
