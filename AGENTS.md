# AGENTS.md

Instructions for AI coding agents (and human contributors) working on this
repository. See `README.md` for user-facing usage docs; this file is about
how to *work on* the project — conventions, architecture, and gotchas that
aren't obvious from reading the code once.

**Persist project conventions/feedback here, not in a personal/local memory
system.** A memory system tied to one person's machine or session isn't
visible to other contributors or agents working on this repo. This file is
checked into git and visible to everyone. When you learn something worth
remembering about how to work on this project, add it here instead.

## What this project is

An unattended, Fedora-CI-shaped tool that runs an AI-powered Fedora package
review. Two independent input modes (see "The skills" and "The Copr/PR
review flow" below for the full picture):

- Given a Koji scratch-build task ID, it downloads the SRPM/RPMs, runs the
  `fedora-package-review-koji` skill
  (`skills/fedora-package-review-koji/SKILL.md`) against them via the Claude
  Agent SDK, and writes the result the way Fedora CI results are normally
  presented (a tmt custom `results.yaml` + artifacts — see "Results
  semantics" below).
- Given a single package's Copr build ID (from a
  forge.fedoraproject.org/packaging/package-review PR), it downloads that
  build's SRPM/RPMs for one chroot and runs the `fedora-package-review-copr`
  skill (`skills/fedora-package-review-copr/SKILL.md`) against them.

There is deliberately **no posting to any external API** (Bugzilla, a PR,
ResultsDB, ...) — Fedora CI's own dashboard renders whatever lands in
`results.yaml`/`$TMT_TEST_DATA`, and the Copr/PR flow's Forgejo job just
uploads its output as a build artifact.

## Architecture

Each module in `src/llm_review/` has one job; read them in this order to
understand the pipeline:

1. **`koji.py`** — resolves a bare task ID or a `taskinfo?taskID=...` URL,
   and downloads a task's artifacts (`koji download-task <id> --logs`). No
   dist-git checkout — the skill extracts the spec file from the SRPM
   itself, so there's no need to clone the package's dist-git repo.
2. **`workspace.py`** — prepares the ephemeral session directory: shallow
   clones of the Packaging Guidelines, Fedora Legal's policy docs
   (`legal-docs`), and the per-license database (`license-data`; see
   "License verification data sources" below), skill install, Koji
   download, and (important — see below) a **deterministic check that the
   download actually produced RPM files** before ever calling the LLM.
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

## The skills (`skills/fedora-package-review*/SKILL.md`) and how they're built

There are now **three** related skills, all unattended-CI adaptations of the
same underlying review process:

1. The user's personal interactive Claude Code skill at
   `~/.claude/skills/fedora-package-review/` (not part of this repo).
2. `skills/fedora-package-review-koji/SKILL.md` — reviews a pre-staged
   Koji-task workspace (Fedora CI, dist-git PRs).
3. `skills/fedora-package-review-copr/SKILL.md` — reviews a pre-staged
   Copr-build workspace, one package at a time (the
   forge.fedoraproject.org/packaging/package-review PR flow).

**Do not edit `~/.claude/skills/...`** as part of work in this repo — (1) is
intentionally independent of (2)/(3) (it reviews COPR/Bugzilla builds
interactively, doing its own lookups). If it gets improved in ways relevant
here (e.g. a better license-verification technique), port the change
manually.

(2) and (3) share almost all of their review logic (rpmlint, source
extraction, license verification, guideline checks, report template) and
only really differ in their "Input" and "Inventory the Build Artifacts"
sections (file names, and whether there's a Koji-specific SRPM-vs-real-log
distinction to worry about). To avoid hand-duplicating the shared content
across two files, **neither SKILL.md is edited directly** — both are
generated by `scripts/build_skills.py` from fragments in
`skills/_fragments/`:

- `input-koji.md` / `input-copr.md`, `inventory-koji.md` / `inventory-copr.md`
  — per-variant content.
- `guidelines.md`, `cannot-review.md`, `review-steps.md` — shared content,
  edit these for anything that should apply to both variants.

Run `python scripts/build_skills.py` after editing a fragment, and commit
the regenerated `SKILL.md` files alongside it (they're real committed files,
not built at install/CI time — `workspace.default_skill_source()` and the
wheel's `force-include` packaging just read them off disk like any other
skill file). `tests/unit/test_build_skills.py` regenerates in-memory and
fails if a committed `SKILL.md` doesn't match its fragments, to catch a
hand-edit of the generated file instead of the fragment.

Key adaptations shared by (2) and (3) from the original personal skill:
- Input is a pre-staged `$WORKDIR`, not a Bugzilla/COPR/PR lookup the skill
  does itself.
- Step 1 (guidelines) has no "ask the user" branch — there's no human to
  ask in CI, so guidelines are always pre-cloned.
- No COPR fedora-review-service artifacts (`review.txt`/`rpmlint.txt`/
  `licensecheck.txt`) are assumed to exist — the skill runs `rpmlint` itself
  and does license verification manually (true for both a Koji build, which
  never has them, and a Copr build, which could in principle but we don't
  rely on it).
- The report must be written to `$REVIEW_OUTPUT_PATH` — this is the only
  way the Python side retrieves the result; nothing said only in the chat
  transcript is recoverable.
- The `### VERDICT` line is one of `approve` / `needs fixes` /
  `needs discussion` / `error`, parsed by `reviewer._VERDICT_RE`. **If you
  change these strings, update `reviewer.VERDICTS`/`_VERDICT_RE` and
  `results.VERDICT_TO_RESULT` in the same change** — they must stay in
  sync, and nothing enforces that automatically.

## The Copr/PR review flow (`workspace.prepare_copr`, `copr.py`)

Hooks into a second, independent CI system:
https://forge.fedoraproject.org/packaging/package-review (a monorepo where a
PR proposes a new package as a `<name>/<name>.spec` subdirectory; its
`.forgejo/workflows/build-in-copr.yml` + the
[fedora-review-process-reimagined](https://github.com/FrostyX/fedora-review-process-reimagined)
script build each package added/changed in the PR as a separate Copr custom
build). `llm-review` reviews **one package's build at a time** — `cli.py`'s
`--copr-build`/`--pr-*` input mode, caller runs it once per package.

- `copr.py` shells out to the `copr-cli` tool (same reasoning as `koji.py`
  using the `koji` CLI instead of a koji python library): no
  `python3-copr`/API dependency needed, and it keeps the "no credentials
  needed for a public read" property (see below) simple to verify by
  reading `copr-cli`'s own source rather than a library's.
- `workspace.clone_pr_package()` is the Copr-flow analogue of
  `clone_dist_git()`: clones the PR's source repo at the exact build commit
  and copies out *only* the `<package>/` subdirectory into `$WORKDIR/dist-git/`
  — same directory name/shape the Koji flow uses, so the shared
  rpmlintrc-discovery fragment (`skills/_fragments/review-steps.md`) needs
  zero awareness of which flow it's running under.
- Copr chroot results don't have Koji's "SRPM-only subtask" gotcha — every
  chroot in `build_chroot_proxy.get_list()` (what `copr-cli download-build`
  downloads per `-r <chroot>`) is a real `%build`/`%install`/`%check` run;
  the SRPM-generation step is a separate, un-downloaded pseudo-chroot. That's
  why `input-copr.md`/`inventory-copr.md` carry no equivalent of the Koji
  variant's `*.srpm.log` caveat.

## Koji CLI auth: `--noauth`, not a Kerberos ticket

Every `koji` call this project makes (`taskinfo`, `call getTaskChildren`,
`download-task`) is a read-only operation and works fine against an
anonymous session on `koji.fedoraproject.org` — none of it needs a logged-in
user. Found live: running without a Kerberos ticket failed with
`GSSAPIAuthError: ... 401 Client Error: Unauthorized for url:
.../kojihub/ssllogin`. That looks like the *read call* was rejected for
lacking auth, but it's not — the `koji` CLI, per the machine's default
`authtype = kerberos` (`/etc/koji.conf`), tries to establish an
*authenticated* session before running any subcommand at all, read-only or
not, and that login attempt is what 401s with no ticket available. The fix
is `koji.py`'s `_global_args()` passing `--noauth` on every invocation,
which skips that login attempt entirely — **not** provisioning a Kerberos
keytab/service-account secret for CI, which would solve a problem that
doesn't actually exist here (and would be needless secret-handling
complexity for a tool that never needs to be a logged-in Koji user).

