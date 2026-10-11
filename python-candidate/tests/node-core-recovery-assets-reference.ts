import { encodeFunctionData, encodeAbiParameters, parseAbi, getAddress } from 'viem';
const abi=parseAbi(['function coreAttachedRecoveryAssets() view returns (address[])']);
const core=getAddress(`0x${'4'.repeat(40)}`);
const assets=[getAddress('0x68749665ff8d2d112fa859aa293f07a622782f38'),getAddress('0x45804880de22913dafe09f4980848ece6ecbaf78')];
console.log(JSON.stringify({core,assets,data:encodeFunctionData({abi,functionName:'coreAttachedRecoveryAssets'}),
 result:encodeAbiParameters([{type:'address[]'}],[assets]),empty:encodeAbiParameters([{type:'address[]'}],[[]])}));
