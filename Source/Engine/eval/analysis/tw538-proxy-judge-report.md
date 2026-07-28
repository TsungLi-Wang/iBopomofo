# tw538 代理判別器上限量測（棒 A-3）

> **污染與定位（必讀）**  
> 本棒使用通用大語言模型（Qwen2.5-Instruct）作**能力上限代理**，幾乎確定在預訓練時看過 PTT 類語料，而 tw538 出自 PTT。  
> **此處數字是能力上限估計，不是可部署方案，也不是引擎分數。**  
> **禁止寫進分數階梯**，禁止與 296 / 333 / 387 / 397 / 402 並列。

**日期**：2026-07-28  
**性質**：純離線量測；**未**改 app／引擎／出貨配置／權重。  
**代理模型未進入任何出貨路徑。**

---

## 步驟 0 控制組

指令：既有 `nbest_path_rerank`（λ=0.75、ν=0.75、N=10、v2c int8）。

```
path scorer loaded=1 params=9734083 emb=256 hidden=512 layers=2 vocab=7875
SLICE1_OFF 296/537
SLICE1_ON 333/537
SLICE1_NBEST_RANK0_MATCH 537/537
SLICE1_WALK_MEAN_US 319.611
SLICE2_NU0_MATCH 537/537
NU 0.75 correct 387/537 mean_ms 46.749
BEST_NU 0.75 correct 387/537
```

**= 387 ✓**

---

## 模型與環境指紋

| 項目 | 值 |
|------|-----|
| 模型 | **Qwen2.5-7B-Instruct**（**非思考** instruct） |
| 量化 | MLX 4-bit（`mlx-community/Qwen2.5-7B-Instruct-4bit`） |
| 參數量 | 7B 級（hidden=3584, layers=28） |
| 權重路徑 | `~/laowang-data/models/Qwen2.5-7B-Instruct-4bit-mlx/model.safetensors`（約 4.0 GiB） |
| 權重 SHA256 | `86110f368236b53cf4c2336f991a85703b17bcc60bb75f292b4002ec0219f071` |
| 推論框架 | `mlx` + `mlx-lm`（Apple M2, 16 GB unified） |
| 取樣 | **greedy / temperature 0**（候選集合上 argmax） |
| 思考模式 | **關閉**（走 logits，無 CoT） |
| 硬體 | Apple M2, 16 GB RAM, Metal 3 |
| 台灣在地模型 | **未做**（本機無 TAIDE / Llama-3-Taiwan 權重；未另下載） |

**選型說明**：家用 16 GB 上限取可穩定載入的最大 Qwen instruct 變體 → 7B 4-bit MLX。未再升 14B（記憶體不足風險）。

**為何必須 instruct 非思考**：要的是候選機率分布而非自然語言推理；思考鏈成本與同音直覺任務不匹配。

---

## 有效性閘門（唯一硬停）

**定義**：代理模型在「出貨已答對」的位置上，受限同音 argmax 正確率 ≥ **96%**。

### 結果（全量 537 句 / T1 流程）

| 指標 | 數值 |
|------|------|
| 出貨已答對位置數 | 6562 |
| 代理在其上答對 | **4962** |
| **閘門正確率** | **75.62%** |
| 門檻 | 96% |
| **判定** | **未過 → 整棒停止** |

同時（僅供診斷，**不是分數階梯**）：

| 指標 | 代理 T1 | 對照 |
|------|---------|------|
| 字級（全位置） | 5070/6797 = **74.59%** | 出貨 96.5% |
| 句級 | **13/537** | 出貨 387/537 |

verbatim 摘要：

```
T1_SECONDS 115.41
T1_POS 5070/6797 74.5917%
T1_SENT 13/537
VALIDITY_GATE 4962/6562 75.6172%
VALIDITY_PASS False
```

### 依棒規停止

- **T2（候選代入整句重打分）未跑**
- **T3（提示式選擇題）未跑**
- 原因：閘門未過 → 代理模型**不是有效上限代理**；繼續跑 T2/T3 只會量測一顆「連簡單位置都不如 v2c」的模型，無法支撐「專門判別器天花板」推論。

