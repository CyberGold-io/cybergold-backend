
import { getAddress, recoverMessageAddress, type Address, type Hex } from "viem";

import { ensureSchema, query } from "@/server/onchain-indexer/db";
import {
  buildGovernanceOwnerAliasAuthMessage,
  GOVERNANCE_OWNER_ALIAS_AUTH_CLOCK_SKEW_MS,
  GOVERNANCE_OWNER_ALIAS_AUTH_MAX_AGE_MS,
  type GovernanceOwnerAliasAuthAction,
} from "@/utils/governanceOwnerAliasesAuth";

export class GovernanceOwnerAliasAuthError extends Error {}

type VerifyOwnerAliasWriteAuthParams = {
  action: GovernanceOwnerAliasAuthAction;
  editorAddress: Address;
  ownerAddress: Address;
  alias: string;
  nonce: string;
  issuedAt: string;
  signature: Hex;
};

function normalizeAddress(value: Address) {
  return value.toLowerCase() as Address;
}

export async function verifyAndConsumeOwnerAliasWriteAuth(
  params: VerifyOwnerAliasWriteAuthParams
) {
  const issuedAtMs = new Date(params.issuedAt).getTime();
  if (!Number.isFinite(issuedAtMs)) {
    throw new GovernanceOwnerAliasAuthError("Invalid alias authorization timestamp.");
  }

  const nowMs = Date.now();
  if (issuedAtMs > nowMs + GOVERNANCE_OWNER_ALIAS_AUTH_CLOCK_SKEW_MS) {
    throw new GovernanceOwnerAliasAuthError("Alias authorization timestamp is in the future.");
  }
  if (nowMs - issuedAtMs > GOVERNANCE_OWNER_ALIAS_AUTH_MAX_AGE_MS) {
    throw new GovernanceOwnerAliasAuthError("Alias authorization expired. Please sign again.");
  }

  const message = buildGovernanceOwnerAliasAuthMessage({
    action: params.action,
    editorAddress: params.editorAddress,
    ownerAddress: params.ownerAddress,
    alias: params.alias,
    nonce: params.nonce,
    issuedAt: params.issuedAt,
  });

  let recovered: Address;
  try {
    recovered = getAddress(
      await recoverMessageAddress({
        message,
        signature: params.signature,
      })
    );
  } catch {
    throw new GovernanceOwnerAliasAuthError("Invalid alias authorization signature.");
  }

  if (recovered.toLowerCase() !== params.editorAddress.toLowerCase()) {
    throw new GovernanceOwnerAliasAuthError(
      "Alias authorization signer does not match editor address."
    );
  }

  await ensureSchema();
  const result = await query<{ inserted: number }>(
    `
      INSERT INTO governance_owner_alias_auth_nonces (editor_address, nonce, used_at)
      VALUES ($1, $2, NOW())
      ON CONFLICT DO NOTHING
      RETURNING 1 AS inserted;
    `,
    [normalizeAddress(params.editorAddress), params.nonce]
  );

  if (result.rows.length === 0) {
    throw new GovernanceOwnerAliasAuthError("Alias authorization nonce has already been used.");
  }
}
