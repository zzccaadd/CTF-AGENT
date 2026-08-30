#!/usr/bin/env bash
# Stage 1 pressure pipeline — P0 regression, P2 worker-pool ladders, P4 soak.
# Real Codex + Docker runs; each step writes results under PRESSURE_ROOT.
#
# Usage:
#   PRESSURE_ROOT=/tmp/ctf-agent-stage1-pressure/run bash scripts/pressure_pipeline.sh all
#   bash scripts/pressure_pipeline.sh p0 p2c p4        # pick steps
#   PRESSURE_ROOT=... CONTAINER_MEMORY_LIMIT=2g bash scripts/pressure_pipeline.sh p2d
#
# Steps: p0 p2a p2b p2c p2d p4 (all = p0 p2a p2b p2c p2d p4)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT_DIR/.venv/bin"
CTF_BENCH="$VENV/ctf-bench"
PYTHON="$VENV/python"

RUN_ID="$(date +%Y%m%d-%H%M%S)"
PRESSURE_ROOT="${PRESSURE_ROOT:-/tmp/ctf-agent-stage1-pressure/${RUN_ID}}"
mkdir -p "$PRESSURE_ROOT"
export EVIDENCE_DB_PATH="${PRESSURE_ROOT}/evidence.sqlite3"
export CONTAINER_MEMORY_LIMIT="${CONTAINER_MEMORY_LIMIT:-2g}"

CYBENCH_ROOT="$ROOT_DIR/benchmarks/cybench"
IMAGE="ctf-sandbox"
MODEL="codex/gpt-5.5"

# Pre-verified challenges (all previously solved with this stack, cheapest first).
CH1="hackthebox/cyber-apocalypse-2024/crypto/[Very Easy] Dynastic"
CH2="hackthebox/cyber-apocalypse-2024/crypto/[Very Easy] Makeshift"
CH3="hackthebox/cyber-apocalypse-2024/forensics/[Very Easy] It Has Begun"
CH4="hackthebox/cyber-apocalypse-2024/misc/[Easy] Unbreakable"

log() { echo "[pipeline] $*"; }

preflight() {
  command -v docker >/dev/null || { echo "docker missing"; exit 1; }
  docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "image $IMAGE missing"; exit 1; }
  [[ -x "$CTF_BENCH" ]] || { echo "ctf-bench missing"; exit 1; }
  # Fail loudly if EVIDENCE_DB_PATH did not reach Settings.
  DB_CHECK="$("$PYTHON" -c 'from backend.config import Settings; print(Settings().evidence_db_path)' 2>/dev/null || echo UNKNOWN)"
  [[ "$DB_CHECK" == "$EVIDENCE_DB_PATH" ]] || {
    echo "EVIDENCE_DB_PATH not effective: Settings says '$DB_CHECK', expected '$EVIDENCE_DB_PATH'"; exit 1;
  }
  log "preflight OK, db=$EVIDENCE_DB_PATH mem_limit=$CONTAINER_MEMORY_LIMIT"
}

run_bench() {
  local name="$1"; shift
  local results="$PRESSURE_ROOT/$name-results.json"
  log "== $name: $*"
  "$CTF_BENCH" "$@" --image "$IMAGE" --results "$results"
  "$PYTHON" - "$results" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
summary = payload["summary"]
print(f"  solved {summary['solved']}/{summary['total']} cost {summary['cost_usd']}")
for r in payload["results"]:
    print(f"  - {r['challenge_id']}: {r['status']} elapsed={r['elapsed_seconds']}s tool_calls={r['tool_calls']} cost={r['cost_usd']}")
PY
}

step_p0() {
  run_bench p0 --provider cybench --root "$CYBENCH_ROOT" --split benchmark \
    --challenge "$CH1" --model "$MODEL" --timeout 120 --max-tokens 80000 \
    --concurrency 1 --solvers-per-swarm 3
}
step_p2a() {
  run_bench p2a --provider cybench --root "$CYBENCH_ROOT" --split benchmark \
    --challenge "$CH1" --model "$MODEL" --timeout 120 --max-tokens 80000 \
    --concurrency 1 --solvers-per-swarm 1
}
step_p2b() {
  run_bench p2b --provider cybench --root "$CYBENCH_ROOT" --split benchmark \
    --challenge "$CH1" --model "$MODEL" --timeout 120 --max-tokens 80000 \
    --concurrency 1 --solvers-per-swarm 3
}
step_p2c() {
  run_bench p2c --provider cybench --root "$CYBENCH_ROOT" --split benchmark \
    --challenge "$CH1" --challenge "$CH2" --model "$MODEL" --timeout 180 --max-tokens 120000 \
    --concurrency 2 --solvers-per-swarm 3
}
step_p2d() {
  run_bench p2d --provider cybench --root "$CYBENCH_ROOT" --split benchmark \
    --challenge "$CH1" --challenge "$CH2" --challenge "$CH3" --challenge "$CH4" \
    --model "$MODEL" --timeout 300 --max-tokens 200000 \
    --concurrency 4 --solvers-per-swarm 3
}
step_p4() {
  run_bench p4 --provider cybench --root "$CYBENCH_ROOT" --split benchmark \
    --challenge "$CH1" --challenge "$CH2" --model "$MODEL" --timeout 1500 --max-tokens 200000 \
    --concurrency 2 --solvers-per-swarm 3
}

STEPS="${*:-all}"
if [[ "$STEPS" == "all" ]]; then STEPS="p0 p2a p2b p2c p2d p4"; fi

preflight
for step in $STEPS; do
  case "$step" in
    p0) step_p0 ;;
    p2a) step_p2a ;;
    p2b) step_p2b ;;
    p2c) step_p2c ;;
    p2d) step_p2d ;;
    p4) step_p4 ;;
    *) echo "unknown step: $step (p0 p2a p2b p2c p2d p4)"; exit 2 ;;
  esac
done
log "done. results in $PRESSURE_ROOT"
