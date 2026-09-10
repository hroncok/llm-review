---
name: fedora-package-review
description: Review a Fedora package build against the Fedora Packaging Guidelines. Reads guidelines from a local checkout, inspects downloaded SRPM/RPM artifacts, verifies licenses (including bundled/minified code), and produces a structured review report written to $REVIEW_OUTPUT_PATH.
---

# Fedora Package Review (CI variant)

Review a package build for Fedora against the packaging guidelines. This is the
unattended, CI variant of the review skill: there is no human present to answer
questions, so every step here must be self-contained.

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

## Step 1: Read the Guidelines

The guideline AsciiDoc files are already checked out at:

```
$WORKDIR/guidelines/guidelines/modules/ROOT/pages/*.adoc
```

Always read the relevant guidelines BEFORE starting the review. Determine
which guideline files to read based on the package type:
- Always read: `Naming.adoc`, `LicensingGuidelines.adoc`, `ReviewGuidelines.adoc`
- For Python packages: `Python.adoc`
- For other languages: the corresponding `<Language>.adoc` file
- As needed: `SourceURL.adoc`, `Versioning.adoc`, `Conflicts.adoc`, `index.adoc`, etc.

**Also always read** `$WORKDIR/legal-docs/modules/ROOT/pages/license-field.adoc`
(how to compose the `License:` field -- AND/OR expressions, when a license
belongs in it at all) and `$WORKDIR/legal-docs/modules/ROOT/pages/allowed-licenses.adoc`
(the license-approval policy). These are Fedora Legal's rules, not the
Packaging Committee's, and the Packaging Guidelines above do not cover this
ground -- do not reason about `License:` field correctness from the
packaging guidelines alone.

Do not rely on memorized rules. The guidelines change -- always read the
current files.

## Step 2: Inventory the Build Artifacts

List `$WORKDIR/artifacts/` to see what was downloaded:

```bash
ls -la "$WORKDIR/artifacts"
```

You should find one `.src.rpm` and one or more binary `.rpm` files (per arch),
and possibly log files named `<name>.<label>.log` (e.g. `build.x86_64.log`,
`root.noarch.log`) -- `<label>` identifies which Koji subtask produced that
log, and it matters:

- A `*.srpm.log` file (e.g. `build.srpm.log`) is from the `buildSRPMFromSCM`
  subtask, which only generates the SRPM -- it never runs
  `%build`/`%install`/`%check`, no matter how big or normal-looking it is.
  **Never treat a `*.srpm.log` as evidence that tests ran or that the build
  succeeded for any architecture.**
- Every other label (`x86_64`, `noarch`, `aarch64`, ...) is a real
  `buildArch` subtask for that target -- **these** are the logs to check
  for `%check` output. If build/root logs are present for a target, check
  the tail of its `build.<label>.log` to verify tests actually ran and
  passed -- do not just assume success from the presence of RPMs.
- A `noarch` package's single `buildArch` subtask can land on a builder
  host of any architecture -- that host arch is irrelevant; the label
  (`noarch`) is what matters, and there's exactly one such log regardless
  of how many RPMs get built from it.

You will run rpmlint yourself in Step 3, and do license verification
manually in Step 5.

