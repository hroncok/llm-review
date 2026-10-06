import subprocess
from pathlib import Path

import pytest

from llm_review import workspace
from llm_review.workspace import (
    WorkspaceError,
    clone_dist_git,
    clone_pr_package,
    ensure_has_rpm_artifacts,
)


def test_ensure_has_rpm_artifacts_passes_with_rpms(tmp_path: Path):
    (tmp_path / "foo-1.0-1.fc99.src.rpm").write_text("")
    (tmp_path / "foo-1.0-1.fc99.noarch.rpm").write_text("")

    ensure_has_rpm_artifacts(tmp_path, description="123456")  # must not raise


def test_ensure_has_rpm_artifacts_raises_when_empty(tmp_path: Path):
    with pytest.raises(WorkspaceError, match="123456"):
        ensure_has_rpm_artifacts(tmp_path, description="123456")


def test_ensure_has_rpm_artifacts_raises_when_only_logs(tmp_path: Path):
    (tmp_path / "build.log").write_text("")
    (tmp_path / "root.log").write_text("")

    with pytest.raises(WorkspaceError):
        ensure_has_rpm_artifacts(tmp_path, description="123456")


def _make_git_repo(path: Path) -> str:
    """Create a local git repo with one commit; return its hash."""
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "first"],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_clone_dist_git_checks_out_exact_ref(tmp_path: Path):
    repo = tmp_path / "upstream"
    ref = _make_git_repo(repo)
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    clone_dist_git(workdir, str(repo), ref)

    checked_out = subprocess.run(
        ["git", "-C", str(workdir / "dist-git"), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert checked_out == ref


def test_clone_dist_git_cleans_up_on_checkout_failure(tmp_path: Path):
    # Real-world case: the fork branch a build's commit lived on was
    # rewritten/deleted, making that exact commit unreachable. Must not
    # leave `dist-git/` behind checked out to the wrong commit.
    repo = tmp_path / "upstream"
    _make_git_repo(repo)
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    with pytest.raises(subprocess.CalledProcessError):
        clone_dist_git(workdir, str(repo), "0" * 40)

    assert not (workdir / "dist-git").exists()


def _make_git_repo_with_package(path: Path, package: str) -> str:
    """Create a local git repo with a `<package>/<package>.spec`; return its hash."""
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / package).mkdir()
    (path / package / f"{package}.spec").write_text("Name: " + package)
    (path / package / f"{package}.rpmlintrc").write_text("")
    (path / "other-package").mkdir()
    (path / "other-package" / "other-package.spec").write_text("Name: other-package")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "first"],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_clone_pr_package_copies_only_the_one_package_subdir(tmp_path: Path):
    repo = tmp_path / "pr-source"
    ref = _make_git_repo_with_package(repo, "foo")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    clone_pr_package(workdir, str(repo), ref, "foo")

    assert (workdir / "dist-git" / "foo.spec").exists()
    assert (workdir / "dist-git" / "foo.rpmlintrc").exists()
    assert not (workdir / "dist-git" / "other-package.spec").exists()
    assert not (workdir / "dist-git" / "other-package").exists()


def test_clone_pr_package_raises_on_checkout_failure(tmp_path: Path):
    repo = tmp_path / "pr-source"
    _make_git_repo_with_package(repo, "foo")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    with pytest.raises(subprocess.CalledProcessError):
        clone_pr_package(workdir, str(repo), "0" * 40, "foo")

    assert not (workdir / "dist-git").exists()


def test_prepare_copr_continues_when_pr_source_checkout_fails(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(workspace, "clone_repos", lambda workdir: None)
    monkeypatch.setattr(
        workspace, "install_skill", lambda workdir, skill_source, skill_name=None: None
    )

    def fake_clone_pr_package(workdir, clone_url, commit, package):
        raise subprocess.CalledProcessError(1, ["git", "switch", "-d", commit])

    monkeypatch.setattr(workspace, "clone_pr_package", fake_clone_pr_package)

    def fake_download(build_id, dest, chroot):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "foo.rpm").write_text("")

    monkeypatch.setattr(workspace.copr, "download_artifacts", fake_download)

    workspace.prepare_copr(
        tmp_path,
        build_id="123",
        chroot="fedora-rawhide-x86_64",
        pr_clone_url="https://example.com/pr.git",
        pr_commit="deadbeef",
        pr_package="foo",
        skill_source=tmp_path,
    )

    assert not (tmp_path / "dist-git").exists()
    assert (tmp_path / "copr-buildinfo.txt").exists()


def test_prepare_skips_dist_git_when_source_is_not_scm(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(workspace, "clone_repos", lambda workdir: None)
    monkeypatch.setattr(
        workspace, "install_skill", lambda workdir, skill_source: None
    )
    monkeypatch.setattr(workspace.koji, "fetch_taskinfo", lambda task_id, profile=None: "Task: 1\n")
    clone_dist_git_calls = []
    monkeypatch.setattr(
        workspace, "clone_dist_git", lambda *a, **kw: clone_dist_git_calls.append(a)
    )

    def fake_download(task_id, dest, profile=None):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "foo.rpm").write_text("")

    monkeypatch.setattr(workspace.koji, "download_artifacts", fake_download)

    workspace.prepare(tmp_path, "123456", skill_source=tmp_path)

    assert clone_dist_git_calls == []
    assert not (tmp_path / "dist-git").exists()
