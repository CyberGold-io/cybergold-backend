---
title: Backend branch and promotion workflow
doc_type: development-guide
status: active
owner: backend-maintainer
created: 2026-10-11
last_reviewed: 2026-10-12
canonical_for: CyberGold Backend feature integration and dev-to-main promotion
---

# Backend branch and promotion workflow

## Contribution and promotion path

```text
feature/* in a contributor fork or CyberGold, created from CyberGold dev
  -> PR into CyberGold dev
  -> existing CI and authorized merge commit
  -> integrated Sandbox testing
  -> PR from CyberGold's exact dev into main
  -> authorized merge commit and the existing release path
```

The owner and `core-team`, including Ksenia, can create feature branches inside
CyberGold and merge PRs into `dev`. Anyone else may create branches in a fork
and propose a feature-to-`dev` PR. Only the owner can merge Backend `main`
promotions.

The selected rules keep `dev` and `main` long-lived and protected: PRs and
existing required CI apply to administrators as well; force pushes and deletion
are disabled. Zero approving reviews are mandatory, allowing an authorized author
to merge their own PR after CI passes. Voluntary review approval does not confer
merge permission. Human Admin access stays with the owner; trusted contributors
have Write. Write also enables broader repository capabilities, including
Actions and secret management, so it is not a dev-only permission.

Only `feature/*` may target `dev`, from this repository or a fork. Only the
canonical CyberGold repository's exact `dev` branch may target `main`. GitHub
lets a contributor select `main` in the PR form. Maintainers do not accept a
feature or fork head into `main`, including a fork branch named `dev`; they
verify the actual head and base repositories and branches before merging.
Keep unfinished changes on feature branches: a `dev` promotion
includes every integrated feature, rather than selecting one feature again.

Use GitHub's merge-commit method for feature integration and promotion. Squash
and rebase merges are disabled so the long-lived `dev` ancestry is preserved.
Hotfixes follow the same feature-to-`dev`-to-`main` route. Correct a faulty
integration with an ordinary revert PR into `dev`.

## CI and delivery

Ordinary fork PR CI uses a read-only token and receives no repository secrets.
GitHub Free native protections enforce the selected merge actors, required PRs
and existing required CI checks. Branch-policy CI uses candidate-controlled
source and provides feedback; it does not independently enforce the permitted
source/base relationship. Before accepting a PR, the authorized maintainer
verifies that relationship and reviews the proposed changes, including
workflows and policy scripts. This workflow uses maintainer checks without a
separate bot or exclusive merger service. Maintainers verify the selected
hosted protections during rollout; this document alone does not establish that
they are active.

PR jobs do not dispatch deployment. Successful admitted `dev` push CI requests
publication through the existing private Ops delivery path, followed by
automatic shared Sandbox adoption. `main` uses the established Mainnet path.
CI success, image publication and actual host adoption are separate results;
maintainers check the served version and exercise the integrated change before
promotion. The shared Sandbox contains several accepted features at once.

Public contributors can use local source fixtures and submit PRs without Ops
access or shared credentials. Maintainers handle deployment evidence and
operations; access to private Ops is not a contribution prerequisite.

## Dependency proposals and contributor entry point

Dependabot proposals target `dev`, but generated `dependabot/*` heads do not
satisfy the existing `feature/*` policy. Adopt an appropriate update onto a
feature branch from `dev`, review the exact dependency revision, and run the
normal checks. Promotion to the default `main` branch is needed before a fixed
advisory can disappear from that branch's dependency alerts.

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for fork setup and local validation.
