import {encodeAbiParameters,encodeEventTopics,parseEventLogs,toEventSelector} from 'viem';
import {createKnownRawLogDecoder} from '../../src/server/onchain-indexer/rawLogModel';
import {retainedDashboard} from './retained_dashboard';
const definitions=retainedDashboard({}).definitions,cases:any[]=[];
function value(param:any):any{
 if(param.type.endsWith('[]'))return [value({...param,type:param.type.slice(0,-2)})];
 if(param.type==='tuple')return Object.fromEntries(param.components.map((p:any)=>[p.name,value(p)]));
 if(param.type==='address')return '0x'+'a'.repeat(40);
 if(param.type==='bool')return true;
 if(param.type==='bytes')return '0x1234';
 if(param.type.startsWith('bytes'))return '0x'+'ab'.repeat(Number(param.type.slice(5)));
 return param.type==='uint8'?1:99n;
}
for(const domain of ['core','governance'])for(const definition of definitions[domain])for(const mode of ['normal','missing-topics','bad-data','extra-topics','uppercase-topic','unknown-topic']){
 const abi=definition.abi,args=Object.fromEntries(abi.inputs.map((p:any)=>[p.name,value(p)]));
 const topics=encodeEventTopics({abi:[abi],eventName:abi.name,args}),parameters=abi.inputs.filter((p:any)=>!p.indexed);
 let data=encodeAbiParameters(parameters,parameters.map((p:any)=>args[p.name]));
 if(mode==='missing-topics')topics.splice(1);
 if(mode==='bad-data')data='0x01';
 if(mode==='extra-topics')topics.push('0x'+'b'.repeat(64));
 if(mode==='uppercase-topic')topics[0]=topics[0].toUpperCase().replace('0X','0x');
 if(mode==='unknown-topic')topics[0]='0x'+'f'.repeat(64);
 const log={address:'0x'+'1'.repeat(40),blockNumber:103n,blockHash:'0x'+'b'.repeat(64),transactionHash:'0x'+'c'.repeat(64),transactionIndex:0,logIndex:0,removed:false,topics,data};
 let known,error;try{known=createKnownRawLogDecoder(definitions[domain])(log);}catch(e){error=(e as Error).message;}
 const legacy=parseEventLogs({abi:[abi],logs:[log],strict:false});
 cases.push({domain,name:definition.name,mode,log,expected:{known:known??null,error:error??null,
  legacy:legacy.length?{eventName:legacy[0].eventName,args:legacy[0].args??null}:null}});
}
console.log(JSON.stringify(cases,(_key,value)=>typeof value==='bigint'?value.toString():value));
