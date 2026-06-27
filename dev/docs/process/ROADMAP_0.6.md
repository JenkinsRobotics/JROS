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

## Native Mac app — launcher + launch-at-login

The "feels like a real app" track. Two tiers, both layered on **today's curl
install** (the download is unchanged). Tier 2 — the thin launcher in
`/Applications` — is the ceiling; a full self-contained bundle / DMG is **out
of scope** (note below).

**Tier 1 — launch at login (easy, no bundling)**
- [ ] `jaeger autostart enable|disable` — writes/removes a
  `~/Library/LaunchAgents/` plist that runs `~/jaeger/jaeger`, then
  `launchctl` (un)loads it. **Opt-in** — a local LLM at every login is heavy.

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

- [x] **Version source of truth** — `jaeger_os.__version__` (now `0.5.2`), and
  pyproject reads it dynamically (no second source). Bump to `0.6.0` when 0.6
  ships.
- [ ] **Latest-version lookup** — a "what's the newest published version" query
  the updater + `doctor` share. (Not done.)
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

## Delivered on this branch (agentic — off-theme)

Landed alongside the install/update work; the operator prioritised the agentic
pipeline. See STATUS.md for the runtime detail.

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
