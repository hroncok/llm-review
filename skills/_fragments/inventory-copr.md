## Step 2: Inventory the Build Artifacts

List `$WORKDIR/artifacts/` to see what was downloaded:

```bash
ls -la "$WORKDIR/artifacts"
```

You should find one `.src.rpm` and one or more binary `.rpm` files, and
(if available) log files named `<name>.<chroot>.log` (e.g.
`build.fedora-rawhide-x86_64.log`, `root.fedora-rawhide-x86_64.log`) --
`<chroot>` is the Copr chroot (distro/release/arch) this package was built
against, also found in `$WORKDIR/copr-buildinfo.txt`.

Unlike a Koji scratch build, there is no separate SRPM-generation log to
watch out for here: Copr's per-chroot `build.<chroot>.log` is always the
real `%build`/`%install`/`%check` log for that chroot. If present, check its
tail to verify tests actually ran and passed -- do not just assume success
from the presence of RPMs.

You will run rpmlint yourself in Step 3, and do license verification
manually in Step 5.
