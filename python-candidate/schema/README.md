# Backend schema revisions

Use the standard Alembic CLI with this `alembic.ini`. `DATABASE_URL` is supplied
privately; it is not written in the config. Native SQLAlchemy/psycopg manages
connections and PostgreSQL transactional DDL. No command runs at API or worker
startup, and Safe/Django and broker databases are outside this environment.

`0012_retained` freezes the current twelve backend tables and indexes. For an
existing retained-schema database, use `alembic -c schema/alembic.ini stamp
0012_retained`: only Alembic's version metadata is created/recorded. For a new
empty database use `upgrade head`, which installs the frozen retained schema
and the additive protocol identity revision.
Returning the version to `base` leaves all application tables/data intact.
Code rollback does not rewind data or change an accepted schema revision.

The existing lazy schema initialization remains in place during adoption. A
later schema-changing release must supply its reviewed revision and explicit
maintenance procedure; adoption creates no new startup prerequisite. Do not
change the frozen baseline JSON. Standard `revision`, `upgrade`, `current`,
`history` and offline `upgrade head --sql` remain available.

`0013_pool_identity` adds `quote_pool_identity_cache`. From a stamped retained
database, `upgrade head` creates the table and copies each historical V3 row
verbatim into `legacy_payload`, retaining the original table and all values.
The new table stores pool identifiers rather than a second pool-state cache:
V4 keys contain PoolManager plus the PoolId derived from the full PoolKey.
The authoritative producer refreshes every hint through the shared registry.
Lazy bootstrap applies the same additive SQL; no schema health condition is
added to quote eligibility. Downgrade preserves the new table/history too.

The optional `tests/native_pool_identity.py seed`/`recover` probe targets a
disposable `DATABASE_URL`; restarting its PostgreSQL between stages exercises
lossless migration and distinct V4 spacing/hooks identities. Its contract RPC
is explicitly synthetic. It is qualification evidence, not a startup gate.

Reference: [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html).
