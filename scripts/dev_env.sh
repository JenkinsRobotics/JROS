#!/usr/bin/env bash
#
# JROS dev-instance shim. Source this from your shell (or from another
# script) to point ``JAEGER_INSTANCE_DIR`` at the in-repo sandbox so
# all your dev runs land in ``sandbox/jros-dev/`` instead of the bundled
# ``src/jaeger_os/instance/default/`` skeleton.
#
# Why this matters
# ----------------
# The bundled skeleton is what ``pip install jaeger-os`` ships. If we
# let dev runs write into it, those writes (memory, logs, authored
# skills, audit trails) accumulate inside the repo's source tree and
# travel into the next wheel. The 0.1.0 release shipped 2.7 MB of dev
# junk this way; HYGIENE-1..5 in docs/ROADMAP_0.2.0.md fixes the
# bundle-time leak, and this shim keeps it from re-accumulating.
#
# Usage
# -----
#   source scripts/dev_env.sh
#   jaeger start          # writes to sandbox/jros-dev/, not the bundle
#
# Or run it as a one-shot wrapper:
#
#   scripts/dev_env.sh jaeger start
#   scripts/dev_env.sh jaeger bench run
#
# When sourced WITHOUT arguments it just exports the var and prints
# the path; when executed WITH arguments it runs them in a subshell
# with the var set.

# Resolve the repo root from wherever this script lives.
_jros_repo="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# The dev instance lives under sandbox/jros-dev/. The whole sandbox/
# tree is gitignored (see the root .gitignore), so this never leaks
# into commits.
export JAEGER_INSTANCE_DIR="$_jros_repo/sandbox/jros-dev"
mkdir -p "$JAEGER_INSTANCE_DIR"

if [[ "${BASH_SOURCE[0]:-}" != "${0}" ]]; then
    # Sourced — leave the export in the caller's shell.
    printf '[dev_env] JAEGER_INSTANCE_DIR=%s\n' "$JAEGER_INSTANCE_DIR" >&2
else
    # Executed — run the rest of argv with the var set.
    if [[ $# -eq 0 ]]; then
        printf 'usage: source %s   (export the var)\n' "${BASH_SOURCE[0]:-$0}" >&2
        printf '   or: %s <cmd> [args...]   (run cmd with the var set)\n' "${BASH_SOURCE[0]:-$0}" >&2
        printf 'JAEGER_INSTANCE_DIR would be: %s\n' "$JAEGER_INSTANCE_DIR" >&2
        exit 64
    fi
    exec "$@"
fi
