from pathlib import Path

import pytest

from llm_review.koji import (
    KojiError,
    _reorganize_downloaded_tasks,
    parse_source_scm,
    parse_task_id,
)


def test_parse_task_id_bare():
    assert parse_task_id("123456789") == "123456789"


def test_parse_task_id_bare_with_whitespace():
    assert parse_task_id("  123456789  ") == "123456789"


def test_parse_task_id_url():
    url = "https://koji.fedoraproject.org/koji/taskinfo?taskID=123456789"
    assert parse_task_id(url) == "123456789"


def test_parse_task_id_url_with_extra_query_args():
    url = "https://koji.fedoraproject.org/koji/taskinfo?foo=bar&taskID=42"
    assert parse_task_id(url) == "42"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-task-id",
        "https://koji.fedoraproject.org/koji/taskinfo?taskID=abc",
        "https://koji.fedoraproject.org/koji/buildinfo?buildID=123",
    ],
)
def test_parse_task_id_invalid(value):
    with pytest.raises(KojiError):
        parse_task_id(value)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_reorganize_downloaded_tasks_disambiguates_same_named_logs_by_label(tmp_path):
    # Real-world case: a buildSRPMFromSCM subtask (label "srpm") and a
    # noarch buildArch subtask (label "noarch") coincidentally ran on
    # same-arch builder hosts, so koji's own flat download would have
    # silently skipped downloading the second (real) build.log as an
    # "already downloaded" duplicate of the first (SRPM-only) one.
    tmp_dir = tmp_path / "downloaded"
    dest = tmp_path / "dest"
    dest.mkdir()
    _write(tmp_dir / "150016654" / "build.log", "srpm generation log")
    _write(tmp_dir / "150016740" / "build.log", "real %build/%check log")
    children = [
        {"id": 150016654, "method": "buildSRPMFromSCM", "label": "srpm"},
        {"id": 150016740, "method": "buildArch", "label": "noarch"},
    ]

    _reorganize_downloaded_tasks(tmp_dir, dest, children)

    assert (dest / "build.srpm.log").read_text() == "srpm generation log"
    assert (dest / "build.noarch.log").read_text() == "real %build/%check log"


def test_reorganize_downloaded_tasks_keeps_rpm_filenames_as_is(tmp_path):
    tmp_dir = tmp_path / "downloaded"
    dest = tmp_path / "dest"
    dest.mkdir()
    _write(tmp_dir / "150016740" / "foo-1.0-1.fc46.noarch.rpm", "rpm content")
    children = [{"id": 150016740, "method": "buildArch", "label": "noarch"}]

    _reorganize_downloaded_tasks(tmp_dir, dest, children)

    assert (dest / "foo-1.0-1.fc46.noarch.rpm").read_text() == "rpm content"


def test_reorganize_downloaded_tasks_falls_back_to_task_id_without_label(tmp_path):
    tmp_dir = tmp_path / "downloaded"
    dest = tmp_path / "dest"
    dest.mkdir()
    _write(tmp_dir / "150016654" / "build.log", "some log")

    _reorganize_downloaded_tasks(tmp_dir, dest, children=[])

    assert (dest / "build.150016654.log").read_text() == "some log"


def test_parse_source_scm_real_taskinfo_output():
    # Real `koji taskinfo -v` output has the Source: line indented under
    # "Request Parameters:".
    taskinfo = (
        "Task: 150016639\n"
        "Type: build\n"
        "Request Parameters:\n"
        "  Source: git+https://src.fedoraproject.org/forks/churchyard/rpms/"
        "python-pip.git#27a9e0d2f29eb7841cfb5d4503f05c6dfec7d4d4\n"
        "  Build Target: rawhide\n"
    )
    assert parse_source_scm(taskinfo) == (
        "https://src.fedoraproject.org/forks/churchyard/rpms/python-pip.git",
        "27a9e0d2f29eb7841cfb5d4503f05c6dfec7d4d4",
    )


def test_parse_source_scm_no_source_line():
    assert parse_source_scm("Task: 1\nType: build\n") is None


def test_parse_source_scm_non_git_source():
    # e.g. a task built from a raw uploaded SRPM, not dist-git.
    taskinfo = "Request Parameters:\n  Source: cli-build/some.src.rpm\n"
    assert parse_source_scm(taskinfo) is None
