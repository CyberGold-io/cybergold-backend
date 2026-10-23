/** Closed browser-telemetry projection, matching the Python API and App consumers. */
const quotePhases = ["context", "initial-search", "initial-preview", "capacity", "basket-preview",
  "expected-input-search", "execution-search", "final-preview", "canonicality", "retained-validation"] as const;
const routePhases = ["context", "eligibility", "v3-coverage", "typed-reserve", "structured-search", "composition", "canonicality"] as const;
const waveNumbers = ["elapsedMs", "subphaseElapsedMs", "legacyCandidates", "legacyCompleted", "typedEnumerated",
  "typedCompleted", "typedPending", "sdkRequests", "sdkWaiting", "sdkLockWaitMs", "sdkExchangeMs"] as const;
const quoteCodes = ["rpc-rate-limit", "rpc-timeout", "rpc-unavailable", "rpc-access-denied", "quote-timeout",
  "quote-no-route", "quote-insufficient-liquidity", "quote-contract-reverted", "quote-unavailable", "insufficient-protocol-supply",
  "issuance-cap-exceeded", "redemption-supply-exceeded", "redemption-capacity-exceeded",
  "insufficient-reserve-balance", "insufficient-recovery-shares"] as const;
const providerStages = ["composition", "basket-preview", "initial-preview", "execution-search", "expected-input-search",
  "final-preview", "tolerance", "canonicality", "selection", "route-pricing", "fee-bounds", "qualification", "retained-validation"] as const;
const providerOutcomes = ["running", "qualified", "rejected", "not-improved", "cancelled", "superseded"] as const;
const legCounters = ["index", "started", "succeeded", "failed", "cancelled", "pending", "omittedFailureCodes", "omittedPools"] as const;
const providerCounters = ["attempts", "qualified", "rejected", "notImproved", "cancelled", "superseded", "pending", "omittedRows"] as const;
const providerAmounts = ["targetAmount", "minimumAmountOut", "maximumAmountOut", "observedAmountOut", "maximumAmountIn", "observedAmountIn",
  "executionAmount", "quotedInput", "quotedOutput", "inputMaximum", "outputMinimum"] as const;
const providerTimes = ["firstQualifiedMs", "selectionMs", "canonicalCompletedMs", "cleanupCompletedMs"] as const;
const attemptTimes = ["startedMs", "completedMs", "elapsedMs"] as const;
const selectionReasons = ["best-initial", "first-extension", "complete", "timeout"] as const;
type QuoteCode = typeof quoteCodes[number];
type PoolIdentity = { protocol: "v2" | "v3" | "v4"; poolId?: string; poolAddress?: string };
type RouteLeg = Partial<Record<typeof legCounters[number], number>> & {
  index: number; inputAsset?: string; outputAsset?: string; amount?: string; bestAvailable?: boolean;
  failureCounts: { code: QuoteCode; count: number }[];
  bestPools: PoolIdentity[];
};
type ProviderQualification = { attempt: number; stage: typeof providerStages[number]; outcome: typeof providerOutcomes[number]; code?: QuoteCode }
  & Partial<Record<typeof providerAmounts[number], string>> & Partial<Record<typeof attemptTimes[number], number>>
  & { pools?: PoolIdentity[]; omittedPools?: number };
export type ProjectedQuoteDiagnostics = { phase?: typeof quotePhases[number]; qualified?: boolean; elapsedMs?: number; inversionIteration?: number;
  routeWave?: { mode?: "exact-in" | "exact-out"; subphase?: typeof routePhases[number];
    legs?: { count: number; omittedRows?: number; rows: RouteLeg[] } } & Partial<Record<typeof waveNumbers[number], number>>;
  providerQualifications?: { provider: "core" | "market"; attempts: number; rows: ProviderQualification[];
    selectedAttempt?: number; selectionReason?: typeof selectionReasons[number] }
    & Partial<Record<typeof providerCounters[number] | typeof providerTimes[number], number>> };

const record = (value: unknown): Record<string, unknown> | undefined =>
  value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
