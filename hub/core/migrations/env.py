"""Environnement Alembic de `core.db` : SQL explicite, pas d'autogénération."""

from alembic import context

from hub.core.db import make_engine
from hub.core.migrations.runner import url_to_path

config = context.config
url = config.get_main_option("sqlalchemy.url") or ""

engine = make_engine(url_to_path(url))
with engine.connect() as connection:
    context.configure(connection=connection, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
