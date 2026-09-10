"""Resolve a Koji scratch-build task and download its artifacts.

Mirrors the approach already used in packit/tmt-plans' ``utils.get_koji_build``
and ``utils.get_dist_git`` (task Source: parsing), adapted to not require a
dist-git checkout -- the fedora-package-review skill extracts the spec file
from the downloaded SRPM itself.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
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


def fetch_task_children(task_id: str, profile: str | None = None) -> list[dict]:
    """Return ``getTaskChildren(task_id)`` (each with ``id``, ``method``, ``label``, ...)."""
    result = run_with_retry(
        ["koji", *_profile_args(profile), "call", "--json-output", "getTaskChildren", task_id],
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _reorganize_downloaded_tasks(tmp_dir: Path, dest: Path, children: list[dict]) -> None:
    """Flatten a ``--dirpertask`` download (``tmp_dir/<task-id>/...``) into ``dest``.

    RPM filenames are kept as-is (already unique via NVRA). Generic
    per-task files (``build.log``, ``root.log``, ...) are renamed with
    that subtask's ``label`` (e.g. ``x86_64``, ``noarch``, ``srpm``)
    instead of koji's own arch-based naming -- see ``download_artifacts``
    for why that matters.
    """
    label_by_task_id = {str(child["id"]): child.get("label") for child in children}
    for task_dir in tmp_dir.iterdir():
        if not task_dir.is_dir():
            continue
        label = label_by_task_id.get(task_dir.name) or task_dir.name
        for path in task_dir.iterdir():
            if path.suffix == ".rpm":
                shutil.move(str(path), dest / path.name)
            else:
                shutil.move(str(path), dest / f"{path.stem}.{label}{path.suffix}")


def download_artifacts(task_id: str, dest: Path, profile: str | None = None) -> None:
    """Download the task's SRPM, RPMs, and logs into ``dest``.

    Uses ``--dirpertask`` and reorganizes into ``dest`` (see
    ``_reorganize_downloaded_tasks``), rather than downloading straight
    into ``dest`` as a flat directory. Koji's own flat-mode naming
    disambiguates generic log files (``build.log``, ``root.log``, ...) by
    the *builder host's* architecture, not the subtask's actual target --
    the ``buildSRPMFromSCM`` subtask (which only generates the SRPM, and
    never runs ``%build``/``%install``/``%check``) can coincidentally run
    on the same-arch builder host as a real ``buildArch`` subtask (e.g. any
    `noarch` package's single buildArch task can land on any host arch).
    When that happens, koji's flat download silently *skips* downloading
    the second (real) log file as an "already downloaded" duplicate --
    losing the genuine build/check log entirely, not just overwriting it
    with something recoverable.
    """
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="koji-download-") as tmp:
        tmp_dir = Path(tmp)
        run_with_retry(
            ["koji", *_profile_args(profile), "download-task", task_id, "--logs", "--dirpertask"],
            cwd=tmp_dir,
        )
        children = fetch_task_children(task_id, profile=profile)
        _reorganize_downloaded_tasks(tmp_dir, dest, children)
