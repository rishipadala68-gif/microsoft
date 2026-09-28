"""Tests that ALLOW_ACTIONS is always False and tool count is correct."""
from __future__ import annotations

from app.agent import tools


def test_allow_actions_is_false() -> None:
    assert tools.ALLOW_ACTIONS is False, "ALLOW_ACTIONS must never be True"


def test_allow_actions_is_bool() -> None:
    assert isinstance(tools.ALLOW_ACTIONS, bool)


def test_tool_count() -> None:
    assert len(tools.TOOL_DEFINITIONS) == 9


def test_all_tools_have_required_fields() -> None:
    for tool in tools.TOOL_DEFINITIONS:
        assert "name" in tool, f"Tool missing 'name': {tool}"
        assert "description" in tool, f"Tool {tool['name']} missing 'description'"
        assert "input_schema" in tool, f"Tool {tool['name']} missing 'input_schema'"
        schema = tool["input_schema"]
        assert schema.get("type") == "object"
        assert "properties" in schema


def test_all_tools_are_readonly() -> None:
    """Verify no tool description mentions write/restart/delete actions."""
    write_keywords = {"delete", "write", "restart", "rollback", "create", "update", "insert"}
    for tool in tools.TOOL_DEFINITIONS:
        desc_lower = tool["description"].lower()
        bad = write_keywords & set(desc_lower.split())
        assert not bad, (
            f"Tool '{tool['name']}' description may imply write action: {bad}"
        )
