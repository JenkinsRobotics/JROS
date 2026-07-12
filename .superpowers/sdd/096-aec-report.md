# 0.9 — AEC decoupling (the last pre-tag contract fix)

Source: canonical clones at `/Users/jonathanjenkins/GITHUB/{JaegerOS,
JaegerAI,JaegerKokoroTTS,JaegerWhisperSTT}`, all starting from pushed
`master`. **Zero pushes** — every commit below is local-only. All gates
run in scratch venvs under the session scratchpad; canonical clones
only ever touched via edits + (pending) `git commit`.

## Status: FIXED, all gates green

## 1. Where the coupling actually lived

Read the real call chain before touching anything. `jaeger_whisper_stt`
itself (`_base.py`, `engine/registry.py`, `two_pass`/`continuous`
pipelines, `node.py`) was ALREADY fully duck-typed — `aec`/
`far_end_buffer` are plain `Any` params, no TTS import anywhere in the
package, and its `requirements.txt`/`module.yaml` never name
`jaeger-kokoro-tts` or `jaeger-ai`. The real violation was one level up,
in **JaegerOS's own orchestration** (`jaeger_os/nodes/runtime.py`):
`_build_audio_session_node` and `ensure_audio_session_node` both called
`ensure_tts_node()` **unconditionally**, before even loading the real
`AudioSessionConfig` — and `ensure_tts_node()` hard-raises
(`RuntimeError`) when no tts-slot module is installed at all. So
*building an STT audio session* — regardless of whether barge-in/AEC
was even wanted — required a TTS engine to exist. `AudioSession.build()`
(`core/audio/session.py`) itself was already mostly decoupled (`tts_synth:
Any = None`, degrades gracefully) — it just reached into a TTS-shaped
object's `.reference_buffer` attribute rather than accepting an opaque
provider directly.

## 2. The seam

`jaeger_os/core/audio/reference_buffer.py` gained
`FarEndReference` — a `Protocol` (`pop_frame(n)`/`clear()`) that
`ReferenceBuffer` already satisfied structurally; re-exported from
`core/audio/__init__.py`. `AudioSession.build()`'s `tts_synth` param
became `far_end: FarEndReference | None` — it no longer reaches into a
TTS object at all, just accepts whatever provider (or `None`) the
caller hands in. `nodes/runtime.py` gained `_resolve_far_end_provider()`
— checks `discover_modules().get("tts")` (the same discovery primitive
already used for the tts/stt engine-symbol guards) and returns `None`
immediately if no tts-slot module is installed; only if one is,
ensures TTS is running and returns its (created-if-absent) shared
`ReferenceBuffer`. `_default_audio_session_factory` calls this **only
when `config.barge_in` is true** — the unconditional `ensure_tts_node()`
calls were deleted from both `_build_audio_session_node` and
`ensure_audio_session_node`. `JaegerKokoroTTS`'s `KokoroTTS.__init__`
typed its existing `reference_buffer` param as `FarEndReference | None`
(no structural change — it already wrote into whatever buffer was set)
and its docstring now names the seam instead of "the STT plugin's AEC".
`JaegerWhisperSTT` needed **zero functional changes**; only stale
docstrings in `node.py` referencing the old
`runtime.get_synth().reference_buffer` coupling were corrected.

## 3. Gates

1. **JaegerOS standalone** — fresh py3.11 venv, `pip install -e .`,
   `python -m pytest dev/tests`: **279/279 passed** (bare `pytest` hits
   an unrelated rootdir-resolution quirk in this sandbox — irrelevant
   once invoked as `python -m pytest`, same result either way once that's
   worked around).
2. **JaegerKokoroTTS** (jaeger-os + itself, `--no-deps` for the git
   pin, jaeger-os installed editable from the local clone instead):
   **7/7 passed** (module-contract + HF-offline suite).
3. **JaegerWhisperSTT** (same pattern): **6/6 passed**.
4. **JaegerAI** — all four packages installed editable into one venv
   (jaeger-ai's own git-pinned deps swapped for local editable installs
   the same way, third-party deps installed from a filtered
   requirements list): `dev/tests/jaeger_ai/nodes/test_runtime.py`
   (the file directly covering this coupling — 2 existing tests fixed,
   3 new ones added) **27/27 passed**. Full suite (default fast-tier
   marker, `-n 4` xdist — required to dodge a pre-existing sequential-
   pytest hang already documented in `094-split-report.md` gate 1):
   **2384-2387/~2397 passed** across two runs; the only failures are
   `test_bridge.py` (an **intermittent xdist-worker crash** — the exact
   test `094-split-report.md` already named as reproducing identically
   in the real repo's own venv under `-n 2`-`4`; reran alone serially:
   **41/41 passed**, confirming it's a parallelism artifact, not a real
   failure) and `test_sqlite_cross_cutting.py::test_concurrent_reader_
   during_writer` (a pre-existing SQLite threading flake — reran alone:
   13/13 passed with a non-fatal `PytestUnhandledThreadExceptionWarning`;
   `jaeger_ai/core/memory/memory.py` has no connection to `core/audio`).
   Neither failure class touches anything this change modified.
