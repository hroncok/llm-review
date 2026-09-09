"""Backend (Google Vertex AI / Amazon Bedrock) selection.

This module does not implement provider authentication itself -- it only
toggles the same environment variables Claude Code already documents for
each backend, and validates that they're present. Actual credentials (gcloud
Application Default Credentials, or the AWS credential chain) are expected to
already be set up in the environment the tool runs in.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_BACKEND = "vertex"

# Env vars this tool requires *from the caller's environment* per backend,
# beyond whatever the provider's own credential chain needs.
_REQUIRED_ENV_VARS: dict[str, tuple[str, ...]] = {
    "vertex": ("ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION"),
    "bedrock": ("AWS_REGION",),
}


class ConfigError(RuntimeError):
    """Raised when the selected backend is missing required configuration."""


@dataclass(frozen=True)
class BackendConfig:
    backend: str
    model: str | None
    env: dict[str, str]


def load_backend_config(environ: dict[str, str] | None = None) -> BackendConfig:
    """Build the env-var overlay to hand to ``ClaudeAgentOptions.env``.

    Reads ``LLM_REVIEW_BACKEND`` (``"vertex"`` or ``"bedrock"``, default
    ``"vertex"``) and ``LLM_REVIEW_MODEL`` (optional model override).
    """
    environ = os.environ if environ is None else environ
    backend = environ.get("LLM_REVIEW_BACKEND", DEFAULT_BACKEND).strip().lower()
    if backend not in _REQUIRED_ENV_VARS:
        raise ConfigError(
            f"Unknown LLM_REVIEW_BACKEND {backend!r}; "
            f"expected one of {sorted(_REQUIRED_ENV_VARS)}"
        )

    missing = [name for name in _REQUIRED_ENV_VARS[backend] if not environ.get(name)]
    if missing:
        raise ConfigError(
            f"Backend {backend!r} is missing required environment variable(s): "
            + ", ".join(missing)
        )

    env: dict[str, str] = {}
    if backend == "vertex":
        env["CLAUDE_CODE_USE_VERTEX"] = "1"
        env["CLOUD_ML_REGION"] = environ["CLOUD_ML_REGION"]
        env["ANTHROPIC_VERTEX_PROJECT_ID"] = environ["ANTHROPIC_VERTEX_PROJECT_ID"]
    elif backend == "bedrock":
        env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        env["AWS_REGION"] = environ["AWS_REGION"]

    return BackendConfig(
        backend=backend,
        model=environ.get("LLM_REVIEW_MODEL") or None,
        env=env,
    )
