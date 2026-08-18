import sys, json, collections, hashlib
sys.path.insert(0,'Source/Engine/eval')
import numpy as np, torch
from train_path_reranker import load, featurize, train_fold, K, SALT
M='/private/tmp/claude-501/-Users-johnny-w-macmini/cea89cfe-14e5-4c59-af23-b4c9950bc97e/scratchpad/m'
IT='/Users/johnny.w_macmini/Documents/i注音-語料/EX1166-題庫/自然驗證集-真實語料.jsonl'
recs=load(M+'/paths-all.tsv', IT)
for r in recs.values():
    r['X']=featurize(r); r['gold_in']=any(p['is_gold'] for p in r['paths'])
    r['cur']=next(p for p in r['paths'] if p['is_walk'])
per=json.load(open(M+'/rerank.md.per-sentence.json',encoding='utf-8'))
# 每句的「第一個錯字方向」
d1={}
with open(M+'/nbest.tsv',encoding='utf-8') as fh:
    next(fh)
    for line in fh:
        f=line.rstrip('\n').split('\t')
        d1.setdefault(f[0], f'{f[2]}→{f[3]}')
print('## 逐方向：cross-fitted reranker 的 rescue / damage\n')
print('| 首個錯字方向 | 句數 | rescue 字 | damage 字 | net | 判讀 |')
print('|---|---|---|---|---|---|')
byd=collections.defaultdict(lambda:[0,0,0])
for s,v in per.items():
    d=d1.get(s)
    if d is None: continue
    byd[d][0]+=1; byd[d][1]+=max(0,v['cur']-v['new']); byd[d][2]+=max(0,v['new']-v['cur'])
for d,(n,r,dm) in sorted(byd.items(),key=lambda x:-x[1][0])[:12]:
    if n<10:
        print(f'| {d} | {n} | {r} | {dm} | {r-dm:+d} | **INSUFFICIENT POWER** |'); continue
    print(f'| {d} | {n} | {r} | {dm} | **{r-dm:+d}** | {"正" if r>dm else ("負" if r<dm else "持平")} |')
small=[d for d,v in byd.items() if v[0]<10]
sr=sum(byd[d][1] for d in small); sd=sum(byd[d][2] for d in small)
print(f'\n方向共 {len(byd)} 個，其中 {len(small)} 個 n<10 標 **INSUFFICIENT POWER**（保留）；'
      f'它們合計 rescue {sr}、damage {sd}、net {sr-sd:+d}。')
neg=sum(1 for d,v in byd.items() if v[0]>=10 and v[1]<v[2])
tot=sum(1 for d,v in byd.items() if v[0]>=10)
print(f'n≥10 的方向共 {tot} 個，其中 **{neg} 個淨為負**。')

print('\n\n## Direction-held-out diagnostic（同一模型／特徵／objective，只換切分）\n')
print('⑭-N 的失敗模式是「方向記憶」。這裡把切分改成 direction-held-out，')
print('確認 reranker 是不是也只在看過的方向上有效。**不是重新訓練 production**，')
print('也**不用它取代主結果** —— 主結果仍是 document-level 5-fold 的 +53。\n')
def dfold(d): return int(hashlib.sha256(f'baton14s-dir-v1:{d}'.encode()).hexdigest()[:8],16)%K
# ⚠️ 第一版切分是壞的：解對的句子沒有「方向」，全部落進同一個 fold，
# 那個 fold 的訓練集幾乎看不到「不要弄壞正確句」的例子 → damage 爆掉（net −1,715）。
# 正確做法：**只對解錯的句子做 direction-held-out**，
# 解對的句子仍照 document 雜湊分散到各 fold。
for sid,r in recs.items():
    if r['cur']['n_err']>0:
        r['dfold']=dfold(d1.get(sid,'—'))
    else:
        r['dfold']=int(hashlib.sha256(f'baton14s-dir-v1:doc:{r["doc"]}'.encode()).hexdigest()[:8],16)%K
trainable=[r for r in recs.values() if r['gold_in']]
d=next(iter(recs.values()))['X'].shape[1]
res=collections.defaultdict(int)
for k in range(K):
    tr=[r for r in trainable if r['dfold']!=k]
    te=[r for r in recs.values() if r['dfold']==k]
    if not tr or not te: continue
    X=np.concatenate([r['X'] for r in tr],axis=0); mu,sd=X.mean(0),X.std(0)+1e-9
    m=train_fold([{'paths':r['paths'],'X':(r['X']-mu)/sd} for r in tr], d)
    m.eval()
    with torch.no_grad():
        for r in te:
            s2=m(torch.from_numpy((r['X']-mu)/sd).float()).numpy()
            pick=r['paths'][int(np.argmax(s2))]
            res['rescue']+=max(0,r['cur']['n_err']-pick['n_err'])
            res['damage']+=max(0,pick['n_err']-r['cur']['n_err'])
print('| 切分 | rescue | damage | net |')
print('|---|---|---|---|')
print(f'| document-held-out（主結果）| 239 | 186 | **+53** |')
print(f'| **direction-held-out**（診斷，修正版）| {res["rescue"]} | {res["damage"]} | '
      f'**{res["rescue"]-res["damage"]:+d}** |')
print(f'\n⑭-N 的節點層在 direction-held-out 下條件 AUC 崩到 0.459（低於隨機）。')
