---
title: No new dependency vulnerabilities
doc_type: security-decision
status: active
owner: security-maintainer
created: 2026-10-26
last_reviewed: 2026-10-26
canonical_for: repository dependency vulnerability admission
---

# No new dependency vulnerabilities

Approved by the owner on 26 October 2026 for the four public repositories:
App, Backend, Protocol and Helpers. The private repositories retain their own
agreed policies. This replaces the public repositories' zero-unaccepted-findings
rule with a comparison against the PR target.

## Merge decision

A PR must not introduce an unaccepted dependency vulnerability absent from its
target branch. Existing findings may remain or be resolved. Every reported
severity, including unknown severity, is included across production, development
and transitive package inventories. Scan/configuration errors fail the check.

The required check is still named `dependency-security`. Maintained `dev` and
`main` retain PR requirements, administrator enforcement and their existing
product, branch, secret and release controls. Feature pushes remain available.

The check scans the target commit and proposed merge in one OSV-Scanner
invocation, using the same current observations rather than an old stored alert
report. Identical package versions share their advisory observations across both
trees. A newly disclosed advisory affecting an unchanged package is therefore
retained, not attributed to an unrelated PR.

The comparison matches advisory identities and aliases, package/ecosystem and
the affected manifest/component. A version change alone does not reopen the same
advisory if both versions are affected. Adding the finding to another component
does introduce it. A previously resolved advisory that returns is new again.
Totals alone never decide: closing one finding and introducing another still
fails even if the total is unchanged or lower.

Reports list introduced, retained and resolved finding instances, all
current findings, explicit acceptances and unresolved coverage. Retained
findings are not declared safe or risk-accepted. They remain an open remediation
backlog without requiring exception records merely to preserve existing state.

## Events and local use

On PRs, CI checks out the target commit separately from GitHub's proposed merge.
On maintained-branch pushes it compares the pre-push revision with the new
revision, retaining the same publication check. Daily/manual runs report the
full current backlog without requiring it to be empty. Scanner errors remain
visible failures; an unavailable scan is not a clean result.

```sh
# Both checkouts must include their selected submodules.
python3 ci/check-dependency-regressions.py --base-root /path/to/target-checkout --report /tmp/dependency-security.json

# Full inventory for manual backlog review; no comparison/merge decision.
python3 ci/check-dependency-regressions.py --report /tmp/dependency-inventory.json
```

Comparison exit codes are 0 for no new unaccepted findings, 1 for introduced
unaccepted findings, and 2 for scan/configuration failure. A full advisory
inventory returns 0 with its findings retained, or 2 on failure. The underlying
`check-dependency-security.py` remains available as an absolute diagnostic scan;
its exit code is not the public-repository merge policy.

Both trees use the same scanner. Historical inherited-inventory selections are
respected; a newly used inherited component is not grandfathered merely because
its files were already vendored. Audited rollout targets that predate scanner
configuration use the current selection for components present in the old tree.
A component absent from the target contributes no target findings. No fixed baseline of
advisory IDs, blanket ignores, severity exemptions or periodic renewal gates
are introduced.

## Inventory and explicit owner decisions

The Python 3.11+ wrapper checksum-verifies official OSV-Scanner 2.7.0. It scans
committed resolved lockfiles, fully pinned requirements, exact Python build pins
and supplemental Git submodule identities. Selected inherited lockfiles must be
used by the project; unrelated upstream authoring/test locks are excluded.
Unversioned build declarations remain explicitly unresolved. Scans do not install
application dependencies or replace image, Action, source, contract or OS checks.

`ci/dependency-security-exceptions.json` records actual owner decisions for exact
advisory/alias, ecosystem, package and manifest, with a reason, approval reference
and review trigger. Selectors match literally. Such findings stay visible and
are not described as resolved. Filling JSON is not owner approval. No exception
is created automatically for a retained or introduced finding.

The existing Dependabot monitors remain discovery controls. Their raw alert
counts are not the candidate merge decision. Additional npm/GitHub dependency
reviews are advisory inventory reports; the common comparison is the dependency
admission check.

## Remediation follows the maintained parent

A direct dependency is a component CyberGold selects and maintains. A transitive
dependency is maintained inside it; GitHub's nearest-manifest label does not
override this boundary.

- CyberGold → Safe Transaction Service → DRF/Pillow: qualify an official Safe
  release as a unit, preserving its upstream manifest and lock.
- Protocol → Halmos/Slither → Python libraries: update Halmos/Slither.
- Ops → Semgrep → MCP: update Semgrep.
- CyberGold-owned application declarations: update those parents and qualify
  their ordinary resolved dependency changes.

Do not independently pin, override or patch a child. If the latest suitable
parent still contains the child, retain the report and track a fixing parent
release. Parent currency alone is not remediation. Existing Safe and paired
OpenZeppelin qualification rules remain in force.
