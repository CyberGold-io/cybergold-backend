---
title: Contributing to CyberGold Backend
doc_type: contributor-guide
status: active
owner: backend-maintainer
created: 2026-10-11
last_reviewed: 2026-10-11
canonical_for: CyberGold Backend public contributor setup and pull-request path
---

# Contributing to CyberGold Backend

Anyone may fork this repository and propose a change. Public contributors keep
feature branches in their own forks; Write access lets trusted team members
create feature branches inside CyberGold. Neither public visibility nor opening
a PR gives someone permission to merge it.

## Start from upstream dev

Fork `CyberGold-io/cybergold-backend` on GitHub, then clone your fork and add the
canonical repository as `upstream`:

```bash
git clone https://github.com/YOUR-GITHUB-USERNAME/cybergold-backend.git
cd cybergold-backend
git remote add upstream https://github.com/CyberGold-io/cybergold-backend.git
git fetch upstream
git switch -c feature/my-change upstream/dev
```

Replace the example username and `my-change` slug with your own values. `origin`
points to your fork and `upstream` to CyberGold. Trusted contributors working
inside CyberGold can instead create the feature branch from `origin/dev`.
Keep changes focused and unfinished work on the feature branch.

## Validate locally

Use Node.js 26.10.0 and npm for the existing TypeScript contract and comparison
checks:

```bash
npm ci
npm run ci-check
```

The serving API/worker is Python. For Python changes, install Python 3.13 and
uv, then use the checked-in frozen environment and local comparison suite:

```bash
uv sync --project python-candidate --frozen
bash python-candidate/tests/check-local.sh
```

The [Python runtime guide](python-candidate/README.md) describes focused and
native container/DB rehearsals. Docker is needed for those native rehearsals;
they use disposable local services and fixtures. State which relevant checks
you ran and which were unavailable. Do not use production credentials or
private Ops configuration to run contributor checks. The root [README](README.md)
and `.env.example` describe self-managed runtime configuration.

## Propose and integrate

1. Push the feature branch to your fork (or the CyberGold repository if you
   have Write access): `git push -u origin feature/my-change`.
2. Open a PR with **base repository `CyberGold-io/cybergold-backend` and base branch
   `dev`**. Describe the change, its documentation impact and validation results.
3. Existing PR CI checks the candidate. An authorized maintainer accepts it
   with GitHub's merge-commit method after the required checks pass. Public
   contributors cannot merge their own or other contributors' PRs.
4. Maintainers test integrated product changes in the shared Sandbox. A PR
   itself does not publish or deploy. The Sandbox contains all accepted `dev`
   changes, rather than a separate environment for each PR.
5. Release promotion is a PR from CyberGold's own exact `dev` branch into
   `main`. Contributors do not open feature-to-`main` or fork-to-`main` PRs.

The owner and `core-team` can merge into `dev`. Only the owner can merge
Backend `main` promotions. The selected rules for both branches require PRs
and the existing CI checks, with zero mandatory approving reviews. Authorized authors
can merge their own valid PRs after CI passes; review comments and voluntary
approvals remain useful. Direct pushes, force pushes and deletion are outside
the protected-branch workflow. Human Admin access stays with the owner.

Write permission has broader GitHub capabilities than merging `dev`; the
selected actor restrictions apply specifically to the protected branches.
The [branch workflow](docs/development/branch-workflow.md) explains promotion
and the source/delivery boundary. Maintainers verify live GitHub protections
when installing this prepared public policy; documentation alone does not
assert that those settings are active.

## Licensing

Contributions to AGPL-covered project code are offered under **AGPL-3.0-only**.
Preserve existing MIT, other explicit grants, and third-party attribution and
license notices. See [licensing scope](LICENSING.md). Do not include private
credentials or private operational configuration in a contribution.
