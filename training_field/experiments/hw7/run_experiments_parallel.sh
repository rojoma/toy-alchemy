#!/usr/bin/env bash
# HW7 — Parallel version: runs sessions inside each experiment concurrently.
# Total wall time ~3-4 min instead of ~13-15 min sequential.
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
  local file="$OUT/$label.json"
  local start=$(date +%s)
  curl -s -X POST "$BASE/api/agent/session/run" \
    -H "Content-Type: application/json" \
    -H "X-Field-Key: $KEY" \
    -d "$body" -o "$file"
  local elapsed=$(( $(date +%s) - start ))
  local sid=$(grep -o '"session_id":"[^"]*"' "$file" | head -1)
  local zpd=$(grep -o '"avg_zpd":[^,}]*' "$file" | head -1)
  local fp=$(grep -o '"final_proficiency":[^,}]*' "$file" | head -1)
  echo "  ✓ ${label} ${elapsed}s | $sid | $zpd | $fp" | tee -a "$LOG"
}

snapshot() {
  curl -s "$BASE/api/agent/leaderboard" -H "X-Field-Key: $KEY" \
    -o "$OUT/leaderboard_$1.json"
  echo "■ snapshot $1" | tee -a "$LOG"
}

snapshot "before"

echo "▶ EXP1: Tournament (3 parallel)" | tee -a "$LOG"
run "exp1/t001_emma" '{"teacher_id":"t001","student_id":"s001","topic":"分数のかけ算とわり算","depth":"quick","run_pre_test":false,"run_post_test":false,"lang":"en"}' &
run "exp1/ext_tanaka_emma" '{"teacher_id":"ext_tanaka","student_id":"s001","topic":"分数のかけ算とわり算","depth":"quick","run_pre_test":false,"run_post_test":false,"lang":"en"}' &
run "exp1/ext_rivera_emma" '{"teacher_id":"ext_rivera","student_id":"s001","topic":"分数のかけ算とわり算","depth":"quick","run_pre_test":false,"run_post_test":false,"lang":"en"}' &
wait
snapshot "after_exp1"

echo "▶ EXP2: Warmth x Confidence (4 parallel)" | tee -a "$LOG"
run "exp2/ext_warm_v1_s001" '{"teacher_id":"ext_warm_v1","student_id":"s001","topic":"円の面積","depth":"quick","run_pre_test":false,"run_post_test":false,"lang":"en"}' &
run "exp2/ext_warm_v1_s006" '{"teacher_id":"ext_warm_v1","student_id":"s006","topic":"円の面積","depth":"quick","run_pre_test":false,"run_post_test":false,"lang":"en"}' &
run "exp2/ext_cool_v1_s001" '{"teacher_id":"ext_cool_v1","student_id":"s001","topic":"円の面積","depth":"quick","run_pre_test":false,"run_post_test":false,"lang":"en"}' &
run "exp2/ext_cool_v1_s006" '{"teacher_id":"ext_cool_v1","student_id":"s006","topic":"円の面積","depth":"quick","run_pre_test":false,"run_post_test":false,"lang":"en"}' &
wait
snapshot "after_exp2"

echo "▶ EXP3: Depth ROI (3 parallel)" | tee -a "$LOG"
run "exp3/t001_priya_quick" '{"teacher_id":"t001","student_id":"s003","topic":"対称な図形","depth":"quick","run_pre_test":false,"run_post_test":false,"lang":"en"}' &
run "exp3/t001_priya_standard" '{"teacher_id":"t001","student_id":"s003","topic":"対称な図形","depth":"standard","run_pre_test":false,"run_post_test":false,"lang":"en"}' &
run "exp3/t001_priya_deep" '{"teacher_id":"t001","student_id":"s003","topic":"対称な図形","depth":"deep","run_pre_test":false,"run_post_test":false,"lang":"en"}' &
wait
snapshot "after_exp3"

echo "" | tee -a "$LOG"
echo "All done." | tee -a "$LOG"
