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

### Linking to guideline/legal-docs pages in the report

Whenever you cite or quote a specific guideline or Fedora Legal page in the
report (e.g. "Per `Naming.adoc`..." or a quoted sentence), link to its
public page instead of just naming the local file -- the local path means
nothing to someone reading the report. The URL is fully deterministic from
the local path, so build it yourself; do not fetch/crawl anything to get it:

- `$WORKDIR/guidelines/guidelines/modules/ROOT/pages/<Name>.adoc` ->
  `https://docs.fedoraproject.org/en-US/packaging-guidelines/<Name>/`
- `$WORKDIR/legal-docs/modules/ROOT/pages/<name>.adoc` ->
  `https://docs.fedoraproject.org/en-US/legal/<name>/`
- Exception: `index.adoc` in either checkout is that component's start
  page, so it takes over the component's own root URL instead of getting
  an `/index/` segment -- link to `https://docs.fedoraproject.org/en-US/packaging-guidelines/`
  or `https://docs.fedoraproject.org/en-US/legal/` (no page name at all).
- Keep `<Name>`/`<name>` byte-for-byte identical to the `.adoc` filename
  (minus the extension) -- these are case-sensitive.

Example: `Per [Naming](https://docs.fedoraproject.org/en-US/packaging-guidelines/Naming/)
...` instead of `Per \`Naming.adoc\`...`.
