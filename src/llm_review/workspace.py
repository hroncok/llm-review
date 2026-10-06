"""Prepare the ephemeral working directory for a review session."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from functools import partial
from importlib import resources
from pathlib import Path

from . import copr, koji
from .retry import run_with_retry

logger = logging.getLogger(__name__)

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
# See skills/_fragments/ and scripts/build_skills.py for how the two skills
# share most of their content.
SKILL_NAME_KOJI = "fedora-package-review-koji"
SKILL_NAME_COPR = "fedora-package-review-copr"


class WorkspaceError(RuntimeError):
    pass


def default_skill_source(skill_name: str = SKILL_NAME_KOJI) -> Path:
    """Locate the ``skill_name`` skill directory.

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
    repo_skill_dir = repo_root / "skills" / skill_name
    if repo_skill_dir.is_dir():
        return repo_skill_dir

    packaged_skill_dir = resources.files("llm_review") / "skill_data" / skill_name
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


def clone_dist_git(workdir: Path, repo_url: str, ref: str) -> None:
    """Clone the dist-git repo this build came from and check out its exact ref.

    Full clone, not shallow -- ``ref`` is a specific commit that may not be
    reachable from a shallow clone of just the default branch's tip. Used
    so the skill can find any ``*.rpmlintrc``/``rpmlint.toml`` next to the
    spec, which a plain `koji download-task` doesn't provide.

    Raises ``subprocess.CalledProcessError`` if ``ref`` can't be checked
    out -- seen live: a PR build's fork branch can be rewritten or deleted
    after the fact, making its exact commit permanently unreachable, not
    just a transient failure. Removes ``dest`` on that failure rather than
    leaving a clone checked out to the wrong (default-branch) commit, which
    would silently mislead the skill into treating it as this build's
    actual dist-git content.
    """
    dest = workdir / "dist-git"
    run_with_retry(
        ["git", "clone", repo_url, str(dest)],
        on_retry=partial(shutil.rmtree, dest, ignore_errors=True),
    )
    try:
        # Local operation once cloned -- not network-dependent, so no retry.
        # `switch -d` (unlike `checkout`) detaches without the noisy "Note:
        # switching to ... you are in 'detached HEAD' state ..." advisory.
        logger.info("Running: git switch -d %s (in %s)", ref, dest)
        subprocess.run(["git", "switch", "-d", ref], cwd=dest, check=True)
    except subprocess.CalledProcessError:
        shutil.rmtree(dest, ignore_errors=True)
        raise


def install_skill(workdir: Path, skill_source: Path, skill_name: str = SKILL_NAME_KOJI) -> None:
    if not skill_source.is_dir():
        raise WorkspaceError(
            f"Skill directory not found at {skill_source}; "
            "set LLM_REVIEW_SKILL_DIR to override."
        )
    dest = workdir / ".claude" / "skills" / skill_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill_source, dest, dirs_exist_ok=True)


def ensure_has_rpm_artifacts(artifacts_dir: Path, description: str) -> None:
    """Raise ``WorkspaceError`` if ``artifacts_dir`` has no ``.rpm`` files.

    Checked deterministically, before ever invoking the LLM: reviewing an
    empty artifact set isn't a legitimate "needs discussion" outcome, it's a
    setup failure (e.g. the build's output expired, or it never produced
    RPMs) and should be reported as one. Shared by both the Koji flow
    (``description`` identifies the task) and the Copr flow (``description``
    identifies the build).
    """
    if not any(artifacts_dir.glob("*.rpm")):
        raise WorkspaceError(
            f"{description} has no RPM artifacts to download "
            "(no .rpm files in the build output) -- there is nothing to review, "
            "e.g. because the output has expired or the build failed "
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

    source = koji.parse_source_scm(taskinfo)
    if not source:
        logger.info(
            "Koji task %s has no SCM source; skipping dist-git clone "
            "(no rpmlintrc discovery for this review)",
            task_id,
        )
    else:
        try:
            clone_dist_git(workdir, *source)
        except subprocess.CalledProcessError as exc:
            # Not fatal: dist-git only enables rpmlintrc discovery, it's not
            # needed for the rest of the review. Seen live: a fork branch
            # can be rewritten/deleted after the build, making its exact
            # commit permanently unreachable.
            logger.warning(
                "Could not clone/check out dist-git for Koji task %s (%s); "
                "continuing without it (no rpmlintrc discovery for this review)",
                task_id,
                exc,
            )

    artifacts_dir = workdir / "artifacts"
    koji.download_artifacts(task_id, artifacts_dir, profile=koji_profile)
    ensure_has_rpm_artifacts(artifacts_dir, f"Koji task {task_id}")


def clone_pr_package(workdir: Path, clone_url: str, commit: str, package: str) -> None:
    """Clone ``clone_url`` at ``commit`` and copy just ``<package>/`` into ``dist-git/``.

    The Copr-flow analogue of ``clone_dist_git()``: the PR source repo is a
    monorepo of ``<name>/<name>.spec`` subdirectories (this package hasn't
    been accepted/imported into Fedora dist-git yet), so only its own
    subdirectory is relevant. Landing it at the same ``dist-git/`` path the
    Koji flow uses means ``skills/_fragments/review-steps.md``'s rpmlintrc
    discovery works unchanged for both flows.

    Raises ``subprocess.CalledProcessError`` if ``commit`` can't be checked
    out -- e.g. a force-push rewrote the PR branch after the build. Not
    fatal to the caller (same as ``clone_dist_git``): rpmlintrc discovery is
    the only thing that's lost.
    """
    dest = workdir / "dist-git"
    with tempfile.TemporaryDirectory(prefix="pr-source-") as tmp:
        clone_dir = Path(tmp) / "clone"
        run_with_retry(["git", "clone", clone_url, str(clone_dir)])
        subprocess.run(["git", "switch", "-d", commit], cwd=clone_dir, check=True)
        shutil.copytree(clone_dir / package, dest)


def prepare_copr(
    workdir: Path,
    build_id: str,
    chroot: str,
    pr_clone_url: str,
    pr_commit: str,
    pr_package: str,
    skill_source: Path | None = None,
) -> None:
    """Set up guidelines, the skill, and Copr artifacts under ``workdir``.

    The Copr-flow counterpart of ``prepare()`` -- reviews one package from a
    Fedora Package Review Process PR, built in Copr (see
    ``skills/fedora-package-review-copr/SKILL.md``).
    """
    clone_repos(workdir)
    install_skill(
        workdir, skill_source or default_skill_source(SKILL_NAME_COPR), skill_name=SKILL_NAME_COPR
    )

    (workdir / "copr-buildinfo.txt").write_text(
        f"Copr build: {build_id}\n"
        f"Chroot: {chroot}\n"
        f"Package: {pr_package}\n"
        f"PR source: {pr_clone_url}\n"
        f"PR commit: {pr_commit}\n"
    )

    try:
        clone_pr_package(workdir, pr_clone_url, pr_commit, pr_package)
    except subprocess.CalledProcessError as exc:
        # Not fatal: dist-git only enables rpmlintrc discovery, it's not
        # needed for the rest of the review. Mirrors the Koji flow's handling
        # of a fork branch rewritten/deleted after the build.
        logger.warning(
            "Could not clone/check out the PR source for package %s at %s (%s); "
            "continuing without it (no rpmlintrc discovery for this review)",
            pr_package,
            pr_commit,
            exc,
        )

    artifacts_dir = workdir / "artifacts"
    copr.download_artifacts(build_id, artifacts_dir, chroot)
    ensure_has_rpm_artifacts(artifacts_dir, f"Copr build {build_id} ({chroot})")
