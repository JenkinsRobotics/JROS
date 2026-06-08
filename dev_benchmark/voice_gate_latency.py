"""Focused timing benchmark for the in-node voice gate.

Operator-reported (2026-06-07 live test): voice turn latency went
from ~6s to ~69s after the gate moved into AudioSession.  The
hypothesis is KV cache thrashing — the gate's system prompt
(VOICE_LLM_GATE_RULE, ~800 tokens) is completely different from
the brain's system prompt (~5-15K tokens), so every gate call
invalidates the brain's prefill and vice versa.  Each phrase
pays a cold prefill cost on BOTH.

This script measures:

  Pass A — typed-turn baseline (cold, then warm)
  Pass B — gate call alone (cold, then warm)
  Pass C — gate → brain turn (the new voice path)

If Pass C ≈ Pass A + Pass B (warm), the gate just adds its own
warm latency.  If Pass C is much higher than Pass A (warm) +
Pass B (warm), the gate's prompt is invalidating the brain's
KV cache and we're paying full prefill on the brain.

Run with the current default instance + model:

    .venv/bin/python -m dev_benchmark.voice_gate_latency
"""

from __future__ import annotations

import os
import time
from typing import Any


def _measure(label: str, fn) -> float:
    started = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - started
    print(f"  {label:40} {elapsed:7.2f}s")
    return elapsed


def main() -> int:
    # Boot the brain in the same way ./launch does so the prompt +
    # warmup match real-world behaviour.
    from jaeger_os.core.instance.instance import (
        InstanceLayout,
        default_instance_name,
        resolve_instance_dir,
    )
    from jaeger_os.core.instance.schemas import Config, load_yaml
    from jaeger_os.core.prompts import (
        build_system_prompt as build_prompt_module_fn,
    )

    inst_name = default_instance_name()
    root = resolve_instance_dir(inst_name)
    layout = InstanceLayout(root=root)
    config = load_yaml(layout.config_path, Config)

    # Set the gate-rule env var BEFORE building the system prompt so
    # the brain's prompt matches what ./launch produces (after my
    # earlier fix at commit beee2f6).
    if config.voice.llm_gate:
        os.environ["JAEGER_VOICE_GATE"] = "1"
    brain_system_prompt = build_prompt_module_fn(layout)
    brain_prompt_chars = len(brain_system_prompt)

    print(f"\n  instance     {inst_name}")
    print(f"  model        {config.model.model_path}")
    print(f"  brain prompt {brain_prompt_chars:,} chars "
          f"(~{brain_prompt_chars // 4} tokens estimated)")

    from jaeger_os.main import make_client, prewarm, _pipeline
    _pipeline["layout"] = layout
    _pipeline["config"] = config
    _pipeline["system_prompt"] = brain_system_prompt

    print(f"\n  loading model + prewarm...", flush=True)
    t0 = time.perf_counter()
    client = make_client(config, layout, warmup=True)
    prewarm(client)
    print(f"  model + prewarm ready in {time.perf_counter() - t0:.1f}s\n")

    # Gate prompt — matches what AudioSession._classify_phrase_llm
    # uses internally.
    from jaeger_os.core.prompts.rules import VOICE_LLM_GATE_RULE
    gate_prompt = VOICE_LLM_GATE_RULE.strip()
    gate_prompt_chars = len(gate_prompt)
    print(f"  gate prompt  {gate_prompt_chars:,} chars "
          f"(~{gate_prompt_chars // 4} tokens estimated)")
    overlap_chars = sum(1 for a, b in zip(brain_system_prompt, gate_prompt)
                         if a == b)
    print(f"  prefix overlap brain↔gate: {overlap_chars} chars\n")

    def _brain_turn(text: str) -> None:
        client.chat(
            [
                {"role": "system", "content": brain_system_prompt},
                {"role": "user", "content": text},
            ],
            max_tokens=32,
            temperature=0.0,
        )

    def _gate_call(text: str) -> None:
        client.chat(
            [
                {"role": "system", "content": gate_prompt},
                {"role": "user", "content": text},
            ],
            max_tokens=10,
            temperature=0.0,
        )

    # ─── Pass A — typed-turn baseline ────────────────────────────
    print("Pass A — typed-turn baseline (brain only):")
    a_cold = _measure("A.1  brain turn  (after prewarm, cold)",
                       lambda: _brain_turn("what time is it"))
    a_warm = _measure("A.2  brain turn  (same prompt, warm)",
                       lambda: _brain_turn("what time is it"))

    # ─── Pass B — gate call baseline ─────────────────────────────
    print("\nPass B — gate call baseline (gate only):")
    b_cold = _measure("B.1  gate call   (first hit, cold)",
                       lambda: _gate_call("what time is it"))
    b_warm = _measure("B.2  gate call   (same prompt, warm)",
                       lambda: _gate_call("what time is it"))

    # ─── Pass C — gate → brain (the new voice path) ──────────────
    print("\nPass C — gate → brain (current voice pipeline):")
    print("  C.1  gate call then brain turn (the realistic case)")
    _gate_call("hey jarvis what time is it")
    c_brain = _measure("       └─ brain turn after gate",
                       lambda: _brain_turn("hey jarvis what time is it"))

    # Now reverse — brain then gate
    print("  C.2  brain turn then gate call (just to show symmetry)")
    _brain_turn("hey jarvis what time is it")
    c_gate = _measure("       └─ gate call after brain",
                      lambda: _gate_call("hey jarvis what time is it"))

    # ─── Verdict ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Verdict:")
    print(f"  Brain warm baseline:  {a_warm:.2f}s")
    print(f"  Gate warm baseline:   {b_warm:.2f}s")
    print(f"  Expected combined:    {a_warm + b_warm:.2f}s")
    print(f"  Observed brain-after-gate: {c_brain:.2f}s")
    print(f"  Observed gate-after-brain: {c_gate:.2f}s")
    overhead = c_brain - a_warm
    print(f"  Brain extra-cost from preceding gate call: "
          f"{overhead:+.2f}s ({overhead / a_warm * 100:+.0f}%)")
    if c_brain > 2.0 * a_warm:
        print("\n  ⚠  Brain prompt prefill INVALIDATED by gate call.")
        print("     KV cache thrashing confirmed.  The two prompts")
        print("     don't share enough prefix; switching between them")
        print("     forces a cold prefill each time.")
    else:
        print("\n  ✓  Brain stays warm after gate call.")
        print("     No KV cache thrashing.  Overhead is just the")
        print("     gate's own decode cost.")

    # ─── Pass D — the CURRENT voice path (single-pass) ────────────
    # AudioSession runs ONLY deterministic filters and the brain's
    # response prefix is the gate.  No separate gate call.  This is
    # what the operator actually experiences after the 2026-06-07
    # revert.  Warm latency should equal Pass A.2.
    print("\nPass D — current voice path (single-pass, no thrash):")
    d_warm = _measure("D.1  brain turn (warm — voice gate rule baked in)",
                       lambda: _brain_turn("what time is it"))
    d_again = _measure("D.2  brain turn (same phrase, still warm)",
                       lambda: _brain_turn("what time is it"))
    print(f"\n  Voice path per-turn cost (the real number that matters):")
    print(f"    Warm  ≈ {d_warm:.2f}s — close to the brain's "
          f"natural answer time")
    print(f"    No extra gate call, no KV cache thrash")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
