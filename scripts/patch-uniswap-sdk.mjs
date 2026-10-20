import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";

// Expose existing fill status and active-liquidity observations; leave the
// SDK's swap arithmetic and tick traversal unchanged.
const require = createRequire(import.meta.url);
const root = resolve(dirname(require.resolve("@uniswap/v3-sdk")), "../../..");
for (const format of ["cjs", "esm"]) {
  const file = resolve(root, `dist/${format}/src/utils/v3swap.js`);
  let source = readFileSync(file, "utf8");
  const status = "        amountSpecifiedRemaining: state.amountSpecifiedRemaining,";
  if (!source.includes(status)) {
    const needle = "        amountCalculated: state.amountCalculated,";
    if (source.split(needle).length !== 2) throw new Error(`SDK status return not found: ${file}`);
    source = source.replace(needle, `${needle}\n${status}`);
  }
  const observed = "nextInitializedTickWithinOneWord(state.tick, zeroForOne, tickSpacing, state.liquidity)";
  if (!source.includes(observed)) {
    const needle = "nextInitializedTickWithinOneWord(state.tick, zeroForOne, tickSpacing)";
    if (source.split(needle).length !== 2) throw new Error(`SDK liquidity observation not found: ${file}`);
    source = source.replace(needle, observed);
  }
  writeFileSync(file, source);
}
for (const format of ["cjs", "esm", "types"]) {
  const file = resolve(root, `dist/${format}/src/utils/v3swap.d.ts`);
  const source = readFileSync(file, "utf8");
  if (source.includes("    amountSpecifiedRemaining: JSBI;")) continue;
  const needle = "    amountCalculated: JSBI;";
  if (source.split(needle).length !== 2) throw new Error(`SDK status type not found: ${file}`);
  writeFileSync(file, source.replace(needle, `${needle}\n    amountSpecifiedRemaining: JSBI;`));
}
