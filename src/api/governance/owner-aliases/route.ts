import type { Address } from "viem";

import {
  deleteOwnerAlias,
  listOwnerAliases,
  upsertOwnerAlias,
} from "@/server/governance-owner-aliases/repository";
import {
  GovernanceOwnerAliasAuthError,
  verifyAndConsumeOwnerAliasWriteAuth,
} from "@/server/governance-owner-aliases/auth";
import { publicApiError } from "@/server/public-api-errors";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type OwnerAliasesAction = "list" | "upsert" | "delete";

type OwnerAliasesRequestBody = {
  action?: OwnerAliasesAction;
  editorAddress?: unknown;
  ownerAddress?: unknown;
  ownerAddresses?: unknown;
  alias?: unknown;
  auth?: unknown;
};

const MAX_ALIAS_LENGTH = 64;

function jsonError(message: string, status = 400) {
  return Response.json({ error: message }, { status, headers: { "Cache-Control": "no-store" } });
}

function isAddress(value: unknown): value is Address {
  return typeof value === "string" && /^0x[a-fA-F0-9]{40}$/.test(value);
}

function parseEditorAddress(value: unknown) {
  if (!isAddress(value)) {
    return undefined;
  }
  return value;
}

function parseOwnerAddress(value: unknown) {
  if (!isAddress(value)) {
    return undefined;
  }
  return value;
}

function parseOwnerAddresses(value: unknown) {
  if (!Array.isArray(value)) {
    return undefined;
  }

  const rows = value.flatMap((entry) => (isAddress(entry) ? [entry] : []));
  return rows.length === value.length ? rows : undefined;
}

function parseAlias(value: unknown) {
  if (typeof value !== "string") {
    return undefined;
  }

  const trimmed = value.trim();
  if (trimmed.length === 0 || trimmed.length > MAX_ALIAS_LENGTH) {
    return undefined;
  }

  return trimmed;
}

type ParsedWriteAuth = {
  nonce: string;
  issuedAt: string;
  signature: `0x${string}`;
};

function parseWriteAuth(value: unknown): ParsedWriteAuth | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }

  const row = value as Record<string, unknown>;
  const nonce = typeof row.nonce === "string" ? row.nonce.trim() : "";
  const issuedAt = typeof row.issuedAt === "string" ? row.issuedAt.trim() : "";
  const signature = typeof row.signature === "string" ? row.signature.trim() : "";

  if (!nonce || nonce.length > 128) {
    return undefined;
  }
  if (!issuedAt || issuedAt.length > 64) {
    return undefined;
  }
  if (!/^0x(?:[a-fA-F0-9]{128}|[a-fA-F0-9]{130})$/.test(signature)) {
    return undefined;
  }

  return {
    nonce,
    issuedAt,
    signature: signature as `0x${string}`,
  };
}

export async function POST(request: Request) {
  let body: OwnerAliasesRequestBody;
  try {
    body = (await request.json()) as OwnerAliasesRequestBody;
  } catch {
    return jsonError("Invalid JSON payload.");
  }

  const action = body.action;
  if (!action) {
    return jsonError("Missing action.");
  }

  try {
    if (action === "list") {
      const editorAddress = parseEditorAddress(body.editorAddress);
      const ownerAddresses = parseOwnerAddresses(body.ownerAddresses);
      if (!editorAddress || !ownerAddresses) {
        return jsonError("Invalid owner alias list payload.");
      }

      const entries = await listOwnerAliases({ editorAddress, ownerAddresses });
      return Response.json({ entries }, { headers: { "Cache-Control": "no-store" } });
    }

    if (action === "upsert") {
      const editorAddress = parseEditorAddress(body.editorAddress);
      const ownerAddress = parseOwnerAddress(body.ownerAddress);
      const alias = parseAlias(body.alias);
      const auth = parseWriteAuth(body.auth);
      if (!editorAddress || !ownerAddress || !alias || !auth) {
        return jsonError(
          `Invalid owner alias upsert payload (alias length must be 1-${MAX_ALIAS_LENGTH}).`
        );
      }

      await verifyAndConsumeOwnerAliasWriteAuth({
        action: "upsert",
        editorAddress,
        ownerAddress,
        alias,
        nonce: auth.nonce,
        issuedAt: auth.issuedAt,
        signature: auth.signature,
      });

      const entry = await upsertOwnerAlias({ editorAddress, ownerAddress, alias });
      return Response.json({ entry }, { headers: { "Cache-Control": "no-store" } });
    }

    if (action === "delete") {
      const editorAddress = parseEditorAddress(body.editorAddress);
      const ownerAddress = parseOwnerAddress(body.ownerAddress);
      const auth = parseWriteAuth(body.auth);
      if (!editorAddress || !ownerAddress || !auth) {
        return jsonError("Invalid owner alias delete payload.");
      }

      await verifyAndConsumeOwnerAliasWriteAuth({
        action: "delete",
        editorAddress,
        ownerAddress,
        alias: "",
        nonce: auth.nonce,
        issuedAt: auth.issuedAt,
        signature: auth.signature,
      });

      const deleted = await deleteOwnerAlias({ editorAddress, ownerAddress });
      return Response.json({ ok: true, deleted }, { headers: { "Cache-Control": "no-store" } });
    }

    return jsonError("Unsupported action.");
  } catch (error) {
    if (error instanceof GovernanceOwnerAliasAuthError) {
      return jsonError(error.message, 401);
    }

    return publicApiError(
      "Failed to process governance owner aliases request.",
      {
        context: "governance-owner-aliases",
        error,
      }
    );
  }
}
