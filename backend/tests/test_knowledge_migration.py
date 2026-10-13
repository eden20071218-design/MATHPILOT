from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text, Table, MetaData, UniqueConstraint

from app.core.config import settings
from app.db.base import Base


def test_upgrade_existing_schema_preserves_data_and_downgrades(tmp_path, monkeypatch):
    url = "sqlite:///" + tmp_path.joinpath("migration.db").as_posix()
    monkeypatch.setattr(settings, "database_url", url)
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(config, "20261013_0001")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO knowledge_points(id, code, name, subject, version) VALUES (:id, 'old', 'existing', 'mathematics', 1)"),
                           {"id": "00000000000000000000000000000001"})
        # Reproduce the legacy SQLite schema's two identically named constraints.
        table = Table('exam_questions', MetaData(), autoload_with=connection)
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint):
                constraint.name = 'uq_exam_questions_exam_id'
        # This temporary test database's table is empty. Use direct DDL because
        # Alembic batch itself collapses two constraints with an identical name.
        table.drop(connection)
        table.create(connection)
    assert "knowledge_revisions" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT name FROM knowledge_points WHERE code='old'")).scalar_one() == "existing"
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        assert {c['name'] for c in inspect(connection).get_unique_constraints('exam_questions')} == {'uq_exam_question', 'uq_exam_position'}
    command.downgrade(config, "20261013_0001")
    assert "knowledge_revisions" not in inspect(engine).get_table_names()
    assert "knowledge_points" in inspect(engine).get_table_names()
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()
