"""Alembic environment configuration for the Code Analyzer MVP.

Uses the same database configuration as the FastAPI app.
Works both inside Docker containers (prepend_sys_path = .) and locally.
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure the project root is on sys.path (alembic.ini sets prepend_sys_path = .)
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Alembic Config object
config = context.config

# Set up Python logging from alembic.ini if the section exists
if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except KeyError:
        # No logging sections in alembic.ini — that's fine, use defaults
        pass

# Import the ORM models so Alembic can autogenerate migrations
from api.models import Base  # noqa: E402
target_metadata = Base.metadata

# Resolve the database URL from the app's config
from api.config import config as app_config  # noqa: E402
database_url = app_config.DATABASE_URL
config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (just generate SQL, no connection)."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
