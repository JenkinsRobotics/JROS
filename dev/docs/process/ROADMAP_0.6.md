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

- [x] **`jaeger` is the canonical command.** Quick Start + Daily-use now use
  `./jaeger` (with the PATH note for global `jaeger`); `run.sh` kept as an
  alias. "Daily use (0.3.0)" header retitled. *(done)*
- [x] **Wizard now picks a character.** Quick Start documents the character
  pick. *(done)*
- [x] **Upgrade instructions fixed.** README now documents `jaeger update`
  (download/apply, `--rollback`, `--ref`) instead of `git pull && ./install.sh`;
  storage table + prose updated. Version badge bumped 0.3.0 → 0.5.2. *(done)*
  *(Still stale: the `0.3.0`-era Status narrative — a broader content pass,
  not part of this theme.)*

## Install experience

- [ ] **Prereq detection + guidance.** Installer checks Python 3.11/3.12, a C
  toolchain, and PortAudio; on a miss it prints the exact per-OS fix command and
  stops early (no half-built `.venv`).
- [ ] **First-run model download** — progress bar + ETA + resumable; surface the
  download size before it starts.
- [ ] **Post-install summary** — verify the "next steps" output is accurate to
  the `jaeger` command set.

## Native Mac app — launcher + launch-at-login

The "feels like a real app" track. Two tiers, both layered on **today's curl
install** (the download is unchanged). Tier 2 — the thin launcher in
`/Applications` — is the ceiling; a full self-contained bundle / DMG is **out
of scope** (note below).

**Tier 1 — launch at login (easy, no bundling)** ✅ *done*
- [x] `jaeger autostart enable|disable|status` — macOS writes/loads a
  `~/Library/LaunchAgents/` LaunchAgent; **Linux** writes a `systemd --user`
  unit (+ best-effort `loginctl enable-linger` for boot-without-login) — the
  unit case the robots need. Runs the install's `jaeger` (extra args forwarded);
  **opt-in**. *(done)*

**Tier 2 — clickable launcher app (the target, no bundling)**
- [ ] After the curl install, an **opt-in step** offers to create the launcher;
  on accept it drops `/Applications/Jaeger.app` — a thin launcher
  (`Contents/MacOS/` stub → `~/jaeger/jaeger`) + icon. Same download as today,
  one extra consented step → Dock / Launchpad presence + double-click launch.
- [ ] **No Gatekeeper friction, no signing.** The launcher is *created locally*
  by the installer (not downloaded), so it carries no quarantine flag — it opens
  without the "unidentified developer" block. No py2app, no notarization.
- [ ] **File access stays full.** The launcher is *not* sandboxed (no App
  Sandbox entitlement) → the spawned Python has the same Unix file access as
  Terminal; workspace + project edits are unaffected. The only gate is **TCC**
  for protected folders (Desktop / Documents / Downloads / external drives):
  `jaeger doctor` detects missing **Full Disk Access** and points to the
  System Settings toggle. Grant once → zero prompts, including headless
  autostart (Tier 1) where there's no GUI to answer a prompt.

**Out of scope — full bundle / DMG** (decided 2026-06-25). No self-contained
py2app / PyInstaller `.app`, no signed / notarized DMG, no drag-to-Applications
install. The curl install + thin launcher is the chosen experience; bundling
the runtime + native deps + code-signing / notarization isn't worth it for the
current audience. Revisit only if shipping to people who won't run a one-liner.

## Update experience — the headline

- [x] **`jaeger update`** — one command, in place, **no git required** for the
  clean curl/product install (downloads + applies a release tarball). Dev
  clones still fast-forward via git. *(done)*
- [x] **Check for updates** — `version_check.latest_version` queries GitHub
  tags, numeric-compares to local `__version__`. Shared by update + doctor. *(done)*
- [x] **Download + apply** — fetch the target tag tarball, copy the PRODUCT
  allowlist, swap each item in place (per-item `os.replace`, recoverable via
  the kept prev dir), preserve `.venv/` + `.jaeger_os/`; reinstall deps **only**
  if `requirements.txt` / `pyproject.toml` changed. *(done)*
- [ ] **Surface availability in-app** — tray menu item + a Jaeger Studio banner:
  "Update available 0.6.x → Install". *(still open — the in-app surface)*
- [~] **Channels / pinning** — `jaeger update --ref TAG` pins a version; honour
  `JAEGER_REF` in the env. Stable-vs-latest channel naming not yet formalised.
- [x] **Rollback** — previous product kept in `.update-prev/`;
  `jaeger update --rollback` restores it (one level). *(done)*

