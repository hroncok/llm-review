**If you cannot actually perform the review** -- e.g. the SRPM is missing,
corrupted, or fails to extract; no spec file can be found; the source tarball
referenced by the spec is missing or unreadable; or any other reason makes it
impossible to check the package against the guidelines -- stop and use the
`error` verdict (see Step 7). Do not guess, do not silently skip the checks
you couldn't perform, and do not fall back to `needs discussion`: `needs
discussion` means you *did* review the package and have a substantive,
genuinely ambiguous call to make; `error` means the review itself could not
be carried out.
