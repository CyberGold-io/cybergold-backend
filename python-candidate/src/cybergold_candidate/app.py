"""Product API with configured providers and fixed operations."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import uuid

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .cache import MarketFeed
from .market import resolve_market, response_headers
from .rpc_http import RpcHttp
from .rpc_diagnostics import RpcDiagnosticsMiddleware
from .source_offer import install_source_offer


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def create_app(client=None, now=timestamp, safe_activity=None, core_activity=None,
               rpc_url=None, rpc_authorization=None, rpc_timeout_seconds=15, liquidity_positions=None,
               dashboard=None, on_shutdown=None, pool_cache=None, safe_service_url=None,
               safe_timeout_seconds=15, safe_status=None, faucet_settings=None, faucet_timeout_seconds=20, faucet_service=None,
               recovery=None,diagnostic_logger=None,release=None,aliases=None,protocol_facts=None,protocol_configuration=None,
               shared_market=None,pool_producer=None,helpers_activity=None,pool_activity=None,basket_preview=None,basket_max=None,governance_core_facts=None,
               wallet_balances=None,helpers_router_facts=None,governance_safe_principal=None,token_preview=None,uniswap_quote=None,core_permit=None,permit2_context=None,core_recovery_assets=None,transaction_fees=None,transaction_nonce=None,transaction_receipt=None,safe_transaction=None,governance_roles=None,governance_authority=None,recovery_redemption=None,permit2_approval_gas=None,safe_execution=None,helpers_execution=None,receipt_wait=None,recovery_share_precision=None,governance_target_code=None,native_balance=None,ens_records=None,transaction_revert=None,route_search=None,quote_intent=None,token_balance=None,token_observations=None,token_approval_gas=None,market_quotes=None,uniswap_registry=None,trade_quotes=None,universal_quotes=None,economic_quotes=None,transaction_preparation=None):
    from .telemetry import Metrics, TelemetryMiddleware
    metrics=Metrics()
    owned_client = client is None
    # HTTPX does not retry by default. Follow provider redirects like fetch().
    client = client or httpx.AsyncClient(timeout=10, follow_redirects=True)

    async def fetch_json(url):
        response = await client.get(url)
        response.raise_for_status()
        return response.status_code, response.json()

    if shared_market:
        shared_market.metrics = metrics

    def resolver(feed, ttl):
        async def resolve(previous):
            async def supplier(last):
                return await resolve_market(feed, last, fetch_json, now)
            return (await shared_market.resolve(feed, previous, supplier, ttl)
                    if shared_market else await supplier(previous))
        return resolve

    feeds = {
        feed: MarketFeed(resolver(feed, ttl), ttl,metrics=metrics,feed=feed)
        for feed, ttl in (('gold', 1800), ('fx', 300))
    }
    rpc = RpcHttp(client, rpc_url, rpc_authorization, rpc_timeout_seconds,metrics=metrics)
    from .safe_service import SafeService, handle_safe_service
    safe_service=SafeService(client,safe_service_url,safe_timeout_seconds)
    from .faucet import Faucet, handle_faucet
    faucet=(Faucet(client,**(faucet_settings or {}),timeout_seconds=faucet_timeout_seconds)
            if faucet_service is None else faucet_service)

    @asynccontextmanager
    async def lifespan(_app):
        try:
            if protocol_configuration and hasattr(protocol_configuration, 'start'):
                await protocol_configuration.start()
            yield
        finally:
            if faucet_service is not None:
                await faucet_service.close()
            if protocol_configuration:
                await protocol_configuration.close()
            for feed in feeds.values():
                await feed.close()
            if shared_market:
                await shared_market.close()
            rpc.close()
            if owned_client:
                await client.aclose()
            if on_shutdown:
                await on_shutdown()
            if recovery:
                await recovery.close()
            if protocol_facts:
                await protocol_facts.close()
            if pool_producer:
                await pool_producer.close()
            if market_quotes:
                await market_quotes.close()
            if uniswap_registry:
                await uniswap_registry.close()
            if basket_preview:
                await basket_preview.close()
            if basket_max:
                await basket_max.close()
            if token_preview:
                await token_preview.close()
            if trade_quotes:
                await trade_quotes.close()
            if quote_intent and hasattr(quote_intent, 'close'):
                await quote_intent.close()
            if route_search:
                await route_search.close()
            if uniswap_quote:
                await uniswap_quote.close()
            if governance_core_facts:
                await governance_core_facts.close()
            if wallet_balances:
                await wallet_balances.close()
            if token_balance:
                await token_balance.close()
            if liquidity_positions:
                await liquidity_positions.close()
            if helpers_router_facts:
                await helpers_router_facts.close()
            if transaction_fees:
                await transaction_fees.close()
            if transaction_nonce:
                await transaction_nonce.close()
            if governance_roles:
                await governance_roles.close()
            if governance_authority:
                await governance_authority.close()
            if recovery_redemption:
                await recovery_redemption.close()
            if permit2_approval_gas:
                await permit2_approval_gas.close()
            if safe_transaction:
                await safe_transaction.close()
            if safe_execution:
                await safe_execution.close()
            if helpers_execution:
                await helpers_execution.close()
            if transaction_receipt:
                await transaction_receipt.close()
            if receipt_wait:
                await receipt_wait.close()
            if recovery_share_precision:
                await recovery_share_precision.close()
            if core_recovery_assets:
                await core_recovery_assets.close()
            if permit2_context:
                await permit2_context.close()
            if token_observations:
                await token_observations.close()
            if token_approval_gas:
                await token_approval_gas.close()
            if core_permit:
                await core_permit.close()
            if transaction_revert:
                await transaction_revert.close()
            if ens_records:
                await ens_records.close()
            if native_balance:
                await native_balance.close()
            if governance_target_code:
                await governance_target_code.close()
            if governance_safe_principal:
                await governance_safe_principal.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.metrics=metrics
    app.add_middleware(TelemetryMiddleware,metrics=metrics,component='api',release=release)
    app.add_middleware(RpcDiagnosticsMiddleware)
    install_source_offer(app, release)

    @app.api_route('/metrics',methods=['GET','HEAD'])
    async def metrics_route():
        return Response(metrics.render(),headers={'Content-Type':'text/plain; version=0.0.4; charset=utf-8','Cache-Control':'no-store'})

    @app.exception_handler(Exception)
    async def unhandled(_request, _error):
        # Retained backend unhandled errors expose no internal text.
        return Response(status_code=500)

    async def market(feed):
        result = await feeds[feed].get()
        headers = response_headers(feed, result['isFresh'], result['payload'], now())
        reason = getattr(result, 'failure_code', None)
        if reason:
            headers['x-cybergold-market-fallback'] = reason
        return JSONResponse(result['payload'], headers=headers)

    @app.api_route('/api/gold', methods=['GET', 'HEAD'])
    async def gold():
        return await market('gold')

    @app.api_route('/api/fx', methods=['GET', 'HEAD'])
    async def fx():
        return await market('fx')

    @app.api_route('/api/protocol/facts', methods=['GET', 'HEAD'])
    async def protocol_facts_route(request: Request):
        from .protocol_facts import handle_protocol_facts
        return await handle_protocol_facts(request, protocol_facts)

    @app.api_route('/api/protocol/config', methods=['GET', 'HEAD'])
    async def protocol_configuration_route():
        from .protocol_config import handle_protocol_configuration
        return await handle_protocol_configuration(protocol_configuration)

    @app.api_route('/api/governance/core-facts', methods=['GET', 'HEAD'])
    async def governance_core_facts_route(request: Request):
        from .protocol_facts import handle_protocol_facts
        return await handle_protocol_facts(request, governance_core_facts, 'governance-core-facts',
                                           'Core governance facts are temporarily unavailable.')

    @app.api_route('/api/transaction/revert', methods=['GET', 'HEAD'])
    async def transaction_revert_route(request: Request):
        from .transaction_revert import handle_transaction_revert
        return await handle_transaction_revert(request, transaction_revert)

    @app.api_route('/api/account/ens-name', methods=['GET', 'HEAD'])
    async def ens_name_route(request: Request):
        from .ens_records import handle_ens
        return await handle_ens(request, ens_records, 'name')

    @app.api_route('/api/account/ens-avatar-record', methods=['GET', 'HEAD'])
    async def ens_avatar_route(request: Request):
        from .ens_records import handle_ens
        return await handle_ens(request, ens_records, 'avatar')

    @app.api_route('/api/account/native-balance', methods=['GET', 'HEAD'])
    async def native_balance_route(request: Request):
        from .wallet_balances import handle_native_balance
        return await handle_native_balance(request, native_balance)

    @app.api_route('/api/account/wallet-balances', methods=['GET', 'HEAD'])
    async def wallet_balances_route(request: Request):
        from .wallet_balances import handle_wallet_balances
        return await handle_wallet_balances(request, wallet_balances)

    @app.api_route('/api/account/token-balance', methods=['GET', 'HEAD'])
    async def token_balance_route(request: Request):
        from .wallet_balances import handle_token_balance
        return await handle_token_balance(request, token_balance)

    @app.api_route('/api/account/liquidity-positions', methods=['GET', 'HEAD'])
    async def liquidity_positions_route(request: Request):
        from .liquidity_positions import handle_liquidity_positions
        return await handle_liquidity_positions(request, liquidity_positions)

    @app.api_route('/api/governance/roles', methods=['GET', 'HEAD'])
    async def governance_roles_route(request: Request):
        from .governance_roles import handle_governance_roles
        return await handle_governance_roles(request, governance_roles)

    @app.api_route('/api/governance/authority', methods=['GET', 'HEAD'])
    async def governance_authority_route(request: Request):
        from .governance_authority import handle_governance_authority
        return await handle_governance_authority(request, governance_authority)

    @app.api_route('/api/governance/safe-nonce', methods=['GET', 'HEAD'])
    async def safe_nonce_route(request: Request):
        from .safe_transaction import handle_safe_transaction
        return await handle_safe_transaction(request, safe_transaction)

    @app.post('/api/governance/safe-transaction-hash')
    async def safe_hash_route(request: Request):
        from .safe_transaction import handle_safe_transaction
        return await handle_safe_transaction(request, safe_transaction, hash_request=True)

    @app.post('/api/transaction/recovery-redemption')
    async def recovery_redemption_route(request: Request):
        from .recovery_redemption import handle_recovery_redemption
        return await handle_recovery_redemption(request, recovery_redemption)

    @app.post('/api/transaction/permit2-approval-gas')
    async def permit2_approval_gas_route(request: Request):
        from .permit2_approval_gas import handle_permit2_approval_gas
        return await handle_permit2_approval_gas(request, permit2_approval_gas)

    @app.post('/api/governance/safe-execution')
    async def safe_execution_route(request: Request):
        from .safe_execution import handle_safe_execution
        return await handle_safe_execution(request, safe_execution)

    @app.post('/api/transaction/helpers-execution')
    async def helpers_execution_route(request: Request):
        from .helpers_execution import handle_helpers_execution
        return await handle_helpers_execution(request, helpers_execution)

    @app.api_route('/api/transaction/receipt', methods=['GET', 'HEAD'])
    async def transaction_receipt_route(request: Request):
        from .transaction_receipt import handle_transaction_receipt
        return await handle_transaction_receipt(request, transaction_receipt)

    @app.api_route('/api/transaction/wait/head', methods=['GET', 'HEAD'])
    async def receipt_wait_head(request: Request):
        from .receipt_wait import handle_receipt_wait
        return await handle_receipt_wait(request, receipt_wait, 'head')

    @app.api_route('/api/transaction/wait/transaction', methods=['GET', 'HEAD'])
    async def receipt_wait_transaction(request: Request):
        from .receipt_wait import handle_receipt_wait
        return await handle_receipt_wait(request, receipt_wait, 'transaction')

    @app.api_route('/api/transaction/wait/receipt', methods=['GET', 'HEAD'])
    async def receipt_wait_receipt(request: Request):
        from .receipt_wait import handle_receipt_wait
        return await handle_receipt_wait(request, receipt_wait, 'receipt')

    @app.api_route('/api/transaction/wait/block', methods=['GET', 'HEAD'])
    async def receipt_wait_block(request: Request):
        from .receipt_wait import handle_receipt_wait
        return await handle_receipt_wait(request, receipt_wait, 'block')

    @app.api_route('/api/account/transaction-nonce', methods=['GET', 'HEAD'])
    async def transaction_nonce_route(request: Request):
        from .transaction_nonce import handle_transaction_nonce
        return await handle_transaction_nonce(request, transaction_nonce)

    @app.api_route('/api/transaction/fees', methods=['GET', 'HEAD'])
    async def transaction_fees_route(request: Request):
        from .protocol_facts import handle_protocol_facts
        return await handle_protocol_facts(request, transaction_fees, 'transaction-fees',
                                           'Transaction fee observations are temporarily unavailable.')

    @app.api_route('/api/protocol/recovery-share-precision', methods=['GET', 'HEAD'])
    async def recovery_share_precision_route(request: Request):
        from .recovery_share_precision import handle_recovery_share_precision
        return await handle_recovery_share_precision(request, recovery_share_precision)

    @app.api_route('/api/protocol/recovery-assets', methods=['GET', 'HEAD'])
    async def core_recovery_assets_route(request: Request):
        from .protocol_facts import handle_protocol_facts
        return await handle_protocol_facts(request, core_recovery_assets, 'core-recovery-assets',
                                           'Core recovery assets are temporarily unavailable.')

    @app.post('/api/account/permit2')
    async def permit2_context_route(request: Request):
        from .permit2_context import handle_permit2_context
        return await handle_permit2_context(request, permit2_context)

    @app.api_route('/api/tokens/metadata', methods=['GET', 'HEAD'])
    async def token_metadata_route(request: Request):
        from .token_permit import handle_token_metadata
        return await handle_token_metadata(request, token_observations)

    @app.api_route('/api/account/token-permit', methods=['GET', 'HEAD'])
    async def token_permit_route(request: Request):
        from .token_permit import handle_token_permit
        return await handle_token_permit(request, token_observations)

    @app.post('/api/transaction/token-approval-gas')
    async def token_approval_gas_route(request: Request):
        from .token_approval_gas import handle_token_approval_gas
        return await handle_token_approval_gas(request, token_approval_gas)

    @app.api_route('/api/account/core-permit', methods=['GET', 'HEAD'])
    async def core_permit_route(request: Request):
        from .core_permit import handle_core_permit
        return await handle_core_permit(request, core_permit)

    @app.api_route('/api/governance/helpers-facts', methods=['GET', 'HEAD'])
    async def helpers_router_facts_route(request: Request):
        from .helpers_router_facts import handle_helpers_router_facts
        return await handle_helpers_router_facts(request, helpers_router_facts)

    @app.api_route('/api/governance/safe-principal', methods=['GET', 'HEAD'])
    async def safe_principal_route(request: Request):
        from .governance_safe_principal import handle_safe_principal
        return await handle_safe_principal(request, governance_safe_principal)

    @app.api_route('/api/governance/target-code', methods=['GET', 'HEAD'])
    async def target_code_route(request: Request):
        from .governance_target_code import handle_governance_target_code
        return await handle_governance_target_code(request, governance_target_code)

    @app.post('/api/rpc')
    async def rpc_route(request: Request):
        return await rpc.handle(request)

    @app.post('/api/quotes/basket-preview')
    async def basket_preview_route(request: Request):
        from .basket_preview import handle_basket_preview
        return await handle_basket_preview(request, basket_preview)

    @app.post('/api/quotes/basket-max')
    async def basket_max_route(request: Request):
        from .basket_max import handle_basket_max
        return await handle_basket_max(request, basket_max)

    @app.post('/api/quotes/token-preview')
    async def token_preview_route(request: Request):
        from .token_preview import handle_token_preview
        return await handle_token_preview(request, token_preview)

    @app.post('/api/quotes/uniswap')
    async def uniswap_quote_route(request: Request):
        from .uniswap_quote import handle_uniswap_quote
        return await handle_uniswap_quote(request, uniswap_quote)

    @app.post('/api/quotes/intent/stream')
    async def quote_intent_route(request: Request):
        from .quote_intent import handle_quote_intent
        return await handle_quote_intent(request, quote_intent)

    @app.post('/api/quotes/market')
    async def market_quote_route(request: Request):
        from .market_swap import handle_market_quote
        return await handle_market_quote(request, market_quotes)

    @app.post('/api/economic-quotes')
    async def economic_quote_route(request: Request):
        from .economic_quotes import handle_economic_quote
        return await handle_economic_quote(request, economic_quotes)

    @app.post('/api/tx-preparations')
    async def tx_preparation_route(request: Request):
        from .economic_quotes import handle_tx_preparation
        return await handle_tx_preparation(request, transaction_preparation)

    @app.post('/api/economic-estimates')
    async def economic_estimate_route(request: Request):
        from .economic_quotes import handle_economic_estimate
        return await handle_economic_estimate(request, trade_quotes)

    @app.post('/api/quotes/universal-exact-input')
    async def universal_quote_route(request: Request):
        from .universal_quote import handle_universal_quote
        return await handle_universal_quote(request, universal_quotes)

    @app.post('/api/quotes/trade/stream')
    async def trade_quote_stream(request: Request):
        from .trade_quote import handle_trade_quote
        return await handle_trade_quote(request, trade_quotes)

    @app.post('/api/quotes/trade/model')
    async def trade_quote_model(request: Request):
        from .trade_quote import handle_trade_quote
        return await handle_trade_quote(request, trade_quotes, model=True)

    @app.post('/api/quotes/market/stream')
    async def market_quote_stream(request: Request):
        from .market_swap import handle_market_quote
        return await handle_market_quote(request, market_quotes, stream=True)

    @app.post('/api/quotes/market/model')
    async def market_model_route(request: Request):
        from .market_swap import MODEL_REQUEST
        from .basket_preview import handle_basket_preview
        from types import SimpleNamespace
        service = SimpleNamespace(get=market_quotes.get_model) if market_quotes else None
        return await handle_basket_preview(request, service, MODEL_REQUEST, 'market-model',
            'Invalid market model input.', 'Market models are temporarily unavailable.')

    @app.post('/api/quotes/routes/stream')
    async def route_stream_http(request: Request):
        from .route_search import handle_route_stream
        return await handle_route_stream(request, route_search)

    @app.post('/api/quotes/routes')
    async def route_search_route(request: Request):
        from .route_search import handle_route_search
        return await handle_route_search(request, route_search)

    @app.post('/api/quote-pool-cache')
    async def pool_cache_route(request: Request):
        from .pool_cache import handle_pool_cache
        return await handle_pool_cache(request,pool_cache)

    @app.post('/api/pools/snapshot')
    async def pool_snapshot_route(request: Request):
        from .pool_producer import handle_pool_snapshot
        return await handle_pool_snapshot(request,pool_producer)

    @app.get('/api/pools/catalog')
    async def pool_catalog_route(request: Request):
        from .pool_producer import handle_pool_catalog
        return await handle_pool_catalog(request,pool_producer)

    @app.post('/api/safe')
    async def safe_service_route(request: Request):
        return await handle_safe_service(request,safe_service)

    @app.post('/api/safe/events')
    async def safe_status_route(request: Request):
        from .safe_status import handle_safe_status
        return await handle_safe_status(request,safe_status)

    @app.post('/api/faucet')
    async def faucet_route(request: Request):
        return await handle_faucet(request,faucet)

    @app.api_route('/api/recovery/shares',methods=['GET','HEAD'])
    async def recovery_route(request: Request):
        from .recovery_http import handle_recovery
        return await handle_recovery(request,recovery)

    @app.post('/api/diagnostics')
    async def diagnostics_route(request: Request):
        from .diagnostics import handle_diagnostics
        return await handle_diagnostics(request,diagnostic_logger,release)

    @app.post('/api/governance/owner-aliases')
    async def aliases_route(request:Request):
        from .alias_http import handle_aliases
        return await handle_aliases(request,aliases)

    async def activity(read, context, message):
        try:
            payload = await read() if read else {'enabled': False, 'events': []}
            return JSONResponse(payload, headers={'Cache-Control': 'no-store'})
        except Exception:
            correlation = str(uuid.uuid4())
            logging.getLogger('cybergold.candidate').error(json.dumps({
                'correlationId': correlation, 'context': context, 'errorClassification': 'unexpected-error'}))
            return JSONResponse({'error': message,
                                 'correlationId': correlation}, status_code=500,
                                headers={'Cache-Control': 'no-store'})

    @app.api_route('/api/activity/safe', methods=['GET', 'HEAD'])
    async def safe():
        return await activity(safe_activity, 'safe-activity', 'Safe activity is temporarily unavailable.')

    @app.api_route('/api/activity/core', methods=['GET', 'HEAD'])
    async def core():
        return await activity(core_activity, 'core-activity', 'Protocol activity is temporarily unavailable.')

    @app.api_route('/api/activity/helpers', methods=['GET', 'HEAD'])
    async def helpers():
        return await activity(helpers_activity, 'helpers-activity', 'Helpers activity is temporarily unavailable.')

    @app.api_route('/api/activity/pools', methods=['GET', 'HEAD'])
    async def pools_activity(request: Request):
        from .pool_activity import activity_filters
        try:
            filters = activity_filters(request.query_params)
        except ValueError as error:
            return JSONResponse({'error': str(error)}, status_code=400, headers={'Cache-Control': 'no-store'})
        async def read():
            return await pool_activity(filters) if pool_activity else {'enabled': False, 'events': [], 'pools': []}
        return await activity(read, 'pool-activity', 'Pool activity is temporarily unavailable.')

    @app.api_route('/api/dashboard/onchain-summary', methods=['GET', 'HEAD'])
    async def dashboard_route():
        from .retained_reads import disabled_dashboard
        try:
            payload = await dashboard() if dashboard else disabled_dashboard()
            return JSONResponse(payload, headers={'Cache-Control': 'public, max-age=10, stale-while-revalidate=20'})
        except Exception:
            correlation = str(uuid.uuid4())
            logging.getLogger('cybergold.candidate').error(json.dumps({
                'correlationId': correlation, 'context': 'dashboard-onchain-summary', 'errorClassification': 'unexpected-error'}))
            return JSONResponse({'error': 'Failed to load on-chain dashboard summary.', 'correlationId': correlation},
                                status_code=500, headers={'Cache-Control': 'no-store'})

    return app
