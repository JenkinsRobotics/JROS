# Migrating a JROS station to the JaegerAI ecosystem

JROS split into four repos at 0.9.0: **JaegerOS** (framework),
**JaegerAI** (the turnkey agent product — what most stations run),
**JaegerKokoroTTS**, and **JaegerWhisperSTT** (voice engines). JROS
0.8.2 is the *handoff release* — the terminal release on this legacy
channel — and its `jaeger update` knows how to carry a deployed 0.8.x
station across to JaegerAI in place, keeping every byte of instance
state.

## What happens

Run `jaeger update` on a 0.8.2 station. If the JaegerAI ecosystem is
reachable (GitHub has a tag >= `0.9.0`), you're offered the migration:

```
$ jaeger update
[jaeger update] The JaegerAI ecosystem (0.9.0) is available — JROS has
split into JaegerOS + JaegerAI + voice-engine packages. 0.8.2 is the
terminal JROS release on this channel; JaegerAI is where future
updates land.
[jaeger update] Migration swaps the product in place — your
.jaeger_os/ instance data (identity, memory, credentials, models) is
never touched — and keeps the old stack in .update-prev/ for `jaeger
update --rollback`. See MIGRATION.md.
Migrate this station to JaegerAI 0.9.0 now? (y/N):
```

* Answer **y** (or run `jaeger update --migrate` to skip the prompt) to
  migrate now.
* Answer **N** / Enter (the default — including every unattended run,
  e.g. the in-app Updates check) to stay on JROS 0.8.2.
* `jaeger update --stay` suppresses the offer entirely and runs the
  ordinary legacy framework update instead (useful for scripting a
  station that should never auto-migrate).

Migration itself:

1. Downloads the JaegerAI release archive for the resolved ref
   (`GET https://github.com/JenkinsRobotics/JaegerAI/archive/<ref>.tar.gz`).
2. **Swaps the product in place.** Every item in JROS's own product
   manifest that exists in your install (`jaeger_os/`, `install.sh`,
   `run.sh`, `jaeger`, `requirements.txt`, `pyproject.toml`,
   `jaeger.toml`, `jaeger.windowed.toml`, `README.md`, `LICENSE`,
   `CHANGELOG.md`) moves wholesale into `.update-prev/` — the SAME
   directory, and the SAME per-item atomic `os.replace`, an ordinary
   `jaeger update` already uses. JaegerAI's own product items are then
   placed into your install root.
3. **`.venv/` is deleted and rebuilt from scratch.** JaegerAI's
   dependency graph doesn't share package identity with the old
   editable `jaeger-os` install this station had — reusing the venv
   risks a stale editable link surviving the swap. A fresh venv is
   exactly what a brand-new curl install already does.
4. **JaegerAI's own `install.sh --product` runs**, in place, against
   your (now-swapped) install root. It creates the fresh `.venv`,
   installs JaegerAI + its git-pinned `jaeger-os` / `jaeger-kokoro-tts`
   / `jaeger-whisper-stt` dependencies (pinned to the same release you
   migrated to), scaffolds `.jaeger_os/` (a no-op — it already exists
   and is left alone), and builds the windowed app.
5. Prints the result and reminds you to restart.

**`.jaeger_os/`** — every instance: identity, memory, skills, logs,
credentials, and any locally-stored models — is named in *neither*
product's manifest, in *either* direction of the swap. No code path in
the migration can reach it. This was verified in the pre-release walk
with a SHA-256 checksum of every file under `.jaeger_os/` taken before
and after migration; see `.superpowers/sdd/082-handoff-report.md`.

## Rolling back

```
jaeger update --rollback
```

This is the *unmodified* rollback command — after migration it's
JaegerAI's own copy of the same code that runs it, and that code
already knows how to reverse a swap generically: it restores whatever
is sitting in `.update-prev/` by name. Since migration stashed the
FULL legacy manifest there, `--rollback` restores JROS 0.8.2 wholesale:
`jaeger_os/`, `install.sh`, `run.sh`, `jaeger`, and the rest, then
resyncs `.venv/`. `.jaeger_os/` was never touched by the migration, so
there's nothing to roll back there either.

**One known, harmless gap:** rollback restores everything that WAS
stashed, but has no reason to remove `jaeger_ai/` itself (a purely new
item — it was never in `.update-prev/` to begin with). You'll see an
inert `jaeger_ai/` directory sitting alongside the restored `jaeger_os/`
after a rollback. Nothing on the restored station imports it (the
restored `jaeger`/`run.sh` wrappers exec `jaeger_os.cli.entry`, not
`jaeger_ai`'s), and a subsequent migration attempt clears it safely —
but it isn't a byte-clean revert of the directory tree, only of the
active product. Delete it by hand if you'd like `~/jaeger` tidy:
`rm -rf ~/jaeger/jaeger_ai`.

## A note on `jaeger doctor` / future update checks after migrating

JaegerAI 0.9.0 carries a known, upstream leftover from the split: its
`core/version_check.py` still defaults to checking JROS's own tags
(`JenkinsRobotics/JROS`) instead of JaegerAI's. The migration works
around this **locally, for your station only** — it exports
`JAEGER_REPO_URL` (the one override that code already honours) from
your freshly-placed `jaeger` and `run.sh` wrapper scripts, so future
`jaeger update` / `jaeger doctor` runs on your migrated station
correctly check JaegerAI's tags. This is not a change to the JaegerAI
source tree; it's flagged for JaegerAI's own next patch.

## `--no-migrate` is a different, older flag

`jaeger update --no-migrate` predates this release and is unrelated:
it skips the per-instance *schema*-migration scan (upgrading an old
`manifest.json:schema_version` after an ordinary framework update),
not the ecosystem migration this document describes. The ecosystem
offer uses `--migrate` / `--stay` specifically to avoid colliding with
that existing, tested flag.
