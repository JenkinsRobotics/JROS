"""TUI theme — the Jaeger-OS accent colour.

hermes-agent's reference TUI is amber/gold; Jaeger-OS shifts the same
shade family to **blue** for its own identity. Every piece of brand
chrome — the banner, turn rules, the answer box, the ``❯`` prompt, the
status bar — draws in :data:`ACCENT`.

Semantic colours are deliberately *not* themed: ``yellow`` stays
warning, ``red`` stays error, ``green`` stays success, ``cyan`` stays
the secondary highlight. Only the brand accent moves.
"""

from __future__ import annotations

# Rich style names for the brand accent.
ACCENT = "bright_blue"
ACCENT_BOLD = "bold bright_blue"
ACCENT_DIM = "dim bright_blue"

# prompt_toolkit style token for the same accent (used in the prompt).
ACCENT_PTK = "ansibrightblue"
