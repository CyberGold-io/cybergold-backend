import {validateEnvironmentValue} from '../../src/config/environmentValidation';
import {readFileSync} from 'node:fs';

const catalog=JSON.parse(readFileSync('python-candidate/src/cybergold_candidate/environment-catalog.json','utf8'));
const values=[undefined,'','  ','\ufeffvalue\ufeff','value','0','1','0001','2','-1','1.5','9007199254740991','9007199254740992',
  '0x'+'a'.repeat(40),'a'.repeat(40),'0x'+'A'.repeat(40),'0x'+'a'.repeat(39),'0x'+'a'.repeat(40)+', 0x'+'b'.repeat(40),
  'http:example.com','https://fixture.invalid','https://[::1]:3000','http://','postgres:fixture','postgresql://fixture.invalid/product','ftp://fixture.invalid'];
const cases=[];
for(const kind of ['text','address','addresses','url','database','integer','positiveInteger','flag']) {
 const item=catalog.find((entry:any)=>entry.kind===kind);
 for(const value of values) for(const required of [false,true]) {
  let result:string|null=null;let error:string|null=null;
  try {result=validateEnvironmentValue(item.name,value,kind as any,required)??null;} catch(failure:any){error=failure.message;}
  cases.push({name:item.name,kind,required,value:value??null,result,error});
 }
}
process.stdout.write(JSON.stringify(cases)+'\n');
