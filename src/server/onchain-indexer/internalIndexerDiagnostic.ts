const MAXIMUM_DIAGNOSTIC_LENGTH = 240;

function isSafeDiagnosticMessage(value: string) {
    return (
        value.length > 0 &&
        value.length <= MAXIMUM_DIAGNOSTIC_LENGTH &&
        !/[\r\n]/.test(value) &&
        !/[a-z][a-z0-9+.-]*:\/\//i.test(value) &&
        !/\b(?:bearer|authorization|password|passwd|secret|credential|api[ _-]?key|database[ _-]?url|rpc[ _-]?url)\b/i.test(
            value
        ) &&
        !/\b[A-Za-z0-9_-]{25,}\b/.test(value)
    );
}

/**
 * Return a bounded reason only when the exception's message is safe to expose
 * through the bearer-authenticated loopback diagnostic endpoint. In all other
 * cases, preserve the existing opaque failure boundary.
 */
export function internalIndexerDiagnostic(error: unknown) {
    if (!(error instanceof Error)) return "unexpected-worker-error";

    const message = error.message.trim();
    if (isSafeDiagnosticMessage(message)) return message;

    // viem deliberately separates a concise operational reason from its
    // full message, which may include the configured transport URL. Prefer
    // that reason only after applying the same redaction boundary.
    const shortMessage = (error as Error & { shortMessage?: unknown })
        .shortMessage;
    if (
        typeof shortMessage === "string" &&
        isSafeDiagnosticMessage(shortMessage.trim())
    ) {
        return shortMessage.trim();
    }

    return "unexpected-worker-error";
}
