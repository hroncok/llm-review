"""Entry point: python -m llm_review [task-id-or-url]

Reviews a Fedora package build via the Claude Agent SDK, and writes the
result in the same shape Fedora CI tests normally use (tmt custom
results.yaml + $TMT_TEST_DATA artifacts). Two input modes, mutually
exclusive, each running its own skill variant:

- A Koji scratch-build task (the ``task`` argument / $KOJI_TASK_ID).
- A single package's Copr build from a Fedora Package Review Process PR
  (``--copr-build``/$COPR_BUILD_ID, plus ``--pr-*``/$PR_* for rpmlintrc
  discovery).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path

from . import copr, koji, workspace
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
        "--copr-build",
        default=os.environ.get("COPR_BUILD_ID"),
        help="Copr build ID or build URL, for the Copr/PR review flow "
        "(default: $COPR_BUILD_ID). Mutually exclusive with a Koji task; "
        "requires --pr-clone-url/--pr-commit/--pr-package.",
    )
    parser.add_argument(
        "--copr-chroot",
        default=os.environ.get("COPR_CHROOT", copr.DEFAULT_CHROOT),
        help="Copr chroot to review the build results for "
        f"(default: $COPR_CHROOT, else {copr.DEFAULT_CHROOT!r})",
    )
    parser.add_argument(
        "--pr-clone-url",
        default=os.environ.get("PR_CLONE_URL"),
        help="Clone URL of the PR's source repository, for rpmlintrc "
        "discovery (default: $PR_CLONE_URL). Required with --copr-build.",
    )
    parser.add_argument(
        "--pr-commit",
        default=os.environ.get("PR_COMMIT"),
        help="Commit the Copr build was built from (default: $PR_COMMIT). "
        "Required with --copr-build.",
    )
    parser.add_argument(
        "--pr-package",
        default=os.environ.get("PR_PACKAGE"),
        help="Name of the package being reviewed, i.e. its "
        "<name>/<name>.spec subdirectory in the PR (default: $PR_PACKAGE). "
        "Required with --copr-build.",
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


def _resolve_source(args: argparse.Namespace):
    """Validate the Koji-vs-Copr input mode and return its parameters.

    Returns ``(prepare, skill_name, context_file, source_desc)`` on success,
    where ``prepare(workdir)`` sets up that workdir -- or ``None`` plus a
    logged error message when the arguments are invalid (caller returns 2).
    """
    if args.copr_build and args.task:
        logger.error(
            "Specify either a Koji task or --copr-build/$COPR_BUILD_ID, not both"
        )
        return None

    if args.copr_build:
        try:
            build_id = copr.parse_build_id(args.copr_build)
        except copr.CoprError as exc:
            logger.error(str(exc))
            return None

        missing = [
            flag
            for flag, value in (
                ("--pr-clone-url/$PR_CLONE_URL", args.pr_clone_url),
                ("--pr-commit/$PR_COMMIT", args.pr_commit),
                ("--pr-package/$PR_PACKAGE", args.pr_package),
            )
            if not value
        ]
        if missing:
            logger.error("--copr-build also requires %s", ", ".join(missing))
            return None

        def prepare(workdir: Path) -> None:
            workspace.prepare_copr(
                workdir,
                build_id,
                args.copr_chroot,
                args.pr_clone_url,
                args.pr_commit,
                args.pr_package,
            )

        return (
            prepare,
            workspace.SKILL_NAME_COPR,
            "copr-buildinfo.txt",
            f"Copr build {build_id} ({args.copr_chroot})",
        )

    if not args.task:
        logger.error(
            "No Koji task ID given (pass it as an argument or set $KOJI_TASK_ID), "
            "and no --copr-build/$COPR_BUILD_ID given"
        )
        return None

    try:
        task_id = koji.parse_task_id(args.task)
    except koji.KojiError as exc:
        logger.error(str(exc))
        return None

    def prepare(workdir: Path) -> None:
        workspace.prepare(workdir, task_id, koji_profile=args.koji_profile)

    return prepare, workspace.SKILL_NAME_KOJI, "koji-taskinfo.txt", f"Koji task {task_id}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    source = _resolve_source(args)
    if source is None:
        return 2
    prepare, skill_name, context_file, source_desc = source

    try:
        backend = load_backend_config()
    except ConfigError as exc:
        logger.error(str(exc))
        return 2

    def do_review(workdir: Path) -> int:
        workdir.mkdir(parents=True, exist_ok=True)
        output_dir = args.output_dir.resolve()

        logger.info("Preparing workspace in %s for %s", workdir, source_desc)
        try:
            prepare(workdir)
        except workspace.WorkspaceError as exc:
            logger.error("%s", exc)
            result = write_error(
                output_dir, str(exc), extra_logs=[workdir / context_file]
            )
            logger.info("Results written to %s", output_dir)
            return exit_code_for(result)

        logger.info("Running review with backend=%s model=%s", backend.backend, backend.model)
        try:
            review = run_review(
                workdir, backend, workdir / "review-output.md", skill_name=skill_name
            )
        except ReviewError as exc:
            logger.error("Review failed: %s", exc)
            extra_logs = [workdir / context_file]
            if exc.report:
                # Preserve the unparseable report before workdir gets cleaned
                # up -- otherwise a failure like this is unrecoverable to
                # diagnose after the fact.
                raw_report_path = workdir / "raw-review-output.md"
                raw_report_path.write_text(exc.report)
                extra_logs.append(raw_report_path)
            result = write_error(output_dir, str(exc), extra_logs=extra_logs)
            logger.info("Results written to %s", output_dir)
            return exit_code_for(result)

        result = write_output(
            review,
            output_dir,
            extra_logs=[workdir / context_file],
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
