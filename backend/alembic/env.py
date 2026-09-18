"""Alembic environment.

The URL and the engine come from app.db, so WAL and foreign keys are set on
a migration connection exactly as they are on a request connection.

render_as_batch is on for SQLite because SQLite cannot alter a column in
place. Without it the first migration that changes a column type fails, and
it fails in phase two rather than now. On Postgres batch mode is unnecessary
and clutters the DDL — turn it off there.
"""

from logging.config import fileConfig

from alembic import context

from app.db import engine
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# SQLite needs batch mode to alter columns. Postgres does not.
_IS_SQLITE = engine.url.get_backend_name() == "sqlite"


def run_migrations_offline() -> None:
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=_IS_SQLITE,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_IS_SQLITE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
