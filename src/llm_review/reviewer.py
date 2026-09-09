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

# \**\s* tolerates the model bolding the word (**approve**) or adding a
# leading space despite instructions to write it bare; \b stops the match
# at the word itself, ignoring trailing punctuation/prose on the same line
# (e.g. "**Approve.** The specific change...").
_VERDICT_RE = re.compile(
    r"###\s*VERDICT\s*\n+\s*\**\s*(approve|needs fixes|needs discussion|error)\b",
    re.IGNORECASE,
)

VERDICTS = ("approve", "needs fixes", "needs discussion", "error")

_SUMMARY_SECTION_RE = re.compile(
    r"###\s*SUMMARY\s*\n(.*?)(?=\n###\s|\Z)", re.IGNORECASE | re.DOTALL
)
_SUMMARY_LINE_RE = re.compile(
    r"^\s*-?\s*(Blockers?|Should-fix|Minor)\s*:\s*(\d+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SUMMARY_KEY_TO_CATEGORY = {
    "blocker": "blocker",
    "blockers": "blocker",
    "should-fix": "should-fix",
    "minor": "minor",
}

ISSUE_CATEGORIES = ("blocker", "should-fix", "minor")


class ReviewError(RuntimeError):
    """Raised when the review session fails or produces no usable report.

    Carries the raw report text when one was written but couldn't be parsed
    (e.g. no ``### VERDICT`` line), so the caller can preserve it for
    debugging before the ephemeral workdir it lives in gets cleaned up --
    losing it made a real failure unrecoverable to diagnose.
    """

    def __init__(self, message: str, report: str | None = None) -> None:
        super().__init__(message)
        self.report = report


@dataclass
class ReviewResult:
    report: str
    verdict: str
    transcript: str
    issue_counts: dict[str, int]


def _extract_verdict(report: str) -> str:
    match = _VERDICT_RE.search(report)
    if not match:
        raise ReviewError(
            "Could not find a '### VERDICT' line in the review report", report=report
        )
    return match.group(1).lower()


def _count_issues(report: str) -> dict[str, int]:
    """Read the per-category issue counts from the ### SUMMARY section.

    The skill is instructed to count its own ### ISSUES list and report the
    totals in a fixed `Category: N` format -- parsing that is far more
    reliable than us re-deriving counts from free-form issue prose (which
    previously miscounted negations like "No **Blocker** issues were found."
    as an actual blocker). Missing/malformed lines default to 0 rather than
    failing the whole review over a formatting slip in a non-essential field.

    A verdict of "approve" can still come with minor (or should-fix) issues
    noted -- these counts let callers surface that instead of collapsing
    everything down to the verdict alone.
    """
    counts = dict.fromkeys(ISSUE_CATEGORIES, 0)
    section_match = _SUMMARY_SECTION_RE.search(report)
    if not section_match:
        logger.warning(
            "Report has no ### SUMMARY section; issue counts default to 0 "
            "and may understate what's actually in ### ISSUES"
        )
        return counts
    for match in _SUMMARY_LINE_RE.finditer(section_match.group(1)):
        category = _SUMMARY_KEY_TO_CATEGORY[match.group(1).lower()]
        counts[category] = int(match.group(2))
    return counts


def _truncate(text: str, limit: int = 200) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tool_use_preview(block: ToolUseBlock) -> str:
    for key in _TOOL_INPUT_PREVIEW_KEYS:
        if key in block.input:
            return _truncate(str(block.input[key]))
    return _truncate(str(block.input)) if block.input else ""


def _result_error_text(message: ResultMessage) -> str:
    """Best-effort human-readable text for a failed ResultMessage.

    An API-level failure (rate limit, auth, ...) arrives with
    ``subtype == "success"`` (sic) and the actual error text in ``result``;
    using ``subtype`` alone there produces a self-contradictory message like
    "Claude session ended in error: success". Prefer ``result`` when it's
    actually populated, falling back to ``subtype`` for terminal errors the
    CLI reports directly (``error_max_turns``, ``error_during_execution``, ...).
    """
    if message.result:
        return message.result
    return message.subtype


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
                raise ReviewError(f"Claude session ended in error: {_result_error_text(message)}")
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