The same question came up for `copr.py`: does `copr-cli download-build` need
Copr credentials? Checked by reading `copr_cli/main.py` directly rather than
assuming symmetry with Koji -- `action_download_build` has no
`@requires_api_auth` decorator (unlike e.g. `cancel`/`create`), and
`config_from_file()` tolerates a completely missing `~/.config/copr` (falls
back to the public instance URL). `Commands.__init__` does default
`config["gssapi"] = True`, mirroring Koji's always-try-to-authenticate
default, but that only matters for calls that actually call
`auth_username()` (the `@requires_api_auth`-wrapped ones) -- `download-build`
never does, so no GSSAPI handshake is attempted and no credentials/ticket
are needed for downloading a public build's results.

## License verification data sources

Found live: the model called a `License:` field's SPDX expression
"redundant" using general reasoning, which was wrong -- License: field
composition rules are Fedora Legal's, not the Packaging Committee's, and
aren't in the Packaging Guidelines at all. Two more repos get cloned into
the workspace for this (`workspace.clone_repos`, via `REPOS_TO_CLONE`):

- `$WORKDIR/legal-docs/` —
  [`fedora-legal-docs`](https://gitlab.com/fedora/legal/fedora-legal-docs.git).
  `modules/ROOT/pages/license-field.adoc` has the actual composition rules
  (AND/OR structure, when a repeated license needs its own clause);
  `allowed-licenses.adoc` has the approval policy.
- `$WORKDIR/license-data/` —
  [`fedora-license-data`](https://forge.fedoraproject.org/legal/fedora-license-data.git).
  **Not** a docs repo — one `data/<SPDX-ID>.toml` file per license (e.g.
  `data/MIT.toml`), each with a `status` field (`allowed`, `not-allowed`,
  ...). A definitive per-license lookup, so the skill doesn't have to guess
  from memorized knowledge of what Fedora permits.

If you're tempted to point `allowed-licenses.adoc` at `license-data`
instead of `legal-docs`: don't, that was an initial wrong guess (based on
the name) corrected by actually cloning both repos and checking.

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
- tmt's `result_note` field is an **array of strings** (`results.py` writes
  `note: [...]`), matching `packit/tmt-plans`. Got this backwards once: a
  stale local `tmt` git checkout (1.30.0) had `result_note: type: string`,
  and that got trusted over the *actually installed* tmt (1.77.0), which has
  `type: array`. Check the installed package's own schema, not a local
  clone that could be an arbitrary vintage.
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

