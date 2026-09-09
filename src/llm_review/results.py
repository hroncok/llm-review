"""Present a review result the way Fedora CI results are normally presented.

Mirrors packit/tmt-plans' ``tests/fedora-review/run-fedora-review.py``: write a
tmt custom result (https://tmt.readthedocs.io/en/stable/spec/results.html) to
``results.yaml`` and copy artifacts into ``$TMT_TEST_DATA``. No posting to any
external API (Bugzilla, a PR, ...) -- Testing Farm/Fedora CI's own dashboard
renders whatever lands here.
"""

from __future__ import annotations

import shutil
from enum import Enum
from pathlib import Path

import yaml

from .reviewer import ReviewResult

REPORT_FILENAME = "review.md"
RESULTS_FILENAME = "results.yaml"


class Result(Enum):
    INFO = "info"
    FAIL = "fail"
    PASS = "pass"
    ERROR = "error"


VERDICT_TO_RESULT: dict[str, Result] = {
    "approve": Result.PASS,
    "needs fixes": Result.FAIL,
    "needs discussion": Result.INFO,
    "error": Result.ERROR,
}

# Exit code Result.value -> process exit code. Only a hard "needs fixes"
# blocks; "needs discussion" surfaces for a human without failing the job.
# "error" means the review could not be performed at all (e.g. no artifacts
# to inspect), which is a setup/infra failure, not a review outcome.
RESULT_TO_EXIT_CODE: dict[Result, int] = {
    Result.PASS: 0,
    Result.INFO: 0,
    Result.FAIL: 1,
    Result.ERROR: 2,
}


def result_for_verdict(verdict: str) -> Result:
    try:
        return VERDICT_TO_RESULT[verdict]
    except KeyError as exc:
        raise ValueError(f"Unknown verdict {verdict!r}") from exc


def _issue_counts_note(issue_counts: dict[str, int]) -> str | None:
    """Summarize non-zero issue counts, e.g. "issues: 1 blocker, 2 minor".

    Lets an "approve" verdict with minor (or should-fix) issues still show
    that something was flagged, instead of collapsing to just the verdict.
    """
    parts = [f"{count} {category}" for category, count in issue_counts.items() if count]
    return "issues: " + ", ".join(parts) if parts else None


def write_output(
    review: ReviewResult,
    output_dir: Path,
    extra_logs: list[Path] | None = None,
) -> Result:
    """Write ``results.yaml`` + report/logs into ``output_dir``. Return the Result."""
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / REPORT_FILENAME
    report_path.write_text(review.report)

    log_names = [REPORT_FILENAME]
    for log in extra_logs or []:
        if log.exists():
            shutil.copy(log, output_dir / log.name)
            log_names.append(log.name)

    result = result_for_verdict(review.verdict)
    # tmt's result_note schema declares a single string, not a list -- see
    # https://tmt.readthedocs.io/en/stable/spec/plans.html#execute
    note = f"verdict: {review.verdict}"
    if issues_note := _issue_counts_note(review.issue_counts):
        note += f"; {issues_note}"
    data = [
        {
            "name": "/",
            "result": result.value,
            "note": note,
            "log": log_names,
        }
    ]
    with (output_dir / RESULTS_FILENAME).open("w") as fp:
        yaml.dump(data, fp)

    return result


def write_error(
    output_dir: Path,
    message: str,
    extra_logs: list[Path] | None = None,
) -> Result:
    """Write a tmt "error" result for when the review couldn't be performed.

    Distinct from a "needs discussion" verdict: that implies the LLM actually
    reviewed something and has a substantive opinion. This is for cases like
    a Koji task with no RPM artifacts at all, where there is nothing to
    review and no LLM session is even run.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    log_names = []
    for log in extra_logs or []:
        if log.exists():
            shutil.copy(log, output_dir / log.name)
            log_names.append(log.name)

    data = [
        {
            "name": "/",
            "result": Result.ERROR.value,
            "note": message,
            "log": log_names,
        }
    ]
    with (output_dir / RESULTS_FILENAME).open("w") as fp:
        yaml.dump(data, fp)

    return Result.ERROR


def exit_code_for(result: Result) -> int:
    return RESULT_TO_EXIT_CODE[result]
