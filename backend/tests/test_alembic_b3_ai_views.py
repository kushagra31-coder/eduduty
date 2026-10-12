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
import ai_service


def get_alembic_config(db_url: str) -> Config:
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ini_path = os.path.join(backend_dir, "alembic.ini")
    config = Config(ini_path)
    config.set_main_option("sqlalchemy.url", db_url)
    return config


def test_b3_migration_view_existence_and_columns():
    """Requirements 1, 2, 3: Migration applies to head, all 5 views exist with expected columns."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)

        # 1. Fresh database migrates through 001 -> 002 -> 003
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        inspector = inspect(engine)
        view_names = inspector.get_view_names()

        # 2. All 5 views exist after migration
        expected_views = {
            "ai_eligibility_summary",
            "ai_attendance_summary",
            "ai_vt_candidates",
            "ai_duty_roster",
            "v_vt_follow_up_status",
        }
        for view in expected_views:
            assert view in view_names, f"View '{view}' missing from migrated database"

        # 3. Each view exposes expected column names
        cols_eligibility = [c["name"] for c in inspector.get_columns("ai_eligibility_summary")]
        assert cols_eligibility == ["class_name", "mst_label", "eligible_count", "borderline_count", "ineligible_count", "missing_count"]

        cols_attendance = [c["name"] for c in inspector.get_columns("ai_attendance_summary")]
        assert cols_attendance == ["class_name", "mst_label", "roll_number", "student_name", "overall_pct", "lowest_subject_pct"]

        cols_vt_cand = [c["name"] for c in inspector.get_columns("ai_vt_candidates")]
        assert cols_vt_cand == ["class_name", "roll_number", "student_name", "mst1_status", "mst2_status"]

        cols_duty = [c["name"] for c in inspector.get_columns("ai_duty_roster")]
        assert set(cols_duty) in (
            {"mst_label", "exam_date", "room_number", "faculty_name", "duty_status"},
            {"mst_label", "exam_date", "room_number", "faculty_name", "faculty_id", "duty_status"},
        )

        cols_vt_status = [c["name"] for c in inspector.get_columns("v_vt_follow_up_status")]
        assert cols_vt_status == [
            "roll_number", "student_name", "class_name", "mst_1_label", "mst_2_label",
            "mst_1_appeared", "mst_2_appeared", "calculated_status", "final_status",
            "overridden", "override_reason", "rule_version", "updated_at"
        ]

        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_b3_view_data_query_correctness_and_privacy():
    """Requirements 4, 5, 6, 7: Seeded records return correct results; empty/missing optional FKs handled safely."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Seed test data
        cls = models.Class(name="CI-1", branch="CSE", year=3, section="A")
        session.add(cls)
        session.flush()

        s1 = models.Student(roll_number="0801CS211001", name="Alice", class_id=cls.id)
        s2 = models.Student(roll_number="0801CS211002", name="Bob", class_id=cls.id)
        session.add_all([s1, s2])
        session.flush()

        e1 = models.MstExam(label="MST-1", exam_date=datetime.date(2026, 11, 1), class_id=cls.id)
        e2 = models.MstExam(label="MST-2", exam_date=datetime.date(2026, 12, 1), class_id=cls.id)
        session.add_all([e1, e2])
        session.flush()

        # Seed eligibility
        el1 = models.MstEligibility(student_id=s1.id, mst_exam_id=e1.id, overall_pct=78.5, lowest_subject_pct=65.0, status="Eligible")
        el2 = models.MstEligibility(student_id=s2.id, mst_exam_id=e1.id, overall_pct=42.0, lowest_subject_pct=35.0, status="Not eligible")
        session.add_all([el1, el2])

        # Seed attempts
        att1 = models.MstAttempt(student_id=s1.id, mst_exam_id=e1.id, status="Present")
        att2 = models.MstAttempt(student_id=s1.id, mst_exam_id=e2.id, status="Absent")
        session.add_all([att1, att2])

        # Seed room & duty (one assigned, one unfilled)
        rm1 = models.Room(room_number="R-101", capacity=30)
        fac1 = models.Faculty(name="Dr. Smith", department="CSE")
        session.add_all([rm1, fac1])
        session.flush()

        duty1 = models.InvigilationDuty(mst_exam_id=e1.id, room_id=rm1.id, faculty_id=fac1.id, status="Assigned")
        duty2 = models.InvigilationDuty(mst_exam_id=e2.id, room_id=rm1.id, faculty_id=None, status="Unfilled")
        session.add_all([duty1, duty2])

        # Seed follow_up_status
        fus1 = models.FollowUpStatus(
            student_id=s1.id,
            mst_1_exam_id=e1.id,
            mst_2_exam_id=e2.id,
            mst_1_appeared=True,
            mst_2_appeared=False,
            calculated_status="under_review",
            final_status="excused",
            override=True,
            override_reason="Medical leave",
            updated_at=datetime.datetime.utcnow()
        )
        session.add(fus1)
        session.commit()

        # --- Assert View 1: ai_eligibility_summary ---
        res_el = session.execute(text("SELECT * FROM ai_eligibility_summary WHERE class_name='CI-1' AND mst_label='MST-1'")).mappings().first()
        assert res_el["eligible_count"] == 1
        assert res_el["ineligible_count"] == 1
        assert res_el["missing_count"] == 0

        # --- Assert View 2: ai_attendance_summary ---
        res_att = session.execute(text("SELECT * FROM ai_attendance_summary WHERE roll_number='0801CS211001'")).mappings().first()
        assert res_att["student_name"] == "Alice"
        assert float(res_att["overall_pct"]) == 78.5
        assert float(res_att["lowest_subject_pct"]) == 65.0

        # --- Assert View 3: ai_vt_candidates ---
        res_vt_cand = session.execute(text("SELECT * FROM ai_vt_candidates WHERE roll_number='0801CS211001'")).mappings().first()
        assert res_vt_cand["mst1_status"] == "Present"
        assert res_vt_cand["mst2_status"] == "Absent"

        # Bob has no attempt records -> mst1_status & mst2_status are 'Missing' / NULL
        res_vt_bob = session.execute(text("SELECT * FROM ai_vt_candidates WHERE roll_number='0801CS211002'")).mappings().first()
        assert res_vt_bob["mst1_status"] in (None, "Missing")
        assert res_vt_bob["mst2_status"] in (None, "Missing")

        # Verify no duplicate rows generated by joins for s1 or s2
        vt_rows = session.execute(text("SELECT * FROM ai_vt_candidates")).mappings().all()
        assert len(vt_rows) == 2

        # --- Assert View 4: ai_duty_roster ---
        duties = session.execute(text("SELECT * FROM ai_duty_roster ORDER BY mst_label")).mappings().all()
        assert len(duties) == 2
        d1 = next(d for d in duties if d["mst_label"] == "MST-1")
        assert d1["faculty_name"] == "Dr. Smith"
        assert d1["duty_status"] == "Assigned"

        d2 = next(d for d in duties if d["mst_label"] == "MST-2")
        assert d2["faculty_name"] is None  # Handled missing optional faculty gracefully
        assert d2["duty_status"] == "Unfilled"

        # --- Assert View 5: v_vt_follow_up_status ---
        fus_row = session.execute(text("SELECT * FROM v_vt_follow_up_status WHERE roll_number='0801CS211001'")).mappings().first()
        assert fus_row["student_name"] == "Alice"
        assert fus_row["class_name"] == "CI-1"
        assert fus_row["mst_1_label"] == "MST-1"
        assert fus_row["mst_2_label"] == "MST-2"
        assert fus_row["mst_1_appeared"] == 1 or fus_row["mst_1_appeared"] is True
        assert fus_row["mst_2_appeared"] == 0 or fus_row["mst_2_appeared"] is False
        assert fus_row["final_status"] == "excused"
        assert fus_row["overridden"] == 1 or fus_row["overridden"] is True
        assert fus_row["override_reason"] == "Medical leave"

        # --- Assert Privacy: sensitive tables/fields not exposed ---
        expected_views = {
            "ai_eligibility_summary",
            "ai_attendance_summary",
            "ai_vt_candidates",
            "ai_duty_roster",
            "v_vt_follow_up_status",
        }
        inspector = inspect(engine)
        # None of the 5 views expose user passwords, faculty exemption reasons, or raw system tokens
        for view_name in expected_views:
            col_names = [c["name"] for c in inspector.get_columns(view_name)]
            assert "password" not in col_names
            assert "supabase_uid" not in col_names
            assert "email" not in col_names

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_b3_ai_read_validator_allows_approved_views_and_rejects_unauthorized():
    """Requirement 8: Validator accepts the 5 approved views and rejects tables, DML/DDL, multi-statements."""
    # Approved views
    assert ai_service._validate_read_sql("SELECT * FROM ai_eligibility_summary")
    assert ai_service._validate_read_sql("SELECT * FROM ai_attendance_summary")
    assert ai_service._validate_read_sql("SELECT * FROM ai_vt_candidates")
    assert ai_service._validate_read_sql("SELECT * FROM ai_duty_roster")
    assert ai_service._validate_read_sql("SELECT * FROM v_vt_follow_up_status")

    # Unauthorized tables/views
    with pytest.raises(ValueError, match="not permitted"):
        ai_service._validate_read_sql("SELECT * FROM users")

    with pytest.raises(ValueError, match="not permitted"):
        ai_service._validate_read_sql("SELECT * FROM students")

    # DDL / DML keywords
    with pytest.raises(ValueError, match="Only SELECT|forbidden keywords"):
        ai_service._validate_read_sql("DELETE FROM ai_eligibility_summary")

    with pytest.raises(ValueError, match="Only SELECT|forbidden keywords"):
        ai_service._validate_read_sql("DROP VIEW ai_attendance_summary")

    # Multi-statement injection
    with pytest.raises(ValueError, match="Multi-statement"):
        ai_service._validate_read_sql("SELECT * FROM ai_duty_roster; DROP TABLE students")


