"""Existing settings wired to the candidate's implemented HTTP/read domains."""
import re
import os

from .app import create_app
from .core_activity import get_core_activity
from .helpers_activity import get_helpers_activity
from .pool_activity import get_pool_activity
from .database import Database
from .environment import load_environment
from .retained_reads import dashboard_snapshot, disabled_dashboard
from .safe_activity import get_safe_activity
from .authoritative_pool_cache import AuthoritativePoolCache
from .pool_producer import PoolProducer
from .safe_status import SafeStatus
from .recovery_http import RecoveryLoader
from .aliases import AliasService
from .protocol_facts import ProtocolFacts
from .governance_core_facts import GovernanceCoreFacts
from .transaction_revert import TransactionRevert
from .ens_records import EnsRecords
from .wallet_balances import WalletBalances, NativeBalance, TokenBalance
from .liquidity_positions import LiquidityPositions
from .transaction_fees import TransactionFees
from .transaction_nonce import TransactionNonce
from .transaction_receipt import TransactionReceipt
from .receipt_wait import ReceiptWait
from .safe_transaction import SafeTransaction
from .governance_roles import GovernanceRoles
from .governance_authority import GovernanceAuthority
from .recovery_redemption import RecoveryRedemption
from .permit2_approval_gas import Permit2ApprovalGas
from .safe_execution import SafeExecution
from .helpers_execution import HelpersExecution
from .core_recovery_assets import CoreRecoveryAssets
from .recovery_share_precision import RecoverySharePrecision
from .core_permit import CorePermit
from .token_permit import TokenObservations
from .token_approval_gas import TokenApprovalGas
from .permit2_context import Permit2Context
from .helpers_router_facts import HelpersRouterFacts
from .protocol_config import ProtocolConfiguration
from .governance_safe_principal import GovernanceSafePrincipal
from .governance_target_code import GovernanceTargetCode
from .shared_market import SharedMarketCache
from .basket_preview import BasketPreview
from .basket_max import BasketMax
from .token_preview import TokenPreview
from .uniswap_quote import UniswapQuote
from .route_search import RouteSearch, RouteSearchRpc
from .quote_intent import QuoteIntent
from .quote_cache import BasketMath, IntentSharing, VerifiedGrossSeed
from .quote_history import QuoteHistory
from .quote_correction import delayed_local_step
from .uniswap_state import PoolRegistry, UniswapStore
from .market_swap import MarketQuotes, DailyRecipientCache
from .trade_quote import TradeQuotes
from .universal_quote import UniversalQuotes
from .shared_reads import SharedReads
from .sandbox_funding import SandboxFunding


def safe_history_profile(settings):
    raw = (settings.SAFE_EVENT_INDEXER_SAFE_ADDRESSES or settings.SAFE_EVENT_INDEXER_SAFE_ADDRESS
           or settings.NEXT_PUBLIC_GOVERNANCE_SAFE_ADDRESS or '')
    addresses = list(dict.fromkeys(address.lower() for address in raw.split(',') if address))
    if len(addresses) > 16:
        raise ValueError('Safe event indexer address policy exceeds 16 configured Safes')
    lookback = min(int(settings.SAFE_EVENT_INDEXER_LOOKBACK_BLOCKS or 0) or 50_000, 100_000)
    return addresses, lookback


def dashboard_enabled(settings):
    # These are the existing getIndexerConfig relationships, not new startup
    # requirements. Retained invalid combinations disable this read domain.
    if not settings.DATABASE_URL or not settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS:
        return False
    finalized = settings.ONCHAIN_INDEXER_ARCHIVE_FREE_FINALIZED_MODE == '1'
    address_scoped = settings.ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS == '1'
    if settings.ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED == '1' and not (finalized and address_scoped):
        return False
    if not finalized and (settings.ONCHAIN_INDEXER_RECOVERY_SHARE_V2_ENABLED == '1'
                          or settings.ONCHAIN_INDEXER_FINALIZED_MULTICALL_ENABLED == '1'):
        return False
    identity = settings.CYBERGOLD_RUNTIME_CONFIG_ID
    if identity and not re.fullmatch(r'sha256:[0-9a-f]{64}', identity):
        return False
    return True


