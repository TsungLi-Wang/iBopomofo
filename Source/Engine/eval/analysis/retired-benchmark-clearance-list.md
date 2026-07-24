# 退役評測集清除清單（B 部分）

本清單不複述任何已刪除之歷史分數或敘述。

## 刪除檔案

- `Source/Engine/eval/benchmarks/tw-sentences.tsv`（退役集本體）

## 修改（引用 / 預設路徑 / 敘述清理）

- `Source/Engine/eval/benchmarks/build-and-run.sh`（預設 tw538 + shell 守門）
- `Source/Engine/eval/benchmarks/run_tw_benchmark.py`
- `Source/Engine/eval/benchmarks/same_path_oracle.cpp`
- `Source/Engine/eval/benchmarks/*` 主要 harness（`#include benchmark_gate.h`）
- `Source/Engine/eval/benchmark_gate.h`（新增）
- `Source/Engine/eval/README.md`、`benchmarks/README.md`
- `CHANGELOG.md`、`AI_HANDOFF_PROMPT.md`、`AGENTS.md`、`docs/ngram-rnn-hybrid.md`
- `Source/KeyHandler.mm`（註解）
- `Source/Engine/eval/slim_word_bigram_table.py`、`em_reestimate_unigram.py`
- 交接檔 v3.1（`Downloads/` 與 `Documents/` 各一份）

## 守門

- 句數 ≠ 537 → abort
- 檔名含 `tw-sentences` → abort
- 無繞過旗標

## 未做

- 未改寫 git 歷史（退役集仍存在於舊 commit，已知可接受）