---

## T1 方法（已完成，用於閘門）

與棒 A 殘餘熵條件對齊：

1. 前綴 = **gold teacher forcing**
2. 對下一字全詞表 logits，**限制到該讀音同音集合 `reading2chars` 後 softmax**
3. argmax 為預測
4. 每句一次前向（BOS + gold 字串）

**未**使用 chat template（純續寫 logits，非對話格式）。

---

## T2 / T3

| 層 | 狀態 |
|----|------|
| T2 雙向整句重打分 | **未跑**（閘門停） |
| T3 提示式選擇題 | **未跑**（閘門停） |
| T3 提示詞 | 腳本內已寫好模板，因未跑不重複測；見 `proxy_judge_measure.py` 中 `T3_SYSTEM` / `T3_USER_TMPL` |

預留 T3 提示詞全文（可重現；本棒未執行）：

```
SYSTEM:
你是繁體中文同音字判別助手。只輸出一個漢字，必須是候選清單中的字，
不要輸出其他任何文字、標點或解釋。

USER:
下列句子中，符號 ▢ 代表一個需要填入的位置。
請依整句語意，從候選字中選出最適合的一個字。

句子：
{sentence}

候選字（只能選一個）：
{choices}

請只輸出一個候選字。
```

---

## 失敗判讀（兩種可能）

| 假設 | 與本棒證據 |
|------|------------|
| A. 任務本身資訊不足 | 尚不能下此結論——代理在**出貨已對**的簡單位置就大幅落敗，問題出在代理不配位，不是「看了還不會」 |
| B. 代理台灣中文／任務格式能力不足 | **較吻合**：Qwen 簡體向通用 LM + 字級同音集合 argmax，在 dogfood 注音任務上遠遜專職 v2c；且**未跑成台灣在地模型對照** |

因此：**不能**把「代理失敗」讀成「判別器框架死亡」；只能讀成：

> **「用現成通用 instruct LLM 當上限代理」這條捷徑不成立。**  
> 要證明「專門選擇題判別器」的天花板，仍需**專職訓練／領域適配**，不能靠現成 Qwen 白嫖上限。

這與棒 A-2「v2c 當判別知識全滅」是**不同命題**：A-2 否決的是 v2c 翻字；A-3 否決的是「通用 LLM 可當有效上限代理」。

---

## GO / NO-GO（本棒判準）

棒規：以 T1/T2/T3 **最佳句級** ≥450 GO / 430–449 邊際 / <430 NO-GO。

因閘門未過：

- **不適用「≥450 開訓練」的 GO 路徑**（代理無效）
- **本棒操作結論：STOP / 代理路線 NO-GO**
- **不得**把 13/537 寫進任何產品分數敘事

是否仍開「專職小判別器訓練線」：  
**本棒無法給出正向上限**；若要開，必須另立訓練假設與成本，不能再引用「強模型一定遠高於 387」——至少 Qwen2.5-7B-Instruct 在此協議下**遠低於** 387。

---

## 產物

| 產物 | 路徑 |
|------|------|
| 逐位置 T1 | `Source/Engine/eval/analysis/tw538-proxy-judge-positions.tsv` |
| 本報告 | `Source/Engine/eval/analysis/tw538-proxy-judge-report.md` |
| 腳本 | `Source/Engine/eval/tools/proxy_judge_measure.py` |
| stdout / summary | `~/laowang-data/batonA3-proxy-judge/` |
| SHA256 | `~/laowang-data/batonA3_sha256_inventory.txt` |

重跑 T1 閘門：

```bash
~/laowang-data/venv/bin/python Source/Engine/eval/tools/proxy_judge_measure.py \
  --repo ~/iBopomofo --data-dir ~/laowang-data
# 全量會先過閘門；目前會在閘門 ABORT
```

---

## app / harness / 交付

1. **app build**：未動  
2. **harness**：控制組 387（見上）  
3. **交付物**：T1 全量 + 閘門失敗報告；T2/T3 依規未跑  
