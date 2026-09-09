"""Drive a Claude Agent SDK session that runs the fedora-package-review skill."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from .config import BackendConfig

SKILL_NAME = "fedora-package-review"

PROMPT = (
    "Use the fedora-package-review skill to review the Fedora package build "
    "prepared in this workspace. Write the final report to $REVIEW_OUTPUT_PATH "
    "as instructed by the skill."
)

_VERDICT_RE = re.compile(
    r"###\s*VERDICT\s*\n+\s*(approve|needs fixes|needs discussion)",
    re.IGNORECASE,
)

VERDICTS = ("approve", "needs fixes", "needs discussion")


class ReviewError(RuntimeError):
    """Raised when the review session fails or produces no usable report."""


@dataclass
class ReviewResult:
    report: str
    verdict: str
    transcript: str


def _extract_verdict(report: str) -> str:
    match = _VERDICT_RE.search(report)
    if not match:
        raise ReviewError("Could not find a '### VERDICT' line in the review report")
    return match.group(1).lower()


async def _run(
    workdir: Path,
    backend: BackendConfig,
    output_path: Path,
) -> ReviewResult:
    options = ClaudeAgentOptions(
        cwd=str(workdir),
        env={**backend.env, "REVIEW_OUTPUT_PATH": str(output_path)},
        model=backend.model,
        skills=[SKILL_NAME],
        tools=["Bash", "Read", "Grep", "Glob"],
        permission_mode="bypassPermissions",
    )

    transcript_parts: list[str] = []
    async for message in query(prompt=PROMPT, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    transcript_parts.append(block.text)
        elif isinstance(message, ResultMessage) and message.is_error:
            raise ReviewError(f"Claude session ended in error: {message.subtype}")

    if not output_path.exists():
        raise ReviewError(f"Skill did not write a report to {output_path}")

    report = output_path.read_text()
    verdict = _extract_verdict(report)
    return ReviewResult(
        report=report,
        verdict=verdict,
        transcript="\n\n".join(transcript_parts),
    )


def run_review(workdir: Path, backend: BackendConfig, output_path: Path) -> ReviewResult:
    return asyncio.run(_run(workdir, backend, output_path))
