#!/usr/bin/env bash
# Capture the pre-refactor benchmark baseline. Run from the JROS repo root.
#
# Writes:
#   benchmark/baseline/manifest.json          git SHA, model, host, timestamp
#   benchmark/baseline/levelN.log             stdout from each level's run
#   benchmark/baseline/level_N_rows.jsonl     per-prompt observation rows
#
# Do this BEFORE Phase 1 of the agent refactor starts.
set -euo pipefail

cd "$(dirname "$0")/../.."
OUT="benchmark/baseline"
mkdir -p "$OUT"

PY="${PY:-./.venv/bin/python}"
if [[ ! -x "$PY" ]]; then PY="python3"; fi

echo "==> capturing baseline benchmark into $OUT/"

# Manifest — pin the state these numbers correspond to.
SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
HOST_INFO="$(uname -srm)"
MEM_BYTES="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Model name — read from the default instance config (best-effort).
MODEL="$($PY -c "
from pathlib import Path
try:
    import yaml
    cfg = yaml.safe_load(Path('src/jaeger_os/instance/default/config.yaml').read_text())
    m = cfg.get('model', {})
    ext = cfg.get('external_model', {})
    if ext.get('enabled'):
        print(f'external · {ext.get(\"provider\")} · {ext.get(\"model\")}')
    else:
        print(f'local · {m.get(\"model_path\")} (ctx={m.get(\"ctx\")})')
except Exception as e:
    print(f'unknown ({e})')
" 2>/dev/null)"

cat > "$OUT/manifest.json" <<EOF
{
  "captured_at": "$TIMESTAMP",
  "git_sha": "$SHA",
  "host": "$HOST_INFO",
  "host_memory_bytes": $MEM_BYTES,
  "model": "$MODEL",
  "framework": "pydantic-ai",
  "note": "Baseline before the JaegerAgent refactor (Phase 1+)."
}
EOF
echo "    manifest:  $OUT/manifest.json"
cat "$OUT/manifest.json"
echo ""

run_level () {
  local n=$1
  local mod=$2
  echo "==> level $n: $mod"
  $PY -m "$mod" 2>&1 | tee "$OUT/level${n}.log"
  # The level modules write into benchmark/levels/level_${n}_rows.jsonl;
  # freeze a copy here so subsequent runs (post-refactor) don't overwrite it.
  if [[ -f "benchmark/levels/level_${n}_rows.jsonl" ]]; then
    cp "benchmark/levels/level_${n}_rows.jsonl" "$OUT/level_${n}_rows.jsonl"
    echo "    rows:     $OUT/level_${n}_rows.jsonl"
  fi
  echo ""
}

run_level 1 benchmark.levels.level1_routing
run_level 2 benchmark.levels.level2_multistep
run_level 3 benchmark.levels.level3_multiturn
run_level 4 benchmark.levels.level4_recovery

echo "==> baseline captured in $OUT/"
echo "    Commit these files so the comparison is reproducible:"
echo "      git add benchmark/baseline/"
echo "      git commit -m 'benchmark: pre-refactor baseline'"
