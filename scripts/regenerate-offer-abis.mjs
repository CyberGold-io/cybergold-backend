#!/usr/bin/env node
// SPDX-License-Identifier: AGPL-3.0-only
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const specs = JSON.parse(fs.readFileSync(path.join(root, "abi-inputs/specs.json"), "utf8"));
for (const spec of specs) {
  const artifact = JSON.parse(fs.readFileSync(path.join(root, "abi-inputs", spec.input), "utf8"));
  const banner = spec.banner;
  const generated = `${banner}export const ${spec.prefix}_ABI = ${JSON.stringify(artifact.abi, null, 2)} as const;\n\n`
    + `export const ${spec.prefix}_FUNCTIONS = ${JSON.stringify(artifact.selectors, null, 2)} as const;\n\n`
    + `export const ${spec.prefix}_INTERFACE_ID = ${JSON.stringify(artifact.interface.interfaceId)} as const;\n\n`
    + `export const ${spec.prefix}_ERC165_ADVERTISED = ${JSON.stringify(artifact.interface.erc165Advertised)} as const;\n`;
  const output = path.join(root, spec.output);
  if (process.argv.includes("--check")) {
    if (fs.readFileSync(output, "utf8") !== generated) throw new Error(`Generated ABI module drift: ${spec.output}`);
  } else { fs.writeFileSync(output, generated); }
}
