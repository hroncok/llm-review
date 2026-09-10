"""Retry helper for network-dependent subprocess calls (koji, git)."""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = int(os.environ.get("LLM_REVIEW_SUBPROCESS_MAX_RETRIES", "2"))
_RETRY_BACKOFF_BASE_S = 5.0


def run_with_retry(
    cmd: list[str],
    max_retries: int = DEFAULT_MAX_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[], None] | None = None,
    **kwargs,
) -> subprocess.CompletedProcess:
    """Run ``cmd`` via ``subprocess.run(cmd, check=True, **kwargs)``.

    Retries with exponential backoff on failure -- covers transient network
    issues talking to Koji or cloning the guidelines repo over git. Call
    ``on_retry`` (if given) before each retry, e.g. to clean up a partial
    ``git clone`` destination that would otherwise make the retry fail
    immediately with an unrelated "destination already exists" error.
    """
    for attempt in range(max_retries + 1):
        try:
            logger.info("Running: %s", shlex.join(cmd))
            return subprocess.run(cmd, check=True, **kwargs)
        except subprocess.CalledProcessError as exc:
            if attempt >= max_retries:
                logger.error(
                    "Giving up on %s after %d attempt(s): %s", cmd[0], attempt + 1, exc
                )
                raise
            wait = _RETRY_BACKOFF_BASE_S * (2**attempt)
            logger.warning(
                "%s failed on attempt %d/%d: %s -- retrying in %.0fs",
                cmd[0],
                attempt + 1,
                max_retries + 1,
                exc,
                wait,
            )
            if on_retry:
                on_retry()
            sleep(wait)
