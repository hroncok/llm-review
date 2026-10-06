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

### Evidence

<the raw data collected in Steps 2-5, so a human reader can check your
claims without re-running anything themselves -- see "What goes in
Evidence" below>

### PASS

<numbered list of checks that passed, with brief justification -- when a
claim relies on something in Evidence, say which part (e.g. "see rpmlint
output" or "see python3-foo's Provides below")>

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

### What goes in Evidence

The point of this section is that a human reading the report should never
have to take a PASS/ISSUES claim on faith or re-run a command themselves to
check it -- the data you based the claim on should already be right there.
Use `####` subheadings, one per RPM/topic as needed, e.g.:

- **RPM metadata** -- for each binary RPM, the `rpm -qp --provides`,
  `--requires`, `-l`, and `--qf '%{LICENSE}\n'` output from Step 3.
- **rpmlint output** -- the full raw output from Step 3, including the
  invocation used (plain, or with a discovered `.rpmlintrc`/`rpmlint.toml`).
- **Build log verification** -- the tail of the build log you checked in
  Step 2, showing tests actually running/passing (name the log you checked;
  note if none was available).
- **License findings** -- from Step 5: which `LICENSE*`/`COPYING*`/`NOTICE*`
  files were found and where; for bundled/vendored code, the extracted
  license comments/metadata (not just your conclusion about them); and the
  `status` looked up for each distinct SPDX license in `license-data`.

Don't paste megabytes of irrelevant output (e.g. a huge passing test log in
full) -- excerpt the parts that actually back a claim, but always include
enough that the reader can see the real command output, not your paraphrase
of it. If a claim in PASS/ISSUES isn't backed by anything in Evidence, that's
a sign that either the check wasn't actually done or a citation was missed.

## Key Principles

1. **Read the guidelines first.** They are the source of truth and they change. Always read the current `.adoc` files.
2. **Verify licenses manually.** Bundled/minified code needs manual inspection.
3. **Distinguish MUST from SHOULD.** Only MUST violations block approval.
4. **Explain false positives.** When rpmlint flags something that is actually correct, explain why.
5. **Check build logs for real test execution.** Verify tests ran and passed using the real build log identified in Step 2 (see its own guidance for what counts as "real" for this input type), not just that the build succeeded.
6. **Always write the report to `$REVIEW_OUTPUT_PATH`.** This is a non-interactive run; nothing you say outside that file is recoverable by the caller.
7. **Use `error`, not `needs discussion`, when you can't review at all.** `needs discussion` implies you completed the review and have a genuine judgment call to flag; `error` means the review itself couldn't be carried out.
8. **Never judge `License:` field composition from general reasoning.** Whether an SPDX expression's `AND`/`OR` structure or a repeated license clause is correct is governed by `legal-docs/license-field.adoc`, not the Packaging Guidelines and not what "looks redundant" -- read that document before flagging anything about the `License:` field.
9. **Show your work.** A PASS/ISSUES claim like "Provides/requires look correct for extras" is not verifiable by itself -- the `### Evidence` section must contain the actual command output (rpm queries, rpmlint, build log excerpts, license findings) it's based on, so a human reviewer can check your reasoning without re-running anything.
