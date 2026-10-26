---
title: Dependency security policy
doc_type: security-decision
status: active
owner: security-maintainer
created: 2026-10-26
last_reviewed: 2026-10-26
canonical_for: repository dependency vulnerability admission
---

# Dependency security policy

Approved by the owner on 26 October 2026 for all maintained CyberGold repositories.
The purpose is to prevent a known, unaccepted dependency vulnerability from being
merged. Builds and functional tests do not establish that security decision.

## Merge rule

Every pull request must pass the `dependency-security` check on its proposed
commit. Scan the complete committed resolved dependency graph, including
production, development and transitive packages. Every reported severity blocks
merging unless the owner explicitly accepted that particular finding. Scanner
failures also fail the check; an unavailable scan is not a clean result.

Feature-branch pushes remain available. Maintained `dev`, `main`, and Website's
`master` require PRs and checks, including administrators, wherever GitHub's plan
supports those protections. Ops has only `main` as a maintained branch; use a
feature branch and PR into `main`. Existing product, fork, branch and release
checks remain applicable.

The current GitHub Free plan cannot enforce protection for several private
repositories. CI and this policy still apply there, but they do not physically
prevent an authorized writer from merging or pushing. Full private-repository
protection needs an appropriate paid organization plan and configured branch
rules. A checked-in workflow alone does not create that enforcement.

## What the check scans

Run it from a checkout with its submodules initialized:

```sh
python3 ci/check-dependency-security.py --report /tmp/dependency-security.json
```

Python 3.11 or newer is required. The wrapper downloads OSV-Scanner 2.7.0 from its
official release and verifies the committed SHA-256. It reads tracked lockfiles,
fully pinned requirements files, exact Python build-system pins, and committed
Git submodule identities. `ci/dependency-security-sources.json` names any lockfile
inherited from a parent component and actually used by this project (Helpers
uses Protocol’s security-tool lock). Upstream libraries’ own authoring/test
lockfiles are not CyberGold’s installed dependency graph and are not imported.
CI checks out submodules recursively to make the selected inherited inputs
available. Unversioned build declarations are listed as unresolved coverage,
not silently pinned or represented as audited. No package dependency is upgraded, application dependency
installed, or upstream manifest rewritten by this check.

All severities and scopes are retained. Uncalled or otherwise classified
unimportant vulnerabilities are included. Repository OSV ignore configurations
are not used: policy exceptions are evaluated separately and remain visible.
The JSON report lists scanned sources, package records, blocking findings and
accepted findings. It is retained as a CI artifact even when the check fails.

The scan covers the committed package inventories, not every operating-system
package in a deployed image or an unrecorded environment. Existing Dependabot,
image, Action, source and contract security checks retain their own coverage.

## Exceptions require an owner decision

`ci/dependency-security-exceptions.json` starts empty. Existing alerts are not
automatically accepted. Each accepted entry must name an exact advisory ID,
ecosystem, package and manifest path, with a reason, owner-approval reference and
review trigger. Wildcards and blanket transitive exemptions are unsupported.
The approval reference records a real owner decision; writing a reference into
JSON does not itself constitute approval. Maintainers must verify that decision
when reviewing a PR that changes this file.

For example, after actual owner acceptance only:

```json
{
  "schemaVersion": 1,
  "exceptions": [
    {
      "advisory": "GHSA-xxxx-yyyy-zzzz",
      "ecosystem": "PyPI",
      "package": "affected-package",
      "manifest": "uv.lock",
      "reason": "Document the reviewed exposure and why the risk is accepted.",
      "owner_approval": "Link to the actual owner decision.",
      "review_trigger": "Review when the maintained parent adopts the upstream fix."
    }
  ]
}
```

An exception matches that advisory's aliases, exact package and manifest only.
Another advisory or another affected manifest still blocks. Accepted findings
remain in the report and in Dependabot; do not dismiss alerts merely to make a
status green. Remove an exception when remediation makes it unnecessary and
revisit it when its recorded trigger occurs.

## Remediate through the maintained parent

A direct dependency is a component CyberGold selects and maintains. A transitive
dependency is maintained inside that component. GitHub's nearest-manifest label
does not override this maintenance boundary.

- CyberGold → Safe Transaction Service → DRF/Pillow: adopt a reviewed official
  Safe release as a unit, retaining its manifest and lock unchanged.
- Protocol → Halmos/Slither → Python libraries: update Halmos/Slither.
- Ops → Semgrep → MCP: update Semgrep.
- CyberGold-owned Next.js, sharp, Fastify or SDK declarations: update those
  parents; their ordinary resolved dependency changes may follow.

Do not independently pin, override or patch a transitive dependency under this
policy. If the latest suitable parent still contains an affected child, keep
tracing it upstream. Transitive status, lack of a fix, or an unavailable parent
release does not automatically grant risk acceptance or make a check pass.
Existing Safe release qualification and paired OpenZeppelin release rules remain
in force; the security workflow is a CyberGold-owned wrapper change.

## Continuous discovery and rollout

The same check runs on PRs, maintained-branch pushes, daily and manually. New
advisories can therefore make unchanged code fail later. Existing default-branch
Dependabot monitors remain inventory and notification controls; their raw open
alert count is not the candidate-commit merge decision.

Rollout consists of landing the workflow and requiring its exact check name on
each maintained branch. An implementation PR with blocking findings is not a
security pass: remediate or obtain specific owner decisions before merging it.
A green implementation test suite does not accept its live findings.

Canonical cross-repository policy and rollout notes are maintained in the
[Ops security documentation](https://github.com/CyberGold-io/cybergold-ops/blob/main/docs/security/dependency-security-policy.md).
