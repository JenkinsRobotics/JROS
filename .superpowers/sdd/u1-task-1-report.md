# U1 Task 1 report — chassis onto transport, app/bus deleted

Status: DONE (with one scope deviation from the brief, explained below — no
BLOCKED condition, nothing genuinely used was broken).

## Files changed

**Production:**
- `jaeger_os/app/app.py` — bus import → `from jaeger_os.transport import Bus,
  InProcBus`; `_build_bus` now always does `self.bus = InProcBus()` (ZMQ
  branch + `Broker`/`ZmqBus` import/construction removed); `registry`
  constructor param and `self.registry` removed.
- `jaeger_os/app/__init__.py` — **not named in the brief, but had to change**:
  the package `__init__.py` itself did `from .bus.api import Bus,
  MessageRegistry, RawMessage` / `from .bus.inproc import InProcBus` — an
  unconditional import that runs on every `import jaeger_os.app`. Repointed
  `Bus`/`InProcBus` to `jaeger_os.transport`; dropped `MessageRegistry`/
  `RawMessage` from the re-export and `__all__` (grepped — nothing outside
  this file imported them from the package top level). Updated the module
  docstring's "Copy-ability" claim (it previously said modules import only
  stdlib/pyyaml/pyzmq **RELATIVELY** — no longer true now that the bus is
  the shared `jaeger_os.transport`, so the docstring now says so explicitly
  instead of quietly lying) and the `Layout` listing (`bus/` and `child.py`
  rows removed).
- `jaeger_os/core/messages.py` — dropped the `MessageRegistry` import, the
  `MESSAGES = MessageRegistry(); MESSAGES.register_all([...])` block, and
  `NodeHealth`/`LogLine` imports (only used by that block). Kept all 11
  `@dataclass` message definitions untouched. `__all__` no longer exports
  `MESSAGES`.
- `jaeger_os/core/windowed.py` — dropped `from jaeger_os.core.messages
  import MESSAGES` and the `registry=MESSAGES` kwarg at the `JaegerApp(...)`
  call site.
- `jaeger_os/interfaces/tui/__main__.py` — **no change needed**: unlike the
  brief's assumption, this file's `JaegerApp(_REPO_ROOT).boot()` call never
  had a `registry=MESSAGES` kwarg (grepped to confirm before touching it).

**Deleted:**
- `jaeger_os/app/bus/` (`__init__.py`, `api.py`, `inproc.py`, `zmq.py`) —
  `git rm -r`, per the brief.
- `jaeger_os/app/child.py` — **deviation from the brief's file list.** This
  is a third production file that hard-depended on `app.bus` (the map said
  "only two": `app.py` and `core/messages.py` — it missed this one). It was
  the subprocess-node ZMQ bootstrap helper (`child_main`, used only via
  `if __name__ == "__main__":` in a node module run as a subprocess). Grepped
  the whole repo: no `jaeger.toml` anywhere ever sets `[bus] backend =
  "zmq"` or a `[[node]] backend = "subprocess"` — both shipped manifests are
  `inproc`/`thread`-only, so this file was exactly as dead as the
  chassis-ZMQ path itself, just one level removed. Its only consumer was a
  test (see `_worker_node.py` below). Repointing it onto transport's
  `ZMQBus`/`make_bus_for_node` instead of deleting it was considered, but
  transport's ZMQ wire codec requires msgspec `Struct` topic schemas — it
  would mean converting `NodeHealth`/`LogLine` (and the test's `TestCmd`/
  `TestEcho`) to msgspec, which the brief explicitly puts out of scope for
  U1 ("Do NOT convert them to msgspec"). Deleting was the scope-respecting
  choice, consistent with the brief's own permission to delete the chassis-
  zmq test "if it only tested the dropped path."
