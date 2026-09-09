import pytest

from llm_review.reviewer import ReviewError, _extract_verdict


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
