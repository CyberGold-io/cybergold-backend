import { decodeEventLog, encodeAbiParameters, encodeEventTopics } from 'viem';
import { HELPERS_DIAMOND_ABI } from '../../src/contracts/generated/helpersDiamond.ts';

function value(input: any): any {
  const array = input.type.match(/^(.*)\[(\d*)\]$/);
  if (array) return [value({ ...input, type: array[1] })];
  if (input.type === 'tuple') return Object.fromEntries(input.components.map((p: any) => [p.name, value(p)]));
  if (input.type === 'address') return '0x' + '1'.repeat(40);
  if (input.type === 'bool') return true;
  if (input.type.startsWith('uint')) return BigInt(2) ** BigInt(Math.min(200, Number(input.type.slice(4) || 256) - 1));
  if (input.type.startsWith('int')) return -1;
  if (input.type.startsWith('bytes')) return '0x' + '12'.repeat(Number(input.type.slice(5) || 4));
  throw new Error('Unrepresented canonical Helpers event parameter: ' + input.type);
}

const events = HELPERS_DIAMOND_ABI.filter((item) => item.type === 'event');
const rows = events.map((event: any, index) => {
  const args = Object.fromEntries(event.inputs.map((input: any) => [input.name, value(input)]));
  const parameters = event.inputs.filter((input: any) => !input.indexed);
  const topics = encodeEventTopics({ abi: [event], eventName: event.name, args });
  const data = encodeAbiParameters(parameters, parameters.map((input: any) => args[input.name]));
  const decoded = decodeEventLog({ abi: [event], topics, data });
  return { block_number: '101', block_hash: '0x' + (101).toString(16).padStart(64, '0'),
    tx_hash: '0x' + (index + 1000).toString(16).padStart(64, '0'), log_index: index,
    block_timestamp_seconds: '1101', topics, data,
    expected: { eventName: decoded.eventName, arguments: event.inputs.length ? decoded.args : null } };
});
console.log(JSON.stringify({ events, rows }, (_key, item) => typeof item === 'bigint' ? item.toString() : item));
