import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { quotePool, sqrtRatioAtTick } from '../src/uniswap-sdk/engine.ts';
import type { PoolSnapshot } from '../src/uniswap-sdk/types.ts';

const require = createRequire(import.meta.url);
const { Token, CurrencyAmount } = require('@uniswap/sdk-core');
const { Pool } = require('@uniswap/v3-sdk');
const JSBI = require('jsbi');
const token0 = { address: '0x0000000000000000000000000000000000000001', decimals: 18, chainId: 1 };
const token1 = { ...token0, address: '0x0000000000000000000000000000000000000002' };

test('empty positive and negative bitmap words preserve upstream swap rounding and post-state', async () => {
  for (const [spacing, fee] of [[1, 100], [10, 500]]) {
    const ticks = [
      { index: -2048 * spacing, liquidityGross: '1000000000000', liquidityNet: '1000000000000' },
      { index: 2048 * spacing, liquidityGross: '1000000000000', liquidityNet: '-1000000000000' },
    ];
    for (const tick of [-1, 0, 255]) for (const direction of [true, false]) {
      for (const mode of ['exactIn', 'exactOut'] as const) {
        const snapshot: PoolSnapshot = {
          id: 'empty-words', protocol: 'v3', token0, token1, feePips: fee, tickSpacing: spacing,
          tick, sqrtRatioX96: sqrtRatioAtTick(tick), liquidity: '1000000000000', ticks,
          bitmapWords: Array.from({ length: 17 }, (_, i) => ({ wordPosition: i - 8,
            bitmap: i === 0 || i === 16 ? '1' : '0' })),
        };
        const original = structuredClone(snapshot);
        const reference = new Pool(new Token(1, token0.address, 18), new Token(1, token1.address, 18),
          fee, snapshot.sqrtRatioX96, snapshot.liquidity, tick, ticks);
        const currency = mode === 'exactIn' ? direction ? token0 : token1 : direction ? token1 : token0;
        const amount = CurrencyAmount.fromRawAmount(new Token(1, currency.address, 18), '1000000000000');
        const limit = sqrtRatioAtTick((direction ? -1024 : 1024) * spacing);
        const [expectedAmount, expectedState] = await (mode === 'exactIn'
          ? reference.getOutputAmount(amount, JSBI.BigInt(limit)) : reference.getInputAmount(amount, JSBI.BigInt(limit)));
        for (const protocol of ['v3', 'v4'] as const) {
          const result = await quotePool({ ...snapshot, protocol, lpFee: fee, protocolFee: 0 },
            mode, amount.quotient.toString(), direction, limit);
          assert.equal(mode === 'exactIn' ? result.amountOut : result.amountIn, expectedAmount.quotient.toString());
          assert.equal(result.postState.sqrtRatioX96, expectedState.sqrtRatioX96.toString());
          assert.equal(result.postState.tick, expectedState.tickCurrent);
          assert.equal(result.postState.liquidity, expectedState.liquidity.toString());
          assert.equal(result.fullyFilled, false);
          assert.ok(BigInt(result.remainingAmount) > 0n);
        }
        assert.deepEqual(snapshot, original);
      }
    }
  }
});
