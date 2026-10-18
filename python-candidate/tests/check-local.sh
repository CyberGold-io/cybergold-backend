#!/usr/bin/env bash
# Local source migration comparison, not a CI/release authorization gate.
set -euo pipefail
cd "$(dirname "$0")/../.."
candidate_reference_dir=$(mktemp -d)
trap 'rm -rf -- "$candidate_reference_dir"' EXIT
node --import tsx python-candidate/tests/node-market-reference.ts > "$candidate_reference_dir/market.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-http-reference.ts > "$candidate_reference_dir/http.json"
node --import tsx python-candidate/tests/node-rpc-reference.ts > "$candidate_reference_dir/rpc.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-safe-reference.ts > "$candidate_reference_dir/safe.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-core-reference.ts > "$candidate_reference_dir/core.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-rpc-http-reference.ts > "$candidate_reference_dir/rpc-http.json"
node --import tsx python-candidate/tests/node-rpc-pacer-reference.ts > "$candidate_reference_dir/rpc-pacer.json"
node --import tsx python-candidate/tests/node-alias-reference.ts > "$candidate_reference_dir/aliases.json"
node --import tsx python-candidate/tests/node-environment-reference.ts > "$candidate_reference_dir/environment.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-runtime-reference.ts > "$candidate_reference_dir/runtime.json"
node --import tsx python-candidate/tests/node-indexer-reference.ts > "$candidate_reference_dir/indexer.json"
node --import tsx python-candidate/tests/node-adaptive-reference.ts > "$candidate_reference_dir/adaptive.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-pool-http-reference.ts > "$candidate_reference_dir/pool-http.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-safe-http-reference.ts > "$candidate_reference_dir/safe-http.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-safe-status-reference.ts > "$candidate_reference_dir/safe-status.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-faucet-reference.ts > "$candidate_reference_dir/faucet.json"
node --import tsx python-candidate/tests/node-recovery-reader-reference.ts > "$candidate_reference_dir/recovery-reader.json"
node --import tsx python-candidate/tests/node-recovery-rpc-reference.ts > "$candidate_reference_dir/recovery-rpc.json"
node --import tsx python-candidate/tests/node-recovery-http-reference.ts > "$candidate_reference_dir/recovery-http.json"
node --import tsx python-candidate/tests/node-diagnostics-reference.ts > "$candidate_reference_dir/diagnostics.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-worker-contract-reference.ts > "$candidate_reference_dir/worker-contract.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-recovery-persistence-reference.ts > "$candidate_reference_dir/recovery-persistence.json"
node --experimental-test-module-mocks --env-file=tests/fixture.env --import tsx python-candidate/tests/node-worker-http-reference.ts > "$candidate_reference_dir/worker-http.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-telemetry-reference.ts > "$candidate_reference_dir/telemetry.json"
node --import tsx python-candidate/tests/node-worker-range-reference.ts > "$candidate_reference_dir/worker-range.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-faucet-legacy-reference.ts > "$candidate_reference_dir/faucet-legacy.json"
node --experimental-test-module-mocks --env-file=tests/fixture.env --import tsx python-candidate/tests/node-alias-http-reference.ts > "$candidate_reference_dir/alias-http.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-protocol-metrics-reference.ts > "$candidate_reference_dir/protocol-metrics.json"
TZ=UTC node --experimental-test-module-mocks --import tsx python-candidate/tests/node-alias-auth-reference.ts > "$candidate_reference_dir/alias-auth.json"
node --import tsx python-candidate/tests/node-transaction-revert-reference.ts > "$candidate_reference_dir/transaction-revert.json"
node --import tsx python-candidate/tests/node-receipt-reference.ts > "$candidate_reference_dir/receipt.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-completed-state-reference.ts "$candidate_reference_dir/receipt.json" > "$candidate_reference_dir/completed-state.json"
node --import tsx python-candidate/tests/node-gateway-lease-reference.ts > "$candidate_reference_dir/gateway-lease.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-fork-recovery-reference.ts > "$candidate_reference_dir/fork-recovery.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-fork-control-reference.ts > "$candidate_reference_dir/fork-control.json"
node --env-file=tests/fixture.env --import tsx python-candidate/tests/node-safe-collector-reference.ts > "$candidate_reference_dir/safe-collector.json"
node --import tsx python-candidate/tests/node-indexer-rpc-reference.ts > "$candidate_reference_dir/indexer-rpc.json"
node --import tsx python-candidate/tests/node-finalized-multicall-reference.ts > "$candidate_reference_dir/finalized-multicall.json"
node --import tsx python-candidate/tests/node-indexer-state-reference.ts > "$candidate_reference_dir/indexer-state.json"
node --import tsx python-candidate/tests/node-indexer-recovery-reference.ts > "$candidate_reference_dir/indexer-recovery.json"
node --import tsx python-candidate/tests/node-dashboard-builder-reference.ts > "$candidate_reference_dir/dashboard-builder.json"
node --import tsx python-candidate/tests/node-indexer-event-codec-reference.ts > "$candidate_reference_dir/indexer-event-codec.json"
node --import tsx python-candidate/tests/node-worker-engine-reference.ts > "$candidate_reference_dir/worker-engine.json"
export PYTHONPATH=python-candidate/src
python-candidate/.venv/bin/python python-candidate/tests/test_route_encoding.py
python-candidate/.venv/bin/python python-candidate/tests/test_route_quote_engine.py
python-candidate/.venv/bin/python python-candidate/tests/test_route_scheduler.py
python-candidate/.venv/bin/python python-candidate/tests/test_route_work_slots.py
python-candidate/.venv/bin/python python-candidate/tests/test_sdk_worker_route_lease_lifecycle.py
python-candidate/.venv/bin/python python-candidate/tests/test_unified_route_pipeline.py
python-candidate/.venv/bin/python python-candidate/tests/test_uniswap_market.py
python-candidate/.venv/bin/python python-candidate/tests/test_market_canonical_anchor.py
python-candidate/.venv/bin/python python-candidate/tests/test_snapshot_copy.py
python-candidate/.venv/bin/python python-candidate/tests/test_cached_discovery_overlap.py
python-candidate/.venv/bin/python python-candidate/tests/test_trade_quote.py
python-candidate/.venv/bin/python python-candidate/tests/test_quote_budget.py
python-candidate/.venv/bin/python python-candidate/tests/test_budget_providers.py
python-candidate/.venv/bin/python python-candidate/tests/test_budget_timeout_diagnostics.py
python-candidate/.venv/bin/python python-candidate/tests/test_provider_quote_diagnostics.py
python-candidate/.venv/bin/python python-candidate/tests/test_issue_candidate_updates.py
python-candidate/.venv/bin/python python-candidate/tests/test_trade_diagnostics.py
python-candidate/.venv/bin/python python-candidate/tests/test_sdk_worker_lifecycle.py
python-candidate/.venv/bin/python python-candidate/tests/test_pending_sdk.py
python-candidate/.venv/bin/python python-candidate/tests/test_market_recipient_cache.py
python-candidate/.venv/bin/python python-candidate/tests/test_protocol_configuration.py
python-candidate/.venv/bin/python python-candidate/tests/test_market.py "$candidate_reference_dir/market.json"
python-candidate/.venv/bin/python python-candidate/tests/test_http.py "$candidate_reference_dir/http.json"
python-candidate/.venv/bin/python python-candidate/tests/test_cache.py
python-candidate/.venv/bin/python python-candidate/tests/test_rpc_policy.py "$candidate_reference_dir/rpc.json"
python-candidate/.venv/bin/python python-candidate/tests/test_safe_abi.py "$candidate_reference_dir/safe.json"
python-candidate/.venv/bin/python python-candidate/tests/test_core_abi.py "$candidate_reference_dir/core.json"
python-candidate/.venv/bin/python python-candidate/tests/test_rpc_transport.py
python-candidate/.venv/bin/python python-candidate/tests/test_quote_errors.py
python-candidate/.venv/bin/python python-candidate/tests/test_rpc_diagnostics.py
python-candidate/.venv/bin/python python-candidate/tests/test_rpc_error_diagnostics_http.py
python-candidate/.venv/bin/python python-candidate/tests/test_safe_http.py
python-candidate/.venv/bin/python python-candidate/tests/test_rpc_http.py "$candidate_reference_dir/rpc-http.json"
python-candidate/.venv/bin/python python-candidate/tests/test_rpc_pacer.py "$candidate_reference_dir/rpc-pacer.json"
python-candidate/.venv/bin/python python-candidate/tests/test_rpc_cancellation.py
python-candidate/.venv/bin/python python-candidate/tests/test_aliases.py "$candidate_reference_dir/aliases.json"
python-candidate/.venv/bin/python python-candidate/tests/test_environment.py "$candidate_reference_dir/environment.json"
python-candidate/.venv/bin/python python-candidate/tests/test_runtime.py "$candidate_reference_dir/runtime.json"
python-candidate/.venv/bin/python python-candidate/tests/test_dashboard_generation.py
python-candidate/.venv/bin/python python-candidate/tests/test_indexer.py "$candidate_reference_dir/indexer.json"
python-candidate/.venv/bin/python python-candidate/tests/test_adaptive.py "$candidate_reference_dir/adaptive.json"
python-candidate/.venv/bin/python python-candidate/tests/test_pool_http.py "$candidate_reference_dir/pool-http.json"
python-candidate/.venv/bin/python python-candidate/tests/test_safe_service.py "$candidate_reference_dir/safe-http.json"
python-candidate/.venv/bin/python python-candidate/tests/test_safe_status.py "$candidate_reference_dir/safe-status.json"
python-candidate/.venv/bin/python python-candidate/tests/test_faucet.py "$candidate_reference_dir/faucet.json"
python-candidate/.venv/bin/python python-candidate/tests/test_faucet_error_diagnostics_http.py
python-candidate/.venv/bin/python python-candidate/tests/test_recovery_reader.py "$candidate_reference_dir/recovery-reader.json"
python-candidate/.venv/bin/python python-candidate/tests/test_recovery_rpc.py "$candidate_reference_dir/recovery-rpc.json"
python-candidate/.venv/bin/python python-candidate/tests/test_recovery_http.py "$candidate_reference_dir/recovery-http.json"
python-candidate/.venv/bin/python python-candidate/tests/test_diagnostics.py "$candidate_reference_dir/diagnostics.json"
python-candidate/.venv/bin/python python-candidate/tests/test_worker_contract.py "$candidate_reference_dir/worker-contract.json"
python-candidate/.venv/bin/python python-candidate/tests/test_recovery_persistence.py "$candidate_reference_dir/recovery-persistence.json"
python-candidate/.venv/bin/python python-candidate/tests/test_worker_http.py "$candidate_reference_dir/worker-http.json"
python-candidate/.venv/bin/python python-candidate/tests/test_telemetry.py "$candidate_reference_dir/telemetry.json"
python-candidate/.venv/bin/python python-candidate/tests/test_worker_rpc.py "$candidate_reference_dir/worker-range.json"
python-candidate/.venv/bin/python python-candidate/tests/test_faucet_legacy.py "$candidate_reference_dir/faucet-legacy.json"
python-candidate/.venv/bin/python python-candidate/tests/test_alias_http.py "$candidate_reference_dir/alias-http.json"
python-candidate/.venv/bin/python python-candidate/tests/test_protocol_metrics.py "$candidate_reference_dir/protocol-metrics.json"
TZ=UTC python-candidate/.venv/bin/python python-candidate/tests/test_alias_authorizer.py "$candidate_reference_dir/alias-auth.json"
python-candidate/.venv/bin/python python-candidate/tests/test_receipt.py "$candidate_reference_dir/receipt.json"
python-candidate/.venv/bin/python python-candidate/tests/test_completed_state.py "$candidate_reference_dir/completed-state.json"
python-candidate/.venv/bin/python python-candidate/tests/test_gateway_lease.py "$candidate_reference_dir/gateway-lease.json"
python-candidate/.venv/bin/python python-candidate/tests/test_fork_recovery.py "$candidate_reference_dir/fork-recovery.json"
python-candidate/.venv/bin/python python-candidate/tests/test_fork_control.py "$candidate_reference_dir/fork-control.json"
python-candidate/.venv/bin/python python-candidate/tests/test_safe_collector.py "$candidate_reference_dir/safe-collector.json"
python-candidate/.venv/bin/python python-candidate/tests/test_indexer_rpc.py "$candidate_reference_dir/indexer-rpc.json"
python-candidate/.venv/bin/python python-candidate/tests/test_finalized_multicall.py "$candidate_reference_dir/finalized-multicall.json"
python-candidate/.venv/bin/python python-candidate/tests/test_indexer_state.py "$candidate_reference_dir/indexer-state.json"
python-candidate/.venv/bin/python python-candidate/tests/test_indexer_recovery.py "$candidate_reference_dir/indexer-recovery.json"
python-candidate/.venv/bin/python python-candidate/tests/test_dashboard_builder.py "$candidate_reference_dir/dashboard-builder.json"
python-candidate/.venv/bin/python python-candidate/tests/test_indexer_event_codec.py "$candidate_reference_dir/indexer-event-codec.json"
python-candidate/.venv/bin/python python-candidate/tests/test_worker_engine.py "$candidate_reference_dir/worker-engine.json"
python-candidate/.venv/bin/python python-candidate/tests/test_indexing_budget.py
for candidate_timezone in UTC Europe/Paris America/New_York; do
  TZ="$candidate_timezone" node --import tsx python-candidate/tests/node-alias-date-reference.ts > "$candidate_reference_dir/alias-dates.json"
  TZ="$candidate_timezone" python-candidate/.venv/bin/python python-candidate/tests/test_alias_dates.py "$candidate_reference_dir/alias-dates.json"
