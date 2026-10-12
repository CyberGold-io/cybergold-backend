# Library source and build controls

The project is AGPL-3.0-only. Third-party components keep their existing licenses,
copyrights and notices. The library sources below supplement the project's
source archive or Git checkout; they do not change the project's lockfiles.

The adjacent `dependency-source-index.json` identifies each source download by
package/version and SHA-256. Source downloads and this index are release assets
under the `dependency-source-2026-10-12` tag in this repository. The complete
producer workspaces keep their source files, dependency locks, build scripts
and notices. They also include ordinary public upstream documentation/tests.

The project Dockerfile/build wrapper and `BUILDING.md` describe installing the
project with its locked dependencies. Rebuilding a library from preferred
source is a separate choice when modifying that library. None of the steps
below require private Ops access, deployment credentials or database contents.

## App libraries

These source assets are listed in the App repository index.

For React/ReactDOM 19.3.0, extract `react-ed4d487b6927.tar.gz` and use its original
`package.json`, `yarn.lock`, `scripts/rollup` and contributor build instructions.
The immutable producer commit is recorded in the index.

For Next 16.3.8, extract `next-16.3.8-tag-source.tar.gz`. This is the complete
release workspace, including `packages/next/src`, native compiler sources,
`packages/next/taskfile.js`, root package/Cargo/pnpm locks and build controls.
Use Node >= 20.9.0 and pnpm 10.33.0 as declared by the producer. Its ordinary
development instructions are `contributing/core/developing.md`; the source
build uses `pnpm install`, `pnpm swc-build-native --release` and `pnpm build-all`.
These producer commands can install/build tools and need network access.

`next-16.3.8-published-sources.tar.gz` additionally preserves the exact authored
UTF-8 `sourcesContent` from the locked npm artifact. `source-map-index.json`
maps each hash-named file to its original source/map path and records preserved
package notices. This supplements the versioned producer tree without guessing
unpublished build revisions. Source-content comparisons passed; a package or
native compiler rebuild was not performed.

## Backend libraries

These source assets are listed in the Backend repository index.

For Universal Router SDK 5.15.0, extract
`universal-router-sdk-5.15.0-source.tar.gz`. Its exact producer Git commit is
17d70b1b1068fc1b5ce79a89fb5901e562a22e79. The editable TypeScript is in
`sdks/universal-router-sdk/src`; all 54 published source-map references resolve
there. Node >= 18 and Bun 1.3.10 are declared in the original controls. From the
workspace, `bun install --frozen-lockfile` followed by
`bun run g:build --filter=@uniswap/universal-router-sdk...` builds the SDK and
its workspace dependencies using the original TypeScript configurations.
The other exact locked SDK source versions use
`uniswap-sdk-core-bc086008a533.tar.gz`. Source versions/grants are in the index.
The SDK declares MIT in its package metadata; producer notices remain intact.

For Psycopg Binary 3.3.6, extract `psycopg-3.3.6-tag-source.tar.gz`. The upstream
`tools/ci/copy_to_binary.py` transforms `psycopg_c` into `psycopg_binary` without
changing its LGPL-3.0-only grant. Run `python3 tools/ci/copy_to_binary.py` once
in a newly extracted producer tree. The separately supplied
`psycopg-binary-3.3.6-generated-preferred-source.tar.gz` contains that generated
editable Cython/native source, its build backend, metadata and license.
Build requirements are in its `pyproject.toml` (setuptools 83.0.0 and Cython >= 3.1.1).

The locked Backend image uses CPython 3.13 on Linux amd64. Upstream
`.github/workflows/packages-bin.yml`, `tools/ci/wheel_linux_before_all.sh`,
`tools/ci/build_libpq.sh` and `tools/ci/strip_wheel.sh` describe its wheel build
and repair. The producer selects manylinux2014 x86_64, libpq 18.6, OpenSSL 3.5.8
and OpenLDAP 2.6.14; these three complete source archives are included.
`build_libpq.sh` includes the source adjustments for disabled default GSS
encryption negotiation and `/var/run/postgresql` as the default socket path.
Preserve these adjustments when rebuilding the bundled libpq.

For a source installation in a suitable Linux development environment, provide
the usual libpq/OpenSSL/GSSAPI/LDAP development libraries and `pg_config`, then
use `python3.13 -m pip install ./psycopg_binary` from the generated source tree.
The upstream wheel recipe uses cibuildwheel 4.2.0, its manylinux builder and
auditwheel to bundle/repair these libraries. It includes normal platform build
dependencies; their versions are not promoted to new project admission checks.

## Scope

The finite selected library sources, controls and license notices are available
in these downloads. Existing project locks and vendored patches identify other
dependencies and their producer artifacts. This index is not a claim that every
transitive dependency was rebuilt or independently audited. Ordinary build
errors remain ordinary errors. Original compiler/container metadata and public
frontend build-time values were not all retained, so these instructions do not
claim a byte-identical historical npm package, wheel or deployed image.
