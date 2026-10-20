import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import * as TJS from "typescript-json-schema";
import openapiTS, { astToString } from "openapi-typescript";

const program = TJS.programFromConfig(resolve("tsconfig.json"));
const schema = TJS.generateSchema(program, "ContractSchemas", { required: true, strictNullChecks: true });
if (!schema) throw new Error("ContractSchemas could not be generated");
const definitions = { ...schema.definitions };
for (const [name, value] of Object.entries(schema.properties ?? {})) {
  if (typeof value === "object" && value.$ref === `#/definitions/${name}`) continue;
  definitions[name] = value;
}
const schemas = JSON.parse(JSON.stringify(definitions)
  .replaceAll("#/definitions/", "#/components/schemas/"));
const ref = (name: string) => ({ $ref: `#/components/schemas/${name}` });
const json = (schema: object) => ({ "application/json": { schema } });
const response = (schema: object, description = "Existing response envelope") => ({ description, content: json(schema) });
const paths: Record<string, object> = {};
function operation(path: string, method: "get" | "post", result?: string, body?: string, extra: object = {}) {
  paths[path] = { ...paths[path], [method]: {
    operationId: `${method}_${path.replace(/[^a-zA-Z0-9]+/g, "_")}`,
    ...(body ? { requestBody: { required: true, content: json(ref(body)) } } : {}),
    responses: { "200": response(result ? ref(result) : {}),
      "401": response(ref("PublicError"), path.startsWith("/api/internal/")
        ? "Private worker bearer rejected" : "Remote API entry requires its environment's backend bearer"),
      default: response(ref("PublicError"), "Existing route-specific errors; see compatibility fixtures") }, ...extra,
  } };
}
operation("/api/protocol/facts", "get", "ProtocolFacts", undefined, {
  description: "Live configured Core/Helpers facts at one canonical block hash, with lossless raw values and per-read failures. No caller-selected ABI, contract target or provider. No database reconciliation or browser RPC fallback. Signing remains browser-owned.",
});
operation("/api/protocol/config", "get", "ProtocolConfiguration", undefined, {
  description: "Configured deployment anchors and the App's initial token catalog, with a cached supported adapter selected from the canonical Helpers allowlist. No request-time chain RPC, routing-infrastructure exposure, signing or submission. Missing optional roots/adapter remain independent; live pause, roles and pre-sign observations keep their existing APIs. Sandbox generation uses the existing durable reset context.",
});
operation("/api/gold", "get", "Gold");
operation("/api/quotes/universal-exact-input", "post", "UniversalExactInputQuote", "UniversalExactInputRequest", {
  description: "Gross-funded universal exact-input plans for scalar Core/Market mixtures and direct basket issue/redemption. One joint Core invocation per candidate; 0/25/50/75/100 Core allocation and both mixed orders replay shared AMM pools in execution order. Measured unused AMM input is a disclosed protocol charge held by Helpers under its current owner. Native ETH and WETH are distinct currencies. The configured successor address is required; no signing, submission, deployment, or silent legacy-plan rebinding.",
});
operation("/api/quotes/market", "post", "MarketQuoteResponse", "MarketQuoteRequest", {
  description: "Fresh exact-input requests delegate to the universal coordinator quote service when its release is configured, returning a disclosed Core/Market/mixed plan. True exact-output and captured legacy plans keep their original address, encoding, and refund semantics. Wallet funding, signing, full-call simulation and submission remain in the App.",
});
operation("/api/quotes/market/stream", "post", "MarketQuoteEvent", "MarketQuoteRequest", {
  responses: { "200": { description: "Market model/estimate/progress/qualified, then complete or error; amount integers are decimal strings.",
    content: { "application/x-ndjson": { schema: ref("MarketQuoteEvent") } } }, default: response(ref("PublicError")) },
});
operation("/api/quotes/market/model", "post", "MarketQuoteModelPacket", "MarketModelRequest", {
  description: "Amount-independent market model acquisition for an active view, without prior successful quotes, wallet signing or a mandatory tick scan. Canonical pool baseline plus contextual organic raw-AMM points; missing optional model state leaves ordinary quotes available.",
});
operation("/api/quotes/trade/stream", "post", "TradeQuoteEvent", "TradeQuoteRequest", {
  description: "Fresh exact-input trades use the universal Core/Market allocation grid when the universal release is configured. True exact-output preserves existing provider selection. A fresh output-target Core-sale winner becomes a newly disclosed Core-only universal quote at its solved gross input, preserving accepted scalar and Core vector minima. Captured legacy plans never silently change address or encoding. Signing and submission remain in the App.",
  responses: { "200": { description: "Cached models, estimates and tagged provider progress; qualified best incumbents, then complete or error. Integers are decimal strings.", content: { "application/x-ndjson": { schema: ref("TradeQuoteEvent") } } }, default: response(ref("PublicError")) },
});
operation("/api/quotes/trade/model", "post", "TradeQuoteModelPacket", "TradeModelRequest", {
  description: "Organic Core and market models with a Backend-ranked indicative estimate. Warm cached packets require no RPC; cold acquisition reuses existing lightweight provider baselines and shared context. Missing model state does not prevent exact trade search; neither models nor estimates are executable quotes.",
});
operation("/api/transaction/revert", "get", "TransactionRevert", undefined, {
  parameters: [{ name: "hash", in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{64}$" } }],
  description: "Replays the chain transaction at latest state for the Apps' receipt error display, using its hash only. EVM return bytes are preserved; private provider text is redacted, native absence/outage remains unavailable. This is not a historical proof of the original revert and never signs/submits or accepts caller-selected calldata/provider.",
});
operation("/api/account/ens-name", "get", "EnsName", undefined, {
  parameters: [{ name: "holder", in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } }],
  description: "Ethereum primary ENS name via standard Web3.py, including forward-address verification, at the configured canonical block. Missing record is null; transport failure is unavailable. No caller-selected resolver, provider or database work.",
});
operation("/api/account/ens-avatar-record", "get", "EnsAvatarRecord", undefined, {
  parameters: [{ name: "name", in: "query", required: true, schema: { type: "string" } }],
  description: "The Apps' avatar text record via standard Web3.py ENS at the configured canonical block. Standard ERC721 tokenURI / ERC1155 uri reads for NFT records use that same hash and return explicit per-read success/failure. Standard Viem retains URI/metadata/image rendering in the browser. No image or metadata URL is fetched by the server; no caller-selected ABI or provider.",
});
operation("/api/account/native-balance", "get", "NativeBalance", undefined, {
  parameters: [{ name: "holder", in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } },
    { name: "purpose", in: "query", required: false, schema: { type: "string" }, description: "display opts ordinary loading out of the repeated chain check and final canonical block reread; omitted or other values retain both existing checks." }],
  description: "The Apps wallet-library latest native ETH balance for its holder at one EIP-1898 canonical block hash from the configured provider. purpose=display opts ordinary loading out of the repeated chain check and final block reread; unmarked and other requests retain both existing checks. Lossless decimal amount; no unrelated token reads, provider selection, shared wallet cache or signing. Historical/pending-tag library requests retain compatibility until separately migrated.",
});
operation("/api/account/wallet-balances", "get", "WalletBalances", undefined, {
  parameters: [{ name: "holder", in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } },
    { name: "purpose", in: "query", required: false, schema: { type: "string" }, description: "display opts ordinary loading out of the repeated chain check and final canonical block reread; omitted, swap-preflight or other values retain both existing checks." }],
  description: "The Apps' six fixed ERC20 assets plus native ETH in one Multicall3 aggregate3 eth_call at one EIP-1898 canonical block hash from the configured provider. Each member allows failure; ETH uses Multicall3.getEthBalance(holder) inside the same aggregate. purpose=display opts ordinary loading out of the repeated chain check and final block reread; unmarked, swap-preflight and other requests retain both existing checks. Lossless decimal amounts and per-asset failures; no caller-selected token, ABI or provider. No separate native balance RPC, database or shared wallet cache; signing remains browser-owned.",
});
operation("/api/account/token-balance", "get", "WalletTokenBalance", undefined, {
  parameters: [{ name: "holder", in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } },
    { name: "tokenId", in: "query", required: true, schema: { type: "string", enum: ["eth", "cygld", "xaut", "paxg", "usdt", "usdc", "weth"] } }],
  description: "Compatibility balance read for one of the Apps' seven fixed wallet assets at its own canonical block. Uses the existing configured Core for CYGLD and fixed Ethereum reserve-token addresses, or native ETH. Lossless decimal raw balance and explicit per-read failure; unrelated assets are never read. Current wallet display and transaction flows use the complete wallet-balances Multicall3 snapshot. No caller-selected contract, ABI or provider, shared wallet cache, signing or submission. Existing fifteen-second deadline, caller cancellation and no-store apply.",
});
operation("/api/account/liquidity-positions", "get", "LiquidityPositions", undefined, {
  parameters: [{ name: "holder", in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } }],
  description: "Wallet-owned Uniswap v4 PAXG/CYGLD LP NFTs for the fixed Ethereum pool, discovered from incoming/outgoing Transfer logs since pool initialization. Position reads share one canonical block hash. Per-position and aggregate decimal token quantities include deposited principal plus unclaimed LP fees, calculated from the position's liquidity and Q128 fee-growth delta with uint256 wraparound. Fee-read failures are unavailable, never a partial principal-only total. Uses the configured environment RPC, so Sandbox fork results can differ from Mainnet. No caller-selected pool, ABI or provider, database work, shared wallet cache, signing or submission.",
});
operation("/api/governance/roles", "get", "GovernanceRoles", undefined, {
  parameters: [{ name: "surface", in: "query", required: true, schema: { type: "string", enum: ["core", "staking", "governance-diamond"] } }],
  description: "The configured Apps' fixed diamond role rosters at one canonical block. Preserves the existing first-50 display policy, raw expected counts and per-member failures. Missing configuration is explicit. No caller-selected address, role, ABI or provider, authority decision, signing or submission.",
});
operation("/api/governance/authority", "get", "GovernanceAuthority", undefined, {
  parameters: [{ name: "surface", in: "query", required: true, schema: { type: "string", enum: ["core", "staking", "governance-diamond"] } },
    { name: "account", in: "query", required: false, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } }],
  description: "Configured diamond paused/Safe wallet and existing canPause/canUnpause observations at one canonical block. Optional connected account is observed without deciding authority, signing or submission. Per-read failures stay explicit; no arbitrary contract, method, ABI or provider.",
});
operation("/api/transaction/recovery-redemption", "post", "RecoveryRedemption", "RecoveryRedemptionRequest", {
  description: "Simulate the App's exact configured Core redeemRecoveryShares call, with holder as sender and recipient and unchanged shares/minRawOut. Canonical configured-chain context and lossless output; no wallet signature, submission, arbitrary ABI, target or provider. Failure never becomes a successful preview.",
});
operation("/api/transaction/permit2-approval-gas", "post", "Permit2ApprovalGas", "Permit2ApprovalGasRequest", {
  description: "Native latest-state gas estimate for the App's fixed ERC20 approve(configured Permit2, maxUint256) operation. Existing holder/token and configured Helpers spender, no arbitrary amount, ABI, provider, signing, submission or reservation. The App retains its gas padding and existing failure fallback.",
});
operation("/api/governance/safe-nonce", "get", "SafeNonce", undefined, {
  parameters: [{ name: "address", in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } }],
  description: "Fresh Safe contract nonce at a canonical configured-chain block. No nonce reservation, generic ABI/provider, signing or submission. The App retains pending proposal selection and wallet intent.",
});
operation("/api/governance/safe-transaction-hash", "post", "SafeTransactionHash", "SafeTransactionHashRequest", {
  description: "The existing Apps' fixed Safe getTransactionHash read for their exact unsigned payload. Standard ABI encoding preserves integer and byte values. No signing, proposal publication, simulation, submission or server-selected transaction fields.",
});
operation("/api/governance/safe-execution", "post", "SafeExecution", "SafeExecutionRequest", {
  description: "Simulate the App's exact Safe execTransaction at latest state, with unchanged payload, signatures, executor and pending executor nonce. A returned false remains false; reverts/outage remain unavailable. No signing, submission, transaction replacement, arbitrary ABI or provider, or server-selected transaction intent.",
});
operation("/api/transaction/helpers-execution", "post", "HelpersExecution", "HelpersExecutionRequest", {
  description: "Helpers Swap operation fee hints, including mixed native/Permit2 basket acquisition and existing allowance redemption: exact caller arguments and optional native value, fixed configured Helpers ABI/target, latest-state simulation followed by native gas estimation. Decimal JSON amounts preserve ABI values. No ABI, provider, target, signing, submission or server-selected intent is accepted from the App. The existing caller keeps fee-hint failure behavior.",
});
operation("/api/transaction/receipt", "get", "TransactionReceiptObservation", undefined, {
  parameters: [{ name: "hash", in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{64}$" } }],
  description: "Fresh configured-chain receipt status, block identity and raw logs for the Apps' Safe history. Native receipt absence is null/unknown; provider failure is unavailable, never inferred pending/replaced/cancelled. No database, cache, confirmations, replacement search, signing or submission.",
});
for (const [operationName, schemaName, parameter] of [
  ["head", "ReceiptWaitHead", undefined],
  ["transaction", "ReceiptWaitTransaction", "hash"],
  ["receipt", "ReceiptWaitReceipt", "hash"],
  ["block", "ReceiptWaitBlock", "blockNumber"],
] as const) {
  operation(`/api/transaction/wait/${operationName}`, "get", schemaName, undefined, {
    ...(parameter ? { parameters: [{ name: parameter, in: "query", required: true,
      schema: { type: "string", pattern: parameter === "hash" ? "^0x[0-9a-fA-F]{64}$" : "^[0-9]+$" } }] } : {}),
    description: "Fresh configured-chain observation for the Apps' existing Viem receipt confirmation/replacement algorithm. Head is decimal; native Ethereum transaction, receipt and full-block wire fields retain lossless hex quantities and standard formatter behavior. Native absence is null; supplier failures stay errors. No arbitrary method, provider, ABI, signing, submission or server notification queue.",
  });
}
operation("/api/account/transaction-nonce", "get", "TransactionNonce", undefined, {
  parameters: [{ name: "owner", in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } }],
  description: "Fresh configured-chain pending account nonce for the Apps' Governance transactions. Lossless decimal nonce and canonical head context; pending state itself is not block-pinned. No cache, reservation, EOA/code prerequisite, simulation, signing or submission. Existing wallet intent and chain checks remain in the App.",
});
operation("/api/transaction/fees", "get", "TransactionFees", undefined, {
  description: "The configured Ethereum App's EIP-1559 fee estimate, preserving its 1.2 base-fee multiplier and priority-method gas-price fallback. Lossless decimal fees with canonical configured-chain block context. No fee cache, simulation, signing or submission.",
});
operation("/api/protocol/recovery-share-precision", "get", "RecoverySharePrecision", undefined, {
  parameters: [{ name: "asset", in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } }],
  description: "The configured Core recoveryPool's permanent shareDecimals for the App's quote display at one canonical block. Current basket membership and token decimals do not determine share precision. No caller-selected contract, ABI, provider, wallet action or shared account cache.",
});
operation("/api/protocol/recovery-assets", "get", "CoreRecoveryAssets", undefined, {
  description: "The configured Core's attached recovery assets in contract order, at one canonical configured-chain block. Empty success is distinct from unavailable; the App constructs redemption minima. No caller ABI/provider/contract target, cache, schema work or signing.",
});
operation("/api/account/permit2", "post", "Permit2Context", "Permit2ContextRequest", {
  description: "The App's fixed fresh Permit2 router/bytecode verification, first-unused nonce traversal and selected token allowances at one canonical block. Helpers chooses the Permit2 target; callers supply only owner/token observations, never a spender, ABI, provider or method. Ordered decimal allowances/nonce retain all bits. No cache, nonce reservation, approval, signing or submission; existing App verification and wallet-intent checks remain.",
});
operation("/api/tokens/metadata", "get", "TokenMetadata", undefined, {
  parameters: [{ name: "token", in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } },
    { name: "holder", in: "query", required: false, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } },
    { name: "purpose", in: "query", required: false, schema: { type: "string" }, description: "balance reads only selected holder balance/context; metadata fields and authorization are explicitly not-requested. Default and other values retain optional discovery." }],
  description: "Selected ERC20 string/legacy bytes32 metadata and optional holder balance through the configured provider. Lossless balance and per-field errors; purpose=balance skips metadata/domain/qualification work for ordinary wallet refresh. Otherwise optional standard-permit domain qualification uses disposable in-memory signatures only inside eth_call. Capability is independent of quote/approval eligibility. No generic ABI, method, provider, user signing or submission. Bounded process-local reusable metadata, existing deadline/cancellation and no-store.",
});
operation("/api/account/token-permit", "get", "TokenPermitContext", undefined, {
  parameters: ["token", "owner"].map(name => ({ name, in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } })),
  description: "Fresh selected ERC20 owner nonce and configured Helpers allowance at one canonical block. Domain separator is reread and changes invalidate reusable domain observations. Explicit unknown, no-native-permit, variants and RPC unavailability; no cached user nonce, reservation, server-selected value/deadline, user signature or submission.",
});
operation("/api/transaction/token-approval-gas", "post", "TokenApprovalGas", "TokenApprovalGasRequest", {
  description: "Native latest-state gas estimation for the exact selected ERC20 approve(configured Helpers, amount), including zero-first reset amount zero. Lossless amount, no spender/provider/ABI selection or submission; nonstandard approval return data is not decoded or relabeled.",
});
operation("/api/account/core-permit", "get", "CorePermit", undefined, {
  parameters: [{ name: "owner", in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } }],
  description: "Fresh configured Core name and owner nonce at one canonical block, preserving the App's version-1 EIP-2612 domain and configured Helpers spender. Lossless decimal nonce, no cache/ABI/provider/contract selection. The App keeps value/deadline choice, wallet chain checks, signing and submission. Read failures never supply a zero/default nonce.",
});
operation("/api/governance/core-facts", "get", "GovernanceCoreFacts", undefined, {
  description: "Configured Core governance configuration at one canonical block: treasury, basket hash, fees and supply limits. Preserves per-field failures and decimal amounts. No caller-selected contract, ABI or provider; wallet signing and submission remain in the App.",
});
operation("/api/governance/helpers-facts", "get", "HelpersRouterFacts", undefined, {
  parameters: [{ name: "adapter", in: "query", required: false, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } },
    { name: "tokenPermitIssuance", in: "query", required: false, schema: { type: "string", enum: ["true"] } },
    { name: "basketPermitIssuance", in: "query", required: false, schema: { type: "string", enum: ["true"] } },
    { name: "universalExactInput", in: "query", required: false, schema: { type: "string", enum: ["true"] } },
    { name: "marketSwap", in: "query", required: false, schema: { type: "string", enum: ["true"] } }],
  description: "Configured Helpers fee, Permit2, wrapped native token, owner, complete adapter allowlist and pause state at one canonical block. Optional App swap-adapter address adds its native code-presence observation at that block, preserving the existing pre-submission check. Lossless fee and per-field failures; no caller-selected ABI, method or provider. Adapter approval is membership in this same canonical enumerable allowlist. Historical tokenPermitIssuance/basketPermitIssuance probes report selector installation for retained deployments; universalExactInput=true separately observes the canonical executeExactInput selector through the same Diamond facetAddress read. Absence remains false and read failure remains unavailable. Signing/submission stay browser-owned.",
});
operation("/api/governance/safe-principal", "get", "GovernanceSafePrincipal", undefined, {
  parameters: [{ name: "address", in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } }],
  description: "The App's governance principal bytecode, Safe owners and threshold at one canonical configured-chain block. Per-field failures and a lossless threshold preserve the App's existing authority interpretation. No caller-selected ABI, method or provider, role authorization, nonce, database write, signing or submission.",
});
operation("/api/governance/target-code", "get", "GovernanceTargetCode", undefined, {
  parameters: [{ name: "address", in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } }],
  description: "Fresh configured-chain code presence for the Apps' Safe proposal destination description, at one canonical block. Empty code is false; supplier failure is unavailable, never an EOA classification. No ABI, method, provider, simulation, authority decision, signing or submission; the App retains its existing proposal interpretation.",
});
operation("/api/quotes/basket-preview", "post", "BasketPreview", "BasketPreviewRequest", {
  description: "The four Helpers issue/redeem basket previews used by Swap, at one canonical configured-chain block. Raw amounts remain decimal strings and basket order is preserved. No caller-selected target, ABI, method or provider. No database, server transaction submission or retry. Wallet signing remains frontend-owned.",
});
operation("/api/quotes/basket-max", "post", "BasketMax", "BasketMaxRequest", {
  description: "Largest wallet-bounded proportional basket driver whose unclipped direct-basket mint fits current gross capacity. Uses configured Core assets, weights, decimals, conversion and fee rounding at one canonical block, with an ordinary positive exact-in Helpers preview. Zero capacity returns zero amounts. No wallet read, signing, submission, Market basket provider or client fee calculation.",
});
operation("/api/quotes/token-preview", "post", "TokenPreview", "TokenPreviewRequest", {
  description: "The Apps' six token/native Helpers issue/redeem previews at one canonical configured-chain block. Preserves ordered opaque adapter calldata and lossless amounts; no routing, slippage modification, caller-selected target/ABI/provider, signing or submission. Ordinary contract errors remain recoverable preview failures.",
});
operation("/api/quotes/routes", "post", "RouteSearch", "RouteSearchRequest", {
  description: "Route search for all ordered targets through one structured route engine and shared candidate scheduler. Preserves direct/via-WETH V3 fee coverage alongside the selected protocol inventory, using SDK pool math and ordinary native Quoter fallback at one canonical block. Exact-output path reversal is a compatibility projection; internal routes keep forward economic direction. Independent candidate failures remain partial failures. No caller-selected ABI, provider or target contract, wallet signing or submission. Lossless amounts, no-store and existing deadline/cancellation; RPC metrics marked coordinator are not supplier call totals.",
});
operation("/api/quotes/routes/stream", "post", "RouteSearchEvent", "RouteSearchRequest", {
  description: "Newline-delimited progress snapshots as candidates settle through the common structured route engine and scheduler. Known inventory overlaps discovery; provisional progress does not prove execution readiness, and only complete follows the existing canonicality check. Original V3 coverage and selected graph routes share SDK pricing, native fallback, candidate errors and owned-task cancellation/drain. Transport/reorg failure emits a redacted terminal error with optional observed RPC diagnostics. No caller-selected contract/provider or submission.",
  responses: { "200": { description: "One RouteSearchEvent JSON object per line; progress, then complete or error.", content: { "application/x-ndjson": { schema: ref("RouteSearchEvent") } } },
    default: response(ref("PublicError")) },
});
operation("/api/quotes/intent/stream", "post", "QuoteIntentEvent", "QuoteIntentRequest", {
  description: "Recipient-less legacy Core quote API. Once the universal release is configured, modes that previously executed exact input return explicitly read-only numeric results without leg calldata or execution recipes. Pure numerical previews and true issue exact-output retain their existing behavior; use the canonical universal endpoint for new exact-input execution.",
  responses: { "200": { description: "One QuoteIntentEvent per line; optional model/estimate/progress/qualified, then complete or error.", content: { "application/x-ndjson": { schema: ref("QuoteIntentEvent") } } }, default: response(ref("PublicError")) },
});
operation("/api/quotes/uniswap", "post", "UniswapQuote", "UniswapQuoteRequest", {
  description: "A caller-selected V3 path is normalized once to a forward structured route and priced by the same SDK quote engine and ordinary native Quoter fallback as route search, at one canonical block. Exact-output packed input retains its established reversed wire order; the result remains one lossless decimal amount. The returned Quoter address identifies the configured native reference, not the source of every successful computation. No caller-selected contract, ABI/provider, wallet signing or transaction submission, and no additional hop, token or path policy.",
});
operation("/api/fx", "get", "Fx");
operation("/api/activity/core", "get", "CoreActivity", undefined, {
  description: "Latest 100 retained Core journal logs, decoded with shipped and historical migration events. Reports stored journal range and undecoded rows; no RPC, replay, database writes or claim to include failed or no-event transactions. No public frontend adapter is required for this operator API.",
});
operation("/api/activity/helpers", "get", "HelpersActivity", undefined, {
  description: "Latest 100 retained Helpers settlement, fee, dust and administration logs with canonical ABI decoding. Its own address-scoped finalized journal starts at the configured collection boundary and reports its independent backfill cursor. Unknown historical layouts remain visible without decoded arguments. No Core supply/reserve double counting, RPC collection on reads or public frontend adapter.",
});
operation("/api/activity/pools", "get", "PoolActivity", undefined, {
  parameters: [
    { name: "protocol", in: "query", required: false, schema: { type: "string", enum: ["v2", "v3", "v4"] } },
    { name: "poolId", in: "query", required: false, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{64}$" } },
    ...["poolAddress", "poolManager"].map(name => ({ name, in: "query", required: false,
      schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } })),
  ],
  description: "Latest 100 persisted V2/V3/V4 pool events across the known CYGLD and active connector inventory. Each exact pool identity retains up to 1000 events and 64 canonical scan-range rollups with explicit coverage. Worker state logs are reused; endpoint reads never acquire RPC logs, backfill, write activity or gate quotes/models. Raw signed amounts and protocol-specific input/output volume exclude USD, per-pool TVL and all-time claims; liquidity deltas remain range units, not token quantities. V4 identity includes PoolManager and PoolId. Existing environment bearer/no-store activity conventions apply.",
});
operation("/api/activity/safe", "get", "SafeActivity", undefined, {
  description: "Latest 100 retained logs across the configured Safes. Decodes existing indexed/non-indexed execution layouts, reports each journal range and the unchanged execution-projection lookback. Includes older retained rows without RPC backfill, projection writes or a claim to complete Safe history. Operator API behind the existing environment bearer; no frontend adapter.",
});
operation("/api/diagnostics", "post", undefined, "ClientDiagnostic", {
  description: "Best-effort, untrusted browser observations projected onto fixed fields in the existing JSON log, including optional signed numeric wallet/RPC codes and four-byte EVM error selectors. Invalid optional fields are ignored. No raw messages, wallet addresses, signatures, error arguments or RPC bodies. An acknowledgement is not proof of collector delivery.",
  responses: { "202": response({ type: "object", properties: { accepted: { const: true } }, required: ["accepted"] }),
    default: response(ref("PublicError")) },
});
operation("/api/dashboard/onchain-summary", "get", "Dashboard", undefined, {
  description: "Completed PostgreSQL dashboard projection, including its existing disabled response; never triggers reconciliation. Sandbox responses also carry the existing durable fork generation for clearing old browser transaction/receipt state; a null or absent marker does not identify a new generation.",
});
operation("/api/recovery/shares", "get", "Recovery", undefined, {
  parameters: [
    { name: "holder", in: "query", required: true, schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } },
    { name: "offset", in: "query", schema: { type: "string", pattern: "^(0|[1-9][0-9]{0,77})$" } },
    { name: "blockHash", in: "query", schema: { type: "string", pattern: "^0x[0-9a-fA-F]{64}$" } },
  ], description: "Live hash-pinned portfolio. A nonzero offset requires blockHash; all responses are no-store.",
});
operation("/api/rpc", "post", undefined, "RpcRequest", {
  description: "Existing read-only JSON-RPC compatibility policy; raw body up to 1 MiB and batch up to 100. After ingress authentication, errors use JSON-RPC envelopes.",
  responses: { "200": response({}), "401": response(ref("PublicError"), "Remote entry bearer rejected before JSON-RPC parsing"),
    default: response({}, "Existing single/batch JSON-RPC error with preserved IDs") },
});
operation("/api/governance/owner-aliases", "post", "AliasesResult", "AliasesRequest");
operation("/api/quote-pool-cache", "post", "PoolResult", "PoolRequest", {
  description: "Retained cache envelopes. The Python pool-authority release accepts browser pool identifiers only; existence/addresses/price/liquidity and quote-success hints are never trusted. Reads refresh historical rows through the configured chain; an outage never publishes browser-owned observations.",
});
operation("/api/pools/snapshot", "post", "PoolSnapshot", "PoolIdentifier", {
  description: "Canonical configured-chain V2/V3/V4 pool state from the shared quote registry. Omitted protocol retains the legacy V3 response. V4 identity includes PoolManager and full PoolKey; its singleton token balances/TVL are absent. Marginal price is the raw token1/token0 rational, concentrated active liquidity is not total TVL, and tick/bitmap coverage contains only acquired ranges. Integer values remain lossless; caller state is never authoritative.",
});
operation("/api/pools/catalog", "get", "PoolCatalog", undefined, {
  parameters: [
    { name: "tokenA", in: "query", schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } },
    { name: "tokenB", in: "query", schema: { type: "string", pattern: "^0x[0-9a-fA-F]{40}$" } },
  ],
  description: "Known canonical CYGLD V2/V3/V4 pool identities, or pair-filtered known inventory. Uses the existing monthly discovery/event registry; no fresh catalog scan, pool getter wave, or client poller. Coverage is the selected inventory, not a claim to have discovered every possible pool.",
});
operation("/api/safe", "post", undefined, "SafeRequest", {
  description: "Preserves the selected Safe upstream service's JSON response; proposal/confirmation requests are never automatically retried.",
});
operation("/api/safe/events", "post", "SafeEventsResult", "SafeEventsRequest");
operation("/api/faucet", "post", "FaucetResult", "FaucetRequest", {
  description: "Sandbox faucet, authenticated by the shared backend bearer. Route failures retain safe error text and add a stable faucet code and correlationId matching the backend failure log. Known adapter outcomes distinguish quota, in-progress, uncertain, conflict and funding failure. Transport deadlines do not prove that funding failed. Private adapter status/code and elapsed time stay in the correlated backend log. Forward trusted nginx client IP; retain Retry-After and X-CyberGold-Faucet-Request-Id. No Origin check or separate caller credential, implicit retry or changed funding behavior.",
  responses: { "200": response(ref("FaucetResult")),
    "401": response(ref("PublicError"), "Remote API entry requires its environment's backend bearer"),
    default: response(ref("FaucetFailure"), "Safe faucet failure with stable code and backend log reference") },
});
const worker = { security: [{ WorkerBearer: [] }], "x-cybergold-listener": "worker",
  description: "Private Ops control only; public frontend has no adapter. Existing versioned worker protocol and raw parser remain authoritative." };
