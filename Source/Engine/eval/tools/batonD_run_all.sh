#!/bin/bash
# Baton D orchestrator: after mining completes, train D0/D1/D2 short runs and eval.
set -u
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin:$PATH"
PY="${IBOPOMOFO_PYTHON:-$HOME/laowang-data/venv/bin/python}"
REPO="${IBOPOMOFO_REPO:-$HOME/iBopomofo}"
OUT="${IBOPOMOFO_BATOND_OUT:-$HOME/laowang-data/batonD-final}"
CORPUS="${IBOPOMOFO_PTT_CORPUS:-$HOME/laowang-data/ptt_spoken_train_v2.txt}"
TRAIN=$REPO/Source/Engine/eval/train_char_lstm_lm.py
EVAL=$REPO/Source/Engine/eval/tools/batonD_eval.py
LOG=$OUT/logs/orchestrator.log
exec >>"$LOG" 2>&1
echo "$(date -Iseconds) orchestrator start"

# Wait for mining
while [ ! -f "$OUT/traindata/mine_meta.json" ]; do
  echo "$(date +%H:%M:%S) wait mine..."
  sleep 60
  if ! pgrep -f 'batonD_mine_hard.py' >/dev/null 2>&1; then
    if [ ! -f "$OUT/traindata/mine_meta.json" ]; then
      echo "MINE_FAILED"
      exit 2
    fi
  fi
done
echo "$(date -Iseconds) mine ready"
cat "$OUT/traindata/mine_meta.json"

if [ -f "$OUT/traindata/POLLUTION_STOP.json" ]; then
  echo "POLLUTION STOP"
  exit 3
fi

HARD=$OUT/traindata/hard_mined_train.txt
COMMON_ARGS=(--emb 256 --hidden 512 --layers 2 --batch 128 --seq-len 64 --stream --device mps --lr 0.001 --seed 42 --val-ratio 0.02 --log-every 200)

# --- D0: original corpus, 2h ---
if [ ! -f "$OUT/models/D0.bin" ]; then
  echo "$(date -Iseconds) D0 train start"
  $PY "$TRAIN" \
    --corpus "$CORPUS" \
    --out "$OUT/models/D0.bin" \
    --epochs 4 \
    --max-hours 2 \
    "${COMMON_ARGS[@]}" \
    2>&1 | tee "$OUT/logs/train_D0.stdout.txt"
  echo D0_EXIT=$?
else
  echo "D0.bin exists, skip train"
fi

# record D0 steps for alignment
D0_STEPS=$(python3 -c "import re; t=open('$OUT/logs/train_D0.stdout.txt').read(); m=re.findall(r'step=(\\d+)', t); print(m[-1] if m else '0')")
echo "D0_STEPS=$D0_STEPS"
if [ -z "$D0_STEPS" ] || [ "$D0_STEPS" = "0" ]; then
  # fallback from DONE line
  D0_STEPS=$(python3 -c "import re; t=open('$OUT/logs/train_D0.stdout.txt').read(); m=re.search(r'DONE step=(\\d+)', t); print(m.group(1) if m else '8000')")
fi
echo "ALIGN_STEPS=$D0_STEPS"

# --- D1: original + hard weight 5×, same step budget ---
# weight grid later; primary short run uses 5× as mid of 2/5/10
for W in 2 5 10; do
  tag="D1_w${W}"
  if [ ! -f "$OUT/models/${tag}.bin" ]; then
    echo "$(date -Iseconds) $tag train start weight=$W steps=$D0_STEPS"
    $PY "$TRAIN" \
      --corpus "$CORPUS" \
      --extra-corpus "$HARD" \
      --extra-weight "$W" \
      --out "$OUT/models/${tag}.bin" \
      --epochs 8 \
      --max-batches "$D0_STEPS" \
      "${COMMON_ARGS[@]}" \
      2>&1 | tee "$OUT/logs/train_${tag}.stdout.txt"
    echo ${tag}_EXIT=$?
  fi
done

# Pick D1 mid weight as primary D1 (5×); D2 = D1 if no synth
cp -f "$OUT/models/D1_w5.bin" "$OUT/models/D1.bin" 2>/dev/null || true
cp -f "$OUT/models/D1_w5.meta.txt" "$OUT/models/D1.meta.txt" 2>/dev/null || true
# D2 skipped synth → copy D1 and note
cp -f "$OUT/models/D1.bin" "$OUT/models/D2.bin" 2>/dev/null || true
cp -f "$OUT/models/D1.meta.txt" "$OUT/models/D2.meta.txt" 2>/dev/null || true
echo "D2=D1 (synth skipped)" | tee "$OUT/logs/D2_note.txt"

# --- Eval all ---
$PY "$EVAL" D0 "$OUT/models/D0.bin" 2>&1 | tee "$OUT/logs/eval_D0_run.stdout.txt"
D0_OK=$(python3 -c "import json; print(json.load(open('$OUT/eval_D0.json'))['best']['n_ok'])")
echo D0_OK=$D0_OK
for tag in D1_w2 D1_w5 D1_w10 D1 D2; do
  if [ -f "$OUT/models/${tag}.bin" ]; then
    $PY "$EVAL" "$tag" "$OUT/models/${tag}.bin" "$D0_OK" 2>&1 | tee "$OUT/logs/eval_${tag}_run.stdout.txt"
  fi
done

# SHA inventory
{
  echo "# batonD SHA256 $(date -Iseconds)"
  find "$OUT" -type f \( -name '*.bin' -o -name '*.txt' -o -name '*.json' -o -name '*.tsv' -o -name '*.meta.txt' \) | sort | while read f; do
    shasum -a 256 "$f"
  done
} > "$OUT/SHA256_INVENTORY.txt"

# report
$PY "$OUT/write_report.py" 2>&1 | tee -a "$OUT/logs/orchestrator.log" || true

date > "$OUT/PIPELINE_COMPLETE.marker"
echo "$(date -Iseconds) ORCH_DONE"
