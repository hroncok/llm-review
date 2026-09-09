"""Entry point: python -m llm_review [task-id-or-url]

Reviews a Fedora package build from a Koji scratch-build task, using the
fedora-package-review skill via the Claude Agent SDK, and writes the result
in the same shape Fedora CI tests normally use (tmt custom results.yaml +
$TMT_TEST_DATA artifacts).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path

from . import koji, workspace
from .config import ConfigError, load_backend_config
from .results import exit_code_for, write_error, write_output
from .reviewer import ReviewError, run_review

logging.basicConfig(level=os.environ.get("LLM_REVIEW_LOG_LEVEL", "INFO"))
logger = logging.getLogger("llm_review")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "task",
        nargs="?",
        default=os.environ.get("KOJI_TASK_ID"),
        help="Koji scratch-build task ID or taskinfo URL "
        "(default: $KOJI_TASK_ID)",
    )
    parser.add_argument(
        "--koji-profile",
        default=os.environ.get("KOJI_PROFILE"),
        help="koji CLI profile to use (default: koji's own default, "
        "override with $KOJI_PROFILE)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.environ.get("TMT_TEST_DATA", "results")),
        help="Where to write results.yaml/review.md "
        "(default: $TMT_TEST_DATA, else ./results)",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Working directory for the review session "
        "(default: a fresh temporary directory)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.task:
        logger.error("No Koji task ID given (pass it as an argument or set $KOJI_TASK_ID)")
        return 2

    try:
        task_id = koji.parse_task_id(args.task)
    except koji.KojiError as exc:
        logger.error(str(exc))
        return 2

    try:
        backend = load_backend_config()
    except ConfigError as exc:
        logger.error(str(exc))
        return 2

    def do_review(workdir: Path) -> int:
        workdir.mkdir(parents=True, exist_ok=True)
        output_dir = args.output_dir.resolve()

        logger.info("Preparing workspace in %s for Koji task %s", workdir, task_id)
        try:
            workspace.prepare(workdir, task_id, koji_profile=args.koji_profile)
        except workspace.WorkspaceError as exc:
            logger.error("%s", exc)
            result = write_error(
                output_dir, str(exc), extra_logs=[workdir / "koji-taskinfo.txt"]
            )
            logger.info("Results written to %s", output_dir)
            return exit_code_for(result)

        logger.info("Running review with backend=%s model=%s", backend.backend, backend.model)
        try:
            review = run_review(workdir, backend, workdir / "review-output.md")
        except ReviewError as exc:
            logger.error("Review failed: %s", exc)
            result = write_error(
                output_dir, str(exc), extra_logs=[workdir / "koji-taskinfo.txt"]
            )
            logger.info("Results written to %s", output_dir)
            return exit_code_for(result)

        result = write_output(
            review,
            output_dir,
            extra_logs=[workdir / "koji-taskinfo.txt"],
        )
        logger.info("Verdict: %s (tmt result: %s)", review.verdict, result.value)
        logger.info("Results written to %s", output_dir)
        return exit_code_for(result)

    if args.workdir:
        return do_review(args.workdir)
    with tempfile.TemporaryDirectory(prefix="llm-review-") as tmp:
        return do_review(Path(tmp))


if __name__ == "__main__":
    sys.exit(main())
