import { encodeFunctionData, encodeFunctionResult } from 'viem';
import { CORE_DIAMOND_ABI } from '../../src/contracts/generated/coreDiamond.ts';
const core = `0x${'1'.repeat(40)}` as const;
console.log(JSON.stringify([0, 6, 18, 255].map((shareDecimals, index) => {
  const asset = `0x${String(index + 2).repeat(40)}` as const;
  const pool = { impaired: false, coreAttachedShares: 2n ** 200n, externalShares: 7n,
    redeemableRaw: 0n, cygldPerAssetRawFp18: 5n, cygldSupplyCap: 8n,
    referenceShares: 9n, referenceValueCygld: 10n, shareDecimals };
  return { core, asset, shareDecimals, data: encodeFunctionData({ abi: CORE_DIAMOND_ABI,
    functionName: 'recoveryPool', args: [asset] }), result: encodeFunctionResult({
    abi: CORE_DIAMOND_ABI, functionName: 'recoveryPool', result: pool }) };
})));
