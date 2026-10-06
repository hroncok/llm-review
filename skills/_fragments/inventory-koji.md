## Step 2: Inventory the Build Artifacts

List `$WORKDIR/artifacts/` to see what was downloaded:

```bash
ls -la "$WORKDIR/artifacts"
```

You should find one `.src.rpm` and one or more binary `.rpm` files (per arch),
and possibly log files named `<name>.<label>.log` (e.g. `build.x86_64.log`,
`root.noarch.log`) -- `<label>` identifies which Koji subtask produced that
log, and it matters:

- A `*.srpm.log` file (e.g. `build.srpm.log`) is from the SRPM-generation
  subtask (`buildSRPMFromSCM`, or `rebuildSRPM` for a build from an
  uploaded SRPM instead of a git source), which only generates the SRPM --
  it never runs `%build`/`%install`/`%check`, no matter how big or
  normal-looking it is. **Never treat a `*.srpm.log` as evidence that tests
  ran or that the build succeeded for any architecture.**
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