done

node --import tsx python-candidate/tests/node-protocol-facts-reference.ts > "$candidate_reference_dir/protocol-facts.json"
python-candidate/.venv/bin/python python-candidate/tests/test_protocol_facts.py "$candidate_reference_dir/protocol-facts.json"

python-candidate/.venv/bin/python python-candidate/tests/test_shared_market.py

python-candidate/.venv/bin/python python-candidate/tests/test_pool_producer.py

node --import tsx python-candidate/tests/node-basket-preview-reference.ts > "$candidate_reference_dir/basket-preview.json"
python-candidate/.venv/bin/python python-candidate/tests/test_basket_preview.py "$candidate_reference_dir/basket-preview.json"
python-candidate/.venv/bin/python python-candidate/tests/test_preview_errors.py

node --import tsx python-candidate/tests/node-token-preview-reference.ts > "$candidate_reference_dir/token-preview.json"
python-candidate/.venv/bin/python python-candidate/tests/test_token_preview.py "$candidate_reference_dir/token-preview.json"

node --import tsx python-candidate/tests/node-uniswap-quote-reference.ts > "$candidate_reference_dir/uniswap-quote.json"
python-candidate/.venv/bin/python python-candidate/tests/test_uniswap_quote.py "$candidate_reference_dir/uniswap-quote.json"

