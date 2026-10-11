const MAX_FX_PRESENTATION_RATE = 1_000_000;
const MAX_GOLD_PRESENTATION_PRICE_USD = 1_000_000_000;
const GOLD_PROVIDER_URL =
  "https://data-api.binance.vision/api/v3/ticker/price?symbol=PAXGUSDT";
const FX_PROVIDER_URL =
  "https://api.frankfurter.app/latest?from=USD&to=EUR,CHF,RUB";
const FALLBACK_GOLD_PRICE = 3320;
const FALLBACK_FX_RATES: FxMarketDataPayload["rates"] = {
  USD: 1,
  EUR: 0.92,
  CHF: 0.89,
  RUB: 91.5,
};

type JsonRecord = Record<string, unknown>;
type MarketDataResolution<T> = {
  payload: T;
  isFresh: boolean;
};
type ResolverOptions = {
  fetchImpl?: typeof fetch;
  now?: () => Date;
};

export type GoldMarketDataPayload = {
  price: number;
  fetchedAt: string;
  stale: boolean;
};

export type FxMarketDataPayload = {
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

function asRecord(value: unknown): JsonRecord | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : undefined;
}

function hasExactKeys(
  value: JsonRecord,
  expectedKeys: readonly string[]
): boolean {
  const actualKeys = Object.keys(value).sort();
  const expected = [...expectedKeys].sort();
  return (
    actualKeys.length === expected.length &&
    actualKeys.every((key, index) => key === expected[index])
  );
}

function boundedPositiveNumber(value: unknown, maximum: number) {
  return typeof value === "number" &&
    Number.isFinite(value) &&
    value > 0 &&
    value <= maximum
    ? value
    : undefined;
}

function isIsoTimestamp(value: unknown): value is string {
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value)
  ) {
    return false;
  }
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString() === value;
}

export function parseFxProviderRates(payload: unknown) {
  const record = asRecord(payload);
  if (
    !record ||
    !hasExactKeys(record, ["amount", "base", "date", "rates"]) ||
    record.amount !== 1 ||
    record.base !== "USD" ||
    typeof record.date !== "string" ||
    !/^\d{4}-\d{2}-\d{2}$/.test(record.date)
  ) {
    return undefined;
  }

  const rates = asRecord(record.rates);
  if (!rates || !hasExactKeys(rates, ["EUR", "CHF", "RUB"])) {
    return undefined;
  }

  const EUR = boundedPositiveNumber(rates.EUR, MAX_FX_PRESENTATION_RATE);
  const CHF = boundedPositiveNumber(rates.CHF, MAX_FX_PRESENTATION_RATE);
  const RUB = boundedPositiveNumber(rates.RUB, MAX_FX_PRESENTATION_RATE);

  return EUR !== undefined && CHF !== undefined && RUB !== undefined
    ? { EUR, CHF, RUB }
    : undefined;
}

export function parseGoldProviderPrice(payload: unknown) {
  const record = asRecord(payload);
  if (
    !record ||
    !hasExactKeys(record, ["symbol", "price"]) ||
    record.symbol !== "PAXGUSDT"
  ) {
    return undefined;
  }

  const rawPrice = record.price;
  const price =
    typeof rawPrice === "number"
      ? rawPrice
      : typeof rawPrice === "string" &&
          /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(rawPrice)
        ? Number(rawPrice)
        : undefined;

  return boundedPositiveNumber(price, MAX_GOLD_PRESENTATION_PRICE_USD);
}

export function parseGoldMarketDataPayload(
  payload: unknown
): GoldMarketDataPayload | undefined {
  const record = asRecord(payload);
  if (!record || !hasExactKeys(record, ["price", "fetchedAt", "stale"])) {
    return undefined;
  }

  const price = boundedPositiveNumber(
    record.price,
    MAX_GOLD_PRESENTATION_PRICE_USD
  );
  return price !== undefined &&
    isIsoTimestamp(record.fetchedAt) &&
    typeof record.stale === "boolean"
    ? {
        price,
        fetchedAt: record.fetchedAt,
        stale: record.stale,
      }
    : undefined;
}

export function parseFxMarketDataPayload(
  payload: unknown
): FxMarketDataPayload | undefined {
  const record = asRecord(payload);
  const rates = asRecord(record?.rates);
  if (
    !record ||
    !hasExactKeys(record, ["base", "rates", "fetchedAt", "stale"]) ||
    record.base !== "USD" ||
    !rates ||
    !hasExactKeys(rates, ["USD", "EUR", "CHF", "RUB"]) ||
    rates.USD !== 1 ||
    !isIsoTimestamp(record.fetchedAt) ||
    typeof record.stale !== "boolean"
  ) {
    return undefined;
  }

  const EUR = boundedPositiveNumber(rates.EUR, MAX_FX_PRESENTATION_RATE);
  const CHF = boundedPositiveNumber(rates.CHF, MAX_FX_PRESENTATION_RATE);
  const RUB = boundedPositiveNumber(rates.RUB, MAX_FX_PRESENTATION_RATE);
  return EUR !== undefined && CHF !== undefined && RUB !== undefined
    ? {
        base: "USD",
        rates: { USD: 1, EUR, CHF, RUB },
        fetchedAt: record.fetchedAt,
        stale: record.stale,
      }
    : undefined;
}

export async function resolveGoldMarketData(
  lastKnownPayload: GoldMarketDataPayload | null,
  options: ResolverOptions = {}
): Promise<MarketDataResolution<GoldMarketDataPayload>> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const now = options.now ?? (() => new Date());

  try {
    const response = await fetchImpl(GOLD_PROVIDER_URL, {
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) {
      throw new Error("Gold price provider request failed");
    }

    const price = parseGoldProviderPrice(await response.json());
    if (price === undefined) {
      throw new Error("Gold price provider returned an invalid payload");
    }

    return {
      payload: {
        price,
        fetchedAt: now().toISOString(),
        stale: false,
      },
      isFresh: true,
    };
  } catch {
    return {
      payload: lastKnownPayload
        ? { ...lastKnownPayload, stale: lastKnownPayload.stale ||
            now().getTime() - Date.parse(lastKnownPayload.fetchedAt) >= 3_600_000 }
        : {
            price: FALLBACK_GOLD_PRICE,
            fetchedAt: now().toISOString(),
            stale: true,
          },
      isFresh: false,
    };
  }
}

export async function resolveFxMarketData(
  lastKnownPayload: FxMarketDataPayload | null,
  options: ResolverOptions = {}
): Promise<MarketDataResolution<FxMarketDataPayload>> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const now = options.now ?? (() => new Date());

  try {
    const response = await fetchImpl(FX_PROVIDER_URL, {
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) {
      throw new Error("FX provider request failed");
    }

    const rates = parseFxProviderRates(await response.json());
    if (!rates) {
      throw new Error("FX provider returned an invalid payload");
    }

    return {
      payload: {
        base: "USD",
        rates: {
          USD: 1,
          ...rates,
        },
        fetchedAt: now().toISOString(),
        stale: false,
      },
      isFresh: true,
    };
  } catch {
    return {
      payload: lastKnownPayload
        ? { ...lastKnownPayload, stale: true }
        : {
            base: "USD",
            rates: FALLBACK_FX_RATES,
            fetchedAt: now().toISOString(),
            stale: true,
          },
      isFresh: false,
    };
  }
}
