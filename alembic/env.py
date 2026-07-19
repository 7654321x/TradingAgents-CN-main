from tradingagents.storage.db import Base
from tradingagents.storage.models import import_models
from alembic import context
from sqlalchemy import engine_from_config, pool
from logging.config import fileConfig
import configparser
import os
import_models()
target_metadata = Base.metadata

config = context.config
# A temporary URL is used by schema-generation and verification tests; it
# deliberately takes precedence over alembic.ini's local default.
override_url = os.getenv("TRADINGAGENTS_ALEMBIC_DATABASE_URL")
if override_url:
    config.set_main_option("sqlalchemy.url", override_url)
# Project alembic.ini intentionally has a minimal logging section.
def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle":"named"})
    with context.begin_transaction(): context.run_migrations()
def run_migrations_online():
    connectable=engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection,target_metadata=target_metadata)
        with context.begin_transaction(): context.run_migrations()
if context.is_offline_mode(): run_migrations_offline()
else: run_migrations_online()
