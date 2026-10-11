# Published Uniswap ABI packages

The SDKs import JSON artifacts from `@uniswap/swap-router-contracts@1.3.1`,
`@uniswap/v3-periphery@1.4.4` and `@uniswap/v3-staker@1.0.0`. Their npm runtime
manifests also install Solidity development toolchains that the snapshot worker
does not use. Local npm file overrides retain all published files while removing
only `dependencies`, `devDependencies` and `scripts` from those manifests.

Each directory records the original registry tarball and SHA-512 integrity in
`UPSTREAM.json`, and the original manifest content in `upstream-package.json`.
The latter preserves JSON content, not original manifest formatting. An
independent comparison against the recorded tarballs verified every published
file except the intentionally changed manifest byte for byte: 51 files for
swap-router-contracts, 90 for v3-periphery and 13 for v3-staker. Retain upstream
licences and sources with the artifacts.

No swap mathematics is copied or modified here. Mathematics SDK dependencies
stay pinned in the root lockfile. Production packaging must copy `vendor`
beside `node_modules` because npm creates relative links to these directories.
The root Dockerfile follows that arrangement. Refresh these files from the
recorded upstream package when upgrading, repeat the file comparison and run
the SDK/reference tests and existing dependency audit.
