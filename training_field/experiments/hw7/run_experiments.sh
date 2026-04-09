#!/usr/bin/env bash
# HW7 — Run all 10 experiment sessions against the deployed Training Field.
#
# Usage:
#   FIELD_API_KEY=field_2026spring_0408 bash run_experiments.sh
#   (or pass it inline; default is read from env)
#
# Outputs:
#   results/<exp>/<sess>.json   per-session raw response
#   results/leaderboard_*.json  leaderboard snapshots before/after each experiment
#   results/all.log             flat log of every run

set -u
BASE="${BASE:-https://beyond-answer-engine.up.railway.app}"
KEY="${FIELD_API_KEY:?set FIELD_API_KEY env var}"
OUT="$(dirname "$0")/results"
mkdir -p "$OUT/exp1" "$OUT/exp2" "$OUT/exp3"
LOG="$OUT/all.log"
: > "$LOG"

run() {
  local label="$1"; shift
  local body="$1"; shift
  echo "▶ $label" | tee -a "$LOG"
  echo "  body: $body" | tee -a "$LOG"
  local start=$(date +%s)
  local file="$OUT/$label.json"
  curl -s -X POST "$BASE/api/agent/session/run" \
    -H "Content-Type: application/json" \
    -H "X-Field-Key: $KEY" \
    -d "$body" -o "$file"
  local rc=$?
  local elapsed=$(( $(date +%s) - start ))
  if [ $rc -ne 0 ]; then
    echo "  ✗ curl failed (rc=$rc) after ${elapsed}s" | tee -a "$LOG"
    return
  fi
  local sid=$(grep -o '"session_id":"[^"]*"' "$file" | head -1)
  local gain=$(grep -o '"learning_gain":[^,}]*' "$file" | head -1)
  local zpd=$(grep -o '"avg_zpd":[^,}]*' "$file" | head -1)
  echo "  ✓ ${elapsed}s | $sid | $gain | $zpd" | tee -a "$LOG"
}

snapshot() {
  local label="$1"
  curl -s "$BASE/api/agent/leaderboard" -H "X-Field-Key: $KEY" \
    -o "$OUT/leaderboard_$label.json"
  echo "■ leaderboard snapshot: $label" | tee -a "$LOG"
}

snapshot "before"

# ── Experiment 1: Tournament — same student/topic, 3 teacher styles ──
EXP1_TOPIC='"分数のかけ算とわり算"'
for tid in t001 ext_tanaka ext_rivera; do
  run "exp1/${tid}_emma" "{
    \"teacher_id\": \"$tid\",
    \"student_id\": \"s001\",
    \"topic\": $EXP1_TOPIC,
    \"depth\": \"quick\",
    \"run_pre_test\": false,
    \"run_post_test\": false,
    \"lang\": \"en\"
  }"
done
snapshot "after_exp1"

# ── Experiment 2: Warmth × Confidence (2x2) ──
EXP2_TOPIC='"円の面積"'
for tid in ext_warm_v1 ext_cool_v1; do
  for sid in s001 s006; do
    run "exp2/${tid}_${sid}" "{
      \"teacher_id\": \"$tid\",
      \"student_id\": \"$sid\",
      \"topic\": $EXP2_TOPIC,
      \"depth\": \"quick\",
      \"run_pre_test\": false,
      \"run_post_test\": false,
      \"lang\": \"en\"
    }"
  done
done
snapshot "after_exp2"

# ── Experiment 3: Depth ROI (quick / standard / deep) ──
EXP3_TOPIC='"対称な図形"'
for d in quick standard deep; do
  run "exp3/t001_priya_${d}" "{
    \"teacher_id\": \"t001\",
    \"student_id\": \"s003\",
    \"topic\": $EXP3_TOPIC,
    \"depth\": \"$d\",
    \"run_pre_test\": false,
    \"run_post_test\": false,
    \"lang\": \"en\"
  }"
done
snapshot "after_exp3"

echo "" | tee -a "$LOG"
echo "All done. Results in $OUT" | tee -a "$LOG"