- `dev/tests/jaeger_os/app/_worker_node.py` — the subprocess-test fixture
  module; its only consumer (`test_subprocess_node_roundtrip_crash_and_
  supervised_restart`, see below) is deleted, and it depended on
  `app.bus.api.MessageRegistry` + `app.child.child_main`, both gone.

## Test files (all ~9 handled)

- `dev/tests/jaeger_os/app/test_app_format.py` — repointed the plain
  `InProcBus` import to `jaeger_os.transport`; dropped the now-unused
  `HealthCache`/`SubprocessHandle` imports. Removed
  `test_registry_roundtrip_and_fallback` and
  `test_registry_refuses_topicless_dataclass` (MessageRegistry is gone),
  replaced with `test_inproc_bus_delivers_plain_dataclass_messages_untouched`
  (asserts the delivered object *is* the published object — proves the
  pass-through contract, not just equality). Removed the `zmq_stack` fixture
  and `test_subprocess_node_roundtrip_crash_and_supervised_restart` (the
  chassis-zmq end-to-end test — now tests only dropped code), replaced with
  a comment explaining why and pointing at
  `test_manifest_refuses_subprocess_on_inproc_bus` (unaffected — pure
  manifest.py validation, no app.bus dependency) as the surviving coverage
  for the subprocess+bus-backend contract. Dropped the now-dead `REPO`
  path constant.
- `dev/tests/jaeger_os/core/test_messages.py` — dropped `MESSAGES` import,
  added `jaeger_os.transport.InProcBus`. Replaced
  `test_registry_round_trips_a_chat_message` +
  `test_unregistered_topic_decodes_to_rawmessage_not_drop` (both exercised
  the deleted ZMQ registry) with one real publish→subscribe delivery test,
  `test_chat_message_round_trips_over_the_bus`. `test_topics_follow_act_
  sense_convention` untouched.
- `dev/tests/jaeger_os/core/test_session_trust.py`,
  `dev/tests/jaeger_os/plugins/test_messaging_shared.py`,
  `dev/tests/jaeger_os/agent/test_approval_routing.py`,
  `dev/tests/jaeger_os/agent/test_bridge.py` — mechanical import swap only
  (`from jaeger_os.app.bus.inproc import InProcBus` → `from
  jaeger_os.transport import InProcBus`); no assertions touched.
