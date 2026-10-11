import { encodeFunctionData, encodeFunctionResult, parseAbi } from 'viem';
const abi = parseAbi(['function safeWallet() view returns (address)', 'function paused() view returns (bool)',
  'function canPause(address account) view returns (bool)', 'function canUnpause(address account) view returns (bool)']);
console.log(JSON.stringify(['core', 'staking', 'governance-diamond'].map((surface, index) => {
  const address = `0x${String(index + 1).repeat(40)}` as const;
  const account = `0x${'4'.repeat(40)}` as const, safe = `0x${'5'.repeat(40)}` as const;
  return { surface, address, account, safe, calls: [
    { name: 'safeWallet', args: [], result: safe }, { name: 'paused', args: [], result: index === 1 },
    { name: 'canPause', args: [account], result: true }, { name: 'canUnpause', args: [account], result: false },
    { name: 'canUnpause', args: [safe], result: true },
  ].map(row => ({ ...row, data: encodeFunctionData({ abi, functionName: row.name, args: row.args } as never),
    encodedResult: encodeFunctionResult({ abi, functionName: row.name, result: row.result } as never) })) };
})));
