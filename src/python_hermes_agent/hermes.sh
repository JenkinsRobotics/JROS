#!/usr/bin/env bash
# hermes.sh — convenience launcher for hermes-agent.
#
# Inference runs on Ollama Cloud (provider: ollama-cloud, model
# qwen3.5:397b). There is no local LLM server to start — Hermes talks
# straight to the cloud — so this wrapper just sanity-checks the setup
# and then runs `hermes` with whatever arguments you pass.
#
#   ./python_hermes_agent/hermes.sh chat -Q -q "what time is it"
#   ./python_hermes_agent/hermes.sh chat                 # interactive REPL
#
# Auth comes from OLLAMA_API_KEY in ~/.hermes/.env (or the environment).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_BIN="$REPO_ROOT/.venv/bin/hermes"

if [ ! -x "$HERMES_BIN" ]; then
  echo "[hermes.sh] $HERMES_BIN not found — run python_hermes_agent/setup.sh first" >&2
  exit 1
fi

# Warn (don't fail) if no Ollama Cloud key is visible — hermes will give a
# clearer error itself, but this points at the usual fix.
if [ -z "${OLLAMA_API_KEY:-}" ] && ! grep -q '^OLLAMA_API_KEY=' "$HOME/.hermes/.env" 2>/dev/null; then
  echo "[hermes.sh] WARNING: no OLLAMA_API_KEY found in the environment or ~/.hermes/.env" >&2
  echo "            qwen3.5:397b runs on Ollama Cloud and needs that key to authenticate." >&2
fi

exec "$HERMES_BIN" "$@"
