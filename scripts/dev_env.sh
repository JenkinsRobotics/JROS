#!/usr/bin/env bash
#
# JROS sandbox shim. Source this from your shell to make the in-repo
# ``sandbox/`` directory behave as a full miniature JROS install:
#
#   <repo>/sandbox/
#   ├── jaeger_os/        ← symlink to ../jaeger_os (live edits show up)
#   └── .jaeger_os/       ← sandbox's own operator state
#       └── instances/jros-dev/
#
# Mechanism
# ---------
# 0.2.6 dropped the old ``~/.jaeger/`` runtime location in favour of
# ``<install_root>/.jaeger_os/``. The runtime reads ``$JAEGER_HOME``
# to find the install root; this script just points $JAEGER_HOME at
# the sandbox dir. Everything else falls out naturally — instances,
# models cache, jaeger.env, all land under sandbox/.jaeger_os/.
#
# Usage
# -----
#   source scripts/dev_env.sh
#   ./run.sh                   # writes to sandbox/.jaeger_os/, not your real install
#   ./run.sh setup jros-dev    # creates the sandbox's test instance
#
# Or one-shot:
#
#   scripts/dev_env.sh ./run.sh
#   scripts/dev_env.sh ./run.sh setup jros-dev
#
# The sandbox tree is gitignored (see .gitignore — both ``sandbox/``
# and ``.jaeger_os/`` are excluded), so dev work never travels in a
# commit.

# Resolve the repo root from wherever this script lives.
_jros_repo="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
_sandbox="$_jros_repo/sandbox"

# Idempotently set up the sandbox's framework symlink so the resolver
# treats sandbox/ as a full install rather than a partial one. The
# operator's existing edits in <repo>/jaeger_os/ are picked up live
# through the symlink — no second checkout to keep in sync.
mkdir -p "$_sandbox"
if [[ ! -e "$_sandbox/jaeger_os" ]]; then
    ln -s "../jaeger_os" "$_sandbox/jaeger_os"
fi

# Operator state goes alongside the framework symlink at
# sandbox/.jaeger_os/. The runtime creates instances/, models/, etc.
# on demand.
mkdir -p "$_sandbox/.jaeger_os/instances"

# Point everything at the sandbox: JAEGER_HOME drives install_root()
# in the python runtime; PYTHONPATH lets ``import jaeger_os`` resolve
# through the sandbox's symlink.
export JAEGER_HOME="$_sandbox"
case ":${PYTHONPATH:-}:" in
    *":$_sandbox:"*) ;;
    *) export PYTHONPATH="$_sandbox${PYTHONPATH:+:$PYTHONPATH}" ;;
esac

if [[ "${BASH_SOURCE[0]:-}" != "${0}" ]]; then
    # Sourced — leave the exports in the caller's shell.
    printf '[dev_env] JAEGER_HOME=%s\n' "$JAEGER_HOME" >&2
    printf '[dev_env] sandbox layout:\n  %s/jaeger_os    -> ../jaeger_os\n  %s/.jaeger_os/\n' \
        "$_sandbox" "$_sandbox" >&2
else
    # Executed — run the rest of argv with the env set.
    if [[ $# -eq 0 ]]; then
        printf 'usage: source %s         (export the vars into your shell)\n' \
            "${BASH_SOURCE[0]:-$0}" >&2
        printf '   or: %s <cmd> [args…]   (run cmd with the env set)\n' \
            "${BASH_SOURCE[0]:-$0}" >&2
        printf 'JAEGER_HOME would be: %s\n' "$JAEGER_HOME" >&2
        exit 64
    fi
    exec "$@"
fi
