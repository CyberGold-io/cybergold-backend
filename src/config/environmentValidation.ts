import { getAddress, type Address } from "viem";

export type EnvironmentKind = "text" | "address" | "addresses" | "url" | "database" | "integer" | "positiveInteger" | "flag";

// Errors name the setting, never its value (which may contain credentials).
export function validateEnvironmentValue(
  name: string,
  raw: string | undefined,
  kind: EnvironmentKind = "text",
  required = false,
): string | undefined {
  const value = raw?.trim();
  if (!value) {
    if (required) throw new Error(`${name} is required.`);
    return undefined;
  }
  const invalid = () => new Error(`${name} is not a valid ${kind} setting.`);
  if (kind === "address" || kind === "addresses") {
    try {
      return (kind === "addresses" ? value.split(",") : [value])
        .map((address) => getAddress(address.trim())).join(",");
    } catch {
      throw invalid();
    }
  }
  if (kind === "url" || kind === "database") {
    try {
      const url = new URL(value);
      const protocols = kind === "database" ? ["postgres:", "postgresql:"] : ["http:", "https:"];
      if (!protocols.includes(url.protocol)) throw invalid();
    } catch {
      throw invalid();
    }
  }
  if ((kind === "integer" || kind === "positiveInteger") &&
    (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value)) ||
      (kind === "positiveInteger" && Number(value) === 0))) {
    throw invalid();
  }
  if (kind === "flag" && value !== "0" && value !== "1") throw invalid();
  return value;
}

// Validate once per configured value. Lazy reads keep optional services independent
// and allow tests to supply their own environment before using a setting.
export function environmentSetting<T extends string = string>(
  name: string,
  read: () => string | undefined,
  kind: EnvironmentKind = "text",
  required = false,
) {
  let initialized = false;
  let previous: string | undefined;
  let validated: T | undefined;
  return () => {
    const raw = read();
    if (!initialized || raw !== previous) {
      validated = validateEnvironmentValue(name, raw, kind, required) as T | undefined;
      previous = raw;
      initialized = true;
    }
    return validated;
  };
}

export function requiredEnvironmentSetting<T extends string = string>(
  name: string, read: () => string | undefined, kind: EnvironmentKind = "text",
) {
  const setting = environmentSetting<T>(name, read, kind, true);
  return () => setting() as T;
}

export type EnvironmentAddress = Address;

export function environmentConfig<T extends Record<string, () => unknown>>(settings: T) {
  return Object.freeze(Object.defineProperties({}, Object.fromEntries(
    Object.entries(settings).map(([name, get]) => [name, { get, enumerable: true }]),
  ))) as { readonly [K in keyof T]: ReturnType<T[K]> };
}
