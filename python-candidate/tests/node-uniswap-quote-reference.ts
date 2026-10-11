import { writeFileSync } from "node:fs";
import { encodeFunctionData, encodeFunctionResult } from "viem";

// Existing App QuoterV2 wire interface, including all four ABI outputs.
const abi = ["quoteExactInput", "quoteExactOutput"].map(name => ({ type: "function" as const, name,
  stateMutability: "nonpayable" as const, inputs: [{ name: "path", type: "bytes" }, { name: "amount", type: "uint256" }],
  outputs: [{ name: "amount", type: "uint256" }, { name: "sqrtPriceX96After", type: "uint160[]" },
    { name: "initializedTicksCrossed", type: "uint32[]" }, { name: "gasEstimate", type: "uint256" }] }));
const helpers = "0x61ffe014ba17989e743c5f6cb21bf9697530b21e";
const direct = "0x45804880de22913dafe09f4980848ece6ecbaf78000bb8c02aaa39b223fe8d0a0e5c4f27ead9083c756cc2";
const rows = (["exact-in", "exact-out"] as const).flatMap(mode => [direct, direct + "0001f4a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"].map(path => {
  const name = mode === "exact-in" ? "quoteExactInput" : "quoteExactOutput";
  const request = { mode, path, amount: (2n ** 200n).toString() };
  return { mode, name, request, value: { amount: (2n ** 210n).toString() },
    data: encodeFunctionData({ abi, functionName: name, args: [path, 2n ** 200n] } as never),
    result: encodeFunctionResult({ abi, functionName: name, result: [2n ** 210n, [2n ** 150n], [17], 200_000n] } as never) };
}));
if (process.argv.includes("--write-abi")) writeFileSync("python-candidate/src/cybergold_candidate/uniswap-quote-abi.json", JSON.stringify(abi, null, 2) + "\n");
console.log(JSON.stringify({ helpers, rows }));
