# CyberGold Backend Agent Instructions

The workspace `AGENTS.md` also applies to this repository.

## Specifications and owner authorization

- [`SPECS.md`](SPECS.md) describes implemented behavior only. The implementation,
  that specification and its linked current-process diagrams must agree.
- **Every change to `SPECS.md` requires explicit authorization from the owner.**
  A behavior change that changes the specification is a coordinated code and
  specification change; obtain explicit owner authorization for that change
  before changing either. A workplan, analysis, recommendation or general
  invitation to improve performance does not supply this authorization.
- Once authorized, update the implementation, `SPECS.md` and affected diagram
  dependencies together. Do not document proposed behavior as implemented or
  leave changed behavior undocumented.
- Keep improvement proposals, performance targets not implemented as contracts,
  experiments and implementation workplans in `cybergold-ops/docs`, using its
  existing workplan organization. Link to them instead of copying proposals
  into `SPECS.md` or its current-process diagrams.
- Analysis and measurements do not themselves authorize implementation changes.
