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
- `$WORKDIR/artifacts/` -- the downloaded Koji task output: the SRPM, the built
  RPMs, and (if available) `build.log`/`root.log`/`task.log`.
- `$WORKDIR/koji-taskinfo.txt` -- the output of `koji taskinfo -v <task-id>`,
  for context (package NVR, build target, owner, etc).

You do not need to download anything yourself, and there is no Bugzilla or
COPR involved -- do not attempt to use the `copr` or `bugzilla` CLIs.

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

Do not rely on memorized rules. The guidelines change -- always read the
current files.

## Step 2: Inventory the Build Artifacts

List `$WORKDIR/artifacts/` to see what was downloaded:

```bash
ls -la "$WORKDIR/artifacts"
```

You should find one `.src.rpm` and one or more binary `.rpm` files (per arch),
and possibly `.log` files. If build/root logs are present, check the tail of
`build.log` to verify tests actually ran and passed -- do not just assume
success from the presence of RPMs.

There is no `review.txt`, `rpmlint.txt`, or `licensecheck.txt` pre-generated
here (those are COPR fedora-review-service artifacts and don't exist for a
plain Koji scratch build) -- you will generate the rpmlint equivalent yourself
in Step 3, and do license verification manually in Step 5.

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
to get the spec file):

```bash
rpmlint "$WORKDIR/artifacts/"*.spec "$WORKDIR/artifacts/"*.rpm
```

Treat this output the same way the interactive skill treats `rpmlint.txt`:
explain every warning/error, and note which ones are false positives.

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

This is the most error-prone area, and there is no automated `licensecheck.txt`
to lean on here -- do this manually.

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
3. **Check upstream**: if third-party license documentation in the source tree seems incomplete, check the upstream repository's LICENSE file directly.

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

### SUMMARY

Blockers: <count>
Should-fix: <count>
Minor: <count>

### VERDICT

<approve / needs fixes / needs discussion / error>
```

The `### SUMMARY` section must contain exactly those three lines, in that
order, with the count of each category you listed under `### ISSUES` (use
`0` if there were none of that category -- never omit a line). The caller
parses these lines programmatically instead of trying to re-count your
`### ISSUES` list itself, so the numbers must accurately match what you
listed above -- don't include a line here for anything you didn't actually
list as a numbered issue (e.g. don't count a sentence like "no blockers were
found").

The `### VERDICT` line must contain *only* the bare word `approve`,
`needs fixes`, `needs discussion`, or `error` -- no bold/markdown formatting,
no trailing period, no additional commentary on that line. The caller
parses this line programmatically to decide the CI result; put any
elaboration in the PASS/ISSUES sections instead.

Use `error` when the review could not actually be performed (see "If you
cannot actually perform the review" above) -- in that case, the ### PASS,
### ISSUES, and ### SUMMARY sections should explain what's missing/broken
instead of listing guideline checks, since none could be run (### SUMMARY
should be all zeros in that case).

## Key Principles

1. **Read the guidelines first.** They are the source of truth and they change. Always read the current `.adoc` files.
2. **Verify licenses manually.** There is no automated licensecheck output here; bundled/minified code needs manual inspection.
3. **Distinguish MUST from SHOULD.** Only MUST violations block approval.
4. **Explain false positives.** When rpmlint flags something that is actually correct, explain why.
5. **Check build logs.** Verify tests ran and passed, not just that the build succeeded.
6. **Always write the report to `$REVIEW_OUTPUT_PATH`.** This is a non-interactive run; nothing you say outside that file is recoverable by the caller.
7. **Use `error`, not `needs discussion`, when you can't review at all.** `needs discussion` implies you completed the review and have a genuine judgment call to flag; `error` means the review itself couldn't be carried out.
8. **Make `### SUMMARY` counts exact.** The caller trusts these numbers instead of re-parsing `### ISSUES` -- they must match the numbered list exactly, with no line omitted even when its count is `0`.
