"""Compare the actual retained fork DB actions and error ordering."""
import asyncio
import json
import re
import sys
from cybergold_candidate.fork_recovery import read_generation,prepare_generation,apply_generation,mark_ready

class Cursor:
    def __init__(self,rows):self.rows=rows
    async def fetchall(self):return self.rows

class Connection:
    def __init__(self,rows):
        self.state={'/'.join((row['chain'],row['address'],row['key'])):row['value'] for row in rows}
        self.operations=[]
    async def execute(self,sql,params):
        command=sql.strip().split()[0];table=re.search(r'(?:FROM|INTO|UPDATE)\s+(\w+)',sql,re.I)[1]
        params=list(params)
        if command=='SELECT':
            chain,second,*tail=params;keys=tail[0] if tail else second
            rows=[]
            for identity,value in self.state.items():
                row_chain,address,key=identity.split('/')
                if row_chain!=chain or key not in keys or tail and address!=second:continue
                rows.append({**({'contract_address':address} if 'SELECT contract_address' in sql else {}),'state_key':key,'state_value':value})
            return Cursor(rows)
        if command=='UPDATE':params=params[1:]+params[:1]
        self.operations.append({'command':command,'table':table,'params':params})
        if command in ('INSERT','UPDATE'):
            chain,address,key,value=params;self.state['/'.join((chain,address,key))]=value
        if command=='DELETE' and table=='onchain_sync_state':
            chain,keys=params
            self.state={identity:value for identity,value in self.state.items() if not(identity.split('/')[0]==chain and identity.split('/')[2] in keys)}
        return Cursor([])

def anchor(value):return {**value,'forkBlock':int(value['forkBlock'])}
def wire(value):
    if type(value) is int:return str(value)
    if isinstance(value,dict):return {key:wire(item) for key,item in value.items()}
    if isinstance(value,list):return [wire(item) for item in value]
    return value

async def check(fixture):
    for case in fixture['cases']:
        x=case['input'];connection=Connection(x['rows']);core=x['core'];current=anchor(x['current'])
        async def apply():return await apply_generation(connection,core,anchor(x['previous']),current,int(x['deploymentStart']),x['commonHash'])
        try:
            action=case['action']
            if action=='read':result=await read_generation(connection,core)
            elif action=='prepare':result=await prepare_generation(connection,core,current)
            elif action=='apply':result=await apply()
            elif action=='mark':result=await mark_ready(connection,core,int(x['reached']))
            else:
                await prepare_generation(connection,core,anchor(x['previous']))
                first=await apply();second=await apply();await mark_ready(connection,core,1200)
                result=[first,second,await apply(),await read_generation(connection,core)]
            actual={'result':wire(result)}
        except Exception as error:actual={'error':str(error)}
        actual['state']=[list(row) for row in sorted(connection.state.items())]
        actual['operations']=connection.operations
        assert actual==case['expected'],(case['name'],actual,case['expected'])
    print(f"PASS: {len(fixture['cases'])} retained fork recovery actions, mutations and error ordering")

if __name__=='__main__':asyncio.run(check(json.load(open(sys.argv[1]))))
