import pytest
from claude_agent_sdk import ToolUseBlock

from llm_review.reviewer import (
    ReviewError,
    _count_issues,
    _extract_verdict,
    _tool_use_preview,
    _truncate,
)


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        ("### VERDICT\n\napprove\n", "approve"),
        ("### VERDICT\nneeds fixes\n", "needs fixes"),
        ("### VERDICT\n\nNeeds Discussion\n", "needs discussion"),
        ("### VERDICT\n\nError\n", "error"),
        ("## Package Review: foo 1-1\n\n...\n\n### VERDICT\n\napprove\n", "approve"),
    ],
)
def test_extract_verdict(report, expected):
    assert _extract_verdict(report) == expected


def test_extract_verdict_missing_raises():
    with pytest.raises(ReviewError):
        _extract_verdict("no verdict section here")


def test_count_issues_none():
    report = "### ISSUES\n\nNone.\n\n### VERDICT\n\napprove\n"
    assert _count_issues(report) == {"blocker": 0, "should-fix": 0, "minor": 0}


def test_count_issues_mixed():
    report = (
        "### ISSUES\n\n"
        "1. **Blocker**: missing License field\n"
        "2. **Should-fix**: use %license macro\n"
        "3. **Minor**: typo in summary\n"
        "4. **Minor**: changelog nit\n\n"
        "### VERDICT\n\nneeds fixes\n"
    )
    assert _count_issues(report) == {"blocker": 1, "should-fix": 1, "minor": 2}


def test_count_issues_approve_with_minor_only():
    report = (
        "### ISSUES\n\n1. **Minor**: consider tightening the Requires\n\n"
        "### VERDICT\n\napprove\n"
    )
    assert _count_issues(report) == {"blocker": 0, "should-fix": 0, "minor": 1}


def test_count_issues_missing_section():
    assert _count_issues("no issues section here") == {
        "blocker": 0,
        "should-fix": 0,
        "minor": 0,
    }


def test_truncate_short_text_unchanged():
    assert _truncate("short text") == "short text"


def test_truncate_collapses_whitespace():
    assert _truncate("a  b\n\nc\td") == "a b c d"


def test_truncate_long_text_gets_ellipsis():
    text = "x" * 300
    result = _truncate(text, limit=50)
    assert len(result) == 50
    assert result.endswith("…")


@pytest.mark.parametrize(
    ("name", "tool_input", "expected"),
    [
        ("Bash", {"command": "rpmlint  foo.spec   bar.rpm"}, "rpmlint foo.spec bar.rpm"),
        ("Read", {"file_path": "/tmp/foo/bar.spec"}, "/tmp/foo/bar.spec"),
        ("Grep", {"pattern": "License:"}, "License:"),
        ("Skill", {}, ""),
    ],
)
def test_tool_use_preview(name, tool_input, expected):
    block = ToolUseBlock(id="1", name=name, input=tool_input)
    assert _tool_use_preview(block) == expected


def test_tool_use_preview_falls_back_to_repr_for_unknown_keys():
    block = ToolUseBlock(id="1", name="SomeTool", input={"weird_key": "value"})
    assert "weird_key" in _tool_use_preview(block)
