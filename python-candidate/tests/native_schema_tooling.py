"""Native PostgreSQL baseline/stamp preserves retained data without startup DDL gates."""
import asyncio
import json
from pathlib import Path
import subprocess
import time
import unittest
import uuid

from alembic import command
from alembic.config import Config
import psycopg
from sqlalchemy import create_engine, event
from cybergold_candidate.database import Database

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'postgres:18-alpine@sha256:9a8afca54e7861fd90fab5fdf4c42477a6b1cb7d293595148e674e0a3181de15'


class NativeSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = 'cybergold-schema-fixture-' + uuid.uuid4().hex[:12]
        subprocess.run(['docker','run','-d','--name',cls.container,'--publish','127.0.0.1::5432',
            '-e','POSTGRES_PASSWORD=synthetic-schema-fixture',IMAGE],check=True,stdout=subprocess.DEVNULL)
        cls.addClassCleanup(lambda: subprocess.run(['docker','rm','--force',cls.container],check=True,stdout=subprocess.DEVNULL))
        port = json.loads(subprocess.check_output(['docker','inspect',cls.container]))[0]['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']
        cls.url = 'postgresql://postgres:synthetic-schema-fixture@127.0.0.1:' + port + '/postgres'
        deadline = time.monotonic() + 60
        while True:
            try:
                with psycopg.connect(cls.url): break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline: raise
                time.sleep(.2)

    def setUp(self):
        self.name = 'fixture_' + uuid.uuid4().hex[:10]
        with psycopg.connect(self.url, autocommit=True) as admin:
            admin.execute('CREATE DATABASE ' + self.name)
        self.dsn = self.url.rsplit('/',1)[0] + '/' + self.name
        self.engine = create_engine(self.dsn.replace('postgresql://','postgresql+psycopg://'))
        self.addCleanup(self.engine.dispose)

    def migration(self, operation, revision):
        with self.engine.begin() as connection:
            config = Config(str(ROOT / 'schema/alembic.ini'))
            config.attributes['connection'] = connection
            getattr(command, operation)(config, revision)

    def catalog(self):
        with psycopg.connect(self.dsn) as connection:
            return connection.execute("""SELECT table_name,column_name,data_type,is_nullable,column_default
                FROM information_schema.columns WHERE table_schema='public' AND table_name!='alembic_version'
                ORDER BY table_name,ordinal_position""").fetchall()

    def retained_schema(self):
        async def install():
            database = Database(self.dsn)
            try: await database.ensure_schema()
            finally: await database.close()
        asyncio.run(install())

    def test_new_database_upgrade_matches_native_retained_bootstrap(self):
        self.migration('upgrade','head')
        before = self.catalog()
        self.assertEqual(len(set(row[0] for row in before)),13)
        # Native lazy bootstrap remains compatible with tool-created schema.
        self.retained_schema()
        self.assertEqual(self.catalog(), before)

    def test_existing_schema_stamp_preserves_alias_nonce_and_domain_catalog(self):
        self.retained_schema()
        before = self.catalog()
        with psycopg.connect(self.dsn) as connection:
            connection.execute("INSERT INTO governance_owner_aliases VALUES ('editor','owner','retained alias',NOW())")
            connection.execute("INSERT INTO governance_owner_alias_auth_nonces VALUES ('editor','consumed nonce',NOW())")
        statements = []
        event.listen(self.engine,'before_cursor_execute',lambda _c,_u,s,_p,_x,_m: statements.append(s))
        self.migration('stamp','0012_retained')
        self.assertEqual(self.catalog(),before)
        self.assertFalse(any('ALTER TABLE' in sql.upper() or 'DROP ' in sql.upper() for sql in statements))
        with psycopg.connect(self.dsn) as connection:
            self.assertEqual(connection.execute('SELECT alias FROM governance_owner_aliases').fetchone()[0],'retained alias')
            self.assertEqual(connection.execute('SELECT nonce FROM governance_owner_alias_auth_nonces').fetchone()[0],'consumed nonce')
            self.assertEqual(connection.execute('SELECT version_num FROM alembic_version').fetchone()[0],'0012_retained')

    def test_repeated_upgrade_keeps_current_writes(self):
        self.migration('upgrade','head')
        with psycopg.connect(self.dsn) as connection:
            connection.execute("INSERT INTO onchain_sync_state VALUES (1,'core','cursor','current target write',NOW())")
        self.migration('upgrade','head')
        with psycopg.connect(self.dsn) as connection:
            self.assertEqual(connection.execute('SELECT state_value FROM onchain_sync_state').fetchone()[0],'current target write')

    def test_baseline_unregister_does_not_destroy_tables_or_aliases(self):
        self.migration('upgrade','head')
        before = self.catalog()
        with psycopg.connect(self.dsn) as connection:
            connection.execute("INSERT INTO governance_owner_aliases VALUES ('editor','owner','current alias',NOW())")
        self.migration('downgrade','base')
        self.assertEqual(self.catalog(),before)
        with psycopg.connect(self.dsn) as connection:
            self.assertEqual(connection.execute('SELECT alias FROM governance_owner_aliases').fetchone()[0],'current alias')
            self.assertEqual(connection.execute('SELECT count(*) FROM alembic_version').fetchone()[0],0)


if __name__ == '__main__': unittest.main()
