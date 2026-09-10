"""Prepare the ephemeral working directory for a review session."""

from __future__ import annotations

import os
import shutil
from functools import partial
from importlib import resources
from pathlib import Path

from . import koji
from .retry import run_with_retry

# Reference repos cloned into the workspace, keyed by the directory name
# they're cloned into under $WORKDIR (see the skill's "Input" section).
REPOS_TO_CLONE = {
    # The Fedora Packaging Guidelines.
    "guidelines": "https://forge.fedoraproject.org/packaging/guidelines.git",
    # Fedora Legal's policy docs -- license-field.adoc (how to compose the
    # License: field) and allowed-licenses.adoc (approval policy).
    # Separate from, and not covered by, the packaging guidelines above.
    "legal-docs": "https://gitlab.com/fedora/legal/fedora-legal-docs.git",
    # A per-license machine-readable database (data/<SPDX-ID>.toml, each
    # with a `status` field) -- a definitive lookup for whether a specific
    # license is allowed in Fedora, instead of the model guessing from
    # memorized knowledge.
    "license-data": "https://forge.fedoraproject.org/legal/fedora-license-data.git",
}
SKILL_NAME = "fedora-package-review"


class WorkspaceError(RuntimeError):
    pass


def default_skill_source() -> Path:
    """Locate the ``fedora-package-review`` skill directory.

    Tries, in order: an explicit override, the repo's top-level ``skills/``
    directory (works when running in place from a source checkout, e.g. an
    editable install or ``PYTHONPATH=src`` -- the top-level directory is the
    canonical, human-editable copy), and finally the copy bundled as package
    data (``[tool.hatch.build.targets.wheel.force-include]`` in
    pyproject.toml), which is what a regular non-editable ``pip install``
    falls back on since it doesn't keep the sibling ``skills/`` directory.
    """
    if override := os.environ.get("LLM_REVIEW_SKILL_DIR"):
        return Path(override)

    repo_root = Path(__file__).resolve().parents[2]
    repo_skill_dir = repo_root / "skills" / SKILL_NAME
    if repo_skill_dir.is_dir():
        return repo_skill_dir

    packaged_skill_dir = resources.files("llm_review") / "skill_data" / SKILL_NAME
    return Path(str(packaged_skill_dir))


def clone_repos(workdir: Path) -> None:
    """Shallow-clone every repo in ``REPOS_TO_CLONE`` into ``workdir``."""
    for name, url in REPOS_TO_CLONE.items():
        dest = workdir / name
        run_with_retry(
            ["git", "clone", "--depth", "1", url, str(dest)],
            # A retry must find `dest` gone, or git fails with "destination
            # path already exists" instead of actually retrying the clone.
            on_retry=partial(shutil.rmtree, dest, ignore_errors=True),
        )


def install_skill(workdir: Path, skill_source: Path) -> None:
    if not skill_source.is_dir():
        raise WorkspaceError(
            f"Skill directory not found at {skill_source}; "
            "set LLM_REVIEW_SKILL_DIR to override."
        )
    dest = workdir / ".claude" / "skills" / SKILL_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill_source, dest, dirs_exist_ok=True)


def ensure_has_rpm_artifacts(artifacts_dir: Path, task_id: str) -> None:
    """Raise ``WorkspaceError`` if ``artifacts_dir`` has no ``.rpm`` files.

    Checked deterministically, before ever invoking the LLM: reviewing an
    empty artifact set isn't a legitimate "needs discussion" outcome, it's a
    setup failure (e.g. the task's output expired, or the build never
    produced RPMs) and should be reported as one.
    """
    if not any(artifacts_dir.glob("*.rpm")):
        raise WorkspaceError(
            f"Koji task {task_id} has no RPM artifacts to download "
            "(no .rpm files in the task output) -- there is nothing to review, "
            "e.g. because the task's output has expired or the build failed "
            "before producing any RPMs"
        )


def prepare(
    workdir: Path,
    task_id: str,
    skill_source: Path | None = None,
    koji_profile: str | None = None,
) -> None:
    """Set up guidelines, the skill, and Koji artifacts under ``workdir``."""
    clone_repos(workdir)
    install_skill(workdir, skill_source or default_skill_source())

    taskinfo = koji.fetch_taskinfo(task_id, profile=koji_profile)
    (workdir / "koji-taskinfo.txt").write_text(taskinfo)

    artifacts_dir = workdir / "artifacts"
    koji.download_artifacts(task_id, artifacts_dir, profile=koji_profile)
    ensure_has_rpm_artifacts(artifacts_dir, task_id)
