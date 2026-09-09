import pytest
from claude_agent_sdk import ResultMessage, ToolUseBlock

from llm_review.reviewer import (
    ReviewError,
    _count_issues,
    _extract_verdict,
    _result_error_text,
    _tool_use_preview,
    _truncate,
)


def _result_message(**overrides) -> ResultMessage:
    defaults = {
        "subtype": "success",
        "duration_ms": 100,
        "duration_api_ms": 100,
        "is_error": True,
        "num_turns": 1,
        "session_id": "test-session",
    }
    return ResultMessage(**{**defaults, **overrides})


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
    report = (
        "### ISSUES\n\nNone.\n\n"
        "### SUMMARY\n\nBlockers: 0\nShould-fix: 0\nMinor: 0\n\n"
        "### VERDICT\n\napprove\n"
    )
    assert _count_issues(report) == {"blocker": 0, "should-fix": 0, "minor": 0}


def test_count_issues_mixed():
    report = (
        "### ISSUES\n\n"
        "1. **Blocker**: missing License field\n"
        "2. **Should-fix**: use %license macro\n"
        "3. **Minor**: typo in summary\n"
        "4. **Minor**: changelog nit\n\n"
        "### SUMMARY\n\nBlockers: 1\nShould-fix: 1\nMinor: 2\n\n"
        "### VERDICT\n\nneeds fixes\n"
    )
    assert _count_issues(report) == {"blocker": 1, "should-fix": 1, "minor": 2}


def test_count_issues_approve_with_minor_only():
    report = (
        "### ISSUES\n\n1. **Minor**: consider tightening the Requires\n\n"
        "### SUMMARY\n\nBlockers: 0\nShould-fix: 0\nMinor: 1\n\n"
        "### VERDICT\n\napprove\n"
    )
    assert _count_issues(report) == {"blocker": 0, "should-fix": 0, "minor": 1}


def test_count_issues_ignores_negation_prose_elsewhere_in_report():
    # Real-world case: the model wrote "No **Blocker** ... issues were found."
    # as prose in ### ISSUES -- that must not affect the ### SUMMARY counts,
    # which are what's actually parsed.
    report = (
        "### ISSUES\n\n"
        "1. **Minor**: spelling-error false positive for a proper noun\n"
        "2. **Minor**: %check only runs an import smoke test\n\n"
        "No **Blocker** (MUST-level) issues were found.\n\n"
        "### SUMMARY\n\nBlockers: 0\nShould-fix: 0\nMinor: 2\n\n"
        "### VERDICT\n\napprove\n"
    )
    assert _count_issues(report) == {"blocker": 0, "should-fix": 0, "minor": 2}


def test_count_issues_missing_summary_section_defaults_to_zero():
    report = "### ISSUES\n\n1. **Blocker**: something bad\n\n### VERDICT\n\nneeds fixes\n"
    assert _count_issues(report) == {"blocker": 0, "should-fix": 0, "minor": 0}


def test_count_issues_missing_section():
    assert _count_issues("no sections here") == {
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


def test_result_error_text_prefers_result_over_success_subtype():
    # Real-world case: an API failure arrives as subtype "success" with the
    # actual error text in `result` -- using subtype alone here produces the
    # self-contradictory "ended in error: success".
    message = _result_message(subtype="success", result="API Error: rate limited")
    assert _result_error_text(message) == "API Error: rate limited"


def test_result_error_text_falls_back_to_subtype_when_no_result():
    message = _result_message(subtype="error_max_turns", result=None)
    assert _result_error_text(message) == "error_max_turns"
