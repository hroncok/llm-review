"""Drive a Claude Agent SDK session that runs the fedora-package-review skill."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from .config import BackendConfig

logger = logging.getLogger(__name__)

SKILL_NAME = "fedora-package-review"

# Tool input keys worth showing as a one-line progress indicator, in order of
# preference (Bash's "command", Read/Glob's "file_path"/"path", Grep's
# "pattern").
_TOOL_INPUT_PREVIEW_KEYS = ("command", "file_path", "pattern", "path")

PROMPT = (
    "Use the fedora-package-review skill to review the Fedora package build "
    "prepared in this workspace. Write the final report to $REVIEW_OUTPUT_PATH "
    "as instructed by the skill."
)

_VERDICT_RE = re.compile(
    r"###\s*VERDICT\s*\n+\s*(approve|needs fixes|needs discussion|error)",
    re.IGNORECASE,
)

VERDICTS = ("approve", "needs fixes", "needs discussion", "error")

_ISSUES_SECTION_RE = re.compile(
    r"###\s*ISSUES\s*\n(.*?)(?=\n###\s|\Z)", re.IGNORECASE | re.DOTALL
)
_ISSUE_CATEGORY_RE = re.compile(r"\*\*(Blocker|Should-fix|Minor)\*\*", re.IGNORECASE)

ISSUE_CATEGORIES = ("blocker", "should-fix", "minor")


class ReviewError(RuntimeError):
    """Raised when the review session fails or produces no usable report."""


@dataclass
class ReviewResult:
    report: str
    verdict: str
    transcript: str
    issue_counts: dict[str, int]


def _extract_verdict(report: str) -> str:
    match = _VERDICT_RE.search(report)
    if not match:
        raise ReviewError("Could not find a '### VERDICT' line in the review report")
    return match.group(1).lower()


def _count_issues(report: str) -> dict[str, int]:
    """Count issues per category (blocker/should-fix/minor) in the ### ISSUES section.

    A verdict of "approve" can still come with minor (or should-fix) issues
    noted -- these counts let callers surface that instead of collapsing
    everything down to the verdict alone.
    """
    counts = dict.fromkeys(ISSUE_CATEGORIES, 0)
    section_match = _ISSUES_SECTION_RE.search(report)
    if not section_match:
        return counts
    for match in _ISSUE_CATEGORY_RE.finditer(section_match.group(1)):
        counts[match.group(1).lower()] += 1
    return counts


def _truncate(text: str, limit: int = 200) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tool_use_preview(block: ToolUseBlock) -> str:
    for key in _TOOL_INPUT_PREVIEW_KEYS:
        if key in block.input:
            return _truncate(str(block.input[key]))
    return _truncate(str(block.input)) if block.input else ""


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
        tools=["Bash", "Read", "Grep", "Glob", "Skill"],
        permission_mode="bypassPermissions",
    )

    transcript_parts: list[str] = []
    async for message in query(prompt=PROMPT, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    transcript_parts.append(block.text)
                    logger.info("Claude: %s", _truncate(block.text))
                elif isinstance(block, ToolUseBlock):
                    preview = _tool_use_preview(block)
                    logger.info(
                        "Tool call: %s%s", block.name, f"({preview})" if preview else ""
                    )
        elif isinstance(message, ResultMessage):
            if message.is_error:
                raise ReviewError(f"Claude session ended in error: {message.subtype}")
            logger.info(
                "Session finished in %d turn(s), %.1fs",
                message.num_turns,
                message.duration_ms / 1000,
            )

    if not output_path.exists():
        raise ReviewError(f"Skill did not write a report to {output_path}")

    report = output_path.read_text()
    verdict = _extract_verdict(report)
    return ReviewResult(
        report=report,
        verdict=verdict,
        transcript="\n\n".join(transcript_parts),
        issue_counts=_count_issues(report),
    )


def run_review(workdir: Path, backend: BackendConfig, output_path: Path) -> ReviewResult:
    return asyncio.run(_run(workdir, backend, output_path))