def create_configured_app(settings=None, database=None, client=None):
    settings = settings or load_environment()
    database = database or Database(settings.DATABASE_URL)
    chain = int(settings.NEXT_PUBLIC_CHAIN_ID)
    core = settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS
    cache_url = os.environ.get('CYBERGOLD_MARKET_CACHE_URL')
    pools = PoolProducer(settings)
    pool_reads = SharedReads()
    def route_rpc(value):
        return RouteSearchRpc(value, pool_reads=pool_reads)
    routes = RouteSearch(settings, rpc_factory=route_rpc)
    history = QuoteHistory(settings)
    uniswap_store = UniswapStore(database, chain, core) if settings.DATABASE_URL else None
    async def configuration_generation():
        from .fork_recovery import read_generation
        async with database.connection() as connection:
            stored = await read_generation(connection, core.lower())
        generation = stored['anchor']['generation'] if stored else None
        await history.observe_generation(generation)
        await market_quotes.observe_generation(generation)
        await configuration.observe_generation(generation)
        return generation
    configuration_store = UniswapStore(database, chain, core) if settings.DATABASE_URL else None
    configuration = ProtocolConfiguration(settings, configuration_store,
        generation_reader=configuration_generation if chain == 31338 and settings.DATABASE_URL else None)
    uniswap_registry = PoolRegistry(settings, store=uniswap_store, pool_reads=pool_reads)
    pools.registry = uniswap_registry
    market_recipient = DailyRecipientCache(uniswap_store, settings.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS)
    market_quotes = MarketQuotes(settings, uniswap_registry, recipient_cache=market_recipient,
                                request_resolver=configuration.resolve_request)
    routes.engine = market_quotes
    core_quotes = QuoteIntent(settings, routes, basket_math=BasketMath(), seeds=VerifiedGrossSeed(), history=history,
        correction=delayed_local_step, retain_plans=True, early_issue_probe=chain == 31338)
    universal_quotes = UniversalQuotes(settings, market_quotes)
    market_quotes.universal_quotes = universal_quotes
    trade_quotes = TradeQuotes(settings, core_quotes, market_quotes, request_resolver=configuration.resolve_request)
    trade_quotes.universal_quotes = universal_quotes
    shared_core_quotes = IntentSharing(core_quotes, rpc_factory=route_rpc,
                                      request_resolver=configuration.resolve_request)
    shared_core_quotes.universal_quotes = universal_quotes

    async def close_runtime():
        await pool_reads.close()
        await database.close()

    async def safe_read():
        if not settings.DATABASE_URL:
            return {'enabled': False, 'events': []}
        addresses, lookback = safe_history_profile(settings)
        return await get_safe_activity(database, chain, addresses, lookback)

    async def core_read():
        return await get_core_activity(database if settings.DATABASE_URL else None, chain, core)

    async def helpers_read():
        return await get_helpers_activity(database if settings.DATABASE_URL else None, chain,
            settings.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS)

    async def pool_activity_read(filters):
        activity_store = uniswap_store
        if uniswap_store and chain == 31338:
            from .fork_recovery import read_generation
            async with database.connection() as connection:
                stored = await read_generation(connection, core.lower())
            generation = stored['anchor']['generation'] if stored else None
            # Activity reads select the durable generation independently of the
            # registry's writable scope and its in-flight observations.
            activity_store = UniswapStore(database, chain, core)
            activity_store.scope = 'generation:'+str(generation)+':' if generation else 'generation:unobserved:'
        return await get_pool_activity(activity_store, chain, filters)

    async def dashboard_read():
        if not dashboard_enabled(settings):
            return disabled_dashboard()
        generation = None
        if chain == 31338:
            # The existing refresh controller/worker owns this durable marker.
            # Expose it so the App can discard old-fork transaction/receipt state
            # even when chain ID, addresses and Safe nonce remain unchanged.
            generation = await configuration_generation()
        payload = await dashboard_snapshot(database, chain, core)
        if chain == 31338:
            payload = {**payload, 'sandboxForkGeneration': generation}
        return payload

    # Retained alias operations bootstrap their schema lazily; other reads do
    # not. Unavailable DB does not block HTTP startup.
    return create_app(client=client, rpc_url=settings.RPC_URL,
                      rpc_authorization=settings.RPC_AUTHORIZATION,
                      safe_activity=safe_read, core_activity=core_read, helpers_activity=helpers_read, pool_activity=pool_activity_read,
                      dashboard=dashboard_read, on_shutdown=close_runtime,
                      pool_cache=AuthoritativePoolCache(database,pools),pool_producer=pools,
                      market_quotes=market_quotes,
                      uniswap_registry=uniswap_registry,
                      safe_service_url=settings.SAFE_TX_SERVICE_URL,
                      safe_status=SafeStatus(database,chain,lambda:safe_history_profile(settings)[0]),
                      faucet_service=SandboxFunding(client=client,
                          enabled=settings.FORK_FAUCET_ENABLED=='1',
                          rpc_url=settings.FORK_FAUCET_RPC_URL,
                          rpc_authorization=settings.FORK_FAUCET_RPC_AUTHORIZATION,
                          state_root=settings.FORK_FAUCET_STATE_ROOT,
                          generation_file=settings.FORK_FAUCET_GENERATION_FILE),
                      recovery=RecoveryLoader(settings),aliases=AliasService(database),protocol_facts=ProtocolFacts(settings, on_observation=history.facts_observed, history=history, pool_reads=pool_reads),
                      protocol_configuration=configuration,
                      basket_preview=BasketPreview(settings, history=history),
                      basket_max=BasketMax(settings),
                      token_preview=TokenPreview(settings),
                      uniswap_quote=UniswapQuote(settings, engine=market_quotes),
                      route_search=routes,
                      quote_intent=shared_core_quotes,
                      trade_quotes=trade_quotes,
                      universal_quotes=universal_quotes,
                      governance_core_facts=GovernanceCoreFacts(settings),
                      wallet_balances=WalletBalances(settings),
                      token_balance=TokenBalance(settings),
                      liquidity_positions=LiquidityPositions(settings),
                      native_balance=NativeBalance(settings),
                      ens_records=EnsRecords(settings),
                      transaction_revert=TransactionRevert(settings),
                      transaction_fees=TransactionFees(settings),
                      transaction_nonce=TransactionNonce(settings),
                      transaction_receipt=TransactionReceipt(settings),
                      receipt_wait=ReceiptWait(settings),
                      safe_transaction=SafeTransaction(settings),
                      governance_roles=GovernanceRoles(settings),
                      governance_authority=GovernanceAuthority(settings),
                      recovery_redemption=RecoveryRedemption(settings),
                      permit2_approval_gas=Permit2ApprovalGas(settings),
                      safe_execution=SafeExecution(settings),
                      helpers_execution=HelpersExecution(settings),
                      core_recovery_assets=CoreRecoveryAssets(settings),
                      recovery_share_precision=RecoverySharePrecision(settings),
                      core_permit=CorePermit(settings),
                      token_observations=TokenObservations(settings),
                      token_approval_gas=TokenApprovalGas(settings),
                      permit2_context=Permit2Context(settings),
                      helpers_router_facts=HelpersRouterFacts(settings, owner_observer=market_recipient.observe,
                          configuration_observer=configuration.capture_facts,
                          configuration_scope=lambda: configuration.generation),
                      governance_safe_principal=GovernanceSafePrincipal(settings),
                      governance_target_code=GovernanceTargetCode(settings),
                      shared_market=SharedMarketCache(cache_url, chain) if cache_url else None,
                      release=os.environ.get('CYBERGOLD_BACKEND_COMMIT'))
