import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const descriptor = JSON.parse(readFileSync(resolve(root, "src/server/onchain-indexer/snapshot-identity.json")));
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
// Match Ops' canonical source-binding JSON: sorted keys and a final newline.
const bindings = [...descriptor.compatibilitySources].sort().map((path) => {
  const bytes = readFileSync(resolve(root, path));
  return { path, sha256: sha256(bytes), size: bytes.length };
});
process.stdout.write(`${sha256(`${JSON.stringify(bindings)}\n`)}\n`);
