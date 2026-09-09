"""Resolve a Koji scratch-build task and download its artifacts.

Mirrors the approach already used in packit/tmt-plans' ``utils.get_koji_build``
and ``utils.get_dist_git`` (task Source: parsing), adapted to not require a
dist-git checkout -- the fedora-package-review skill extracts the spec file
from the downloaded SRPM itself.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .retry import run_with_retry

_TASK_ID_RE = re.compile(r"^\d+$")


class KojiError(RuntimeError):
    """Raised when a Koji task ID can't be resolved or its artifacts fetched."""


def parse_task_id(value: str) -> str:
    """Accept a bare Koji task ID or a ``taskinfo?taskID=`` URL; return the ID."""
    value = value.strip()
    if _TASK_ID_RE.match(value):
        return value
    task_ids = parse_qs(urlparse(value).query).get("taskID")
    if task_ids and _TASK_ID_RE.match(task_ids[0]):
        return task_ids[0]
    raise KojiError(f"Could not extract a Koji task ID from {value!r}")


def _profile_args(profile: str | None) -> list[str]:
    return ["--profile", profile] if profile else []


def fetch_taskinfo(task_id: str, profile: str | None = None) -> str:
    """Return the output of ``koji taskinfo -v <task_id>``."""
    result = run_with_retry(
        ["koji", *_profile_args(profile), "taskinfo", "-v", task_id],
        capture_output=True,
        text=True,
    )
    return result.stdout


def download_artifacts(task_id: str, dest: Path, profile: str | None = None) -> None:
    """Download the task's SRPM, RPMs, and logs into ``dest``.

    Safe to retry as-is: ``koji download-task`` skips files it already
    downloaded into ``dest`` rather than starting over.
    """
    dest.mkdir(parents=True, exist_ok=True)
    run_with_retry(
        ["koji", *_profile_args(profile), "download-task", task_id, "--logs"],
        cwd=dest,
    )
