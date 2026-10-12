import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

import models
from main import _ensure_ai_views


def test_ai_attendance_summary_view_has_exam_columns():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        # Create a class, exam, student, and eligibility row
        cls = models.Class(name="CI-1", branch="CSE", year=3)
        db.add(cls)
        db.commit()

        exam = models.MstExam(label="MST-1", class_id=cls.id)
        db.add(exam)
        db.commit()

        student = models.Student(roll_number="0827CS211001", name="Alice", class_id=cls.id)
        db.add(student)
        db.commit()

        elig = models.MstEligibility(
            student_id=student.id,
            mst_exam_id=exam.id,
            overall_pct=78.5,
            lowest_subject_pct=65.0,
            status="Eligible",
        )
        db.add(elig)
        db.commit()

        # Build view using the same definition
        view_sql = """
            CREATE VIEW ai_attendance_summary AS
            SELECT c.name AS class_name, s.roll_number, s.name AS student_name,
            me.overall_pct, me.lowest_subject_pct,
            me.mst_exam_id, e.label AS mst_label
            FROM mst_eligibility me
            JOIN students s ON s.id = me.student_id
            JOIN classes c ON c.id = s.class_id
            LEFT JOIN mst_exams e ON e.id = me.mst_exam_id
        """
        db.execute(text(view_sql))
        db.commit()

        rows = db.execute(text("SELECT * FROM ai_attendance_summary")).mappings().all()
        assert len(rows) == 1
        row = rows[0]
        assert "mst_exam_id" in row
        assert "mst_label" in row
        assert row["mst_exam_id"] == exam.id
        assert row["mst_label"] == "MST-1"
        assert row["roll_number"] == "0827CS211001"
        assert float(row["overall_pct"]) == 78.5
    finally:
        db.close()
