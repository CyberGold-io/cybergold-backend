import Fastify, { LogController, type FastifyServerOptions } from "fastify";
import { Readable } from "node:stream";
import { metricsRegistry, httpRequests, httpDuration, observeMetrics } from "./server/metrics";
import { CLIENT_DIAGNOSTICS_PATH, registerClientDiagnostics } from "./server/clientDiagnostics";

export type BackendRole = "api" | "worker";
type WebHandler = (request: Request) => Response | Promise<Response>;
type RouteModule = Partial<Record<"GET" | "POST", WebHandler>>;

export const routeDefinitions = [
  { path: "/api/activity/core", role: "api", load: () => import("./api/activity/core/route") },
  { path: "/api/activity/safe", role: "api", load: () => import("./api/activity/safe/route") },
  { path: "/api/dashboard/onchain-summary", role: "api", load: () => import("./api/dashboard/onchain-summary/route") },
  { path: "/api/recovery/shares", role: "api", load: () => import("./api/recovery/shares/route") },
  { path: "/api/gold", role: "api", load: () => import("./api/gold/route") },
  { path: "/api/fx", role: "api", load: () => import("./api/fx/route") },
  { path: "/api/rpc", role: "api", load: () => import("./api/rpc/route") },
  { path: "/api/governance/owner-aliases", role: "api", load: () => import("./api/governance/owner-aliases/route") },
  { path: "/api/quote-pool-cache", role: "api", load: () => import("./api/quote-pool-cache/route") },
  { path: "/api/safe", role: "api", load: () => import("./api/safe/route") },
  { path: "/api/safe/events", role: "api", load: () => import("./api/safe/events/route") },
  { path: "/api/faucet", role: "api", load: () => import("./api/faucet/route") },
  { path: "/api/internal/onchain-indexer/reconcile", role: "worker", load: () => import("./api/internal/onchain-indexer/reconcile/route") },
  { path: "/api/internal/onchain-indexer/fork-generation", role: "worker", load: () => import("./api/internal/onchain-indexer/fork-generation/route") },
] as const;

export async function createBackendServer(role: BackendRole, options: FastifyServerOptions = {}) {
  const app = Fastify({ logger: true, logController: new LogController({ disableRequestLogging: true }), ...options });
  // Handlers retain their exact raw-body limits, JSON parsing and error envelopes.
  // Fastify's generic JSON parser/coercion/body limit must not redefine them.
  app.removeAllContentTypeParsers();
  app.addContentTypeParser("*", (_request, stream, done) => done(null, stream));
  app.setErrorHandler((_error, request, reply) => {
    // Like a production Next route's uncaught failure, return no internal text.
    // Handled domain errors already carry their established public envelope.
    app.log.error({ operation: request.routeOptions.url, requestId: request.id,
      component: role }, "unhandled route failure");
    reply.code(500).send();
  });

  app.get("/metrics", async (_request, reply) => {
    reply.header("Cache-Control", "no-store").type(metricsRegistry.contentType);
    return metricsRegistry.metrics();
  });
  if (role === "api") await registerClientDiagnostics(app);

  for (const route of routeDefinitions) {
    if (route.role !== role) continue;
    const module: RouteModule = await route.load();
    for (const method of ["GET", "POST"] as const) {
      const handler = module[method];
      if (!handler) continue;
      app.route({
        method,
        url: route.path,
        async handler(request, reply) {
          const abort = new AbortController();
          const onAborted = () => abort.abort();
          const onClosed = () => { if (!reply.raw.writableEnded) abort.abort(); };
          request.raw.once("aborted", onAborted);
          reply.raw.once("close", onClosed);
          const headers = new Headers();
          for (const [name, value] of Object.entries(request.headers)) {
            if (value !== undefined) headers.set(name, Array.isArray(value) ? value.join(", ") : value);
          }
          const init: RequestInit & { duplex?: "half" } = {
            method, headers, signal: abort.signal,
          };
          if (method === "POST" && request.body instanceof Readable) {
            init.body = Readable.toWeb(request.body) as ReadableStream<Uint8Array>;
            init.duplex = "half";
          }
          try {
            const response = await handler(new Request(`http://backend.internal${request.raw.url}`, init));
            reply.code(response.status);
            response.headers.forEach((value, name) => reply.header(name, value));
            // Every compatibility route returns a bounded JSON/text response, not SSE.
            return reply.send(Buffer.from(await response.arrayBuffer()));
          } finally {
            request.raw.removeListener("aborted", onAborted);
            reply.raw.removeListener("close", onClosed);
          }
        },
      });
    }
  }
  app.addHook("onResponse", async (request, reply) => {
    if (request.routeOptions.url === "/metrics") return;
    const operation = request.routeOptions.url === CLIENT_DIAGNOSTICS_PATH ? CLIENT_DIAGNOSTICS_PATH
      : routeDefinitions.find(route => route.path === request.routeOptions.url)?.path ?? "unmatched";
    const method = ["GET", "HEAD", "POST", "OPTIONS"].includes(request.method) ? request.method : "other";
    observeMetrics(() => {
      httpRequests.inc({ operation, method, status: String(reply.statusCode) });
      httpDuration.observe({ operation, method }, reply.elapsedTime / 1000);
    });
    app.log.info({ operation: request.routeOptions.url, method: request.method,
      statusCode: reply.statusCode, durationMs: reply.elapsedTime, requestId: request.id,
      component: role, release: process.env.CYBERGOLD_BACKEND_COMMIT }, "request completed");
  });
  app.addHook("onClose", async () => {
    const pool = globalThis.__cybergoldDashboardPgPool;
    if (pool) {
      globalThis.__cybergoldDashboardPgPool = undefined;
      await pool.end();
    }
  });
  return app;
}