- `dev/tests/jaeger_os/interfaces/test_windowed_app.py` — import swap;
  dropped `MESSAGES` from the `from jaeger_os.core.messages import ...`
  line and the `registry=MESSAGES` kwarg in
  `test_windowed_manifest_boots_agent_core_over_chassis`. Also **added** an
  assertion there (`assert isinstance(app.bus, InProcBus)`, `InProcBus` now
  being transport's) — this is the "focused unit test that builds JaegerApp
  from jaeger.windowed.toml and asserts app.bus is a transport.InProcBus"
  Step 7 asks for; it already existed as the right host for it, so no new
  test file was needed.
- `dev/tests/jaeger_os/interfaces/test_bridge.py` — checked, no `app.bus`
  reference; left untouched (brief's "~9" list included it but it wasn't
  actually affected).
- No test imported `BusOverflowError` — the `BusOverflowError` →
  `InProcBusOverflowError` rename in the brief was a no-op for this repo
  (only `app/bus/inproc.py` itself, since deleted, referenced the name;
  transport already has its own `test_inproc_bus.py` covering
  `InProcBusOverflowError`).

## Grep-clean confirmation

`grep -rn "app\.bus\.\|MessageRegistry" jaeger_os/ --include=*.py` → no hits.
`grep -rn "app\.bus\|app/bus" jaeger_os/` → one hit, in `app/__init__.py`'s
own docstring prose (not code). `grep -rn "JaegerApp("` across the repo →
no remaining `registry=` kwarg anywhere. `jaeger_os/app/bus/` directory
removed from disk entirely (deleted the leftover `__pycache__` too).

## Test suite result

Full `dev/tests` is 2565 collected tests. A single monolithic
`pytest dev/tests -q` run is **not reliable** on this machine — it dies with
no traceback partway through (observed at ~64-73% across two attempts),
matching exactly the brief's warned F1-class native-teardown flake
(llama.cpp/ggml Metal backend aborts in a C++ static destructor during
process exit after enough native-library state has accumulated across many
tests in one process). I independently reproduced the identical
`GGML_ASSERT ... ggml_metal_device_free` abort with a bare one-off script
that only booted+shut down a single `JaegerApp`/`AgentCore` — zero involvement
of anything I changed. Pre-existing, unrelated to this task.

To get full coverage, ran the suite in four batches (routing around the
flake, `-p no:cacheprovider` as suggested), covering every one of the 2565
collected tests exactly once:

- `dev/tests/jaeger_os/app dev/tests/jaeger_os/core` → **1015 passed**
- `dev/tests/jaeger_os/interfaces` → **249 passed**
- `dev/tests/jaeger_os/agent dev/tests/jaeger_os/plugins` → **634 passed**
- everything else (`cli`, `hardware`, `main`, `nodes`, `personality`,
  `personas`, `skill_tree`, `skills`, `timeline`, `transport`, top-level
  `test_*.py`) → **657 passed, 10 skipped**

Total: **2555 passed, 10 skipped, 0 failed** — matches the full collection
count. The touched areas (`app`, `core`, `interfaces`, plus `agent`/
`plugins` since I edited files there too) are all green.

## Windowed boot smoke

`python -c "import jaeger_os.core.windowed; print('windowed import OK')"` →
OK.

Headless boot check (real model load, not the monkeypatched pytest path):
built `JaegerApp('jaeger.windowed.toml')`, called `.boot()`, and confirmed
`type(app.bus)` is `jaeger_os.transport.inproc_bus.InProcBus` and
`isinstance(app.bus, transport.InProcBus)` is `True`, then `.shutdown()`
printed "shutdown complete" cleanly. The process then hit the same
pre-existing F1 native-teardown abort at final process exit (after Python
had already finished and printed its own shutdown message) — expected,
unrelated, not a boot/bus problem.

The pytest-level version of this same check
(`test_windowed_manifest_boots_agent_core_over_chassis` in
`test_windowed_app.py`, model boot monkeypatched so it's fast) also passed
and now explicitly asserts `isinstance(app.bus, InProcBus)`.

## Concerns / notes for the operator

1. **Scope deviation**: deleted `jaeger_os/app/child.py` and
   `dev/tests/jaeger_os/app/_worker_node.py`, neither named in the brief's
   file list. Both were dead-in-production (chassis-ZMQ subprocess
   bootstrap; no manifest in this repo ever used it) and both hard-depended
   on the deleted `app/bus/`. Also had to touch `jaeger_os/app/__init__.py`
   (the package's own `__init__.py` re-exported from `app/bus/` — not
   called out in the brief's "only two files" map either). None of these
   were "genuinely used" paths per the map's own low-risk-scope reasoning
   (chassis-ZMQ unexercised, both toml configs are `inproc`) — this is a
   map gap, not a live capability being cut. Flagging per your instruction
   to note (not silently break) anything the map got wrong.
2. Left `JaegerApp._broker` (always `None` now) and its two dead
   conditionals in `shutdown()`/`_make_handle()` alone — narrow scope, not
   asked for, harmless dead code; worth a follow-up cleanup pass whenever
   convenient.
3. Did not run the routing bench (≥79/81 gate) — the brief said "run
   separately" and it wasn't in the Verify section given for this task.
4. `git add -A` was **not** run — per your memory note (never push/tag
   without explicit OK is separate, but per "milestone commits" convention
   I staged only the files this task touched, not `.superpowers/` which is
   untracked scratch/plan material from this session).

## Commit

Files staged and committed (see git log) — see the assistant's final reply
for the SHA.
