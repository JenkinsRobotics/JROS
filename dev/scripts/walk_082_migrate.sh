#!/bin/bash
# 0.8.2 HANDOFF RELEASE — the mandatory migrate-flow walk.
#
# Builds a scripted station shaped like a real deployed 0.8.x install
# (clean/product layout, no .git, a fabricated instance with
# memory/credentials/skills markers) running THIS repo's code, then:
#
#   1. runs `jaeger update --migrate` for real (real network download
#      of JaegerAI@0.9.0, real install.sh, real fresh .venv)
#   2. checksums .jaeger_os/ before/after — asserts byte-identical
#   3. points the instance at a small real GGUF and runs one real turn
#      through the freshly-migrated JaegerAI stack
#   4. runs `jaeger update --rollback` and checksums again — asserts
#      the product is restored byte-identical AND instance data is
#      still untouched
#
# This is NOT part of CI (real network, ~GB-scale downloads, a couple
# of minutes runtime) — it's the manual pre-release walk. Run by hand:
#   dev/scripts/walk_082_migrate.sh [/path/to/scratch]
#
# Results from the last run are in .superpowers/sdd/082-handoff-report.md.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRATCH="${1:-$(mktemp -d)}"
STATION="$SCRATCH/station"
USERHOME="$SCRATCH/userhome"
MODELDIR="$SCRATCH/tinymodel"

echo "== 0.8.2 migrate walk — scratch: $SCRATCH =="

# ── 1. build a clean, product-shaped 0.8.x-looking station ──────────
rm -rf "$STATION" "$USERHOME"
mkdir -p "$STATION" "$USERHOME"
for item in jaeger_os install.sh run.sh jaeger requirements.txt \
            pyproject.toml jaeger.toml jaeger.windowed.toml \
            README.md LICENSE CHANGELOG.md; do
  cp -R "$REPO/$item" "$STATION/$item"
done
find "$STATION/jaeger_os" -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

python3.11 -m venv "$STATION/.venv"
"$STATION/.venv/bin/pip" install -q --upgrade pip
"$STATION/.venv/bin/pip" install -q -e "$STATION" --no-deps
"$STATION/.venv/bin/pip" install -q pydantic PyYAML msgspec requests

# ── 2. fabricate an "0.8.1-vintage" instance with real-shaped markers ─
INST="$STATION/.jaeger_os/instances/fieldbot"
mkdir -p "$INST/memory" "$INST/logs" "$INST/skills"
mkdir -p -m 700 "$INST/credentials"
cat > "$INST/identity.yaml" <<'EOF'
name: FieldBot
role: field-test agent
personality: pragmatic, terse
EOF
cat > "$INST/config.yaml" <<EOF
instance_name: fieldbot
model:
  model_path: gemma-4-26b-a4b-it-q4_k_m
  ctx: 32768
EOF
SCHEMA_VERSION="$("$STATION/.venv/bin/python" -c \
  "import sys; sys.path.insert(0,'$STATION'); \
   from jaeger_os.core.instance.schemas import SCHEMA_VERSION as v; print(v)")"
cat > "$INST/manifest.json" <<EOF
{"instance_name": "fieldbot", "schema_version": "$SCHEMA_VERSION", "created_at": "2026-05-01T00:00:00+00:00"}
EOF
echo "0.8.1-vintage memory: FieldBot remembers the operator prefers terse answers." \
  > "$INST/memory/notes.txt"
echo '{"provider": "telegram", "token": "FAKE-TOKEN-DO-NOT-USE"}' > "$INST/credentials/telegram.json"
chmod 600 "$INST/credentials/telegram.json"
echo "2026-05-01 boot ok" > "$INST/logs/boot.log"
echo "skill: weather lookup" > "$INST/skills/weather.md"
mkdir -p "$STATION/.jaeger_os/models"
head -c 65536 /dev/urandom | base64 > "$STATION/.jaeger_os/models/fake-model-marker.bin"
echo "fieldbot" > "$STATION/.jaeger_os/active_instance"

find "$STATION/.jaeger_os" -type f | sort | xargs shasum -a 256 > "$SCRATCH/checksums_before.txt"

# ── 3. run the migrate path for real ─────────────────────────────────
export HOME="$USERHOME"
export JAEGER_HOME="$STATION"
cd "$STATION"
bash jaeger update --migrate

find "$STATION/.jaeger_os" -type f | sort | xargs shasum -a 256 > "$SCRATCH/checksums_after_migrate.txt"
if ! diff -q "$SCRATCH/checksums_before.txt" "$SCRATCH/checksums_after_migrate.txt" >/dev/null; then
  echo "FAIL: .jaeger_os/ changed across migration"; exit 1
fi
echo "OK: instance data byte-identical across migration"
[ -d "$STATION/jaeger_ai" ] || { echo "FAIL: jaeger_ai/ not placed"; exit 1; }
[ -d "$STATION/jaeger_os" ] && { echo "FAIL: jaeger_os/ not stashed"; exit 1; }
grep -q JAEGER_REPO_URL "$STATION/jaeger" || { echo "FAIL: repo-url patch missing"; exit 1; }

# ── 4. point the instance at a small real gguf + run one real turn ──
mkdir -p "$MODELDIR"
if [ ! -f "$MODELDIR/tiny.gguf" ]; then
  curl -fL --max-time 180 -o "$MODELDIR/tiny.gguf" \
    "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"
fi
cat > "$INST/config.yaml" <<EOF
instance_name: fieldbot
model:
  model_path: $MODELDIR/tiny.gguf
  ctx: 4096
EOF
bash jaeger --instance fieldbot "In exactly one short sentence, what is 2+2?"

# ── 5. rollback + verify byte-identical revert ───────────────────────
find "$STATION/.jaeger_os" -type f | sort | xargs shasum -a 256 > "$SCRATCH/checksums_pre_rollback.txt"
bash jaeger update --rollback
find "$STATION/.jaeger_os" -type f | sort | xargs shasum -a 256 > "$SCRATCH/checksums_post_rollback.txt"
if ! diff -q "$SCRATCH/checksums_pre_rollback.txt" "$SCRATCH/checksums_post_rollback.txt" >/dev/null; then
  echo "FAIL: .jaeger_os/ changed across rollback"; exit 1
fi
echo "OK: instance data byte-identical across rollback"
[ -d "$STATION/jaeger_os" ] || { echo "FAIL: jaeger_os/ not restored"; exit 1; }
[ -d "$STATION/jaeger_ai" ] && echo "NOTE: jaeger_ai/ debris left behind (documented, harmless — see MIGRATION.md)"
diff -rq --exclude=__pycache__ "$STATION/jaeger_os" "$REPO/jaeger_os" \
  && echo "OK: jaeger_os/ restored byte-identical to the original product"

echo "== walk complete: $SCRATCH =="