const boundedInteger = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 1e12;
const boundedNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1e12;
const address = (value: unknown) => typeof value === "string" && /^0x[0-9a-fA-F]{40}$/.exec(value)?.[0] === value ? value.toLowerCase() : undefined;
const uint256 = (value: unknown): value is string => typeof value === "string" && /^(0|[1-9][0-9]{0,77})$/.exec(value)?.[0] === value && BigInt(value) < 2n ** 256n;
function poolIdentity(value: unknown) {
  if (typeof value !== "string") return;
  if (/^0x(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$/.exec(value)?.[0] === value) return value.toLowerCase();
  const matched = /^v3:(0x[0-9a-fA-F]{40}):(0x[0-9a-fA-F]{40}):([0-9]{1,7})$/.exec(value);
  if (matched?.[0] === value && Number(matched[3]) <= 1e6) return value.toLowerCase();
}
function counters<T extends string>(source: Record<string, unknown>, names: readonly T[]) {
  const result: Partial<Record<T, number>> = {};
  for (const name of names) if (boundedInteger(source[name])) result[name] = source[name];
  return result;
}
function numbers<T extends string>(source: Record<string, unknown>, names: readonly T[]) {
  const result: Partial<Record<T, number>> = {};
  for (const name of names) if (boundedNumber(source[name])) result[name] = source[name];
  return result;
}
function pools(value: unknown): PoolIdentity[] {
  const result: PoolIdentity[] = [];
  for (const raw of Array.isArray(value) ? value.slice(0, 8) : []) {
    const pool = record(raw);
    if (!pool || (pool.protocol !== "v2" && pool.protocol !== "v3" && pool.protocol !== "v4")) continue;
    const poolId = poolIdentity(pool.poolId), poolAddress = address(pool.poolAddress);
    if (poolId || poolAddress) result.push({ protocol: pool.protocol, ...(poolId ? { poolId } : {}), ...(poolAddress ? { poolAddress } : {}) });
  }
  return result;
}
function routeLegs(value: unknown): NonNullable<NonNullable<ProjectedQuoteDiagnostics["routeWave"]>["legs"]> | undefined {
  const source = record(value);
  if (!source || !boundedInteger(source.count)) return;
  const rows: RouteLeg[] = [];
  for (const raw of Array.isArray(source.rows) ? source.rows.slice(0, 16) : []) {
    const input = record(raw);
    if (!input || !boundedInteger(input.index)) continue;
    const row: RouteLeg = { ...counters(input, legCounters), index: input.index, failureCounts: [], bestPools: [] };
    if (typeof input.bestAvailable === "boolean") row.bestAvailable = input.bestAvailable;
    for (const name of ["inputAsset", "outputAsset"] as const) {
      const safe = address(input[name]);
      if (safe) row[name] = safe;
    }
    if (uint256(input.amount)) row.amount = input.amount;
    for (const rawFailure of Array.isArray(input.failureCounts) ? input.failureCounts.slice(0, 16) : []) {
      const failure = record(rawFailure);
      if (failure && (quoteCodes as readonly unknown[]).includes(failure.code) && boundedInteger(failure.count))
        row.failureCounts.push({ code: failure.code as QuoteCode, count: failure.count });
    }
    row.bestPools = pools(input.bestPools);
    rows.push(row);
  }
  return { count: source.count, ...(boundedInteger(source.omittedRows) ? { omittedRows: source.omittedRows } : {}), rows };
}
function providerQualifications(value: unknown): ProjectedQuoteDiagnostics["providerQualifications"] {
  const source = record(value);
  if (!source || (source.provider !== "core" && source.provider !== "market") || !boundedInteger(source.attempts)) return;
  const rows: ProviderQualification[] = [];
  for (const raw of Array.isArray(source.rows) ? source.rows.slice(0, 8) : []) {
    const input = record(raw);
    if (!input || !boundedInteger(input.attempt) || !(providerStages as readonly unknown[]).includes(input.stage)
      || !(providerOutcomes as readonly unknown[]).includes(input.outcome)) continue;
    const row: ProviderQualification = { attempt: input.attempt, stage: input.stage as ProviderQualification["stage"], outcome: input.outcome as ProviderQualification["outcome"] };
    if ((quoteCodes as readonly unknown[]).includes(input.code)) row.code = input.code as QuoteCode;
    for (const name of providerAmounts) if (uint256(input[name])) row[name] = input[name];
    Object.assign(row, numbers(input, attemptTimes));
    if (Array.isArray(input.pools)) row.pools = pools(input.pools);
    if (boundedInteger(input.omittedPools)) row.omittedPools = input.omittedPools;
    rows.push(row);
  }
  return { ...counters(source, providerCounters), ...numbers(source, providerTimes),
    ...(boundedInteger(source.selectedAttempt) ? { selectedAttempt: source.selectedAttempt } : {}),
    ...((selectionReasons as readonly unknown[]).includes(source.selectionReason)
      ? { selectionReason: source.selectionReason as typeof selectionReasons[number] } : {}),
    provider: source.provider, attempts: source.attempts, rows };
}

/** Project optional browser quote-work evidence; it never determines readiness. */
export function projectQuoteDiagnostics(value: unknown): ProjectedQuoteDiagnostics | undefined {
  try {
    if (!value || typeof value !== "object" || Array.isArray(value)) return;
    const source = value as Record<string, unknown>, result: ProjectedQuoteDiagnostics = {};
    if (typeof source.phase === "string" && (quotePhases as readonly string[]).includes(source.phase)) result.phase = source.phase as ProjectedQuoteDiagnostics["phase"];
    if (typeof source.qualified === "boolean") result.qualified = source.qualified;
    Object.assign(result, numbers(source, ["elapsedMs", "inversionIteration"]));
    const qualifications = providerQualifications(source.providerQualifications);
    if (qualifications) result.providerQualifications = qualifications;
    const wave = source.routeWave;
    if (wave && typeof wave === "object" && !Array.isArray(wave)) {
      const input = wave as Record<string, unknown>, projected: NonNullable<ProjectedQuoteDiagnostics["routeWave"]> = {};
      if (input.mode === "exact-in" || input.mode === "exact-out") projected.mode = input.mode;
      if (typeof input.subphase === "string" && (routePhases as readonly string[]).includes(input.subphase)) projected.subphase = input.subphase as typeof routePhases[number];
      Object.assign(projected, numbers(input, waveNumbers));
      const legs = routeLegs(input.legs);
      if (legs) projected.legs = legs;
      if (Object.keys(projected).length) result.routeWave = projected;
    }
    return Object.keys(result).length ? result : undefined;
  } catch { /* Optional diagnostics cannot replace a quote outcome. */ }
}

