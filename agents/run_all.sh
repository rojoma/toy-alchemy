#!/bin/bash
# Run all 5 agents in parallel locally.
# Usage: FIELD_API_KEY=field_2026spring_0408 bash run_all.sh

set -e

if [ -z "$FIELD_API_KEY" ]; then
  echo "Error: FIELD_API_KEY not set"
  echo "Usage: FIELD_API_KEY=field_2026spring_0408 bash run_all.sh"
  exit 1
fi

export FIELD_URL="${FIELD_URL:-https://beyond-answer-engine.up.railway.app}"
export SESSION_DEPTH="${SESSION_DEPTH:-quick}"
export MAX_SESSIONS="${MAX_SESSIONS:-1}"
export SESSION_DELAY="${SESSION_DELAY:-10}"

mkdir -p logs

echo "=== Launching 5 agents ==="
for i in 1 2 3 4 5; do
  echo "Starting agent $i..."
  AGENT_ID=$i python agent.py > "logs/agent_${i}.log" 2>&1 &
  echo "  PID: $!"
done

echo ""
echo "All 5 agents running. Logs in logs/"
echo "Watch live: tail -f logs/agent_*.log"
echo "Wait for all to finish..."
wait
echo "=== All agents finished ==="

echo ""
echo "=== Summary ==="
for i in 1 2 3 4 5; do
  echo "--- Agent $i ---"
  grep -E "(Registered|Session sess_|finished)" "logs/agent_${i}.log" || echo "  (no results)"
done
