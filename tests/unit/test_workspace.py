from pathlib import Path

import pytest

from llm_review.workspace import WorkspaceError, ensure_has_rpm_artifacts


def test_ensure_has_rpm_artifacts_passes_with_rpms(tmp_path: Path):
    (tmp_path / "foo-1.0-1.fc99.src.rpm").write_text("")
    (tmp_path / "foo-1.0-1.fc99.noarch.rpm").write_text("")

    ensure_has_rpm_artifacts(tmp_path, task_id="123456")  # must not raise


def test_ensure_has_rpm_artifacts_raises_when_empty(tmp_path: Path):
    with pytest.raises(WorkspaceError, match="123456"):
        ensure_has_rpm_artifacts(tmp_path, task_id="123456")


def test_ensure_has_rpm_artifacts_raises_when_only_logs(tmp_path: Path):
    (tmp_path / "build.log").write_text("")
    (tmp_path / "root.log").write_text("")

    with pytest.raises(WorkspaceError):
        ensure_has_rpm_artifacts(tmp_path, task_id="123456")