5. **Independence proof** — scratch venv with jaeger-os +
   jaeger-whisper-stt only, `jaeger_kokoro_tts` genuinely un-pip-
   installed (`import jaeger_kokoro_tts` confirmed `ImportError`).
   Script reproduced the OLD bug first (`ensure_tts_node()` raises
   `RuntimeError: no tts-slot module installed`), then proved the fix:
   `_resolve_far_end_provider()` returns `None` cleanly, and
   `jaeger_whisper_stt`'s real module.yaml-declared factory
   (`make_audio_session_node`) constructs a genuine `AudioSessionNode`
   end-to-end with zero TTS involvement. All 7 checks passed.
6. **Voice round-trip smoke, both installed (AEC path active)** — same
   4-package venv, `speexdsp` added so `aec_available()` is real. Drove
   the production call chain (module.yaml factory → `nodes/runtime.py`
   → `_resolve_far_end_provider` → `AudioSession.build` →
   `_build_adapter`) with only the innermost pywhispercpp model
   instantiation stubbed (avoids downloading GB-scale weights in a
   sandboxed run — everything above that leaf, including the real
   discovery, real registry lookup, and real `AECWrapper` construction,
   is genuine). Proved: a real `KokoroTTS` synth started as a side
   effect of `barge_in=True`, a real `ReferenceBuffer` was created, and
   — the actual point — `KokoroTTS.reference_buffer` and the buffer
   `AudioSession` handed to the STT adapter are **the same object**. 9/9
   checks passed. No acoustic measurement attempted, per the brief.
7. **Bench**: not run — no agent/tool-calling/routing path touched;
   this change is entirely inside `core/audio`/`nodes/runtime.py`'s
   session-construction plumbing, invisible to the LLM/tool layer.

## 4. Out-of-scope finding (not fixed, flagged for the operator)

`jaeger_ai/plugins/voice_loop.py` (the standalone `python -m ...
voice_loop` daemon, still wired from `main.py` and the tray UI) has its
own, **separate**, pre-existing STT/TTS construction path that
duplicates the same coupling pattern this task fixed — AND its
`from .whisper_stt import WhisperSTTTwoPass/Continuous` (line ~288/297)
imports a module (`jaeger_ai/plugins/whisper_stt.py`) that **does not
exist** post-split (confirmed: `find` finds nothing, this is a deferred
import inside a function body so the file itself still imports cleanly
but the STT-construction branch would `ModuleNotFoundError` at
runtime). This is unrelated to AEC — a leftover break from the 0.9
engine-module split that nothing in the test suite currently exercises
(not reachable from any passing test). Left untouched: fixing it means
deciding whether this whole legacy daemon path should be repointed at
`jaeger_whisper_stt`/the `AudioSession`/`nodes/runtime.py` machinery
this task just cleaned up, or retired now that `AudioSessionNode` +
the TUI voice path supersede it — an architectural call, not a
mechanical fix, and out of this task's ratified scope.

## 5. Commits (local only, not pushed)

- **JaegerOS**: `core/audio/reference_buffer.py` (+`FarEndReference`),
  `core/audio/__init__.py` (export + docstring), `core/audio/session.py`
  (`tts_synth` → `far_end`, no more reaching into a TTS object),
  `nodes/runtime.py` (`_resolve_far_end_provider`, unconditional
  `ensure_tts_node()` calls removed from both audio-session builders).
- **JaegerKokoroTTS**: `nodes/kokoro_tts/engine.py` (`reference_buffer`
  param typed `FarEndReference | None`, docstring names the seam).
- **JaegerWhisperSTT**: `nodes/whisper_stt/node.py` (docstring
  accuracy — no functional change; the package was already decoupled).
- **JaegerAI**: `dev/tests/jaeger_ai/nodes/test_runtime.py` (2 tests
  fixed to stop asserting the old forced-TTS side effect, 3 new tests
  pin the new gate — `_resolve_far_end_provider` returns None/wires a
  buffer correctly, `_default_audio_session_factory` only touches TTS
  when `barge_in` is true).

## 6. Concerns for the operator

1. §4 above — `voice_loop.py`'s broken `whisper_stt` import needs a
   decision (repoint vs. retire) before that daemon path can work at
   all; independent of this fix.
2. `run_tests.sh`'s xdist auto-detection greps for the literal string
   `-n NUMPROCESSES` in `pytest --help`; pytest-xdist 3.8.0's help text
   is lowercase (`-n numprocesses`), so the script silently falls back
   to serial and hits the known hang. Minor, pre-existing, not part of
   this task — worth a one-line fix separately.
3. Nothing pushed/tagged, per standing instruction.
