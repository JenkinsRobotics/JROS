# python_hermes_agent — NousResearch hermes-agent on Ollama Cloud (Qwen3.5)

Wraps the real [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
framework and drives it with **Qwen3.5 (`qwen3.5:397b`) running on Ollama
Cloud**. Inference happens on Ollama's cloud GPUs — there is no local model,
no GGUF, and no local Ollama daemon. The agent still uses its full toolset:
web search, fetch, terminal, file ops, and more.

hermes-agent is a full self-improving agent framework: 40+ tools, persistent
skills, session search, and its own learning loop.

## How inference is wired

Hermes ships a first-class **`ollama-cloud` provider**. Set that as the
provider and Hermes talks straight to Ollama Cloud over HTTPS — the local
`ollama` CLI/daemon is not involved at all.

```
┌──────────────────────────────┐   HTTPS   ┌────────────────────────────┐
│  hermes-agent CLI            │  ───────► │  Ollama Cloud              │
│  (chat -Q -q "...")          │  provider │  model: qwen3.5:397b       │
│  picks tools, runs them,     │  ollama-  │  (runs on cloud GPUs)      │
│  asks the LLM to summarize   │  cloud    └────────────────────────────┘
└──────────────────────────────┘
       │
       │ enabled toolsets: web search, fetch, terminal, files
       ▼
   tool results → fed back to the model → final reply
```

`qwen3.5:397b` is a 397-billion-parameter model — it only runs on the
cloud, never on a local machine.

## Configuration

Two files, both under `~/.hermes/`:

- **`~/.hermes/config.yaml`** — Hermes' full runtime config. Its `model`
  block is set to `provider: ollama-cloud`, `default: qwen3.5:397b`.
- **`~/.hermes/cli-config.yaml`** — a symlink to this directory's
  [`cli-config.yaml`](cli-config.yaml), so the project carries its own
  model settings. `setup.sh` creates/repairs that symlink.

Auth is the **`OLLAMA_API_KEY`** in `~/.hermes/.env`. It is read from there
at runtime and is never stored in the repo, so `cli-config.yaml` is safe to
commit.

## Quick start

```bash
# 1. Clone hermes-agent upstream, install it into the project venv, and
#    link cli-config.yaml into ~/.hermes/.
./setup.sh

# 2. Confirm the Ollama Cloud key is in place.
grep OLLAMA_API_KEY ~/.hermes/.env

# 3. Send a one-shot prompt.
./hermes.sh chat -Q -q "search the web for robot vacuum reviews"

# Interactive REPL:
./hermes.sh chat

# Or via the bench-friendly Python wrapper:
.venv/bin/python python_hermes_agent/run_prompt.py "tell me a one sentence story about a robot"
```

## Files in this directory

| File | What it does |
|---|---|
| `setup.sh` | clones upstream/, `pip install -e upstream`, links `cli-config.yaml` into `~/.hermes/` |
| `hermes.sh` | convenience launcher — sanity-checks the venv + key, then runs `hermes` |
| `cli-config.yaml` | project config — `provider: ollama-cloud`, `default: qwen3.5:397b` |
| `run_prompt.py` | one-shot Python wrapper that returns a `run_for_voice`-shaped dict for the bench harness |
| `upstream/` | clone of NousResearch/hermes-agent — not committed (ignored via `.gitignore`); rerun `setup.sh` to refresh |

## What to expect

hermes-agent expects the model to drive a broad toolset (40+ tools across
web/terminal/file/code/vision/memory/skills/cron categories). Qwen3.5 is a
large, tool-trained model, so it routes that surface reliably:

- `"what time is it"` → hermes runs `date` via the `terminal` toolset.
- `"search the web for X"` → handled by the `web` toolset.
- `"calculate 47 * 23 + 12"` → `code_execution` (Python) or `terminal` (`bc`).

Because inference is cloud-hosted, expect a network round-trip to Ollama
Cloud on each agent step rather than local GPU time.

## Caveats

- **Not offline.** Inference runs on Ollama Cloud — a network connection
  and a valid `OLLAMA_API_KEY` are required. Local tools still run locally.
- **Cloud usage is billed to whatever account the key belongs to.** Swap
  the key in `~/.hermes/.env` to bill a different account.
- **Memory state lives at `~/.hermes/`** — not in this repo. Wipe it with
  `hermes uninstall` (or `rm -rf ~/.hermes` for a clean slate).
- **`upstream/` is ignored by git** — the clone is ~214 MB and re-derivable
  from the public repo. `setup.sh` handles refresh.