## SDK gotcha: `tools` vs `allowed_tools`/`skills`

`ClaudeAgentOptions.tools` (→ CLI `--tools`) is the *base set of available
built-in tools* — anything not listed is entirely unavailable, full stop.
`ClaudeAgentOptions.allowed_tools`/`skills` (→ CLI `--allowedTools`) only
*pre-approves permission* for tools that are already in that base set; it
cannot add a tool the base set excludes. Setting `skills=[SKILL_NAME]`
without also including `"Skill"` in `tools` silently makes the `Skill` tool
unavailable, so the model never formally invokes the skill — it just
happens to `find`/`Read` `SKILL.md` on its own initiative (which is why
things still mostly worked, misleadingly). `reviewer._run()`'s `tools=`
list must always include `"Skill"` whenever `skills=` is set. Caught by
watching a live run's tool-call log and seeing `find`/manual `Read` calls
hunting for the skill file instead of a `Skill` tool call.

## SDK gotcha: the subprocess inherits your real `~/.claude` unless redirected

`ClaudeAgentOptions.skills=[SKILL_NAME]` only filters what's *shown* to the
model — it is "a context filter, not a sandbox" (the SDK's own docstring):
unlisted skills' files are still on disk and reachable via Bash/Read. Left
alone, the subprocess spawned by `query()` inherits the developer's real
`HOME`, so it would also discover `~/.claude/skills/fedora-package-review`
— the developer's personal, *interactive* skill of the same name (see "The
skill" section above) — and could read from or get confused by it. Fixed by
setting `CLAUDE_CONFIG_DIR` (in `reviewer._run()`'s `env=`) to an empty
directory under the ephemeral workdir, which redirects the CLI's notion of
the user-level config/skills tree away from the real `~/.claude` entirely.
Project-level skill discovery (`<cwd>/.claude/skills`, i.e. the one
`workspace.install_skill()` populates) is unaffected — that's resolved via
`cwd`, not `CLAUDE_CONFIG_DIR`.

## SDK gotcha: `ResultMessage.subtype` can lie when `is_error` is set

An API-level failure (rate limit, auth, transient error, ...) arrives as a
`ResultMessage` with `subtype == "success"` (sic), `is_error == True`, and
the actual error text in `result` instead. Terminal errors the CLI raises
itself (`error_max_turns`, `error_during_execution`, ...) do put useful text
in `subtype`. Using `subtype` unconditionally when `is_error` is set
produces a self-contradictory message like "Claude session ended in error:
success" — seen live. `reviewer._result_error_text()` prefers `result` when
present, falling back to `subtype` otherwise; keep using it rather than
`message.subtype` directly.

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
- **Only run the checks relevant to what actually changed.** A README.md-only
  (or other pure prose/docs) change touches nothing `ruff`/`pytest`/`tmt
  lint` read — running them anyway is just noise. Editing a
  `skills/_fragments/*.md` fragment is *not* in that category even though
  it looks like a docs change: run `python scripts/build_skills.py` to
  regenerate the `SKILL.md` files, then `pytest` --
  `tests/unit/test_build_skills.py` fails if the committed `SKILL.md` and
  its fragments disagree. Run `pytest`/`ruff` when `src/`/`tests/*.py`
  changed, `tmt lint` when `plans/`/`tests/*/main.fmf` changed, and skip verification
  commands entirely for a docs/skill-wording-only change.
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
- **Commit independent changes separately, not bundled into one commit.**
  If a session produced several unrelated fixes/features, that's several
  commits, each reviewable and revertable on its own — don't fold them
  together just because they landed in the same conversation.
- Trailer: use `Assisted-By: <model name>` (e.g. `Assisted-By: Claude Sonnet
  5`), **not** the default `Co-Authored-By: <model> <noreply@anthropic.com>`.
  No email address. Use whichever model actually did the work — don't
  hardcode a specific model name in tooling or templates, since it will
  change over time.
- **When a commit is a fixup for something just committed in the same
  session** (a bug found in, or a change of approach to, work from a commit
  earlier in the same conversation) — ask the user whether it should be a
  new commit or a fixup for an earlier one, rather than assuming either way.
  When they want a fixup, use `git commit --fixup=<hash>` and stop there —
  do **not** run `git rebase --autosquash`, `git reset --soft` +
  recommit, a detached-HEAD checkout/amend/`rebase --onto` dance, or any
  other history rewriting on your own initiative, even non-interactive
  rewriting. The user squashes it themselves when they're ready; your job
  ends at creating the `fixup!` commit. (Previously handled a fixup for a
  non-tip commit via a manual detached-HEAD amend + `rebase --onto` — it
  worked, but the user didn't want that; `--fixup` is the only sanctioned
  tool here, tip commit or not.)
