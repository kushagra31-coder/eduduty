import os
import tempfile
import pytest
from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from database import Base
import models


def get_alembic_config(db_url: str) -> Config:
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ini_path = os.path.join(backend_dir, "alembic.ini")
    config = Config(ini_path)
    config.set_main_option("sqlalchemy.url", db_url)
    return config


def setup_prereq_data(session):
    cls = models.Class(name="CS-A", branch="CSE", year=3, section="A")
    session.add(cls)
    session.flush()

    s1 = models.Student(roll_number="0801CS211001", name="Alice", class_id=cls.id)
    s2 = models.Student(roll_number="0801CS211002", name="Bob", class_id=cls.id)
    session.add_all([s1, s2])
    session.flush()

    e1 = models.MstExam(label="MST-1", class_id=cls.id)
    e2 = models.MstExam(label="MST-2", class_id=cls.id)
    session.add_all([e1, e2])
    session.flush()

    return cls, s1, s2, e1, e2


def test_b2_eligibility_uniqueness_enforcement():
    """Requirements 1, 2, 5: First eligibility succeeds, duplicate fails, distinct combos succeed."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        _, s1, s2, e1, e2 = setup_prereq_data(session)

        # 1. Valid first eligibility record inserts successfully
        el1 = models.MstEligibility(student_id=s1.id, mst_exam_id=e1.id, status="eligible")
        session.add(el1)
        session.commit()

        # 2. Second eligibility record with same student and exam is rejected
        el1_dup = models.MstEligibility(student_id=s1.id, mst_exam_id=e1.id, status="eligible")
        session.add(el1_dup)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # 5. Different student or different exam combinations remain valid
        el_diff_student = models.MstEligibility(student_id=s2.id, mst_exam_id=e1.id, status="eligible")
        el_diff_exam = models.MstEligibility(student_id=s1.id, mst_exam_id=e2.id, status="eligible")
        session.add_all([el_diff_student, el_diff_exam])
        session.commit()

        assert session.query(models.MstEligibility).count() == 3
        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_b2_attempt_uniqueness_enforcement():
    """Requirements 3, 4, 5: First attempt succeeds, duplicate fails, distinct combos succeed."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        _, s1, s2, e1, e2 = setup_prereq_data(session)

        # 3. Valid first attempt record inserts successfully
        att1 = models.MstAttempt(student_id=s1.id, mst_exam_id=e1.id, status="present")
        session.add(att1)
        session.commit()

        # 4. Second attempt record with same student and exam is rejected
        att1_dup = models.MstAttempt(student_id=s1.id, mst_exam_id=e1.id, status="absent")
        session.add(att1_dup)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # 5. Different student or different exam combinations remain valid
        att_diff_student = models.MstAttempt(student_id=s2.id, mst_exam_id=e1.id, status="present")
        att_diff_exam = models.MstAttempt(student_id=s1.id, mst_exam_id=e2.id, status="absent")
        session.add_all([att_diff_student, att_diff_exam])
        session.commit()

        assert session.query(models.MstAttempt).count() == 3
        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_b2_upgrade_nonduplicate_data_survival():
    """Requirement 6: Existing nonduplicate records survive upgrade 001 -> 002."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)

        # Upgrade to 001 baseline
        command.upgrade(config, "001_baseline_schema")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        _, s1, s2, e1, e2 = setup_prereq_data(session)

        # Add nonduplicate eligibility & attempt records in 001 baseline
        session.add_all([
            models.MstEligibility(student_id=s1.id, mst_exam_id=e1.id, status="eligible"),
            models.MstEligibility(student_id=s2.id, mst_exam_id=e1.id, status="eligible"),
            models.MstAttempt(student_id=s1.id, mst_exam_id=e1.id, status="present"),
            models.MstAttempt(student_id=s2.id, mst_exam_id=e2.id, status="absent"),
        ])
        session.commit()
        session.close()
        engine.dispose()

        # Upgrade to 002
        command.upgrade(config, "002_add_unique_constraints")

        # Verify data survived upgrade intact
        engine2 = create_engine(db_url)
        Session2 = sessionmaker(bind=engine2)
        session2 = Session2()

        assert session2.query(models.MstEligibility).count() == 2
        assert session2.query(models.MstAttempt).count() == 2
        session2.close()
        engine2.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_b2_upgrade_preflight_duplicate_failure_and_record_preservation():
    """Requirements 7 & 8: Duplicate data halts upgrade with clear diagnostic and preserves records."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)

        # Upgrade to 001 baseline
        command.upgrade(config, "001_baseline_schema")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        _, s1, _, e1, _ = setup_prereq_data(session)

        # Insert duplicate eligibility records directly
        session.add_all([
            models.MstEligibility(student_id=s1.id, mst_exam_id=e1.id, status="eligible"),
            models.MstEligibility(student_id=s1.id, mst_exam_id=e1.id, status="conditionally_eligible"),
        ])
        session.commit()
        session.close()
        engine.dispose()

        # Attempt upgrade to 002: must fail preflight check cleanly
        with pytest.raises(RuntimeError) as exc_info:
            command.upgrade(config, "002_add_unique_constraints")

        assert "Preflight data integrity check failed" in str(exc_info.value)
        assert "mst_eligibility contains duplicate" in str(exc_info.value)
        assert "Manual data reconciliation is required" in str(exc_info.value)

        # Verify records are fully preserved
        engine2 = create_engine(db_url)
        Session2 = sessionmaker(bind=engine2)
        session2 = Session2()

        assert session2.query(models.MstEligibility).count() == 2
        el_statuses = [e.status for e in session2.query(models.MstEligibility).all()]
        assert "eligible" in el_statuses
        assert "conditionally_eligible" in el_statuses

        session2.close()
        engine2.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_b2_downgrade_and_reupgrade_cycle():
    """Requirements 9 & 10: Downgrade removes constraints & preserves data; re-upgrade works."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)

        # Upgrade to head (002)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        _, s1, s2, e1, _ = setup_prereq_data(session)

        session.add_all([
            models.MstEligibility(student_id=s1.id, mst_exam_id=e1.id, status="eligible"),
            models.MstAttempt(student_id=s1.id, mst_exam_id=e1.id, status="present"),
        ])
        session.commit()
        session.close()
        engine.dispose()

        # Downgrade to 001
        command.downgrade(config, "001_baseline_schema")

        # Verify data preserved after downgrade
        engine2 = create_engine(db_url)
        Session2 = sessionmaker(bind=engine2)
        session2 = Session2()

        assert session2.query(models.MstEligibility).count() == 1
        assert session2.query(models.MstAttempt).count() == 1

        # Re-upgrade to head (002)
        session2.close()
        engine2.dispose()

        command.upgrade(config, "head")

        # Verify DB is at head with 002 applied
        engine3 = create_engine(db_url)
        Session3 = sessionmaker(bind=engine3)
        session3 = Session3()

        assert session3.query(models.MstEligibility).count() == 1
        assert session3.query(models.MstAttempt).count() == 1

        session3.close()
        engine3.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_b2_schema_zero_drift_check():
    """Verify alembic check / compare_metadata shows zero drift after 002 upgrade."""
    from alembic.migration import MigrationContext
    from alembic.autogenerate import compare_metadata

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        with engine.connect() as conn:
            migration_context = MigrationContext.configure(conn)
            diff = compare_metadata(migration_context, Base.metadata)
            assert diff == [], f"Unexpected metadata drift detected: {diff}"

        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass
