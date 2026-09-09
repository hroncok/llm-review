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


VERDICT_TO_RESULT: dict[str, Result] = {
    "approve": Result.PASS,
    "needs fixes": Result.FAIL,
    "needs discussion": Result.INFO,
}

# Exit code Result.value -> process exit code. Only a hard "needs fixes"
# blocks; "needs discussion" surfaces for a human without failing the job.
RESULT_TO_EXIT_CODE: dict[Result, int] = {
    Result.PASS: 0,
    Result.INFO: 0,
    Result.FAIL: 1,
}


def result_for_verdict(verdict: str) -> Result:
    try:
        return VERDICT_TO_RESULT[verdict]
    except KeyError as exc:
        raise ValueError(f"Unknown verdict {verdict!r}") from exc


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
    data = [
        {
            "name": "/",
            "result": result.value,
            "note": [f"verdict: {review.verdict}"],
            "log": log_names,
        }
    ]
    with (output_dir / RESULTS_FILENAME).open("w") as fp:
        yaml.dump(data, fp)

    return result


def exit_code_for(result: Result) -> int:
    return RESULT_TO_EXIT_CODE[result]
