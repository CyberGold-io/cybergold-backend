# Bunyan runtime packaging

Published Bunyan 1.8.15 files and MIT license are preserved. This package is
used only by the isolated AlphaRouter stdout/blackhole logger. Its optional
`mv` rotating-file dependency is omitted; no rotating-file logger is offered
by this integration. Development dependencies/scripts are not installed.
No Bunyan runtime JavaScript is changed. `upstream-package.json` preserves the
original manifest; `VENDOR.json` records the published integrity and file hashes.
This removes the unused mv/rimraf/legacy-glob graph rather than substituting an
incompatible minimatch API. Current ordinary logging behavior is retained.
