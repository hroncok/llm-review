import pytest

from llm_review.koji import KojiError, parse_task_id


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
