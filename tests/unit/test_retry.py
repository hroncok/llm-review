import subprocess

import pytest

from llm_review.retry import run_with_retry


def _fake_run_factory(failures: int, calls: list):
    """subprocess.run stand-in: raises CalledProcessError `failures` times."""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if len(calls) <= failures:
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    return fake_run


def test_run_with_retry_succeeds_first_try(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", _fake_run_factory(0, calls))

    result = run_with_retry(["echo", "hi"], sleep=lambda _: None)

    assert result.returncode == 0
    assert len(calls) == 1


def test_run_with_retry_succeeds_after_transient_failures(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", _fake_run_factory(2, calls))
    sleeps = []

    result = run_with_retry(["echo", "hi"], sleep=sleeps.append)

    assert result.returncode == 0
    assert len(calls) == 3
    assert len(sleeps) == 2


def test_run_with_retry_gives_up_after_max_retries(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", _fake_run_factory(99, calls))
    sleeps = []

    with pytest.raises(subprocess.CalledProcessError):
        run_with_retry(["echo", "hi"], max_retries=2, sleep=sleeps.append)

    assert len(calls) == 3  # initial attempt + 2 retries
    assert len(sleeps) == 2


def test_run_with_retry_backoff_is_exponential(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", _fake_run_factory(3, calls))
    sleeps = []

    run_with_retry(["echo", "hi"], max_retries=3, sleep=sleeps.append)

    assert sleeps == [5.0, 10.0, 20.0]


def test_run_with_retry_calls_on_retry_before_each_retry(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", _fake_run_factory(2, calls))
    on_retry_calls = []

    run_with_retry(
        ["echo", "hi"],
        sleep=lambda _: None,
        on_retry=lambda: on_retry_calls.append(1),
    )

    assert len(on_retry_calls) == 2


def test_run_with_retry_does_not_call_on_retry_when_no_failure(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", _fake_run_factory(0, calls))
    on_retry_calls = []

    run_with_retry(
        ["echo", "hi"],
        sleep=lambda _: None,
        on_retry=lambda: on_retry_calls.append(1),
    )

    assert on_retry_calls == []
