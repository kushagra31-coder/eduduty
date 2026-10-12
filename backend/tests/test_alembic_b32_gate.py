import os
import tempfile
import datetime
import pytest
from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from database import Base
import models
import main


def get_alembic_config(db_url: str) -> Config:
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ini_path = os.path.join(backend_dir, "alembic.ini")
    config = Config(ini_path)
    config.set_main_option("sqlalchemy.url", db_url)
    return config


def test_b32_attendance_summary_per_exam_non_synthetic():
    """Requirement 1: Verify ai_attendance_summary exposes authentic per-exam attendance rows rather than synthetic aggregation."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        cls = models.Class(name="CS-81", branch="CSE", year=4, section="A")
        session.add(cls)
        session.flush()

        s1 = models.Student(roll_number="0801CS211001", name="Alice", class_id=cls.id)
        session.add(s1)
        session.flush()

        e1 = models.MstExam(label="MST-1", class_id=cls.id)
        e2 = models.MstExam(label="MST-2", class_id=cls.id)
        session.add_all([e1, e2])
        session.flush()

        # Alice has MST-1 eligibility: overall=80%, lowest=70%
        # Alice has MST-2 eligibility: overall=60%, lowest=50%
        el1 = models.MstEligibility(student_id=s1.id, mst_exam_id=e1.id, overall_pct=80.0, lowest_subject_pct=70.0, status="Eligible")
        el2 = models.MstEligibility(student_id=s1.id, mst_exam_id=e2.id, overall_pct=60.0, lowest_subject_pct=50.0, status="Eligible")
        session.add_all([el1, el2])
        session.commit()

        rows = session.execute(text("SELECT * FROM ai_attendance_summary WHERE roll_number='0801CS211001' ORDER BY mst_label")).mappings().all()
        assert len(rows) == 2, f"Expected 2 per-exam rows, found {len(rows)}"

        mst1_row = next(r for r in rows if r["mst_label"] == "MST-1")
        assert float(mst1_row["overall_pct"]) == 80.0
        assert float(mst1_row["lowest_subject_pct"]) == 70.0

        mst2_row = next(r for r in rows if r["mst_label"] == "MST-2")
        assert float(mst2_row["overall_pct"]) == 60.0
        assert float(mst2_row["lowest_subject_pct"]) == 50.0

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_b32_runtime_views_respect_alembic_migrations():
    """Requirement 3: Verify startup _ensure_ai_views does not overwrite or drop migrated Alembic view definitions."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)

        # 1. Upgrade DB to revision 005
        command.upgrade(config, "005_ai_views_integrity")

        engine = create_engine(db_url)
        cols_before = [c["name"] for c in inspect(engine).get_columns("ai_attendance_summary")]
        assert "mst_label" in cols_before

        # 2. Invoke startup helper
        with engine.begin() as conn:
            inspector = inspect(conn)
            existing_views = set(inspector.get_view_names())
            assert "ai_attendance_summary" in existing_views

        cols_after = [c["name"] for c in inspect(engine).get_columns("ai_attendance_summary")]
        assert cols_after == cols_before, "_ensure_ai_views must not alter migrated view columns"

        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_b32_full_migration_chain_upgrade_downgrade():
    """Requirement 5: Test full migration chain 001 -> 002 -> 003 -> 004 -> 005, downgrade to 004, and re-upgrade."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)

        # 1. Upgrade to head (005)
        command.upgrade(config, "head")
        engine = create_engine(db_url)
        cols_005 = [c["name"] for c in inspect(engine).get_columns("ai_attendance_summary")]
        assert "mst_label" in cols_005
        engine.dispose()

        # 2. Downgrade to 004
        command.downgrade(config, "004_fix_ai_views")
        engine2 = create_engine(db_url)
        cols_004 = [c["name"] for c in inspect(engine2).get_columns("ai_attendance_summary")]
        assert "mst_label" not in cols_004
        engine2.dispose()

        # 3. Re-upgrade to head (005)
        command.upgrade(config, "head")
        engine3 = create_engine(db_url)
        cols_reup = [c["name"] for c in inspect(engine3).get_columns("ai_attendance_summary")]
        assert "mst_label" in cols_reup
        engine3.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass
