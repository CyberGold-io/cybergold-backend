import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys

from cybergold_candidate.aliases import AliasAuthError, AliasService


class Database:
    def __init__(self,used):self.used=used;self.calls=[]
    async def ensure_schema(self):self.calls.append('schema')
    @asynccontextmanager
    async def connection(self):yield self
    async def execute(self,*args):self.calls.append('nonce');return self
    async def fetchone(self):return None if self.used else {'inserted':1}


async def main(path):
    cases=json.loads(Path(path).read_text())
    for case in cases:
        db=Database(case['mode']=='used');service=AliasService(db,lambda:1790762400000);error=None
        try:await service.authorize(case['params'])
        except AliasAuthError as failure:error=str(failure)
        assert (error,db.calls)==(case['error'],case['calls']),(case['params']['issuedAt'],case['mode'],error,db.calls,case)
    print(f'PASS: {len(cases)} actual Node/Python timestamp/signature/schema/nonce authorization-order comparisons')


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