node --import tsx python-candidate/tests/node-governance-core-facts-reference.ts > "$candidate_reference_dir/governance-core-facts.json"
python-candidate/.venv/bin/python python-candidate/tests/test_governance_core_facts.py "$candidate_reference_dir/governance-core-facts.json"

node --import tsx python-candidate/tests/node-wallet-balances-reference.ts > "$candidate_reference_dir/wallet-balances.json"
python-candidate/.venv/bin/python python-candidate/tests/test_wallet_balances.py "$candidate_reference_dir/wallet-balances.json"
python-candidate/.venv/bin/python python-candidate/tests/test_token_balance.py
python-candidate/.venv/bin/python python-candidate/tests/test_liquidity_positions.py

node --import tsx python-candidate/tests/node-helpers-router-facts-reference.ts > "$candidate_reference_dir/helpers-router-facts.json"
python-candidate/.venv/bin/python python-candidate/tests/test_helpers_router_facts.py "$candidate_reference_dir/helpers-router-facts.json"

node --import tsx python-candidate/tests/node-safe-principal-reference.ts > "$candidate_reference_dir/safe-principal.json"
python-candidate/.venv/bin/python python-candidate/tests/test_safe_principal.py "$candidate_reference_dir/safe-principal.json"

node --import tsx python-candidate/tests/node-core-permit-reference.ts > "$candidate_reference_dir/core-permit.json"
python-candidate/.venv/bin/python python-candidate/tests/test_core_permit.py "$candidate_reference_dir/core-permit.json"
python-candidate/.venv/bin/python python-candidate/tests/test_token_permit.py

