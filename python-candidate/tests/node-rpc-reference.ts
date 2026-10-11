import { readFile } from "node:fs/promises";
import { validateRpcPayload, isValidRpcResponsePayload } from "../../src/server/rpcProxyPolicy";
const fixtures = JSON.parse(await readFile(new URL("../fixtures/rpc-policy.json", import.meta.url), "utf8"));
process.stdout.write(JSON.stringify(fixtures.map((fixture: any) => ({ name: fixture.name,
  result: fixture.kind === "request" ? validateRpcPayload(fixture.value) : isValidRpcResponsePayload(fixture.value),
}))) + "\n");
