"""Resolve a Copr build and download its artifacts for one chroot.

Mirrors ``koji.py``'s approach: shell out to the existing ``copr-cli`` tool
(already the standard way to interact with Copr from a script/CI job)
instead of depending on the ``python3-copr`` library, which -- like the
``koji`` CLI tool vs. a koji python library -- is the simpler, more portable
choice for a project installed via plain ``pip``.
"""

from __future__ import annotations

import gzip
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .retry import run_with_retry

DEFAULT_CHROOT = "fedora-rawhide-x86_64"

_BUILD_ID_RE = re.compile(r"^\d+$")


class CoprError(RuntimeError):
    """Raised when a Copr build ID can't be resolved or its artifacts fetched."""


def parse_build_id(value: str) -> str:
    """Accept a bare Copr build ID or a build URL; return the ID."""
    value = value.strip()
    if _BUILD_ID_RE.match(value):
        return value
    # e.g. https://copr.fedorainfracloud.org/coprs/build/10660758/
    match = re.search(r"/coprs/build/(\d+)", urlparse(value).path)
    if match:
        return match.group(1)
    # Tolerate a stray query-string form too, for consistency with koji's URL input.
    build_ids = parse_qs(urlparse(value).query).get("buildID")
    if build_ids and _BUILD_ID_RE.match(build_ids[0]):
        return build_ids[0]
    raise CoprError(f"Could not extract a Copr build ID from {value!r}")


def _gunzip_and_relabel_logs(chroot_dir: Path, chroot: str) -> None:
    """Decompress ``*.log.gz`` to ``*.log`` and rename ``build.log`` -> ``build.<chroot>.log``.

    Keeps the ``build.<label>.log`` naming convention (from
    ``skills/_fragments/inventory-copr.md``) working the same way regardless
    of download source, and avoids teaching the skill a second,
    source-specific detail (that Copr logs arrive gzipped).
    """
    for gz_path in chroot_dir.glob("*.log.gz"):
        log_path = gz_path.with_suffix("")  # drop ".gz"
        with gzip.open(gz_path, "rb") as src, log_path.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        gz_path.unlink()

    for log_path in chroot_dir.glob("*.log"):
        if log_path.stem == "build":
            log_path.rename(chroot_dir / f"build.{chroot}.log")


def download_artifacts(build_id: str, dest: Path, chroot: str = DEFAULT_CHROOT) -> None:
    """Download ``build_id``'s SRPM, RPMs, and logs for ``chroot`` into ``dest``.

    Works against a public build with no Copr credentials at all --
    ``copr-cli download-build`` doesn't require authentication for this
    (unlike e.g. ``cancel``/``create``), mirroring the ``koji --noauth``
    situation already handled in ``koji.py``.
    """
    dest.mkdir(parents=True, exist_ok=True)
    run_with_retry(
        ["copr-cli", "download-build", build_id, "-r", chroot, "--dest", str(dest)],
    )
    chroot_dir = dest / chroot
    if not chroot_dir.is_dir():
        # Nothing downloaded for this chroot (e.g. it hasn't finished, or
        # failed before producing any output) -- leave `dest` empty and let
        # workspace.ensure_has_rpm_artifacts() report it the same generic
        # way it does for an empty Koji download.
        return

    _gunzip_and_relabel_logs(chroot_dir, chroot)
    for path in chroot_dir.iterdir():
        shutil.move(str(path), dest / path.name)
    chroot_dir.rmdir()
