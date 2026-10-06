## Input

You are reviewing a package proposed via the [Fedora Package Review
Process][package-review] -- a PR against a monorepo where each package lives
in its own `<name>/<name>.spec` subdirectory, built in Copr rather than Koji.
The build already prepared in the current working directory (`$WORKDIR`, i.e.
`.`) is for exactly **one** package from that PR. The following are
guaranteed to exist before you start:

[package-review]: https://forge.fedoraproject.org/packaging/package-review

- `$WORKDIR/guidelines/` -- a checkout of the Fedora Packaging Guidelines (see
  Step 1).
- `$WORKDIR/legal-docs/` -- a checkout of Fedora Legal's policy docs (see
  Step 1 and Step 5) -- covers License: field composition and license
  approval policy, which the Packaging Guidelines do *not* cover.
- `$WORKDIR/license-data/` -- a checkout of Fedora's per-license database
  (see Step 5) -- one `data/<SPDX-ID>.toml` file per license, each with the
  license's actual Fedora approval `status`.
- `$WORKDIR/artifacts/` -- the downloaded Copr build output for **one**
  chroot: the SRPM, the built RPMs, and (if available) logs named
  `<name>.<chroot>.log` (e.g. `build.fedora-rawhide-x86_64.log`) -- see
  Step 2 for what `<chroot>` means.
- `$WORKDIR/copr-buildinfo.txt` -- the Copr build ID, chroot, package name,
  and the PR source commit this was built from, for context.
- `$WORKDIR/dist-git/` -- *if* the exact PR commit could still be checked
  out, a checkout of **just this package's subdirectory** from the PR's own
  source repository (not Fedora dist-git -- this package has not been
  accepted/imported yet). **Not always present** -- absent if that exact
  commit could no longer be checked out (e.g. a force-push rewrote the PR
  branch after the build). Not an error; proceed without it, just without
  rpmlintrc discovery (see Step 3).

You do not need to download anything yourself.
