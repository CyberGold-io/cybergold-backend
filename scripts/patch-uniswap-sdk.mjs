import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";

// Expose the SDK's existing fill status; leave its swap algorithm unchanged.
const require = createRequire(import.meta.url);
const root = resolve(dirname(require.resolve("@uniswap/v3-sdk")), "../../..");
for (const format of ["cjs", "esm"]) {
  const file = resolve(root, `dist/${format}/src/utils/v3swap.js`);
  const source = readFileSync(file, "utf8");
  const status = "        amountSpecifiedRemaining: state.amountSpecifiedRemaining,";
  if (source.includes(status)) continue;
  const needle = "        amountCalculated: state.amountCalculated,";
  if (source.split(needle).length !== 2) throw new Error(`SDK status return not found: ${file}`);
  writeFileSync(file, source.replace(needle, `${needle}\n${status}`));
}
for (const format of ["cjs", "esm", "types"]) {
  const file = resolve(root, `dist/${format}/src/utils/v3swap.d.ts`);
  const source = readFileSync(file, "utf8");
  if (source.includes("    amountSpecifiedRemaining: JSBI;")) continue;
  const needle = "    amountCalculated: JSBI;";
  if (source.split(needle).length !== 2) throw new Error(`SDK status type not found: ${file}`);
  writeFileSync(file, source.replace(needle, `${needle}\n    amountSpecifiedRemaining: JSBI;`));
}
