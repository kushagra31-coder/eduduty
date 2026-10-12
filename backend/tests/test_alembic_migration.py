import os
import sys
import tempfile
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic import command
from sqlalchemy import create_engine, inspect

from database import Base
import models


def test_alembic_config_and_metadata_discovery():
    """Verify Alembic configuration loads correctly and discovers all 18 ORM models."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ini_path = os.path.join(backend_dir, "alembic.ini")
    
    assert os.path.exists(ini_path), "alembic.ini must exist in backend/"
    
    config = Config(ini_path)
    script_dir = ScriptDirectory.from_config(config)
    
    # Check baseline revision registration
    revisions = list(script_dir.walk_revisions())
    assert len(revisions) >= 1
    assert revisions[-1].revision == "001_baseline_schema"

    # Verify target metadata has all 18 expected models
    tables = list(Base.metadata.tables.keys())
    assert len(tables) == 18
    assert "classes" in tables
    assert "students" in tables
    assert "faculty" in tables
    assert "attendance_records" in tables
    assert "mst_eligibility" in tables
    assert "mst_attempts" in tables
    assert "invigilation_duties" in tables
    assert "users" in tables
    assert "follow_up_statuses" in tables


def test_alembic_fresh_database_migration_and_no_drift():
    """
    Verify alembic upgrade head runs cleanly on a fresh temporary SQLite database,
    current/history commands work, and autogenerate comparison shows no drift.
    """
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ini_path = os.path.join(backend_dir, "alembic.ini")

    # Create isolated temporary database file
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        test_url = f"sqlite:///{db_path}"
        config = Config(ini_path)
        config.set_main_option("sqlalchemy.url", test_url)

        # 1. Run upgrade head on fresh DB
        command.upgrade(config, "head")

        # 2. Inspect created tables in fresh DB
        temp_engine = create_engine(test_url)
        inspector = inspect(temp_engine)
        created_tables = inspector.get_table_names()

        assert "alembic_version" in created_tables
        assert "classes" in created_tables
        assert "students" in created_tables
        assert "faculty" in created_tables
        assert "attendance_records" in created_tables
        assert "mst_eligibility" in created_tables
        assert "mst_attempts" in created_tables
        assert "follow_up_statuses" in created_tables
        assert len(created_tables) == 19  # 18 app tables + alembic_version

        # 3. Verify history and current command execution
        command.history(config)
        command.current(config)

        # 4. Verify no pending migrations / no drift against fresh DB
        from alembic.migration import MigrationContext
        from alembic.autogenerate import compare_metadata

        with temp_engine.connect() as conn:
            migration_context = MigrationContext.configure(conn)
            diff = compare_metadata(migration_context, Base.metadata)
            assert diff == [], f"Unexplained metadata drift detected on fresh database: {diff}"

        temp_engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_existing_eduduty_db_is_untouched():
    """Verify that migration tests do not touch or modify the main eduduty.db file."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_file = os.path.join(backend_dir, "eduduty.db")

    if os.path.exists(db_file):
        mtime_before = os.path.getmtime(db_file)
        # Execute config check
        test_alembic_config_and_metadata_discovery()
        mtime_after = os.path.getmtime(db_file)
        assert mtime_before == mtime_after, "eduduty.db must not be modified by tests"
