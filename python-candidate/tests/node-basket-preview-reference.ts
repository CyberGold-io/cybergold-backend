import { encodeFunctionData, encodeFunctionResult } from "viem";
import { HELPERS_DIAMOND_ABI } from "../../src/contracts/generated/helpersDiamond";

const helpers = "0x30e9afd21a30b2629be33508a131ac890368f534";
const tokens = ["0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "0x45804880de22913dafe09f4980848ece6ecbaf78"] as const;
const fees = { protocolFeeCygld: 0n, helperFeeCygld: 2n ** 180n };
const projectedCoreOutputs = [{ kind: 0, token: tokens[0], id: 0n, amount: 2n ** 200n },
  { kind: 1, token: tokens[1], id: 2n ** 190n, amount: 17n }];
const maximumAmountsIn = [2n ** 200n, 17n];
const minimumOutputs = projectedCoreOutputs.map(({ amount, ...row }) => ({ ...row, minimumAmount: amount }));
const rows = [
  { mode: "issue-exact-in", name: "previewIssueFromBasketExactIn", args: [maximumAmountsIn],
    request: { mode: "issue-exact-in", maximumAmountsIn },
    value: { netCygldOut: 2n ** 210n, fees, amountsInExact: maximumAmountsIn, orderedCoreAssets: tokens } },
  { mode: "issue-exact-out", name: "previewIssueFromBasketExactOut", args: [2n ** 210n],
    request: { mode: "issue-exact-out", netCygldOut: 2n ** 210n },
    value: { fees, amountsInExact: maximumAmountsIn, orderedCoreAssets: tokens } },
  { mode: "redeem-exact-in", name: "previewRedeemToBasketExactIn", args: [2n ** 210n],
    request: { mode: "redeem-exact-in", grossCygldIn: 2n ** 210n }, value: { projectedCoreOutputs, fees } },
  { mode: "redeem-exact-out", name: "previewRedeemToBasketExactOut", args: [minimumOutputs],
    request: { mode: "redeem-exact-out", minimumOutputs },
    value: { grossCygldIn: 2n ** 210n, projectedCoreOutputs, fees } },
] as const;
console.log(JSON.stringify({ helpers, rows: rows.map(row => ({ ...row,
  data: encodeFunctionData({ abi: HELPERS_DIAMOND_ABI, functionName: row.name, args: row.args } as never),
  result: encodeFunctionResult({ abi: HELPERS_DIAMOND_ABI, functionName: row.name, result: row.value } as never),
})) }, (_key, value) => typeof value === "bigint" ? value.toString() : value));
