# 0.8.2 — the handoff release

Branch `0.8.2`, cut from `master` (0.8.1 merge state, `3d4009b`), in a
separate git worktree (`../JROS-0.8.2`) so the 0.9.0 working tree was
never touched. Local commits only; nothing pushed or tagged.

## What shipped

`jaeger update` gained the ecosystem-migration path:

- **Detection**: `migrate_verb.check_ecosystem_available()` — GitHub
  tags for `JenkinsRobotics/JaegerAI`, returns the newest tag if
  `>= 0.9.0`, else `None` (network failures degrade the same way
  `version_check.latest_version` already does — never raises).
- **CLI**: `jaeger update` offers migration with an explicit y/N
  confirm (default N — never migrates unattended); `--migrate` runs it
  non-interactively; `--stay` suppresses the offer entirely. **Did not
  reuse `--no-migrate`** — that flag already means "skip the
  per-instance schema-migration scan" (tested, shipped since INST-7)
  and is semantically unrelated; colliding the two would have been a
  silent behavior change for existing scripts. Documented in
  MIGRATION.md's last section.
- **Migration** (`migrate_verb.run_ecosystem_migration`): downloads
  JaegerAI@ref's tarball, reuses `update_verb._extract_product` (now
  takes a `product=` allowlist param) with JaegerAI's own manifest,
  then a new `_migrate_swap` — a full-manifest stash-then-place, since
  `update_verb._swap_in`'s name-matched loop structurally can't stash
  `jaeger_os` (no same-named item exists in JaegerAI's manifest).
  `.venv/` is deleted and rebuilt via JaegerAI's own `install.sh
  --product` (dependency identity doesn't survive the swap; a fresh
  venv is what a real curl install already does). `.jaeger_os/` is
  named in neither manifest, in either direction — no code path can
  reach it.
- **Rollback reuse, verified for real**: `jaeger update --rollback`
  post-migration runs from the newly-installed `jaeger_ai` package's
  own (byte-identical) copy of `update_verb.py` — completely
  unmodified. It reverses the swap correctly because it restores
  whatever's in `.update-prev/` by name, not by knowing what a "JROS
  update" looks like. Confirmed live in the walk, not just by reading
  the code.
- **Known upstream bug worked around, not fixed**: JaegerAI 0.9.0's
  `core/version_check.py` still hardcodes `_DEFAULT_REPO =
  "JenkinsRobotics/JROS"` (a split-era leftover, verified by reading
  the file). Out of this task's repo/scope to patch (already tagged).
  Worked around locally: migration exports `JAEGER_REPO_URL` from the
  migrated station's own `jaeger`/`run.sh` wrappers — the one override
  that code already honours — confirmed live (`repo_slug()` correctly
  returns `JenkinsRobotics/JaegerAI` post-patch).
- **Known cosmetic gap, documented**: `_do_rollback` restores what's
  in `.update-prev/` but has no reason to delete `jaeger_ai/` itself
  (never stashed there — it's a new item, not a restored one). A
  rollback leaves an inert `jaeger_ai/` directory behind (confirmed
  live: it even causes `_rebuild_swift_app` to rebuild against the
  *debris* tree during rollback, producing a stray `JaegerOS.app`
  under `jaeger_ai/interfaces/swift/.build/`). Harmless — nothing on
  the restored station's `sys.path` or wrapper scripts references it —
  but not a byte-clean directory revert. `_migrate_swap` was hardened
  to clear such debris before a repeat migration (prevents `ENOTEMPTY`
  on retry). Both gaps are flagged for JaegerAI's own next patch.

Files: `jaeger_os/cli/verbs/migrate_verb.py` (new),
`jaeger_os/cli/verbs/update_verb.py` (`--migrate`/`--stay` flags, the
offer/confirm flow, `_extract_product`'s new `product=` param),
`CHANGELOG.md`, `MIGRATION.md` (new), `jaeger_os/__init__.py`
(`__version__ = "0.8.2"`).

## Tests

`dev/tests/jaeger_os/cli/verbs/test_migrate_verb.py` (new, 17 tests):
repo-slug/threshold parsing, `already_migrated`, the JaegerAI-allowlist
extraction, `_migrate_swap` (including the debris/retry-safety case),
`_patch_repo_url`, and `run_ecosystem_migration` orchestration
(download/subprocess mocked). `test_update_verb.py` (+11 tests): the
CLI offer/confirm/`--migrate`/`--stay`/`--check` wiring, gated behind a
new autouse fixture (`_no_ecosystem_offer`) so all 37 pre-existing
tests keep exercising only the legacy flow, hermetically (no live
network in any test). 59/59 green in this file pair; 236/236 across
`dev/tests/jaeger_os/cli/`; 41/41 in the touched `core` slices
(instance resolver/lock, version_check). Built a fresh minimal venv
for the worktree (pydantic + PyYAML + msgspec were the only 3rd-party
imports on the actual `jaeger update` code path — confirmed by AST
scan — everything else in the dependency-warning noise is unrelated
pre-existing surface).

## The walk (mandatory, run for real — not inspected)

Script: `dev/scripts/walk_082_migrate.sh` (checked in, reproducible).
Ran it live against `~/GITHUB/JaegerAI`'s real tagged `0.9.0` over the
real network, not mocked:

1. Built a clean, product-shaped station (no `.git`, exactly the
   `_PRODUCT` allowlist — matching what a real curl install has) from
   this branch's own code, plus a fabricated "0.8.1-vintage" instance
   (`fieldbot`): identity, config, manifest at the real `SCHEMA_VERSION`,
   a memory marker, a credentials marker, a skill, a boot log, plus an
   install-level model-cache marker.
2. `jaeger update --migrate`: real download of JaegerAI's `0.9.0`
   tarball, real swap, real `.venv` rebuild + `install.sh --product`
   (fresh deps incl. llama-cpp-python w/ Metal, torch, kokoro,
   pywhispercpp — all installed clean; JaegerOS.app built). **Checksum
   of every file under `.jaeger_os/` before vs. immediately after:
   byte-identical, 9/9 files.**
3. Pointed the instance's `config.yaml` at a freshly downloaded small
   real GGUF (Qwen2.5-0.5B-Instruct, Q4_K_M, ~470 MB) and ran
   `jaeger --instance fieldbot "In exactly one short sentence, what is
   2+2?"` through the live, freshly-installed `jaeger_ai` stack — real
   model load, real STT/TTS warm (whisper + kokoro both came up
   online), real generation: **`2+2 equals 4.`** exit 0. (One
   self-inflicted hiccup: killing an early attempt mid-download left a
   corrupted whisper weight file that then crashed the process on
   reload — deleted and re-ran to completion; not a product bug.)
4. Checksummed `.jaeger_os/` again pre-rollback (now showing the
   *expected* writes from real usage — new memory/log files, an
   updated `manifest.json:last_started_at` boot timestamp, plus my own
   deliberate `config.yaml` edit — none of the original fabricated
   markers touched).
5. `jaeger update --rollback`: real, unmodified rollback via the
   installed `jaeger_ai` package. **Checksum of `.jaeger_os/`
   pre-vs-post-rollback: byte-identical.** `jaeger_os/` restored;
   `diff -rq` against this branch's own `jaeger_os/` source: clean,
   byte-identical. `jaeger --version` back to `jaeger-os 0.8.2`.
   `.update-prev/` correctly consumed. `jaeger_ai/` debris left behind
   as documented above.

Every assertion in the script passed; nothing was patched to make the
walk pass — the one real bug hit (the corrupted-download crash) was an
artifact of my own interrupted test run, not migration code, and is
called out rather than hidden.

## Concerns for the operator

1. Two JaegerAI-side gaps found and worked around/hardened from this
   repo but not fixed at the source (out of scope): the
   `version_check.repo_slug` default, and rollback's `jaeger_ai/`
   debris. Worth a small JaegerAI patch at some point.
2. The walk's fresh-venv install pulled `jaeger-os`/kokoro/whisper via
   git from GitHub (no `~/GITHUB` siblings inside the isolated scratch
   `$HOME`) — i.e. it exercised the real curl-install dependency path,
   not the dev-sibling shortcut. A real deployed station will do the
   same.
3. `--no-migrate` now has two co-existing, differently-scoped meanings
   in the surrounding ecosystem (JROS 0.8.2: instance-schema scan only;
   the word "migrate" also describes the new ecosystem move) — flagged
   clearly in `--help` and MIGRATION.md's last section to avoid
   operator confusion.
