---
title: Build and run CyberGold Backend
doc_type: developer-guide
status: active
owner: backend-maintainer
created: 2026-10-12
last_reviewed: 2026-10-12
canonical_for: Public source build and local runtime instructions
---

# Build and run this Backend source

This package contains the Python API/worker, Node SDK worker and patched SDK
sources, SQL schemas, original npm/Python locks, vendored notices and Dockerfile.
A Git checkout identifies its source with `git rev-parse HEAD`; retained source
packages record their original versions in `source-info.json`. Compact Protocol ABI inputs support historical generated
module regeneration without an old private Git checkout.

Use Docker with BuildKit and Python 3 for the wrapper. The original Dockerfile
uses digest-pinned Node 26.10.0 and Python 3.13.14, npm integrity and pip hashes.
It installs the source's SDK patch, copies Python/SQL sources, and starts the
API. Public registries are needed; private Ops, Git history, registry signing
and production credentials are unnecessary.

```sh
bash scripts/build-public-image.sh . cybergold-backend:local
docker run --rm --add-host host.docker.internal:host-gateway -p 127.0.0.1:3001:3000 --env-file env/backend-local.example.env cybergold-backend:local
```

Copy the local example and set your own chain/RPC/actual Core and optional
deployment addresses. The example's `0x...0001` is a placeholder; it does not
establish working contract flows. Database state, private provider access and
live deployment availability are separate from source availability. Existing
environment/provider/database checks and their errors are preserved.

For native installation, use Node from `.nvmrc`, `npm ci`, Python 3.13 and
`python3.13 -m venv python-candidate/.venv`, then
`python-candidate/.venv/bin/pip install --require-hashes -r python-candidate/requirements.txt`.
Export your local settings and run
`PYTHONPATH=python-candidate/src python-candidate/.venv/bin/python -m cybergold_candidate.main`.
The original SQL files and schema installation code are under
`python-candidate/schema` and `python-candidate/src/cybergold_candidate`.
For a database-backed worker, configure your own PostgreSQL/RPC settings and
use the same image with `python -m cybergold_candidate.worker_main` as command.

`node scripts/regenerate-offer-abis.mjs --check` compares compact rendered ABI
inputs with the exact original modules. It needs no Protocol Git graph. The
normal image build consumes checked-in modules and does not compile Solidity
or run ABI generators. Included tests support source modification; normal
product CI stays documented separately in the public repository.

This is source/build guidance, not a claim of an identical deployed image.
Original apt packages, builder/frontend/layer metadata and external dependency
source/availability still have separate qualification limits. No live service,
host setting, private environment or database data is changed by this package.

## Repository-owned image delivery

A successful Backend CI push on `dev` or `main` starts `publish-image.yml`
in this repository. The separate build job checks out that exact source and
builds the API/worker image without registry credentials or private Ops inputs.
The publish job loads the current-run archive, reuses the exact successful CI
run and current branch head, publishes an immutable image, and moves `desired`
last. Pull-request, scheduled and manual CI runs do not publish images.

| Source branch | Environment | Existing private GHCR package |
| --- | --- | --- |
| `dev` | Sandbox | `cybergold-backend-b2b-sandbox` |
| `main` | Mainnet | `cybergold-backend-b2b-mainnet` |

Ops continues to own deployment, private runtime configuration, health checks
and rollback. Image labels identify Backend as the OCI source and revision;
the existing Backend commit and snapshot-source labels remain available to
host tooling. Publication uses this repository's `GITHUB_TOKEN` and needs no
Ops checkout or cross-repository dispatch token.

For activation, grant this repository Write access under **Manage Actions
access** for both existing packages, keeping their visibility private. Merge
through `dev`, then promote the unchanged `dev` branch to default `main`:
GitHub only starts `workflow_run` workflows present on the default branch.
After that promotion, a fresh or rerun successful current-head push CI run
can release the matching environment. Retire the old Ops publisher only after
the new publisher is available. The former dispatch secret can then be removed.

During the `dev`-merge to default-`main` promotion interval, CI continues to
validate source but automatic image publication pauses because the former Ops
dispatch has been removed and GitHub has not registered the new workflow yet.
Running services retain their current image. Coordinate the default-branch
promotion before relying on subsequent automatic releases.
