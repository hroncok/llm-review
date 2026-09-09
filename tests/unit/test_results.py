from pathlib import Path

import pytest
import yaml

from llm_review.results import (
    RESULTS_FILENAME,
    Result,
    exit_code_for,
    result_for_verdict,
    write_error,
    write_output,
)
from llm_review.reviewer import ReviewResult


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        ("approve", Result.PASS),
        ("needs fixes", Result.FAIL),
        ("needs discussion", Result.INFO),
        ("error", Result.ERROR),
    ],
)
def test_result_for_verdict(verdict, expected):
    assert result_for_verdict(verdict) is expected


def test_result_for_unknown_verdict_raises():
    with pytest.raises(ValueError):
        result_for_verdict("something else")


@pytest.mark.parametrize(
    ("result", "code"),
    [(Result.PASS, 0), (Result.INFO, 0), (Result.FAIL, 1), (Result.ERROR, 2)],
)
def test_exit_code_for(result, code):
    assert exit_code_for(result) == code


NO_ISSUES = {"blocker": 0, "should-fix": 0, "minor": 0}


def test_write_output_pass(tmp_path: Path):
    review = ReviewResult(
        report="## report\n### VERDICT\n\napprove\n",
        verdict="approve",
        transcript="",
        issue_counts=NO_ISSUES,
    )
    output_dir = tmp_path / "out"

    result = write_output(review, output_dir)

    assert result is Result.PASS
    assert (output_dir / "review.md").read_text() == review.report
    data = yaml.safe_load((output_dir / RESULTS_FILENAME).read_text())
    assert data == [
        {
            "name": "/",
            "result": "pass",
            "note": "verdict: approve",
            "log": ["review.md"],
        }
    ]


def test_write_output_approve_with_minor_issues_notes_them(tmp_path: Path):
    review = ReviewResult(
        report="report",
        verdict="approve",
        transcript="",
        issue_counts={"blocker": 0, "should-fix": 0, "minor": 2},
    )
    output_dir = tmp_path / "out"

    write_output(review, output_dir)

    data = yaml.safe_load((output_dir / RESULTS_FILENAME).read_text())
    assert data[0]["note"] == "verdict: approve; issues: 2 minor"


def test_write_output_includes_extra_logs(tmp_path: Path):
    review = ReviewResult(
        report="report", verdict="needs fixes", transcript="", issue_counts=NO_ISSUES
    )
    extra_log = tmp_path / "koji-taskinfo.txt"
    extra_log.write_text("some log content")
    output_dir = tmp_path / "out"

    result = write_output(review, output_dir, extra_logs=[extra_log])

    assert result is Result.FAIL
    assert (output_dir / "koji-taskinfo.txt").read_text() == "some log content"


def test_write_output_skips_missing_extra_logs(tmp_path: Path):
    review = ReviewResult(
        report="report", verdict="needs discussion", transcript="", issue_counts=NO_ISSUES
    )
    missing_log = tmp_path / "does-not-exist.txt"
    output_dir = tmp_path / "out"

    write_output(review, output_dir, extra_logs=[missing_log])

    assert not (output_dir / "does-not-exist.txt").exists()


def test_write_output_error_verdict(tmp_path: Path):
    review = ReviewResult(
        report="## report\n### VERDICT\n\nerror\n",
        verdict="error",
        transcript="",
        issue_counts=NO_ISSUES,
    )
    output_dir = tmp_path / "out"

    result = write_output(review, output_dir)

    assert result is Result.ERROR
    data = yaml.safe_load((output_dir / RESULTS_FILENAME).read_text())
    assert data[0]["result"] == "error"


def test_write_error(tmp_path: Path):
    output_dir = tmp_path / "out"

    result = write_error(output_dir, "no RPM artifacts to review")

    assert result is Result.ERROR
    assert exit_code_for(result) == 2
    data = yaml.safe_load((output_dir / RESULTS_FILENAME).read_text())
    assert data == [
        {
            "name": "/",
            "result": "error",
            "note": "no RPM artifacts to review",
            "log": [],
        }
    ]
    assert not (output_dir / "review.md").exists()


def test_write_error_includes_extra_logs(tmp_path: Path):
    extra_log = tmp_path / "koji-taskinfo.txt"
    extra_log.write_text("some log content")
    output_dir = tmp_path / "out"

    write_error(output_dir, "no artifacts", extra_logs=[extra_log])

    assert (output_dir / "koji-taskinfo.txt").read_text() == "some log content"