> Note: trimmed the git-archive tarball `jaeger update` fetches — untracked
> `avatar/.build/` (93 MB derived Swift cache) **and** `.gitattributes
> export-ignore` on `dev/` + `.github/`. A product-only Release asset could
> shrink it further still.

## Uninstall

- [ ] **`jaeger uninstall`** — remove the framework; prompt to keep or wipe
  instance state (`~/jaeger/.jaeger_os/`). Mirrors the install's clean split.

## Plumbing

- [x] **Version source of truth** — `jaeger_os.__version__` (now `0.5.2`), and
  pyproject reads it dynamically (no second source). Bump to `0.6.0` when 0.6
  ships.
- [x] **Latest-version lookup** — `jaeger_os/core/version_check.py`, shared by
  the updater + `doctor`. *(done)*
- [x] **`jaeger doctor`** reports current vs. latest (CLI only — the agent's
  `self_check` stays network-free). *(done)*

---

## Also queued (not this theme — don't lose them)

- **Tier-1 `core` role** in the app framework (`JaegerApp` hosts the brain as a
  first-class main-thread core, not a stubbed node) — design already drafted;
  aligns JROS to the demos.
- **JP01 hardware adapter layer** (mic-in / RGB-out / speaker-out streaming on
  the device, riding the `MediaFrame` / `ZmqBus` seam declared in 0.5.0) — see
  [`../hardware/`](../hardware/). HISTORY flagged this for 0.6/0.7; the
  install/update theme takes 0.6, hardware likely lands 0.7.

## Delivered on this branch

The install/update **theme** work, then the agentic pipeline that landed
alongside it. See STATUS.md for the runtime detail.

**Install / update theme:**

- [x] **Update mechanism — clean-install download/apply** (this commit) — the
  theme headline's core: on a no-`.git` curl/product install, `jaeger update`
  downloads the target release tarball and swaps the PRODUCT files in place,
  keeping `.venv/` + `.jaeger_os/`; `--ref` pins, `--rollback` reverts, deps
  reinstall only when they change. Latest-version lookup (`version_check`) is
  shared with `jaeger doctor`'s current-vs-latest readout. Untracked 93 MB of
  derived Swift `.build/` (it had been dragged into every clone + install).
  *Remaining for the theme:* in-app update surface, Native Mac app, uninstall.
- [x] **`jaeger autostart`** (this commit) — opt-in boot/login service so a
  deployed unit runs unattended after reboot/power-loss. macOS LaunchAgent +
  Linux `systemd --user` (+ linger). Manual `jaeger` start unchanged.
- [x] **README accuracy + lighter update download** (this commit) — `jaeger`
  documented as canonical, `jaeger update` upgrade path, character-pick wizard,
  badge bump; `.gitattributes export-ignore dev/` trims the release tarball.

**Agentic (off-theme, operator-prioritised):**

- [x] **Person index** — profiles of people the agent knows (name/handles/access/
  likes/facts), grown like skills; folds into the admin trust model.
- [x] **Admin trust + channel-agnostic polish** — per-channel admin gating,
  in-channel approvals + `/mode` slash + receipt ack shared across
  telegram/discord/imessage.
- [x] **Autonomy modes (`ask` / `scoped` / `auto`)** — execution autonomy as a
  switchable mode (default `scoped`): agree the plan up front, then run the loop
  without per-action prompts; reach out (`clarify`) only when missing info or
  out of agreed scope. `/ask` `/scoped` `/auto` on every channel.
- [x] **Packaging — editable install** (`3f4b693`) — JROS is a proper package
  again (`uv pip install -e .`), code unmoved. Real `jaeger --version`, deps +
  version single-sourced. **Partially delivers the Update headline below**:
  `jaeger update` = `git pull --ff-only` + editable reinstall.
- [x] **Entry-point unification** (`dc1809f`) — one `jaeger` dispatcher behind
  the console script + the `./jaeger` wrapper.
- [x] **Model defaults from a clean 7-model benchmark** (`ea8c309`) — `normal`
  → e4b (voice), `high`/`deep-sleep` → 26B-A4B QAT, 12B = voice backup; bench
  tooling un-rotted. New-instance defaults (`DEFAULT_MODEL` + host_recommendation)
  aligned to match.
- [x] **Skill self-improvement loop** (`4be104b`, `4a5b345`, + this commit) —
  per-use notes journal → threshold/agent trigger → measured Deep Think rewrite
  (smoke + benchmark, keep-if-better) → revision log. **On by default (opt-out)**;
  `jaeger skills notes` / `revisions` surface it.
