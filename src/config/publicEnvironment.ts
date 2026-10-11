import { environmentConfig, environmentSetting, requiredEnvironmentSetting, type EnvironmentAddress } from "./environmentValidation.ts";

// Existing profile names are retained at extraction; these values are server configuration here.
export const publicEnv = environmentConfig({
  NEXT_PUBLIC_APP_ORIGIN: environmentSetting("NEXT_PUBLIC_APP_ORIGIN", () => process.env.NEXT_PUBLIC_APP_ORIGIN, "url"),
  NEXT_PUBLIC_CHAIN_ID: requiredEnvironmentSetting("NEXT_PUBLIC_CHAIN_ID", () => process.env.NEXT_PUBLIC_CHAIN_ID, "positiveInteger"),
  NEXT_PUBLIC_CORE_DIAMOND_ADDRESS: requiredEnvironmentSetting<EnvironmentAddress>("NEXT_PUBLIC_CORE_DIAMOND_ADDRESS", () => process.env.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS, "address"),
  NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS: environmentSetting<EnvironmentAddress>("NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS", () => process.env.NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS, "address"),
  NEXT_PUBLIC_GOVERNANCE_SAFE_ADDRESS: environmentSetting<EnvironmentAddress>("NEXT_PUBLIC_GOVERNANCE_SAFE_ADDRESS", () => process.env.NEXT_PUBLIC_GOVERNANCE_SAFE_ADDRESS, "address"),
  NEXT_PUBLIC_RPC_URL: requiredEnvironmentSetting("NEXT_PUBLIC_RPC_URL", () => process.env.NEXT_PUBLIC_RPC_URL, "url"),
});

export function validatePublicEnvironment() {
  Object.values(publicEnv);
}
