---
title: Backend licensing
doc_type: reference
status: active
owner: backend-maintainer
created: 2026-10-11
last_reviewed: 2026-10-11
canonical_for: CyberGold Backend project-license scope and preserved third-party grants
---

# Backend licensing

CyberGold-authored project code in this repository is offered by its respective
copyright holders under **GNU Affero General Public License version 3 only**
(`AGPL-3.0-only`), except where an existing file or component explicitly states
another license. The full license text is in [LICENSE](LICENSE). This declaration
is the project license notice; copyright remains with the respective holders.

The project declaration does not withdraw previously granted MIT,
`AGPL-3.0-or-later`, or other permissions. Files and components with explicit
existing notices retain those grants. Do not remove their copyright,
attribution, warranty or license notices when modifying or distributing them.

npm, Python and other third-party dependencies retain their own licenses.
The Uniswap ABI packages in `vendor/uniswap-abi-packages/` retain their original
license and attribution files. Preserve
upstream notices for copied, vendored or distributed dependency code; the npm
project metadata does not claim those dependencies were relicensed.

## Contributions and source availability

Contributions to AGPL-covered CyberGold code are offered under the same
`AGPL-3.0-only` terms. Changes to a file or component with another explicit
existing license retain that license. Identify any third-party code and keep
its original notices. No copyright transfer is implied by opening a PR.

AGPL permits copying, modification, redistribution and commercial use subject
to its terms. Those permissions grant no authority to merge changes into the
CyberGold repository; merge rights are governed by the
[branch workflow](docs/development/branch-workflow.md).

For a modified version used over a network, AGPL section 13 requires offering
its users the corresponding source of that version. Corresponding source also
includes the build/install/run material required by section 1. Operators should
provide a clear source link to the version they actually deploy, with the
required build inputs available. A link to a newer branch alone does not prove
availability of an older deployed version's source. Publishing this notice does
not itself verify source availability for any currently deployed version.

Independent hosting and administration tooling is not automatically covered
merely because it runs the service. Necessary corresponding-source material
must nevertheless be available; private credentials and unrelated operational
data are not substituted for reproducible public build/run instructions.
