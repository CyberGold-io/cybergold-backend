import { publicEnv } from "./publicEnvironment.ts";
import type { TokenType } from "../types.ts";

interface token {
  id: string;
  symbol: string;
  name: string;
}

export interface nativeToken extends token {
  type: "native";
  decimals: number;
}

export interface erc20Token extends token {
  type: "erc20";
  address: `0x${string}`;
  decimals: number;
}

export type spendableToken = nativeToken | erc20Token;

export interface basket extends token {
  type: "basket";
  components: { token: erc20Token; targetWeight: bigint }[];
}

export const tokenAddresses = {
  CYGLD: publicEnv.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS as `0x${string}`, // CyberGold token address - defined in .env file
  XAUT: "0x68749665FF8D2d112Fa859AA293F07A622782F38",
  PAXG: "0x45804880De22913dAFE09f4980848ECE6EcbAf78",
  USDT: "0xdAC17F958D2ee523a2206206994597C13D831ec7",
  USDC: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
  WETH: "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", // Wrapped Ether, for Uniswap compatibility
} as const;

  export const tokens: TokenType[] = [
  { id: "cygld", symbol: "CYGLD", name: "CyberGold", type: "erc20", address: tokenAddresses.CYGLD, decimals: 18 },
  { id: "xaut", symbol: "XAUt", name: "Tether Gold", type: "erc20", address: tokenAddresses.XAUT, decimals: 6 },
  { id: "paxg", symbol: "PAXG", name: "Paxos Gold", type: "erc20", address: tokenAddresses.PAXG, decimals: 18 },
  {id: "usdt", symbol:"USDT", name:"Tether USD", type: "erc20", address: tokenAddresses.USDT, decimals: 6},
  {id: "usdc", symbol:"USDC", name:"USDC", type: "erc20", address: tokenAddresses.USDC, decimals: 6},
  {id: "eth", symbol:"ETH", name:"Ether", type: "native", decimals: 18},
  {id: "weth", symbol:"WETH", name:"Wrapped Ether", type: "erc20", address: tokenAddresses.WETH, decimals: 18},
]
