# llm-review

AI-powered Fedora package review for Fedora CI.

Given a Koji scratch-build task (as produced by Fedora CI for a package pull
request), this tool downloads the build's SRPM/RPMs, and runs the
[`fedora-package-review`](skills/fedora-package-review/SKILL.md) Claude Code
skill against them headlessly through the
[Claude Agent SDK](https://pypi.org/project/claude-agent-sdk/), producing a
structured review report and a Fedora-CI-style result.

The skill in this repo is a copy of the interactive
`~/.claude/skills/fedora-package-review` skill, adapted to run unattended
against a Koji build instead of a COPR/Bugzilla review request -- your local
skill is untouched.

## How it works

1. `llm_review.koji` resolves a Koji task ID (bare, or from a
   `taskinfo?taskID=...` URL, or `$KOJI_TASK_ID`) and downloads its SRPM/RPMs/logs.
2. `llm_review.workspace` prepares an ephemeral working directory: a shallow
   clone of the [Fedora Packaging
   Guidelines](https://forge.fedoraproject.org/packaging/guidelines.git), the
   adapted skill, and the downloaded artifacts.
3. `llm_review.reviewer` runs the skill via the Claude Agent SDK against that
   workspace, and reads back the report the skill is instructed to write.
4. `llm_review.results` writes the result the way Fedora CI results are
   normally presented: a tmt [custom
   result](https://tmt.readthedocs.io/en/stable/spec/results.html)
   (`results.yaml`) plus the report and logs, into `$TMT_TEST_DATA` (or
   `--output-dir` outside of tmt). There is no posting to Bugzilla, a PR, or
   any other API -- Fedora CI's own dashboard renders whatever lands here,
   the same way it does for `rpmlint`/`fedora-review`/etc.

## Configuration

Backend selection is environment-variable driven, mirroring the same
variables Claude Code itself uses (see `src/llm_review/config.py`):

- `LLM_REVIEW_BACKEND`: `vertex` (default) or `bedrock`.
- `LLM_REVIEW_MODEL`: optional model override.
- **Vertex** (today's default): `ANTHROPIC_VERTEX_PROJECT_ID`, `CLOUD_ML_REGION`,
  plus standard `gcloud` Application Default Credentials.
- **Bedrock** (once available): `AWS_REGION`, plus the standard AWS credential
  chain.

Other environment variables:

- `KOJI_TASK_ID` / `KOJI_PROFILE`: input task and koji CLI profile
  (`shared-tests`' convention).
- `LLM_REVIEW_SKILL_DIR`: override the skill directory location. Needed when
  running from a non-editable pip install, since the skill lives outside the
  Python package (see `tests/llm-review/main.fmf` for how the tmt test sets
  this).

## Usage

```console
$ export ANTHROPIC_VERTEX_PROJECT_ID=... CLOUD_ML_REGION=...
$ python -m llm_review 123456789
```

or with a taskinfo URL:

```console
$ python -m llm_review https://koji.fedoraproject.org/koji/taskinfo?taskID=123456789
```

This writes `review.md` + `results.yaml` to `./results` (or `$TMT_TEST_DATA`
if set), and exits `0` for `approve`/`needs discussion`, `1` for
`needs fixes`.

## tmt plan

`plans/llm-review/main.fmf` + `tests/llm-review/main.fmf` wrap this as a tmt
plan, structured like the existing
[`packit/tmt-plans`](https://github.com/packit/tmt-plans) plans (e.g.
`fedora-review`), so it can later be referenced from `shared-tests` the same
way via `plan.import` -- that wiring is not part of this repo.

Run it locally with:

```console
$ tmt run -a provision -h local plan --name /plans/llm-review -e KOJI_TASK_ID=123456789
```

## Development

```console
$ pip install -e '.[test]'
$ pytest
```

Unit tests cover pure logic only (Koji ID/URL parsing, backend config,
verdict-to-result mapping) -- no network or LLM calls.
