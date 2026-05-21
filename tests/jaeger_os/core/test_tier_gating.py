"""Tier gating — every write/effect tool routes through the permission
policy (audit gap #1).

The 6-tier `core/permissions.py` system is only as good as its
coverage. These tests build the real agent, introspect each registered
tool, and assert the write/effect surface carries a `requires_tier`
decorator — so a `write_file` / `browser` / `send_message` can never
run un-gated again.
"""

from __future__ import annotations

import pytest

from jaeger_os.core.permissions import (
    DenyAllProvider,
    PermissionDenied,
    PermissionPolicy,
    PermissionTier,
    get_tier,
    requires_tier,
    use_policy,
)


def _registered_tools():
    """Build the real agent and return its {name: function} tool map."""
    from pydantic_ai import Agent
    from jaeger_os.main import _register_builtins
    agent = Agent("test")
    _register_builtins(agent, client=None)
    return {n: t.function for n, t in agent._function_toolset.tools.items()}


# ── write / effect tools must be gated ───────────────────────────────


def test_write_and_effect_tools_are_tier_gated() -> None:
    tools = _registered_tools()
    expected = {
        "write_file": PermissionTier.WRITE_LOCAL,
        "append_file": PermissionTier.WRITE_LOCAL,
        "patch": PermissionTier.WRITE_LOCAL,
        "delete_file": PermissionTier.WRITE_LOCAL,
        "execute_code": PermissionTier.WRITE_LOCAL,
        "image_generate": PermissionTier.WRITE_LOCAL,
        "browser": PermissionTier.EXTERNAL_EFFECT,
        "open_on_host": PermissionTier.EXTERNAL_EFFECT,
        "send_message": PermissionTier.EXTERNAL_EFFECT,
    }
    for name, tier in expected.items():
        assert name in tools, f"{name} is not registered"
        got = get_tier(tools[name])
        assert got == tier, f"{name}: expected {tier.name}, got {got}"


def test_read_tools_carry_the_read_only_tier() -> None:
    tools = _registered_tools()
    for name in ("read_file", "list_skill_dir", "search_files"):
        assert get_tier(tools[name]) == PermissionTier.READ_ONLY


def test_run_shell_impl_is_privileged() -> None:
    # `terminal` wraps run_shell, which is gated at the implementation.
    from jaeger_os.core.tools.code import run_shell
    assert get_tier(run_shell) == PermissionTier.PRIVILEGED


# ── the gate actually denies ─────────────────────────────────────────


def test_gated_tool_is_denied_under_a_deny_policy() -> None:
    @requires_tier(PermissionTier.WRITE_LOCAL, skill="t", operation="op")
    def effect() -> str:
        return "ran"

    with use_policy(PermissionPolicy(confirmation=DenyAllProvider())):
        with pytest.raises(PermissionDenied):
            effect()


def test_read_only_tier_passes_under_a_deny_policy() -> None:
    # Tier 0 is default-allowed — a deny confirmation provider is never
    # even consulted for a read.
    @requires_tier(PermissionTier.READ_ONLY, skill="t", operation="op")
    def look() -> str:
        return "ok"

    with use_policy(PermissionPolicy(confirmation=DenyAllProvider())):
        assert look() == "ok"
