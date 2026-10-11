import {mkdtemp,writeFile,chmod,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fundForkWallet} from '../../src/server/faucet/forkFaucet';
const root=await mkdtemp(path.join(tmpdir(),'cybergold-legacy-faucet-'));
const source=`#!/usr/bin/env python3
import json,os,sys
mode=os.environ['FIXTURE_LEGACY_MODE']
assert sys.argv[2]=='--json'
assert os.environ['PATH'].startswith('/fixture-foundry:')
if mode=='invalid':print('invalid JSON');sys.exit(0)
if mode=='overflow':print('x'*1048577);sys.exit(0)
if mode.startswith('error:'):
 print(json.dumps({'status':'error','reason':mode[6:]}));sys.exit(1)
if mode=='private':print('fixture-private-detail',file=sys.stderr);sys.exit(1)
print(json.dumps({'status':'ok','address':sys.argv[1],'ethWei':'1','tokens':[],
 'dryRun':mode=='dry','extra':True} if mode=='extra' else {'status':'ok',
 'address':sys.argv[1],'ethWei':'1','tokens':[],'dryRun':mode=='dry'}))
`;
const script=path.join(root,'fund.py');await writeFile(script,source);await chmod(script,0o700);
const cases:any[]=[];
try{
 process.env.FORK_FAUCET_ENABLED='1';delete process.env.FORK_FAUCET_SERVICE_URL;delete process.env.FORK_FAUCET_SERVICE_TOKEN;
 process.env.FOUNDRY_BIN_DIR='/fixture-foundry';
 for(const mode of ['success','dry','extra','invalid','private','overflow','error:cooldown','error:LIMIT',
   'error:max calls','error:not allowed','error:private detail','missing','not-executable','production']){
   process.env.FIXTURE_LEGACY_MODE=mode;process.env.NODE_ENV=mode==='production'?'production':'test';
   process.env.FORK_FAUCET_SCRIPT_PATH=mode==='missing'?path.join(root,'missing'):script;
   await chmod(script,mode==='not-executable'?0o600:0o700);
   let result=null,error=null;
   try{result=await fundForkWallet('0x'+'a'.repeat(40));}
   catch(failure){const value=failure as any;error={code:value.code,status:value.status,message:value.message};}
   cases.push({mode,result,error});
 }
}finally{await rm(root,{recursive:true,force:true});}
console.log(JSON.stringify({source,cases}));
