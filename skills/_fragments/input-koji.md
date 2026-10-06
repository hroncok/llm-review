## Input

You are reviewing the package build already prepared in the current working
directory (`$WORKDIR`, i.e. `.`). The following are guaranteed to exist before
you start:

- `$WORKDIR/guidelines/` -- a checkout of the Fedora Packaging Guidelines (see
  Step 1).
- `$WORKDIR/legal-docs/` -- a checkout of Fedora Legal's policy docs (see
  Step 1 and Step 5) -- covers License: field composition and license
  approval policy, which the Packaging Guidelines do *not* cover.
- `$WORKDIR/license-data/` -- a checkout of Fedora's per-license database
  (see Step 5) -- one `data/<SPDX-ID>.toml` file per license, each with the
  license's actual Fedora approval `status`.
- `$WORKDIR/artifacts/` -- the downloaded Koji task output: the SRPM, the
  built RPMs, and (if available) per-subtask logs named `<name>.<label>.log`
  (e.g. `build.x86_64.log`, `build.noarch.log`) -- see Step 2 for what
  `<label>` means and why `srpm`-labeled logs are not a real build log.
- `$WORKDIR/koji-taskinfo.txt` -- the output of `koji taskinfo -v <task-id>`,
  for context (package NVR, build target, owner, etc).
- `$WORKDIR/dist-git/` -- *if* the build came from an SCM source (the normal
  case for a PR-triggered scratch build), a checkout of the dist-git repo at
  the exact commit used for this build. **Not always present** -- absent for
  a task with no SCM source, or if that exact commit could no longer be
  checked out (e.g. a fork branch was rewritten/deleted after the build).
  Neither case is an error; proceed without it, just without rpmlintrc
  discovery (see Step 3).

You do not need to download anything yourself.
