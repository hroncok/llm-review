from llm_review import workspace
from llm_review.cli import _resolve_source, parse_args


def test_resolve_source_koji_task():
    args = parse_args(["123456"])
    prepare, skill_name, context_file, source_desc = _resolve_source(args)

    assert skill_name == workspace.SKILL_NAME_KOJI
    assert context_file == "koji-taskinfo.txt"
    assert source_desc == "Koji task 123456"


def test_resolve_source_copr_build():
    args = parse_args(
        [
            "--copr-build",
            "10660758",
            "--pr-clone-url",
            "https://example.com/pr.git",
            "--pr-commit",
            "deadbeef",
            "--pr-package",
            "foo",
        ]
    )
    prepare, skill_name, context_file, source_desc = _resolve_source(args)

    assert skill_name == workspace.SKILL_NAME_COPR
    assert context_file == "copr-buildinfo.txt"
    assert "10660758" in source_desc


def test_resolve_source_rejects_both_koji_and_copr():
    args = parse_args(["123456", "--copr-build", "999"])
    assert _resolve_source(args) is None


def test_resolve_source_rejects_neither_koji_nor_copr():
    args = parse_args([])
    args.task = None  # in case $KOJI_TASK_ID happens to be set in the test env
    assert _resolve_source(args) is None


def test_resolve_source_copr_requires_pr_args():
    args = parse_args(["--copr-build", "10660758"])
    assert _resolve_source(args) is None
