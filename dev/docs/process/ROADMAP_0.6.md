# JROS 0.6 Roadmap — Polished install / update / lifecycle UX

**Status:** active (2026-06-25) — branch opened off 0.5.0
**Branch:** `0.6.0`
**Pre-req:** 0.5.0 shipped + merged to `master` (commit `6c50374`)
**Target:** JROS *feels like a real app* to install, run, and keep current —
including in-app **update checks** and **self-update** (download + apply), not
just a curl one-liner.

## The position

0.5 made the agent visibly alive (animation, personality, skill tree). 0.6
makes the **product around it** feel finished: the install, the update, the
uninstall. The headline is a real update experience — the app knows when a
newer version exists and can pull it down in place, keeping the operator's
`.venv/` and instance state untouched. No "re-paste this curl command."

Renders via `jaeger roadmap` (it picks the highest-numbered ROADMAP).

---

## Carry-over flags from 0.5.0 — docs accuracy (quick wins)

The README drifted during 0.5.0. Fix first; they're small and load-bearing for
a polished first impression.

- [ ] **`jaeger` is the canonical command.** README Quick Start uses `./run.sh`;
  document `jaeger` as the one operator command (`run.sh` still works). The
  "Daily use (0.3.0)" header is stale — retitle.
- [ ] **Wizard now picks a character.** README says the wizard asks
  memory/model/voice; 0.5.0 added the **character pick** (defaults to Jarvis)
  and binds it to the instance. Document it.
- [ ] **Upgrade instructions are wrong for curl installs.** `git pull &&
  ./install.sh` only works for a manual `git clone` (it has `.git`). The curl
  one-liner copies product-only (no `.git`) → upgrade is re-running the
  one-liner today, and `jaeger update` once it lands (below).

## Install experience

- [ ] **Prereq detection + guidance.** Installer checks Python 3.11/3.12, a C
  toolchain, and PortAudio; on a miss it prints the exact per-OS fix command and
  stops early (no half-built `.venv`).
- [ ] **First-run model download** — progress bar + ETA + resumable; surface the
  download size before it starts.
- [ ] **Post-install summary** — verify the "next steps" output is accurate to
  the `jaeger` command set.

## Update experience — the headline

- [ ] **`jaeger update`** — one command, in place, **no git required** (works for
  the product-only curl install).
- [ ] **Check for updates** — query GitHub tags/releases (or `master`'s
  `jaeger_os.__version__`), compare to the local `__version__`; cache the result
  so it's cheap to call often.
- [ ] **Download + apply** — fetch the target ref, swap the product dir
  **atomically**, preserve `.venv/` + `.jaeger_os/`; re-run dependency install
  **only** if `requirements.txt` / `pyproject.toml` changed.
- [ ] **Surface availability in-app** — tray menu item + a Jaeger Studio banner:
  "Update available 0.6.x → Install".
- [ ] **Channels / pinning** — stable vs. latest; honour `JAEGER_REF`.
- [ ] **Rollback** — keep the previous product dir; `jaeger update --rollback`.

## Uninstall

- [ ] **`jaeger uninstall`** — remove the framework; prompt to keep or wipe
  instance state (`~/jaeger/.jaeger_os/`). Mirrors the install's clean split.

## Plumbing

- [ ] **Version source of truth** — `jaeger_os.__version__` (currently `0.5.0`);
  bump to `0.6.0` when 0.6 ships. Add a tiny "what's the latest published
  version" lookup the updater + `doctor` share.
- [ ] **`jaeger doctor`** reports current vs. latest + update readiness.

---

## Also queued (not this theme — don't lose them)

- **Tier-1 `core` role** in the app framework (`JaegerApp` hosts the brain as a
  first-class main-thread core, not a stubbed node) — design already drafted;
  aligns JROS to the demos.
- **JP01 hardware adapter layer** (mic-in / RGB-out / speaker-out streaming on
  the device, riding the `MediaFrame` / `ZmqBus` seam declared in 0.5.0) — see
  [`../hardware/`](../hardware/). HISTORY flagged this for 0.6/0.7; the
  install/update theme takes 0.6, hardware likely lands 0.7.