**If you cannot actually perform the review** -- e.g. the SRPM is missing,
corrupted, or fails to extract; no spec file can be found; the source tarball
referenced by the spec is missing or unreadable; or any other reason makes it
impossible to check the package against the guidelines -- stop and use the
`error` verdict (see Step 7). Do not guess, do not silently skip the checks
you couldn't perform, and do not fall back to `needs discussion`: `needs
discussion` means you *did* review the package and have a substantive,
genuinely ambiguous call to make; `error` means the review itself could not
be carried out.

## Step 3: Inspect RPMs and Run rpmlint

```bash
rpm -qp --provides <RPM>
rpm -qp --requires <RPM>
rpm -qp -l <RPM>
rpm -qp --qf '%{LICENSE}\n' <RPM>
```

Run `rpmlint` directly against the spec file and all RPMs (see Step 4 for how
to get the spec file). If `$WORKDIR/dist-git/` exists (see Input), first
check whether it has an `*.rpmlintrc` or `rpmlint.toml`:

```bash
ls "$WORKDIR/dist-git/"*.rpmlintrc "$WORKDIR/dist-git/rpmlint.toml" 2>/dev/null
```

If a config was found, run rpmlint from *within* `dist-git/` and pass it
explicitly -- running rpmlint from that directory does **not** make it
auto-discover the config on its own (rpmlint only auto-loads a same-name
rpmlintrc when linting exactly one file, from that one file's own
directory; here you're linting multiple files that live in `artifacts/`,
a different directory entirely):

```bash
(cd "$WORKDIR/dist-git" && rpmlint -r ./NAME.rpmlintrc "$WORKDIR/artifacts/"*.spec "$WORKDIR/artifacts/"*.rpm)
# or, for rpmlint.toml:
(cd "$WORKDIR/dist-git" && rpmlint -c ./rpmlint.toml "$WORKDIR/artifacts/"*.spec "$WORKDIR/artifacts/"*.rpm)
```

Otherwise (no `dist-git/`, or no config file in it), run it plainly:

```bash
rpmlint "$WORKDIR/artifacts/"*.spec "$WORKDIR/artifacts/"*.rpm
```

Explain every warning/error, and note which ones are false positives. If a
project's own `.rpmlintrc` suppresses a warning, don't re-flag it as an
issue -- that's the maintainer's deliberate, checked-in call.

## Step 4: Extract and Inspect Sources

The SRPM contains the spec file and the source tarball(s)/patches. Extract it:

```bash
mkdir -p "$WORKDIR/extracted" "$WORKDIR/src"
rpm2cpio "$WORKDIR/artifacts/"*.src.rpm | cpio -idmv -D "$WORKDIR/extracted"
cp "$WORKDIR/extracted/"*.spec "$WORKDIR/artifacts/"  # if not already there
tar xf "$WORKDIR/extracted/<source-tarball>" -C "$WORKDIR/src"
```

Then inspect license files, bundled code, and embedded metadata.

## Step 5: License Verification

This is the most error-prone area -- do this manually.

1. **Inspect bundled/vendored code manually**:
   - Check all `LICENSE*`, `COPYING*`, `NOTICE*` files in the source tree.
   - For minified JavaScript bundles (common in Python packages with JS):
     - Extract license **comments** from the minified file:
       ```python
       python3 -c "
       import re
       with open('bundled.js') as f: data = f.read()
       for c in re.findall(r'/\*[^*]*\*+(?:[^/*][^*]*\*+)*/', data):
           if any(w in c.lower() for w in ['license', 'copyright', 'permission']):
               print(c[:500]); print('---')
       "
       ```
     - Check embedded **package metadata** (package.json-like objects with `name:` and `license:` fields):
       ```python
       python3 -c "
       import re
       with open('bundled.js') as f: data = f.read()
       for m in re.finditer(r'name:\"([^\"]+)\"[^}]{0,500}?license:\"([^\"]+)\"', data):
           print(f'{m.group(1)}: {m.group(2)}')
       "
       ```
     - **Warning**: keyword searches (grep for `BSD`, `GPL`, etc.) in minified JS produce many false positives from SPDX validation data modules (like `spdx-license-ids`). These are data strings, not licenses of bundled code. Focus on comment blocks and package metadata instead.
   - For bundled Python code: check source file headers and associated LICENSE files.
2. **Verify the `License:` field** covers ALL licenses found -- the main project AND all bundled dependencies.
3. **Verify the `License:` field's SPDX expression is composed correctly**
   per `$WORKDIR/legal-docs/modules/ROOT/pages/license-field.adoc` --
   e.g. whether multiple licenses should be joined with `AND`/`OR`, and
   whether a license already implied elsewhere in the expression needs its
   own separate clause. Don't call an expression "redundant" or "wrong"
   based on general reasoning alone -- check what this specific document
   says about composing expressions with repeated/overlapping licenses.
4. **Look up each distinct license found** in
   `$WORKDIR/license-data/data/<SPDX-ID>.toml` (e.g. `data/MIT.toml`,
   `data/Apache-2.0.toml`) for its actual Fedora `status` (`allowed`,
   `not-allowed`, etc.) -- this is the definitive source, not memorized
   knowledge of which licenses Fedora permits.
5. **Check upstream**: if third-party license documentation in the source tree seems incomplete, check the upstream repository's LICENSE file directly.

## Step 6: Review Against Guidelines

Read the spec file and all collected data (rpmlint output, RPM queries, build
logs) and check against the guideline `.adoc` files read in Step 1.

- Check every MUST and SHOULD item from the relevant guideline documents.
- Verify tests actually ran and passed (check the build log tail, not just
  build status).
- Explain any rpmlint errors or warnings.

### Known false positives

- **"Directories without known owners: /usr/lib/pythonX.Y, /usr/lib/pythonX.Y/site-packages"**: Owned by `python3`, not a problem.

## Step 7: Produce the Review Report

Write the report using this template to `$REVIEW_OUTPUT_PATH` (in addition to
showing it in your response) -- this is the only reliable way the caller has
of retrieving your result, so do not skip this:

```
## Package Review: <name> <version>-<release>

