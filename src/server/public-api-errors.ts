type PublicApiErrorOptions = {
  context: string;
  error?: unknown;
  status?: number;
};

export function logPublicApiFailure(context: string, error?: unknown) {
  const correlationId = crypto.randomUUID();
  const errorClassification =
    error === undefined
      ? "unspecified"
      : error instanceof Error
        ? "unexpected-error"
        : "unexpected-value";

  console.error("[public-api] request failed", {
    correlationId,
    context,
    errorClassification,
  });

  return correlationId;
}

export function publicApiError(
  message: string,
  { context, error, status = 500 }: PublicApiErrorOptions
) {
  const correlationId = logPublicApiFailure(context, error);
  const responseStatus =
    Number.isInteger(status) && status >= 400 && status <= 599 ? status : 500;

  return Response.json(
    {
      error: message,
      correlationId,
    },
    {
      status: responseStatus,
      headers: { "Cache-Control": "no-store" },
    }
  );
}
