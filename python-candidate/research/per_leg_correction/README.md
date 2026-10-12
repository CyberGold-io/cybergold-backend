# Inactive per-leg correction research

This package preserves a per-leg minimum-output model and its focused tests and
read-only comparison drivers. The serving API/worker does not import this
package or construct `ComponentCorrection`. The model proposes an input amount;
an ordinary exact preview still decides whether that amount meets the original
output interval and evaluation budget. No midpoint, execution margin or
production solver policy is changed.

The package uses the current Backend libraries and existing public Basket
fixture. It was prepared against [sanitized Backend dev](https://github.com/CyberGold-io/cybergold-backend/tree/e1472f6a6d0bb6e9afe26124176d54225b5f2d99).
Project licensing follows the repository's [AGPL-3.0-only policy](../../../LICENSING.md).

From the repository root, install the existing locked contributor environment:

```bash
uv sync --project python-candidate --frozen
PYTHONPATH=python-candidate/src:python-candidate/research \
  python-candidate/.venv/bin/python -m unittest -v \
  per_leg_correction.test_quote_component_correction
PYTHONPATH=python-candidate/src:python-candidate/research \
  python-candidate/.venv/bin/python -m per_leg_correction.benchmark_component_correction \
  --output /tmp/per-leg-controlled-results.json
```

The six tests cover the initial checks, ordinary fallback, missing legs, supply
errors, controlled output bounds, and direct-token/recovery handling. The
controlled benchmark compares the shipped step, fitted model and upper-rate
model across smooth and changed-tick cases. Its discrete-output gaps and model
regressions are retained in the results; this is not evidence of a universal
latency or price improvement.

The live drivers remain research scaffolding:

- `benchmark_quote_followup` compares retained validity with a fresh search.
- `benchmark_quote_next` contains only the per-leg correction cohort. The old
  ordering experiment and obsolete error-decoder pilot are excluded.
- Both accept `--help` through `python -m per_leg_correction.<driver>` with the
  same `PYTHONPATH` as above. Supply your own `MAINNET_RPC_URL`, optional
  `RPC_AUTHORIZATION`, protocol-facts origin and local seed/sample files. Private
  Ops access and shared credentials are not required. Provider failures are
  reported by type, without publishing configured endpoints or bearer values.

Live per-leg timing is **not qualified on current source**. The current
`QuoteIntent` loop lacks the observer callback used to calibrate this model.
`quote-intent-observer.patch` preserves the narrow integration for the current
protected exact-preview loop; it has been checked for clean application but
has not been applied. Without that integration, the live driver cannot measure
the intended calibrated solver. Preserve this as unfinished research rather
than treating its outputs as production savings. Future evaluation also needs
paid route changes, integer discontinuities and the economic output tradeoff;
neither this branch nor its benchmark selects a production policy.
