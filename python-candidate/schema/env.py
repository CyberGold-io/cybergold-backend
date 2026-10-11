"""Native Alembic environment. Connection inputs remain private environment data."""
import os
from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool


def run(connection):
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(dialect_name='postgresql', literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif context.config.attributes.get('connection') is not None:
    run(context.config.attributes['connection'])
else:
    url = make_url(os.environ['DATABASE_URL']).set(drivername='postgresql+psycopg')
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            run(connection)
    finally:
        engine.dispose()
