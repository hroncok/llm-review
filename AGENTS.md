# AGENTS.md

Instructions for AI coding agents (and human contributors) working on this
repository. See `README.md` for user-facing usage docs; this file is about
how to *work on* the project — conventions, architecture, and gotchas that
aren't obvious from reading the code once.

## What this project is

An unattended, Fedora-CI-shaped tool that runs an AI-powered Fedora package
review. Given a Koji scratch-build task ID, it downloads the SRPM/RPMs, runs
the `fedora-package-review` skill (`skills/fedora-package-review/SKILL.md`)
against them via the Claude Agent SDK, and writes the result the way Fedora
CI results are normally presented (a tmt custom `results.yaml` + artifacts —
see "Results semantics" below). There is deliberately **no posting to any
external API** (Bugzilla, a PR, ResultsDB, ...) — Fedora CI's own dashboard
renders whatever lands in `results.yaml`/`$TMT_TEST_DATA`.

## Architecture

Each module in `src/llm_review/` has one job; read them in this order to
understand the pipeline:

1. **`koji.py`** — resolves a bare task ID or a `taskinfo?taskID=...` URL,
   and downloads a task's artifacts (`koji download-task <id> --logs`). No
   dist-git checkout — the skill extracts the spec file from the SRPM
   itself, so there's no need to clone the package's dist-git repo.
2. **`workspace.py`** — prepares the ephemeral session directory: shallow
   guidelines clone, skill install, Koji download, and (important — see
   below) a **deterministic check that the download actually produced RPM
   files** before ever calling the LLM.
3. **`reviewer.py`** — runs the skill via `claude_agent_sdk.query()`,
   streams progress (assistant text + tool calls) to the log, and parses the
   final report's `### VERDICT` line and `### ISSUES` section.
4. **`results.py`** — maps a verdict to a tmt result outcome and writes
   `results.yaml` + `review.md` (+ logs) to `$TMT_TEST_DATA`/`--output-dir`.
5. **`config.py`** — Vertex/Bedrock backend selection, see below.
6. **`cli.py`** — wires the above together; `python -m llm_review` entry
   point.

