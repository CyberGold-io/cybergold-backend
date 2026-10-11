
import type { QueryResultRow } from "pg";
import type { Address } from "viem";

import { ensureSchema, query } from "@/server/onchain-indexer/db";

type GovernanceOwnerAliasRow = QueryResultRow & {
  editorAddress: string;
  ownerAddress: string;
  alias: string;
  updatedAt: Date | string;
};

export type GovernanceOwnerAliasEntry = {
  editorAddress: Address;
  ownerAddress: Address;
  alias: string;
  updatedAt: string;
};

type ListOwnerAliasesParams = {
  editorAddress: Address;
  ownerAddresses: readonly Address[];
};

type UpsertOwnerAliasParams = {
  editorAddress: Address;
  ownerAddress: Address;
  alias: string;
};

type DeleteOwnerAliasParams = {
  editorAddress: Address;
  ownerAddress: Address;
};

function normalizeAddress(value: Address) {
  return value.toLowerCase() as Address;
}

function normalizeRow(row: GovernanceOwnerAliasRow): GovernanceOwnerAliasEntry {
  return {
    editorAddress: normalizeAddress(row.editorAddress as Address),
    ownerAddress: normalizeAddress(row.ownerAddress as Address),
    alias: row.alias,
    updatedAt: new Date(row.updatedAt).toISOString(),
  };
}

export async function listOwnerAliases(
  params: ListOwnerAliasesParams
): Promise<GovernanceOwnerAliasEntry[]> {
  await ensureSchema();

  const editorAddress = normalizeAddress(params.editorAddress);
  const ownerAddresses = Array.from(
    new Set(params.ownerAddresses.map((ownerAddress) => normalizeAddress(ownerAddress)))
  );
  if (ownerAddresses.length === 0) {
    return [];
  }

  const result = await query<GovernanceOwnerAliasRow>(
    `
      SELECT
        editor_address AS "editorAddress",
        owner_address AS "ownerAddress",
        alias,
        updated_at AS "updatedAt"
      FROM governance_owner_aliases
      WHERE editor_address = $1
        AND owner_address = ANY($2::text[])
      ORDER BY owner_address ASC;
    `,
    [editorAddress, ownerAddresses]
  );

  return result.rows.map(normalizeRow);
}

export async function upsertOwnerAlias(
  params: UpsertOwnerAliasParams
): Promise<GovernanceOwnerAliasEntry> {
  await ensureSchema();

  const editorAddress = normalizeAddress(params.editorAddress);
  const ownerAddress = normalizeAddress(params.ownerAddress);

  const result = await query<GovernanceOwnerAliasRow>(
    `
      INSERT INTO governance_owner_aliases (
        editor_address,
        owner_address,
        alias,
        updated_at
      )
      VALUES ($1, $2, $3, NOW())
      ON CONFLICT (editor_address, owner_address)
      DO UPDATE SET
        alias = EXCLUDED.alias,
        updated_at = NOW()
      RETURNING
        editor_address AS "editorAddress",
        owner_address AS "ownerAddress",
        alias,
        updated_at AS "updatedAt";
    `,
    [editorAddress, ownerAddress, params.alias]
  );

  const row = result.rows[0];
  if (!row) {
    throw new Error("Failed to save governance owner alias.");
  }

  return normalizeRow(row);
}

export async function deleteOwnerAlias(params: DeleteOwnerAliasParams): Promise<boolean> {
  await ensureSchema();

  const editorAddress = normalizeAddress(params.editorAddress);
  const ownerAddress = normalizeAddress(params.ownerAddress);

  const result = await query<{ deleted: number }>(
    `
      DELETE FROM governance_owner_aliases
      WHERE editor_address = $1
        AND owner_address = $2
      RETURNING 1 AS deleted;
    `,
    [editorAddress, ownerAddress]
  );

  return result.rows.length > 0;
}
