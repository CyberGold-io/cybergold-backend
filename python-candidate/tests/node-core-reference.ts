import { writeFile } from 'node:fs/promises';
import { encodeAbiParameters, encodeEventTopics, type Hex } from 'viem';
import { CORE_ACTIVITY_ABI, decodeCoreActivity } from '../../src/server/onchain-indexer/coreActivity';

function argument(input: any): any {
  const array = input.type.match(/^(.*)\[(\d*)\]$/);
  if (array) return Array.from({length: array[2] ? Number(array[2]) : 2}, () => argument({...input,type:array[1]}));
  if (input.type === 'tuple') return input.components.map(argument);
  if (input.type === 'address') return `0x${'ab'.repeat(20)}`;
  if (input.type === 'bool') return true;
  if (/^u?int/.test(input.type)) {
    const bits = Number(input.type.replace(/^u?int/, '') || 256);
    return bits <= 48 ? 7 : 2n ** BigInt(bits - 2);
  }
  if (input.type === 'string') return 'fixture-é';
  if (input.type === 'bytes') return '0x12ab';
  if (/^bytes\d+$/.test(input.type)) return `0x${'ab'.repeat(Number(input.type.slice(5)))}`;
  throw new Error(`Fixture does not support ${input.type}`);
}
const fixtures=[];
for (const event of CORE_ACTIVITY_ABI) {
  const values=Object.fromEntries(event.inputs.map(input => [input.name,argument(input)]));
  const topics=encodeEventTopics({abi:[event],eventName:event.name,args:values});
  const data=encodeAbiParameters(event.inputs.filter(input => !input.indexed),event.inputs.filter(input => !input.indexed).map(input=>values[input.name]));
  const row={block_number:'100',block_hash:`0x${'a'.repeat(64)}`,tx_hash:`0x${'b'.repeat(64)}`,
    log_index:0,block_timestamp_seconds:'1000',topics:topics as Hex[],data};
  fixtures.push({row,result:decodeCoreActivity(row)});
}
for (const topics of [[],[`0x${'c'.repeat(64)}`],fixtures[0].row.topics]) {
  const row={...fixtures[0].row,topics:topics as Hex[],data:'0x01' as Hex};
  fixtures.push({row,result:decodeCoreActivity(row)});
}
await writeFile(new URL('../src/cybergold_candidate/core-activity-abi.json',import.meta.url), JSON.stringify(CORE_ACTIVITY_ABI,null,2)+'\n');
process.stdout.write(JSON.stringify(fixtures)+'\n');
