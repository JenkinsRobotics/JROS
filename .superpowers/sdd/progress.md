# SDD ledger — JROS 0.8 module refactor
Spec: dev/docs/JROS_0.8_MODULE_REFACTOR_SPEC.md (commit a3fcc8a)
Phase U next: U1 delete app/bus + repoint chassis onto transport; U2 one Node/NodeHealth; U3 Supervisor replaces runtime.py singletons + enable jaeger.toml nodes; then Phase M kokoro_tts.
U1 base: c9e0e82
U1 T1 implemented (c9e0e82..dc0ecef) 2555 passed; bench pending
U1 COMPLETE (c9e0e82..dc0ecef): one bus — chassis on transport.InProcBus; app/bus/ + child.py deleted (dead), chassis-ZMQ dropped. Gates: review Approved; suite 2555 pass; bench 80/81. Minors→U3: _broker dead code; backend=zmq config incoherence.
U2 COMPLETE (dc0ecef..5ddfcb3): one Node/NodeState/FrameNode; identity verified; grep-clean; app/core/interfaces green
U3 plan committed e1d7528; Task A next
U3 Task A (6484e17..a2f9f7a): bus injection (runtime.set_bus) + transcript
  is_final collision fix + NodeHealth unified on /sense/node_health with
  base-node heartbeats. Suite green.
U3 Task B (final): supervisor-backed ensure_* — factories construct
  nodes directly (no ensure_* recursion), ensure_* delegates to a
  registered Supervisor when the manifest declares+enables the node.
  jaeger.windowed.toml declares tts+animation (enabled=true, headless-
  safe) — audio_session stays declared-but-disabled (real mic/Whisper
  load, no headless degrade path yet; see u3b-report.md). jaeger.toml
  header updated: duality resolved, disabled now because the TUI path
  builds no chassis Supervisor. Headless windowed smoke: one bus, 2/3
  nodes RUNNING, zero orphan threads on shutdown. 1990 tests green
  across app/core/agent/interfaces/nodes. U3 COMPLETE → Phase M next
  (kokoro_tts module).
