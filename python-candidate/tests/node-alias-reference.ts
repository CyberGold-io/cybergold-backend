import { hashMessage, recoverMessageAddress, parseCompactSignature, compactSignatureToSignature, serializeSignature } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import { buildGovernanceOwnerAliasAuthMessage } from '../../src/utils/governanceOwnerAliasesAuth';

const account=privateKeyToAccount(('0x'+'1'.repeat(64)) as `0x${string}`);
const aliases=['Treasury','  Treasury  ','CYGLD 🪙','quote " slash \\ newline\n','\ufeff 名称 \ufeff','\u001cname\u001c','\ud800','\u2028line\u2029'];
const results=[];
for(const [index,alias] of aliases.entries()) {
  const params={action:index%2?'delete':'upsert', editorAddress:account.address,
    ownerAddress:'0xABcdEFABcdEFabcdEfAbCdefabcdeFABcDEFabCD',alias,nonce:'fixture-'+index,
    issuedAt:'2026-09-30T10:00:00.000Z'} as any;
  const message=buildGovernanceOwnerAliasAuthMessage(params);
  const signature=await account.signMessage({message});
  const parity=BigInt(parseInt(signature.slice(-2),16)-27);
  const compact='0x'+signature.slice(2,66)+(BigInt('0x'+signature.slice(66,130))|(parity<<255n)).toString(16).padStart(64,'0');
  const v=parseInt(signature.slice(-2),16);
  const normalizedV=signature.slice(0,-2)+(v-27).toString(16).padStart(2,'0');
  const eip155=signature.slice(0,-2)+(v+10).toString(16).padStart(2,'0');
  const highS='0x'+signature.slice(2,66)+(0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141n-BigInt('0x'+signature.slice(66,130))).toString(16).padStart(64,'0')+(v===27?'1c':'1b');
  for(const value of [signature,compact,normalizedV,eip155,highS]) {
    let recovered:string|null=null;
    let error:string|null=null;
    try { recovered=await recoverMessageAddress({message,signature:(value.length === 130 ? serializeSignature(compactSignatureToSignature(parseCompactSignature(value as `0x${string}`))) : value) as `0x${string}`}); }
    catch { error='Invalid alias authorization signature.'; }
    results.push({params:{...params,signature:value},message,hash:hashMessage(message),recovered,error});
  }
}
process.stdout.write(JSON.stringify(results)+'\n');
