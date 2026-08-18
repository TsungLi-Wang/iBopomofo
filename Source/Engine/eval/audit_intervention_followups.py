import sys,json,collections
sys.path.insert(0,'Source/Engine/eval')
from audit_full_corpus_error_map import load_nodes,build,SIX_CHARS
from audit_error_intervention_map import load_lex,classify
M='/private/tmp/claude-501/-Users-johnny-w-macmini/cea89cfe-14e5-4c59-af23-b4c9950bc97e/scratchpad/m'
meta={}
for i,l in enumerate(open('/Users/johnny.w_macmini/Documents/i注音-語料/EX1166-題庫/自然驗證集-真實語料.jsonl',encoding='utf-8'),1):
    if l.strip(): meta[str(i)]=json.loads(l)
lex=load_lex(M+'/lex.tsv')
errs,tot,ns,sk=build(load_nodes(M+'/natural-all-nodes.tsv'),meta)
for e in errs:
    m=meta[e['sid']]; syl=m['full_reading'].split('-')
    e['syl']=syl[e['pos']] if len(syl)==len(m['sentence']) else None
    e['family']=classify(e,lex); e['isolated']=e['run_len']==1
N=len(errs)
print('\n\n## Q4：⑭-L 那 209 個「整句解碼錯」的 D2 對應\n')
tgt=[e for e in errs if meta[e['sid']].get('target_index',-1)==e['pos']]
tr=[e for e in tgt if not e['isolated']]
print(f'題庫目標位置的錯字（≈ D1 的口徑）**{len(tgt)}**；')
print(f'其中目標字以外同句也有錯（＝「整句解碼錯」的操作型定義）**{len(tr)}**。')
print(f'（⑭-L 報 209，那是 error_taxonomy.py 在 D1′ 上的分類；口徑不同，**NOT COMPARABLE**，')
print(f' 但量級相符，可作對照。）\n')
print('| 這批錯的家族 | 錯字 | 佔比 | 有沒有明確可操作介入點 |')
print('|---|---|---|---|')
c=collections.Counter(e['family'] for e in tr)
note={'NODE':'**有** —— 正解就在該節點候選裡，換值即可','PATH/SEG':'有 —— 字在詞庫，要改斷詞／路徑','LEXICON':'要補詞庫','UNKNOWN':'—'}
for k,v in c.most_common():
    print(f'| {k} | {v} | {v/len(tr):.1%} | {note[k]} |')
nn=c['NODE']
print(f'\n**Q4 答案：{nn}/{len(tr)} = {nn/len(tr):.0%} 有明確可操作介入點**（正解已在候選內）。')
print('「整句解碼錯」這個名字造成的誤解在這裡被量化了：它描述的是**現象**')
print('（目標字以外也錯），不是**成因**（解碼器壞掉）。大多數位置的正解仍在候選裡。')

print('\n\n## Q3 / 任務十：node-level 是否存在不依賴 direction 記憶的共同結構\n')
node=[e for e in errs if e['family']=='NODE']
neg_note='（對照組＝同一批 dump 裡引擎選對的節點，見 ⑭-N）'
print('本棒只做描述統計，不訓練、不宣稱可學。⑭-N 已證明條件 AUC 0.459。\n')
print('| 結構性指標 | NODE 家族錯字 | 判讀 |')
print('|---|---|---|')
r0=sum(1 for e in node if e['chosen_rank']==0)
g1=sum(1 for e in node if e['gold_rank']<=1)
print(f'| 引擎選了 unigram 第一名 | {r0:,}（{r0/len(node):.1%}）| 要對抗的是詞頻先驗 |')
print(f'| 金標在前兩名 | {g1:,}（{g1/len(node):.1%}）| 決策接近二選一 |')
sp1=sum(1 for e in node if e['span']==1)
print(f'| 單字節點 | {sp1:,}（{sp1/len(node):.1%}）| |')
nc=sum(1 for e in node if e['n_cands']>=10)
print(f'| 候選數 ≥10 | {nc:,}（{nc/len(node):.1%}）| 不是二選一的簡單題 |')
d=collections.Counter(f"{e['chosen']}→{e['gold']}" for e in node)
print(f'| 不同 engine→gold 方向 | **{len(d):,}** | 長尾（⑭-M 的 775 在 span=1 上的全量版）|')
top=sum(v for _,v in d.most_common(50))
print(f'| 前 50 個方向的覆蓋 | {top:,}（{top/len(node):.1%}）| 集中度低 |')
print(f'\n**結論：UNKNOWN。** 本棒沒有找到任何「不依賴方向記憶」的共同結構的**證據**；')
print('⑭-N 已直接測過字元無關的引擎側數值特徵，條件 AUC 0.459（低於隨機）。')
print('沒有新證據 → 不得提出新的節點層訓練提案。')
