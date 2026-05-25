#!/usr/bin/env bash
# One-shot setup for the python_hermes_agent demo:
#   - clones NousResearch/hermes-agent into ./upstream/ (if missing)
#   - pip installs it into the project venv (editable, base extras only)
#   - links cli-config.yaml into ~/.hermes/ so the next `hermes` run
#     uses our Ollama Cloud (qwen3.5:397b) settings
#
# Inference runs on Ollama Cloud via the `ollama-cloud` provider — this
# script downloads no model weights and needs no local Ollama daemon.
# Auth is the OLLAMA_API_KEY in ~/.hermes/.env (see Next steps).
#
# Re-runnable: skips clone if upstream/ exists; reinstall is harmless.
set -euo pipefail

cd "$(dirname "$0")"
PROJECT_ROOT="$(cd .. && pwd)"
VENV="$PROJECT_ROOT/.venv"

if [ ! -d upstream/.git ]; then
  echo "[hermes-setup] cloning NousResearch/hermes-agent..."
  git clone --depth 1 https://github.com/NousResearch/hermes-agent.git upstream
else
  echo "[hermes-setup] upstream/ already cloned — skipping git clone."
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "[hermes-setup] missing $VENV — run the project bootstrap first." >&2
  exit 1
fi

echo "[hermes-setup] installing hermes-agent into $VENV..."
"$VENV/bin/pip" install -e upstream

mkdir -p "$HOME/.hermes"
CFG_LINK="$HOME/.hermes/cli-config.yaml"
if [ -L "$CFG_LINK" ]; then
  # Existing symlink (possibly stale, e.g. an old repo path) — re-point it.
  ln -sf "$PWD/cli-config.yaml" "$CFG_LINK"
  echo "[hermes-setup] (re)linked $PWD/cli-config.yaml -> $CFG_LINK"
elif [ -f "$CFG_LINK" ]; then
  echo "[hermes-setup] $CFG_LINK is a real file — leaving it alone."
  echo "              to use our config: ln -sf '$PWD/cli-config.yaml' '$CFG_LINK'"
else
  ln -s "$PWD/cli-config.yaml" "$CFG_LINK"
  echo "[hermes-setup] linked $PWD/cli-config.yaml -> $CFG_LINK"
fi

# Qwen3.5 runs on Ollama Cloud — flag a missing API key early.
if [ -z "${OLLAMA_API_KEY:-}" ] && ! grep -q '^OLLAMA_API_KEY=' "$HOME/.hermes/.env" 2>/dev/null; then
  echo ""
  echo "[hermes-setup] WARNING: no OLLAMA_API_KEY in the environment or ~/.hermes/.env."
  echo "              Add one (get it from https://ollama.com/settings):"
  echo "              echo 'OLLAMA_API_KEY=<your-key>' >> ~/.hermes/.env"
fi

echo ""
echo "Done. Next steps:"
echo "  1. Confirm the cloud key:   grep OLLAMA_API_KEY ~/.hermes/.env"
echo "  2. Run a one-shot prompt:   ./hermes.sh chat -Q -q 'what time is it'"
echo "  3. Or the bench-style demo: .venv/bin/python python_hermes_agent/run_prompt.py 'what time is it'"