operation("/api/internal/onchain-indexer/reconcile", "get", "Receipt", undefined, worker);
operation("/api/internal/onchain-indexer/reconcile", "post", "ReconcileResult", undefined, {
  ...worker,
  requestBody: { required: false, description: "An empty body retains the existing legacy protocol.", content: json(ref("ReconcileRequest")) },
  parameters: ["force", "diagnostic"].map(name => ({ name, in: "query", schema: { type: "string", enum: ["1"] } })),
  responses: { "200": response(ref("ReconcileResult")), "202": response(ref("ReconcileResult")),
    "409": response(ref("ReconcileResult")), default: response(ref("PublicError")) },
});
operation("/api/internal/onchain-indexer/fork-generation", "get", "ForkStatus", undefined, worker);
operation("/api/internal/onchain-indexer/fork-generation", "post", "ForkResult", "ForkRequest", {
  ...worker, responses: { "200": response(ref("ForkResult")), "409": response(ref("ForkResult")), default: response(ref("PublicError")) },
});
// Diagnostic linkage is optional on every fixed operation and grants no
// authority. Existing clients can ignore it; IDs never become metric labels.
for (const methods of Object.values(paths)) {
  for (const value of Object.values(methods as Record<string, any>)) {
    value.parameters = [...(value.parameters ?? []), { name: "X-CyberGold-Attempt-Id", in: "header",
      required: false, description: "Optional UUID for one browser trade attempt. Invalid values are ignored.",
      schema: { type: "string", format: "uuid" } }];
    for (const reply of Object.values(value.responses) as Record<string, any>[]) {
      reply.headers = { ...(reply.headers ?? {}), "X-CyberGold-Request-Id": {
        description: "Backend request reference, separate for each subscriber to shared quote work.",
        schema: { type: "string", format: "uuid" } }, "X-CyberGold-Backend-Revision": {
        description: "Optional observed Backend build commit from this responding process; absent for unversioned local builds.",
        schema: { type: "string", pattern: "^[0-9a-f]{40}$" } } };
    }
  }
}
const document = { openapi: "3.1.0", info: { title: "CyberGold backend compatibility API", version: "1.0.0" },
  security: [{ BackendBearer: [] }],
  paths, components: { schemas, securitySchemes: {
    BackendBearer: { type: "http", scheme: "bearer", description: "Environment-specific remote API entry credential, enforced by Ops Nginx. The API process itself remains private." },
    WorkerBearer: { type: "http", scheme: "bearer" },
  } } };
const specification = JSON.stringify(document, null, 2) + "\n";
const generated = astToString(await openapiTS(JSON.parse(specification)));
for (const [path, text] of [["contracts/openapi.json", specification], ["contracts/http.d.ts", generated]]) {
  if (process.argv.includes("--check")) {
    if (readFileSync(path, "utf8") !== text) throw new Error(`${path} is not current; run npm run generate:contracts`);
  } else writeFileSync(path, text);
}
