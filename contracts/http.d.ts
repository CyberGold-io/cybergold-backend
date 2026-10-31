export interface paths {
    "/api/protocol/facts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Live configured Core/Helpers facts at one canonical block hash, with lossless raw values and per-read failures. No caller-selected ABI, contract target or provider. No database reconciliation or browser RPC fallback. Signing remains browser-owned. */
        get: operations["get__api_protocol_facts"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/protocol/config": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Configured deployment anchors and the App's initial token catalog, with a cached supported adapter selected from the canonical Helpers allowlist. No request-time chain RPC, routing-infrastructure exposure, signing or submission. Missing optional roots/adapter remain independent; live pause, roles and pre-sign observations keep their existing APIs. Sandbox generation uses the existing durable reset context. */
        get: operations["get__api_protocol_config"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/gold": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["get__api_gold"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/economic-quotes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Wallet-free whole-plan economics. Ordinary lookup reuses the last successful shared observation with its original context; explicit refresh searches current state and may seed from the saved plan. No execution guards, deadline, calldata, signing or broadcast. */
        post: operations["post__api_economic_quotes"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/economic-quotes/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Subscription-owned complete economic incumbents, canonically confirmed before ready publication while bounded search continues. Stored hits retain their historical observation contract. Caller disconnect cancels/drains only its owned work and preserves its last confirmed incumbent without signing or submission. */
        post: operations["post__api_economic_quotes_stream"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tx-preparations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Replay only the selected semantic plan at current state. Bind accepted input/output guards before repricing and start the ten-minute execution lifetime during unsigned preparation. No replacement-route discovery, signing or broadcast. */
        post: operations["post__api_tx_preparations"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/economic-estimates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description One Backend Fast Estimator; advisory Core/Market estimate and model evidence, independent of transaction preparation. Existing model callers retain their compatibility endpoints during migration. */
        post: operations["post__api_economic_estimates"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quotes/universal-exact-input": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Gross-funded universal exact-input plans for scalar Core/Market mixtures and direct basket issue/redemption. One joint Core invocation per candidate; 0/25/50/75/100 Core allocation and both mixed orders replay shared AMM pools in execution order. Measured unused AMM input is a disclosed protocol charge held by Helpers under its current owner. Native ETH and WETH are distinct currencies. The configured successor address is required; no signing, submission, deployment, or silent legacy-plan rebinding. */
        post: operations["post__api_quotes_universal_exact_input"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quotes/market": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Fresh exact-input requests delegate to the universal coordinator quote service when its release is configured, returning a disclosed Core/Market/mixed plan. True exact-output and captured legacy plans keep their original address, encoding, and refund semantics. Wallet funding, signing, full-call simulation and submission remain in the App. */
        post: operations["post__api_quotes_market"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quotes/market/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["post__api_quotes_market_stream"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quotes/market/model": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Amount-independent market model acquisition for an active view, without prior successful quotes, wallet signing or a mandatory tick scan. Canonical pool baseline plus contextual organic raw-AMM points; missing optional model state leaves ordinary quotes available. */
        post: operations["post__api_quotes_market_model"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quotes/trade/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Fresh exact-input trades use the universal Core/Market allocation grid when the universal release is configured. True exact-output preserves existing provider selection. A fresh output-target Core-sale winner becomes a newly disclosed Core-only universal quote at its solved gross input, preserving accepted scalar and Core vector minima. Captured legacy plans never silently change address or encoding. Signing and submission remain in the App. */
        post: operations["post__api_quotes_trade_stream"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quotes/trade/model": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Organic Core and market models with a Backend-ranked indicative estimate. Warm cached packets require no RPC; cold acquisition reuses existing lightweight provider baselines and shared context. Missing model state does not prevent exact trade search; neither models nor estimates are executable quotes. */
        post: operations["post__api_quotes_trade_model"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transaction/revert": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Replays the chain transaction at latest state for the Apps' receipt error display, using its hash only. EVM return bytes are preserved; private provider text is redacted, native absence/outage remains unavailable. This is not a historical proof of the original revert and never signs/submits or accepts caller-selected calldata/provider. */
        get: operations["get__api_transaction_revert"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/account/ens-name": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Ethereum primary ENS name via standard Web3.py, including forward-address verification, at the configured canonical block. Missing record is null; transport failure is unavailable. No caller-selected resolver, provider or database work. */
        get: operations["get__api_account_ens_name"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/account/ens-avatar-record": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description The Apps' avatar text record via standard Web3.py ENS at the configured canonical block. Standard ERC721 tokenURI / ERC1155 uri reads for NFT records use that same hash and return explicit per-read success/failure. Standard Viem retains URI/metadata/image rendering in the browser. No image or metadata URL is fetched by the server; no caller-selected ABI or provider. */
        get: operations["get__api_account_ens_avatar_record"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/account/native-balance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description The Apps wallet-library latest native ETH balance for its holder at one EIP-1898 canonical block hash from the configured provider. purpose=display opts ordinary loading out of the repeated chain check and final block reread; unmarked and other requests retain both existing checks. Lossless decimal amount; no unrelated token reads, provider selection, shared wallet cache or signing. Historical/pending-tag library requests retain compatibility until separately migrated. */
        get: operations["get__api_account_native_balance"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/account/wallet-balances": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description The Apps' six fixed ERC20 assets plus native ETH in one Multicall3 aggregate3 eth_call at one EIP-1898 canonical block hash from the configured provider. Each member allows failure; ETH uses Multicall3.getEthBalance(holder) inside the same aggregate. purpose=display opts ordinary loading out of the repeated chain check and final block reread; unmarked, swap-preflight and other requests retain both existing checks. Lossless decimal amounts and per-asset failures; no caller-selected token, ABI or provider. No separate native balance RPC, database or shared wallet cache; signing remains browser-owned. */
        get: operations["get__api_account_wallet_balances"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/account/token-balance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Compatibility balance read for one of the Apps' seven fixed wallet assets at its own canonical block. Uses the existing configured Core for CYGLD and fixed Ethereum reserve-token addresses, or native ETH. Lossless decimal raw balance and explicit per-read failure; unrelated assets are never read. Current wallet display and transaction flows use the complete wallet-balances Multicall3 snapshot. No caller-selected contract, ABI or provider, shared wallet cache, signing or submission. Existing fifteen-second deadline, caller cancellation and no-store apply. */
        get: operations["get__api_account_token_balance"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/account/liquidity-positions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Wallet-owned Uniswap v4 PAXG/CYGLD LP NFTs for the fixed Ethereum pool, discovered from incoming/outgoing Transfer logs since pool initialization. Position reads share one canonical block hash. Per-position and aggregate decimal token quantities include deposited principal plus unclaimed LP fees, calculated from the position's liquidity and Q128 fee-growth delta with uint256 wraparound. Fee-read failures are unavailable, never a partial principal-only total. Uses the configured environment RPC, so Sandbox fork results can differ from Mainnet. No caller-selected pool, ABI or provider, database work, shared wallet cache, signing or submission. */
        get: operations["get__api_account_liquidity_positions"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/governance/roles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description The configured Apps' fixed diamond role rosters at one canonical block. Preserves the existing first-50 display policy, raw expected counts and per-member failures. Missing configuration is explicit. No caller-selected address, role, ABI or provider, authority decision, signing or submission. */
        get: operations["get__api_governance_roles"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/governance/authority": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Configured diamond paused/Safe wallet and existing canPause/canUnpause observations at one canonical block. Optional connected account is observed without deciding authority, signing or submission. Per-read failures stay explicit; no arbitrary contract, method, ABI or provider. */
        get: operations["get__api_governance_authority"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transaction/recovery-redemption": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Simulate the App's exact configured Core redeemRecoveryShares call, with holder as sender and recipient and unchanged shares/minRawOut. Canonical configured-chain context and lossless output; no wallet signature, submission, arbitrary ABI, target or provider. Failure never becomes a successful preview. */
        post: operations["post__api_transaction_recovery_redemption"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transaction/permit2-approval-gas": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Native latest-state gas estimate for the App's fixed ERC20 approve(configured Permit2, maxUint256) operation. Existing holder/token and configured Helpers spender, no arbitrary amount, ABI, provider, signing, submission or reservation. The App retains its gas padding and existing failure fallback. */
        post: operations["post__api_transaction_permit2_approval_gas"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/governance/safe-nonce": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Fresh Safe contract nonce at a canonical configured-chain block. No nonce reservation, generic ABI/provider, signing or submission. The App retains pending proposal selection and wallet intent. */
        get: operations["get__api_governance_safe_nonce"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/governance/safe-transaction-hash": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description The existing Apps' fixed Safe getTransactionHash read for their exact unsigned payload. Standard ABI encoding preserves integer and byte values. No signing, proposal publication, simulation, submission or server-selected transaction fields. */
        post: operations["post__api_governance_safe_transaction_hash"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/governance/safe-execution": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Simulate the App's exact Safe execTransaction at latest state, with unchanged payload, signatures, executor and pending executor nonce. A returned false remains false; reverts/outage remain unavailable. No signing, submission, transaction replacement, arbitrary ABI or provider, or server-selected transaction intent. */
        post: operations["post__api_governance_safe_execution"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transaction/helpers-execution": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Helpers Swap operation fee hints, including mixed native/Permit2 basket acquisition and existing allowance redemption: exact caller arguments and optional native value, fixed configured Helpers ABI/target, latest-state simulation followed by native gas estimation. Decimal JSON amounts preserve ABI values. No ABI, provider, target, signing, submission or server-selected intent is accepted from the App. The existing caller keeps fee-hint failure behavior. */
        post: operations["post__api_transaction_helpers_execution"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transaction/receipt": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Fresh configured-chain receipt status, block identity and raw logs for the Apps' Safe history. Native receipt absence is null/unknown; provider failure is unavailable, never inferred pending/replaced/cancelled. No database, cache, confirmations, replacement search, signing or submission. */
        get: operations["get__api_transaction_receipt"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transaction/wait/head": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Fresh configured-chain observation for the Apps' existing Viem receipt confirmation/replacement algorithm. Head is decimal; native Ethereum transaction, receipt and full-block wire fields retain lossless hex quantities and standard formatter behavior. Native absence is null; supplier failures stay errors. No arbitrary method, provider, ABI, signing, submission or server notification queue. */
        get: operations["get__api_transaction_wait_head"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transaction/wait/transaction": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Fresh configured-chain observation for the Apps' existing Viem receipt confirmation/replacement algorithm. Head is decimal; native Ethereum transaction, receipt and full-block wire fields retain lossless hex quantities and standard formatter behavior. Native absence is null; supplier failures stay errors. No arbitrary method, provider, ABI, signing, submission or server notification queue. */
        get: operations["get__api_transaction_wait_transaction"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transaction/wait/receipt": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Fresh configured-chain observation for the Apps' existing Viem receipt confirmation/replacement algorithm. Head is decimal; native Ethereum transaction, receipt and full-block wire fields retain lossless hex quantities and standard formatter behavior. Native absence is null; supplier failures stay errors. No arbitrary method, provider, ABI, signing, submission or server notification queue. */
        get: operations["get__api_transaction_wait_receipt"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transaction/wait/block": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Fresh configured-chain observation for the Apps' existing Viem receipt confirmation/replacement algorithm. Head is decimal; native Ethereum transaction, receipt and full-block wire fields retain lossless hex quantities and standard formatter behavior. Native absence is null; supplier failures stay errors. No arbitrary method, provider, ABI, signing, submission or server notification queue. */
        get: operations["get__api_transaction_wait_block"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/account/transaction-nonce": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Fresh configured-chain pending account nonce for the Apps' Governance transactions. Lossless decimal nonce and canonical head context; pending state itself is not block-pinned. No cache, reservation, EOA/code prerequisite, simulation, signing or submission. Existing wallet intent and chain checks remain in the App. */
        get: operations["get__api_account_transaction_nonce"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transaction/fees": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description The configured Ethereum App's EIP-1559 fee estimate, preserving its 1.2 base-fee multiplier and priority-method gas-price fallback. Lossless decimal fees with canonical configured-chain block context. No fee cache, simulation, signing or submission. */
        get: operations["get__api_transaction_fees"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/protocol/recovery-share-precision": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description The configured Core recoveryPool's permanent shareDecimals for the App's quote display at one canonical block. Current basket membership and token decimals do not determine share precision. No caller-selected contract, ABI, provider, wallet action or shared account cache. */
        get: operations["get__api_protocol_recovery_share_precision"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/protocol/recovery-assets": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description The configured Core's attached recovery assets in contract order, at one canonical configured-chain block. Empty success is distinct from unavailable; the App constructs redemption minima. No caller ABI/provider/contract target, cache, schema work or signing. */
        get: operations["get__api_protocol_recovery_assets"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/account/permit2": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description The App's fixed fresh Permit2 router/bytecode verification, first-unused nonce traversal and selected token allowances at one canonical block. Helpers chooses the Permit2 target; callers supply only owner/token observations, never a spender, ABI, provider or method. Ordered decimal allowances/nonce retain all bits. No cache, nonce reservation, approval, signing or submission; existing App verification and wallet-intent checks remain. */
        post: operations["post__api_account_permit2"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tokens/metadata": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Selected ERC20 string/legacy bytes32 metadata and optional holder balance through the configured provider. Lossless balance and per-field errors; purpose=balance skips metadata/domain/qualification work for ordinary wallet refresh. Otherwise optional standard-permit domain qualification uses disposable in-memory signatures only inside eth_call. Capability is independent of quote/approval eligibility. No generic ABI, method, provider, user signing or submission. Bounded process-local reusable metadata, existing deadline/cancellation and no-store. */
        get: operations["get__api_tokens_metadata"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/account/token-permit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Fresh selected ERC20 owner nonce and configured Helpers allowance at one canonical block. Domain separator is reread and changes invalidate reusable domain observations. Explicit unknown, no-native-permit, variants and RPC unavailability; no cached user nonce, reservation, server-selected value/deadline, user signature or submission. */
        get: operations["get__api_account_token_permit"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transaction/token-approval-gas": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Native latest-state gas estimation for the exact selected ERC20 approve(configured Helpers, amount), including zero-first reset amount zero. Lossless amount, no spender/provider/ABI selection or submission; nonstandard approval return data is not decoded or relabeled. */
        post: operations["post__api_transaction_token_approval_gas"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/account/core-permit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Fresh configured Core name and owner nonce at one canonical block, preserving the App's version-1 EIP-2612 domain and configured Helpers spender. Lossless decimal nonce, no cache/ABI/provider/contract selection. The App keeps value/deadline choice, wallet chain checks, signing and submission. Read failures never supply a zero/default nonce. */
        get: operations["get__api_account_core_permit"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/governance/core-facts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Configured Core governance configuration at one canonical block: treasury, basket hash, fees and supply limits. Preserves per-field failures and decimal amounts. No caller-selected contract, ABI or provider; wallet signing and submission remain in the App. */
        get: operations["get__api_governance_core_facts"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/governance/helpers-facts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Configured Helpers fee, Permit2, wrapped native token, owner, complete adapter allowlist and pause state at one canonical block. Optional App swap-adapter address adds its native code-presence observation at that block, preserving the existing pre-submission check. Lossless fee and per-field failures; no caller-selected ABI, method or provider. Adapter approval is membership in this same canonical enumerable allowlist. Historical tokenPermitIssuance/basketPermitIssuance probes report selector installation for retained deployments; universalExactInput=true separately observes the canonical executeExactInput selector through the same Diamond facetAddress read. Absence remains false and read failure remains unavailable. Signing/submission stay browser-owned. */
        get: operations["get__api_governance_helpers_facts"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/governance/safe-principal": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description The App's governance principal bytecode, Safe owners and threshold at one canonical configured-chain block. Per-field failures and a lossless threshold preserve the App's existing authority interpretation. No caller-selected ABI, method or provider, role authorization, nonce, database write, signing or submission. */
        get: operations["get__api_governance_safe_principal"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/governance/target-code": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Fresh configured-chain code presence for the Apps' Safe proposal destination description, at one canonical block. Empty code is false; supplier failure is unavailable, never an EOA classification. No ABI, method, provider, simulation, authority decision, signing or submission; the App retains its existing proposal interpretation. */
        get: operations["get__api_governance_target_code"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quotes/basket-preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description The four Helpers issue/redeem basket previews used by Swap, at one canonical configured-chain block. Raw amounts remain decimal strings and basket order is preserved. No caller-selected target, ABI, method or provider. No database, server transaction submission or retry. Wallet signing remains frontend-owned. */
        post: operations["post__api_quotes_basket_preview"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quotes/basket-max": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Largest wallet-bounded proportional basket driver whose unclipped direct-basket mint fits current gross capacity. Uses configured Core assets, weights, decimals, conversion and fee rounding at one canonical block, with an ordinary positive exact-in Helpers preview. Zero capacity returns zero amounts. No wallet read, signing, submission, Market basket provider or client fee calculation. */
        post: operations["post__api_quotes_basket_max"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quotes/token-preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description The Apps' six token/native Helpers issue/redeem previews at one canonical configured-chain block. Preserves ordered opaque adapter calldata and lossless amounts; no routing, slippage modification, caller-selected target/ABI/provider, signing or submission. Ordinary contract errors remain recoverable preview failures. */
        post: operations["post__api_quotes_token_preview"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quotes/routes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Route search for all ordered targets through one structured route engine and shared candidate scheduler. Preserves direct/via-WETH V3 fee coverage alongside the selected protocol inventory, using SDK pool math and ordinary native Quoter fallback at one canonical block. Exact-output path reversal is a compatibility projection; internal routes keep forward economic direction. Independent candidate failures remain partial failures. No caller-selected ABI, provider or target contract, wallet signing or submission. Lossless amounts, no-store and existing deadline/cancellation; RPC metrics marked coordinator are not supplier call totals. */
        post: operations["post__api_quotes_routes"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quotes/routes/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Newline-delimited progress snapshots as candidates settle through the common structured route engine and scheduler. Known inventory overlaps discovery; provisional progress does not prove execution readiness, and only complete follows the existing canonicality check. Original V3 coverage and selected graph routes share SDK pricing, native fallback, candidate errors and owned-task cancellation/drain. Transport/reorg failure emits a redacted terminal error with optional observed RPC diagnostics. No caller-selected contract/provider or submission. */
        post: operations["post__api_quotes_routes_stream"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quotes/intent/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Recipient-less legacy Core quote API. Once the universal release is configured, modes that previously executed exact input return explicitly read-only numeric results without leg calldata or execution recipes. Pure numerical previews and true issue exact-output retain their existing behavior; use the canonical universal endpoint for new exact-input execution. */
        post: operations["post__api_quotes_intent_stream"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quotes/uniswap": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description A caller-selected V3 path is normalized once to a forward structured route and priced by the same SDK quote engine and ordinary native Quoter fallback as route search, at one canonical block. Exact-output packed input retains its established reversed wire order; the result remains one lossless decimal amount. The returned Quoter address identifies the configured native reference, not the source of every successful computation. No caller-selected contract, ABI/provider, wallet signing or transaction submission, and no additional hop, token or path policy. */
        post: operations["post__api_quotes_uniswap"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/fx": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["get__api_fx"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/activity/core": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Latest 100 retained Core journal logs, decoded with shipped and historical migration events. Reports stored journal range and undecoded rows; no RPC, replay, database writes or claim to include failed or no-event transactions. No public frontend adapter is required for this operator API. */
        get: operations["get__api_activity_core"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/activity/helpers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Latest 100 retained Helpers settlement, fee, dust and administration logs with canonical ABI decoding. Its own address-scoped finalized journal starts at the configured collection boundary and reports its independent backfill cursor. Unknown historical layouts remain visible without decoded arguments. No Core supply/reserve double counting, RPC collection on reads or public frontend adapter. */
        get: operations["get__api_activity_helpers"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/activity/pools": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Latest 100 persisted V2/V3/V4 pool events across the known CYGLD and active connector inventory. Each exact pool identity retains up to 1000 events and 64 canonical scan-range rollups with explicit coverage. Worker state logs are reused; endpoint reads never acquire RPC logs, backfill, write activity or gate quotes/models. Raw signed amounts and protocol-specific input/output volume exclude USD, per-pool TVL and all-time claims; liquidity deltas remain range units, not token quantities. V4 identity includes PoolManager and PoolId. Existing environment bearer/no-store activity conventions apply. */
        get: operations["get__api_activity_pools"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/activity/safe": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Latest 100 retained logs across the configured Safes. Decodes existing indexed/non-indexed execution layouts, reports each journal range and the unchanged execution-projection lookback. Includes older retained rows without RPC backfill, projection writes or a claim to complete Safe history. Operator API behind the existing environment bearer; no frontend adapter. */
        get: operations["get__api_activity_safe"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/diagnostics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Best-effort, untrusted browser observations projected onto fixed fields in the existing JSON log, including optional signed numeric wallet/RPC codes and four-byte EVM error selectors. Invalid optional fields are ignored. No raw messages, wallet addresses, signatures, error arguments or RPC bodies. An acknowledgement is not proof of collector delivery. */
        post: operations["post__api_diagnostics"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/dashboard/onchain-summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Completed PostgreSQL dashboard projection, including its existing disabled response; never triggers reconciliation. Sandbox responses also carry the existing durable fork generation for clearing old browser transaction/receipt state; a null or absent marker does not identify a new generation. */
        get: operations["get__api_dashboard_onchain_summary"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/recovery/shares": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Live hash-pinned portfolio. A nonzero offset requires blockHash; all responses are no-store. */
        get: operations["get__api_recovery_shares"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/rpc": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Existing read-only JSON-RPC compatibility policy; raw body up to 1 MiB and batch up to 100. After ingress authentication, errors use JSON-RPC envelopes. */
        post: operations["post__api_rpc"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/governance/owner-aliases": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["post__api_governance_owner_aliases"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quote-pool-cache": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Retained cache envelopes. The Python pool-authority release accepts browser pool identifiers only; existence/addresses/price/liquidity and quote-success hints are never trusted. Reads refresh historical rows through the configured chain; an outage never publishes browser-owned observations. */
        post: operations["post__api_quote_pool_cache"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/pools/snapshot": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Canonical configured-chain V2/V3/V4 pool state from the shared quote registry. Omitted protocol retains the legacy V3 response. V4 identity includes PoolManager and full PoolKey; its singleton token balances/TVL are absent. Marginal price is the raw token1/token0 rational, concentrated active liquidity is not total TVL, and tick/bitmap coverage contains only acquired ranges. Integer values remain lossless; caller state is never authoritative. */
        post: operations["post__api_pools_snapshot"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/pools/catalog": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Known canonical CYGLD V2/V3/V4 pool identities, or pair-filtered known inventory. Uses the existing monthly discovery/event registry; no fresh catalog scan, pool getter wave, or client poller. Coverage is the selected inventory, not a claim to have discovered every possible pool. */
        get: operations["get__api_pools_catalog"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/safe": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Preserves the selected Safe upstream service's JSON response; proposal/confirmation requests are never automatically retried. */
        post: operations["post__api_safe"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/safe/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["post__api_safe_events"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/faucet": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** @description Sandbox faucet, authenticated by the shared backend bearer. Route failures retain safe error text and add a stable faucet code and correlationId matching the backend failure log. Known adapter outcomes distinguish quota, in-progress, uncertain, conflict and funding failure. Transport deadlines do not prove that funding failed. Private adapter status/code and elapsed time stay in the correlated backend log. Forward trusted nginx client IP; retain Retry-After and X-CyberGold-Faucet-Request-Id. No Origin check or separate caller credential, implicit retry or changed funding behavior. */
        post: operations["post__api_faucet"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/internal/onchain-indexer/reconcile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Private Ops control only; public frontend has no adapter. Existing versioned worker protocol and raw parser remain authoritative. */
        get: operations["get__api_internal_onchain_indexer_reconcile"];
        put?: never;
        /** @description Private Ops control only; public frontend has no adapter. Existing versioned worker protocol and raw parser remain authoritative. */
        post: operations["post__api_internal_onchain_indexer_reconcile"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/internal/onchain-indexer/fork-generation": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** @description Private Ops control only; public frontend has no adapter. Existing versioned worker protocol and raw parser remain authoritative. */
        get: operations["get__api_internal_onchain_indexer_fork_generation"];
        put?: never;
        /** @description Private Ops control only; public frontend has no adapter. Existing versioned worker protocol and raw parser remain authoritative. */
        post: operations["post__api_internal_onchain_indexer_fork_generation"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** @enum {string} */
        QuoteErrorCode: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
        /** @description Economic calculation has no recipient, execution guards, expiry or wire bytes. */
        EconomicRequest: {
            inputs: {
                currency: string;
                amount: string;
            }[];
            /** @enum {number} */
            intent: 0 | 1 | 2 | 3;
            outputCurrency: string;
        };
        "Record<string,Record<string,unknown>>": {
            [key: string]: components["schemas"]["Record<string,unknown>"];
        };
        "Record<string,unknown>": {
            [key: string]: unknown;
        };
        EconomicQuoteRequest: components["schemas"]["EconomicRequest"] & {
            refresh?: boolean;
        };
        EconomicQuote: components["schemas"]["Omit<UniversalExactInputQuote,\"plan\"|\"planDescription\"|\"outputMinimum\"|\"economicQuote\">"] & {
            request: components["schemas"]["EconomicRequest"];
            plan: {
                allocations: {
                    /** @enum {number} */
                    kind: 0 | 1;
                    amountIn: string;
                }[];
                conversions: components["schemas"]["Record<string,Record<string,unknown>>"];
                body: components["schemas"]["Record<string,unknown>"];
            };
            /** @description Measured conversion quantities; these never reduce declared funding by inference. */
            conversionObservations?: {
                operation: string;
                inputCurrency: string;
                fundedInput: string;
                consumedInput: string;
                outputCurrency: string;
                output: string;
            }[];
            observation?: {
                /** @enum {string} */
                source: "search" | "stored";
                refresh: boolean;
            };
            /** @description Cached arithmetic only; never executable amounts or accepted bounds. */
            reuseSample?: {
                referenceInput: string;
                netOutput: string;
                fees: {
                    coreProtocolFeeCygld: string;
                    coreHelpersFeeCygld: string;
                    marketFeeCygld: string;
                };
                /** @enum {string} */
                basis: "funded-input-approximation" | "market-sale-consumed" | "observed-nonretained";
            };
        };
        "Omit<UniversalExactInputQuote,\"plan\"|\"planDescription\"|\"outputMinimum\"|\"economicQuote\">": {
            /** @constant */
            operation: "executeExactInput";
            fees: {
                coreProtocolFeeCygld: string;
                coreHelpersFeeCygld: string;
                marketFeeCygld: string;
            };
            inputs: {
                currency: string;
                amount: string;
            }[];
            /** @constant */
            strategy: "universal";
            /** @enum {string} */
            routeFamily: "core" | "market" | "mixed";
            /** @constant */
            settlementPolicy: "protocol-retained-input";
            quotedInput?: string;
            inputMaximum?: string;
            quotedOutput: string;
            estimatedRetainedInputCharges: {
                branch: number;
                stage: number;
                currency: string;
                amount: string;
            }[];
            estimatedRecipientOutputs: {
                kind: number;
                token: string;
                id: string;
                amount: string;
            }[];
            recoveryShares: {
                kind: number;
                token: string;
                id: string;
                amount: string;
            }[];
            deployment: {
                helpers: string;
                adapter: string;
                /** @constant */
                encoding: "uniswap-routing-v1";
            };
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            retentionDisclosure: {
                custodian: string;
                /** @constant */
                beneficiary: "helpers-owner-at-settlement";
            };
            searchCoverage: {
                coreSharesPercent: number[];
                orders: string[];
                maxCoreInvocations: number;
                maxAmmHops: number;
                /** @constant */
                scope: "selected-inventory";
                /** @enum {string} */
                selectedPhase?: "backward-prefix" | "capacity-limited" | "detailed" | "first-result" | "nearby-lower" | "nearby-upper" | "route-family" | "route-family-exploration" | "saved-plan";
            };
            /** @description Producer clocks, distinct from client request or browser journey duration. */
            metrics?: {
                firstQualifiedMs?: number;
                selectionMs?: number;
                canonicalCompletedMs?: number;
                cleanupCompletedMs?: number;
                finalizationMs?: number;
            } & {
                totalMs: number;
                timeToFirstWholePlanMs: null | number;
                searchMs: null | number;
                selectionReason: ("best-initial" | "complete" | "first-extension" | "timeout") | null;
                nearbySearch?: {
                    starts: number;
                    completed: number;
                    sources: {
                        /** @enum {string} */
                        side: "lower" | "upper";
                        identity?: null | string;
                        /** @enum {string} */
                        referenceBasis?: "funded-input-approximation" | "market-sale-consumed" | "observed-nonretained";
                        attempts: {
                            funding: string;
                            completed?: boolean;
                            elapsedMs: number;
                            /** @enum {string} */
                            failureCode?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        }[];
                        /** @enum {string} */
                        failureCode?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                    }[];
                };
            };
        };
        /** @description Qualified frames contain canonical-ready full tuples; arithmetic stays separate. */
        EconomicQuoteEvent: ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "qualified";
            value: components["schemas"]["EconomicQuote"];
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "complete";
            value: components["schemas"]["EconomicQuote"];
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "invalidated";
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "error";
            error: string;
            /** @enum {string} */
            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
            /** @description Canonical preview rejection evidence; absent quantities were not provided by the contract. */
            constraint?: {
                /** @enum {string} */
                kind?: "issuance-cap" | "redemption-capacity" | "redemption-supply";
                /** @enum {string} */
                quantity?: "core-output-minima" | "gross-cygld-input" | "gross-cygld-mint";
                /** @enum {string} */
                limitKind?: "effective-supply-cap" | "maximum-total-supply";
                requestedRaw?: string;
                availableRaw?: string;
                currentSupplyRaw?: string;
                limitRaw?: string;
            };
            /** @description Optional observed RPC failure context; provider text is sanitized before publication. */
            diagnostics?: {
                rpcMethod?: string;
                stage?: string;
                elapsedMs?: number;
                upstreamErrorCode?: number;
                providerMessage?: string;
                httpStatus?: number;
                /** @enum {string} */
                failureType?: "backend-deadline" | "http-error" | "provider-timeout" | "rpc-error" | "transport-error";
                errorSelector?: string;
                errorName?: string;
            };
            /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
            quoteDiagnostics?: {
                /** @enum {string} */
                phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                elapsedMs?: number;
                qualified?: boolean;
                inversionIteration?: number;
                routeWave?: {
                    elapsedMs?: number;
                    subphaseElapsedMs?: number;
                    /** @enum {string} */
                    subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                    /** @enum {string} */
                    mode?: "exact-in" | "exact-out";
                    legacyCandidates?: number;
                    legacyCompleted?: number;
                    typedEnumerated?: number;
                    typedCompleted?: number;
                    typedPending?: number;
                    sdkRequests?: number;
                    sdkWaiting?: number;
                    sdkLockWaitMs?: number;
                    sdkExchangeMs?: number;
                    legs?: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        count: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            index: number;
                            inputAsset?: string;
                            outputAsset?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            amount?: string;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            started: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            succeeded: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            failed: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            cancelled: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            pending: number;
                            bestAvailable: boolean;
                            failureCounts: {
                                code: components["schemas"]["QuoteErrorCode"];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                count: number;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedFailureCodes: number;
                            bestPools: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools: number;
                        }[];
                    };
                };
                providerQualifications?: {
                    /** @enum {string} */
                    provider: "core" | "market";
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    attempts: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    qualified: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    rejected: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    notImproved: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    cancelled: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    superseded: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    pending: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    omittedRows: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    selectedAttempt?: number;
                    /** @enum {string} */
                    selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    firstQualifiedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    selectionMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    canonicalCompletedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    cleanupCompletedMs?: number;
                    rows: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempt: number;
                        /** @enum {string} */
                        stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                        /** @enum {string} */
                        outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                        /** @enum {string} */
                        code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        targetAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        minimumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountIn?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountIn?: string;
                        /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                        startedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        completedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        elapsedMs?: number;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        executionAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedInput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedOutput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        inputMaximum?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        outputMinimum?: string;
                        pools?: {
                            /** @enum {string} */
                            protocol: "v2" | "v3" | "v4";
                            /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                            poolId?: string;
                            poolAddress?: string;
                        }[];
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedPools?: number;
                    }[];
                };
            };
        });
        PreparedTransaction: {
            /** @constant */
            strategy: "universal";
            /** @enum {string} */
            routeFamily: "core" | "market" | "mixed";
            /** @constant */
            operation: "executeExactInput";
            /** @constant */
            settlementPolicy: "protocol-retained-input";
            plan: components["schemas"]["UniversalExactInputPlan"];
            planDescription: components["schemas"]["Record<string,unknown>"];
            economicQuote?: components["schemas"]["EconomicQuote"];
            inputs: {
                currency: string;
                amount: string;
            }[];
            quotedInput?: string;
            inputMaximum?: string;
            quotedOutput: string;
            outputMinimum: string;
            estimatedRetainedInputCharges: {
                branch: number;
                stage: number;
                currency: string;
                amount: string;
            }[];
            estimatedRecipientOutputs: {
                kind: number;
                token: string;
                id: string;
                amount: string;
            }[];
            fees: {
                coreProtocolFeeCygld: string;
                coreHelpersFeeCygld: string;
                marketFeeCygld: string;
            };
            recoveryShares: {
                kind: number;
                token: string;
                id: string;
                amount: string;
            }[];
            deployment: {
                helpers: string;
                adapter: string;
                /** @constant */
                encoding: "uniswap-routing-v1";
            };
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            retentionDisclosure: {
                custodian: string;
                /** @constant */
                beneficiary: "helpers-owner-at-settlement";
            };
            searchCoverage: {
                coreSharesPercent: number[];
                orders: string[];
                maxCoreInvocations: number;
                maxAmmHops: number;
                /** @constant */
                scope: "selected-inventory";
                /** @enum {string} */
                selectedPhase?: "backward-prefix" | "capacity-limited" | "detailed" | "first-result" | "nearby-lower" | "nearby-upper" | "route-family" | "route-family-exploration" | "saved-plan";
            };
            /** @description Producer clocks, distinct from client request or browser journey duration. */
            metrics?: {
                firstQualifiedMs?: number;
                selectionMs?: number;
                canonicalCompletedMs?: number;
                cleanupCompletedMs?: number;
                finalizationMs?: number;
            } & {
                totalMs: number;
                timeToFirstWholePlanMs: null | number;
                searchMs: null | number;
                selectionReason: ("best-initial" | "complete" | "first-extension" | "timeout") | null;
                nearbySearch?: {
                    starts: number;
                    completed: number;
                    sources: {
                        /** @enum {string} */
                        side: "lower" | "upper";
                        identity?: null | string;
                        /** @enum {string} */
                        referenceBasis?: "funded-input-approximation" | "market-sale-consumed" | "observed-nonretained";
                        attempts: {
                            funding: string;
                            completed?: boolean;
                            elapsedMs: number;
                            /** @enum {string} */
                            failureCode?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        }[];
                        /** @enum {string} */
                        failureCode?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                    }[];
                };
            };
        } & {
            economicQuote: components["schemas"]["EconomicQuote"];
            sender: string;
        };
        UniversalExactInputPlan: components["schemas"]["Omit<UniversalExactInputRequest,\"slippageBps\">"] & {
            minimumOutput: string;
            body: string;
        };
        "Omit<UniversalExactInputRequest,\"slippageBps\">": {
            deadline: string;
            recipient: string;
            inputs: {
                currency: string;
                amount: string;
            }[];
            /** @enum {number} */
            intent: 0 | 1 | 2 | 3;
            outputCurrency: string;
        };
        TradeQuoteRequest: {
            /** @enum {string} */
            side: "buy" | "sell";
            /** @enum {string} */
            mode: "exact-in" | "exact-out";
            counterToken: string;
            native: boolean;
            amount: string;
            slippageBps?: number;
        } & {
            recipient: string;
            deadline: string;
            retainedPlan?: {
                /** @constant */
                strategy: "core";
                request: {
                    /** @enum {string} */
                    mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
                    token: string;
                    quoteToken: string;
                    native: boolean;
                    amount: string;
                    adapter?: string;
                    deadline: string;
                    orderedAssets: string[];
                    targets: {
                        inputAsset: string;
                        outputAsset: string;
                        amount: string;
                    }[];
                    /**
                     * @description Execution tolerance in basis points; omitted defaults to 100 (1%).
                     * @default 100
                     */
                    slippageBps: number;
                    retainedPlan?: {
                        slippageBps?: number;
                        expectedInputAmount?: string;
                        executionAmount: string;
                        maximumInputAmount: string;
                        minimumAmountOut: string;
                        quotes: (({
                            adapter: string;
                            amountIn: string;
                            minimumAmountOut: string;
                            data: string;
                            routePlan?: {
                                /** @constant */
                                version: 1;
                                /** @enum {string} */
                                executionContext: "helpers-core" | "helpers-market";
                                /** @enum {string} */
                                mode: "exactIn" | "exactOut";
                                tokenIn: string;
                                tokenOut: string;
                                branches: {
                                    amountIn: string;
                                    hops: {
                                        pool: components["schemas"]["RoutePoolRef"];
                                        zeroForOne: boolean;
                                    }[];
                                }[];
                                inputAmount: string;
                                outputAmount: string;
                                limit: string;
                                deadline: string;
                            };
                        } & {
                            outputAsset: string;
                        }) | ({
                            adapter: string;
                            minimumAmountOut: string;
                            data: string;
                            routePlan?: {
                                /** @constant */
                                version: 1;
                                /** @enum {string} */
                                executionContext: "helpers-core" | "helpers-market";
                                /** @enum {string} */
                                mode: "exactIn" | "exactOut";
                                tokenIn: string;
                                tokenOut: string;
                                branches: {
                                    amountIn: string;
                                    hops: {
                                        pool: components["schemas"]["RoutePoolRef"];
                                        zeroForOne: boolean;
                                    }[];
                                }[];
                                inputAmount: string;
                                outputAmount: string;
                                limit: string;
                                deadline: string;
                            };
                        } & {
                            inputAsset: string;
                            inputAmount: string;
                        }))[];
                        expectedCoreOutputs: {
                            kind: number;
                            token: string;
                            id: string;
                            minimumAmount: string;
                        }[];
                    };
                };
                quote: {
                    /** @enum {string} */
                    mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
                    context: {
                        chainId: number;
                        blockNumber: string;
                        blockHash: string;
                        observedAt: string;
                    };
                    quotes: (({
                        adapter: string;
                        amountIn: string;
                        minimumAmountOut: string;
                        data: string;
                        routePlan?: {
                            /** @constant */
                            version: 1;
                            /** @enum {string} */
                            executionContext: "helpers-core" | "helpers-market";
                            /** @enum {string} */
                            mode: "exactIn" | "exactOut";
                            tokenIn: string;
                            tokenOut: string;
                            branches: {
                                amountIn: string;
                                hops: {
                                    pool: components["schemas"]["RoutePoolRef"];
                                    zeroForOne: boolean;
                                }[];
                            }[];
                            inputAmount: string;
                            outputAmount: string;
                            limit: string;
                            deadline: string;
                        };
                    } & {
                        outputAsset: string;
                    }) | ({
                        adapter: string;
                        minimumAmountOut: string;
                        data: string;
                        routePlan?: {
                            /** @constant */
                            version: 1;
                            /** @enum {string} */
                            executionContext: "helpers-core" | "helpers-market";
                            /** @enum {string} */
                            mode: "exactIn" | "exactOut";
                            tokenIn: string;
                            tokenOut: string;
                            branches: {
                                amountIn: string;
                                hops: {
                                    pool: components["schemas"]["RoutePoolRef"];
                                    zeroForOne: boolean;
                                }[];
                            }[];
                            inputAmount: string;
                            outputAmount: string;
                            limit: string;
                            deadline: string;
                        };
                    } & {
                        inputAsset: string;
                        inputAmount: string;
                    }))[];
                    preview: {
                        netCygldOut: string;
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        orderedCoreAssets: string[];
                    } | {
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        orderedCoreAssets: string[];
                    } | {
                        minimumAmountOut: string;
                        projectedCoreOutputs: {
                            kind: number;
                            token: string;
                            id: string;
                            amount: string;
                        }[];
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                    };
                    initialPreview: {
                        netCygldOut: string;
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        amountsInExact: string[];
                        orderedCoreAssets: string[];
                    } | {
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        amountsInExact: string[];
                        orderedCoreAssets: string[];
                    } | {
                        projectedCoreOutputs: {
                            kind: number;
                            token: string;
                            id: string;
                            amount: string;
                        }[];
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                    } | {
                        grossCygldIn: string;
                        projectedCoreOutputs: {
                            kind: number;
                            token: string;
                            id: string;
                            amount: string;
                        }[];
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                    } | {
                        netCygldOut: string;
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        orderedCoreAssets: string[];
                    } | {
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        orderedCoreAssets: string[];
                    } | {
                        minimumAmountOut: string;
                        projectedCoreOutputs: {
                            kind: number;
                            token: string;
                            id: string;
                            amount: string;
                        }[];
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                    } | null;
                    basketPreview: {
                        netCygldOut: string;
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        amountsInExact: string[];
                        orderedCoreAssets: string[];
                    } | {
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        amountsInExact: string[];
                        orderedCoreAssets: string[];
                    } | {
                        projectedCoreOutputs: {
                            kind: number;
                            token: string;
                            id: string;
                            amount: string;
                        }[];
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                    } | {
                        grossCygldIn: string;
                        projectedCoreOutputs: {
                            kind: number;
                            token: string;
                            id: string;
                            amount: string;
                        }[];
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                    };
                    displayAmount: string;
                    executionAmount: string;
                    maximumInputAmount: string;
                    slippageBps?: number;
                    /** @description Expected input before execution cushions, including direct basket input. */
                    expectedInputAmount?: string;
                    requestedGrossCygldOut?: string;
                    requestedNetCygldOut?: string;
                    remainingGrossCapacity?: string;
                    remainingNetCapacity?: string;
                    expectedOutputAmount?: string;
                    expectedCoreOutputs?: {
                        kind: number;
                        token: string;
                        id: string;
                        minimumAmount: string;
                    }[];
                    metrics: {
                        rpcReads: number;
                        rpcReadsRequested: number;
                        rpcReadsCoalesced: number;
                        rpcReadsReused: number;
                        /** @constant */
                        rpcReadsScope?: "coordinator";
                        candidateCalls: number;
                        iterations: number;
                        totalMs: number;
                    } & {
                        firstQualifiedMs?: number;
                        selectionMs?: number;
                        canonicalCompletedMs?: number;
                        cleanupCompletedMs?: number;
                        finalizationMs?: number;
                    };
                    /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
                    quoteDiagnostics?: {
                        /** @enum {string} */
                        phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                        elapsedMs?: number;
                        qualified?: boolean;
                        inversionIteration?: number;
                        routeWave?: {
                            elapsedMs?: number;
                            subphaseElapsedMs?: number;
                            /** @enum {string} */
                            subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                            /** @enum {string} */
                            mode?: "exact-in" | "exact-out";
                            legacyCandidates?: number;
                            legacyCompleted?: number;
                            typedEnumerated?: number;
                            typedCompleted?: number;
                            typedPending?: number;
                            sdkRequests?: number;
                            sdkWaiting?: number;
                            sdkLockWaitMs?: number;
                            sdkExchangeMs?: number;
                            legs?: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                count: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedRows: number;
                                rows: {
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    index: number;
                                    inputAsset?: string;
                                    outputAsset?: string;
                                    /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                    amount?: string;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    started: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    succeeded: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    failed: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    cancelled: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    pending: number;
                                    bestAvailable: boolean;
                                    failureCounts: {
                                        code: components["schemas"]["QuoteErrorCode"];
                                        /** @description Bounded observation count; never an execution eligibility predicate. */
                                        count: number;
                                    }[];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    omittedFailureCodes: number;
                                    bestPools: {
                                        /** @enum {string} */
                                        protocol: "v2" | "v3" | "v4";
                                        /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                        poolId?: string;
                                        poolAddress?: string;
                                    }[];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    omittedPools: number;
                                }[];
                            };
                        };
                        providerQualifications?: {
                            /** @enum {string} */
                            provider: "core" | "market";
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            attempts: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            qualified: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            rejected: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            notImproved: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            cancelled: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            superseded: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            pending: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedRows: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            selectedAttempt?: number;
                            /** @enum {string} */
                            selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            firstQualifiedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            selectionMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            canonicalCompletedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            cleanupCompletedMs?: number;
                            rows: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                attempt: number;
                                /** @enum {string} */
                                stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                                /** @enum {string} */
                                outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                                /** @enum {string} */
                                code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                targetAmount?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                minimumAmountOut?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                maximumAmountOut?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                observedAmountOut?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                maximumAmountIn?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                observedAmountIn?: string;
                                /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                                startedMs?: number;
                                /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                                completedMs?: number;
                                /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                                elapsedMs?: number;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                executionAmount?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                quotedInput?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                quotedOutput?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                inputMaximum?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                outputMinimum?: string;
                                pools?: {
                                    /** @enum {string} */
                                    protocol: "v2" | "v3" | "v4";
                                    /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                    poolId?: string;
                                    poolAddress?: string;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedPools?: number;
                            }[];
                        };
                    };
                };
            } | {
                /** @constant */
                strategy: "market";
                request: {
                    /** @enum {string} */
                    side: "buy" | "sell";
                    /** @enum {string} */
                    mode: "exact-in" | "exact-out";
                    counterToken: string;
                    amount: string;
                    adapter?: string;
                    recipient: string;
                    deadline: string;
                    slippageBps?: number;
                    retainedPlan?: {
                        /** @enum {string} */
                        side: "buy" | "sell";
                        /** @enum {string} */
                        mode: "exact-in" | "exact-out";
                        amount: string;
                        slippageBps: number;
                        route: {
                            /** @constant */
                            version: 1;
                            /** @enum {string} */
                            executionContext: "helpers-core" | "helpers-market";
                            /** @enum {string} */
                            mode: "exactIn" | "exactOut";
                            tokenIn: string;
                            tokenOut: string;
                            branches: {
                                amountIn: string;
                                hops: {
                                    pool: components["schemas"]["RoutePoolRef"];
                                    zeroForOne: boolean;
                                }[];
                            }[];
                            inputAmount: string;
                            outputAmount: string;
                            limit: string;
                            deadline: string;
                        };
                        params: {
                            /** @enum {number} */
                            side: 0 | 1;
                            counterToken: string;
                            amount: string;
                            bound: string;
                            routedInput: string;
                            feeCygld: string;
                            recipient: string;
                            deadline: string;
                            adapter: string;
                            data: string;
                        };
                        fee: {
                            asset: string;
                            ratePpm: number;
                            amount: string;
                            /** @constant */
                            basis: "quoted";
                            notional: string;
                        };
                    };
                };
                quote: {
                    /** @constant */
                    operation: "market";
                    /** @enum {string} */
                    side: "buy" | "sell";
                    /** @enum {string} */
                    mode: "exact-in" | "exact-out";
                    tokenIn: string;
                    tokenOut: string;
                    amountIn: string;
                    amountOut: string;
                    totalInput: string;
                    netOutput: string;
                    grossOutput: string;
                    routedAmountIn: string;
                    inputMaximum: string;
                    outputMinimum: string;
                    refundDust: string;
                    outputRefundEstimate?: string;
                    fee: {
                        asset: string;
                        ratePpm: number;
                        amount: string;
                        /** @constant */
                        basis: "quoted";
                        notional: string;
                    };
                    params: {
                        /** @enum {number} */
                        side: 0 | 1;
                        counterToken: string;
                        amount: string;
                        bound: string;
                        routedInput: string;
                        feeCygld: string;
                        recipient: string;
                        deadline: string;
                        adapter: string;
                        data: string;
                    };
                    adapterData: string;
                    plan: {
                        /** @enum {string} */
                        side: "buy" | "sell";
                        /** @enum {string} */
                        mode: "exact-in" | "exact-out";
                        amount: string;
                        slippageBps: number;
                        route: {
                            /** @constant */
                            version: 1;
                            /** @enum {string} */
                            executionContext: "helpers-core" | "helpers-market";
                            /** @enum {string} */
                            mode: "exactIn" | "exactOut";
                            tokenIn: string;
                            tokenOut: string;
                            branches: {
                                amountIn: string;
                                hops: {
                                    pool: components["schemas"]["RoutePoolRef"];
                                    zeroForOne: boolean;
                                }[];
                            }[];
                            inputAmount: string;
                            outputAmount: string;
                            limit: string;
                            deadline: string;
                        };
                        params: {
                            /** @enum {number} */
                            side: 0 | 1;
                            counterToken: string;
                            amount: string;
                            bound: string;
                            routedInput: string;
                            feeCygld: string;
                            recipient: string;
                            deadline: string;
                            adapter: string;
                            data: string;
                        };
                        fee: {
                            asset: string;
                            ratePpm: number;
                            amount: string;
                            /** @constant */
                            basis: "quoted";
                            notional: string;
                        };
                    };
                    context: {
                        chainId: number;
                        blockNumber: string;
                        blockHash: string;
                        observedAt: string;
                    };
                    feeBeneficiaryDisplay?: {
                        address: string;
                        observedAt: string;
                    };
                    /** @description AMM price impact excluding LP/protocol/application fees; absent without a coherent baseline. */
                    priceImpactPpm?: string;
                    /** @constant */
                    qualification: "sdk";
                    executionSimulationRequired?: boolean;
                    quoteVerificationUnavailable?: string;
                    searchCoverage?: {
                        /** @constant */
                        scope: "selected-inventory";
                        maxHops: number;
                        splitPercentages: number[];
                        inventoryPools: number;
                        catalogMonth: null | string;
                    };
                    metrics: {
                        candidateCalls: number;
                        totalMs: number;
                    } & {
                        firstQualifiedMs?: number;
                        selectionMs?: number;
                        canonicalCompletedMs?: number;
                        cleanupCompletedMs?: number;
                        finalizationMs?: number;
                    };
                    /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
                    quoteDiagnostics?: {
                        /** @enum {string} */
                        phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                        elapsedMs?: number;
                        qualified?: boolean;
                        inversionIteration?: number;
                        routeWave?: {
                            elapsedMs?: number;
                            subphaseElapsedMs?: number;
                            /** @enum {string} */
                            subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                            /** @enum {string} */
                            mode?: "exact-in" | "exact-out";
                            legacyCandidates?: number;
                            legacyCompleted?: number;
                            typedEnumerated?: number;
                            typedCompleted?: number;
                            typedPending?: number;
                            sdkRequests?: number;
                            sdkWaiting?: number;
                            sdkLockWaitMs?: number;
                            sdkExchangeMs?: number;
                            legs?: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                count: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedRows: number;
                                rows: {
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    index: number;
                                    inputAsset?: string;
                                    outputAsset?: string;
                                    /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                    amount?: string;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    started: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    succeeded: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    failed: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    cancelled: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    pending: number;
                                    bestAvailable: boolean;
                                    failureCounts: {
                                        code: components["schemas"]["QuoteErrorCode"];
                                        /** @description Bounded observation count; never an execution eligibility predicate. */
                                        count: number;
                                    }[];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    omittedFailureCodes: number;
                                    bestPools: {
                                        /** @enum {string} */
                                        protocol: "v2" | "v3" | "v4";
                                        /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                        poolId?: string;
                                        poolAddress?: string;
                                    }[];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    omittedPools: number;
                                }[];
                            };
                        };
                        providerQualifications?: {
                            /** @enum {string} */
                            provider: "core" | "market";
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            attempts: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            qualified: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            rejected: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            notImproved: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            cancelled: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            superseded: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            pending: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedRows: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            selectedAttempt?: number;
                            /** @enum {string} */
                            selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            firstQualifiedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            selectionMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            canonicalCompletedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            cleanupCompletedMs?: number;
                            rows: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                attempt: number;
                                /** @enum {string} */
                                stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                                /** @enum {string} */
                                outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                                /** @enum {string} */
                                code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                targetAmount?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                minimumAmountOut?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                maximumAmountOut?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                observedAmountOut?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                maximumAmountIn?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                observedAmountIn?: string;
                                /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                                startedMs?: number;
                                /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                                completedMs?: number;
                                /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                                elapsedMs?: number;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                executionAmount?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                quotedInput?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                quotedOutput?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                inputMaximum?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                outputMinimum?: string;
                                pools?: {
                                    /** @enum {string} */
                                    protocol: "v2" | "v3" | "v4";
                                    /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                    poolId?: string;
                                    poolAddress?: string;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedPools?: number;
                            }[];
                        };
                    };
                };
            };
        };
        RoutePoolRef: components["schemas"]["Omit<MarketPoolRef,\"token0\"|\"token1\">"] & {
            /** @description Executable identity can precede optional SDK/display metadata acquisition. */
            token0: {
                address: string;
                decimals?: number;
                chainId?: number;
                decimalsKnown?: boolean;
            };
            /** @description Executable identity can precede optional SDK/display metadata acquisition. */
            token1: {
                address: string;
                decimals?: number;
                chainId?: number;
                decimalsKnown?: boolean;
            };
        };
        "Omit<MarketPoolRef,\"token0\"|\"token1\">": {
            address?: string;
            id: string;
            /** @enum {string} */
            protocol: "v2" | "v3" | "v4";
            feePips: number;
            tickSpacing?: number;
            poolManager?: string;
            hooks?: string;
        };
        /** @description Additive maps are optional for compatibility with prior served responses. */
        TradeQuote: ({
            /** @enum {string} */
            side: "buy" | "sell";
            /** @enum {string} */
            mode: "exact-in" | "exact-out";
            tokenIn: string;
            tokenOut: string;
            quotedInput: string;
            quotedOutput: string;
            inputMaximum: string;
            outputMinimum: string;
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            evaluation: components["schemas"]["TradeEvaluation"];
            metrics: {
                totalMs: number;
                targetReads: number;
            } & {
                firstQualifiedMs?: number;
                selectionMs?: number;
                canonicalCompletedMs?: number;
                cleanupCompletedMs?: number;
                finalizationMs?: number;
            };
        } & {
            /** @constant */
            strategy: "core";
            providerRequest: {
                /** @enum {string} */
                mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
                token: string;
                quoteToken: string;
                native: boolean;
                amount: string;
                adapter?: string;
                deadline: string;
                orderedAssets: string[];
                targets: {
                    inputAsset: string;
                    outputAsset: string;
                    amount: string;
                }[];
                /**
                 * @description Execution tolerance in basis points; omitted defaults to 100 (1%).
                 * @default 100
                 */
                slippageBps: number;
                retainedPlan?: {
                    slippageBps?: number;
                    expectedInputAmount?: string;
                    executionAmount: string;
                    maximumInputAmount: string;
                    minimumAmountOut: string;
                    quotes: (({
                        adapter: string;
                        amountIn: string;
                        minimumAmountOut: string;
                        data: string;
                        routePlan?: {
                            /** @constant */
                            version: 1;
                            /** @enum {string} */
                            executionContext: "helpers-core" | "helpers-market";
                            /** @enum {string} */
                            mode: "exactIn" | "exactOut";
                            tokenIn: string;
                            tokenOut: string;
                            branches: {
                                amountIn: string;
                                hops: {
                                    pool: components["schemas"]["RoutePoolRef"];
                                    zeroForOne: boolean;
                                }[];
                            }[];
                            inputAmount: string;
                            outputAmount: string;
                            limit: string;
                            deadline: string;
                        };
                    } & {
                        outputAsset: string;
                    }) | ({
                        adapter: string;
                        minimumAmountOut: string;
                        data: string;
                        routePlan?: {
                            /** @constant */
                            version: 1;
                            /** @enum {string} */
                            executionContext: "helpers-core" | "helpers-market";
                            /** @enum {string} */
                            mode: "exactIn" | "exactOut";
                            tokenIn: string;
                            tokenOut: string;
                            branches: {
                                amountIn: string;
                                hops: {
                                    pool: components["schemas"]["RoutePoolRef"];
                                    zeroForOne: boolean;
                                }[];
                            }[];
                            inputAmount: string;
                            outputAmount: string;
                            limit: string;
                            deadline: string;
                        };
                    } & {
                        inputAsset: string;
                        inputAmount: string;
                    }))[];
                    expectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        minimumAmount: string;
                    }[];
                };
            };
            providerQuote: {
                /** @enum {string} */
                mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                quotes: (({
                    adapter: string;
                    amountIn: string;
                    minimumAmountOut: string;
                    data: string;
                    routePlan?: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                } & {
                    outputAsset: string;
                }) | ({
                    adapter: string;
                    minimumAmountOut: string;
                    data: string;
                    routePlan?: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                } & {
                    inputAsset: string;
                    inputAmount: string;
                }))[];
                preview: {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    minimumAmountOut: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                };
                initialPreview: {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | {
                    grossCygldIn: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    minimumAmountOut: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | null;
                basketPreview: {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | {
                    grossCygldIn: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                };
                displayAmount: string;
                executionAmount: string;
                maximumInputAmount: string;
                slippageBps?: number;
                /** @description Expected input before execution cushions, including direct basket input. */
                expectedInputAmount?: string;
                requestedGrossCygldOut?: string;
                requestedNetCygldOut?: string;
                remainingGrossCapacity?: string;
                remainingNetCapacity?: string;
                expectedOutputAmount?: string;
                expectedCoreOutputs?: {
                    kind: number;
                    token: string;
                    id: string;
                    minimumAmount: string;
                }[];
                metrics: {
                    rpcReads: number;
                    rpcReadsRequested: number;
                    rpcReadsCoalesced: number;
                    rpcReadsReused: number;
                    /** @constant */
                    rpcReadsScope?: "coordinator";
                    candidateCalls: number;
                    iterations: number;
                    totalMs: number;
                } & {
                    firstQualifiedMs?: number;
                    selectionMs?: number;
                    canonicalCompletedMs?: number;
                    cleanupCompletedMs?: number;
                    finalizationMs?: number;
                };
                /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
                quoteDiagnostics?: {
                    /** @enum {string} */
                    phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                    elapsedMs?: number;
                    qualified?: boolean;
                    inversionIteration?: number;
                    routeWave?: {
                        elapsedMs?: number;
                        subphaseElapsedMs?: number;
                        /** @enum {string} */
                        subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                        /** @enum {string} */
                        mode?: "exact-in" | "exact-out";
                        legacyCandidates?: number;
                        legacyCompleted?: number;
                        typedEnumerated?: number;
                        typedCompleted?: number;
                        typedPending?: number;
                        sdkRequests?: number;
                        sdkWaiting?: number;
                        sdkLockWaitMs?: number;
                        sdkExchangeMs?: number;
                        legs?: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            count: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedRows: number;
                            rows: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                index: number;
                                inputAsset?: string;
                                outputAsset?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                amount?: string;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                started: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                succeeded: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                failed: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                cancelled: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                pending: number;
                                bestAvailable: boolean;
                                failureCounts: {
                                    code: components["schemas"]["QuoteErrorCode"];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    count: number;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedFailureCodes: number;
                                bestPools: {
                                    /** @enum {string} */
                                    protocol: "v2" | "v3" | "v4";
                                    /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                    poolId?: string;
                                    poolAddress?: string;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedPools: number;
                            }[];
                        };
                    };
                    providerQualifications?: {
                        /** @enum {string} */
                        provider: "core" | "market";
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempts: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        qualified: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        rejected: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        notImproved: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        cancelled: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        superseded: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        pending: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        selectedAttempt?: number;
                        /** @enum {string} */
                        selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        firstQualifiedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        selectionMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        canonicalCompletedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        cleanupCompletedMs?: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            attempt: number;
                            /** @enum {string} */
                            stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                            /** @enum {string} */
                            outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                            /** @enum {string} */
                            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            targetAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            minimumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountIn?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountIn?: string;
                            /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                            startedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            completedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            elapsedMs?: number;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            executionAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedInput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedOutput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            inputMaximum?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            outputMinimum?: string;
                            pools?: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools?: number;
                        }[];
                    };
                };
            };
        } & {
            providerAssessments?: components["schemas"]["TradeProviderAssessments"];
            providerCandidates?: {
                /** @description One complete provider plan, without recursive provider evidence maps. */
                core?: components["schemas"]["CoreTradeProviderCandidate"];
                market?: components["schemas"]["MarketTradeProviderCandidate"];
            };
        }) | ({
            /** @enum {string} */
            side: "buy" | "sell";
            /** @enum {string} */
            mode: "exact-in" | "exact-out";
            tokenIn: string;
            tokenOut: string;
            quotedInput: string;
            quotedOutput: string;
            inputMaximum: string;
            outputMinimum: string;
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            evaluation: components["schemas"]["TradeEvaluation"];
            metrics: {
                totalMs: number;
                targetReads: number;
            } & {
                firstQualifiedMs?: number;
                selectionMs?: number;
                canonicalCompletedMs?: number;
                cleanupCompletedMs?: number;
                finalizationMs?: number;
            };
        } & {
            /** @constant */
            strategy: "market";
            providerRequest: {
                /** @enum {string} */
                side: "buy" | "sell";
                /** @enum {string} */
                mode: "exact-in" | "exact-out";
                counterToken: string;
                amount: string;
                adapter?: string;
                recipient: string;
                deadline: string;
                slippageBps?: number;
                retainedPlan?: {
                    /** @enum {string} */
                    side: "buy" | "sell";
                    /** @enum {string} */
                    mode: "exact-in" | "exact-out";
                    amount: string;
                    slippageBps: number;
                    route: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                    params: {
                        /** @enum {number} */
                        side: 0 | 1;
                        counterToken: string;
                        amount: string;
                        bound: string;
                        routedInput: string;
                        feeCygld: string;
                        recipient: string;
                        deadline: string;
                        adapter: string;
                        data: string;
                    };
                    fee: {
                        asset: string;
                        ratePpm: number;
                        amount: string;
                        /** @constant */
                        basis: "quoted";
                        notional: string;
                    };
                };
            };
            providerQuote: {
                /** @constant */
                operation: "market";
                /** @enum {string} */
                side: "buy" | "sell";
                /** @enum {string} */
                mode: "exact-in" | "exact-out";
                tokenIn: string;
                tokenOut: string;
                amountIn: string;
                amountOut: string;
                totalInput: string;
                netOutput: string;
                grossOutput: string;
                routedAmountIn: string;
                inputMaximum: string;
                outputMinimum: string;
                refundDust: string;
                outputRefundEstimate?: string;
                fee: {
                    asset: string;
                    ratePpm: number;
                    amount: string;
                    /** @constant */
                    basis: "quoted";
                    notional: string;
                };
                params: {
                    /** @enum {number} */
                    side: 0 | 1;
                    counterToken: string;
                    amount: string;
                    bound: string;
                    routedInput: string;
                    feeCygld: string;
                    recipient: string;
                    deadline: string;
                    adapter: string;
                    data: string;
                };
                adapterData: string;
                plan: {
                    /** @enum {string} */
                    side: "buy" | "sell";
                    /** @enum {string} */
                    mode: "exact-in" | "exact-out";
                    amount: string;
                    slippageBps: number;
                    route: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                    params: {
                        /** @enum {number} */
                        side: 0 | 1;
                        counterToken: string;
                        amount: string;
                        bound: string;
                        routedInput: string;
                        feeCygld: string;
                        recipient: string;
                        deadline: string;
                        adapter: string;
                        data: string;
                    };
                    fee: {
                        asset: string;
                        ratePpm: number;
                        amount: string;
                        /** @constant */
                        basis: "quoted";
                        notional: string;
                    };
                };
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                feeBeneficiaryDisplay?: {
                    address: string;
                    observedAt: string;
                };
                /** @description AMM price impact excluding LP/protocol/application fees; absent without a coherent baseline. */
                priceImpactPpm?: string;
                /** @constant */
                qualification: "sdk";
                executionSimulationRequired?: boolean;
                quoteVerificationUnavailable?: string;
                searchCoverage?: {
                    /** @constant */
                    scope: "selected-inventory";
                    maxHops: number;
                    splitPercentages: number[];
                    inventoryPools: number;
                    catalogMonth: null | string;
                };
                metrics: {
                    candidateCalls: number;
                    totalMs: number;
                } & {
                    firstQualifiedMs?: number;
                    selectionMs?: number;
                    canonicalCompletedMs?: number;
                    cleanupCompletedMs?: number;
                    finalizationMs?: number;
                };
                /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
                quoteDiagnostics?: {
                    /** @enum {string} */
                    phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                    elapsedMs?: number;
                    qualified?: boolean;
                    inversionIteration?: number;
                    routeWave?: {
                        elapsedMs?: number;
                        subphaseElapsedMs?: number;
                        /** @enum {string} */
                        subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                        /** @enum {string} */
                        mode?: "exact-in" | "exact-out";
                        legacyCandidates?: number;
                        legacyCompleted?: number;
                        typedEnumerated?: number;
                        typedCompleted?: number;
                        typedPending?: number;
                        sdkRequests?: number;
                        sdkWaiting?: number;
                        sdkLockWaitMs?: number;
                        sdkExchangeMs?: number;
                        legs?: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            count: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedRows: number;
                            rows: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                index: number;
                                inputAsset?: string;
                                outputAsset?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                amount?: string;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                started: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                succeeded: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                failed: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                cancelled: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                pending: number;
                                bestAvailable: boolean;
                                failureCounts: {
                                    code: components["schemas"]["QuoteErrorCode"];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    count: number;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedFailureCodes: number;
                                bestPools: {
                                    /** @enum {string} */
                                    protocol: "v2" | "v3" | "v4";
                                    /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                    poolId?: string;
                                    poolAddress?: string;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedPools: number;
                            }[];
                        };
                    };
                    providerQualifications?: {
                        /** @enum {string} */
                        provider: "core" | "market";
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempts: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        qualified: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        rejected: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        notImproved: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        cancelled: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        superseded: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        pending: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        selectedAttempt?: number;
                        /** @enum {string} */
                        selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        firstQualifiedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        selectionMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        canonicalCompletedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        cleanupCompletedMs?: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            attempt: number;
                            /** @enum {string} */
                            stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                            /** @enum {string} */
                            outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                            /** @enum {string} */
                            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            targetAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            minimumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountIn?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountIn?: string;
                            /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                            startedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            completedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            elapsedMs?: number;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            executionAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedInput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedOutput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            inputMaximum?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            outputMinimum?: string;
                            pools?: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools?: number;
                        }[];
                    };
                };
            };
        } & {
            providerAssessments?: components["schemas"]["TradeProviderAssessments"];
            providerCandidates?: {
                /** @description One complete provider plan, without recursive provider evidence maps. */
                core?: components["schemas"]["CoreTradeProviderCandidate"];
                market?: components["schemas"]["MarketTradeProviderCandidate"];
            };
        });
        TradeEvaluation: {
            /** @enum {string} */
            core: "complete" | "running" | "unavailable" | "unsupported";
            /** @enum {string} */
            market: "complete" | "running" | "unavailable" | "unsupported";
        };
        TradeProviderAssessments: {
            core: {
                /** @enum {string} */
                availability: "not-run" | "pending" | "qualified" | "unavailable" | "unsupported";
                /** @enum {string} */
                searchOutcome: "cancelled" | "complete" | "error" | "not-run" | "running" | "timeout";
                error?: string;
                /** @enum {string} */
                code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                /** @description Canonical preview rejection evidence; absent quantities were not provided by the contract. */
                constraint?: {
                    /** @enum {string} */
                    kind?: "issuance-cap" | "redemption-capacity" | "redemption-supply";
                    /** @enum {string} */
                    quantity?: "core-output-minima" | "gross-cygld-input" | "gross-cygld-mint";
                    /** @enum {string} */
                    limitKind?: "effective-supply-cap" | "maximum-total-supply";
                    requestedRaw?: string;
                    availableRaw?: string;
                    currentSupplyRaw?: string;
                    limitRaw?: string;
                };
                /** @description Optional observed RPC failure context; provider text is sanitized before publication. */
                diagnostics?: {
                    rpcMethod?: string;
                    stage?: string;
                    elapsedMs?: number;
                    upstreamErrorCode?: number;
                    providerMessage?: string;
                    httpStatus?: number;
                    /** @enum {string} */
                    failureType?: "backend-deadline" | "http-error" | "provider-timeout" | "rpc-error" | "transport-error";
                    errorSelector?: string;
                    errorName?: string;
                };
                /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
                quoteDiagnostics?: {
                    /** @enum {string} */
                    phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                    elapsedMs?: number;
                    qualified?: boolean;
                    inversionIteration?: number;
                    routeWave?: {
                        elapsedMs?: number;
                        subphaseElapsedMs?: number;
                        /** @enum {string} */
                        subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                        /** @enum {string} */
                        mode?: "exact-in" | "exact-out";
                        legacyCandidates?: number;
                        legacyCompleted?: number;
                        typedEnumerated?: number;
                        typedCompleted?: number;
                        typedPending?: number;
                        sdkRequests?: number;
                        sdkWaiting?: number;
                        sdkLockWaitMs?: number;
                        sdkExchangeMs?: number;
                        legs?: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            count: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedRows: number;
                            rows: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                index: number;
                                inputAsset?: string;
                                outputAsset?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                amount?: string;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                started: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                succeeded: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                failed: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                cancelled: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                pending: number;
                                bestAvailable: boolean;
                                failureCounts: {
                                    code: components["schemas"]["QuoteErrorCode"];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    count: number;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedFailureCodes: number;
                                bestPools: {
                                    /** @enum {string} */
                                    protocol: "v2" | "v3" | "v4";
                                    /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                    poolId?: string;
                                    poolAddress?: string;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedPools: number;
                            }[];
                        };
                    };
                    providerQualifications?: {
                        /** @enum {string} */
                        provider: "core" | "market";
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempts: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        qualified: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        rejected: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        notImproved: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        cancelled: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        superseded: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        pending: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        selectedAttempt?: number;
                        /** @enum {string} */
                        selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        firstQualifiedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        selectionMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        canonicalCompletedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        cleanupCompletedMs?: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            attempt: number;
                            /** @enum {string} */
                            stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                            /** @enum {string} */
                            outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                            /** @enum {string} */
                            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            targetAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            minimumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountIn?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountIn?: string;
                            /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                            startedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            completedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            elapsedMs?: number;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            executionAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedInput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedOutput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            inputMaximum?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            outputMinimum?: string;
                            pools?: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools?: number;
                        }[];
                    };
                };
            };
            market: {
                /** @enum {string} */
                availability: "not-run" | "pending" | "qualified" | "unavailable" | "unsupported";
                /** @enum {string} */
                searchOutcome: "cancelled" | "complete" | "error" | "not-run" | "running" | "timeout";
                error?: string;
                /** @enum {string} */
                code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                /** @description Canonical preview rejection evidence; absent quantities were not provided by the contract. */
                constraint?: {
                    /** @enum {string} */
                    kind?: "issuance-cap" | "redemption-capacity" | "redemption-supply";
                    /** @enum {string} */
                    quantity?: "core-output-minima" | "gross-cygld-input" | "gross-cygld-mint";
                    /** @enum {string} */
                    limitKind?: "effective-supply-cap" | "maximum-total-supply";
                    requestedRaw?: string;
                    availableRaw?: string;
                    currentSupplyRaw?: string;
                    limitRaw?: string;
                };
                /** @description Optional observed RPC failure context; provider text is sanitized before publication. */
                diagnostics?: {
                    rpcMethod?: string;
                    stage?: string;
                    elapsedMs?: number;
                    upstreamErrorCode?: number;
                    providerMessage?: string;
                    httpStatus?: number;
                    /** @enum {string} */
                    failureType?: "backend-deadline" | "http-error" | "provider-timeout" | "rpc-error" | "transport-error";
                    errorSelector?: string;
                    errorName?: string;
                };
                /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
                quoteDiagnostics?: {
                    /** @enum {string} */
                    phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                    elapsedMs?: number;
                    qualified?: boolean;
                    inversionIteration?: number;
                    routeWave?: {
                        elapsedMs?: number;
                        subphaseElapsedMs?: number;
                        /** @enum {string} */
                        subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                        /** @enum {string} */
                        mode?: "exact-in" | "exact-out";
                        legacyCandidates?: number;
                        legacyCompleted?: number;
                        typedEnumerated?: number;
                        typedCompleted?: number;
                        typedPending?: number;
                        sdkRequests?: number;
                        sdkWaiting?: number;
                        sdkLockWaitMs?: number;
                        sdkExchangeMs?: number;
                        legs?: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            count: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedRows: number;
                            rows: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                index: number;
                                inputAsset?: string;
                                outputAsset?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                amount?: string;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                started: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                succeeded: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                failed: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                cancelled: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                pending: number;
                                bestAvailable: boolean;
                                failureCounts: {
                                    code: components["schemas"]["QuoteErrorCode"];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    count: number;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedFailureCodes: number;
                                bestPools: {
                                    /** @enum {string} */
                                    protocol: "v2" | "v3" | "v4";
                                    /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                    poolId?: string;
                                    poolAddress?: string;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedPools: number;
                            }[];
                        };
                    };
                    providerQualifications?: {
                        /** @enum {string} */
                        provider: "core" | "market";
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempts: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        qualified: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        rejected: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        notImproved: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        cancelled: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        superseded: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        pending: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        selectedAttempt?: number;
                        /** @enum {string} */
                        selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        firstQualifiedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        selectionMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        canonicalCompletedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        cleanupCompletedMs?: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            attempt: number;
                            /** @enum {string} */
                            stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                            /** @enum {string} */
                            outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                            /** @enum {string} */
                            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            targetAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            minimumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountIn?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountIn?: string;
                            /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                            startedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            completedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            elapsedMs?: number;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            executionAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedInput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedOutput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            inputMaximum?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            outputMinimum?: string;
                            pools?: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools?: number;
                        }[];
                    };
                };
            };
        };
        /** @description One complete provider plan, without recursive provider evidence maps. */
        CoreTradeProviderCandidate: {
            /** @enum {string} */
            side: "buy" | "sell";
            /** @enum {string} */
            mode: "exact-in" | "exact-out";
            tokenIn: string;
            tokenOut: string;
            quotedInput: string;
            quotedOutput: string;
            inputMaximum: string;
            outputMinimum: string;
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            evaluation: components["schemas"]["TradeEvaluation"];
            metrics: {
                totalMs: number;
                targetReads: number;
            } & {
                firstQualifiedMs?: number;
                selectionMs?: number;
                canonicalCompletedMs?: number;
                cleanupCompletedMs?: number;
                finalizationMs?: number;
            };
        } & {
            /** @constant */
            strategy: "core";
            providerRequest: {
                /** @enum {string} */
                mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
                token: string;
                quoteToken: string;
                native: boolean;
                amount: string;
                adapter?: string;
                deadline: string;
                orderedAssets: string[];
                targets: {
                    inputAsset: string;
                    outputAsset: string;
                    amount: string;
                }[];
                /**
                 * @description Execution tolerance in basis points; omitted defaults to 100 (1%).
                 * @default 100
                 */
                slippageBps: number;
                retainedPlan?: {
                    slippageBps?: number;
                    expectedInputAmount?: string;
                    executionAmount: string;
                    maximumInputAmount: string;
                    minimumAmountOut: string;
                    quotes: (({
                        adapter: string;
                        amountIn: string;
                        minimumAmountOut: string;
                        data: string;
                        routePlan?: {
                            /** @constant */
                            version: 1;
                            /** @enum {string} */
                            executionContext: "helpers-core" | "helpers-market";
                            /** @enum {string} */
                            mode: "exactIn" | "exactOut";
                            tokenIn: string;
                            tokenOut: string;
                            branches: {
                                amountIn: string;
                                hops: {
                                    pool: components["schemas"]["RoutePoolRef"];
                                    zeroForOne: boolean;
                                }[];
                            }[];
                            inputAmount: string;
                            outputAmount: string;
                            limit: string;
                            deadline: string;
                        };
                    } & {
                        outputAsset: string;
                    }) | ({
                        adapter: string;
                        minimumAmountOut: string;
                        data: string;
                        routePlan?: {
                            /** @constant */
                            version: 1;
                            /** @enum {string} */
                            executionContext: "helpers-core" | "helpers-market";
                            /** @enum {string} */
                            mode: "exactIn" | "exactOut";
                            tokenIn: string;
                            tokenOut: string;
                            branches: {
                                amountIn: string;
                                hops: {
                                    pool: components["schemas"]["RoutePoolRef"];
                                    zeroForOne: boolean;
                                }[];
                            }[];
                            inputAmount: string;
                            outputAmount: string;
                            limit: string;
                            deadline: string;
                        };
                    } & {
                        inputAsset: string;
                        inputAmount: string;
                    }))[];
                    expectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        minimumAmount: string;
                    }[];
                };
            };
            providerQuote: {
                /** @enum {string} */
                mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                quotes: (({
                    adapter: string;
                    amountIn: string;
                    minimumAmountOut: string;
                    data: string;
                    routePlan?: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                } & {
                    outputAsset: string;
                }) | ({
                    adapter: string;
                    minimumAmountOut: string;
                    data: string;
                    routePlan?: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                } & {
                    inputAsset: string;
                    inputAmount: string;
                }))[];
                preview: {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    minimumAmountOut: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                };
                initialPreview: {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | {
                    grossCygldIn: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    minimumAmountOut: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | null;
                basketPreview: {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | {
                    grossCygldIn: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                };
                displayAmount: string;
                executionAmount: string;
                maximumInputAmount: string;
                slippageBps?: number;
                /** @description Expected input before execution cushions, including direct basket input. */
                expectedInputAmount?: string;
                requestedGrossCygldOut?: string;
                requestedNetCygldOut?: string;
                remainingGrossCapacity?: string;
                remainingNetCapacity?: string;
                expectedOutputAmount?: string;
                expectedCoreOutputs?: {
                    kind: number;
                    token: string;
                    id: string;
                    minimumAmount: string;
                }[];
                metrics: {
                    rpcReads: number;
                    rpcReadsRequested: number;
                    rpcReadsCoalesced: number;
                    rpcReadsReused: number;
                    /** @constant */
                    rpcReadsScope?: "coordinator";
                    candidateCalls: number;
                    iterations: number;
                    totalMs: number;
                } & {
                    firstQualifiedMs?: number;
                    selectionMs?: number;
                    canonicalCompletedMs?: number;
                    cleanupCompletedMs?: number;
                    finalizationMs?: number;
                };
                /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
                quoteDiagnostics?: {
                    /** @enum {string} */
                    phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                    elapsedMs?: number;
                    qualified?: boolean;
                    inversionIteration?: number;
                    routeWave?: {
                        elapsedMs?: number;
                        subphaseElapsedMs?: number;
                        /** @enum {string} */
                        subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                        /** @enum {string} */
                        mode?: "exact-in" | "exact-out";
                        legacyCandidates?: number;
                        legacyCompleted?: number;
                        typedEnumerated?: number;
                        typedCompleted?: number;
                        typedPending?: number;
                        sdkRequests?: number;
                        sdkWaiting?: number;
                        sdkLockWaitMs?: number;
                        sdkExchangeMs?: number;
                        legs?: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            count: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedRows: number;
                            rows: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                index: number;
                                inputAsset?: string;
                                outputAsset?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                amount?: string;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                started: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                succeeded: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                failed: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                cancelled: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                pending: number;
                                bestAvailable: boolean;
                                failureCounts: {
                                    code: components["schemas"]["QuoteErrorCode"];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    count: number;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedFailureCodes: number;
                                bestPools: {
                                    /** @enum {string} */
                                    protocol: "v2" | "v3" | "v4";
                                    /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                    poolId?: string;
                                    poolAddress?: string;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedPools: number;
                            }[];
                        };
                    };
                    providerQualifications?: {
                        /** @enum {string} */
                        provider: "core" | "market";
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempts: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        qualified: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        rejected: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        notImproved: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        cancelled: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        superseded: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        pending: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        selectedAttempt?: number;
                        /** @enum {string} */
                        selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        firstQualifiedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        selectionMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        canonicalCompletedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        cleanupCompletedMs?: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            attempt: number;
                            /** @enum {string} */
                            stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                            /** @enum {string} */
                            outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                            /** @enum {string} */
                            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            targetAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            minimumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountIn?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountIn?: string;
                            /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                            startedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            completedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            elapsedMs?: number;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            executionAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedInput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedOutput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            inputMaximum?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            outputMinimum?: string;
                            pools?: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools?: number;
                        }[];
                    };
                };
            };
        };
        MarketTradeProviderCandidate: {
            /** @enum {string} */
            side: "buy" | "sell";
            /** @enum {string} */
            mode: "exact-in" | "exact-out";
            tokenIn: string;
            tokenOut: string;
            quotedInput: string;
            quotedOutput: string;
            inputMaximum: string;
            outputMinimum: string;
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            evaluation: components["schemas"]["TradeEvaluation"];
            metrics: {
                totalMs: number;
                targetReads: number;
            } & {
                firstQualifiedMs?: number;
                selectionMs?: number;
                canonicalCompletedMs?: number;
                cleanupCompletedMs?: number;
                finalizationMs?: number;
            };
        } & {
            /** @constant */
            strategy: "market";
            providerRequest: {
                /** @enum {string} */
                side: "buy" | "sell";
                /** @enum {string} */
                mode: "exact-in" | "exact-out";
                counterToken: string;
                amount: string;
                adapter?: string;
                recipient: string;
                deadline: string;
                slippageBps?: number;
                retainedPlan?: {
                    /** @enum {string} */
                    side: "buy" | "sell";
                    /** @enum {string} */
                    mode: "exact-in" | "exact-out";
                    amount: string;
                    slippageBps: number;
                    route: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                    params: {
                        /** @enum {number} */
                        side: 0 | 1;
                        counterToken: string;
                        amount: string;
                        bound: string;
                        routedInput: string;
                        feeCygld: string;
                        recipient: string;
                        deadline: string;
                        adapter: string;
                        data: string;
                    };
                    fee: {
                        asset: string;
                        ratePpm: number;
                        amount: string;
                        /** @constant */
                        basis: "quoted";
                        notional: string;
                    };
                };
            };
            providerQuote: {
                /** @constant */
                operation: "market";
                /** @enum {string} */
                side: "buy" | "sell";
                /** @enum {string} */
                mode: "exact-in" | "exact-out";
                tokenIn: string;
                tokenOut: string;
                amountIn: string;
                amountOut: string;
                totalInput: string;
                netOutput: string;
                grossOutput: string;
                routedAmountIn: string;
                inputMaximum: string;
                outputMinimum: string;
                refundDust: string;
                outputRefundEstimate?: string;
                fee: {
                    asset: string;
                    ratePpm: number;
                    amount: string;
                    /** @constant */
                    basis: "quoted";
                    notional: string;
                };
                params: {
                    /** @enum {number} */
                    side: 0 | 1;
                    counterToken: string;
                    amount: string;
                    bound: string;
                    routedInput: string;
                    feeCygld: string;
                    recipient: string;
                    deadline: string;
                    adapter: string;
                    data: string;
                };
                adapterData: string;
                plan: {
                    /** @enum {string} */
                    side: "buy" | "sell";
                    /** @enum {string} */
                    mode: "exact-in" | "exact-out";
                    amount: string;
                    slippageBps: number;
                    route: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                    params: {
                        /** @enum {number} */
                        side: 0 | 1;
                        counterToken: string;
                        amount: string;
                        bound: string;
                        routedInput: string;
                        feeCygld: string;
                        recipient: string;
                        deadline: string;
                        adapter: string;
                        data: string;
                    };
                    fee: {
                        asset: string;
                        ratePpm: number;
                        amount: string;
                        /** @constant */
                        basis: "quoted";
                        notional: string;
                    };
                };
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                feeBeneficiaryDisplay?: {
                    address: string;
                    observedAt: string;
                };
                /** @description AMM price impact excluding LP/protocol/application fees; absent without a coherent baseline. */
                priceImpactPpm?: string;
                /** @constant */
                qualification: "sdk";
                executionSimulationRequired?: boolean;
                quoteVerificationUnavailable?: string;
                searchCoverage?: {
                    /** @constant */
                    scope: "selected-inventory";
                    maxHops: number;
                    splitPercentages: number[];
                    inventoryPools: number;
                    catalogMonth: null | string;
                };
                metrics: {
                    candidateCalls: number;
                    totalMs: number;
                } & {
                    firstQualifiedMs?: number;
                    selectionMs?: number;
                    canonicalCompletedMs?: number;
                    cleanupCompletedMs?: number;
                    finalizationMs?: number;
                };
                /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
                quoteDiagnostics?: {
                    /** @enum {string} */
                    phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                    elapsedMs?: number;
                    qualified?: boolean;
                    inversionIteration?: number;
                    routeWave?: {
                        elapsedMs?: number;
                        subphaseElapsedMs?: number;
                        /** @enum {string} */
                        subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                        /** @enum {string} */
                        mode?: "exact-in" | "exact-out";
                        legacyCandidates?: number;
                        legacyCompleted?: number;
                        typedEnumerated?: number;
                        typedCompleted?: number;
                        typedPending?: number;
                        sdkRequests?: number;
                        sdkWaiting?: number;
                        sdkLockWaitMs?: number;
                        sdkExchangeMs?: number;
                        legs?: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            count: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedRows: number;
                            rows: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                index: number;
                                inputAsset?: string;
                                outputAsset?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                amount?: string;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                started: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                succeeded: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                failed: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                cancelled: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                pending: number;
                                bestAvailable: boolean;
                                failureCounts: {
                                    code: components["schemas"]["QuoteErrorCode"];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    count: number;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedFailureCodes: number;
                                bestPools: {
                                    /** @enum {string} */
                                    protocol: "v2" | "v3" | "v4";
                                    /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                    poolId?: string;
                                    poolAddress?: string;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedPools: number;
                            }[];
                        };
                    };
                    providerQualifications?: {
                        /** @enum {string} */
                        provider: "core" | "market";
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempts: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        qualified: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        rejected: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        notImproved: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        cancelled: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        superseded: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        pending: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        selectedAttempt?: number;
                        /** @enum {string} */
                        selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        firstQualifiedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        selectionMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        canonicalCompletedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        cleanupCompletedMs?: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            attempt: number;
                            /** @enum {string} */
                            stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                            /** @enum {string} */
                            outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                            /** @enum {string} */
                            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            targetAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            minimumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountIn?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountIn?: string;
                            /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                            startedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            completedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            elapsedMs?: number;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            executionAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedInput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedOutput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            inputMaximum?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            outputMinimum?: string;
                            pools?: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools?: number;
                        }[];
                    };
                };
            };
        };
        TradeProviderCandidate: components["schemas"]["CoreTradeProviderCandidate"] | components["schemas"]["MarketTradeProviderCandidate"];
        TradeQuoteEvent: ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "model";
            value: {
                /** @constant */
                namespace: "trade";
                /** @description One user trade; Backend chooses a complete Core or market execution. */
                intent: {
                    /** @enum {string} */
                    side: "buy" | "sell";
                    /** @enum {string} */
                    mode: "exact-in" | "exact-out";
                    counterToken: string;
                    native: boolean;
                    amount: string;
                    slippageBps?: number;
                };
                models: ({
                    /** @constant */
                    strategy: "core";
                    /** @description Display-only source data. No transaction tuples or execution readiness. */
                    value: {
                        revision: number;
                        intent: components["schemas"]["Omit<QuoteIntentRequest,\"deadline\"|\"retainedPlan\">"];
                        routes: {
                            tokens: string[];
                            fees: number[];
                            context: {
                                chainId: number;
                                blockNumber: string;
                                blockHash: string;
                                observedAt: string;
                            };
                            routePlan?: {
                                /** @constant */
                                version: 1;
                                /** @enum {string} */
                                executionContext: "helpers-core" | "helpers-market";
                                /** @enum {string} */
                                mode: "exactIn" | "exactOut";
                                tokenIn: string;
                                tokenOut: string;
                                branches: {
                                    amountIn: string;
                                    hops: {
                                        pool: components["schemas"]["RoutePoolRef"];
                                        zeroForOne: boolean;
                                    }[];
                                }[];
                                inputAmount: string;
                                outputAmount: string;
                                limit: string;
                                deadline: string;
                            };
                            protocols?: ("v2" | "v3" | "v4")[];
                            poolIds?: string[];
                            points: {
                                input: string;
                                output: string;
                                context?: {
                                    chainId: number;
                                    blockNumber: string;
                                    blockHash: string;
                                    observedAt: string;
                                };
                                recordedAt?: number;
                            }[];
                            exchangeRate?: {
                                numerator: string;
                                denominator: string;
                            };
                            exchangeContext?: {
                                chainId: number;
                                blockNumber: string;
                                blockHash: string;
                                observedAt: string;
                            };
                            feeRetention: {
                                numerator: string;
                                denominator: string;
                            };
                            localImpact?: {
                                numerator: string;
                                denominator: string;
                            };
                        }[];
                        whole: {
                            input: string;
                            display: string;
                            context: {
                                chainId: number;
                                blockNumber: string;
                                blockHash: string;
                                observedAt: string;
                            };
                            recordedAt: number;
                        }[];
                        protocol: {
                            context: {
                                chainId: number;
                                blockNumber: string;
                                blockHash: string;
                                observedAt: string;
                            };
                            state: {
                                assets: string[];
                                weights: string[];
                                conversions: string[];
                                issueFee: string;
                                helperFee: string;
                                redeemFee: string;
                                supply: string;
                                maxSupply: string;
                                effectiveCap: string;
                                available: string[];
                                recoveryShares: string[];
                                recoveryValues: string[];
                                descriptors: {
                                    kind: number;
                                    token: string;
                                    id: string;
                                }[];
                            };
                        } | null;
                    };
                } | {
                    /** @constant */
                    strategy: "market";
                    value: {
                        /** @constant */
                        namespace: "market";
                        family: string;
                        context?: {
                            chainId: number;
                            blockNumber: string;
                            blockHash: string;
                            observedAt: string;
                        };
                        intent: {
                            /** @enum {string} */
                            side: "buy" | "sell";
                            /** @enum {string} */
                            mode: "exact-in" | "exact-out";
                            counterToken: string;
                            adapter: string;
                        };
                        cygld: string;
                        feeRatePpm: number;
                        routes: {
                            route: {
                                /** @constant */
                                version: 1;
                                /** @enum {string} */
                                executionContext: "helpers-core" | "helpers-market";
                                /** @enum {string} */
                                mode: "exactIn" | "exactOut";
                                tokenIn: string;
                                tokenOut: string;
                                branches: {
                                    amountIn: string;
                                    hops: {
                                        pool: components["schemas"]["RoutePoolRef"];
                                        zeroForOne: boolean;
                                    }[];
                                }[];
                                inputAmount: string;
                                outputAmount: string;
                                limit: string;
                                deadline: string;
                            };
                            amountIn: string;
                            amountOut: string;
                            sourceObservations?: {
                                poolId: string;
                                context: {
                                    chainId: number;
                                    blockNumber: string;
                                    blockHash: string;
                                    observedAt: string;
                                };
                            }[];
                            sourceContext?: {
                                chainId: number;
                                blockNumber: string;
                                blockHash: string;
                                observedAt: string;
                            } | null;
                            points: {
                                amountIn: string;
                                amountOut: string;
                                context?: {
                                    chainId: number;
                                    blockNumber: string;
                                    blockHash: string;
                                    observedAt: string;
                                };
                                requestedAmount?: string;
                                family?: string;
                                feeRatePpm?: number;
                                routeIdentity?: string;
                            }[];
                            exchangeRate?: {
                                numerator: string;
                                denominator: string;
                            };
                            feeRetention?: {
                                numerator: string;
                                denominator: string;
                            };
                            localImpact?: {
                                numerator: string;
                                denominator: string;
                            };
                        }[];
                    };
                })[];
                estimate?: {
                    /** @enum {string} */
                    strategy: "core" | "market";
                    amount: string;
                } | {
                    /** @constant */
                    strategy: "universal";
                    amount: string;
                    /** @constant */
                    source: "cached-upper";
                    referenceInput: string;
                    /** @enum {string} */
                    basis: "funded-input-approximation" | "market-sale-consumed" | "observed-nonretained";
                    fees: {
                        coreProtocolFeeCygld: string;
                        coreHelpersFeeCygld: string;
                        marketFeeCygld: string;
                    };
                    context: {
                        chainId: number;
                        blockNumber: string;
                        blockHash: string;
                        observedAt: string;
                    };
                    sourceIdentity?: string;
                    sourceRequestedInput?: string;
                };
                /** @description Display-only economics of a Backend-selected quote. An absent maximumBudget means no upper budget bound. */
                budgetRange?: {
                    minimumBudget: string;
                    maximumBudget?: string;
                    quotedInput: string;
                    quotedOutput: string;
                };
            };
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "estimate";
            /** @enum {string} */
            strategy: "core" | "market";
            amount: string;
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @enum {string} */
            type: "complete" | "qualified";
            value: {
                /** @constant */
                strategy: "universal";
                /** @enum {string} */
                routeFamily: "core" | "market" | "mixed";
                /** @constant */
                operation: "executeExactInput";
                /** @constant */
                settlementPolicy: "protocol-retained-input";
                plan: components["schemas"]["UniversalExactInputPlan"];
                planDescription: components["schemas"]["Record<string,unknown>"];
                economicQuote?: components["schemas"]["EconomicQuote"];
                inputs: {
                    currency: string;
                    amount: string;
                }[];
                quotedInput?: string;
                inputMaximum?: string;
                quotedOutput: string;
                outputMinimum: string;
                estimatedRetainedInputCharges: {
                    branch: number;
                    stage: number;
                    currency: string;
                    amount: string;
                }[];
                estimatedRecipientOutputs: {
                    kind: number;
                    token: string;
                    id: string;
                    amount: string;
                }[];
                fees: {
                    coreProtocolFeeCygld: string;
                    coreHelpersFeeCygld: string;
                    marketFeeCygld: string;
                };
                recoveryShares: {
                    kind: number;
                    token: string;
                    id: string;
                    amount: string;
                }[];
                deployment: {
                    helpers: string;
                    adapter: string;
                    /** @constant */
                    encoding: "uniswap-routing-v1";
                };
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                retentionDisclosure: {
                    custodian: string;
                    /** @constant */
                    beneficiary: "helpers-owner-at-settlement";
                };
                searchCoverage: {
                    coreSharesPercent: number[];
                    orders: string[];
                    maxCoreInvocations: number;
                    maxAmmHops: number;
                    /** @constant */
                    scope: "selected-inventory";
                    /** @enum {string} */
                    selectedPhase?: "backward-prefix" | "capacity-limited" | "detailed" | "first-result" | "nearby-lower" | "nearby-upper" | "route-family" | "route-family-exploration" | "saved-plan";
                };
                /** @description Producer clocks, distinct from client request or browser journey duration. */
                metrics?: {
                    firstQualifiedMs?: number;
                    selectionMs?: number;
                    canonicalCompletedMs?: number;
                    cleanupCompletedMs?: number;
                    finalizationMs?: number;
                } & {
                    totalMs: number;
                    timeToFirstWholePlanMs: null | number;
                    searchMs: null | number;
                    selectionReason: ("best-initial" | "complete" | "first-extension" | "timeout") | null;
                    nearbySearch?: {
                        starts: number;
                        completed: number;
                        sources: {
                            /** @enum {string} */
                            side: "lower" | "upper";
                            identity?: null | string;
                            /** @enum {string} */
                            referenceBasis?: "funded-input-approximation" | "market-sale-consumed" | "observed-nonretained";
                            attempts: {
                                funding: string;
                                completed?: boolean;
                                elapsedMs: number;
                                /** @enum {string} */
                                failureCode?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                            }[];
                            /** @enum {string} */
                            failureCode?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        }[];
                    };
                };
            } | ({
                /** @enum {string} */
                side: "buy" | "sell";
                /** @enum {string} */
                mode: "exact-in" | "exact-out";
                tokenIn: string;
                tokenOut: string;
                quotedInput: string;
                quotedOutput: string;
                inputMaximum: string;
                outputMinimum: string;
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                evaluation: components["schemas"]["TradeEvaluation"];
                metrics: {
                    totalMs: number;
                    targetReads: number;
                } & {
                    firstQualifiedMs?: number;
                    selectionMs?: number;
                    canonicalCompletedMs?: number;
                    cleanupCompletedMs?: number;
                    finalizationMs?: number;
                };
            } & {
                /** @constant */
                strategy: "core";
                providerRequest: {
                    /** @enum {string} */
                    mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
                    token: string;
                    quoteToken: string;
                    native: boolean;
                    amount: string;
                    adapter?: string;
                    deadline: string;
                    orderedAssets: string[];
                    targets: {
                        inputAsset: string;
                        outputAsset: string;
                        amount: string;
                    }[];
                    /**
                     * @description Execution tolerance in basis points; omitted defaults to 100 (1%).
                     * @default 100
                     */
                    slippageBps: number;
                    retainedPlan?: {
                        slippageBps?: number;
                        expectedInputAmount?: string;
                        executionAmount: string;
                        maximumInputAmount: string;
                        minimumAmountOut: string;
                        quotes: (({
                            adapter: string;
                            amountIn: string;
                            minimumAmountOut: string;
                            data: string;
                            routePlan?: {
                                /** @constant */
                                version: 1;
                                /** @enum {string} */
                                executionContext: "helpers-core" | "helpers-market";
                                /** @enum {string} */
                                mode: "exactIn" | "exactOut";
                                tokenIn: string;
                                tokenOut: string;
                                branches: {
                                    amountIn: string;
                                    hops: {
                                        pool: components["schemas"]["RoutePoolRef"];
                                        zeroForOne: boolean;
                                    }[];
                                }[];
                                inputAmount: string;
                                outputAmount: string;
                                limit: string;
                                deadline: string;
                            };
                        } & {
                            outputAsset: string;
                        }) | ({
                            adapter: string;
                            minimumAmountOut: string;
                            data: string;
                            routePlan?: {
                                /** @constant */
                                version: 1;
                                /** @enum {string} */
                                executionContext: "helpers-core" | "helpers-market";
                                /** @enum {string} */
                                mode: "exactIn" | "exactOut";
                                tokenIn: string;
                                tokenOut: string;
                                branches: {
                                    amountIn: string;
                                    hops: {
                                        pool: components["schemas"]["RoutePoolRef"];
                                        zeroForOne: boolean;
                                    }[];
                                }[];
                                inputAmount: string;
                                outputAmount: string;
                                limit: string;
                                deadline: string;
                            };
                        } & {
                            inputAsset: string;
                            inputAmount: string;
                        }))[];
                        expectedCoreOutputs: {
                            kind: number;
                            token: string;
                            id: string;
                            minimumAmount: string;
                        }[];
                    };
                };
                providerQuote: {
                    /** @enum {string} */
                    mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
                    context: {
                        chainId: number;
                        blockNumber: string;
                        blockHash: string;
                        observedAt: string;
                    };
                    quotes: (({
                        adapter: string;
                        amountIn: string;
                        minimumAmountOut: string;
                        data: string;
                        routePlan?: {
                            /** @constant */
                            version: 1;
                            /** @enum {string} */
                            executionContext: "helpers-core" | "helpers-market";
                            /** @enum {string} */
                            mode: "exactIn" | "exactOut";
                            tokenIn: string;
                            tokenOut: string;
                            branches: {
                                amountIn: string;
                                hops: {
                                    pool: components["schemas"]["RoutePoolRef"];
                                    zeroForOne: boolean;
                                }[];
                            }[];
                            inputAmount: string;
                            outputAmount: string;
                            limit: string;
                            deadline: string;
                        };
                    } & {
                        outputAsset: string;
                    }) | ({
                        adapter: string;
                        minimumAmountOut: string;
                        data: string;
                        routePlan?: {
                            /** @constant */
                            version: 1;
                            /** @enum {string} */
                            executionContext: "helpers-core" | "helpers-market";
                            /** @enum {string} */
                            mode: "exactIn" | "exactOut";
                            tokenIn: string;
                            tokenOut: string;
                            branches: {
                                amountIn: string;
                                hops: {
                                    pool: components["schemas"]["RoutePoolRef"];
                                    zeroForOne: boolean;
                                }[];
                            }[];
                            inputAmount: string;
                            outputAmount: string;
                            limit: string;
                            deadline: string;
                        };
                    } & {
                        inputAsset: string;
                        inputAmount: string;
                    }))[];
                    preview: {
                        netCygldOut: string;
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        orderedCoreAssets: string[];
                    } | {
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        orderedCoreAssets: string[];
                    } | {
                        minimumAmountOut: string;
                        projectedCoreOutputs: {
                            kind: number;
                            token: string;
                            id: string;
                            amount: string;
                        }[];
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                    };
                    initialPreview: {
                        netCygldOut: string;
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        amountsInExact: string[];
                        orderedCoreAssets: string[];
                    } | {
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        amountsInExact: string[];
                        orderedCoreAssets: string[];
                    } | {
                        projectedCoreOutputs: {
                            kind: number;
                            token: string;
                            id: string;
                            amount: string;
                        }[];
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                    } | {
                        grossCygldIn: string;
                        projectedCoreOutputs: {
                            kind: number;
                            token: string;
                            id: string;
                            amount: string;
                        }[];
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                    } | {
                        netCygldOut: string;
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        orderedCoreAssets: string[];
                    } | {
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        orderedCoreAssets: string[];
                    } | {
                        minimumAmountOut: string;
                        projectedCoreOutputs: {
                            kind: number;
                            token: string;
                            id: string;
                            amount: string;
                        }[];
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                    } | null;
                    basketPreview: {
                        netCygldOut: string;
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        amountsInExact: string[];
                        orderedCoreAssets: string[];
                    } | {
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                        amountsInExact: string[];
                        orderedCoreAssets: string[];
                    } | {
                        projectedCoreOutputs: {
                            kind: number;
                            token: string;
                            id: string;
                            amount: string;
                        }[];
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                    } | {
                        grossCygldIn: string;
                        projectedCoreOutputs: {
                            kind: number;
                            token: string;
                            id: string;
                            amount: string;
                        }[];
                        fees: {
                            protocolFeeCygld: string;
                            helperFeeCygld: string;
                        };
                    };
                    displayAmount: string;
                    executionAmount: string;
                    maximumInputAmount: string;
                    slippageBps?: number;
                    /** @description Expected input before execution cushions, including direct basket input. */
                    expectedInputAmount?: string;
                    requestedGrossCygldOut?: string;
                    requestedNetCygldOut?: string;
                    remainingGrossCapacity?: string;
                    remainingNetCapacity?: string;
                    expectedOutputAmount?: string;
                    expectedCoreOutputs?: {
                        kind: number;
                        token: string;
                        id: string;
                        minimumAmount: string;
                    }[];
                    metrics: {
                        rpcReads: number;
                        rpcReadsRequested: number;
                        rpcReadsCoalesced: number;
                        rpcReadsReused: number;
                        /** @constant */
                        rpcReadsScope?: "coordinator";
                        candidateCalls: number;
                        iterations: number;
                        totalMs: number;
                    } & {
                        firstQualifiedMs?: number;
                        selectionMs?: number;
                        canonicalCompletedMs?: number;
                        cleanupCompletedMs?: number;
                        finalizationMs?: number;
                    };
                    /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
                    quoteDiagnostics?: {
                        /** @enum {string} */
                        phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                        elapsedMs?: number;
                        qualified?: boolean;
                        inversionIteration?: number;
                        routeWave?: {
                            elapsedMs?: number;
                            subphaseElapsedMs?: number;
                            /** @enum {string} */
                            subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                            /** @enum {string} */
                            mode?: "exact-in" | "exact-out";
                            legacyCandidates?: number;
                            legacyCompleted?: number;
                            typedEnumerated?: number;
                            typedCompleted?: number;
                            typedPending?: number;
                            sdkRequests?: number;
                            sdkWaiting?: number;
                            sdkLockWaitMs?: number;
                            sdkExchangeMs?: number;
                            legs?: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                count: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedRows: number;
                                rows: {
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    index: number;
                                    inputAsset?: string;
                                    outputAsset?: string;
                                    /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                    amount?: string;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    started: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    succeeded: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    failed: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    cancelled: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    pending: number;
                                    bestAvailable: boolean;
                                    failureCounts: {
                                        code: components["schemas"]["QuoteErrorCode"];
                                        /** @description Bounded observation count; never an execution eligibility predicate. */
                                        count: number;
                                    }[];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    omittedFailureCodes: number;
                                    bestPools: {
                                        /** @enum {string} */
                                        protocol: "v2" | "v3" | "v4";
                                        /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                        poolId?: string;
                                        poolAddress?: string;
                                    }[];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    omittedPools: number;
                                }[];
                            };
                        };
                        providerQualifications?: {
                            /** @enum {string} */
                            provider: "core" | "market";
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            attempts: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            qualified: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            rejected: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            notImproved: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            cancelled: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            superseded: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            pending: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedRows: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            selectedAttempt?: number;
                            /** @enum {string} */
                            selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            firstQualifiedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            selectionMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            canonicalCompletedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            cleanupCompletedMs?: number;
                            rows: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                attempt: number;
                                /** @enum {string} */
                                stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                                /** @enum {string} */
                                outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                                /** @enum {string} */
                                code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                targetAmount?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                minimumAmountOut?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                maximumAmountOut?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                observedAmountOut?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                maximumAmountIn?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                observedAmountIn?: string;
                                /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                                startedMs?: number;
                                /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                                completedMs?: number;
                                /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                                elapsedMs?: number;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                executionAmount?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                quotedInput?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                quotedOutput?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                inputMaximum?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                outputMinimum?: string;
                                pools?: {
                                    /** @enum {string} */
                                    protocol: "v2" | "v3" | "v4";
                                    /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                    poolId?: string;
                                    poolAddress?: string;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedPools?: number;
                            }[];
                        };
                    };
                };
            } & {
                providerAssessments?: components["schemas"]["TradeProviderAssessments"];
                providerCandidates?: {
                    /** @description One complete provider plan, without recursive provider evidence maps. */
                    core?: components["schemas"]["CoreTradeProviderCandidate"];
                    market?: components["schemas"]["MarketTradeProviderCandidate"];
                };
            }) | ({
                /** @enum {string} */
                side: "buy" | "sell";
                /** @enum {string} */
                mode: "exact-in" | "exact-out";
                tokenIn: string;
                tokenOut: string;
                quotedInput: string;
                quotedOutput: string;
                inputMaximum: string;
                outputMinimum: string;
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                evaluation: components["schemas"]["TradeEvaluation"];
                metrics: {
                    totalMs: number;
                    targetReads: number;
                } & {
                    firstQualifiedMs?: number;
                    selectionMs?: number;
                    canonicalCompletedMs?: number;
                    cleanupCompletedMs?: number;
                    finalizationMs?: number;
                };
            } & {
                /** @constant */
                strategy: "market";
                providerRequest: {
                    /** @enum {string} */
                    side: "buy" | "sell";
                    /** @enum {string} */
                    mode: "exact-in" | "exact-out";
                    counterToken: string;
                    amount: string;
                    adapter?: string;
                    recipient: string;
                    deadline: string;
                    slippageBps?: number;
                    retainedPlan?: {
                        /** @enum {string} */
                        side: "buy" | "sell";
                        /** @enum {string} */
                        mode: "exact-in" | "exact-out";
                        amount: string;
                        slippageBps: number;
                        route: {
                            /** @constant */
                            version: 1;
                            /** @enum {string} */
                            executionContext: "helpers-core" | "helpers-market";
                            /** @enum {string} */
                            mode: "exactIn" | "exactOut";
                            tokenIn: string;
                            tokenOut: string;
                            branches: {
                                amountIn: string;
                                hops: {
                                    pool: components["schemas"]["RoutePoolRef"];
                                    zeroForOne: boolean;
                                }[];
                            }[];
                            inputAmount: string;
                            outputAmount: string;
                            limit: string;
                            deadline: string;
                        };
                        params: {
                            /** @enum {number} */
                            side: 0 | 1;
                            counterToken: string;
                            amount: string;
                            bound: string;
                            routedInput: string;
                            feeCygld: string;
                            recipient: string;
                            deadline: string;
                            adapter: string;
                            data: string;
                        };
                        fee: {
                            asset: string;
                            ratePpm: number;
                            amount: string;
                            /** @constant */
                            basis: "quoted";
                            notional: string;
                        };
                    };
                };
                providerQuote: {
                    /** @constant */
                    operation: "market";
                    /** @enum {string} */
                    side: "buy" | "sell";
                    /** @enum {string} */
                    mode: "exact-in" | "exact-out";
                    tokenIn: string;
                    tokenOut: string;
                    amountIn: string;
                    amountOut: string;
                    totalInput: string;
                    netOutput: string;
                    grossOutput: string;
                    routedAmountIn: string;
                    inputMaximum: string;
                    outputMinimum: string;
                    refundDust: string;
                    outputRefundEstimate?: string;
                    fee: {
                        asset: string;
                        ratePpm: number;
                        amount: string;
                        /** @constant */
                        basis: "quoted";
                        notional: string;
                    };
                    params: {
                        /** @enum {number} */
                        side: 0 | 1;
                        counterToken: string;
                        amount: string;
                        bound: string;
                        routedInput: string;
                        feeCygld: string;
                        recipient: string;
                        deadline: string;
                        adapter: string;
                        data: string;
                    };
                    adapterData: string;
                    plan: {
                        /** @enum {string} */
                        side: "buy" | "sell";
                        /** @enum {string} */
                        mode: "exact-in" | "exact-out";
                        amount: string;
                        slippageBps: number;
                        route: {
                            /** @constant */
                            version: 1;
                            /** @enum {string} */
                            executionContext: "helpers-core" | "helpers-market";
                            /** @enum {string} */
                            mode: "exactIn" | "exactOut";
                            tokenIn: string;
                            tokenOut: string;
                            branches: {
                                amountIn: string;
                                hops: {
                                    pool: components["schemas"]["RoutePoolRef"];
                                    zeroForOne: boolean;
                                }[];
                            }[];
                            inputAmount: string;
                            outputAmount: string;
                            limit: string;
                            deadline: string;
                        };
                        params: {
                            /** @enum {number} */
                            side: 0 | 1;
                            counterToken: string;
                            amount: string;
                            bound: string;
                            routedInput: string;
                            feeCygld: string;
                            recipient: string;
                            deadline: string;
                            adapter: string;
                            data: string;
                        };
                        fee: {
                            asset: string;
                            ratePpm: number;
                            amount: string;
                            /** @constant */
                            basis: "quoted";
                            notional: string;
                        };
                    };
                    context: {
                        chainId: number;
                        blockNumber: string;
                        blockHash: string;
                        observedAt: string;
                    };
                    feeBeneficiaryDisplay?: {
                        address: string;
                        observedAt: string;
                    };
                    /** @description AMM price impact excluding LP/protocol/application fees; absent without a coherent baseline. */
                    priceImpactPpm?: string;
                    /** @constant */
                    qualification: "sdk";
                    executionSimulationRequired?: boolean;
                    quoteVerificationUnavailable?: string;
                    searchCoverage?: {
                        /** @constant */
                        scope: "selected-inventory";
                        maxHops: number;
                        splitPercentages: number[];
                        inventoryPools: number;
                        catalogMonth: null | string;
                    };
                    metrics: {
                        candidateCalls: number;
                        totalMs: number;
                    } & {
                        firstQualifiedMs?: number;
                        selectionMs?: number;
                        canonicalCompletedMs?: number;
                        cleanupCompletedMs?: number;
                        finalizationMs?: number;
                    };
                    /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
                    quoteDiagnostics?: {
                        /** @enum {string} */
                        phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                        elapsedMs?: number;
                        qualified?: boolean;
                        inversionIteration?: number;
                        routeWave?: {
                            elapsedMs?: number;
                            subphaseElapsedMs?: number;
                            /** @enum {string} */
                            subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                            /** @enum {string} */
                            mode?: "exact-in" | "exact-out";
                            legacyCandidates?: number;
                            legacyCompleted?: number;
                            typedEnumerated?: number;
                            typedCompleted?: number;
                            typedPending?: number;
                            sdkRequests?: number;
                            sdkWaiting?: number;
                            sdkLockWaitMs?: number;
                            sdkExchangeMs?: number;
                            legs?: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                count: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedRows: number;
                                rows: {
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    index: number;
                                    inputAsset?: string;
                                    outputAsset?: string;
                                    /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                    amount?: string;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    started: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    succeeded: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    failed: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    cancelled: number;
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    pending: number;
                                    bestAvailable: boolean;
                                    failureCounts: {
                                        code: components["schemas"]["QuoteErrorCode"];
                                        /** @description Bounded observation count; never an execution eligibility predicate. */
                                        count: number;
                                    }[];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    omittedFailureCodes: number;
                                    bestPools: {
                                        /** @enum {string} */
                                        protocol: "v2" | "v3" | "v4";
                                        /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                        poolId?: string;
                                        poolAddress?: string;
                                    }[];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    omittedPools: number;
                                }[];
                            };
                        };
                        providerQualifications?: {
                            /** @enum {string} */
                            provider: "core" | "market";
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            attempts: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            qualified: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            rejected: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            notImproved: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            cancelled: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            superseded: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            pending: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedRows: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            selectedAttempt?: number;
                            /** @enum {string} */
                            selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            firstQualifiedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            selectionMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            canonicalCompletedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            cleanupCompletedMs?: number;
                            rows: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                attempt: number;
                                /** @enum {string} */
                                stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                                /** @enum {string} */
                                outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                                /** @enum {string} */
                                code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                targetAmount?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                minimumAmountOut?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                maximumAmountOut?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                observedAmountOut?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                maximumAmountIn?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                observedAmountIn?: string;
                                /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                                startedMs?: number;
                                /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                                completedMs?: number;
                                /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                                elapsedMs?: number;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                executionAmount?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                quotedInput?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                quotedOutput?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                inputMaximum?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                outputMinimum?: string;
                                pools?: {
                                    /** @enum {string} */
                                    protocol: "v2" | "v3" | "v4";
                                    /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                    poolId?: string;
                                    poolAddress?: string;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedPools?: number;
                            }[];
                        };
                    };
                };
            } & {
                providerAssessments?: components["schemas"]["TradeProviderAssessments"];
                providerCandidates?: {
                    /** @description One complete provider plan, without recursive provider evidence maps. */
                    core?: components["schemas"]["CoreTradeProviderCandidate"];
                    market?: components["schemas"]["MarketTradeProviderCandidate"];
                };
            });
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "provider-qualified";
            /** @enum {string} */
            strategy: "core" | "market";
            value: components["schemas"]["TradeProviderCandidate"];
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "provider-assessment";
            /** @enum {string} */
            strategy: "core" | "market";
            value: {
                /** @enum {string} */
                availability: "not-run" | "pending" | "qualified" | "unavailable" | "unsupported";
                /** @enum {string} */
                searchOutcome: "cancelled" | "complete" | "error" | "not-run" | "running" | "timeout";
                error?: string;
                /** @enum {string} */
                code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                /** @description Canonical preview rejection evidence; absent quantities were not provided by the contract. */
                constraint?: {
                    /** @enum {string} */
                    kind?: "issuance-cap" | "redemption-capacity" | "redemption-supply";
                    /** @enum {string} */
                    quantity?: "core-output-minima" | "gross-cygld-input" | "gross-cygld-mint";
                    /** @enum {string} */
                    limitKind?: "effective-supply-cap" | "maximum-total-supply";
                    requestedRaw?: string;
                    availableRaw?: string;
                    currentSupplyRaw?: string;
                    limitRaw?: string;
                };
                /** @description Optional observed RPC failure context; provider text is sanitized before publication. */
                diagnostics?: {
                    rpcMethod?: string;
                    stage?: string;
                    elapsedMs?: number;
                    upstreamErrorCode?: number;
                    providerMessage?: string;
                    httpStatus?: number;
                    /** @enum {string} */
                    failureType?: "backend-deadline" | "http-error" | "provider-timeout" | "rpc-error" | "transport-error";
                    errorSelector?: string;
                    errorName?: string;
                };
                /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
                quoteDiagnostics?: {
                    /** @enum {string} */
                    phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                    elapsedMs?: number;
                    qualified?: boolean;
                    inversionIteration?: number;
                    routeWave?: {
                        elapsedMs?: number;
                        subphaseElapsedMs?: number;
                        /** @enum {string} */
                        subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                        /** @enum {string} */
                        mode?: "exact-in" | "exact-out";
                        legacyCandidates?: number;
                        legacyCompleted?: number;
                        typedEnumerated?: number;
                        typedCompleted?: number;
                        typedPending?: number;
                        sdkRequests?: number;
                        sdkWaiting?: number;
                        sdkLockWaitMs?: number;
                        sdkExchangeMs?: number;
                        legs?: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            count: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedRows: number;
                            rows: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                index: number;
                                inputAsset?: string;
                                outputAsset?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                amount?: string;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                started: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                succeeded: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                failed: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                cancelled: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                pending: number;
                                bestAvailable: boolean;
                                failureCounts: {
                                    code: components["schemas"]["QuoteErrorCode"];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    count: number;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedFailureCodes: number;
                                bestPools: {
                                    /** @enum {string} */
                                    protocol: "v2" | "v3" | "v4";
                                    /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                    poolId?: string;
                                    poolAddress?: string;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedPools: number;
                            }[];
                        };
                    };
                    providerQualifications?: {
                        /** @enum {string} */
                        provider: "core" | "market";
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempts: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        qualified: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        rejected: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        notImproved: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        cancelled: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        superseded: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        pending: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        selectedAttempt?: number;
                        /** @enum {string} */
                        selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        firstQualifiedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        selectionMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        canonicalCompletedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        cleanupCompletedMs?: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            attempt: number;
                            /** @enum {string} */
                            stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                            /** @enum {string} */
                            outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                            /** @enum {string} */
                            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            targetAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            minimumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountIn?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountIn?: string;
                            /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                            startedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            completedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            elapsedMs?: number;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            executionAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedInput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedOutput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            inputMaximum?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            outputMinimum?: string;
                            pools?: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools?: number;
                        }[];
                    };
                };
            };
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "progress";
            /** @enum {string} */
            strategy: "core" | "market";
            value: {
                stage?: string;
                completed?: number;
                total?: number;
                completedCandidates?: number;
                totalCandidates?: number;
            };
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "provider-error";
            /** @enum {string} */
            strategy: "core" | "market";
            error: string;
            /** @enum {string} */
            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
            /** @description Canonical preview rejection evidence; absent quantities were not provided by the contract. */
            constraint?: {
                /** @enum {string} */
                kind?: "issuance-cap" | "redemption-capacity" | "redemption-supply";
                /** @enum {string} */
                quantity?: "core-output-minima" | "gross-cygld-input" | "gross-cygld-mint";
                /** @enum {string} */
                limitKind?: "effective-supply-cap" | "maximum-total-supply";
                requestedRaw?: string;
                availableRaw?: string;
                currentSupplyRaw?: string;
                limitRaw?: string;
            };
            /** @description Optional observed RPC failure context; provider text is sanitized before publication. */
            diagnostics?: {
                rpcMethod?: string;
                stage?: string;
                elapsedMs?: number;
                upstreamErrorCode?: number;
                providerMessage?: string;
                httpStatus?: number;
                /** @enum {string} */
                failureType?: "backend-deadline" | "http-error" | "provider-timeout" | "rpc-error" | "transport-error";
                errorSelector?: string;
                errorName?: string;
            };
            /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
            quoteDiagnostics?: {
                /** @enum {string} */
                phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                elapsedMs?: number;
                qualified?: boolean;
                inversionIteration?: number;
                routeWave?: {
                    elapsedMs?: number;
                    subphaseElapsedMs?: number;
                    /** @enum {string} */
                    subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                    /** @enum {string} */
                    mode?: "exact-in" | "exact-out";
                    legacyCandidates?: number;
                    legacyCompleted?: number;
                    typedEnumerated?: number;
                    typedCompleted?: number;
                    typedPending?: number;
                    sdkRequests?: number;
                    sdkWaiting?: number;
                    sdkLockWaitMs?: number;
                    sdkExchangeMs?: number;
                    legs?: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        count: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            index: number;
                            inputAsset?: string;
                            outputAsset?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            amount?: string;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            started: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            succeeded: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            failed: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            cancelled: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            pending: number;
                            bestAvailable: boolean;
                            failureCounts: {
                                code: components["schemas"]["QuoteErrorCode"];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                count: number;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedFailureCodes: number;
                            bestPools: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools: number;
                        }[];
                    };
                };
                providerQualifications?: {
                    /** @enum {string} */
                    provider: "core" | "market";
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    attempts: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    qualified: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    rejected: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    notImproved: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    cancelled: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    superseded: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    pending: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    omittedRows: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    selectedAttempt?: number;
                    /** @enum {string} */
                    selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    firstQualifiedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    selectionMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    canonicalCompletedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    cleanupCompletedMs?: number;
                    rows: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempt: number;
                        /** @enum {string} */
                        stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                        /** @enum {string} */
                        outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                        /** @enum {string} */
                        code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        targetAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        minimumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountIn?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountIn?: string;
                        /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                        startedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        completedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        elapsedMs?: number;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        executionAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedInput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedOutput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        inputMaximum?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        outputMinimum?: string;
                        pools?: {
                            /** @enum {string} */
                            protocol: "v2" | "v3" | "v4";
                            /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                            poolId?: string;
                            poolAddress?: string;
                        }[];
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedPools?: number;
                    }[];
                };
            };
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "invalidated";
            /** @enum {string} */
            strategy: "core" | "market";
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "error";
            error: string;
            /** @enum {string} */
            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
            /** @description Canonical preview rejection evidence; absent quantities were not provided by the contract. */
            constraint?: {
                /** @enum {string} */
                kind?: "issuance-cap" | "redemption-capacity" | "redemption-supply";
                /** @enum {string} */
                quantity?: "core-output-minima" | "gross-cygld-input" | "gross-cygld-mint";
                /** @enum {string} */
                limitKind?: "effective-supply-cap" | "maximum-total-supply";
                requestedRaw?: string;
                availableRaw?: string;
                currentSupplyRaw?: string;
                limitRaw?: string;
            };
            /** @description Optional observed RPC failure context; provider text is sanitized before publication. */
            diagnostics?: {
                rpcMethod?: string;
                stage?: string;
                elapsedMs?: number;
                upstreamErrorCode?: number;
                providerMessage?: string;
                httpStatus?: number;
                /** @enum {string} */
                failureType?: "backend-deadline" | "http-error" | "provider-timeout" | "rpc-error" | "transport-error";
                errorSelector?: string;
                errorName?: string;
            };
            /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
            quoteDiagnostics?: {
                /** @enum {string} */
                phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                elapsedMs?: number;
                qualified?: boolean;
                inversionIteration?: number;
                routeWave?: {
                    elapsedMs?: number;
                    subphaseElapsedMs?: number;
                    /** @enum {string} */
                    subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                    /** @enum {string} */
                    mode?: "exact-in" | "exact-out";
                    legacyCandidates?: number;
                    legacyCompleted?: number;
                    typedEnumerated?: number;
                    typedCompleted?: number;
                    typedPending?: number;
                    sdkRequests?: number;
                    sdkWaiting?: number;
                    sdkLockWaitMs?: number;
                    sdkExchangeMs?: number;
                    legs?: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        count: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            index: number;
                            inputAsset?: string;
                            outputAsset?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            amount?: string;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            started: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            succeeded: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            failed: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            cancelled: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            pending: number;
                            bestAvailable: boolean;
                            failureCounts: {
                                code: components["schemas"]["QuoteErrorCode"];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                count: number;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedFailureCodes: number;
                            bestPools: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools: number;
                        }[];
                    };
                };
                providerQualifications?: {
                    /** @enum {string} */
                    provider: "core" | "market";
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    attempts: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    qualified: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    rejected: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    notImproved: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    cancelled: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    superseded: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    pending: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    omittedRows: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    selectedAttempt?: number;
                    /** @enum {string} */
                    selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    firstQualifiedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    selectionMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    canonicalCompletedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    cleanupCompletedMs?: number;
                    rows: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempt: number;
                        /** @enum {string} */
                        stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                        /** @enum {string} */
                        outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                        /** @enum {string} */
                        code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        targetAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        minimumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountIn?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountIn?: string;
                        /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                        startedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        completedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        elapsedMs?: number;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        executionAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedInput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedOutput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        inputMaximum?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        outputMinimum?: string;
                        pools?: {
                            /** @enum {string} */
                            protocol: "v2" | "v3" | "v4";
                            /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                            poolId?: string;
                            poolAddress?: string;
                        }[];
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedPools?: number;
                    }[];
                };
            };
            providerAssessments?: components["schemas"]["TradeProviderAssessments"];
            providerCandidates?: {
                /** @description One complete provider plan, without recursive provider evidence maps. */
                core?: components["schemas"]["CoreTradeProviderCandidate"];
                market?: components["schemas"]["MarketTradeProviderCandidate"];
            };
        });
        "Omit<QuoteIntentRequest,\"deadline\"|\"retainedPlan\">": {
            /** @enum {string} */
            mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
            amount: string;
            targets: {
                inputAsset: string;
                outputAsset: string;
                amount: string;
            }[];
            token: string;
            native: boolean;
            /**
             * @description Execution tolerance in basis points; omitted defaults to 100 (1%).
             * @default 100
             */
            slippageBps: number;
            adapter?: string;
            quoteToken: string;
            orderedAssets: string[];
        };
        /** @description App deployment configuration; routing infrastructure stays server-owned. */
        ProtocolConfiguredToken: ({
            id: string;
            symbol: string;
            name: string;
            decimals: number;
            chainId: number;
        } & {
            /** @constant */
            type: "erc20";
            address: string;
        }) | ({
            id: string;
            symbol: string;
            name: string;
            decimals: number;
            chainId: number;
        } & {
            /** @constant */
            type: "native";
        });
        MarketQuoteResponse: {
            /** @constant */
            strategy: "universal";
            /** @enum {string} */
            routeFamily: "core" | "market" | "mixed";
            /** @constant */
            operation: "executeExactInput";
            /** @constant */
            settlementPolicy: "protocol-retained-input";
            plan: components["schemas"]["UniversalExactInputPlan"];
            planDescription: components["schemas"]["Record<string,unknown>"];
            economicQuote?: components["schemas"]["EconomicQuote"];
            inputs: {
                currency: string;
                amount: string;
            }[];
            quotedInput?: string;
            inputMaximum?: string;
            quotedOutput: string;
            outputMinimum: string;
            estimatedRetainedInputCharges: {
                branch: number;
                stage: number;
                currency: string;
                amount: string;
            }[];
            estimatedRecipientOutputs: {
                kind: number;
                token: string;
                id: string;
                amount: string;
            }[];
            fees: {
                coreProtocolFeeCygld: string;
                coreHelpersFeeCygld: string;
                marketFeeCygld: string;
            };
            recoveryShares: {
                kind: number;
                token: string;
                id: string;
                amount: string;
            }[];
            deployment: {
                helpers: string;
                adapter: string;
                /** @constant */
                encoding: "uniswap-routing-v1";
            };
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            retentionDisclosure: {
                custodian: string;
                /** @constant */
                beneficiary: "helpers-owner-at-settlement";
            };
            searchCoverage: {
                coreSharesPercent: number[];
                orders: string[];
                maxCoreInvocations: number;
                maxAmmHops: number;
                /** @constant */
                scope: "selected-inventory";
                /** @enum {string} */
                selectedPhase?: "backward-prefix" | "capacity-limited" | "detailed" | "first-result" | "nearby-lower" | "nearby-upper" | "route-family" | "route-family-exploration" | "saved-plan";
            };
            /** @description Producer clocks, distinct from client request or browser journey duration. */
            metrics?: {
                firstQualifiedMs?: number;
                selectionMs?: number;
                canonicalCompletedMs?: number;
                cleanupCompletedMs?: number;
                finalizationMs?: number;
            } & {
                totalMs: number;
                timeToFirstWholePlanMs: null | number;
                searchMs: null | number;
                selectionReason: ("best-initial" | "complete" | "first-extension" | "timeout") | null;
                nearbySearch?: {
                    starts: number;
                    completed: number;
                    sources: {
                        /** @enum {string} */
                        side: "lower" | "upper";
                        identity?: null | string;
                        /** @enum {string} */
                        referenceBasis?: "funded-input-approximation" | "market-sale-consumed" | "observed-nonretained";
                        attempts: {
                            funding: string;
                            completed?: boolean;
                            elapsedMs: number;
                            /** @enum {string} */
                            failureCode?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        }[];
                        /** @enum {string} */
                        failureCode?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                    }[];
                };
            };
        } | {
            /** @constant */
            operation: "market";
            /** @enum {string} */
            side: "buy" | "sell";
            /** @enum {string} */
            mode: "exact-in" | "exact-out";
            tokenIn: string;
            tokenOut: string;
            amountIn: string;
            amountOut: string;
            totalInput: string;
            netOutput: string;
            grossOutput: string;
            routedAmountIn: string;
            inputMaximum: string;
            outputMinimum: string;
            refundDust: string;
            outputRefundEstimate?: string;
            fee: {
                asset: string;
                ratePpm: number;
                amount: string;
                /** @constant */
                basis: "quoted";
                notional: string;
            };
            params: {
                /** @enum {number} */
                side: 0 | 1;
                counterToken: string;
                amount: string;
                bound: string;
                routedInput: string;
                feeCygld: string;
                recipient: string;
                deadline: string;
                adapter: string;
                data: string;
            };
            adapterData: string;
            plan: {
                /** @enum {string} */
                side: "buy" | "sell";
                /** @enum {string} */
                mode: "exact-in" | "exact-out";
                amount: string;
                slippageBps: number;
                route: {
                    /** @constant */
                    version: 1;
                    /** @enum {string} */
                    executionContext: "helpers-core" | "helpers-market";
                    /** @enum {string} */
                    mode: "exactIn" | "exactOut";
                    tokenIn: string;
                    tokenOut: string;
                    branches: {
                        amountIn: string;
                        hops: {
                            pool: components["schemas"]["RoutePoolRef"];
                            zeroForOne: boolean;
                        }[];
                    }[];
                    inputAmount: string;
                    outputAmount: string;
                    limit: string;
                    deadline: string;
                };
                params: {
                    /** @enum {number} */
                    side: 0 | 1;
                    counterToken: string;
                    amount: string;
                    bound: string;
                    routedInput: string;
                    feeCygld: string;
                    recipient: string;
                    deadline: string;
                    adapter: string;
                    data: string;
                };
                fee: {
                    asset: string;
                    ratePpm: number;
                    amount: string;
                    /** @constant */
                    basis: "quoted";
                    notional: string;
                };
            };
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            feeBeneficiaryDisplay?: {
                address: string;
                observedAt: string;
            };
            /** @description AMM price impact excluding LP/protocol/application fees; absent without a coherent baseline. */
            priceImpactPpm?: string;
            /** @constant */
            qualification: "sdk";
            executionSimulationRequired?: boolean;
            quoteVerificationUnavailable?: string;
            searchCoverage?: {
                /** @constant */
                scope: "selected-inventory";
                maxHops: number;
                splitPercentages: number[];
                inventoryPools: number;
                catalogMonth: null | string;
            };
            metrics: {
                candidateCalls: number;
                totalMs: number;
            } & {
                firstQualifiedMs?: number;
                selectionMs?: number;
                canonicalCompletedMs?: number;
                cleanupCompletedMs?: number;
                finalizationMs?: number;
            };
            /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
            quoteDiagnostics?: {
                /** @enum {string} */
                phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                elapsedMs?: number;
                qualified?: boolean;
                inversionIteration?: number;
                routeWave?: {
                    elapsedMs?: number;
                    subphaseElapsedMs?: number;
                    /** @enum {string} */
                    subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                    /** @enum {string} */
                    mode?: "exact-in" | "exact-out";
                    legacyCandidates?: number;
                    legacyCompleted?: number;
                    typedEnumerated?: number;
                    typedCompleted?: number;
                    typedPending?: number;
                    sdkRequests?: number;
                    sdkWaiting?: number;
                    sdkLockWaitMs?: number;
                    sdkExchangeMs?: number;
                    legs?: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        count: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            index: number;
                            inputAsset?: string;
                            outputAsset?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            amount?: string;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            started: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            succeeded: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            failed: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            cancelled: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            pending: number;
                            bestAvailable: boolean;
                            failureCounts: {
                                code: components["schemas"]["QuoteErrorCode"];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                count: number;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedFailureCodes: number;
                            bestPools: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools: number;
                        }[];
                    };
                };
                providerQualifications?: {
                    /** @enum {string} */
                    provider: "core" | "market";
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    attempts: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    qualified: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    rejected: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    notImproved: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    cancelled: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    superseded: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    pending: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    omittedRows: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    selectedAttempt?: number;
                    /** @enum {string} */
                    selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    firstQualifiedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    selectionMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    canonicalCompletedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    cleanupCompletedMs?: number;
                    rows: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempt: number;
                        /** @enum {string} */
                        stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                        /** @enum {string} */
                        outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                        /** @enum {string} */
                        code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        targetAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        minimumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountIn?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountIn?: string;
                        /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                        startedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        completedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        elapsedMs?: number;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        executionAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedInput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedOutput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        inputMaximum?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        outputMinimum?: string;
                        pools?: {
                            /** @enum {string} */
                            protocol: "v2" | "v3" | "v4";
                            /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                            poolId?: string;
                            poolAddress?: string;
                        }[];
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedPools?: number;
                    }[];
                };
            };
        };
        MarketQuoteEvent: ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "model";
            value: {
                /** @constant */
                namespace: "market";
                family: string;
                context?: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                intent: {
                    /** @enum {string} */
                    side: "buy" | "sell";
                    /** @enum {string} */
                    mode: "exact-in" | "exact-out";
                    counterToken: string;
                    adapter: string;
                };
                cygld: string;
                feeRatePpm: number;
                routes: {
                    route: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                    amountIn: string;
                    amountOut: string;
                    sourceObservations?: {
                        poolId: string;
                        context: {
                            chainId: number;
                            blockNumber: string;
                            blockHash: string;
                            observedAt: string;
                        };
                    }[];
                    sourceContext?: {
                        chainId: number;
                        blockNumber: string;
                        blockHash: string;
                        observedAt: string;
                    } | null;
                    points: {
                        amountIn: string;
                        amountOut: string;
                        context?: {
                            chainId: number;
                            blockNumber: string;
                            blockHash: string;
                            observedAt: string;
                        };
                        requestedAmount?: string;
                        family?: string;
                        feeRatePpm?: number;
                        routeIdentity?: string;
                    }[];
                    exchangeRate?: {
                        numerator: string;
                        denominator: string;
                    };
                    feeRetention?: {
                        numerator: string;
                        denominator: string;
                    };
                    localImpact?: {
                        numerator: string;
                        denominator: string;
                    };
                }[];
            };
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "estimate";
            amount: string;
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @enum {string} */
            type: "complete" | "qualified";
            value: {
                /** @constant */
                strategy: "universal";
                /** @enum {string} */
                routeFamily: "core" | "market" | "mixed";
                /** @constant */
                operation: "executeExactInput";
                /** @constant */
                settlementPolicy: "protocol-retained-input";
                plan: components["schemas"]["UniversalExactInputPlan"];
                planDescription: components["schemas"]["Record<string,unknown>"];
                economicQuote?: components["schemas"]["EconomicQuote"];
                inputs: {
                    currency: string;
                    amount: string;
                }[];
                quotedInput?: string;
                inputMaximum?: string;
                quotedOutput: string;
                outputMinimum: string;
                estimatedRetainedInputCharges: {
                    branch: number;
                    stage: number;
                    currency: string;
                    amount: string;
                }[];
                estimatedRecipientOutputs: {
                    kind: number;
                    token: string;
                    id: string;
                    amount: string;
                }[];
                fees: {
                    coreProtocolFeeCygld: string;
                    coreHelpersFeeCygld: string;
                    marketFeeCygld: string;
                };
                recoveryShares: {
                    kind: number;
                    token: string;
                    id: string;
                    amount: string;
                }[];
                deployment: {
                    helpers: string;
                    adapter: string;
                    /** @constant */
                    encoding: "uniswap-routing-v1";
                };
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                retentionDisclosure: {
                    custodian: string;
                    /** @constant */
                    beneficiary: "helpers-owner-at-settlement";
                };
                searchCoverage: {
                    coreSharesPercent: number[];
                    orders: string[];
                    maxCoreInvocations: number;
                    maxAmmHops: number;
                    /** @constant */
                    scope: "selected-inventory";
                    /** @enum {string} */
                    selectedPhase?: "backward-prefix" | "capacity-limited" | "detailed" | "first-result" | "nearby-lower" | "nearby-upper" | "route-family" | "route-family-exploration" | "saved-plan";
                };
                /** @description Producer clocks, distinct from client request or browser journey duration. */
                metrics?: {
                    firstQualifiedMs?: number;
                    selectionMs?: number;
                    canonicalCompletedMs?: number;
                    cleanupCompletedMs?: number;
                    finalizationMs?: number;
                } & {
                    totalMs: number;
                    timeToFirstWholePlanMs: null | number;
                    searchMs: null | number;
                    selectionReason: ("best-initial" | "complete" | "first-extension" | "timeout") | null;
                    nearbySearch?: {
                        starts: number;
                        completed: number;
                        sources: {
                            /** @enum {string} */
                            side: "lower" | "upper";
                            identity?: null | string;
                            /** @enum {string} */
                            referenceBasis?: "funded-input-approximation" | "market-sale-consumed" | "observed-nonretained";
                            attempts: {
                                funding: string;
                                completed?: boolean;
                                elapsedMs: number;
                                /** @enum {string} */
                                failureCode?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                            }[];
                            /** @enum {string} */
                            failureCode?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        }[];
                    };
                };
            } | {
                /** @constant */
                operation: "market";
                /** @enum {string} */
                side: "buy" | "sell";
                /** @enum {string} */
                mode: "exact-in" | "exact-out";
                tokenIn: string;
                tokenOut: string;
                amountIn: string;
                amountOut: string;
                totalInput: string;
                netOutput: string;
                grossOutput: string;
                routedAmountIn: string;
                inputMaximum: string;
                outputMinimum: string;
                refundDust: string;
                outputRefundEstimate?: string;
                fee: {
                    asset: string;
                    ratePpm: number;
                    amount: string;
                    /** @constant */
                    basis: "quoted";
                    notional: string;
                };
                params: {
                    /** @enum {number} */
                    side: 0 | 1;
                    counterToken: string;
                    amount: string;
                    bound: string;
                    routedInput: string;
                    feeCygld: string;
                    recipient: string;
                    deadline: string;
                    adapter: string;
                    data: string;
                };
                adapterData: string;
                plan: {
                    /** @enum {string} */
                    side: "buy" | "sell";
                    /** @enum {string} */
                    mode: "exact-in" | "exact-out";
                    amount: string;
                    slippageBps: number;
                    route: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                    params: {
                        /** @enum {number} */
                        side: 0 | 1;
                        counterToken: string;
                        amount: string;
                        bound: string;
                        routedInput: string;
                        feeCygld: string;
                        recipient: string;
                        deadline: string;
                        adapter: string;
                        data: string;
                    };
                    fee: {
                        asset: string;
                        ratePpm: number;
                        amount: string;
                        /** @constant */
                        basis: "quoted";
                        notional: string;
                    };
                };
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                feeBeneficiaryDisplay?: {
                    address: string;
                    observedAt: string;
                };
                /** @description AMM price impact excluding LP/protocol/application fees; absent without a coherent baseline. */
                priceImpactPpm?: string;
                /** @constant */
                qualification: "sdk";
                executionSimulationRequired?: boolean;
                quoteVerificationUnavailable?: string;
                searchCoverage?: {
                    /** @constant */
                    scope: "selected-inventory";
                    maxHops: number;
                    splitPercentages: number[];
                    inventoryPools: number;
                    catalogMonth: null | string;
                };
                metrics: {
                    candidateCalls: number;
                    totalMs: number;
                } & {
                    firstQualifiedMs?: number;
                    selectionMs?: number;
                    canonicalCompletedMs?: number;
                    cleanupCompletedMs?: number;
                    finalizationMs?: number;
                };
                /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
                quoteDiagnostics?: {
                    /** @enum {string} */
                    phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                    elapsedMs?: number;
                    qualified?: boolean;
                    inversionIteration?: number;
                    routeWave?: {
                        elapsedMs?: number;
                        subphaseElapsedMs?: number;
                        /** @enum {string} */
                        subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                        /** @enum {string} */
                        mode?: "exact-in" | "exact-out";
                        legacyCandidates?: number;
                        legacyCompleted?: number;
                        typedEnumerated?: number;
                        typedCompleted?: number;
                        typedPending?: number;
                        sdkRequests?: number;
                        sdkWaiting?: number;
                        sdkLockWaitMs?: number;
                        sdkExchangeMs?: number;
                        legs?: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            count: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedRows: number;
                            rows: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                index: number;
                                inputAsset?: string;
                                outputAsset?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                amount?: string;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                started: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                succeeded: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                failed: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                cancelled: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                pending: number;
                                bestAvailable: boolean;
                                failureCounts: {
                                    code: components["schemas"]["QuoteErrorCode"];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    count: number;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedFailureCodes: number;
                                bestPools: {
                                    /** @enum {string} */
                                    protocol: "v2" | "v3" | "v4";
                                    /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                    poolId?: string;
                                    poolAddress?: string;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedPools: number;
                            }[];
                        };
                    };
                    providerQualifications?: {
                        /** @enum {string} */
                        provider: "core" | "market";
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempts: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        qualified: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        rejected: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        notImproved: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        cancelled: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        superseded: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        pending: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        selectedAttempt?: number;
                        /** @enum {string} */
                        selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        firstQualifiedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        selectionMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        canonicalCompletedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        cleanupCompletedMs?: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            attempt: number;
                            /** @enum {string} */
                            stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                            /** @enum {string} */
                            outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                            /** @enum {string} */
                            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            targetAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            minimumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountIn?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountIn?: string;
                            /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                            startedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            completedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            elapsedMs?: number;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            executionAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedInput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedOutput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            inputMaximum?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            outputMinimum?: string;
                            pools?: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools?: number;
                        }[];
                    };
                };
            };
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "progress";
            completedCandidates: number;
            totalCandidates?: number;
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "invalidated";
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "error";
            error: string;
            code?: string;
            /** @description Optional observed RPC failure context; provider text is sanitized before publication. */
            diagnostics?: {
                rpcMethod?: string;
                stage?: string;
                elapsedMs?: number;
                upstreamErrorCode?: number;
                providerMessage?: string;
                httpStatus?: number;
                /** @enum {string} */
                failureType?: "backend-deadline" | "http-error" | "provider-timeout" | "rpc-error" | "transport-error";
                errorSelector?: string;
                errorName?: string;
            };
            /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
            quoteDiagnostics?: {
                /** @enum {string} */
                phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                elapsedMs?: number;
                qualified?: boolean;
                inversionIteration?: number;
                routeWave?: {
                    elapsedMs?: number;
                    subphaseElapsedMs?: number;
                    /** @enum {string} */
                    subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                    /** @enum {string} */
                    mode?: "exact-in" | "exact-out";
                    legacyCandidates?: number;
                    legacyCompleted?: number;
                    typedEnumerated?: number;
                    typedCompleted?: number;
                    typedPending?: number;
                    sdkRequests?: number;
                    sdkWaiting?: number;
                    sdkLockWaitMs?: number;
                    sdkExchangeMs?: number;
                    legs?: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        count: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            index: number;
                            inputAsset?: string;
                            outputAsset?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            amount?: string;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            started: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            succeeded: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            failed: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            cancelled: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            pending: number;
                            bestAvailable: boolean;
                            failureCounts: {
                                code: components["schemas"]["QuoteErrorCode"];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                count: number;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedFailureCodes: number;
                            bestPools: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools: number;
                        }[];
                    };
                };
                providerQualifications?: {
                    /** @enum {string} */
                    provider: "core" | "market";
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    attempts: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    qualified: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    rejected: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    notImproved: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    cancelled: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    superseded: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    pending: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    omittedRows: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    selectedAttempt?: number;
                    /** @enum {string} */
                    selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    firstQualifiedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    selectionMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    canonicalCompletedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    cleanupCompletedMs?: number;
                    rows: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempt: number;
                        /** @enum {string} */
                        stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                        /** @enum {string} */
                        outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                        /** @enum {string} */
                        code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        targetAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        minimumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountIn?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountIn?: string;
                        /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                        startedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        completedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        elapsedMs?: number;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        executionAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedInput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedOutput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        inputMaximum?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        outputMinimum?: string;
                        pools?: {
                            /** @enum {string} */
                            protocol: "v2" | "v3" | "v4";
                            /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                            poolId?: string;
                            poolAddress?: string;
                        }[];
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedPools?: number;
                    }[];
                };
            };
        });
        MarketModelRequest: {
            /** @enum {string} */
            mode: "exact-in" | "exact-out";
            /** @enum {string} */
            side: "buy" | "sell";
            counterToken: string;
            adapter?: string;
        };
        PoolIdentifier: ({
            tokenA: string;
            tokenB: string;
            id?: string;
        } & {
            /** @constant */
            protocol?: "v3";
            fee: number;
        }) | ({
            tokenA: string;
            tokenB: string;
            id?: string;
        } & {
            /** @constant */
            protocol: "v2";
            fee?: number;
        }) | ({
            tokenA: string;
            tokenB: string;
            id?: string;
        } & {
            /** @constant */
            protocol: "v4";
            fee: number;
            tickSpacing: number;
            hooks: string;
            poolManager?: string;
            poolId?: string;
        });
        PoolSnapshot: {
            /** @enum {string} */
            protocol?: "v2" | "v3" | "v4";
            id?: string;
            poolId?: string;
            poolManager?: string;
            tickSpacing?: number;
            hooks?: string;
            poolKey?: {
                currency0: string;
                currency1: string;
                fee: number;
                tickSpacing: number;
                hooks: string;
            };
        } & {
            pool?: {
                id: string;
                /** @enum {string} */
                protocol: "v2" | "v3" | "v4";
                token0: {
                    address: string;
                    decimals: number;
                    chainId: number;
                    decimalsKnown?: boolean;
                };
                token1: {
                    address: string;
                    decimals: number;
                    chainId: number;
                    decimalsKnown?: boolean;
                };
                address?: string;
                feePips: number;
                tickSpacing?: number;
                poolManager?: string;
                hooks?: string;
            };
            reserve0Raw?: string;
            reserve1Raw?: string;
            /** @description V3 nominal fee tier; V4 current StateView LP fee pips. */
            lpFee?: number;
            /** @description V3 packed 4-bit protocol-share divisors; V4 packed 12-bit protocol fee pips. */
            protocolFee?: number;
            /** @description Raw token1/token0 marginal rate, without token decimals or swap fees. */
            marginalPrice?: {
                numerator: string;
                denominator: string;
            };
            ticks?: {
                index: number;
                liquidityGross: string;
                liquidityNet: string;
            }[];
            bitmapWords?: {
                wordPosition: number;
                bitmap: string;
            }[];
        } & {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            dex: components["schemas"]["PoolDex"];
            token0: string;
            token1: string;
            fee: number;
            exists: boolean;
            poolAddress?: string;
            activeLiquidityRaw?: string;
            sqrtPriceX96Raw?: string;
            tick?: number;
            /** @description Observed V3 ERC20 pool balances. V2 uses reserve fields; absent for V4. */
            token0BalanceRaw?: string;
            token1BalanceRaw?: string;
        };
        /** @enum {string} */
        PoolDex: "uniswap_v2" | "uniswap_v3" | "uniswap_v4";
        PoolActivity: {
            /** @constant */
            enabled: false;
            events: unknown[];
            pools: unknown[];
        } | {
            /** @constant */
            enabled: true;
            chainId: number;
            /** @constant */
            source: "retained-uniswap-pool-events";
            hasMore: boolean;
            events: {
                identity: string;
                pool: {
                    id: string;
                    /** @enum {string} */
                    protocol: "v2" | "v3" | "v4";
                    token0: {
                        address: string;
                        decimals: number;
                        chainId: number;
                        decimalsKnown?: boolean;
                    };
                    token1: {
                        address: string;
                        decimals: number;
                        chainId: number;
                        decimalsKnown?: boolean;
                    };
                    address?: string;
                    feePips: number;
                    tickSpacing?: number;
                    poolManager?: string;
                    hooks?: string;
                };
                blockNumber: string;
                blockHash: string;
                transactionHash: string;
                transactionIndex: number;
                logIndex: number;
                address: string;
                eventName: string;
                arguments: components["schemas"]["Record<string,string>"] | null;
                topics: string[];
                data: string;
            }[];
            pools: {
                pool: {
                    id: string;
                    /** @enum {string} */
                    protocol: "v2" | "v3" | "v4";
                    token0: {
                        address: string;
                        decimals: number;
                        chainId: number;
                        decimalsKnown?: boolean;
                    };
                    token1: {
                        address: string;
                        decimals: number;
                        chainId: number;
                        decimalsKnown?: boolean;
                    };
                    address?: string;
                    feePips: number;
                    tickSpacing?: number;
                    poolManager?: string;
                    hooks?: string;
                };
                journalStartBlock: string;
                indexedThroughBlock: string;
                indexedThroughBlockHash: string;
                hasMore: boolean;
                rollups: {
                    startBlock: string;
                    blockNumber: string;
                    blockHash: string;
                    rollup: {
                        eventCount: number;
                        swapCount: number;
                        liquidityAdditionCount: number;
                        liquidityRemovalCount: number;
                        stateUpdateCount: number;
                        feeChangeCount: number;
                        undecodedCount: number;
                        amount0InRaw: string;
                        amount1InRaw: string;
                        amount0OutRaw: string;
                        amount1OutRaw: string;
                        /** @description Range liquidity units, never active liquidity or token deposit/withdrawal amounts. */
                        liquidityAddedRaw: string;
                        liquidityRemovedRaw: string;
                    };
                }[];
            }[];
            retention: {
                eventsPerPool: number;
                rangesPerPool: number;
                publicEvents: number;
            };
        };
        "Record<string,string>": Record<string, never>;
        /** @description Live configured product facts; amounts stay lossless over JSON. */
        "FactRead<string>": {
            /** @constant */
            status: "failure";
            /** @enum {string} */
            error: "contract-read-failed" | "not-configured";
        } | {
            /** @constant */
            status: "success";
            value: string;
        };
        /** @description Live configured product facts; amounts stay lossless over JSON. */
        "FactRead<string[]>": {
            /** @constant */
            status: "failure";
            /** @enum {string} */
            error: "contract-read-failed" | "not-configured";
        } | {
            /** @constant */
            status: "success";
            value: string[];
        };
        /** @description Live configured product facts; amounts stay lossless over JSON. */
        "FactRead<number>": {
            /** @constant */
            status: "failure";
            /** @enum {string} */
            error: "contract-read-failed" | "not-configured";
        } | {
            /** @constant */
            status: "success";
            value: number;
        };
        /** @description Live configured product facts; amounts stay lossless over JSON. */
        "FactRead<boolean>": {
            /** @constant */
            status: "failure";
            /** @enum {string} */
            error: "contract-read-failed" | "not-configured";
        } | {
            /** @constant */
            status: "success";
            value: boolean;
        };
        RecoveryRedemption: {
            holder: string;
            asset: string;
            shares: string;
            minRawOut: string;
        } & {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            core: string;
            rawOut: string;
        };
        Permit2ApprovalGas: {
            owner: string;
            token: string;
        } & {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            permit2: string;
            gas: string;
            /** @constant */
            blockTag: "latest";
        };
        SafeExecutionRequest: components["schemas"]["Omit<SafeTransactionHashRequest,\"nonce\">"] & {
            executor: string;
            executorNonce: string;
            signatures: string;
        };
        "Omit<SafeTransactionHashRequest,\"nonce\">": {
            value: string;
            operation: number;
            address: string;
            to: string;
            data: string;
            gasPrice: string;
            safeTxGas: string;
            baseGas: string;
            gasToken: string;
            refundReceiver: string;
        };
        ReceiptWaitHead: {
            chainId: number;
            observedAt: string;
        } & {
            blockNumber: string;
            blockHash: string;
            blockTimestamp: string;
        };
        ReceiptWaitTransaction: {
            chainId: number;
            observedAt: string;
        } & {
            transaction: components["schemas"]["{blockNumber:`0x${string}`|null;blockHash:`0x${string}`|null;value:`0x${string}`;chainId?:`0x${string}`|undefined;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x0\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice:`0x${string}`;maxFeePerBlobGas?:undefined;maxFeePerGas?:undefined;maxPriorityFeePerGas?:undefined;accessList?:undefined;authorizationList?:undefined;hash:`0x${string}`;yParity?:undefined;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`|null;}"] | components["schemas"]["{blockNumber:`0x${string}`|null;blockHash:`0x${string}`|null;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x1\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice:`0x${string}`;maxFeePerBlobGas?:undefined;maxFeePerGas?:undefined;maxPriorityFeePerGas?:undefined;accessList:AccessList;authorizationList?:undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`|null;yParity?:`0x${string}`|undefined;}"] | components["schemas"]["{blockNumber:`0x${string}`|null;blockHash:`0x${string}`|null;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x2\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice?:undefined;maxFeePerBlobGas?:undefined;maxFeePerGas:`0x${string}`;maxPriorityFeePerGas:`0x${string}`;accessList:AccessList;authorizationList?:undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`|null;yParity?:`0x${string}`|undefined;}"] | components["schemas"]["{blockNumber:`0x${string}`|null;blockHash:`0x${string}`|null;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x3\";gas:`0x${string}`;blobVersionedHashes:readonly`0x${string}`[];gasPrice?:undefined;maxFeePerBlobGas:`0x${string}`;maxFeePerGas:`0x${string}`;maxPriorityFeePerGas:`0x${string}`;accessList:AccessList;authorizationList?:undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`|null;yParity?:`0x${string}`|undefined;}"] | components["schemas"]["{blockNumber:`0x${string}`|null;blockHash:`0x${string}`|null;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x4\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice?:undefined;maxFeePerBlobGas?:undefined;maxFeePerGas:`0x${string}`;maxPriorityFeePerGas:`0x${string}`;accessList:AccessList;authorizationList?:RpcAuthorizationList|undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`|null;yParity?:`0x${string}`|undefined;}"] | null;
        };
        "{blockNumber:`0x${string}`|null;blockHash:`0x${string}`|null;value:`0x${string}`;chainId?:`0x${string}`|undefined;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x0\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice:`0x${string}`;maxFeePerBlobGas?:undefined;maxFeePerGas?:undefined;maxPriorityFeePerGas?:undefined;accessList?:undefined;authorizationList?:undefined;hash:`0x${string}`;yParity?:undefined;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`|null;}": {
            /** @description Number of block containing this transaction or `null` if pending */
            blockNumber: string | null;
            /** @description Hash of block containing this transaction or `null` if pending */
            blockHash: string | null;
            /** @description Value in wei sent with this transaction */
            value: string;
            /** @description Chain ID that this transaction is valid on. */
            chainId?: string;
            /** @description ECDSA signature s */
            s: string;
            /** @description Transaction sender */
            from: string;
            /** @description Transaction recipient or `null` if deploying a contract */
            to: string | null;
            /** @description Unique number identifying this transaction */
            nonce: string;
            /** @description ECDSA recovery ID */
            v: string;
            /** @description ECDSA signature r */
            r: string;
            /** @constant */
            type: "0x0";
            /** @description Gas provided for transaction execution */
            gas: string;
            /** @description Base fee per gas. */
            gasPrice: string;
            /** @description Hash of this transaction */
            hash: string;
            /** @description Unix timestamp of when this block was included */
            blockTimestamp?: string;
            /** @description Contract code or a hashed method call */
            input: string;
            /** @description Index of this transaction in the block or `null` if pending */
            transactionIndex: string | null;
        };
        "{blockNumber:`0x${string}`|null;blockHash:`0x${string}`|null;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x1\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice:`0x${string}`;maxFeePerBlobGas?:undefined;maxFeePerGas?:undefined;maxPriorityFeePerGas?:undefined;accessList:AccessList;authorizationList?:undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`|null;yParity?:`0x${string}`|undefined;}": {
            /** @description Number of block containing this transaction or `null` if pending */
            blockNumber: string | null;
            /** @description Hash of block containing this transaction or `null` if pending */
            blockHash: string | null;
            /** @description Value in wei sent with this transaction */
            value: string;
            /** @description Chain ID that this transaction is valid on. */
            chainId: string;
            /** @description ECDSA signature s */
            s: string;
            /** @description Transaction sender */
            from: string;
            /** @description Transaction recipient or `null` if deploying a contract */
            to: string | null;
            /** @description Unique number identifying this transaction */
            nonce: string;
            /** @description ECDSA recovery ID */
            v: string;
            /** @description ECDSA signature r */
            r: string;
            /** @constant */
            type: "0x1";
            /** @description Gas provided for transaction execution */
            gas: string;
            /** @description Base fee per gas. */
            gasPrice: string;
            /** @description EIP-2930 Access List. */
            accessList: {
                address: string;
                storageKeys: string[];
            }[];
            /** @description Hash of this transaction */
            hash: string;
            /** @description Unix timestamp of when this block was included */
            blockTimestamp?: string;
            /** @description Contract code or a hashed method call */
            input: string;
            /** @description Index of this transaction in the block or `null` if pending */
            transactionIndex: string | null;
            /** @description The parity of the y-value of the secp256k1 signature. */
            yParity?: string;
        };
        "{blockNumber:`0x${string}`|null;blockHash:`0x${string}`|null;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x2\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice?:undefined;maxFeePerBlobGas?:undefined;maxFeePerGas:`0x${string}`;maxPriorityFeePerGas:`0x${string}`;accessList:AccessList;authorizationList?:undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`|null;yParity?:`0x${string}`|undefined;}": {
            /** @description Number of block containing this transaction or `null` if pending */
            blockNumber: string | null;
            /** @description Hash of block containing this transaction or `null` if pending */
            blockHash: string | null;
            /** @description Value in wei sent with this transaction */
            value: string;
            /** @description Chain ID that this transaction is valid on. */
            chainId: string;
            /** @description ECDSA signature s */
            s: string;
            /** @description Transaction sender */
            from: string;
            /** @description Transaction recipient or `null` if deploying a contract */
            to: string | null;
            /** @description Unique number identifying this transaction */
            nonce: string;
            /** @description ECDSA recovery ID */
            v: string;
            /** @description ECDSA signature r */
            r: string;
            /** @constant */
            type: "0x2";
            /** @description Gas provided for transaction execution */
            gas: string;
            /** @description Total fee per gas in wei (gasPrice/baseFeePerGas + maxPriorityFeePerGas). */
            maxFeePerGas: string;
            /** @description Max priority fee per gas (in wei). */
            maxPriorityFeePerGas: string;
            /** @description EIP-2930 Access List. */
            accessList: {
                address: string;
                storageKeys: string[];
            }[];
            /** @description Hash of this transaction */
            hash: string;
            /** @description Unix timestamp of when this block was included */
            blockTimestamp?: string;
            /** @description Contract code or a hashed method call */
            input: string;
            /** @description Index of this transaction in the block or `null` if pending */
            transactionIndex: string | null;
            /** @description The parity of the y-value of the secp256k1 signature. */
            yParity?: string;
        };
        "{blockNumber:`0x${string}`|null;blockHash:`0x${string}`|null;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x3\";gas:`0x${string}`;blobVersionedHashes:readonly`0x${string}`[];gasPrice?:undefined;maxFeePerBlobGas:`0x${string}`;maxFeePerGas:`0x${string}`;maxPriorityFeePerGas:`0x${string}`;accessList:AccessList;authorizationList?:undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`|null;yParity?:`0x${string}`|undefined;}": {
            /** @description Number of block containing this transaction or `null` if pending */
            blockNumber: string | null;
            /** @description Hash of block containing this transaction or `null` if pending */
            blockHash: string | null;
            /** @description Value in wei sent with this transaction */
            value: string;
            /** @description Chain ID that this transaction is valid on. */
            chainId: string;
            /** @description ECDSA signature s */
            s: string;
            /** @description Transaction sender */
            from: string;
            /** @description Transaction recipient or `null` if deploying a contract */
            to: string | null;
            /** @description Unique number identifying this transaction */
            nonce: string;
            /** @description ECDSA recovery ID */
            v: string;
            /** @description ECDSA signature r */
            r: string;
            /** @constant */
            type: "0x3";
            /** @description Gas provided for transaction execution */
            gas: string;
            /** @description List of versioned blob hashes associated with the transaction's blobs. */
            blobVersionedHashes: string[];
            /** @description Maximum total fee per gas sender is willing to pay for blob gas (in wei). */
            maxFeePerBlobGas: string;
            /** @description Total fee per gas in wei (gasPrice/baseFeePerGas + maxPriorityFeePerGas). */
            maxFeePerGas: string;
            /** @description Max priority fee per gas (in wei). */
            maxPriorityFeePerGas: string;
            /** @description EIP-2930 Access List. */
            accessList: {
                address: string;
                storageKeys: string[];
            }[];
            /** @description Hash of this transaction */
            hash: string;
            /** @description Unix timestamp of when this block was included */
            blockTimestamp?: string;
            /** @description Contract code or a hashed method call */
            input: string;
            /** @description Index of this transaction in the block or `null` if pending */
            transactionIndex: string | null;
            /** @description The parity of the y-value of the secp256k1 signature. */
            yParity?: string;
        };
        "{blockNumber:`0x${string}`|null;blockHash:`0x${string}`|null;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x4\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice?:undefined;maxFeePerBlobGas?:undefined;maxFeePerGas:`0x${string}`;maxPriorityFeePerGas:`0x${string}`;accessList:AccessList;authorizationList?:RpcAuthorizationList|undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`|null;yParity?:`0x${string}`|undefined;}": {
            /** @description Number of block containing this transaction or `null` if pending */
            blockNumber: string | null;
            /** @description Hash of block containing this transaction or `null` if pending */
            blockHash: string | null;
            /** @description Value in wei sent with this transaction */
            value: string;
            /** @description Chain ID that this transaction is valid on. */
            chainId: string;
            /** @description ECDSA signature s */
            s: string;
            /** @description Transaction sender */
            from: string;
            /** @description Transaction recipient or `null` if deploying a contract */
            to: string | null;
            /** @description Unique number identifying this transaction */
            nonce: string;
            /** @description ECDSA recovery ID */
            v: string;
            /** @description ECDSA signature r */
            r: string;
            /** @constant */
            type: "0x4";
            /** @description Gas provided for transaction execution */
            gas: string;
            /** @description Total fee per gas in wei (gasPrice/baseFeePerGas + maxPriorityFeePerGas). */
            maxFeePerGas: string;
            /** @description Max priority fee per gas (in wei). */
            maxPriorityFeePerGas: string;
            /** @description EIP-2930 Access List. */
            accessList: {
                address: string;
                storageKeys: string[];
            }[];
            authorizationList?: {
                /** @description Address of the contract to set as code for the Authority. */
                address: string;
                /** @description Chain ID to authorize. */
                chainId: string;
                /** @description Nonce of the Authority to authorize. */
                nonce: string;
                /** @description ECDSA r value. */
                r: string;
                /** @description ECDSA s value. */
                s: string;
                /** @description y parity. */
                yParity: string;
            }[];
            /** @description Hash of this transaction */
            hash: string;
            /** @description Unix timestamp of when this block was included */
            blockTimestamp?: string;
            /** @description Contract code or a hashed method call */
            input: string;
            /** @description Index of this transaction in the block or `null` if pending */
            transactionIndex: string | null;
            /** @description The parity of the y-value of the secp256k1 signature. */
            yParity?: string;
        };
        ReceiptWaitReceipt: {
            chainId: number;
            observedAt: string;
        } & {
            receipt: {
                /** @description The actual value per gas deducted from the sender's account for blob gas. Only specified for blob transactions as defined by EIP-4844. */
                blobGasPrice?: string;
                /** @description The amount of blob gas used. Only specified for blob transactions as defined by EIP-4844. */
                blobGasUsed?: string;
                /** @description Hash of block containing this transaction */
                blockHash: string;
                /** @description Number of block containing this transaction */
                blockNumber: string;
                /** @description Unix timestamp of when this block was included */
                blockTimestamp?: string;
                /** @description Address of new contract or `null` if no contract was created */
                contractAddress?: string | null;
                /** @description Gas used by this and all preceding transactions in this block */
                cumulativeGasUsed: string;
                /** @description Pre-London, it is equal to the transaction's gasPrice. Post-London, it is equal to the actual gas price paid for inclusion. */
                effectiveGasPrice: string;
                /** @description Transaction sender */
                from: string;
                /** @description Gas used by this transaction */
                gasUsed: string;
                /** @description List of log objects generated by this transaction */
                logs: components["schemas"]["Log<`0x${string}`,`0x${string}`,false>"][];
                /** @description Logs bloom filter */
                logsBloom: string;
                /** @description The post-transaction state root. Only specified for transactions included before the Byzantium upgrade. */
                root?: string;
                /** @description `success` if this transaction was successful or `reverted` if it failed */
                status: components["schemas"]["status"];
                /** @description Transaction recipient or `null` if deploying a contract */
                to: string | null;
                /** @description Hash of this transaction */
                transactionHash: string;
                /** @description Index of this transaction in the block */
                transactionIndex: string;
                /** @description Transaction type */
                type: components["schemas"]["TransactionType"];
            } | null;
        };
        "Log<`0x${string}`,`0x${string}`,false>": {
            /** @description The address from which this log originated */
            address: string;
            /** @description Hash of block containing this log or `null` if pending */
            blockHash: string;
            /** @description Number of block containing this log or `null` if pending */
            blockNumber: string;
            /** @description Timestamp of block containing this log or `null` if pending */
            blockTimestamp?: string;
            /** @description Contains the non-indexed arguments of the log */
            data: string;
            /** @description Index of this log within its block or `null` if pending */
            logIndex: string;
            /** @description Hash of the transaction that created this log or `null` if pending */
            transactionHash: string;
            /** @description Index of the transaction that created this log or `null` if pending */
            transactionIndex: string;
            /** @description `true` if this filter has been destroyed and is invalid */
            removed: boolean;
        } & {
            topics: unknown[] | [
                string
            ];
        };
        /** @enum {string} */
        status: "0x0" | "0x1";
        TransactionType: (Record<string, never> & string) | ("0x0" | "0x1" | "0x2" | "0x3" | "0x4");
        ReceiptWaitBlock: {
            chainId: number;
            observedAt: string;
        } & {
            block: {
                /** @description Base fee per gas */
                baseFeePerGas: string | null;
                /** @description Total used blob gas by all transactions in this block */
                blobGasUsed: string;
                /** @description Difficulty for this block */
                difficulty: string;
                /** @description Excess blob gas */
                excessBlobGas: string;
                /** @description "Extra data" field of this block */
                extraData: string;
                /** @description Maximum gas allowed in this block */
                gasLimit: string;
                /** @description Total used gas by all transactions in this block */
                gasUsed: string;
                /** @description Block hash or `null` if pending */
                hash: string;
                /** @description Logs bloom filter or `null` if pending */
                logsBloom: string;
                /** @description Address that received this block’s mining rewards, COINBASE address */
                miner: string;
                /** @description Unique identifier for the block. */
                mixHash: string;
                /** @description Proof-of-work hash or `null` if pending */
                nonce: string;
                /** @description Block number or `null` if pending */
                number: string;
                /** @description Root of the parent beacon chain block */
                parentBeaconBlockRoot?: string;
                /** @description Parent block hash */
                parentHash: string;
                /** @description Root of the this block’s receipts trie */
                receiptsRoot: string;
                sealFields: string[];
                /** @description SHA3 of the uncles data in this block */
                sha3Uncles: string;
                /** @description Size of this block in bytes */
                size: string;
                /** @description Root of this block’s final state trie */
                stateRoot: string;
                /** @description Unix timestamp of when this block was collated */
                timestamp: string;
                /** @description Total difficulty of the chain until this block */
                totalDifficulty: string | null;
                /** @description List of transaction objects or hashes */
                transactions: components["schemas"]["RpcTransaction<false>"][];
                /** @description Root of this block’s transaction trie */
                transactionsRoot: string;
                /** @description List of uncle hashes */
                uncles: string[];
                /** @description List of withdrawal objects */
                withdrawals?: {
                    address: string;
                    amount: string;
                    index: string;
                    validatorIndex: string;
                }[];
                /** @description Root of the this block’s withdrawals trie */
                withdrawalsRoot?: string;
            } | null;
        };
        "RpcTransaction<false>": components["schemas"]["{blockNumber:`0x${string}`;blockHash:`0x${string}`;value:`0x${string}`;chainId?:`0x${string}`|undefined;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x0\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice:`0x${string}`;maxFeePerBlobGas?:undefined;maxFeePerGas?:undefined;maxPriorityFeePerGas?:undefined;accessList?:undefined;authorizationList?:undefined;hash:`0x${string}`;yParity?:undefined;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`;}"] | components["schemas"]["{blockNumber:`0x${string}`;blockHash:`0x${string}`;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x1\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice:`0x${string}`;maxFeePerBlobGas?:undefined;maxFeePerGas?:undefined;maxPriorityFeePerGas?:undefined;accessList:AccessList;authorizationList?:undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`;yParity?:`0x${string}`|undefined;}"] | components["schemas"]["{blockNumber:`0x${string}`;blockHash:`0x${string}`;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x2\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice?:undefined;maxFeePerBlobGas?:undefined;maxFeePerGas:`0x${string}`;maxPriorityFeePerGas:`0x${string}`;accessList:AccessList;authorizationList?:undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`;yParity?:`0x${string}`|undefined;}"] | components["schemas"]["{blockNumber:`0x${string}`;blockHash:`0x${string}`;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x3\";gas:`0x${string}`;blobVersionedHashes:readonly`0x${string}`[];gasPrice?:undefined;maxFeePerBlobGas:`0x${string}`;maxFeePerGas:`0x${string}`;maxPriorityFeePerGas:`0x${string}`;accessList:AccessList;authorizationList?:undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`;yParity?:`0x${string}`|undefined;}"] | components["schemas"]["{blockNumber:`0x${string}`;blockHash:`0x${string}`;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x4\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice?:undefined;maxFeePerBlobGas?:undefined;maxFeePerGas:`0x${string}`;maxPriorityFeePerGas:`0x${string}`;accessList:AccessList;authorizationList?:RpcAuthorizationList|undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`;yParity?:`0x${string}`|undefined;}"];
        "{blockNumber:`0x${string}`;blockHash:`0x${string}`;value:`0x${string}`;chainId?:`0x${string}`|undefined;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x0\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice:`0x${string}`;maxFeePerBlobGas?:undefined;maxFeePerGas?:undefined;maxPriorityFeePerGas?:undefined;accessList?:undefined;authorizationList?:undefined;hash:`0x${string}`;yParity?:undefined;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`;}": {
            /** @description Number of block containing this transaction or `null` if pending */
            blockNumber: string;
            /** @description Hash of block containing this transaction or `null` if pending */
            blockHash: string;
            /** @description Value in wei sent with this transaction */
            value: string;
            /** @description Chain ID that this transaction is valid on. */
            chainId?: string;
            /** @description ECDSA signature s */
            s: string;
            /** @description Transaction sender */
            from: string;
            /** @description Transaction recipient or `null` if deploying a contract */
            to: string | null;
            /** @description Unique number identifying this transaction */
            nonce: string;
            /** @description ECDSA recovery ID */
            v: string;
            /** @description ECDSA signature r */
            r: string;
            /** @constant */
            type: "0x0";
            /** @description Gas provided for transaction execution */
            gas: string;
            /** @description Base fee per gas. */
            gasPrice: string;
            /** @description Hash of this transaction */
            hash: string;
            /** @description Unix timestamp of when this block was included */
            blockTimestamp?: string;
            /** @description Contract code or a hashed method call */
            input: string;
            /** @description Index of this transaction in the block or `null` if pending */
            transactionIndex: string;
        };
        "{blockNumber:`0x${string}`;blockHash:`0x${string}`;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x1\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice:`0x${string}`;maxFeePerBlobGas?:undefined;maxFeePerGas?:undefined;maxPriorityFeePerGas?:undefined;accessList:AccessList;authorizationList?:undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`;yParity?:`0x${string}`|undefined;}": {
            /** @description Number of block containing this transaction or `null` if pending */
            blockNumber: string;
            /** @description Hash of block containing this transaction or `null` if pending */
            blockHash: string;
            /** @description Value in wei sent with this transaction */
            value: string;
            /** @description Chain ID that this transaction is valid on. */
            chainId: string;
            /** @description ECDSA signature s */
            s: string;
            /** @description Transaction sender */
            from: string;
            /** @description Transaction recipient or `null` if deploying a contract */
            to: string | null;
            /** @description Unique number identifying this transaction */
            nonce: string;
            /** @description ECDSA recovery ID */
            v: string;
            /** @description ECDSA signature r */
            r: string;
            /** @constant */
            type: "0x1";
            /** @description Gas provided for transaction execution */
            gas: string;
            /** @description Base fee per gas. */
            gasPrice: string;
            /** @description EIP-2930 Access List. */
            accessList: {
                address: string;
                storageKeys: string[];
            }[];
            /** @description Hash of this transaction */
            hash: string;
            /** @description Unix timestamp of when this block was included */
            blockTimestamp?: string;
            /** @description Contract code or a hashed method call */
            input: string;
            /** @description Index of this transaction in the block or `null` if pending */
            transactionIndex: string;
            /** @description The parity of the y-value of the secp256k1 signature. */
            yParity?: string;
        };
        "{blockNumber:`0x${string}`;blockHash:`0x${string}`;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x2\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice?:undefined;maxFeePerBlobGas?:undefined;maxFeePerGas:`0x${string}`;maxPriorityFeePerGas:`0x${string}`;accessList:AccessList;authorizationList?:undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`;yParity?:`0x${string}`|undefined;}": {
            /** @description Number of block containing this transaction or `null` if pending */
            blockNumber: string;
            /** @description Hash of block containing this transaction or `null` if pending */
            blockHash: string;
            /** @description Value in wei sent with this transaction */
            value: string;
            /** @description Chain ID that this transaction is valid on. */
            chainId: string;
            /** @description ECDSA signature s */
            s: string;
            /** @description Transaction sender */
            from: string;
            /** @description Transaction recipient or `null` if deploying a contract */
            to: string | null;
            /** @description Unique number identifying this transaction */
            nonce: string;
            /** @description ECDSA recovery ID */
            v: string;
            /** @description ECDSA signature r */
            r: string;
            /** @constant */
            type: "0x2";
            /** @description Gas provided for transaction execution */
            gas: string;
            /** @description Total fee per gas in wei (gasPrice/baseFeePerGas + maxPriorityFeePerGas). */
            maxFeePerGas: string;
            /** @description Max priority fee per gas (in wei). */
            maxPriorityFeePerGas: string;
            /** @description EIP-2930 Access List. */
            accessList: {
                address: string;
                storageKeys: string[];
            }[];
            /** @description Hash of this transaction */
            hash: string;
            /** @description Unix timestamp of when this block was included */
            blockTimestamp?: string;
            /** @description Contract code or a hashed method call */
            input: string;
            /** @description Index of this transaction in the block or `null` if pending */
            transactionIndex: string;
            /** @description The parity of the y-value of the secp256k1 signature. */
            yParity?: string;
        };
        "{blockNumber:`0x${string}`;blockHash:`0x${string}`;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x3\";gas:`0x${string}`;blobVersionedHashes:readonly`0x${string}`[];gasPrice?:undefined;maxFeePerBlobGas:`0x${string}`;maxFeePerGas:`0x${string}`;maxPriorityFeePerGas:`0x${string}`;accessList:AccessList;authorizationList?:undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`;yParity?:`0x${string}`|undefined;}": {
            /** @description Number of block containing this transaction or `null` if pending */
            blockNumber: string;
            /** @description Hash of block containing this transaction or `null` if pending */
            blockHash: string;
            /** @description Value in wei sent with this transaction */
            value: string;
            /** @description Chain ID that this transaction is valid on. */
            chainId: string;
            /** @description ECDSA signature s */
            s: string;
            /** @description Transaction sender */
            from: string;
            /** @description Transaction recipient or `null` if deploying a contract */
            to: string | null;
            /** @description Unique number identifying this transaction */
            nonce: string;
            /** @description ECDSA recovery ID */
            v: string;
            /** @description ECDSA signature r */
            r: string;
            /** @constant */
            type: "0x3";
            /** @description Gas provided for transaction execution */
            gas: string;
            /** @description List of versioned blob hashes associated with the transaction's blobs. */
            blobVersionedHashes: string[];
            /** @description Maximum total fee per gas sender is willing to pay for blob gas (in wei). */
            maxFeePerBlobGas: string;
            /** @description Total fee per gas in wei (gasPrice/baseFeePerGas + maxPriorityFeePerGas). */
            maxFeePerGas: string;
            /** @description Max priority fee per gas (in wei). */
            maxPriorityFeePerGas: string;
            /** @description EIP-2930 Access List. */
            accessList: {
                address: string;
                storageKeys: string[];
            }[];
            /** @description Hash of this transaction */
            hash: string;
            /** @description Unix timestamp of when this block was included */
            blockTimestamp?: string;
            /** @description Contract code or a hashed method call */
            input: string;
            /** @description Index of this transaction in the block or `null` if pending */
            transactionIndex: string;
            /** @description The parity of the y-value of the secp256k1 signature. */
            yParity?: string;
        };
        "{blockNumber:`0x${string}`;blockHash:`0x${string}`;value:`0x${string}`;chainId:`0x${string}`;s:`0x${string}`;from:`0x${string}`;to:`0x${string}`|null;nonce:`0x${string}`;v:`0x${string}`;r:`0x${string}`;type:\"0x4\";gas:`0x${string}`;blobVersionedHashes?:undefined;gasPrice?:undefined;maxFeePerBlobGas?:undefined;maxFeePerGas:`0x${string}`;maxPriorityFeePerGas:`0x${string}`;accessList:AccessList;authorizationList?:RpcAuthorizationList|undefined;hash:`0x${string}`;blockTimestamp?:`0x${string}`|undefined;input:`0x${string}`;transactionIndex:`0x${string}`;yParity?:`0x${string}`|undefined;}": {
            /** @description Number of block containing this transaction or `null` if pending */
            blockNumber: string;
            /** @description Hash of block containing this transaction or `null` if pending */
            blockHash: string;
            /** @description Value in wei sent with this transaction */
            value: string;
            /** @description Chain ID that this transaction is valid on. */
            chainId: string;
            /** @description ECDSA signature s */
            s: string;
            /** @description Transaction sender */
            from: string;
            /** @description Transaction recipient or `null` if deploying a contract */
            to: string | null;
            /** @description Unique number identifying this transaction */
            nonce: string;
            /** @description ECDSA recovery ID */
            v: string;
            /** @description ECDSA signature r */
            r: string;
            /** @constant */
            type: "0x4";
            /** @description Gas provided for transaction execution */
            gas: string;
            /** @description Total fee per gas in wei (gasPrice/baseFeePerGas + maxPriorityFeePerGas). */
            maxFeePerGas: string;
            /** @description Max priority fee per gas (in wei). */
            maxPriorityFeePerGas: string;
            /** @description EIP-2930 Access List. */
            accessList: {
                address: string;
                storageKeys: string[];
            }[];
            authorizationList?: {
                /** @description Address of the contract to set as code for the Authority. */
                address: string;
                /** @description Chain ID to authorize. */
                chainId: string;
                /** @description Nonce of the Authority to authorize. */
                nonce: string;
                /** @description ECDSA r value. */
                r: string;
                /** @description ECDSA s value. */
                s: string;
                /** @description y parity. */
                yParity: string;
            }[];
            /** @description Hash of this transaction */
            hash: string;
            /** @description Unix timestamp of when this block was included */
            blockTimestamp?: string;
            /** @description Contract code or a hashed method call */
            input: string;
            /** @description Index of this transaction in the block or `null` if pending */
            transactionIndex: string;
            /** @description The parity of the y-value of the secp256k1 signature. */
            yParity?: string;
        };
        TokenApprovalGas: {
            owner: string;
            token: string;
            amount: string;
        } & {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            spender: string;
            gas: string;
            /** @constant */
            blockTag: "latest";
        };
        Permit2ContextRequest: {
            /** @constant */
            mode: "verify";
        } | {
            /** @constant */
            mode: "nonce";
            owner: string;
        } | {
            /** @constant */
            mode: "allowances";
            owner: string;
            tokens: string[];
        };
        Permit2Context: ({
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            helpers: null | string;
            permit2: string;
        } & {
            /** @constant */
            mode: "verify";
            result: {
                code: string;
            };
        }) | ({
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            helpers: null | string;
            permit2: string;
        } & {
            /** @constant */
            mode: "nonce";
            result: {
                owner: string;
                nonce: string;
            };
        }) | ({
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            helpers: null | string;
            permit2: string;
        } & {
            /** @constant */
            mode: "allowances";
            result: {
                owner: string;
                allowances: {
                    token: string;
                    value: string;
                }[];
            };
        });
        BasketPreviewRequest: {
            /** @constant */
            mode: "issue-exact-in";
            maximumAmountsIn: string[];
        } | {
            /** @constant */
            mode: "issue-exact-out";
            netCygldOut: string;
        } | {
            /** @constant */
            mode: "redeem-exact-in";
            grossCygldIn: string;
        } | {
            /** @constant */
            mode: "redeem-exact-out";
            minimumOutputs: {
                kind: number;
                token: string;
                id: string;
                minimumAmount: string;
            }[];
        };
        BasketPreview: ({
            basketModel?: {
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                state: {
                    assets: string[];
                    weights: string[];
                    conversions: string[];
                    issueFee: string;
                    helperFee: string;
                    redeemFee: string;
                    supply: string;
                    maxSupply: string;
                    effectiveCap: string;
                    available: string[];
                    recoveryShares: string[];
                    recoveryValues: string[];
                    descriptors: {
                        kind: number;
                        token: string;
                        id: string;
                    }[];
                };
            } | null;
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            helpers: string;
        } & {
            /** @constant */
            mode: "issue-exact-in";
            result: {
                netCygldOut: string;
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
                amountsInExact: string[];
                orderedCoreAssets: string[];
            };
        }) | ({
            basketModel?: {
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                state: {
                    assets: string[];
                    weights: string[];
                    conversions: string[];
                    issueFee: string;
                    helperFee: string;
                    redeemFee: string;
                    supply: string;
                    maxSupply: string;
                    effectiveCap: string;
                    available: string[];
                    recoveryShares: string[];
                    recoveryValues: string[];
                    descriptors: {
                        kind: number;
                        token: string;
                        id: string;
                    }[];
                };
            } | null;
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            helpers: string;
        } & {
            /** @constant */
            mode: "issue-exact-out";
            result: {
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
                amountsInExact: string[];
                orderedCoreAssets: string[];
            };
        }) | ({
            basketModel?: {
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                state: {
                    assets: string[];
                    weights: string[];
                    conversions: string[];
                    issueFee: string;
                    helperFee: string;
                    redeemFee: string;
                    supply: string;
                    maxSupply: string;
                    effectiveCap: string;
                    available: string[];
                    recoveryShares: string[];
                    recoveryValues: string[];
                    descriptors: {
                        kind: number;
                        token: string;
                        id: string;
                    }[];
                };
            } | null;
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            helpers: string;
        } & {
            /** @constant */
            mode: "redeem-exact-in";
            result: {
                projectedCoreOutputs: {
                    kind: number;
                    token: string;
                    id: string;
                    amount: string;
                }[];
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
            };
        }) | ({
            basketModel?: {
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                state: {
                    assets: string[];
                    weights: string[];
                    conversions: string[];
                    issueFee: string;
                    helperFee: string;
                    redeemFee: string;
                    supply: string;
                    maxSupply: string;
                    effectiveCap: string;
                    available: string[];
                    recoveryShares: string[];
                    recoveryValues: string[];
                    descriptors: {
                        kind: number;
                        token: string;
                        id: string;
                    }[];
                };
            } | null;
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            helpers: string;
        } & {
            /** @constant */
            mode: "redeem-exact-out";
            result: {
                grossCygldIn: string;
                projectedCoreOutputs: {
                    kind: number;
                    token: string;
                    id: string;
                    amount: string;
                }[];
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
            };
        });
        TokenPreviewRequest: {
            /** @constant */
            mode: "issue-token-exact-in";
            inputToken: string;
            inputAmount: string;
            quotes: {
                adapter: string;
                amountIn: string;
                minimumAmountOut: string;
                data: string;
                routePlan?: {
                    /** @constant */
                    version: 1;
                    /** @enum {string} */
                    executionContext: "helpers-core" | "helpers-market";
                    /** @enum {string} */
                    mode: "exactIn" | "exactOut";
                    tokenIn: string;
                    tokenOut: string;
                    branches: {
                        amountIn: string;
                        hops: {
                            pool: components["schemas"]["RoutePoolRef"];
                            zeroForOne: boolean;
                        }[];
                    }[];
                    inputAmount: string;
                    outputAmount: string;
                    limit: string;
                    deadline: string;
                };
            }[];
        } | {
            /** @constant */
            mode: "issue-native-exact-in";
            inputAmount: string;
            quotes: {
                adapter: string;
                amountIn: string;
                minimumAmountOut: string;
                data: string;
                routePlan?: {
                    /** @constant */
                    version: 1;
                    /** @enum {string} */
                    executionContext: "helpers-core" | "helpers-market";
                    /** @enum {string} */
                    mode: "exactIn" | "exactOut";
                    tokenIn: string;
                    tokenOut: string;
                    branches: {
                        amountIn: string;
                        hops: {
                            pool: components["schemas"]["RoutePoolRef"];
                            zeroForOne: boolean;
                        }[];
                    }[];
                    inputAmount: string;
                    outputAmount: string;
                    limit: string;
                    deadline: string;
                };
            }[];
        } | {
            /** @constant */
            mode: "issue-token-exact-out";
            inputToken: string;
            maximumInputAmount: string;
            netCygldOut: string;
            quotes: {
                adapter: string;
                amountIn: string;
                minimumAmountOut: string;
                data: string;
                routePlan?: {
                    /** @constant */
                    version: 1;
                    /** @enum {string} */
                    executionContext: "helpers-core" | "helpers-market";
                    /** @enum {string} */
                    mode: "exactIn" | "exactOut";
                    tokenIn: string;
                    tokenOut: string;
                    branches: {
                        amountIn: string;
                        hops: {
                            pool: components["schemas"]["RoutePoolRef"];
                            zeroForOne: boolean;
                        }[];
                    }[];
                    inputAmount: string;
                    outputAmount: string;
                    limit: string;
                    deadline: string;
                };
            }[];
        } | {
            /** @constant */
            mode: "issue-native-exact-out";
            maximumNativeIn: string;
            netCygldOut: string;
            quotes: {
                adapter: string;
                amountIn: string;
                minimumAmountOut: string;
                data: string;
                routePlan?: {
                    /** @constant */
                    version: 1;
                    /** @enum {string} */
                    executionContext: "helpers-core" | "helpers-market";
                    /** @enum {string} */
                    mode: "exactIn" | "exactOut";
                    tokenIn: string;
                    tokenOut: string;
                    branches: {
                        amountIn: string;
                        hops: {
                            pool: components["schemas"]["RoutePoolRef"];
                            zeroForOne: boolean;
                        }[];
                    }[];
                    inputAmount: string;
                    outputAmount: string;
                    limit: string;
                    deadline: string;
                };
            }[];
        } | {
            /** @constant */
            mode: "redeem-token-exact-in";
            outputToken: string;
            grossCygldIn: string;
            quotes: {
                adapter: string;
                minimumAmountOut: string;
                data: string;
                routePlan?: {
                    /** @constant */
                    version: 1;
                    /** @enum {string} */
                    executionContext: "helpers-core" | "helpers-market";
                    /** @enum {string} */
                    mode: "exactIn" | "exactOut";
                    tokenIn: string;
                    tokenOut: string;
                    branches: {
                        amountIn: string;
                        hops: {
                            pool: components["schemas"]["RoutePoolRef"];
                            zeroForOne: boolean;
                        }[];
                    }[];
                    inputAmount: string;
                    outputAmount: string;
                    limit: string;
                    deadline: string;
                };
            }[];
        } | {
            /** @constant */
            mode: "redeem-native-exact-in";
            grossCygldIn: string;
            quotes: {
                adapter: string;
                minimumAmountOut: string;
                data: string;
                routePlan?: {
                    /** @constant */
                    version: 1;
                    /** @enum {string} */
                    executionContext: "helpers-core" | "helpers-market";
                    /** @enum {string} */
                    mode: "exactIn" | "exactOut";
                    tokenIn: string;
                    tokenOut: string;
                    branches: {
                        amountIn: string;
                        hops: {
                            pool: components["schemas"]["RoutePoolRef"];
                            zeroForOne: boolean;
                        }[];
                    }[];
                    inputAmount: string;
                    outputAmount: string;
                    limit: string;
                    deadline: string;
                };
            }[];
        };
        TokenPreview: ({
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            helpers: string;
        } & {
            /** @enum {string} */
            mode: "issue-native-exact-in" | "issue-token-exact-in";
            result: {
                netCygldOut: string;
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
                orderedCoreAssets: string[];
            };
        }) | ({
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            helpers: string;
        } & {
            /** @enum {string} */
            mode: "issue-native-exact-out" | "issue-token-exact-out";
            result: {
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
                orderedCoreAssets: string[];
            };
        }) | ({
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            helpers: string;
        } & {
            /** @enum {string} */
            mode: "redeem-native-exact-in" | "redeem-token-exact-in";
            result: {
                minimumAmountOut: string;
                projectedCoreOutputs: {
                    kind: number;
                    token: string;
                    id: string;
                    amount: string;
                }[];
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
            };
        });
        RouteSearchEvent: {
            /** @constant */
            type: "progress";
            results: ({
                target: {
                    inputAsset: string;
                    outputAsset: string;
                    amount: string;
                };
                best: {
                    path: string;
                    quote: string;
                    /** @enum {string} */
                    route: "direct" | "identity" | "mixed" | "viaWeth";
                    feeInfo: string;
                    routePlan?: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                } | null;
                attempted: number;
                succeeded: number;
                failures: {
                    path: string;
                    rpcCode: number;
                    /** @enum {string} */
                    code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                    /** @description Canonical preview rejection evidence; absent quantities were not provided by the contract. */
                    constraint?: {
                        /** @enum {string} */
                        kind?: "issuance-cap" | "redemption-capacity" | "redemption-supply";
                        /** @enum {string} */
                        quantity?: "core-output-minima" | "gross-cygld-input" | "gross-cygld-mint";
                        /** @enum {string} */
                        limitKind?: "effective-supply-cap" | "maximum-total-supply";
                        requestedRaw?: string;
                        availableRaw?: string;
                        currentSupplyRaw?: string;
                        limitRaw?: string;
                    };
                    /** @description Optional observed RPC failure context; provider text is sanitized before publication. */
                    diagnostics?: {
                        rpcMethod?: string;
                        stage?: string;
                        elapsedMs?: number;
                        upstreamErrorCode?: number;
                        providerMessage?: string;
                        httpStatus?: number;
                        /** @enum {string} */
                        failureType?: "backend-deadline" | "http-error" | "provider-timeout" | "rpc-error" | "transport-error";
                        errorSelector?: string;
                        errorName?: string;
                    };
                }[];
            } & {
                total: number;
            })[];
        } | {
            /** @constant */
            type: "complete";
            value: {
                /** @enum {string} */
                mode: "exact-in" | "exact-out";
                /** @constant */
                qualification: "sdk";
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                results: {
                    target: {
                        inputAsset: string;
                        outputAsset: string;
                        amount: string;
                    };
                    best: {
                        path: string;
                        quote: string;
                        /** @enum {string} */
                        route: "direct" | "identity" | "mixed" | "viaWeth";
                        feeInfo: string;
                        routePlan?: {
                            /** @constant */
                            version: 1;
                            /** @enum {string} */
                            executionContext: "helpers-core" | "helpers-market";
                            /** @enum {string} */
                            mode: "exactIn" | "exactOut";
                            tokenIn: string;
                            tokenOut: string;
                            branches: {
                                amountIn: string;
                                hops: {
                                    pool: components["schemas"]["RoutePoolRef"];
                                    zeroForOne: boolean;
                                }[];
                            }[];
                            inputAmount: string;
                            outputAmount: string;
                            limit: string;
                            deadline: string;
                        };
                    } | null;
                    attempted: number;
                    succeeded: number;
                    failures: {
                        path: string;
                        rpcCode: number;
                        /** @enum {string} */
                        code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        /** @description Canonical preview rejection evidence; absent quantities were not provided by the contract. */
                        constraint?: {
                            /** @enum {string} */
                            kind?: "issuance-cap" | "redemption-capacity" | "redemption-supply";
                            /** @enum {string} */
                            quantity?: "core-output-minima" | "gross-cygld-input" | "gross-cygld-mint";
                            /** @enum {string} */
                            limitKind?: "effective-supply-cap" | "maximum-total-supply";
                            requestedRaw?: string;
                            availableRaw?: string;
                            currentSupplyRaw?: string;
                            limitRaw?: string;
                        };
                        /** @description Optional observed RPC failure context; provider text is sanitized before publication. */
                        diagnostics?: {
                            rpcMethod?: string;
                            stage?: string;
                            elapsedMs?: number;
                            upstreamErrorCode?: number;
                            providerMessage?: string;
                            httpStatus?: number;
                            /** @enum {string} */
                            failureType?: "backend-deadline" | "http-error" | "provider-timeout" | "rpc-error" | "transport-error";
                            errorSelector?: string;
                            errorName?: string;
                        };
                    }[];
                }[];
                metrics: {
                    candidateCalls: number;
                    rpcReads: number;
                    rpcReadsRequested: number;
                    /** @constant */
                    rpcReadsScope?: "coordinator";
                    rpcReadsCoalesced: number;
                    rpcReadsReused: number;
                    contextMs: number;
                    quotesMs: number;
                    canonicalityMs: number;
                    totalMs: number;
                };
            };
        } | {
            /** @constant */
            type: "error";
            error: string;
            correlationId: string;
            /** @enum {string} */
            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
            /** @description Canonical preview rejection evidence; absent quantities were not provided by the contract. */
            constraint?: {
                /** @enum {string} */
                kind?: "issuance-cap" | "redemption-capacity" | "redemption-supply";
                /** @enum {string} */
                quantity?: "core-output-minima" | "gross-cygld-input" | "gross-cygld-mint";
                /** @enum {string} */
                limitKind?: "effective-supply-cap" | "maximum-total-supply";
                requestedRaw?: string;
                availableRaw?: string;
                currentSupplyRaw?: string;
                limitRaw?: string;
            };
            /** @description Optional observed RPC failure context; provider text is sanitized before publication. */
            diagnostics?: {
                rpcMethod?: string;
                stage?: string;
                elapsedMs?: number;
                upstreamErrorCode?: number;
                providerMessage?: string;
                httpStatus?: number;
                /** @enum {string} */
                failureType?: "backend-deadline" | "http-error" | "provider-timeout" | "rpc-error" | "transport-error";
                errorSelector?: string;
                errorName?: string;
            };
            /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
            quoteDiagnostics?: {
                /** @enum {string} */
                phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                elapsedMs?: number;
                qualified?: boolean;
                inversionIteration?: number;
                routeWave?: {
                    elapsedMs?: number;
                    subphaseElapsedMs?: number;
                    /** @enum {string} */
                    subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                    /** @enum {string} */
                    mode?: "exact-in" | "exact-out";
                    legacyCandidates?: number;
                    legacyCompleted?: number;
                    typedEnumerated?: number;
                    typedCompleted?: number;
                    typedPending?: number;
                    sdkRequests?: number;
                    sdkWaiting?: number;
                    sdkLockWaitMs?: number;
                    sdkExchangeMs?: number;
                    legs?: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        count: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            index: number;
                            inputAsset?: string;
                            outputAsset?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            amount?: string;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            started: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            succeeded: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            failed: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            cancelled: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            pending: number;
                            bestAvailable: boolean;
                            failureCounts: {
                                code: components["schemas"]["QuoteErrorCode"];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                count: number;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedFailureCodes: number;
                            bestPools: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools: number;
                        }[];
                    };
                };
                providerQualifications?: {
                    /** @enum {string} */
                    provider: "core" | "market";
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    attempts: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    qualified: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    rejected: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    notImproved: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    cancelled: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    superseded: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    pending: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    omittedRows: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    selectedAttempt?: number;
                    /** @enum {string} */
                    selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    firstQualifiedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    selectionMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    canonicalCompletedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    cleanupCompletedMs?: number;
                    rows: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempt: number;
                        /** @enum {string} */
                        stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                        /** @enum {string} */
                        outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                        /** @enum {string} */
                        code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        targetAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        minimumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountIn?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountIn?: string;
                        /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                        startedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        completedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        elapsedMs?: number;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        executionAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedInput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedOutput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        inputMaximum?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        outputMinimum?: string;
                        pools?: {
                            /** @enum {string} */
                            protocol: "v2" | "v3" | "v4";
                            /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                            poolId?: string;
                            poolAddress?: string;
                        }[];
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedPools?: number;
                    }[];
                };
            };
        };
        QuoteIntentEvent: ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "model";
            /** @description Display-only source data. No transaction tuples or execution readiness. */
            value: {
                revision: number;
                intent: components["schemas"]["Omit<QuoteIntentRequest,\"deadline\"|\"retainedPlan\">"];
                routes: {
                    tokens: string[];
                    fees: number[];
                    context: {
                        chainId: number;
                        blockNumber: string;
                        blockHash: string;
                        observedAt: string;
                    };
                    routePlan?: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                    protocols?: ("v2" | "v3" | "v4")[];
                    poolIds?: string[];
                    points: {
                        input: string;
                        output: string;
                        context?: {
                            chainId: number;
                            blockNumber: string;
                            blockHash: string;
                            observedAt: string;
                        };
                        recordedAt?: number;
                    }[];
                    exchangeRate?: {
                        numerator: string;
                        denominator: string;
                    };
                    exchangeContext?: {
                        chainId: number;
                        blockNumber: string;
                        blockHash: string;
                        observedAt: string;
                    };
                    feeRetention: {
                        numerator: string;
                        denominator: string;
                    };
                    localImpact?: {
                        numerator: string;
                        denominator: string;
                    };
                }[];
                whole: {
                    input: string;
                    display: string;
                    context: {
                        chainId: number;
                        blockNumber: string;
                        blockHash: string;
                        observedAt: string;
                    };
                    recordedAt: number;
                }[];
                protocol: {
                    context: {
                        chainId: number;
                        blockNumber: string;
                        blockHash: string;
                        observedAt: string;
                    };
                    state: {
                        assets: string[];
                        weights: string[];
                        conversions: string[];
                        issueFee: string;
                        helperFee: string;
                        redeemFee: string;
                        supply: string;
                        maxSupply: string;
                        effectiveCap: string;
                        available: string[];
                        recoveryShares: string[];
                        recoveryValues: string[];
                        descriptors: {
                            kind: number;
                            token: string;
                            id: string;
                        }[];
                    };
                } | null;
            };
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "progress";
            stage: string;
            completed: number;
            total: number;
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "estimate";
            amount: string;
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "qualified";
            value: {
                /** @enum {string} */
                mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                quotes: (({
                    adapter: string;
                    amountIn: string;
                    minimumAmountOut: string;
                    data: string;
                    routePlan?: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                } & {
                    outputAsset: string;
                }) | ({
                    adapter: string;
                    minimumAmountOut: string;
                    data: string;
                    routePlan?: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                } & {
                    inputAsset: string;
                    inputAmount: string;
                }))[];
                preview: {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    minimumAmountOut: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                };
                initialPreview: {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | {
                    grossCygldIn: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    minimumAmountOut: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | null;
                basketPreview: {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | {
                    grossCygldIn: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                };
                displayAmount: string;
                executionAmount: string;
                maximumInputAmount: string;
                slippageBps?: number;
                /** @description Expected input before execution cushions, including direct basket input. */
                expectedInputAmount?: string;
                requestedGrossCygldOut?: string;
                requestedNetCygldOut?: string;
                remainingGrossCapacity?: string;
                remainingNetCapacity?: string;
                expectedOutputAmount?: string;
                expectedCoreOutputs?: {
                    kind: number;
                    token: string;
                    id: string;
                    minimumAmount: string;
                }[];
                metrics: {
                    rpcReads: number;
                    rpcReadsRequested: number;
                    rpcReadsCoalesced: number;
                    rpcReadsReused: number;
                    /** @constant */
                    rpcReadsScope?: "coordinator";
                    candidateCalls: number;
                    iterations: number;
                    totalMs: number;
                } & {
                    firstQualifiedMs?: number;
                    selectionMs?: number;
                    canonicalCompletedMs?: number;
                    cleanupCompletedMs?: number;
                    finalizationMs?: number;
                };
                /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
                quoteDiagnostics?: {
                    /** @enum {string} */
                    phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                    elapsedMs?: number;
                    qualified?: boolean;
                    inversionIteration?: number;
                    routeWave?: {
                        elapsedMs?: number;
                        subphaseElapsedMs?: number;
                        /** @enum {string} */
                        subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                        /** @enum {string} */
                        mode?: "exact-in" | "exact-out";
                        legacyCandidates?: number;
                        legacyCompleted?: number;
                        typedEnumerated?: number;
                        typedCompleted?: number;
                        typedPending?: number;
                        sdkRequests?: number;
                        sdkWaiting?: number;
                        sdkLockWaitMs?: number;
                        sdkExchangeMs?: number;
                        legs?: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            count: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedRows: number;
                            rows: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                index: number;
                                inputAsset?: string;
                                outputAsset?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                amount?: string;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                started: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                succeeded: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                failed: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                cancelled: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                pending: number;
                                bestAvailable: boolean;
                                failureCounts: {
                                    code: components["schemas"]["QuoteErrorCode"];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    count: number;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedFailureCodes: number;
                                bestPools: {
                                    /** @enum {string} */
                                    protocol: "v2" | "v3" | "v4";
                                    /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                    poolId?: string;
                                    poolAddress?: string;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedPools: number;
                            }[];
                        };
                    };
                    providerQualifications?: {
                        /** @enum {string} */
                        provider: "core" | "market";
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempts: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        qualified: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        rejected: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        notImproved: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        cancelled: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        superseded: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        pending: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        selectedAttempt?: number;
                        /** @enum {string} */
                        selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        firstQualifiedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        selectionMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        canonicalCompletedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        cleanupCompletedMs?: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            attempt: number;
                            /** @enum {string} */
                            stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                            /** @enum {string} */
                            outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                            /** @enum {string} */
                            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            targetAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            minimumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountIn?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountIn?: string;
                            /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                            startedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            completedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            elapsedMs?: number;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            executionAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedInput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedOutput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            inputMaximum?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            outputMinimum?: string;
                            pools?: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools?: number;
                        }[];
                    };
                };
            } | {
                /** @constant */
                readOnly: true;
                /** @enum {string} */
                mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                slippageBps?: number;
                metrics?: {
                    rpcReads: number;
                    rpcReadsRequested: number;
                    rpcReadsCoalesced: number;
                    rpcReadsReused: number;
                    /** @constant */
                    rpcReadsScope?: "coordinator";
                    candidateCalls: number;
                    iterations: number;
                    totalMs: number;
                } & {
                    firstQualifiedMs?: number;
                    selectionMs?: number;
                    canonicalCompletedMs?: number;
                    cleanupCompletedMs?: number;
                    finalizationMs?: number;
                };
                displayAmount?: string;
                executionAmount?: string;
                maximumInputAmount?: string;
                expectedInputAmount?: string;
                expectedOutputAmount?: string;
                minimumAmountOut: string;
            };
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "invalidated";
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            /** @constant */
            reason?: "snapshot-changed";
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "complete";
            value: {
                /** @enum {string} */
                mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                quotes: (({
                    adapter: string;
                    amountIn: string;
                    minimumAmountOut: string;
                    data: string;
                    routePlan?: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                } & {
                    outputAsset: string;
                }) | ({
                    adapter: string;
                    minimumAmountOut: string;
                    data: string;
                    routePlan?: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                } & {
                    inputAsset: string;
                    inputAmount: string;
                }))[];
                preview: {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    minimumAmountOut: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                };
                initialPreview: {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | {
                    grossCygldIn: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    orderedCoreAssets: string[];
                } | {
                    minimumAmountOut: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | null;
                basketPreview: {
                    netCygldOut: string;
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                    amountsInExact: string[];
                    orderedCoreAssets: string[];
                } | {
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                } | {
                    grossCygldIn: string;
                    projectedCoreOutputs: {
                        kind: number;
                        token: string;
                        id: string;
                        amount: string;
                    }[];
                    fees: {
                        protocolFeeCygld: string;
                        helperFeeCygld: string;
                    };
                };
                displayAmount: string;
                executionAmount: string;
                maximumInputAmount: string;
                slippageBps?: number;
                /** @description Expected input before execution cushions, including direct basket input. */
                expectedInputAmount?: string;
                requestedGrossCygldOut?: string;
                requestedNetCygldOut?: string;
                remainingGrossCapacity?: string;
                remainingNetCapacity?: string;
                expectedOutputAmount?: string;
                expectedCoreOutputs?: {
                    kind: number;
                    token: string;
                    id: string;
                    minimumAmount: string;
                }[];
                metrics: {
                    rpcReads: number;
                    rpcReadsRequested: number;
                    rpcReadsCoalesced: number;
                    rpcReadsReused: number;
                    /** @constant */
                    rpcReadsScope?: "coordinator";
                    candidateCalls: number;
                    iterations: number;
                    totalMs: number;
                } & {
                    firstQualifiedMs?: number;
                    selectionMs?: number;
                    canonicalCompletedMs?: number;
                    cleanupCompletedMs?: number;
                    finalizationMs?: number;
                };
                /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
                quoteDiagnostics?: {
                    /** @enum {string} */
                    phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                    elapsedMs?: number;
                    qualified?: boolean;
                    inversionIteration?: number;
                    routeWave?: {
                        elapsedMs?: number;
                        subphaseElapsedMs?: number;
                        /** @enum {string} */
                        subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                        /** @enum {string} */
                        mode?: "exact-in" | "exact-out";
                        legacyCandidates?: number;
                        legacyCompleted?: number;
                        typedEnumerated?: number;
                        typedCompleted?: number;
                        typedPending?: number;
                        sdkRequests?: number;
                        sdkWaiting?: number;
                        sdkLockWaitMs?: number;
                        sdkExchangeMs?: number;
                        legs?: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            count: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedRows: number;
                            rows: {
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                index: number;
                                inputAsset?: string;
                                outputAsset?: string;
                                /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                                amount?: string;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                started: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                succeeded: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                failed: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                cancelled: number;
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                pending: number;
                                bestAvailable: boolean;
                                failureCounts: {
                                    code: components["schemas"]["QuoteErrorCode"];
                                    /** @description Bounded observation count; never an execution eligibility predicate. */
                                    count: number;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedFailureCodes: number;
                                bestPools: {
                                    /** @enum {string} */
                                    protocol: "v2" | "v3" | "v4";
                                    /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                    poolId?: string;
                                    poolAddress?: string;
                                }[];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                omittedPools: number;
                            }[];
                        };
                    };
                    providerQualifications?: {
                        /** @enum {string} */
                        provider: "core" | "market";
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempts: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        qualified: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        rejected: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        notImproved: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        cancelled: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        superseded: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        pending: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        selectedAttempt?: number;
                        /** @enum {string} */
                        selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        firstQualifiedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        selectionMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        canonicalCompletedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        cleanupCompletedMs?: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            attempt: number;
                            /** @enum {string} */
                            stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                            /** @enum {string} */
                            outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                            /** @enum {string} */
                            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            targetAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            minimumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountOut?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            maximumAmountIn?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            observedAmountIn?: string;
                            /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                            startedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            completedMs?: number;
                            /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                            elapsedMs?: number;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            executionAmount?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedInput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            quotedOutput?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            inputMaximum?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            outputMinimum?: string;
                            pools?: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools?: number;
                        }[];
                    };
                };
            } | {
                /** @constant */
                readOnly: true;
                /** @enum {string} */
                mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                slippageBps?: number;
                metrics?: {
                    rpcReads: number;
                    rpcReadsRequested: number;
                    rpcReadsCoalesced: number;
                    rpcReadsReused: number;
                    /** @constant */
                    rpcReadsScope?: "coordinator";
                    candidateCalls: number;
                    iterations: number;
                    totalMs: number;
                } & {
                    firstQualifiedMs?: number;
                    selectionMs?: number;
                    canonicalCompletedMs?: number;
                    cleanupCompletedMs?: number;
                    finalizationMs?: number;
                };
                displayAmount?: string;
                executionAmount?: string;
                maximumInputAmount?: string;
                expectedInputAmount?: string;
                expectedOutputAmount?: string;
                minimumAmountOut: string;
            };
        }) | ({
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            /** @constant */
            type: "error";
            error: string;
            correlationId: string;
            /** @enum {string} */
            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
            /** @description Canonical preview rejection evidence; absent quantities were not provided by the contract. */
            constraint?: {
                /** @enum {string} */
                kind?: "issuance-cap" | "redemption-capacity" | "redemption-supply";
                /** @enum {string} */
                quantity?: "core-output-minima" | "gross-cygld-input" | "gross-cygld-mint";
                /** @enum {string} */
                limitKind?: "effective-supply-cap" | "maximum-total-supply";
                requestedRaw?: string;
                availableRaw?: string;
                currentSupplyRaw?: string;
                limitRaw?: string;
            };
            /** @description Optional observed RPC failure context; provider text is sanitized before publication. */
            diagnostics?: {
                rpcMethod?: string;
                stage?: string;
                elapsedMs?: number;
                upstreamErrorCode?: number;
                providerMessage?: string;
                httpStatus?: number;
                /** @enum {string} */
                failureType?: "backend-deadline" | "http-error" | "provider-timeout" | "rpc-error" | "transport-error";
                errorSelector?: string;
                errorName?: string;
            };
            /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
            quoteDiagnostics?: {
                /** @enum {string} */
                phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                elapsedMs?: number;
                qualified?: boolean;
                inversionIteration?: number;
                routeWave?: {
                    elapsedMs?: number;
                    subphaseElapsedMs?: number;
                    /** @enum {string} */
                    subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                    /** @enum {string} */
                    mode?: "exact-in" | "exact-out";
                    legacyCandidates?: number;
                    legacyCompleted?: number;
                    typedEnumerated?: number;
                    typedCompleted?: number;
                    typedPending?: number;
                    sdkRequests?: number;
                    sdkWaiting?: number;
                    sdkLockWaitMs?: number;
                    sdkExchangeMs?: number;
                    legs?: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        count: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            index: number;
                            inputAsset?: string;
                            outputAsset?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            amount?: string;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            started: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            succeeded: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            failed: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            cancelled: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            pending: number;
                            bestAvailable: boolean;
                            failureCounts: {
                                code: components["schemas"]["QuoteErrorCode"];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                count: number;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedFailureCodes: number;
                            bestPools: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools: number;
                        }[];
                    };
                };
                providerQualifications?: {
                    /** @enum {string} */
                    provider: "core" | "market";
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    attempts: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    qualified: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    rejected: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    notImproved: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    cancelled: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    superseded: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    pending: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    omittedRows: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    selectedAttempt?: number;
                    /** @enum {string} */
                    selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    firstQualifiedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    selectionMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    canonicalCompletedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    cleanupCompletedMs?: number;
                    rows: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempt: number;
                        /** @enum {string} */
                        stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                        /** @enum {string} */
                        outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                        /** @enum {string} */
                        code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        targetAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        minimumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountIn?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountIn?: string;
                        /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                        startedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        completedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        elapsedMs?: number;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        executionAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedInput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedOutput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        inputMaximum?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        outputMinimum?: string;
                        pools?: {
                            /** @enum {string} */
                            protocol: "v2" | "v3" | "v4";
                            /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                            poolId?: string;
                            poolAddress?: string;
                        }[];
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedPools?: number;
                    }[];
                };
            };
        });
        RouteLeg: components["schemas"]["Partial<Record<\"index\"|\"pending\"|\"cancelled\"|\"failed\"|\"started\"|\"succeeded\"|\"omittedFailureCodes\"|\"omittedPools\",number>>"] & {
            index: number;
            inputAsset?: string;
            outputAsset?: string;
            amount?: string;
            bestAvailable?: boolean;
            failureCounts: {
                code: components["schemas"]["QuoteCode"];
                count: number;
            }[];
            bestPools: {
                /** @enum {string} */
                protocol: "v2" | "v3" | "v4";
                poolId?: string;
                poolAddress?: string;
            }[];
        };
        "Partial<Record<\"index\"|\"pending\"|\"cancelled\"|\"failed\"|\"started\"|\"succeeded\"|\"omittedFailureCodes\"|\"omittedPools\",number>>": {
            index?: number;
            pending?: number;
            cancelled?: number;
            failed?: number;
            started?: number;
            succeeded?: number;
            omittedFailureCodes?: number;
            omittedPools?: number;
        };
        /** @enum {string} */
        QuoteCode: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
        "Partial<Record<\"elapsedMs\"|\"subphaseElapsedMs\"|\"legacyCandidates\"|\"legacyCompleted\"|\"typedEnumerated\"|\"typedCompleted\"|\"typedPending\"|\"sdkRequests\"|\"sdkWaiting\"|\"sdkLockWaitMs\"|\"sdkExchangeMs\",number>>": {
            elapsedMs?: number;
            subphaseElapsedMs?: number;
            legacyCandidates?: number;
            legacyCompleted?: number;
            typedEnumerated?: number;
            typedCompleted?: number;
            typedPending?: number;
            sdkRequests?: number;
            sdkWaiting?: number;
            sdkLockWaitMs?: number;
            sdkExchangeMs?: number;
        };
        ProviderQualification: {
            attempt: number;
            /** @enum {string} */
            stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
            /** @enum {string} */
            outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
            /** @enum {string} */
            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
        } & components["schemas"]["Partial<Record<\"outputMinimum\"|\"quotedInput\"|\"inputMaximum\"|\"quotedOutput\"|\"targetAmount\"|\"minimumAmountOut\"|\"maximumAmountOut\"|\"observedAmountOut\"|\"maximumAmountIn\"|\"observedAmountIn\"|\"executionAmount\",string>>"] & components["schemas"]["Partial<Record<\"elapsedMs\"|\"startedMs\"|\"completedMs\",number>>"] & {
            pools?: {
                /** @enum {string} */
                protocol: "v2" | "v3" | "v4";
                poolId?: string;
                poolAddress?: string;
            }[];
            omittedPools?: number;
        };
        "Partial<Record<\"outputMinimum\"|\"quotedInput\"|\"inputMaximum\"|\"quotedOutput\"|\"targetAmount\"|\"minimumAmountOut\"|\"maximumAmountOut\"|\"observedAmountOut\"|\"maximumAmountIn\"|\"observedAmountIn\"|\"executionAmount\",string>>": {
            outputMinimum?: string;
            quotedInput?: string;
            inputMaximum?: string;
            quotedOutput?: string;
            targetAmount?: string;
            minimumAmountOut?: string;
            maximumAmountOut?: string;
            observedAmountOut?: string;
            maximumAmountIn?: string;
            observedAmountIn?: string;
            executionAmount?: string;
        };
        "Partial<Record<\"elapsedMs\"|\"startedMs\"|\"completedMs\",number>>": {
            elapsedMs?: number;
            startedMs?: number;
            completedMs?: number;
        };
        "Partial<Record<\"pending\"|\"cancelled\"|\"attempts\"|\"qualified\"|\"rejected\"|\"superseded\"|\"notImproved\"|\"omittedRows\"|\"firstQualifiedMs\"|\"selectionMs\"|\"canonicalCompletedMs\"|\"cleanupCompletedMs\",number>>": {
            pending?: number;
            cancelled?: number;
            attempts?: number;
            qualified?: number;
            rejected?: number;
            superseded?: number;
            notImproved?: number;
            omittedRows?: number;
            firstQualifiedMs?: number;
            selectionMs?: number;
            canonicalCompletedMs?: number;
            cleanupCompletedMs?: number;
        };
        HelpersActivity: {
            /** @constant */
            enabled: false;
            events: {
                blockNumber: string;
                blockHash: string;
                transactionHash: string;
                logIndex: number;
                timestampSeconds: string;
                topic: string;
                eventName: null | string;
                arguments: components["schemas"]["Record<string,unknown>"] | null;
            }[];
        } | (components["schemas"]["Omit<{enabled:true;chainId:number;address:string;source:\"retained-core-journal\";journalStartBlock:string|null;indexedThroughBlock:string|null;indexedThroughBlockHash:string|null;hasMore:boolean;events:{blockNumber:string;blockHash:string;transactionHash:string;logIndex:number;timestampSeconds:string;topic:`0x${string}`;eventName:string|null;arguments:Record<string,unknown>|null;}[];},\"source\">"] & {
            /** @constant */
            source: "retained-helpers-journal";
        });
        "Omit<{enabled:true;chainId:number;address:string;source:\"retained-core-journal\";journalStartBlock:string|null;indexedThroughBlock:string|null;indexedThroughBlockHash:string|null;hasMore:boolean;events:{blockNumber:string;blockHash:string;transactionHash:string;logIndex:number;timestampSeconds:string;topic:`0x${string}`;eventName:string|null;arguments:Record<string,unknown>|null;}[];},\"source\">": {
            indexedThroughBlock: null | string;
            chainId: number;
            address: string;
            events: {
                blockNumber: string;
                blockHash: string;
                transactionHash: string;
                logIndex: number;
                timestampSeconds: string;
                topic: string;
                eventName: null | string;
                arguments: components["schemas"]["Record<string,unknown>"] | null;
            }[];
            /** @constant */
            enabled: true;
            journalStartBlock: null | string;
            indexedThroughBlockHash: null | string;
            hasMore: boolean;
        };
        RecoveryPool: {
            asset: string;
            impaired: boolean;
            coreAttachedShares: string;
            externalShares: string;
            totalShares: string;
            redeemableRaw: string;
            cygldPerAssetRawFp18: string;
            cygldSupplyCap: string;
            referenceShares?: string;
            referenceValueCygld?: string;
            shareDecimals?: number;
        } & {
            asset: string;
            referenceShares: string;
            referenceValueCygld: string;
            shareDecimals: number;
            lifecycle: {
                asset: string;
                lifecycle: number;
                exitEntitlementRaw: string;
            };
            custody: {
                lifecycle: number;
                poolImpaired: boolean;
                redeemablePoolRaw: string;
                coreAttachedShares: string;
                externalShares: string;
                exitEntitlementRaw: string;
                liveBalanceAvailable: boolean;
                liveRawCustody: string;
                activeAvailableRaw: string;
                poolRawDeficit: string;
                exitEntitlementDeficitRaw: string;
            };
        };
        "Record<DashboardRangeKey,DashboardRangeBucket[]>": {
            "24H": {
                bucketStartMs: number;
                mintCygld: number;
                redeemCygld: number;
                netCygld: number;
                supplyCygld: number;
                transferredCygld: number;
                transferTxCount: number;
            }[];
            "7D": {
                bucketStartMs: number;
                mintCygld: number;
                redeemCygld: number;
                netCygld: number;
                supplyCygld: number;
                transferredCygld: number;
                transferTxCount: number;
            }[];
            "1M": {
                bucketStartMs: number;
                mintCygld: number;
                redeemCygld: number;
                netCygld: number;
                supplyCygld: number;
                transferredCygld: number;
                transferTxCount: number;
            }[];
        };
        OwnerAliasesRequest: {
            /** @constant */
            action: "list";
            editorAddress: string;
            ownerAddresses: string[];
        } | {
            /** @constant */
            action: "upsert";
            editorAddress: string;
            ownerAddress: string;
            alias: string;
            auth: {
                nonce: string;
                issuedAt: string;
                signature: string;
            };
        } | {
            /** @constant */
            action: "delete";
            editorAddress: string;
            ownerAddress: string;
            auth: {
                nonce: string;
                issuedAt: string;
                signature: string;
            };
        };
        PoolCacheRequest: ({
            /** @constant */
            action: "list-pools";
        } & {
            chainId: number;
            /** @enum {string} */
            dex: "uniswap" | "uniswap_v2" | "uniswap_v3" | "uniswap_v4";
            pairs: components["schemas"]["PoolCacheLookupPair"][];
        }) | {
            /** @constant */
            action: "record-observations";
            entries: components["schemas"]["PoolCacheObservation"][];
        };
        PoolCacheLookupPair: {
            /** @enum {string} */
            protocol?: "v2" | "v3" | "v4";
            id?: string;
            poolId?: string;
            poolManager?: string;
            tickSpacing?: number;
            hooks?: string;
            poolKey?: {
                currency0: string;
                currency1: string;
                fee: number;
                tickSpacing: number;
                hooks: string;
            };
        } & {
            tokenA: string;
            tokenB: string;
            fee?: number;
        };
        PoolCacheObservation: {
            /** @enum {string} */
            protocol?: "v2" | "v3" | "v4";
            id?: string;
            poolId?: string;
            poolManager?: string;
            tickSpacing?: number;
            hooks?: string;
            poolKey?: {
                currency0: string;
                currency1: string;
                fee: number;
                tickSpacing: number;
                hooks: string;
            };
        } & {
            pool?: {
                id: string;
                /** @enum {string} */
                protocol: "v2" | "v3" | "v4";
                token0: {
                    address: string;
                    decimals: number;
                    chainId: number;
                    decimalsKnown?: boolean;
                };
                token1: {
                    address: string;
                    decimals: number;
                    chainId: number;
                    decimalsKnown?: boolean;
                };
                address?: string;
                feePips: number;
                tickSpacing?: number;
                poolManager?: string;
                hooks?: string;
            };
            reserve0Raw?: string;
            reserve1Raw?: string;
            /** @description V3 nominal fee tier; V4 current StateView LP fee pips. */
            lpFee?: number;
            /** @description V3 packed 4-bit protocol-share divisors; V4 packed 12-bit protocol fee pips. */
            protocolFee?: number;
            /** @description Raw token1/token0 marginal rate, without token decimals or swap fees. */
            marginalPrice?: {
                numerator: string;
                denominator: string;
            };
            ticks?: {
                index: number;
                liquidityGross: string;
                liquidityNet: string;
            }[];
            bitmapWords?: {
                wordPosition: number;
                bitmap: string;
            }[];
        } & {
            chainId: number;
            dex: components["schemas"]["PoolDex"];
            tokenA: string;
            tokenB: string;
            fee: number;
            poolAddress?: string;
            exists: boolean;
            quoteSucceeded?: boolean;
            activeLiquidityRaw?: string;
            sqrtPriceX96Raw?: string;
            tick?: number;
            token0BalanceRaw?: string;
            token1BalanceRaw?: string;
        };
        CachedPoolCandidate: {
            /** @enum {string} */
            protocol?: "v2" | "v3" | "v4";
            id?: string;
            poolId?: string;
            poolManager?: string;
            tickSpacing?: number;
            hooks?: string;
            poolKey?: {
                currency0: string;
                currency1: string;
                fee: number;
                tickSpacing: number;
                hooks: string;
            };
        } & {
            pool?: {
                id: string;
                /** @enum {string} */
                protocol: "v2" | "v3" | "v4";
                token0: {
                    address: string;
                    decimals: number;
                    chainId: number;
                    decimalsKnown?: boolean;
                };
                token1: {
                    address: string;
                    decimals: number;
                    chainId: number;
                    decimalsKnown?: boolean;
                };
                address?: string;
                feePips: number;
                tickSpacing?: number;
                poolManager?: string;
                hooks?: string;
            };
            reserve0Raw?: string;
            reserve1Raw?: string;
            /** @description V3 nominal fee tier; V4 current StateView LP fee pips. */
            lpFee?: number;
            /** @description V3 packed 4-bit protocol-share divisors; V4 packed 12-bit protocol fee pips. */
            protocolFee?: number;
            /** @description Raw token1/token0 marginal rate, without token decimals or swap fees. */
            marginalPrice?: {
                numerator: string;
                denominator: string;
            };
            ticks?: {
                index: number;
                liquidityGross: string;
                liquidityNet: string;
            }[];
            bitmapWords?: {
                wordPosition: number;
                bitmap: string;
            }[];
        } & {
            dex: components["schemas"]["PoolDex"];
            token0: string;
            token1: string;
            fee: number;
            poolAddress?: string;
            exists: boolean;
            successCount?: number;
            activeLiquidityRaw?: string;
            sqrtPriceX96Raw?: string;
            tick?: number;
            token0BalanceRaw?: string;
            token1BalanceRaw?: string;
            liquidityCheckedAt?: string;
            lastCheckedAt?: string;
        };
        /** @enum {string} */
        FaucetErrorCode: "ADDRESS_QUOTA_EXHAUSTED" | "AUTHENTICATION_FAILED" | "BAD_GATEWAY" | "CHAIN_UNAVAILABLE" | "CONFIGURATION_ERROR" | "DISABLED" | "EXECUTION_FAILED" | "FUNDING_FAILED" | "GLOBAL_QUOTA_EXHAUSTED" | "INTERNAL_ERROR" | "INVALID_ADDRESS" | "INVALID_REQUEST" | "INVALID_REQUESTER_IP" | "INVALID_REQUEST_ID" | "INVALID_RESPONSE" | "IP_QUOTA_EXHAUSTED" | "RATE_LIMITED" | "REQUEST_CONFLICT" | "REQUEST_IN_PROGRESS" | "REQUEST_REJECTED" | "REQUEST_TOO_LARGE" | "REQUEST_UNCERTAIN" | "TIMEOUT" | "UNAVAILABLE" | "UNSUPPORTED_MEDIA_TYPE";
        /** @enum {string} */
        InternalReconcileMode: "allow-exact-receipt-noop" | "require-worker-run";
        "Record<\"eth_call\"|\"eth_chainId\"|\"eth_getBlockByHash\"|\"eth_getBlockByNumber\"|\"eth_getCode\"|\"eth_getLogs\",number>": {
            eth_call: number;
            eth_chainId: number;
            eth_getBlockByHash: number;
            eth_getBlockByNumber: number;
            eth_getCode: number;
            eth_getLogs: number;
        };
        "Record<IndexerRpcRequestSource,number>": {
            "core-event": number;
            "governance-event": number;
            "safe-event": number;
            "core-address": number;
            "governance-address": number;
            "safe-address": number;
        };
        ForkRequest: ({
            /** @constant */
            kind: "cybergold-sandbox-fork-generation";
            /** @constant */
            formatVersion: 1;
        } & {
            /** @constant */
            action: "prepare";
            current: {
                generation: string;
                forkBlock: string;
                forkBlockHash: string;
            };
        }) | ({
            /** @constant */
            kind: "cybergold-sandbox-fork-generation";
            /** @constant */
            formatVersion: 1;
        } & {
            /** @constant */
            action: "apply";
            previous: {
                generation: string;
                forkBlock: string;
                forkBlockHash: string;
            };
            current: {
                generation: string;
                forkBlock: string;
                forkBlockHash: string;
            };
        });
        /** @description Optional subscriber references; workId belongs to shared producer work. */
        DiagnosticReferences: {
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        };
        /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
        QuoteWorkDiagnostics: {
            /** @enum {string} */
            phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
            elapsedMs?: number;
            qualified?: boolean;
            inversionIteration?: number;
            routeWave?: {
                elapsedMs?: number;
                subphaseElapsedMs?: number;
                /** @enum {string} */
                subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                /** @enum {string} */
                mode?: "exact-in" | "exact-out";
                legacyCandidates?: number;
                legacyCompleted?: number;
                typedEnumerated?: number;
                typedCompleted?: number;
                typedPending?: number;
                sdkRequests?: number;
                sdkWaiting?: number;
                sdkLockWaitMs?: number;
                sdkExchangeMs?: number;
                legs?: {
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    count: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    omittedRows: number;
                    rows: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        index: number;
                        inputAsset?: string;
                        outputAsset?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        amount?: string;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        started: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        succeeded: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        failed: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        cancelled: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        pending: number;
                        bestAvailable: boolean;
                        failureCounts: {
                            code: components["schemas"]["QuoteErrorCode"];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            count: number;
                        }[];
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedFailureCodes: number;
                        bestPools: {
                            /** @enum {string} */
                            protocol: "v2" | "v3" | "v4";
                            /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                            poolId?: string;
                            poolAddress?: string;
                        }[];
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedPools: number;
                    }[];
                };
            };
            providerQualifications?: {
                /** @enum {string} */
                provider: "core" | "market";
                /** @description Bounded observation count; never an execution eligibility predicate. */
                attempts: number;
                /** @description Bounded observation count; never an execution eligibility predicate. */
                qualified: number;
                /** @description Bounded observation count; never an execution eligibility predicate. */
                rejected: number;
                /** @description Bounded observation count; never an execution eligibility predicate. */
                notImproved: number;
                /** @description Bounded observation count; never an execution eligibility predicate. */
                cancelled: number;
                /** @description Bounded observation count; never an execution eligibility predicate. */
                superseded: number;
                /** @description Bounded observation count; never an execution eligibility predicate. */
                pending: number;
                /** @description Bounded observation count; never an execution eligibility predicate. */
                omittedRows: number;
                /** @description Bounded observation count; never an execution eligibility predicate. */
                selectedAttempt?: number;
                /** @enum {string} */
                selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                firstQualifiedMs?: number;
                /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                selectionMs?: number;
                /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                canonicalCompletedMs?: number;
                /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                cleanupCompletedMs?: number;
                rows: {
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    attempt: number;
                    /** @enum {string} */
                    stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                    /** @enum {string} */
                    outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                    /** @enum {string} */
                    code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                    /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                    targetAmount?: string;
                    /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                    minimumAmountOut?: string;
                    /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                    maximumAmountOut?: string;
                    /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                    observedAmountOut?: string;
                    /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                    maximumAmountIn?: string;
                    /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                    observedAmountIn?: string;
                    /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                    startedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    completedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    elapsedMs?: number;
                    /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                    executionAmount?: string;
                    /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                    quotedInput?: string;
                    /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                    quotedOutput?: string;
                    /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                    inputMaximum?: string;
                    /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                    outputMinimum?: string;
                    pools?: {
                        /** @enum {string} */
                        protocol: "v2" | "v3" | "v4";
                        /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                        poolId?: string;
                        poolAddress?: string;
                    }[];
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    omittedPools?: number;
                }[];
            };
        };
        /** @description One user trade; Backend chooses a complete Core or market execution. */
        TradeModelRequest: {
            /** @enum {string} */
            side: "buy" | "sell";
            /** @enum {string} */
            mode: "exact-in" | "exact-out";
            counterToken: string;
            native: boolean;
            amount: string;
            slippageBps?: number;
        };
        EconomicPlan: {
            allocations: {
                /** @enum {number} */
                kind: 0 | 1;
                amountIn: string;
            }[];
            conversions: components["schemas"]["Record<string,Record<string,unknown>>"];
            body: components["schemas"]["Record<string,unknown>"];
        };
        TransactionPreparationRequest: {
            quote: components["schemas"]["EconomicQuote"];
            sender: string;
            recipient: string;
            slippageBps?: number;
            acceptedBounds?: {
                inputs?: {
                    currency: string;
                    amount: string;
                }[];
                minimumOutput?: string;
                expectedCoreOutputs?: {
                    kind: number;
                    token: string;
                    id: string;
                    minimumAmount: string;
                }[];
            };
        };
        /** @description Market swaps transfer existing CYGLD; never use Core basket economics. */
        UniversalExactInputRequest: {
            /** @enum {number} */
            intent: 0 | 1 | 2 | 3;
            inputs: {
                currency: string;
                amount: string;
            }[];
            outputCurrency: string;
            recipient: string;
            deadline: string;
            slippageBps?: number;
        };
        UniversalExactInputQuote: {
            /** @constant */
            strategy: "universal";
            /** @enum {string} */
            routeFamily: "core" | "market" | "mixed";
            /** @constant */
            operation: "executeExactInput";
            /** @constant */
            settlementPolicy: "protocol-retained-input";
            plan: components["schemas"]["UniversalExactInputPlan"];
            planDescription: components["schemas"]["Record<string,unknown>"];
            economicQuote?: components["schemas"]["EconomicQuote"];
            inputs: {
                currency: string;
                amount: string;
            }[];
            quotedInput?: string;
            inputMaximum?: string;
            quotedOutput: string;
            outputMinimum: string;
            estimatedRetainedInputCharges: {
                branch: number;
                stage: number;
                currency: string;
                amount: string;
            }[];
            estimatedRecipientOutputs: {
                kind: number;
                token: string;
                id: string;
                amount: string;
            }[];
            fees: {
                coreProtocolFeeCygld: string;
                coreHelpersFeeCygld: string;
                marketFeeCygld: string;
            };
            recoveryShares: {
                kind: number;
                token: string;
                id: string;
                amount: string;
            }[];
            deployment: {
                helpers: string;
                adapter: string;
                /** @constant */
                encoding: "uniswap-routing-v1";
            };
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            retentionDisclosure: {
                custodian: string;
                /** @constant */
                beneficiary: "helpers-owner-at-settlement";
            };
            searchCoverage: {
                coreSharesPercent: number[];
                orders: string[];
                maxCoreInvocations: number;
                maxAmmHops: number;
                /** @constant */
                scope: "selected-inventory";
                /** @enum {string} */
                selectedPhase?: "backward-prefix" | "capacity-limited" | "detailed" | "first-result" | "nearby-lower" | "nearby-upper" | "route-family" | "route-family-exploration" | "saved-plan";
            };
            /** @description Producer clocks, distinct from client request or browser journey duration. */
            metrics?: {
                firstQualifiedMs?: number;
                selectionMs?: number;
                canonicalCompletedMs?: number;
                cleanupCompletedMs?: number;
                finalizationMs?: number;
            } & {
                totalMs: number;
                timeToFirstWholePlanMs: null | number;
                searchMs: null | number;
                selectionReason: ("best-initial" | "complete" | "first-extension" | "timeout") | null;
                nearbySearch?: {
                    starts: number;
                    completed: number;
                    sources: {
                        /** @enum {string} */
                        side: "lower" | "upper";
                        identity?: null | string;
                        /** @enum {string} */
                        referenceBasis?: "funded-input-approximation" | "market-sale-consumed" | "observed-nonretained";
                        attempts: {
                            funding: string;
                            completed?: boolean;
                            elapsedMs: number;
                            /** @enum {string} */
                            failureCode?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        }[];
                        /** @enum {string} */
                        failureCode?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                    }[];
                };
            };
        };
        TradeProviderAssessment: {
            /** @enum {string} */
            availability: "not-run" | "pending" | "qualified" | "unavailable" | "unsupported";
            /** @enum {string} */
            searchOutcome: "cancelled" | "complete" | "error" | "not-run" | "running" | "timeout";
            error?: string;
            /** @enum {string} */
            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
            /** @description Canonical preview rejection evidence; absent quantities were not provided by the contract. */
            constraint?: {
                /** @enum {string} */
                kind?: "issuance-cap" | "redemption-capacity" | "redemption-supply";
                /** @enum {string} */
                quantity?: "core-output-minima" | "gross-cygld-input" | "gross-cygld-mint";
                /** @enum {string} */
                limitKind?: "effective-supply-cap" | "maximum-total-supply";
                requestedRaw?: string;
                availableRaw?: string;
                currentSupplyRaw?: string;
                limitRaw?: string;
            };
            /** @description Optional observed RPC failure context; provider text is sanitized before publication. */
            diagnostics?: {
                rpcMethod?: string;
                stage?: string;
                elapsedMs?: number;
                upstreamErrorCode?: number;
                providerMessage?: string;
                httpStatus?: number;
                /** @enum {string} */
                failureType?: "backend-deadline" | "http-error" | "provider-timeout" | "rpc-error" | "transport-error";
                errorSelector?: string;
                errorName?: string;
            };
            /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
            quoteDiagnostics?: {
                /** @enum {string} */
                phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                elapsedMs?: number;
                qualified?: boolean;
                inversionIteration?: number;
                routeWave?: {
                    elapsedMs?: number;
                    subphaseElapsedMs?: number;
                    /** @enum {string} */
                    subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                    /** @enum {string} */
                    mode?: "exact-in" | "exact-out";
                    legacyCandidates?: number;
                    legacyCompleted?: number;
                    typedEnumerated?: number;
                    typedCompleted?: number;
                    typedPending?: number;
                    sdkRequests?: number;
                    sdkWaiting?: number;
                    sdkLockWaitMs?: number;
                    sdkExchangeMs?: number;
                    legs?: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        count: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            index: number;
                            inputAsset?: string;
                            outputAsset?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            amount?: string;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            started: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            succeeded: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            failed: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            cancelled: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            pending: number;
                            bestAvailable: boolean;
                            failureCounts: {
                                code: components["schemas"]["QuoteErrorCode"];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                count: number;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedFailureCodes: number;
                            bestPools: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools: number;
                        }[];
                    };
                };
                providerQualifications?: {
                    /** @enum {string} */
                    provider: "core" | "market";
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    attempts: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    qualified: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    rejected: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    notImproved: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    cancelled: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    superseded: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    pending: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    omittedRows: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    selectedAttempt?: number;
                    /** @enum {string} */
                    selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    firstQualifiedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    selectionMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    canonicalCompletedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    cleanupCompletedMs?: number;
                    rows: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempt: number;
                        /** @enum {string} */
                        stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                        /** @enum {string} */
                        outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                        /** @enum {string} */
                        code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        targetAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        minimumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountIn?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountIn?: string;
                        /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                        startedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        completedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        elapsedMs?: number;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        executionAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedInput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedOutput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        inputMaximum?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        outputMinimum?: string;
                        pools?: {
                            /** @enum {string} */
                            protocol: "v2" | "v3" | "v4";
                            /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                            poolId?: string;
                            poolAddress?: string;
                        }[];
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedPools?: number;
                    }[];
                };
            };
        };
        TradeProviderCandidates: {
            /** @description One complete provider plan, without recursive provider evidence maps. */
            core?: components["schemas"]["CoreTradeProviderCandidate"];
            market?: components["schemas"]["MarketTradeProviderCandidate"];
        };
        TradeQuoteModelPacket: {
            /** @constant */
            namespace: "trade";
            /** @description One user trade; Backend chooses a complete Core or market execution. */
            intent: {
                /** @enum {string} */
                side: "buy" | "sell";
                /** @enum {string} */
                mode: "exact-in" | "exact-out";
                counterToken: string;
                native: boolean;
                amount: string;
                slippageBps?: number;
            };
            models: ({
                /** @constant */
                strategy: "core";
                /** @description Display-only source data. No transaction tuples or execution readiness. */
                value: {
                    revision: number;
                    intent: components["schemas"]["Omit<QuoteIntentRequest,\"deadline\"|\"retainedPlan\">"];
                    routes: {
                        tokens: string[];
                        fees: number[];
                        context: {
                            chainId: number;
                            blockNumber: string;
                            blockHash: string;
                            observedAt: string;
                        };
                        routePlan?: {
                            /** @constant */
                            version: 1;
                            /** @enum {string} */
                            executionContext: "helpers-core" | "helpers-market";
                            /** @enum {string} */
                            mode: "exactIn" | "exactOut";
                            tokenIn: string;
                            tokenOut: string;
                            branches: {
                                amountIn: string;
                                hops: {
                                    pool: components["schemas"]["RoutePoolRef"];
                                    zeroForOne: boolean;
                                }[];
                            }[];
                            inputAmount: string;
                            outputAmount: string;
                            limit: string;
                            deadline: string;
                        };
                        protocols?: ("v2" | "v3" | "v4")[];
                        poolIds?: string[];
                        points: {
                            input: string;
                            output: string;
                            context?: {
                                chainId: number;
                                blockNumber: string;
                                blockHash: string;
                                observedAt: string;
                            };
                            recordedAt?: number;
                        }[];
                        exchangeRate?: {
                            numerator: string;
                            denominator: string;
                        };
                        exchangeContext?: {
                            chainId: number;
                            blockNumber: string;
                            blockHash: string;
                            observedAt: string;
                        };
                        feeRetention: {
                            numerator: string;
                            denominator: string;
                        };
                        localImpact?: {
                            numerator: string;
                            denominator: string;
                        };
                    }[];
                    whole: {
                        input: string;
                        display: string;
                        context: {
                            chainId: number;
                            blockNumber: string;
                            blockHash: string;
                            observedAt: string;
                        };
                        recordedAt: number;
                    }[];
                    protocol: {
                        context: {
                            chainId: number;
                            blockNumber: string;
                            blockHash: string;
                            observedAt: string;
                        };
                        state: {
                            assets: string[];
                            weights: string[];
                            conversions: string[];
                            issueFee: string;
                            helperFee: string;
                            redeemFee: string;
                            supply: string;
                            maxSupply: string;
                            effectiveCap: string;
                            available: string[];
                            recoveryShares: string[];
                            recoveryValues: string[];
                            descriptors: {
                                kind: number;
                                token: string;
                                id: string;
                            }[];
                        };
                    } | null;
                };
            } | {
                /** @constant */
                strategy: "market";
                value: {
                    /** @constant */
                    namespace: "market";
                    family: string;
                    context?: {
                        chainId: number;
                        blockNumber: string;
                        blockHash: string;
                        observedAt: string;
                    };
                    intent: {
                        /** @enum {string} */
                        side: "buy" | "sell";
                        /** @enum {string} */
                        mode: "exact-in" | "exact-out";
                        counterToken: string;
                        adapter: string;
                    };
                    cygld: string;
                    feeRatePpm: number;
                    routes: {
                        route: {
                            /** @constant */
                            version: 1;
                            /** @enum {string} */
                            executionContext: "helpers-core" | "helpers-market";
                            /** @enum {string} */
                            mode: "exactIn" | "exactOut";
                            tokenIn: string;
                            tokenOut: string;
                            branches: {
                                amountIn: string;
                                hops: {
                                    pool: components["schemas"]["RoutePoolRef"];
                                    zeroForOne: boolean;
                                }[];
                            }[];
                            inputAmount: string;
                            outputAmount: string;
                            limit: string;
                            deadline: string;
                        };
                        amountIn: string;
                        amountOut: string;
                        sourceObservations?: {
                            poolId: string;
                            context: {
                                chainId: number;
                                blockNumber: string;
                                blockHash: string;
                                observedAt: string;
                            };
                        }[];
                        sourceContext?: {
                            chainId: number;
                            blockNumber: string;
                            blockHash: string;
                            observedAt: string;
                        } | null;
                        points: {
                            amountIn: string;
                            amountOut: string;
                            context?: {
                                chainId: number;
                                blockNumber: string;
                                blockHash: string;
                                observedAt: string;
                            };
                            requestedAmount?: string;
                            family?: string;
                            feeRatePpm?: number;
                            routeIdentity?: string;
                        }[];
                        exchangeRate?: {
                            numerator: string;
                            denominator: string;
                        };
                        feeRetention?: {
                            numerator: string;
                            denominator: string;
                        };
                        localImpact?: {
                            numerator: string;
                            denominator: string;
                        };
                    }[];
                };
            })[];
            estimate?: {
                /** @enum {string} */
                strategy: "core" | "market";
                amount: string;
            } | {
                /** @constant */
                strategy: "universal";
                amount: string;
                /** @constant */
                source: "cached-upper";
                referenceInput: string;
                /** @enum {string} */
                basis: "funded-input-approximation" | "market-sale-consumed" | "observed-nonretained";
                fees: {
                    coreProtocolFeeCygld: string;
                    coreHelpersFeeCygld: string;
                    marketFeeCygld: string;
                };
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                sourceIdentity?: string;
                sourceRequestedInput?: string;
            };
            /** @description Display-only economics of a Backend-selected quote. An absent maximumBudget means no upper budget bound. */
            budgetRange?: {
                minimumBudget: string;
                maximumBudget?: string;
                quotedInput: string;
                quotedOutput: string;
            };
        };
        ProtocolConfiguration: {
            chainId: number;
            contracts: {
                core: null | string;
                helpers: null | string;
                governance: null | string;
                staking: null | string;
                safe: null | string;
                uniswapAdapter: null | string;
            };
            tokens: components["schemas"]["ProtocolConfiguredToken"][];
            sandboxForkGeneration: null | string;
            adapter: {
                /** @enum {string} */
                status: "success" | "unavailable";
                encoding: ("uniswap-multi-protocol-v1" | "uniswap-routing-v1" | "uniswap-v3") | null;
                observation: {
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                } | null;
            };
            universalExactInput: {
                adapter: null | string;
                encoding: "uniswap-routing-v1" | null;
                /** @constant */
                settlementPolicy: "protocol-retained-input";
            };
        };
        MarketQuoteRequest: {
            /** @enum {string} */
            side: "buy" | "sell";
            /** @enum {string} */
            mode: "exact-in" | "exact-out";
            counterToken: string;
            amount: string;
            adapter?: string;
            recipient: string;
            deadline: string;
            slippageBps?: number;
            retainedPlan?: {
                /** @enum {string} */
                side: "buy" | "sell";
                /** @enum {string} */
                mode: "exact-in" | "exact-out";
                amount: string;
                slippageBps: number;
                route: {
                    /** @constant */
                    version: 1;
                    /** @enum {string} */
                    executionContext: "helpers-core" | "helpers-market";
                    /** @enum {string} */
                    mode: "exactIn" | "exactOut";
                    tokenIn: string;
                    tokenOut: string;
                    branches: {
                        amountIn: string;
                        hops: {
                            pool: components["schemas"]["RoutePoolRef"];
                            zeroForOne: boolean;
                        }[];
                    }[];
                    inputAmount: string;
                    outputAmount: string;
                    limit: string;
                    deadline: string;
                };
                params: {
                    /** @enum {number} */
                    side: 0 | 1;
                    counterToken: string;
                    amount: string;
                    bound: string;
                    routedInput: string;
                    feeCygld: string;
                    recipient: string;
                    deadline: string;
                    adapter: string;
                    data: string;
                };
                fee: {
                    asset: string;
                    ratePpm: number;
                    amount: string;
                    /** @constant */
                    basis: "quoted";
                    notional: string;
                };
            };
        };
        MarketQuote: {
            /** @constant */
            operation: "market";
            /** @enum {string} */
            side: "buy" | "sell";
            /** @enum {string} */
            mode: "exact-in" | "exact-out";
            tokenIn: string;
            tokenOut: string;
            amountIn: string;
            amountOut: string;
            totalInput: string;
            netOutput: string;
            grossOutput: string;
            routedAmountIn: string;
            inputMaximum: string;
            outputMinimum: string;
            refundDust: string;
            outputRefundEstimate?: string;
            fee: {
                asset: string;
                ratePpm: number;
                amount: string;
                /** @constant */
                basis: "quoted";
                notional: string;
            };
            params: {
                /** @enum {number} */
                side: 0 | 1;
                counterToken: string;
                amount: string;
                bound: string;
                routedInput: string;
                feeCygld: string;
                recipient: string;
                deadline: string;
                adapter: string;
                data: string;
            };
            adapterData: string;
            plan: {
                /** @enum {string} */
                side: "buy" | "sell";
                /** @enum {string} */
                mode: "exact-in" | "exact-out";
                amount: string;
                slippageBps: number;
                route: {
                    /** @constant */
                    version: 1;
                    /** @enum {string} */
                    executionContext: "helpers-core" | "helpers-market";
                    /** @enum {string} */
                    mode: "exactIn" | "exactOut";
                    tokenIn: string;
                    tokenOut: string;
                    branches: {
                        amountIn: string;
                        hops: {
                            pool: components["schemas"]["RoutePoolRef"];
                            zeroForOne: boolean;
                        }[];
                    }[];
                    inputAmount: string;
                    outputAmount: string;
                    limit: string;
                    deadline: string;
                };
                params: {
                    /** @enum {number} */
                    side: 0 | 1;
                    counterToken: string;
                    amount: string;
                    bound: string;
                    routedInput: string;
                    feeCygld: string;
                    recipient: string;
                    deadline: string;
                    adapter: string;
                    data: string;
                };
                fee: {
                    asset: string;
                    ratePpm: number;
                    amount: string;
                    /** @constant */
                    basis: "quoted";
                    notional: string;
                };
            };
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            feeBeneficiaryDisplay?: {
                address: string;
                observedAt: string;
            };
            /** @description AMM price impact excluding LP/protocol/application fees; absent without a coherent baseline. */
            priceImpactPpm?: string;
            /** @constant */
            qualification: "sdk";
            executionSimulationRequired?: boolean;
            quoteVerificationUnavailable?: string;
            searchCoverage?: {
                /** @constant */
                scope: "selected-inventory";
                maxHops: number;
                splitPercentages: number[];
                inventoryPools: number;
                catalogMonth: null | string;
            };
            metrics: {
                candidateCalls: number;
                totalMs: number;
            } & {
                firstQualifiedMs?: number;
                selectionMs?: number;
                canonicalCompletedMs?: number;
                cleanupCompletedMs?: number;
                finalizationMs?: number;
            };
            /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
            quoteDiagnostics?: {
                /** @enum {string} */
                phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                elapsedMs?: number;
                qualified?: boolean;
                inversionIteration?: number;
                routeWave?: {
                    elapsedMs?: number;
                    subphaseElapsedMs?: number;
                    /** @enum {string} */
                    subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                    /** @enum {string} */
                    mode?: "exact-in" | "exact-out";
                    legacyCandidates?: number;
                    legacyCompleted?: number;
                    typedEnumerated?: number;
                    typedCompleted?: number;
                    typedPending?: number;
                    sdkRequests?: number;
                    sdkWaiting?: number;
                    sdkLockWaitMs?: number;
                    sdkExchangeMs?: number;
                    legs?: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        count: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            index: number;
                            inputAsset?: string;
                            outputAsset?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            amount?: string;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            started: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            succeeded: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            failed: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            cancelled: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            pending: number;
                            bestAvailable: boolean;
                            failureCounts: {
                                code: components["schemas"]["QuoteErrorCode"];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                count: number;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedFailureCodes: number;
                            bestPools: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools: number;
                        }[];
                    };
                };
                providerQualifications?: {
                    /** @enum {string} */
                    provider: "core" | "market";
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    attempts: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    qualified: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    rejected: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    notImproved: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    cancelled: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    superseded: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    pending: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    omittedRows: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    selectedAttempt?: number;
                    /** @enum {string} */
                    selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    firstQualifiedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    selectionMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    canonicalCompletedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    cleanupCompletedMs?: number;
                    rows: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempt: number;
                        /** @enum {string} */
                        stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                        /** @enum {string} */
                        outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                        /** @enum {string} */
                        code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        targetAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        minimumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountIn?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountIn?: string;
                        /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                        startedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        completedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        elapsedMs?: number;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        executionAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedInput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedOutput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        inputMaximum?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        outputMinimum?: string;
                        pools?: {
                            /** @enum {string} */
                            protocol: "v2" | "v3" | "v4";
                            /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                            poolId?: string;
                            poolAddress?: string;
                        }[];
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedPools?: number;
                    }[];
                };
            };
        };
        MarketQuoteModelPacket: {
            /** @constant */
            namespace: "market";
            family: string;
            context?: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            intent: {
                /** @enum {string} */
                side: "buy" | "sell";
                /** @enum {string} */
                mode: "exact-in" | "exact-out";
                counterToken: string;
                adapter: string;
            };
            cygld: string;
            feeRatePpm: number;
            routes: {
                route: {
                    /** @constant */
                    version: 1;
                    /** @enum {string} */
                    executionContext: "helpers-core" | "helpers-market";
                    /** @enum {string} */
                    mode: "exactIn" | "exactOut";
                    tokenIn: string;
                    tokenOut: string;
                    branches: {
                        amountIn: string;
                        hops: {
                            pool: components["schemas"]["RoutePoolRef"];
                            zeroForOne: boolean;
                        }[];
                    }[];
                    inputAmount: string;
                    outputAmount: string;
                    limit: string;
                    deadline: string;
                };
                amountIn: string;
                amountOut: string;
                sourceObservations?: {
                    poolId: string;
                    context: {
                        chainId: number;
                        blockNumber: string;
                        blockHash: string;
                        observedAt: string;
                    };
                }[];
                sourceContext?: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                } | null;
                points: {
                    amountIn: string;
                    amountOut: string;
                    context?: {
                        chainId: number;
                        blockNumber: string;
                        blockHash: string;
                        observedAt: string;
                    };
                    requestedAmount?: string;
                    family?: string;
                    feeRatePpm?: number;
                    routeIdentity?: string;
                }[];
                exchangeRate?: {
                    numerator: string;
                    denominator: string;
                };
                feeRetention?: {
                    numerator: string;
                    denominator: string;
                };
                localImpact?: {
                    numerator: string;
                    denominator: string;
                };
            }[];
        };
        MarketRoutePlan: {
            /** @constant */
            version: 1;
            /** @enum {string} */
            executionContext: "helpers-core" | "helpers-market";
            /** @enum {string} */
            mode: "exactIn" | "exactOut";
            tokenIn: string;
            tokenOut: string;
            branches: {
                amountIn: string;
                hops: {
                    pool: components["schemas"]["RoutePoolRef"];
                    zeroForOne: boolean;
                }[];
            }[];
            inputAmount: string;
            outputAmount: string;
            limit: string;
            deadline: string;
        };
        GovernanceTargetCode: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            address: string;
            hasCode: boolean;
        };
        PoolCatalog: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            entries: {
                id: string;
                /** @enum {string} */
                protocol: "v2" | "v3" | "v4";
                token0: {
                    address: string;
                    decimals: number;
                    chainId: number;
                    decimalsKnown?: boolean;
                };
                token1: {
                    address: string;
                    decimals: number;
                    chainId: number;
                    decimalsKnown?: boolean;
                };
                address?: string;
                feePips: number;
                tickSpacing?: number;
                poolManager?: string;
                hooks?: string;
            }[];
            catalogMonth: null | string;
        };
        ProtocolFacts: {
            basketModel?: {
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                state: {
                    assets: string[];
                    weights: string[];
                    conversions: string[];
                    issueFee: string;
                    helperFee: string;
                    redeemFee: string;
                    supply: string;
                    maxSupply: string;
                    effectiveCap: string;
                    available: string[];
                    recoveryShares: string[];
                    recoveryValues: string[];
                    descriptors: {
                        kind: number;
                        token: string;
                        id: string;
                    }[];
                };
            } | null;
            /** @description Current mint-capacity facts, available without quote-model history. */
            issuanceCapacity?: {
                totalSupply: components["schemas"]["FactRead<string>"];
                maxTotalSupply: components["schemas"]["FactRead<string>"];
                effectiveCygldSupplyCap: components["schemas"]["FactRead<string>"];
            };
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            core: string;
            helpers: null | string;
            basket: {
                assets: components["schemas"]["FactRead<string[]>"];
                targetsPpm: components["schemas"]["FactRead<string[]>"];
                goldRefGramsFp18: components["schemas"]["FactRead<string[]>"];
                cygldPerUnitFp18: components["schemas"]["FactRead<string[]>"];
                metadata: {
                    address: string;
                    decimals: components["schemas"]["FactRead<number>"];
                    name: components["schemas"]["FactRead<string>"];
                    symbol: components["schemas"]["FactRead<string>"];
                }[];
            };
            reference: components["schemas"]["FactRead<string>"];
            fees: {
                issuancePpm: components["schemas"]["FactRead<string>"];
                helpersPpm: components["schemas"]["FactRead<string>"];
            };
            pause: components["schemas"]["FactRead<boolean>"];
        };
        GovernanceCoreFacts: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            core: string;
            configuration: {
                treasury: components["schemas"]["FactRead<string>"];
                basketConfigHash: components["schemas"]["FactRead<string>"];
                issuanceFeePpm: components["schemas"]["FactRead<string>"];
                redemptionFeePpm: components["schemas"]["FactRead<string>"];
                maxFeePpm: components["schemas"]["FactRead<string>"];
                maxTotalSupply: components["schemas"]["FactRead<string>"];
                totalSupply: components["schemas"]["FactRead<string>"];
                /** @description Live configured product facts; amounts stay lossless over JSON. */
                safeWallet?: {
                    /** @constant */
                    status: "failure";
                    /** @enum {string} */
                    error: "contract-read-failed" | "not-configured";
                } | {
                    /** @constant */
                    status: "success";
                    value: string;
                };
            };
        };
        HelpersRouterFacts: {
            adapter?: {
                address: string;
                codePresent: components["schemas"]["FactRead<boolean>"];
            };
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            helpers: null | string;
            configuration: {
                helperFeePpm: components["schemas"]["FactRead<string>"];
                permit2: components["schemas"]["FactRead<string>"];
                wrappedNative: components["schemas"]["FactRead<string>"];
                owner: components["schemas"]["FactRead<string>"];
                approvedAdapters: components["schemas"]["FactRead<string[]>"];
                paused: components["schemas"]["FactRead<boolean>"];
                /** @description Live configured product facts; amounts stay lossless over JSON. */
                tokenPermitIssuance?: {
                    /** @constant */
                    status: "failure";
                    /** @enum {string} */
                    error: "contract-read-failed" | "not-configured";
                } | {
                    /** @constant */
                    status: "success";
                    value: boolean;
                };
                /** @description Live configured product facts; amounts stay lossless over JSON. */
                basketPermitIssuanceExactIn?: {
                    /** @constant */
                    status: "failure";
                    /** @enum {string} */
                    error: "contract-read-failed" | "not-configured";
                } | {
                    /** @constant */
                    status: "success";
                    value: boolean;
                };
                /** @description Live configured product facts; amounts stay lossless over JSON. */
                basketPermitIssuanceExactOut?: {
                    /** @constant */
                    status: "failure";
                    /** @enum {string} */
                    error: "contract-read-failed" | "not-configured";
                } | {
                    /** @constant */
                    status: "success";
                    value: boolean;
                };
                /** @description Live configured product facts; amounts stay lossless over JSON. */
                universalExactInput?: {
                    /** @constant */
                    status: "failure";
                    /** @enum {string} */
                    error: "contract-read-failed" | "not-configured";
                } | {
                    /** @constant */
                    status: "success";
                    value: boolean;
                };
                /** @description Live configured product facts; amounts stay lossless over JSON. */
                marketSwapExactInput?: {
                    /** @constant */
                    status: "failure";
                    /** @enum {string} */
                    error: "contract-read-failed" | "not-configured";
                } | {
                    /** @constant */
                    status: "success";
                    value: boolean;
                };
                /** @description Live configured product facts; amounts stay lossless over JSON. */
                marketSwapExactOutput?: {
                    /** @constant */
                    status: "failure";
                    /** @enum {string} */
                    error: "contract-read-failed" | "not-configured";
                } | {
                    /** @constant */
                    status: "success";
                    value: boolean;
                };
            };
        };
        GovernanceSafePrincipal: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            address: string;
            code: components["schemas"]["FactRead<string>"];
            owners: components["schemas"]["FactRead<string[]>"];
            threshold: components["schemas"]["FactRead<string>"];
        };
        TransactionRevert: {
            chainId: number;
            observedAt: string;
            transactionHash: string;
            data: null | string;
            reverted: boolean;
        };
        EnsName: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            holder: string;
            name: null | string;
        };
        EnsAvatarRecord: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            name: string;
            avatarRecord: null | string;
            nftTokenUri?: {
                /** @constant */
                status: "success";
                value: string;
            } | {
                /** @constant */
                status: "failure";
                error: string;
            };
        };
        NativeBalance: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            holder: string;
            balance: string;
        };
        LiquidityPositions: {
            /** @description Each NFT's token quantities include deposited principal and unclaimed LP fees. */
            positions: {
                tokenId: string;
                paxgAmount: string;
                cygldAmount: string;
            }[];
            /** @description Aggregate PAXG principal plus unclaimed PAXG LP fees, in decimal token units. */
            paxgAmount: string;
            /** @description Aggregate CYGLD principal plus unclaimed CYGLD LP fees, in decimal token units. */
            cygldAmount: string;
            blockNumber: string;
        };
        WalletBalances: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            holder: string;
            native: components["schemas"]["FactRead<string>"];
            tokens: {
                /** @enum {string} */
                id: "cygld" | "paxg" | "usdc" | "usdt" | "weth" | "xaut";
                address: string;
                balance: components["schemas"]["FactRead<string>"];
            }[];
        };
        WalletTokenBalance: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            holder: string;
            /** @enum {string} */
            tokenId: "cygld" | "eth" | "paxg" | "usdc" | "usdt" | "weth" | "xaut";
            balance: components["schemas"]["FactRead<string>"];
        };
        GovernanceRoles: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            /** @enum {string} */
            surface: "core" | "governance-diamond" | "staking";
            address: null | string;
            /** @constant */
            memberDisplayLimit: 50;
            roles: {
                id: string;
                count: components["schemas"]["FactRead<string>"];
                members: components["schemas"]["FactRead<string>"][];
            }[];
        };
        GovernanceAuthority: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            /** @enum {string} */
            surface: "core" | "governance-diamond" | "staking";
            address: null | string;
            account: null | string;
            safeWallet: components["schemas"]["FactRead<string>"];
            paused: components["schemas"]["FactRead<boolean>"];
            accountCanPause: components["schemas"]["FactRead<boolean>"];
            accountCanUnpause: components["schemas"]["FactRead<boolean>"];
            safeCanUnpause: components["schemas"]["FactRead<boolean>"];
        };
        RecoveryRedemptionRequest: {
            holder: string;
            asset: string;
            shares: string;
            minRawOut: string;
        };
        Permit2ApprovalGasRequest: {
            owner: string;
            token: string;
        };
        SafeNonce: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            address: string;
            nonce: string;
        };
        SafeTransactionHash: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            address: string;
            safeTxHash: string;
        };
        SafeTransactionHashRequest: {
            address: string;
            to: string;
            value: string;
            data: string;
            operation: number;
            safeTxGas: string;
            baseGas: string;
            gasPrice: string;
            gasToken: string;
            refundReceiver: string;
            nonce: string;
        };
        SafeExecution: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            address: string;
            executor: string;
            executorNonce: string;
            success: boolean;
            /** @constant */
            blockTag: "latest";
        };
        HelpersExecutionRequest: {
            owner: string;
            /** @enum {string} */
            operation: "executeExactInput" | "issueFromBasketExactOutWithMixedPermits" | "issueFromBasketExactOutWithPermit2" | "issueFromNativeExactOut" | "issueFromTokenExactOut" | "issueFromTokenExactOutWithPermit" | "issueFromTokenExactOutWithPermit2" | "swapExactOutput";
            args: unknown[];
            value?: string;
        };
        HelpersExecution: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            helpers: string;
            owner: string;
            /** @enum {string} */
            operation: "executeExactInput" | "issueFromBasketExactOutWithMixedPermits" | "issueFromBasketExactOutWithPermit2" | "issueFromNativeExactOut" | "issueFromTokenExactOut" | "issueFromTokenExactOutWithPermit" | "issueFromTokenExactOutWithPermit2" | "swapExactOutput";
            gas: string;
            /** @constant */
            blockTag: "latest";
        };
        TransactionFees: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            maxFeePerGas: string;
            maxPriorityFeePerGas: string;
        };
        TransactionNonce: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            owner: string;
            /** @constant */
            blockTag: "pending";
            nonce: string;
        };
        TransactionReceiptObservation: {
            chainId: number;
            observedAt: string;
            transactionHash: string;
            receipt: {
                transactionHash: string;
                blockHash: string;
                blockNumber: string;
                /** @enum {string} */
                status: "reverted" | "success";
                logs: {
                    address: string;
                    data: string;
                    topics: string[];
                }[];
            } | null;
        };
        CoreRecoveryAssets: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            core: string;
            assets: string[];
        };
        RecoverySharePrecision: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            core: string;
            asset: string;
            shareDecimals: number;
        };
        CorePermit: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            owner: string;
            spender: null | string;
            nonce: string;
            domain: {
                name: string;
                /** @constant */
                version: "1";
                chainId: number;
                verifyingContract: string;
            };
        };
        TokenMetadata: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            token: {
                chainId: number;
                address: string;
            };
            metadata: {
                name: components["schemas"]["FactRead<string>"];
                symbol: components["schemas"]["FactRead<string>"];
                decimals: components["schemas"]["FactRead<number>"];
            };
            holder?: string;
            /** @description Live configured product facts; amounts stay lossless over JSON. */
            balance?: {
                /** @constant */
                status: "failure";
                /** @enum {string} */
                error: "contract-read-failed" | "not-configured";
            } | {
                /** @constant */
                status: "success";
                value: string;
            };
            authorization: {
                /** @enum {string} */
                kind: "erc2612" | "none" | "unavailable" | "unknown" | "variant";
                /** @enum {string} */
                confidence: "observed" | "qualified" | "unknown";
                domain?: {
                    name?: string;
                    version?: string;
                    chainId?: string | number;
                    verifyingContract?: string;
                    salt?: string;
                };
                /** @constant */
                variant?: "dai";
                /** @enum {string} */
                source?: "erc5267" | "reconstruction" | "seed";
                reason?: string;
                observation?: {
                    blockNumber: string;
                    blockHash: string;
                };
            };
        };
        TokenPermitContext: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                blockTimestamp: string;
                observedAt: string;
            };
            token: {
                chainId: number;
                address: string;
            };
            owner: string;
            spender: null | string;
            nonce: components["schemas"]["FactRead<string>"];
            allowance: components["schemas"]["FactRead<string>"];
            authorization: {
                /** @enum {string} */
                kind: "erc2612" | "none" | "unavailable" | "unknown" | "variant";
                /** @enum {string} */
                confidence: "observed" | "qualified" | "unknown";
                domain?: {
                    name?: string;
                    version?: string;
                    chainId?: string | number;
                    verifyingContract?: string;
                    salt?: string;
                };
                /** @constant */
                variant?: "dai";
                /** @enum {string} */
                source?: "erc5267" | "reconstruction" | "seed";
                reason?: string;
                observation?: {
                    blockNumber: string;
                    blockHash: string;
                };
            };
        };
        TokenApprovalGasRequest: {
            owner: string;
            token: string;
            amount: string;
        };
        BasketMaxRequest: {
            driverToken: string;
            maximumAmountsIn: string[];
        };
        BasketMax: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            helpers: string;
            orderedCoreAssets: string[];
            driverToken: string;
            driverAmount: string;
            maximumAmountsIn: string[];
            netCygldOut: string;
        };
        UniswapQuoteRequest: {
            /** @enum {string} */
            mode: "exact-in" | "exact-out";
            path: string;
            amount: string;
        };
        UniswapQuote: {
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            /** @constant */
            qualification: "sdk";
            /** @enum {string} */
            mode: "exact-in" | "exact-out";
            result: {
                amount: string;
            };
        };
        RouteSearchRequest: {
            /** @enum {string} */
            mode: "exact-in" | "exact-out";
            targets: {
                inputAsset: string;
                outputAsset: string;
                amount: string;
            }[];
            adapter?: string;
        };
        RouteSearch: {
            /** @enum {string} */
            mode: "exact-in" | "exact-out";
            /** @constant */
            qualification: "sdk";
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            results: {
                target: {
                    inputAsset: string;
                    outputAsset: string;
                    amount: string;
                };
                best: {
                    path: string;
                    quote: string;
                    /** @enum {string} */
                    route: "direct" | "identity" | "mixed" | "viaWeth";
                    feeInfo: string;
                    routePlan?: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                } | null;
                attempted: number;
                succeeded: number;
                failures: {
                    path: string;
                    rpcCode: number;
                    /** @enum {string} */
                    code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                    /** @description Canonical preview rejection evidence; absent quantities were not provided by the contract. */
                    constraint?: {
                        /** @enum {string} */
                        kind?: "issuance-cap" | "redemption-capacity" | "redemption-supply";
                        /** @enum {string} */
                        quantity?: "core-output-minima" | "gross-cygld-input" | "gross-cygld-mint";
                        /** @enum {string} */
                        limitKind?: "effective-supply-cap" | "maximum-total-supply";
                        requestedRaw?: string;
                        availableRaw?: string;
                        currentSupplyRaw?: string;
                        limitRaw?: string;
                    };
                    /** @description Optional observed RPC failure context; provider text is sanitized before publication. */
                    diagnostics?: {
                        rpcMethod?: string;
                        stage?: string;
                        elapsedMs?: number;
                        upstreamErrorCode?: number;
                        providerMessage?: string;
                        httpStatus?: number;
                        /** @enum {string} */
                        failureType?: "backend-deadline" | "http-error" | "provider-timeout" | "rpc-error" | "transport-error";
                        errorSelector?: string;
                        errorName?: string;
                    };
                }[];
            }[];
            metrics: {
                candidateCalls: number;
                rpcReads: number;
                rpcReadsRequested: number;
                /** @constant */
                rpcReadsScope?: "coordinator";
                rpcReadsCoalesced: number;
                rpcReadsReused: number;
                contextMs: number;
                quotesMs: number;
                canonicalityMs: number;
                totalMs: number;
            };
        };
        QuoteIntentRequest: {
            /** @enum {string} */
            mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
            token: string;
            quoteToken: string;
            native: boolean;
            amount: string;
            adapter?: string;
            deadline: string;
            orderedAssets: string[];
            targets: {
                inputAsset: string;
                outputAsset: string;
                amount: string;
            }[];
            /**
             * @description Execution tolerance in basis points; omitted defaults to 100 (1%).
             * @default 100
             */
            slippageBps: number;
            retainedPlan?: {
                slippageBps?: number;
                expectedInputAmount?: string;
                executionAmount: string;
                maximumInputAmount: string;
                minimumAmountOut: string;
                quotes: (({
                    adapter: string;
                    amountIn: string;
                    minimumAmountOut: string;
                    data: string;
                    routePlan?: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                } & {
                    outputAsset: string;
                }) | ({
                    adapter: string;
                    minimumAmountOut: string;
                    data: string;
                    routePlan?: {
                        /** @constant */
                        version: 1;
                        /** @enum {string} */
                        executionContext: "helpers-core" | "helpers-market";
                        /** @enum {string} */
                        mode: "exactIn" | "exactOut";
                        tokenIn: string;
                        tokenOut: string;
                        branches: {
                            amountIn: string;
                            hops: {
                                pool: components["schemas"]["RoutePoolRef"];
                                zeroForOne: boolean;
                            }[];
                        }[];
                        inputAmount: string;
                        outputAmount: string;
                        limit: string;
                        deadline: string;
                    };
                } & {
                    inputAsset: string;
                    inputAmount: string;
                }))[];
                expectedCoreOutputs: {
                    kind: number;
                    token: string;
                    id: string;
                    minimumAmount: string;
                }[];
            };
        };
        QuoteIntent: {
            /** @enum {string} */
            mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            quotes: (({
                adapter: string;
                amountIn: string;
                minimumAmountOut: string;
                data: string;
                routePlan?: {
                    /** @constant */
                    version: 1;
                    /** @enum {string} */
                    executionContext: "helpers-core" | "helpers-market";
                    /** @enum {string} */
                    mode: "exactIn" | "exactOut";
                    tokenIn: string;
                    tokenOut: string;
                    branches: {
                        amountIn: string;
                        hops: {
                            pool: components["schemas"]["RoutePoolRef"];
                            zeroForOne: boolean;
                        }[];
                    }[];
                    inputAmount: string;
                    outputAmount: string;
                    limit: string;
                    deadline: string;
                };
            } & {
                outputAsset: string;
            }) | ({
                adapter: string;
                minimumAmountOut: string;
                data: string;
                routePlan?: {
                    /** @constant */
                    version: 1;
                    /** @enum {string} */
                    executionContext: "helpers-core" | "helpers-market";
                    /** @enum {string} */
                    mode: "exactIn" | "exactOut";
                    tokenIn: string;
                    tokenOut: string;
                    branches: {
                        amountIn: string;
                        hops: {
                            pool: components["schemas"]["RoutePoolRef"];
                            zeroForOne: boolean;
                        }[];
                    }[];
                    inputAmount: string;
                    outputAmount: string;
                    limit: string;
                    deadline: string;
                };
            } & {
                inputAsset: string;
                inputAmount: string;
            }))[];
            preview: {
                netCygldOut: string;
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
                orderedCoreAssets: string[];
            } | {
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
                orderedCoreAssets: string[];
            } | {
                minimumAmountOut: string;
                projectedCoreOutputs: {
                    kind: number;
                    token: string;
                    id: string;
                    amount: string;
                }[];
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
            };
            initialPreview: {
                netCygldOut: string;
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
                amountsInExact: string[];
                orderedCoreAssets: string[];
            } | {
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
                amountsInExact: string[];
                orderedCoreAssets: string[];
            } | {
                projectedCoreOutputs: {
                    kind: number;
                    token: string;
                    id: string;
                    amount: string;
                }[];
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
            } | {
                grossCygldIn: string;
                projectedCoreOutputs: {
                    kind: number;
                    token: string;
                    id: string;
                    amount: string;
                }[];
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
            } | {
                netCygldOut: string;
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
                orderedCoreAssets: string[];
            } | {
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
                orderedCoreAssets: string[];
            } | {
                minimumAmountOut: string;
                projectedCoreOutputs: {
                    kind: number;
                    token: string;
                    id: string;
                    amount: string;
                }[];
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
            } | null;
            basketPreview: {
                netCygldOut: string;
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
                amountsInExact: string[];
                orderedCoreAssets: string[];
            } | {
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
                amountsInExact: string[];
                orderedCoreAssets: string[];
            } | {
                projectedCoreOutputs: {
                    kind: number;
                    token: string;
                    id: string;
                    amount: string;
                }[];
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
            } | {
                grossCygldIn: string;
                projectedCoreOutputs: {
                    kind: number;
                    token: string;
                    id: string;
                    amount: string;
                }[];
                fees: {
                    protocolFeeCygld: string;
                    helperFeeCygld: string;
                };
            };
            displayAmount: string;
            executionAmount: string;
            maximumInputAmount: string;
            slippageBps?: number;
            /** @description Expected input before execution cushions, including direct basket input. */
            expectedInputAmount?: string;
            requestedGrossCygldOut?: string;
            requestedNetCygldOut?: string;
            remainingGrossCapacity?: string;
            remainingNetCapacity?: string;
            expectedOutputAmount?: string;
            expectedCoreOutputs?: {
                kind: number;
                token: string;
                id: string;
                minimumAmount: string;
            }[];
            metrics: {
                rpcReads: number;
                rpcReadsRequested: number;
                rpcReadsCoalesced: number;
                rpcReadsReused: number;
                /** @constant */
                rpcReadsScope?: "coordinator";
                candidateCalls: number;
                iterations: number;
                totalMs: number;
            } & {
                firstQualifiedMs?: number;
                selectionMs?: number;
                canonicalCompletedMs?: number;
                cleanupCompletedMs?: number;
                finalizationMs?: number;
            };
            /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
            quoteDiagnostics?: {
                /** @enum {string} */
                phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                elapsedMs?: number;
                qualified?: boolean;
                inversionIteration?: number;
                routeWave?: {
                    elapsedMs?: number;
                    subphaseElapsedMs?: number;
                    /** @enum {string} */
                    subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                    /** @enum {string} */
                    mode?: "exact-in" | "exact-out";
                    legacyCandidates?: number;
                    legacyCompleted?: number;
                    typedEnumerated?: number;
                    typedCompleted?: number;
                    typedPending?: number;
                    sdkRequests?: number;
                    sdkWaiting?: number;
                    sdkLockWaitMs?: number;
                    sdkExchangeMs?: number;
                    legs?: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        count: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            index: number;
                            inputAsset?: string;
                            outputAsset?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            amount?: string;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            started: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            succeeded: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            failed: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            cancelled: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            pending: number;
                            bestAvailable: boolean;
                            failureCounts: {
                                code: components["schemas"]["QuoteErrorCode"];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                count: number;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedFailureCodes: number;
                            bestPools: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools: number;
                        }[];
                    };
                };
                providerQualifications?: {
                    /** @enum {string} */
                    provider: "core" | "market";
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    attempts: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    qualified: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    rejected: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    notImproved: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    cancelled: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    superseded: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    pending: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    omittedRows: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    selectedAttempt?: number;
                    /** @enum {string} */
                    selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    firstQualifiedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    selectionMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    canonicalCompletedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    cleanupCompletedMs?: number;
                    rows: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempt: number;
                        /** @enum {string} */
                        stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                        /** @enum {string} */
                        outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                        /** @enum {string} */
                        code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        targetAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        minimumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountIn?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountIn?: string;
                        /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                        startedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        completedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        elapsedMs?: number;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        executionAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedInput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedOutput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        inputMaximum?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        outputMinimum?: string;
                        pools?: {
                            /** @enum {string} */
                            protocol: "v2" | "v3" | "v4";
                            /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                            poolId?: string;
                            poolAddress?: string;
                        }[];
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedPools?: number;
                    }[];
                };
            };
        };
        /** @description Display-only source data. No transaction tuples or execution readiness. */
        QuoteModelPacket: {
            revision: number;
            intent: components["schemas"]["Omit<QuoteIntentRequest,\"deadline\"|\"retainedPlan\">"];
            routes: {
                tokens: string[];
                fees: number[];
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                routePlan?: {
                    /** @constant */
                    version: 1;
                    /** @enum {string} */
                    executionContext: "helpers-core" | "helpers-market";
                    /** @enum {string} */
                    mode: "exactIn" | "exactOut";
                    tokenIn: string;
                    tokenOut: string;
                    branches: {
                        amountIn: string;
                        hops: {
                            pool: components["schemas"]["RoutePoolRef"];
                            zeroForOne: boolean;
                        }[];
                    }[];
                    inputAmount: string;
                    outputAmount: string;
                    limit: string;
                    deadline: string;
                };
                protocols?: ("v2" | "v3" | "v4")[];
                poolIds?: string[];
                points: {
                    input: string;
                    output: string;
                    context?: {
                        chainId: number;
                        blockNumber: string;
                        blockHash: string;
                        observedAt: string;
                    };
                    recordedAt?: number;
                }[];
                exchangeRate?: {
                    numerator: string;
                    denominator: string;
                };
                exchangeContext?: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                feeRetention: {
                    numerator: string;
                    denominator: string;
                };
                localImpact?: {
                    numerator: string;
                    denominator: string;
                };
            }[];
            whole: {
                input: string;
                display: string;
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                recordedAt: number;
            }[];
            protocol: {
                context: {
                    chainId: number;
                    blockNumber: string;
                    blockHash: string;
                    observedAt: string;
                };
                state: {
                    assets: string[];
                    weights: string[];
                    conversions: string[];
                    issueFee: string;
                    helperFee: string;
                    redeemFee: string;
                    supply: string;
                    maxSupply: string;
                    effectiveCap: string;
                    available: string[];
                    recoveryShares: string[];
                    recoveryValues: string[];
                    descriptors: {
                        kind: number;
                        token: string;
                        id: string;
                    }[];
                };
            } | null;
        };
        NumericCoreQuote: {
            /** @constant */
            readOnly: true;
            /** @enum {string} */
            mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
            context: {
                chainId: number;
                blockNumber: string;
                blockHash: string;
                observedAt: string;
            };
            slippageBps?: number;
            metrics?: {
                rpcReads: number;
                rpcReadsRequested: number;
                rpcReadsCoalesced: number;
                rpcReadsReused: number;
                /** @constant */
                rpcReadsScope?: "coordinator";
                candidateCalls: number;
                iterations: number;
                totalMs: number;
            } & {
                firstQualifiedMs?: number;
                selectionMs?: number;
                canonicalCompletedMs?: number;
                cleanupCompletedMs?: number;
                finalizationMs?: number;
            };
            displayAmount?: string;
            executionAmount?: string;
            maximumInputAmount?: string;
            expectedInputAmount?: string;
            expectedOutputAmount?: string;
            minimumAmountOut: string;
        };
        /** @description Optional observed RPC failure context; provider text is sanitized before publication. */
        RpcErrorDiagnostics: {
            rpcMethod?: string;
            stage?: string;
            elapsedMs?: number;
            upstreamErrorCode?: number;
            providerMessage?: string;
            httpStatus?: number;
            /** @enum {string} */
            failureType?: "backend-deadline" | "http-error" | "provider-timeout" | "rpc-error" | "transport-error";
            errorSelector?: string;
            errorName?: string;
        };
        ClientDiagnostic: {
            /** @enum {string} */
            operation?: "quote" | "swap" | "wallet";
            /** @enum {string} */
            outcome?: "failed" | "requested" | "reverted" | "started" | "submitted" | "succeeded" | "unconfirmed";
            /** @enum {string} */
            reason?: "contract_reverted" | "rpc_error" | "unknown" | "wallet_rejected" | "wrong_chain";
            /** @description Numeric wallet or JSON-RPC code; no error message or provider text. */
            errorCode?: number;
            /** @description Four-byte EVM error selector only; no encoded arguments or calldata. */
            errorSelector?: string;
            /** @enum {string} */
            direction?: "issue" | "redeem";
            /** @enum {string} */
            route?: "basket" | "token";
            /** @enum {string} */
            inputMode?: "exact-in" | "exact-out";
            /** @enum {string} */
            walletStep?: "approval" | "signature" | "transaction";
            attemptId?: string;
            quoteId?: string;
            requestId?: string;
            correlationId?: string;
            workId?: string;
            /** @enum {string} */
            side?: "buy" | "sell";
            /** @enum {string} */
            strategy?: "core" | "market" | "universal";
            /** @enum {string} */
            stage?: "authorization" | "balance" | "confirmation" | "network" | "preparation" | "quote" | "simulation" | "submission";
            /** @description Canonical preview rejection evidence; absent quantities were not provided by the contract. */
            constraint?: {
                /** @enum {string} */
                kind?: "issuance-cap" | "redemption-capacity" | "redemption-supply";
                /** @enum {string} */
                quantity?: "core-output-minima" | "gross-cygld-input" | "gross-cygld-mint";
                /** @enum {string} */
                limitKind?: "effective-supply-cap" | "maximum-total-supply";
                requestedRaw?: string;
                availableRaw?: string;
                currentSupplyRaw?: string;
                limitRaw?: string;
            };
            quoteDiagnostics?: {
                /** @enum {string} */
                phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                qualified?: boolean;
                elapsedMs?: number;
                inversionIteration?: number;
                routeWave?: {
                    /** @enum {string} */
                    mode?: "exact-in" | "exact-out";
                    /** @enum {string} */
                    subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                    legs?: {
                        count: number;
                        omittedRows?: number;
                        rows: components["schemas"]["RouteLeg"][];
                    };
                } & components["schemas"]["Partial<Record<\"elapsedMs\"|\"subphaseElapsedMs\"|\"legacyCandidates\"|\"legacyCompleted\"|\"typedEnumerated\"|\"typedCompleted\"|\"typedPending\"|\"sdkRequests\"|\"sdkWaiting\"|\"sdkLockWaitMs\"|\"sdkExchangeMs\",number>>"];
                providerQualifications?: {
                    /** @enum {string} */
                    provider: "core" | "market";
                    attempts: number;
                    rows: components["schemas"]["ProviderQualification"][];
                    selectedAttempt?: number;
                    /** @enum {string} */
                    selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                } & components["schemas"]["Partial<Record<\"pending\"|\"cancelled\"|\"attempts\"|\"qualified\"|\"rejected\"|\"superseded\"|\"notImproved\"|\"omittedRows\"|\"firstQualifiedMs\"|\"selectionMs\"|\"canonicalCompletedMs\"|\"cleanupCompletedMs\",number>>"];
            };
            /** @enum {string} */
            errorClassification?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-invalid-input" | "quote-no-route" | "quote-request-limit" | "quote-service-unavailable" | "quote-stream-interrupted" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
            tokenIn?: string;
            tokenOut?: string;
            amount?: string;
            inputMaximum?: string;
            outputMinimum?: string;
            blockNumber?: string;
            blockHash?: string;
            transactionHash?: string;
            durationMs?: number;
            chainId?: number;
            assetCount?: number;
        };
        CoreActivity: {
            /** @constant */
            enabled: true;
            chainId: number;
            address: string;
            /** @constant */
            source: "retained-core-journal";
            journalStartBlock: null | string;
            indexedThroughBlock: null | string;
            indexedThroughBlockHash: null | string;
            hasMore: boolean;
            events: {
                blockNumber: string;
                blockHash: string;
                transactionHash: string;
                logIndex: number;
                timestampSeconds: string;
                topic: string;
                eventName: null | string;
                arguments: components["schemas"]["Record<string,unknown>"] | null;
            }[];
        } | {
            /** @constant */
            enabled: false;
            events: {
                blockNumber: string;
                blockHash: string;
                transactionHash: string;
                logIndex: number;
                timestampSeconds: string;
                topic: string;
                eventName: null | string;
                arguments: components["schemas"]["Record<string,unknown>"] | null;
            }[];
        };
        SafeActivity: {
            /** @constant */
            enabled: true;
            chainId: number;
            /** @constant */
            source: "retained-safe-journal";
            projectionLookbackBlocks: string;
            coverage: {
                address: string;
                journalStartBlock: null | string;
                indexedThroughBlock: null | string;
                indexedThroughBlockHash: null | string;
                projectionIndexedThroughBlock: null | string;
            }[];
            hasMore: boolean;
            events: {
                safeAddress: string;
                blockNumber: string;
                blockHash: string;
                transactionHash: string;
                logIndex: number;
                timestampSeconds: string;
                topic: string;
                eventName: ("ExecutionFailure" | "ExecutionSuccess") | null;
                safeTxHash: string | null;
                paymentWei: null | string;
            }[];
        } | {
            /** @constant */
            enabled: false;
            events: {
                safeAddress: string;
                blockNumber: string;
                blockHash: string;
                transactionHash: string;
                logIndex: number;
                timestampSeconds: string;
                topic: string;
                eventName: ("ExecutionFailure" | "ExecutionSuccess") | null;
                safeTxHash: string | null;
                paymentWei: null | string;
            }[];
        };
        Gold: {
            price: number;
            fetchedAt: string;
            stale: boolean;
        };
        Fx: {
            /** @constant */
            base: "USD";
            rates: {
                USD: number;
                EUR: number;
                CHF: number;
                RUB: number;
            };
            fetchedAt: string;
            stale: boolean;
        };
        Recovery: {
            enabled: boolean;
            /** @enum {string} */
            status: "not-configured" | "ready";
            schemaVersion: string;
            chainId: string;
            collection: string | null;
            snapshotBlock: null | string;
            snapshotBlockHash: null | string;
            complete: boolean;
            nextOffset: null | string;
            totalAssets: string;
            corePaused: null | boolean;
            fund: {
                configured: boolean;
                available: boolean;
                reason: ("not-configured" | "unavailable-or-inconsistent") | null;
                problem: null | string;
                governance: string | null;
                governancePaused: null | boolean;
            } | null;
            balances: {
                shareId: string;
                balanceRaw: string;
                pool: components["schemas"]["RecoveryPool"];
                payoutRaw: null | string;
                payoutProblem: ("custody-unavailable" | "preview-unavailable") | null;
                fundOffer: {
                    /** @constant */
                    available: true;
                    impairedAsset: string;
                    generation: string;
                    governancePaused: boolean;
                    holderShares: string;
                    acceptedShares: string;
                    remainingCapacity: string;
                    cygldToken: string;
                    cygldAmount: string;
                } | {
                    /** @constant */
                    available: false;
                    generation: string;
                    problem: string;
                } | null;
            }[];
            pools: components["schemas"]["RecoveryPool"][];
        };
        RecoveryFundSnapshot: {
            configured: boolean;
            available: boolean;
            reason: ("not-configured" | "unavailable-or-inconsistent") | null;
            problem: null | string;
            governance: null | string;
            trustedCore: null | string;
            governancePaused: null | boolean;
            treasury: {
                balance: string;
                allowanceExposure: string;
                unallowanced: string;
                aggregateCommitment: string;
                available: string;
                deficit: string;
            } | null;
            funds: {
                impairedAsset: string;
                generation: string;
                active: boolean;
                coverageShares: string;
                purchasedShares: string;
                remainingCoverageShares: string;
                initialCygldCommitment: string;
                paidCygld: string;
                remainingCygldCommitment: string;
                governanceBalance: string;
                uncoveredInterest: string;
                currentlyUnfundedInterest: string;
                acquiredShares: string;
                purchasePreview: {
                    generation: string;
                    shares: string;
                    cygldAmount: string;
                } | null;
            }[];
        };
        PortfolioPool: {
            asset: string;
            impaired: boolean;
            coreAttachedShares: string;
            externalShares: string;
            totalShares: string;
            redeemableRaw: string;
            cygldPerAssetRawFp18: string;
            cygldSupplyCap: string;
            referenceShares?: string;
            referenceValueCygld?: string;
            shareDecimals?: number;
            lifecycle: {
                asset: string;
                lifecycle: number;
                exitEntitlementRaw: string;
            };
            custody: {
                lifecycle: number;
                poolImpaired: boolean;
                redeemablePoolRaw: string;
                coreAttachedShares: string;
                externalShares: string;
                exitEntitlementRaw: string;
                liveBalanceAvailable: boolean;
                liveRawCustody: string;
                activeAvailableRaw: string;
                poolRawDeficit: string;
                exitEntitlementDeficitRaw: string;
            };
        };
        Dashboard: ({
            /** @default true */
            enabled: boolean;
            protocolLogicUpdate: {
                timestampMs: number;
                txHash: null | string;
            } | null;
            protocolParameterUpdate: {
                timestampMs: number;
                txHash: null | string;
            } | null;
            chainHeadBlock: string;
            snapshotBlock: string;
            chainHeadTimestampMs: number;
            lastScannedBlock: string;
            metrics: {
                currentTotalSupplyCygld: number;
                netIssuance24hCygld: number;
                holderCount: null | number;
                issuanceFeePercent: null | number;
                redemptionFeePercent: null | number;
                paused: boolean;
            };
            basket: {
                reserveAddress: null | string;
                cygldRefGrams: null | number;
                cygldRefGramsFp18: null | string;
                assets: {
                    address: string;
                    symbol: string;
                    targetPercent: number;
                    actualPercent: number;
                    driftPercent: number;
                    decimals: null | number;
                    reserveBalance: null | number;
                    reserveBalanceRaw: string;
                    totalSupply: null | number;
                    totalSupplyRaw: null | string;
                    goldRefGrams: null | number;
                    cygldPerUnitFp18: string;
                    cygldPerToken: null | number;
                }[];
                withinBand: null | boolean;
            } | null;
            recovery: {
                collection: string;
                pools: {
                    asset: string;
                    impaired: boolean;
                    coreAttachedShares: string;
                    externalShares: string;
                    totalShares: string;
                    redeemableRaw: string;
                    cygldPerAssetRawFp18: string;
                    cygldSupplyCap: string;
                    referenceShares: string;
                    referenceValueCygld: string;
                    shareDecimals: number;
                    lifecycle: {
                        asset: string;
                        lifecycle: number;
                        exitEntitlementRaw: string;
                    };
                    custody: {
                        lifecycle: number;
                        poolImpaired: boolean;
                        redeemablePoolRaw: string;
                        coreAttachedShares: string;
                        externalShares: string;
                        exitEntitlementRaw: string;
                        liveBalanceAvailable: boolean;
                        liveRawCustody: string;
                        activeAvailableRaw: string;
                        poolRawDeficit: string;
                        exitEntitlementDeficitRaw: string;
                    };
                }[];
                reserveLifecycles: {
                    asset: string;
                    lifecycle: number;
                    exitEntitlementRaw: string;
                }[];
                fund: {
                    configured: boolean;
                    available: boolean;
                    reason: ("not-configured" | "unavailable-or-inconsistent") | null;
                    problem: null | string;
                    governance: null | string;
                    trustedCore: null | string;
                    governancePaused: null | boolean;
                    treasury: {
                        balance: string;
                        allowanceExposure: string;
                        unallowanced: string;
                        aggregateCommitment: string;
                        available: string;
                        deficit: string;
                    } | null;
                    funds: {
                        impairedAsset: string;
                        generation: string;
                        active: boolean;
                        coverageShares: string;
                        purchasedShares: string;
                        remainingCoverageShares: string;
                        initialCygldCommitment: string;
                        paidCygld: string;
                        remainingCygldCommitment: string;
                        governanceBalance: string;
                        uncoveredInterest: string;
                        currentlyUnfundedInterest: string;
                        acquiredShares: string;
                        purchasePreview: {
                            generation: string;
                            shares: string;
                            cygldAmount: string;
                        } | null;
                    }[];
                };
            } | null;
            series: components["schemas"]["Record<DashboardRangeKey,DashboardRangeBucket[]>"];
        } & {
            sandboxForkGeneration?: null | string;
        }) | ({
            /** @constant */
            enabled: false;
            protocolLogicUpdate: null;
            protocolParameterUpdate: null;
            lastScannedBlock: null;
        } & {
            sandboxForkGeneration?: null | string;
        });
        PublicError: {
            requestId?: string;
            attemptId?: string;
            correlationId?: string;
            workId?: string;
        } & {
            error: string;
            /** @enum {string} */
            code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
            /** @description Canonical preview rejection evidence; absent quantities were not provided by the contract. */
            constraint?: {
                /** @enum {string} */
                kind?: "issuance-cap" | "redemption-capacity" | "redemption-supply";
                /** @enum {string} */
                quantity?: "core-output-minima" | "gross-cygld-input" | "gross-cygld-mint";
                /** @enum {string} */
                limitKind?: "effective-supply-cap" | "maximum-total-supply";
                requestedRaw?: string;
                availableRaw?: string;
                currentSupplyRaw?: string;
                limitRaw?: string;
            };
            /** @description Optional observed RPC failure context; provider text is sanitized before publication. */
            diagnostics?: {
                rpcMethod?: string;
                stage?: string;
                elapsedMs?: number;
                upstreamErrorCode?: number;
                providerMessage?: string;
                httpStatus?: number;
                /** @enum {string} */
                failureType?: "backend-deadline" | "http-error" | "provider-timeout" | "rpc-error" | "transport-error";
                errorSelector?: string;
                errorName?: string;
            };
            /** @description Existing public quote-work projection; aggregate waits are not wall-clock partitions. */
            quoteDiagnostics?: {
                /** @enum {string} */
                phase?: "basket-preview" | "canonicality" | "capacity" | "context" | "execution-search" | "expected-input-search" | "final-preview" | "initial-preview" | "initial-search" | "retained-validation";
                elapsedMs?: number;
                qualified?: boolean;
                inversionIteration?: number;
                routeWave?: {
                    elapsedMs?: number;
                    subphaseElapsedMs?: number;
                    /** @enum {string} */
                    subphase?: "canonicality" | "composition" | "context" | "eligibility" | "structured-search" | "typed-reserve" | "v3-coverage";
                    /** @enum {string} */
                    mode?: "exact-in" | "exact-out";
                    legacyCandidates?: number;
                    legacyCompleted?: number;
                    typedEnumerated?: number;
                    typedCompleted?: number;
                    typedPending?: number;
                    sdkRequests?: number;
                    sdkWaiting?: number;
                    sdkLockWaitMs?: number;
                    sdkExchangeMs?: number;
                    legs?: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        count: number;
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedRows: number;
                        rows: {
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            index: number;
                            inputAsset?: string;
                            outputAsset?: string;
                            /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                            amount?: string;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            started: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            succeeded: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            failed: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            cancelled: number;
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            pending: number;
                            bestAvailable: boolean;
                            failureCounts: {
                                code: components["schemas"]["QuoteErrorCode"];
                                /** @description Bounded observation count; never an execution eligibility predicate. */
                                count: number;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedFailureCodes: number;
                            bestPools: {
                                /** @enum {string} */
                                protocol: "v2" | "v3" | "v4";
                                /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                                poolId?: string;
                                poolAddress?: string;
                            }[];
                            /** @description Bounded observation count; never an execution eligibility predicate. */
                            omittedPools: number;
                        }[];
                    };
                };
                providerQualifications?: {
                    /** @enum {string} */
                    provider: "core" | "market";
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    attempts: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    qualified: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    rejected: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    notImproved: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    cancelled: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    superseded: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    pending: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    omittedRows: number;
                    /** @description Bounded observation count; never an execution eligibility predicate. */
                    selectedAttempt?: number;
                    /** @enum {string} */
                    selectionReason?: "best-initial" | "complete" | "first-extension" | "timeout";
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    firstQualifiedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    selectionMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    canonicalCompletedMs?: number;
                    /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                    cleanupCompletedMs?: number;
                    rows: {
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        attempt: number;
                        /** @enum {string} */
                        stage: "basket-preview" | "canonicality" | "composition" | "execution-search" | "expected-input-search" | "fee-bounds" | "final-preview" | "initial-preview" | "qualification" | "retained-validation" | "route-pricing" | "selection" | "tolerance";
                        /** @enum {string} */
                        outcome: "cancelled" | "not-improved" | "qualified" | "rejected" | "running" | "superseded";
                        /** @enum {string} */
                        code?: "insufficient-protocol-supply" | "insufficient-recovery-shares" | "insufficient-reserve-balance" | "issuance-cap-exceeded" | "quote-contract-reverted" | "quote-insufficient-liquidity" | "quote-no-route" | "quote-timeout" | "quote-unavailable" | "redemption-capacity-exceeded" | "redemption-supply-exceeded" | "rpc-access-denied" | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable";
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        targetAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        minimumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountOut?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        maximumAmountIn?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        observedAmountIn?: string;
                        /** @description Offsets use the existing selection-budget origin, or provider-work origin without a budget. */
                        startedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        completedMs?: number;
                        /** @description Observed duration or offset in milliseconds, never a selection predicate. */
                        elapsedMs?: number;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        executionAmount?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedInput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        quotedOutput?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        inputMaximum?: string;
                        /** @description Raw uint256 quantity; the producer additionally enforces the uint256 maximum. */
                        outputMinimum?: string;
                        pools?: {
                            /** @enum {string} */
                            protocol: "v2" | "v3" | "v4";
                            /** @description Concrete pool identity or the existing unresolved V3 execution identity. */
                            poolId?: string;
                            poolAddress?: string;
                        }[];
                        /** @description Bounded observation count; never an execution eligibility predicate. */
                        omittedPools?: number;
                    }[];
                };
            };
        };
        AliasesRequest: components["schemas"]["OwnerAliasesRequest"];
        AliasesResult: {
            entries: {
                editorAddress: string;
                ownerAddress: string;
                alias: string;
                updatedAt: string;
            }[];
        } | {
            entry: {
                editorAddress: string;
                ownerAddress: string;
                alias: string;
                updatedAt: string;
            };
        } | {
            /** @constant */
            ok: true;
            deleted: boolean;
        };
        PoolRequest: components["schemas"]["PoolCacheRequest"];
        PoolResult: {
            entries: components["schemas"]["CachedPoolCandidate"][];
        } | {
            /** @constant */
            ok: true;
        };
        SafeRequest: {
            /** @enum {string} */
            action: "confirm-transaction" | "executed-transactions" | "pending-transactions" | "propose-transaction" | "safe-info" | "transaction-details";
            safeAddress?: string;
            safeTxHash?: string;
            payload?: components["schemas"]["Record<string,unknown>"];
        };
        SafeEventsRequest: {
            safeAddress: string;
            safeTxHashes: string[];
        };
        SafeEventsResult: {
            results: {
                safeTxHash: string;
                /** @enum {string} */
                status: "executed" | "failed";
                transactionHash: string;
                blockNumber: string;
                executionDate: string;
            }[];
        };
        FaucetRequest: {
            address: string;
            requestId?: string;
        };
        FaucetResult: {
            /** @constant */
            status: "ok";
            address: string;
            ethWei: string;
            tokens: {
                symbol: string;
                amount: string;
            }[];
            dryRun: boolean;
        };
        FaucetFailure: {
            error: string;
            code: components["schemas"]["FaucetErrorCode"];
            correlationId: string;
        };
        RpcRequest: {
            /** @constant */
            jsonrpc?: "2.0";
            id?: null | string | number;
            method: string;
            params?: unknown[];
        } | {
            /** @constant */
            jsonrpc?: "2.0";
            id?: null | string | number;
            method: string;
            params?: unknown[];
        }[];
        ReconcileRequest: {
            /** @constant */
            kind: "cybergold-b2b-reconcile-request";
            /** @constant */
            formatVersion: 1;
            mode: components["schemas"]["InternalReconcileMode"];
        };
        ReconcileResult: {
            /** @enum {string} */
            status: "busy" | "deferred-cadence" | "incomplete" | "reconciled";
        };
        Receipt: {
            /** @constant */
            kind: "cybergold-onchain-indexer-reconciliation-receipt";
            /** @constant */
            formatVersion: 2;
            /** @constant */
            partial: false;
            reconciliationId: string;
            gatewayConfigRevision: string;
            runtimeConfigId: null | string;
            finalizedAnchor: {
                number: string;
                hash: string;
            };
            identities: {
                databaseSchemaVersion: string;
                rawJournalVersion: string;
                dashboardProjectionVersion: string;
                stateSnapshotVersion: string;
                safeCursorVersion: string;
            };
            rawJournal: {
                trackedAddressCount: number;
                cursorCount: number;
                logCount: string;
                cursors: {
                    address: string;
                    blockNumber: string;
                    blockHash: string;
                }[];
            };
            dashboardProjection: {
                /** @constant */
                cursorCount: 1;
                eventLogCount: string;
                blockNumber: string;
                blockHash: string;
                profile: string;
            };
            stateSnapshot: {
                /** @constant */
                cursorCount: 1;
                modelCount: string;
                blockNumber: string;
                blockHash: string;
                profile: string;
            };
            safeCursors: {
                configuredSafeCount: number;
                cursorCount: number;
                eventLogCount: string;
                cursors: {
                    address: string;
                    blockNumber: string;
                    blockHash: string;
                }[];
            };
            rpcRequests: {
                totalAttempts: number;
                failedAttempts: number;
                adaptiveRetryAttempts: number;
                byMethod: components["schemas"]["Record<\"eth_call\"|\"eth_chainId\"|\"eth_getBlockByHash\"|\"eth_getBlockByNumber\"|\"eth_getCode\"|\"eth_getLogs\",number>"];
                ethGetLogs: {
                    attempts: number;
                    plannedAttempts: number;
                    adaptiveAttempts: number;
                    failedAttempts: number;
                    /** @constant */
                    addressScopedViemTransportRetries: 0;
                    legacyViemTransportRetriesObserved: null;
                    bySource: components["schemas"]["Record<IndexerRpcRequestSource,number>"];
                    plannedBySource: components["schemas"]["Record<IndexerRpcRequestSource,number>"];
                };
            };
            completedAt: string;
            durationMs: number;
        };
        ForkStatus: {
            /** @constant */
            kind: "cybergold-sandbox-fork-generation-status";
            /** @constant */
            formatVersion: 1;
            current: {
                generation: string;
                forkBlock: string;
                forkBlockHash: string;
                status: string;
            } | null;
        };
        ForkResult: {
            /** @enum {string} */
            status: "already-applied" | "already-ready" | "busy" | "prepared";
        } | {
            /** @constant */
            status: "applied";
            plan: {
                kind: string;
                invalidateFrom: string;
                retainedThrough: null | string;
            };
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    get__api_protocol_facts: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolFacts"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_protocol_config: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolConfiguration"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_gold: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Gold"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_economic_quotes: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EconomicQuoteRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EconomicQuote"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_economic_quotes_stream: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EconomicQuoteRequest"];
            };
        };
        responses: {
            /** @description Canonical-ready qualified improvements, then exactly one complete or error. Snapshot disproof emits invalidated before error. Integers are decimal strings. */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/x-ndjson": components["schemas"]["EconomicQuoteEvent"];
                };
            };
            /** @description Existing response envelope */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_tx_preparations: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TransactionPreparationRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PreparedTransaction"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_economic_estimates: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TradeModelRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TradeQuoteModelPacket"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_quotes_universal_exact_input: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UniversalExactInputRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UniversalExactInputQuote"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_quotes_market: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MarketQuoteRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MarketQuoteResponse"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_quotes_market_stream: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MarketQuoteRequest"];
            };
        };
        responses: {
            /** @description Market model/estimate/progress/qualified, then complete or error; amount integers are decimal strings. */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/x-ndjson": components["schemas"]["MarketQuoteEvent"];
                };
            };
            /** @description Existing response envelope */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_quotes_market_model: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MarketModelRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MarketQuoteModelPacket"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_quotes_trade_stream: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TradeQuoteRequest"];
            };
        };
        responses: {
            /** @description Cached models, estimates and tagged provider progress; qualified best incumbents, then complete or error. Integers are decimal strings. */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/x-ndjson": components["schemas"]["TradeQuoteEvent"];
                };
            };
            /** @description Existing response envelope */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_quotes_trade_model: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TradeModelRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TradeQuoteModelPacket"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_transaction_revert: {
        parameters: {
            query: {
                hash: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransactionRevert"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_account_ens_name: {
        parameters: {
            query: {
                holder: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EnsName"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_account_ens_avatar_record: {
        parameters: {
            query: {
                name: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EnsAvatarRecord"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_account_native_balance: {
        parameters: {
            query: {
                holder: string;
                /** @description display opts ordinary loading out of the repeated chain check and final canonical block reread; omitted or other values retain both existing checks. */
                purpose?: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NativeBalance"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_account_wallet_balances: {
        parameters: {
            query: {
                holder: string;
                /** @description display opts ordinary loading out of the repeated chain check and final canonical block reread; omitted, swap-preflight or other values retain both existing checks. */
                purpose?: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WalletBalances"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_account_token_balance: {
        parameters: {
            query: {
                holder: string;
                tokenId: "eth" | "cygld" | "xaut" | "paxg" | "usdt" | "usdc" | "weth";
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WalletTokenBalance"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_account_liquidity_positions: {
        parameters: {
            query: {
                holder: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LiquidityPositions"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_governance_roles: {
        parameters: {
            query: {
                surface: "core" | "staking" | "governance-diamond";
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GovernanceRoles"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_governance_authority: {
        parameters: {
            query: {
                surface: "core" | "staking" | "governance-diamond";
                account?: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GovernanceAuthority"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_transaction_recovery_redemption: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecoveryRedemptionRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecoveryRedemption"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_transaction_permit2_approval_gas: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Permit2ApprovalGasRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Permit2ApprovalGas"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_governance_safe_nonce: {
        parameters: {
            query: {
                address: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SafeNonce"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_governance_safe_transaction_hash: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SafeTransactionHashRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SafeTransactionHash"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_governance_safe_execution: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SafeExecutionRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SafeExecution"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_transaction_helpers_execution: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["HelpersExecutionRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HelpersExecution"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_transaction_receipt: {
        parameters: {
            query: {
                hash: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransactionReceiptObservation"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_transaction_wait_head: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReceiptWaitHead"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_transaction_wait_transaction: {
        parameters: {
            query: {
                hash: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReceiptWaitTransaction"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_transaction_wait_receipt: {
        parameters: {
            query: {
                hash: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReceiptWaitReceipt"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_transaction_wait_block: {
        parameters: {
            query: {
                blockNumber: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReceiptWaitBlock"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_account_transaction_nonce: {
        parameters: {
            query: {
                owner: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransactionNonce"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_transaction_fees: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransactionFees"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_protocol_recovery_share_precision: {
        parameters: {
            query: {
                asset: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecoverySharePrecision"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_protocol_recovery_assets: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CoreRecoveryAssets"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_account_permit2: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Permit2ContextRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Permit2Context"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_tokens_metadata: {
        parameters: {
            query: {
                token: string;
                holder?: string;
                /** @description balance reads only selected holder balance/context; metadata fields and authorization are explicitly not-requested. Default and other values retain optional discovery. */
                purpose?: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenMetadata"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_account_token_permit: {
        parameters: {
            query: {
                token: string;
                owner: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenPermitContext"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_transaction_token_approval_gas: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TokenApprovalGasRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenApprovalGas"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_account_core_permit: {
        parameters: {
            query: {
                owner: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CorePermit"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_governance_core_facts: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GovernanceCoreFacts"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_governance_helpers_facts: {
        parameters: {
            query?: {
                adapter?: string;
                tokenPermitIssuance?: "true";
                basketPermitIssuance?: "true";
                universalExactInput?: "true";
                marketSwap?: "true";
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HelpersRouterFacts"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_governance_safe_principal: {
        parameters: {
            query: {
                address: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GovernanceSafePrincipal"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_governance_target_code: {
        parameters: {
            query: {
                address: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GovernanceTargetCode"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_quotes_basket_preview: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BasketPreviewRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BasketPreview"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_quotes_basket_max: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BasketMaxRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BasketMax"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_quotes_token_preview: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TokenPreviewRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenPreview"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_quotes_routes: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RouteSearchRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RouteSearch"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_quotes_routes_stream: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RouteSearchRequest"];
            };
        };
        responses: {
            /** @description One RouteSearchEvent JSON object per line; progress, then complete or error. */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/x-ndjson": components["schemas"]["RouteSearchEvent"];
                };
            };
            /** @description Existing response envelope */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_quotes_intent_stream: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QuoteIntentRequest"];
            };
        };
        responses: {
            /** @description One QuoteIntentEvent per line; optional model/estimate/progress/qualified, then complete or error. */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/x-ndjson": components["schemas"]["QuoteIntentEvent"];
                };
            };
            /** @description Existing response envelope */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_quotes_uniswap: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UniswapQuoteRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UniswapQuote"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_fx: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Fx"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_activity_core: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CoreActivity"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_activity_helpers: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HelpersActivity"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_activity_pools: {
        parameters: {
            query?: {
                protocol?: "v2" | "v3" | "v4";
                poolId?: string;
                poolAddress?: string;
                poolManager?: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PoolActivity"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_activity_safe: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SafeActivity"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_diagnostics: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ClientDiagnostic"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            202: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        /** @constant */
                        accepted: true;
                    };
                };
            };
            /** @description Existing response envelope */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_dashboard_onchain_summary: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Dashboard"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_recovery_shares: {
        parameters: {
            query: {
                holder: string;
                offset?: string;
                blockHash?: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Recovery"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_rpc: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RpcRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Remote entry bearer rejected before JSON-RPC parsing */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing single/batch JSON-RPC error with preserved IDs */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    post__api_governance_owner_aliases: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AliasesRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AliasesResult"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_quote_pool_cache: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PoolRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PoolResult"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_pools_snapshot: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PoolIdentifier"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PoolSnapshot"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_pools_catalog: {
        parameters: {
            query?: {
                tokenA?: string;
                tokenB?: string;
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PoolCatalog"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_safe: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SafeRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_safe_events: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SafeEventsRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SafeEventsResult"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_faucet: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FaucetRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FaucetResult"];
                };
            };
            /** @description Remote API entry requires its environment's backend bearer */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Safe faucet failure with stable code and backend log reference */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FaucetFailure"];
                };
            };
        };
    };
    get__api_internal_onchain_indexer_reconcile: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Receipt"];
                };
            };
            /** @description Private worker bearer rejected */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_internal_onchain_indexer_reconcile: {
        parameters: {
            query?: {
                force?: "1";
                diagnostic?: "1";
            };
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        /** @description An empty body retains the existing legacy protocol. */
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ReconcileRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReconcileResult"];
                };
            };
            /** @description Existing response envelope */
            202: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReconcileResult"];
                };
            };
            /** @description Existing response envelope */
            409: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReconcileResult"];
                };
            };
            /** @description Existing response envelope */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    get__api_internal_onchain_indexer_fork_generation: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ForkStatus"];
                };
            };
            /** @description Private worker bearer rejected */
            401: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
            /** @description Existing route-specific errors; see compatibility fixtures */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
    post__api_internal_onchain_indexer_fork_generation: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional UUID for one browser trade attempt. Invalid values are ignored. */
                "X-CyberGold-Attempt-Id"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ForkRequest"];
            };
        };
        responses: {
            /** @description Existing response envelope */
            200: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ForkResult"];
                };
            };
            /** @description Existing response envelope */
            409: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ForkResult"];
                };
            };
            /** @description Existing response envelope */
            default: {
                headers: {
                    /** @description Backend request reference, separate for each subscriber to shared quote work. */
                    "X-CyberGold-Request-Id"?: string;
                    /** @description Optional observed Backend build commit from this responding process; absent for unversioned local builds. */
                    "X-CyberGold-Backend-Revision"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicError"];
                };
            };
        };
    };
}