def test_b3_downgrade_and_reupgrade_cycle():
    """Requirements 9 & 10: Downgrade drops only the 5 AI views; re-upgrade recreates them correctly."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)

        # 1. Upgrade to head (003)
        command.upgrade(config, "head")
        engine = create_engine(db_url)
        inspector = inspect(engine)

        views_003 = set(inspector.get_view_names())
        assert views_003 == {
            "ai_eligibility_summary",
            "ai_attendance_summary",
            "ai_vt_candidates",
            "ai_duty_roster",
            "v_vt_follow_up_status",
        }
        engine.dispose()

        # 2. Downgrade to 002
        command.downgrade(config, "002_add_unique_constraints")
        engine2 = create_engine(db_url)
        inspector2 = inspect(engine2)

        views_002 = set(inspector2.get_view_names())
        assert len(views_002) == 0, f"Expected 0 views after downgrade to 002, found: {views_002}"

        # Tables from 002 must be preserved
        tables_002 = set(inspector2.get_table_names())
        assert "students" in tables_002
        assert "mst_eligibility" in tables_002
        engine2.dispose()

        # 3. Re-upgrade to head (003)
        command.upgrade(config, "head")
        engine3 = create_engine(db_url)
        inspector3 = inspect(engine3)

        views_reup = set(inspector3.get_view_names())
        assert views_reup == {
            "ai_eligibility_summary",
            "ai_attendance_summary",
            "ai_vt_candidates",
            "ai_duty_roster",
            "v_vt_follow_up_status",
        }
        engine3.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_b3_main_eduduty_db_untouched():
    """Confirm main eduduty.db file modification timestamp remains unchanged."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_file = os.path.join(backend_dir, "eduduty.db")

    if os.path.exists(db_file):
        mtime_before = os.path.getmtime(db_file)
        test_b3_migration_view_existence_and_columns()
        mtime_after = os.path.getmtime(db_file)
        assert mtime_before == mtime_after, "eduduty.db must not be modified by tests"
