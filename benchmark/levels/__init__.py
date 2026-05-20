"""Tiered jaeger_os benchmark suite.

Levels:
  1. routing      — single-turn tool routing accuracy (the canonical bench)
  2. multistep    — single prompt requires multiple tool calls in sequence
  3. multiturn    — multi-turn conversations with shared session history
  4. recovery     — intentional failures; assert the agent recovers / explains

Each level is its own module with a ``run_level(client) -> list[dict]`` entry
point + ``render_markdown(rows) -> str`` renderer. Run one with
``python -m benchmark.run_level <N>``; run all with
``python -m benchmark.run_all_levels``.
"""
