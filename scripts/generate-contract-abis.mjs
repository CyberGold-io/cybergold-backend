#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const check = process.argv.includes("--check");
const source = JSON.parse(fs.readFileSync(path.join(root, "contracts/abi-source.json"), "utf8"));

const specs = [
  {
    source: "generated/abi/CoreDiamond.json",
    output: path.resolve(root, "src/contracts/generated/coreDiamond.ts"),
    prefix: "CORE_DIAMOND",
  },
  {
    source: "generated/abi/GovernanceDiamond.json",
    output: path.resolve(root, "src/contracts/generated/governanceDiamond.ts"),
    prefix: "GOVERNANCE_DIAMOND",
  },
];

function render(spec, artifact) {
  if (
    !artifact.interface ||
    typeof artifact.interface.interfaceId !== "string" ||
    typeof artifact.interface.erc165Advertised !== "boolean"
  ) {
    throw new Error(
      `Canonical release ABI lacks explicit interface metadata: ${spec.source}`
    );
  }
  const banner = "// Generated from the compiled release facets. Do not edit by hand.\n";
  return `${banner}export const ${spec.prefix}_ABI = ${JSON.stringify(artifact.abi, null, 2)} as const;\n\n`
    + `export const ${spec.prefix}_FUNCTIONS = ${JSON.stringify(artifact.selectors, null, 2)} as const;\n\n`
    + `export const ${spec.prefix}_INTERFACE_ID = ${JSON.stringify(artifact.interface.interfaceId)} as const;\n\n`
    + `export const ${spec.prefix}_ERC165_ADVERTISED = ${JSON.stringify(artifact.interface.erc165Advertised)} as const;\n`;
}

const generatedModules = specs.map((spec) => {
  const artifact = JSON.parse(execFileSync("git", ["-C", path.resolve(root, "../cybergold-protocol"),
    "show", `${source.commit}:${spec.source}`], { encoding: "utf8" }));
  return { spec, generated: render(spec, artifact) };
});

for (const { spec, generated } of generatedModules) {
  if (check) {
    if (!fs.existsSync(spec.output) || fs.readFileSync(spec.output, "utf8") !== generated) {
      throw new Error(`Generated ABI module drift: ${spec.output}`);
    }
  } else {
    fs.mkdirSync(path.dirname(spec.output), { recursive: true });
    fs.writeFileSync(spec.output, generated);
    process.stdout.write(`Generated ${spec.output}\n`);
  }
}