node --import tsx python-candidate/tests/node-permit2-context-reference.ts > "$candidate_reference_dir/permit2-context.json"
python-candidate/.venv/bin/python python-candidate/tests/test_permit2_context.py "$candidate_reference_dir/permit2-context.json"

node --import tsx python-candidate/tests/node-core-recovery-assets-reference.ts > "$candidate_reference_dir/core-recovery-assets.json"
python-candidate/.venv/bin/python python-candidate/tests/test_core_recovery_assets.py "$candidate_reference_dir/core-recovery-assets.json"

node --import tsx python-candidate/tests/node-transaction-fees-reference.ts > "$candidate_reference_dir/transaction-fees.json"
python-candidate/.venv/bin/python python-candidate/tests/test_transaction_fees.py "$candidate_reference_dir/transaction-fees.json"

node --import tsx python-candidate/tests/node-transaction-nonce-reference.ts > "$candidate_reference_dir/transaction-nonce.json"
python-candidate/.venv/bin/python python-candidate/tests/test_transaction_nonce.py "$candidate_reference_dir/transaction-nonce.json"

node --import tsx python-candidate/tests/node-transaction-receipt-reference.ts > "$candidate_reference_dir/transaction-receipt.json"
python-candidate/.venv/bin/python python-candidate/tests/test_transaction_receipt.py "$candidate_reference_dir/transaction-receipt.json"
python-candidate/.venv/bin/python python-candidate/tests/test_receipt_wait.py

