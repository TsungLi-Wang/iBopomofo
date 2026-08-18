import sys, json, collections, statistics
sys.path.insert(0,'Source/Engine/eval')
from audit_path_score_discriminability import load, gold_rank, pairwise, wilson, SCORERS
M='/private/tmp/claude-501/-Users-johnny-w-macmini/cea89cfe-14e5-4c59-af23-b4c9950bc97e/scratchpad/m'
sents=load(M+'/paths.tsv')
gold={s:ps for s,ps in sents.items() if any(p['is_gold'] for p in ps)}
print('## gold 離第一名有多遠（融合分數）\n')
defs=[]; rng=[]
for ps in gold.values():
    g=max((p for p in ps if p['is_gold']),key=lambda p:p['fused'])
    top=max(ps,key=lambda p:p['fused'])
    lo=min(p['fused'] for p in ps)
    defs.append(top['fused']-g['fused']); rng.append(top['fused']-lo)
q=lambda v,p: sorted(v)[min(len(v)-1,int(p*len(v)))]
print('| 分位 | gold 落後第一名的分數 | 佔該句 top–bottom 分數跨度的比例 |')
print('|---|---|---|')
frac=[d/r if r>0 else 0 for d,r in zip(defs,rng)]
for p,lbl in ((.10,'P10'),(.25,'P25'),(.50,'**中位數**'),(.75,'P75'),(.90,'P90')):
    print(f'| {lbl} | {q(defs,p):.3f} | {q(frac,p):.1%} |')
print(f'\n中位數落後 {statistics.median(defs):.3f} 分，只佔該句分數跨度的 '
      f'**{statistics.median(frac):.1%}** —— gold 幾乎都貼著第一名。')

print('\n\n## 逐方向（`CORPUS-LEVEL / DIRECTION-LEVEL EVIDENCE`）\n')
# 用 ⑭-M 的錯字方向；一句可能有多個錯字，取該句第一個
import itertools
meta={}
for i,l in enumerate(open('/Users/johnny.w_macmini/Documents/i注音-語料/EX1166-題庫/自然驗證集-真實語料.jsonl',encoding='utf-8'),1):
    if l.strip(): meta[str(i)]=json.loads(l)
nb={}
with open(M+'/nbest.tsv',encoding='utf-8') as fh:
    next(fh)
    for line in fh:
        f=line.rstrip('\n').split('\t')
        nb.setdefault(f[0],[]).append((f[2],f[3]))
byd=collections.defaultdict(list)
for s,ps in gold.items():
    for c,g in nb.get(s,[]):
        byd[f'{c}→{g}'].append(ps); break
print('| 方向 | 句數 | pairwise acc | gold 中位名次 | 判讀 |')
print('|---|---|---|---|---|')
key=lambda p:p['fused']
for d,lst in sorted(byd.items(),key=lambda x:-len(x[1]))[:12]:
    if len(lst)<10:
        print(f'| {d} | {len(lst)} | — | — | **INSUFFICIENT POWER** |'); continue
    W=T=L=0
    for ps in lst:
        a,b,c=pairwise(ps,key); W+=a; T+=b; L+=c
    rs=[gold_rank(ps,key) for ps in lst]
    acc=(W+0.5*T)/(W+T+L)
    print(f'| {d} | {len(lst)} | **{acc:.3f}** | {statistics.median(rs):.0f} | '
          f'{"有訊號" if acc>=0.65 else "弱"} |')
ins=sum(1 for d,l in byd.items() if len(l)<10)
print(f'\n方向共 {len(byd)} 個，其中 {ins} 個 n<10 標 **INSUFFICIENT POWER**（保留不刪）。')

print('\n\n## 可爭取量與 system-level 換算\n')
we=0
for ps in gold.values():
    we+=next(p['n_err'] for p in ps if p['is_walk'])
print('| 量 | 值 | 標記 |')
print('|---|---|---|')
print(f'| gold path 在 top-10 的句子 | {len(gold):,} | `OBSERVED` |')
print(f'| 這些句子的 walk 錯字 | {we:,} | `OBSERVED` |')
print(f'| 佔 D2 (3,192) | **{we/3192:.1%}** | `OBSERVED` |')
print(f'| 佔全部字位 (74,649) | {we/74649:.2%} | `OBSERVED` |')
print(f'| ⑭-P 可達 top-10 oracle（不限零錯路徑）| 37.5% of D2 | `THEORETICAL UPPER BOUND` |')
print(f'| 現有 top-1 錯誤 | 3,192 / 74,649 = 4.28% | `OBSERVED` |')
