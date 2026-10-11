## Change

Describe the problem, resulting behavior and documentation impact.

## Branch path

Choose the applicable path:

- [ ] `feature/*` from CyberGold `dev`, in CyberGold or a contributor fork, targeting CyberGold `dev`.
- [ ] Promotion from CyberGold's exact `dev` branch into its `main`.

Use a merge commit. Feature/fork heads cannot merge into `main`. Only authorized
maintainers merge: owner/core-team into `dev`; owner into Backend `main`.
Zero mandatory approving reviews allows authorized authors to merge their own
PRs after the existing required checks pass.

## Validation

List the commands and results relevant to the change. State any unavailable
browser, wallet, archive-fork or live evidence explicitly.

For ABI, environment, wallet/signing or security changes, describe the affected
interfaces and evidence so maintainers can review their impact.

## Integration and release

A PR runs checks without deploying. After an accepted `dev` merge, the existing
App/Backend delivery path updates the shared Sandbox; maintainers verify the
served version and test the integrated change before promoting `dev` to `main`.

Preserve applicable third-party notices; see [CONTRIBUTING.md](../CONTRIBUTING.md).