### Spec file

<show the spec file>

### PASS

<numbered list of checks that passed, with brief justification>

### ISSUES

<numbered list of problems, each categorized as:>
- **Blocker**: MUST-level guideline violations
- **Should-fix**: SHOULD-level items not followed
- **Minor**: Cosmetic or informational

Use exactly one of those three bold labels per item, with nothing else
inside the bold markers (not `**Minor / informational**` or
`**Minor / pre-existing**`) -- put any qualifier *after* the label instead,
e.g. `**Minor** (pre-existing): ...`. The caller counts these labels
programmatically by scanning this list -- don't separately summarize or
total them anywhere else in the report.

### VERDICT

<approve / needs fixes / needs discussion / error>
```

The `### VERDICT` line must contain *only* the bare word `approve`,
`needs fixes`, `needs discussion`, or `error` -- no bold/markdown formatting,
no trailing period, no additional commentary on that line. The caller
parses this line programmatically to decide the CI result; put any
elaboration in the PASS/ISSUES sections instead.

Use `error` when the review could not actually be performed (see "If you
cannot actually perform the review" above) -- in that case, the ### PASS
and ### ISSUES sections should explain what's missing/broken instead of
listing guideline checks, since none could be run.

## Key Principles

1. **Read the guidelines first.** They are the source of truth and they change. Always read the current `.adoc` files.
2. **Verify licenses manually.** Bundled/minified code needs manual inspection.
3. **Distinguish MUST from SHOULD.** Only MUST violations block approval.
4. **Explain false positives.** When rpmlint flags something that is actually correct, explain why.
5. **Check build logs -- but not the `*.srpm.log` one.** Verify tests ran and passed using a real `buildArch` log (`build.<label>.log` where `<label>` isn't `srpm`), not just that the build succeeded.
6. **Always write the report to `$REVIEW_OUTPUT_PATH`.** This is a non-interactive run; nothing you say outside that file is recoverable by the caller.
7. **Use `error`, not `needs discussion`, when you can't review at all.** `needs discussion` implies you completed the review and have a genuine judgment call to flag; `error` means the review itself couldn't be carried out.
8. **Never judge `License:` field composition from general reasoning.** Whether an SPDX expression's `AND`/`OR` structure or a repeated license clause is correct is governed by `legal-docs/license-field.adoc`, not the Packaging Guidelines and not what "looks redundant" -- read that document before flagging anything about the `License:` field.
