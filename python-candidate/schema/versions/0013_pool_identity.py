"""Add protocol pool identities; preserve every historical V3 row verbatim."""
import json
from pathlib import Path
from alembic import op

revision = '0013_pool_identity'
down_revision = '0012_retained'
branch_labels = None
depends_on = None


def upgrade():
    for statement in json.loads(Path(__file__).with_suffix('.json').read_text())['statements']:
        op.execute(statement)


def downgrade():
    # Old consumers still use the unchanged retained table. Preserve history.
    pass
