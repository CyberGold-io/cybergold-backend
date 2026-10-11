"""Baseline the retained twelve-table backend schema; no domain redesign."""
import json
from pathlib import Path
from alembic import op

revision = '0012_retained'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Freeze the baseline here; future revisions do not edit this snapshot.
    statements = json.loads(Path(__file__).with_suffix('.json').read_text())['statements']
    for statement in statements:
        op.execute(statement)


def downgrade():
    # Unregister the baseline without destroying retained application data.
    # Returning to old code does not require dropping the current schema.
    pass
