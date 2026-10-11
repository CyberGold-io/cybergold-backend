"""Standard Alembic offline behavior, frozen schema and credential independence."""
import io
import json
from pathlib import Path
import unittest
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]


class SchemaToolingTests(unittest.TestCase):
    def test_offline_upgrade_emits_retained_schema_without_database_credentials(self):
        stream = io.StringIO()
        config = Config(str(ROOT / 'schema/alembic.ini'), output_buffer=stream)
        command.upgrade(config, 'head', sql=True)
        sql = stream.getvalue()
        schema = json.loads((ROOT / 'src/cybergold_candidate/retained-schema.json').read_text())
        for statement in schema['statements']:
            self.assertIn(statement.strip(), sql)
        self.assertIn("'0012_retained'", sql)
        self.assertIn('COMMIT;', sql)
        self.assertNotIn('DROP TABLE', sql)
        self.assertNotIn('password', sql.lower())

    def test_baseline_snapshot_is_frozen_and_native_history_has_one_head(self):
        self.assertEqual((ROOT / 'schema/versions/0012_retained.json').read_bytes(),
                         (ROOT / 'src/cybergold_candidate/retained-schema.json').read_bytes())
        stream = io.StringIO()
        command.heads(Config(str(ROOT / 'schema/alembic.ini'), stdout=stream))
        self.assertEqual(stream.getvalue().strip(), '0013_pool_identity (head)')
        self.assertEqual((ROOT / 'schema/versions/0013_pool_identity.json').read_bytes(),
                         (ROOT / 'src/cybergold_candidate/pool-identity-schema.json').read_bytes())

    def test_identity_migration_preserves_the_legacy_row_and_table(self):
        stream = io.StringIO()
        command.upgrade(Config(str(ROOT / 'schema/alembic.ini'), output_buffer=stream),
                        '0012_retained:head', sql=True)
        sql = stream.getvalue()
        self.assertIn('quote_pool_identity_cache', sql)
        self.assertIn('to_jsonb(quote_pool_cache)', sql)
        self.assertIn('ON CONFLICT(chain_id,dex,identity) DO NOTHING', sql)
        self.assertNotIn('ALTER TABLE quote_pool_cache', sql)
        self.assertNotIn('DROP TABLE', sql)


if __name__ == '__main__': unittest.main()
