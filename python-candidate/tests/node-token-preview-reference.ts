import { writeFileSync } from "node:fs";
import { encodeFunctionData, encodeFunctionResult } from "viem";
import { HELPERS_DIAMOND_ABI as abi } from "../../src/contracts/generated/helpersDiamond";

const helpers = "0x30e9afd21a30b2629be33508a131ac890368f534";
const inputToken = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2";
const outputToken = "0x45804880de22913dafe09f4980848ece6ecbaf78";
const adapter = "0x00000000000000000000000000000000000000a1";
const inputAmount = 2n ** 200n, netCygldOut = 2n ** 210n;
const quotes = [{ adapter, amountIn: inputAmount, minimumAmountOut: 2n ** 180n, data: "0x123400abcdef" }];
const redemption = [{ adapter, minimumAmountOut: 2n ** 180n, data: "0x00abcdef1234" }];
const fees = { protocolFeeCygld: 0n, helperFeeCygld: 2n ** 180n };
const projectedCoreOutputs = [{ kind: 0, token: outputToken, id: 0n, amount: inputAmount },
  { kind: 1, token: inputToken, id: 2n ** 190n, amount: 17n }];
const rows = [
  { mode: "issue-token-exact-in", name: "previewIssueFromTokenExactIn", args: [{ inputToken, inputAmount }, quotes],
    request: { mode: "issue-token-exact-in", inputToken, inputAmount, quotes }, value: { netCygldOut, fees, orderedCoreAssets: [outputToken, inputToken] } },
  { mode: "issue-native-exact-in", name: "previewIssueFromNativeExactIn", args: [inputAmount, quotes],
    request: { mode: "issue-native-exact-in", inputAmount, quotes }, value: { netCygldOut, fees, orderedCoreAssets: [outputToken, inputToken] } },
  { mode: "issue-token-exact-out", name: "previewIssueFromTokenExactOut", args: [{ inputToken, maximumInputAmount: inputAmount, netCygldOut }, quotes],
    request: { mode: "issue-token-exact-out", inputToken, maximumInputAmount: inputAmount, netCygldOut, quotes }, value: { fees, orderedCoreAssets: [outputToken, inputToken] } },
  { mode: "issue-native-exact-out", name: "previewIssueFromNativeExactOut", args: [{ maximumNativeIn: inputAmount, netCygldOut }, quotes],
    request: { mode: "issue-native-exact-out", maximumNativeIn: inputAmount, netCygldOut, quotes }, value: { fees, orderedCoreAssets: [outputToken, inputToken] } },
  { mode: "redeem-token-exact-in", name: "previewRedeemToTokenExactIn", args: [{ grossCygldIn: netCygldOut, outputToken }, redemption],
    request: { mode: "redeem-token-exact-in", grossCygldIn: netCygldOut, outputToken, quotes: redemption }, value: { minimumAmountOut: inputAmount, projectedCoreOutputs, fees } },
  { mode: "redeem-native-exact-in", name: "previewRedeemToNativeExactIn", args: [netCygldOut, redemption],
    request: { mode: "redeem-native-exact-in", grossCygldIn: netCygldOut, quotes: redemption }, value: { minimumAmountOut: inputAmount, projectedCoreOutputs, fees } },
] as const;
if (process.argv.includes("--write-abi")) {
  writeFileSync("python-candidate/src/cybergold_candidate/token-preview-abi.json",
    JSON.stringify(abi.filter(row => row.type === "function" && rows.some(entry => entry.name === row.name)), null, 2) + "\n");
}
console.log(JSON.stringify({ helpers, rows: rows.map(row => ({ ...row,
  data: encodeFunctionData({ abi, functionName: row.name, args: row.args } as never),
  result: encodeFunctionResult({ abi, functionName: row.name, result: row.value } as never),
})) }, (_key, value) => typeof value === "bigint" ? value.toString() : value));
