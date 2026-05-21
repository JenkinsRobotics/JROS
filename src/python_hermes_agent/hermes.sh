#!/usr/bin/env bash
# hermes.sh — launch hermes-agent with the local Gemma LLM server auto-started.
#
# Ensures the llama-cpp-python OpenAI-compat server is up on :11435 (starting
# it and waiting out the model warm-up if needed), then runs `hermes` with
# whatever arguments you pass. The server is left running in the background,
# so the next launch is instant — no second terminal, no manual start_llm.sh.
#
#   ./python_hermes_agent/hermes.sh chat -Q -q "what time is it"
#   ./python_hermes_agent/hermes.sh chat                 # interactive REPL
#
# Env overrides (same as start_llm.sh): HERMES_LLM_PORT, HERMES_LLM_MODEL,
# HERMES_LLM_CTX, HERMES_LLM_GPU_LAYERS. HERMES_LLM_LOG sets the server log.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${HERMES_LLM_PORT:-11435}"
HEALTH_URL="http://127.0.0.1:${PORT}/v1/models"
SERVER_LOG="${HERMES_LLM_LOG:-/tmp/hermes_llm.log}"
HERMES_BIN="$REPO_ROOT/.venv/bin/hermes"

if [ ! -x "$HERMES_BIN" ]; then
  echo "[hermes.sh] $HERMES_BIN not found — run python_hermes_agent/setup.sh first" >&2
  exit 1
fi

# A process bound to the port means a server already exists — possibly
# mid-request. Don't start a second one (port clash); and don't probe
# /v1/models for this check, since it false-negatives while the server is
# busy (its event loop is single-threaded).
port_bound()      { lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; }
# Server answers a trivial request — fully warmed up and free.
server_healthy()  { curl -s -m 3 "$HEALTH_URL" >/dev/null 2>&1; }

if port_bound; then
  echo "[hermes.sh] LLM server already running on :${PORT}"
else
  echo "[hermes.sh] starting LLM server on :${PORT} (log: ${SERVER_LOG})..."
  nohup "$REPO_ROOT/python_hermes_agent/start_llm.sh" >"$SERVER_LOG" 2>&1 &
  for i in $(seq 1 60); do
    if server_healthy; then
      echo "[hermes.sh] LLM server ready"
      break
    fi
    if [ "$i" -eq 60 ]; then
      echo "[hermes.sh] ERROR: server not ready after 600s — see ${SERVER_LOG}" >&2
      exit 1
    fi
    sleep 10
  done
fi

exec "$HERMES_BIN" "$@"