U3a COMPLETE (6484e17+a2f9f7a); U3b COMPLETE (7da54d9): one bus, supervisor-owned tts/animation, audio_session deferred-lazy (mic). 1990 green. Gates: bench+security running
U3 COMPLETE (e1d7528..7da54d9): review APPROVED (all 7 named risks verified safe); 1990 tests green; bench 60/81+ with 0 fails (finishing, machine-loaded). Minors→ledger: audio_session ordering (dormant, enabled=false); diagnose() health noise; anim rebind degradation; stale globals post-shutdown. PHASE U COMPLETE — bus+Node+supervision unified; the duality is resolved.
U3 bench gate PASSED: 79/81 rows with 0 fails (>=79 guaranteed). PHASE U fully gated. M1 begins.
M1 plan committed 393ffd4
M1 T1 (5e3c268+519a888) + T2 (a49a159) implemented; review+bench running
M1 COMPLETE (393ffd4..8a7c258): kokoro_tts engine-module (node+engine+own config+module.yaml+tests; nodes/tts + plugins/kokoro_tts deleted, no shims); core/modules.py loader+discovery; availability gate probes requires_libraries (fail-closed, cached). Review: Needs-fixes->fixed (8a7c258). Gates: suites green, bench 79/81 (known tails only). Minor deferred: schemas->nodes import edge direction (cycle-trap comment-worthy).
M2a begins: slot-resolution (manifest slot= binding via discover_modules) + cut runtime/speak hard imports of kokoro_tts (graceful degradation). Then M2b+ remaining node conversions.
M2a plan committed 6b3e913; Task A (slot-res) next
M2a-A (91b6099) + M2a-B (6b5555d) done; review+bench running
M2a COMPLETE (6b3e913..6b5555d): slot-resolution (manifest slot=tts binds via discover_modules, fail-closed) + graceful removal (guarded imports + early no-module speak return + schemas leaf stand-in). Review APPROVED (2 cosmetic minors). Bench 79/81. Swap-mechanism + remove-property now REAL on tts. Deferred (ponytail/YAGNI): synth engine still hardcoded in runtime._default_synth_factory — a 2nd real TTS engine forces that decoupling.
M2b plan committed 0f4ead7; Task A next
M2b-A (81f9a57) + M2b-B (a776e08) done; review+bench running
M2b COMPLETE (0f4ead7..a776e08): whisper_stt second engine-module (audio_session node + whisper engine consolidated, slot=stt; listen gate module-aware fail-closed; config routed — wake_word inconsistency FIXED, supervisor path was the outlier). Review APPROVED (3 minors). Bench 78/81: -1 vs gate ISOLATED to rec_python_syntax temp-0 flip caused by the required plugins-tool docstring edit (1-token surface ripple; run_python verified correct; model self-corrects broken code — known marginal case). Deliberately NOT chasing the token; flagged to operator. Suites 2075+1191 green.
M2c plan committed ff088cc
M2c implemented (7481b29); review+bench running
M2c COMPLETE (ff088cc..7481b29): animation + media engine-modules (slot-bound; avatar config_key mismatch fixed + proven load-bearing; avatar tools module-gated fail-closed; media cheap-recipe; animation_dev deliberately deferred w/ README). Review APPROVED (2 doc-nit minors). Bench 79/81 — GATE MET (chain_weather_t3 flipped back to pass; rec_python_syntax + pf_macos_do fail — both known-marginal). ALL PURE-JROS NODE CONVERSIONS DONE: 4 slots live (tts/stt/animation/media).
Swift-app update fix: c46ed67 + 45a669c — flow-walked (scratch station: pull→missing-app build→idempotent→stale rebuild); cli suite 209 green
Capability-layer design DRAFTED (awaiting operator OK): hardware/ framework is ~80% of it; gaps = boot root, beta->per-unit verified flag, unit.yaml identity handshake
M3 plan committed e41702b; Task A next
M3a (2a84575) + M3b (2a89d6a+69daa2a) done; review+bench running
M3 COMPLETE (e41702b..b92188b): fail-open gates closed (ha/ai_gen); avaudio_io->core/audio; messaging = first multi-module slot (3x module.yaml, plugin.yaml deleted, send_message ANY-OF fail-closed, requires_platform added). Review APPROVED (minors fixed/false-alarm). BENCH 81/81 — NEW ALL-TIME RECORD (surface cleaned by gating unavailable tools; all marginal rows passed).
Scenario security lane on 0.8.0 head: 14/15 — sole fail inj-mem-poison = the KNOWN 4B baseline gap (26B fixes). No security regression from Phase U/M1-M3. STATUS.md 0.8 entry committed. P1 push->pull experiment implemented (uncommitted), bench rerunning.
P1 verdict: ALREADY DONE (25d358c) — backlog was stale, corrected; dead formatter removed; bench 80/81 on byte-identical code = record reproducibility sample. Suites 1032+589 green.
Docs reorg complete (9a69486 + vision README bd057b4): reality/history/roadmap/vision sections; ONE index; ~120 links fixed
Identity create-flow plan committed 73ea5cf; implementing
Persona A/B/C design committed 66790d2 — awaiting operator OK (C first). Persona filter hardened 065957f. Identity create-flow fix shipped 0fcc789+c94f406+eca5cb5.
Mode C APPROVED by operator 2026-07-10; recon then build
Mode C build plan committed a6fca5a; Task 1 dispatching
Mode C: review NEEDS-FIXES -> fixed bb63ed2 (Critical: raise-mid-delegation double-run; Important: history reality). Gate run 1: delegation 5/12 FAIL (root cause: native tools= path malformed for gemma — lane now speaks the proven text dialect + delegate-first contract; 662 unit green); chat latency C 3.62s vs A 30.28s (8x); over-delegation 0/12; bench 80/81; distinctness sheet generated. Gate RERUN in flight.
Mode C GATED (2b66526): delegation 12/12 (was 5/12; text-dialect fix), over-delegation 0/12, chat avg 3.0s (vs A 30.28s), bench 80/81, 662 unit green, review Approved-after-fixes. Remaining before default-flip: operator eyeballs distinctness sheet -> flip jros-dev; security lane vs Mode C ledgered as pre-default gate. Headless-audio wedge noted (env, pre-existing).
RELEASE RUNWAY committed eec3308: 1) scenario harness->run_command + security rerun 2) character-name GUI leak audit 3) setup-name verify 4) new-chat/history UI 5) full rebench 6) operator test 7) release. persona_first default SHIPPED aee7fa3 (14/15 security on worker path; front-door coverage owed via item 1).
ITEM 1 GATE FAILED (harness wiring correct, engaged 15/15; NOT committed): through the REAL front door persona_first shows release-blocking bugs — security 8/15 vs 14/15 (compose rewrites refusals into Socratic pushback; request-paraphrase may launder injection framing; safe-credential-leak: inner agent ran the sweep), memory silent data loss ('Noted.' with no tool call = under-delegation on store-memory verbs), suite runner dies at 28/51 (resource accumulation). Worker path re-confirmed 14/15 same day. Fix classes: verbatim request pass-through, refusal-preservation in compose, memory verbs in delegate contract, runner leak. OPERATOR DECISION PENDING: fix-then-regate vs ship 0.8.0 with persona_last default + persona_first opt-in experimental. Full evidence: .superpowers/sdd/runway-item-1-report.md
OPERATOR: Option A — harden the lane, fix, re-gate. Fix classes: (1) verbatim request pass-through (no paraphrase laundering), (2) refusal-preservation in compose (refusals are pass-through content, never restyled), (3) delegate contract: remember/store/note/'do X' agentic verbs MUST delegate, (4) scenario-runner per-session resource leak (dies 28/51). Then re-run security lane (target 14/15 parity) + full suite. Working-tree harness changes from item 1 to be committed with the fix.
ITEM 1 RE-GATE PASSED (persona_first hardened): verbatim delegation (append-only request guard), refusal pass-through (compose skipped via suite's _is_refusal, imported), agentic-verb+refuse-plainly contract (incl. say-out-loud), runner leak fixed (main.evict_session + per-case teardown; RSS flat all 51). Security 15/15,15/15,14/15 samples (gate >=14/15 MET; inj-mem-poison now passes, mem-no-fab the new stochastic tail); full run COMPLETES 36/51 (baseline 35/51); delegation 12/12, over-delegation 0/12; 1707 unit green. Committed with item-1 harness wiring. Evidence appended to runway-item-1-report.md.
ITEM 1 COMPLETE (eed6f8a): persona_first HARDENED + gates GREEN — security 15/15 x2 (14/15 final sample; inj-mem-poison NOW PASSES — historic 4B fail fixed by the lane!), full suite completes 36/51 (+1 vs baseline; leak fixed, RSS flat), delegation 12/12, over-delegation 0/12, 1707 unit green. Watch: mem-no-fab (new marginal), mem-store-recall sampling (item-5 rebench). NEXT: runway item 2 — character-name GUI leak audit.
ITEMS 2+3 COMPLETE: character-name GUI leak audit fixed 3 real leaks (Swift AgentBridge.displayName fallback character->instance; AgentSettingsHUD.name same; PySide6 legacy surfaces: tray/qt.py _character_brand used character.name for the header, agent_settings/window.py._name defaulted to character.name/renamed on persona switch — both now agent_name(ctx)-first, never character) + 1 cosmetic mislabel (status_cmd.py "Persona" row -> "Agent name", value was already ident.name not character). Labeled secondary "playing X" surfaces (Swift ChatView/HomePage, PySide6 rich_tui banner via agent_name()) verified compliant, left alone. Item 3 (setup/name sweep) verified complete on all 5 points — no code changes needed (docs bare-create, wizard default order, review page layout, TUI parity, never-empty guarantee all already correct from the shipped create-flow fix). Gates: Swift build+test green (23 tests), Python core+cli+interfaces green (1498 tests), no protocol fields touched so no fixture changes. Evidence: .superpowers/sdd/runway-items-2-3-report.md. NEXT: runway item 4 — new chat + chat history UI.