node --import tsx python-candidate/tests/node-safe-transaction-reference.ts > "$candidate_reference_dir/safe-transaction.json"
python-candidate/.venv/bin/python python-candidate/tests/test_safe_transaction.py "$candidate_reference_dir/safe-transaction.json"

node --import tsx python-candidate/tests/node-governance-roles-reference.ts > "$candidate_reference_dir/governance-roles.json"
python-candidate/.venv/bin/python python-candidate/tests/test_governance_roles.py "$candidate_reference_dir/governance-roles.json"

node --import tsx python-candidate/tests/node-governance-authority-reference.ts > "$candidate_reference_dir/governance-authority.json"
python-candidate/.venv/bin/python python-candidate/tests/test_governance_authority.py "$candidate_reference_dir/governance-authority.json"

node --import tsx python-candidate/tests/node-recovery-redemption-reference.ts > "$candidate_reference_dir/recovery-redemption.json"
python-candidate/.venv/bin/python python-candidate/tests/test_recovery_redemption.py "$candidate_reference_dir/recovery-redemption.json"

node --import tsx python-candidate/tests/node-permit2-approval-gas-reference.ts > "$candidate_reference_dir/permit2-approval-gas.json"
python-candidate/.venv/bin/python python-candidate/tests/test_permit2_approval_gas.py "$candidate_reference_dir/permit2-approval-gas.json"

node --import tsx python-candidate/tests/node-safe-execution-reference.ts > "$candidate_reference_dir/safe-execution.json"
python-candidate/.venv/bin/python python-candidate/tests/test_safe_execution.py "$candidate_reference_dir/safe-execution.json"

node --import tsx python-candidate/tests/node-helpers-execution-reference.ts > "$candidate_reference_dir/helpers-execution.json"
python-candidate/.venv/bin/python python-candidate/tests/test_helpers_execution.py "$candidate_reference_dir/helpers-execution.json"

node --import tsx python-candidate/tests/node-recovery-share-precision-reference.ts > "$candidate_reference_dir/recovery-share-precision.json"
python-candidate/.venv/bin/python python-candidate/tests/test_recovery_share_precision.py "$candidate_reference_dir/recovery-share-precision.json"

python-candidate/.venv/bin/python python-candidate/tests/test_governance_target_code.py

python-candidate/.venv/bin/python python-candidate/tests/test_transaction_revert.py "$candidate_reference_dir/transaction-revert.json"
python-candidate/.venv/bin/python python-candidate/tests/test_ens_records.py
python-candidate/.venv/bin/python python-candidate/tests/test_native_balance.py

python-candidate/.venv/bin/python python-candidate/tests/test_schema_tooling.py
python-candidate/.venv/bin/python python-candidate/tests/test_pool_protocols.py
python-candidate/.venv/bin/python python-candidate/tests/test_pool_activity.py

python-candidate/.venv/bin/python python-candidate/tests/test_alias_canonical.py

python-candidate/.venv/bin/python python-candidate/tests/test_audit_remediations.py
python-candidate/.venv/bin/python python-candidate/tests/test_route_search.py
python-candidate/.venv/bin/python python-candidate/tests/test_quote_intent.py
python-candidate/.venv/bin/python python-candidate/tests/test_selected_forward_replay.py
python-candidate/.venv/bin/python python-candidate/tests/test_quote_intent_cold_seed.py
python-candidate/.venv/bin/python python-candidate/tests/test_quote_experiments.py
python-candidate/.venv/bin/python python-candidate/tests/test_quote_history.py
python-candidate/.venv/bin/python python-candidate/tests/test_shared_reads.py
python-candidate/.venv/bin/python python-candidate/tests/test_market_freshness.py
