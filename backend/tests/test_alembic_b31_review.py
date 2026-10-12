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


def get_alembic_config(db_url: str) -> Config:
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ini_path = os.path.join(backend_dir, "alembic.ini")
    config = Config(ini_path)
    config.set_main_option("sqlalchemy.url", db_url)
    return config


def test_b31_eligibility_status_classification():
    """Verify that Borderline, conditionally_eligible, Eligible, Not eligible, and Missing are classified correctly in 004 views."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        cls = models.Class(name="CS-81", branch="CSE", year=4, section="B")
        session.add(cls)
        session.flush()

        s1 = models.Student(roll_number="0801CS211001", name="Alice", class_id=cls.id)
        s2 = models.Student(roll_number="0801CS211002", name="Bob", class_id=cls.id)
        s3 = models.Student(roll_number="0801CS211003", name="Charlie", class_id=cls.id)
        s4 = models.Student(roll_number="0801CS211004", name="David", class_id=cls.id)
        s5 = models.Student(roll_number="0801CS211005", name="Eve", class_id=cls.id)
        session.add_all([s1, s2, s3, s4, s5])
        session.flush()

        e1 = models.MstExam(label="MST-1", class_id=cls.id)
        session.add(e1)
        session.flush()

        el1 = models.MstEligibility(student_id=s1.id, mst_exam_id=e1.id, status="Eligible")
        el2 = models.MstEligibility(student_id=s2.id, mst_exam_id=e1.id, status="Borderline")
        el3 = models.MstEligibility(student_id=s3.id, mst_exam_id=e1.id, status="conditionally_eligible")
        el4 = models.MstEligibility(student_id=s4.id, mst_exam_id=e1.id, status="Not eligible")
        el5 = models.MstEligibility(student_id=s5.id, mst_exam_id=e1.id, status="Missing")
        session.add_all([el1, el2, el3, el4, el5])
        session.commit()

        row = session.execute(text("SELECT * FROM ai_eligibility_summary WHERE class_name='CS-81' AND mst_label='MST-1'")).mappings().first()
        assert row["eligible_count"] == 1
        assert row["borderline_count"] == 2   # Borderline + conditionally_eligible
        assert row["ineligible_count"] == 1
        assert row["missing_count"] == 1

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_b31_vt_candidates_canonical_follow_up_integration():
    """Verify ai_vt_candidates integrates with follow_up_statuses and handles missing data cleanly."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        cls = models.Class(name="Cyber-3", branch="Cyber", year=2, section="A")
        session.add(cls)
        session.flush()

        s1 = models.Student(roll_number="0801CY211001", name="Grace", class_id=cls.id)
        s2 = models.Student(roll_number="0801CY211002", name="Heidi", class_id=cls.id)
        session.add_all([s1, s2])
        session.flush()

        # s1 has follow_up_statuses: MST-1 Present, MST-2 Absent
        fus1 = models.FollowUpStatus(
            student_id=s1.id,
            mst_1_appeared=True,
            mst_2_appeared=False,
            calculated_status="under_review",
            final_status="under_review",
            updated_at=datetime.datetime.utcnow()
        )
        session.add(fus1)
        session.commit()

        # s1 status
        r1 = session.execute(text("SELECT * FROM ai_vt_candidates WHERE roll_number='0801CY211001'")).mappings().first()
        assert r1["mst1_status"] == "Present"
        assert r1["mst2_status"] == "Absent"

        # s2 has no follow_up_statuses entry -> 'Missing' for both MSTs
        r2 = session.execute(text("SELECT * FROM ai_vt_candidates WHERE roll_number='0801CY211002'")).mappings().first()
        assert r2["mst1_status"] == "Missing"
        assert r2["mst2_status"] == "Missing"

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_b31_migration_003_to_004_upgrade_downgrade():
    """Verify upgrading 003 -> 004, checking view results, downgrading to 003, and re-upgrading."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)

        # 1. Upgrade to 003
        command.upgrade(config, "003_add_ai_views")
        engine = create_engine(db_url)
        cols_003 = [c["name"] for c in inspect(engine).get_columns("ai_eligibility_summary")]
        assert "borderline_count" not in cols_003
        engine.dispose()

        # 2. Upgrade to 004
        command.upgrade(config, "004_fix_ai_views")
        engine2 = create_engine(db_url)
        cols_004 = [c["name"] for c in inspect(engine2).get_columns("ai_eligibility_summary")]
        assert "borderline_count" in cols_004
        engine2.dispose()

        # 3. Downgrade to 003
        command.downgrade(config, "003_add_ai_views")
        engine3 = create_engine(db_url)
        cols_003_revert = [c["name"] for c in inspect(engine3).get_columns("ai_eligibility_summary")]
        assert "borderline_count" not in cols_003_revert
        engine3.dispose()

        # 4. Re-upgrade to head (004)
        command.upgrade(config, "head")
        engine4 = create_engine(db_url)
        cols_head = [c["name"] for c in inspect(engine4).get_columns("ai_eligibility_summary")]
        assert "borderline_count" in cols_head
        engine4.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass
