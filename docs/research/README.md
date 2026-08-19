# docs/research — 外部文獻與方法調查

**這裡放「外面已經知道什麼」。** 要選下一個機制時才讀；不是每次進場都要看。

## 分工（別放錯層）

| 要寫的東西 | 該去哪 |
|---|---|
| **外部文獻、業界先例、方法比較** | **本目錄** |
| 我們自己為什麼這樣做、試過什麼 | `docs/decisions/` |
| 已證明無效 | `docs/dead-ends.md` |
| 到哪了、下一刀 | `AI_HANDOFF_PROMPT.md` |

## 規矩

- **外勤（grok／codex）的原始回報原樣歸檔**，統治局的採納判斷寫在調查檔裡，兩者分開放。
  混在一起就分不出「誰說的」與「我們憑什麼信」。
- 引用一律附**作者／年份／venue／URL**，而且要寫「**它沒有證明什麼**」。
- **抽驗過的引用要標明**；沒逐條下載核對的，在檔案開頭寫清楚仍屬待驗。

## 目錄

| 檔案 | 內容 |
|---|---|
| [personalization-methods-survey.md](personalization-methods-survey.md) | 低資料量下的個人化選字機制調查與裁決（棒㉒-B）。**結論：UOM abstraction DROP、`用 correction 學排序` 整個家族 DROP** |
| [personalization-external-research-raw.md](personalization-external-research-raw.md) | 上者的外勤原始回報（grok，26 條引用），原樣歸檔 |