Design principle throughout: **reuse the existing
[`packit/tmt-plans`](https://github.com/packit/tmt-plans) ecosystem's
conventions instead of inventing new ones.** This project was built by
directly reading a local checkout of that repo (see its
`tests/fedora-review/run-fedora-review.py` and `utils/__init__.py`) — the
`koji taskinfo`/`download-task` usage, the `/prepare` + `/run-*` tmt test
split, and the `results.yaml` custom-result approach are all copied from
there, not designed from scratch. If you're extending this project and
something looks like it should have prior art in that ecosystem, check
there first.

## The skill (`skills/fedora-package-review/SKILL.md`)

This is a **copy**, adapted for unattended CI use, of the user's personal
interactive Claude Code skill at `~/.claude/skills/fedora-package-review/`.
**Do not edit `~/.claude/skills/...`** as part of work in this repo — the two
are intentionally independent (the original reviews COPR/Bugzilla builds
interactively; this one reviews a pre-staged Koji-task workspace
unattended). If the upstream personal skill gets improved in ways relevant
here (e.g. a better license-verification technique), port the change
manually.

Key adaptations from the original:
- Input is a pre-staged `$WORKDIR` (guidelines + `artifacts/` +
  `koji-taskinfo.txt`), not a Bugzilla/COPR lookup the skill does itself.
- Step 1 (guidelines) has no "ask the user" branch — there's no human to
  ask in CI, so guidelines are always pre-cloned.
- No COPR fedora-review-service artifacts (`review.txt`/`rpmlint.txt`/
  `licensecheck.txt`) exist for a Koji build — the skill runs `rpmlint`
  itself and does license verification manually.
- The report must be written to `$REVIEW_OUTPUT_PATH` — this is the only
  way the Python side retrieves the result; nothing said only in the chat
  transcript is recoverable.
- The `### VERDICT` line is one of `approve` / `needs fixes` /
  `needs discussion` / `error`, parsed by `reviewer._VERDICT_RE`. **If you
  change these strings, update `reviewer.VERDICTS`/`_VERDICT_RE` and
  `results.VERDICT_TO_RESULT` in the same change** — they must stay in
  sync, and nothing enforces that automatically.

## Results semantics — verdict vs. outcome

This distinction was a real bug we fixed, worth preserving explicitly:

- A verdict is what the **LLM** decides after reviewing an actual package:
  `approve` (pass), `needs fixes` (fail), `needs discussion` (info — a
  genuine, substantive judgment call).
- `error` is different in kind, not degree: it means **the review could not
  be performed at all** — there was nothing to check, or something broke
  the process itself (corrupted SRPM, no artifacts, LLM session crash).
  It must never be conflated with `needs discussion`.
- Because an LLM can't be trusted to always self-report "there's nothing
  here" correctly, `workspace.ensure_has_rpm_artifacts()` catches the most
  common cause (a Koji task with zero `.rpm` files — e.g. expired task
  output) **deterministically in Python, before spending an LLM call on
  it**. The skill's own `error` verdict is the backstop for failure modes
  only discoverable mid-review (corrupted archive, missing spec, ...).
- `cli.py` routes every failure path (`WorkspaceError`, `ReviewError`) through
  `results.write_error()` so a `results.yaml` is *always* produced — never
  exit silently with just a log line and no result file.
- tmt's `result_note` field (`tmt/schemas/common.yaml`) is a plain
  **string**, not a list — even though upstream `packit/tmt-plans` code
  sometimes writes `note: [single_item]`, don't copy that; keep it a single
  string here (see `results._issue_counts_note` composing one string with
  `; `).
- Exit codes mirror the tmt result: `pass`/`info` → 0, `fail` → 1,
  `error` → 2. Argument/config validation errors in `cli.py` also return 2,
  consistent with `error` being "something's wrong with the setup," not
  "the package has problems."

## Backend configuration (Vertex / Bedrock)

`config.py` is deliberately thin: it does not implement any provider
authentication. It only toggles the same environment variables Claude Code
itself already documents, and validates they're present:

- Vertex (today's default, and what's actually usable right now via the
  developer's `gcloud` ADC login): `CLAUDE_CODE_USE_VERTEX=1`,
  `CLOUD_ML_REGION`, `ANTHROPIC_VERTEX_PROJECT_ID`.
- Bedrock (not yet available to the project owner, but zero extra design
  cost): `CLAUDE_CODE_USE_BEDROCK=1`, `AWS_REGION`.

If you need to support a new knob (a new pinned model env var, a new
region override, etc.), extend `_REQUIRED_ENV_VARS` and the `if backend ==
...` branches in `load_backend_config` — don't build a parallel
config-file system; env vars are the intentional single source of truth
here, matching how Claude Code itself is configured (and how Fedora CI/tmt
plans pass in configuration generally, e.g. `KOJI_TASK_ID`).

## Skill packaging gotcha (already fixed, don't regress)

`workspace.default_skill_source()` resolves the skill directory in three
steps: `$LLM_REVIEW_SKILL_DIR` override → the repo's top-level `skills/`
directory (works for editable installs / running in place) → a copy bundled
as package data via `[tool.hatch.build.targets.wheel.force-include]` in
`pyproject.toml`. **This is load-bearing**: a naive `Path(__file__).parents[2]
/ "skills" / ...` resolution silently breaks for a regular non-editable
`pip install .`, because the sibling `skills/` directory doesn't exist in
`site-packages`. This was a real bug found via live testing — if you touch
`default_skill_source()` or the wheel packaging config, verify with an
actual non-editable install from a fresh venv, not just the dev `.venv`
(editable installs mask this class of bug).

## Testing

- `tests/unit/` — pytest, **pure logic only, no network or LLM calls**
  (Koji ID/URL parsing, backend env construction, verdict→result mapping,
  artifact-presence checks, log-preview truncation). Run with
  `.venv/bin/pytest -q` (or `pip install -e '.[test]'` + `pytest`).
- `tests/llm-review/`, `plans/` — tmt fmf metadata, not pytest. Validate
  with `tmt lint` after touching them (a plan needs `plans/main.fmf` to
  provide `execute: how: tmt` for `plans/llm-review/main.fmf` to be
  recognized at all — this is easy to get wrong silently, since `tmt plans
  ls` just prints nothing instead of erroring when a plan node is
  malformed).
- Always run `ruff check src tests` alongside pytest; it's part of what
  "done" means for a change here.
- **There is no mocking of the Claude Agent SDK.** An actual end-to-end run
  (`python -m llm_review <task-id>`) makes a real, billed call to whichever
  backend is configured (Vertex today). Don't run one casually while
  iterating — prefer the unit tests, and only do a live run when you
  specifically need to verify SDK-facing behavior (prompt wording, tool
  permissions, message-stream handling), and mention to the user that
  you're about to spend real API budget before doing so.

## Git conventions

- Only commit when the user explicitly asks — this project follows the
  general Claude Code default of not committing proactively.
- Trailer: use `Assisted-By: <model name>` (e.g. `Assisted-By: Claude Sonnet
  5`), **not** the default `Co-Authored-By: <model> <noreply@anthropic.com>`.
  No email address. Use whichever model actually did the work — don't
  hardcode a specific model name in tooling or templates, since it will
  change over time.
