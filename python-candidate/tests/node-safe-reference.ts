import { encodeAbiParameters, toEventHash, type Hex } from "viem";
import { safeExecutionLogArgs } from "../../src/server/safe-events/indexer";
const txHash = `0x${"Ab".repeat(32)}` as Hex;
const fixtures = [];
for (const event of ["ExecutionSuccess", "ExecutionFailure"]) {
  const topic = toEventHash(`${event}(bytes32,uint256)`);
  for (const payment of [0n, 1n, 2n ** 64n, 2n ** 256n - 1n]) {
    const data = encodeAbiParameters([{ type: "uint256" }], [payment]);
    fixtures.push({ topics: [topic, txHash], data });
    fixtures.push({ topics: [topic], data: encodeAbiParameters([{ type: "bytes32" }, { type: "uint256" }], [txHash, payment]) });
  }
  fixtures.push({ topics: [topic, txHash], data: "0x" });
  fixtures.push({ topics: [topic, txHash, txHash], data: "0x" });
  fixtures.push({ topics: [topic, txHash], data: "0x01" });
  fixtures.push({ topics: [topic], data: "0x01" });
  fixtures.push({ topics: [topic, "0x01"], data: "0x" });
}
process.stdout.write(JSON.stringify(fixtures.map(log => {
  const value = safeExecutionLogArgs(log as { topics: Hex[]; data: Hex });
  return { log, result: value ? { safeTxHash: value.safeTxHash, payment: value.payment.toString() } : null };
})) + "\n");
