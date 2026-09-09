import pytest

from llm_review.reviewer import ReviewError, _count_issues, _extract_verdict


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        ("### VERDICT\n\napprove\n", "approve"),
        ("### VERDICT\nneeds fixes\n", "needs fixes"),
        ("### VERDICT\n\nNeeds Discussion\n", "needs discussion"),
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
