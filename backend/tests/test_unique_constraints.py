import pytest
from sqlalchemy import create_engine, text, UniqueConstraint
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

import models
from migrate_unique_constraints import run_unique_constraint_migration


def test_unique_constraint_defined_on_models():
    """Verify SQLAlchemy models define the UniqueConstraint on (student_id, mst_exam_id)."""
    elig_constraints = [
        c for c in models.MstEligibility.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    assert len(elig_constraints) >= 1
    elig_cols = {col.name for col in elig_constraints[0].columns}
    assert elig_cols == {"student_id", "mst_exam_id"}

    att_constraints = [
        c for c in models.MstAttempt.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    assert len(att_constraints) >= 1
    att_cols = {col.name for col in att_constraints[0].columns}
    assert att_cols == {"student_id", "mst_exam_id"}


def test_migration_deduplicates_and_enforces_unique_constraint():
    """Simulate legacy database without unique constraints, populated with duplicates,
    and verify the migration cleans duplicates (retaining latest) and enforces uniqueness."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    with engine.begin() as conn:
        # Create tables without unique constraint to simulate legacy unconstrained state
        conn.execute(text("""
            CREATE TABLE mst_eligibility (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                mst_exam_id INTEGER NOT NULL,
                overall_pct NUMERIC(5,2),
                lowest_subject_pct NUMERIC(5,2),
                status VARCHAR(20) NOT NULL,
                override BOOLEAN NOT NULL DEFAULT 0,
                override_reason VARCHAR(300),
                override_by INTEGER
            );
        """))
        conn.execute(text("""
            CREATE TABLE mst_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                mst_exam_id INTEGER NOT NULL,
                room_id INTEGER,
                seat_id INTEGER,
                status VARCHAR(30) NOT NULL,
                marked_by INTEGER,
                marked_at TIMESTAMP,
                remarks VARCHAR(300)
            );
        """))

        # Insert duplicate rows for student_id=1, mst_exam_id=1
        conn.execute(text("""
            INSERT INTO mst_eligibility (id, student_id, mst_exam_id, status, override)
            VALUES (1, 1, 1, 'Not eligible', 0), (2, 1, 1, 'Eligible', 1)
        """))
        conn.execute(text("""
            INSERT INTO mst_attempts (id, student_id, mst_exam_id, status)
            VALUES (1, 1, 1, 'Absent'), (2, 1, 1, 'Present')
        """))

    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        # Verify duplicate rows exist before migration
        elig_cnt = db.execute(text("SELECT COUNT(*) FROM mst_eligibility WHERE student_id=1 AND mst_exam_id=1")).scalar()
        att_cnt = db.execute(text("SELECT COUNT(*) FROM mst_attempts WHERE student_id=1 AND mst_exam_id=1")).scalar()
        assert elig_cnt == 2
        assert att_cnt == 2

        # Run migration
        report = run_unique_constraint_migration(engine)

        assert len(report["eligibility_duplicates"]) == 1
        assert len(report["attempt_duplicates"]) == 1
        assert report["eligibility_duplicates"][0]["student_id"] == 1
        assert report["constraints_applied"] is True

        # Verify only latest rows survive
        remaining_elig = db.execute(text("SELECT id, status, override FROM mst_eligibility WHERE student_id=1")).fetchall()
        assert len(remaining_elig) == 1
        assert remaining_elig[0][0] == 2  # Kept id=2 (latest)
        assert remaining_elig[0][1] == "Eligible"

        remaining_att = db.execute(text("SELECT id, status FROM mst_attempts WHERE student_id=1")).fetchall()
        assert len(remaining_att) == 1
        assert remaining_att[0][0] == 2  # Kept id=2 (latest)
        assert remaining_att[0][1] == "Present"

        # Verify unique constraint enforces uniqueness on mst_eligibility
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO mst_eligibility (student_id, mst_exam_id, status, override)
                    VALUES (1, 1, 'Duplicate', 0)
                """))

        # Verify unique constraint enforces uniqueness on mst_attempts
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO mst_attempts (student_id, mst_exam_id, status)
                    VALUES (1, 1, 'Duplicate')
                """))
    finally:
        db.close()
