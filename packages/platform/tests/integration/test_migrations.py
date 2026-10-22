import pytest
from alembic import command
from conftest import alembic_config, throwaway_database
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from robomcp_platform.db import make_engine
from robomcp_platform.models import Base


def test_upgrade_downgrade_upgrade_round_trip():
    with throwaway_database(migrate=False) as url:
        cfg = alembic_config(url)
        engine = make_engine(url)
        try:
            command.upgrade(cfg, "head")
            assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
            command.downgrade(cfg, "base")
            inspector = inspect(engine)
            assert inspector.get_table_names() == ["alembic_version"]
            with engine.connect() as conn:
                assert conn.scalar(text("SELECT count(*) FROM pg_proc WHERE proname = 'forbid_update'")) == 0
            command.upgrade(cfg, "head")
            assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
        finally:
            engine.dispose()


@pytest.mark.parametrize("table", ["suite_versions", "agent_versions"])
def test_versions_are_immutable(make_org, engine, table):
    org = make_org()
    org.experiment([{"key": "t", "check": "red"}], seeds=[1])
    column = "tasks" if table == "suite_versions" else "config"
    with pytest.raises(DBAPIError, match="immutable"), engine.begin() as conn:
        conn.execute(text(f"UPDATE {table} SET {column} = '{{}}'::jsonb"))
