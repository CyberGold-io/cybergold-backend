import type { Address } from "viem";

export type GovernanceOwnerAliasAuthAction = "upsert" | "delete";

export type GovernanceOwnerAliasAuthPayload = {
  action: GovernanceOwnerAliasAuthAction;
  editorAddress: Address;
  ownerAddress: Address;
  alias: string;
  nonce: string;
  issuedAt: string;
};

export const GOVERNANCE_OWNER_ALIAS_AUTH_MAX_AGE_MS = 5 * 60 * 1000;
export const GOVERNANCE_OWNER_ALIAS_AUTH_CLOCK_SKEW_MS = 30 * 1000;

export function buildGovernanceOwnerAliasAuthMessage(
  payload: GovernanceOwnerAliasAuthPayload
) {
  return (
    "CyberGold governance owner alias authorization\n" +
    JSON.stringify({
      action: payload.action,
      editorAddress: payload.editorAddress.toLowerCase(),
      ownerAddress: payload.ownerAddress.toLowerCase(),
      alias: payload.alias.trim(),
      nonce: payload.nonce,
      issuedAt: payload.issuedAt,
    })
  );
}
