"""Prepare the ephemeral working directory for a review session."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import koji

GUIDELINES_URL = "https://forge.fedoraproject.org/packaging/guidelines.git"
SKILL_NAME = "fedora-package-review"


class WorkspaceError(RuntimeError):
    pass


def default_skill_source() -> Path:
    """Locate the repo's ``skills/fedora-package-review`` directory.

    Assumes this package runs in place from a source checkout (editable
    install or ``PYTHONPATH=src``), which is how it's invoked in CI (tmt
    fetches the whole repo and runs it from there). Override with
    ``LLM_REVIEW_SKILL_DIR`` if that assumption doesn't hold.
    """
    if override := os.environ.get("LLM_REVIEW_SKILL_DIR"):
        return Path(override)
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "skills" / SKILL_NAME


def clone_guidelines(workdir: Path) -> None:
    dest = workdir / "guidelines"
    subprocess.run(
        ["git", "clone", "--depth", "1", GUIDELINES_URL, str(dest)],
        check=True,
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


def prepare(
    workdir: Path,
    task_id: str,
    skill_source: Path | None = None,
    koji_profile: str | None = None,
) -> None:
    """Set up guidelines, the skill, and Koji artifacts under ``workdir``."""
    clone_guidelines(workdir)
    install_skill(workdir, skill_source or default_skill_source())

    taskinfo = koji.fetch_taskinfo(task_id, profile=koji_profile)
    (workdir / "koji-taskinfo.txt").write_text(taskinfo)

    koji.download_artifacts(task_id, workdir / "artifacts", profile=koji_profile)
