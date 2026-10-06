import gzip
from pathlib import Path

import pytest

from llm_review import copr as copr_module
from llm_review.copr import CoprError, DEFAULT_CHROOT, download_artifacts, parse_build_id


def test_parse_build_id_bare():
    assert parse_build_id("123456") == "123456"


def test_parse_build_id_bare_with_whitespace():
    assert parse_build_id("  123456  ") == "123456"


def test_parse_build_id_url():
    url = "https://copr.fedorainfracloud.org/coprs/build/10660758/"
    assert parse_build_id(url) == "10660758"


def test_parse_build_id_url_without_trailing_slash():
    url = "https://copr.fedorainfracloud.org/coprs/build/10660758"
    assert parse_build_id(url) == "10660758"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-build-id",
        "https://copr.fedorainfracloud.org/coprs/g/fedora-review/some-project/",
    ],
)
def test_parse_build_id_invalid(value):
    with pytest.raises(CoprError):
        parse_build_id(value)


def _write(path: Path, content: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_download_artifacts_passes_noauth_equivalent_command(monkeypatch, tmp_path):
    # copr-cli download-build needs no credentials for a public build (see
    # copr.py's docstring) -- just confirm we invoke it directly, with no
    # config-file dance like koji's --noauth fix needed.
    calls = []

    def fake_run_with_retry(cmd, **kwargs):
        calls.append(cmd)
        chroot_dir = tmp_path / "dest" / DEFAULT_CHROOT
        _write(chroot_dir / "foo-1.0-1.fc99.src.rpm")
        _write(chroot_dir / "foo-1.0-1.fc99.noarch.rpm")
        _write(chroot_dir / "build.log.gz", gzip.compress(b"log contents"))

    monkeypatch.setattr(copr_module, "run_with_retry", fake_run_with_retry)

    download_artifacts("123", tmp_path / "dest")

    assert calls == [
        ["copr-cli", "download-build", "123", "-r", DEFAULT_CHROOT, "--dest", str(tmp_path / "dest")]
    ]


def test_download_artifacts_flattens_and_relabels_logs(monkeypatch, tmp_path):
    def fake_run_with_retry(cmd, **kwargs):
        chroot_dir = tmp_path / "dest" / "fedora-rawhide-x86_64"
        _write(chroot_dir / "foo-1.0-1.fc99.src.rpm", b"srpm")
        _write(chroot_dir / "foo-1.0-1.fc99.noarch.rpm", b"rpm")
        _write(chroot_dir / "build.log.gz", gzip.compress(b"build succeeded"))
        _write(chroot_dir / "root.log.gz", gzip.compress(b"root log"))

    monkeypatch.setattr(copr_module, "run_with_retry", fake_run_with_retry)

    dest = tmp_path / "dest"
    download_artifacts("123", dest, chroot="fedora-rawhide-x86_64")

    assert (dest / "foo-1.0-1.fc99.src.rpm").read_bytes() == b"srpm"
    assert (dest / "foo-1.0-1.fc99.noarch.rpm").read_bytes() == b"rpm"
    assert (dest / "build.fedora-rawhide-x86_64.log").read_bytes() == b"build succeeded"
    assert not (dest / "build.log.gz").exists()
    assert not (dest / "fedora-rawhide-x86_64").exists()


def test_download_artifacts_leaves_dest_empty_when_chroot_missing(monkeypatch, tmp_path):
    # No results for the requested chroot (e.g. build hasn't finished there).
    # Leave `dest` empty rather than raising -- workspace.ensure_has_rpm_artifacts()
    # reports this the same generic way it does for an empty Koji download.
    monkeypatch.setattr(copr_module, "run_with_retry", lambda cmd, **kwargs: None)

    dest = tmp_path / "dest"
    download_artifacts("123", dest, chroot="fedora-rawhide-x86_64")

    assert list(dest.iterdir()) == []
