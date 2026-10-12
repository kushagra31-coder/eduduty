import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
from pdf_service import build_student_record_html


def test_attendance_pct_property():
    # 29 / 44 = 65.909... -> 65.91
    rec1 = models.AttendanceRecord(classes_conducted=44, classes_attended=29)
    assert rec1.pct == 65.91

    # 0 conducted -> 0.0
    rec2 = models.AttendanceRecord(classes_conducted=0, classes_attended=0)
    assert rec2.pct == 0.0

    # None attended or None conducted
    rec3 = models.AttendanceRecord(classes_conducted=None, classes_attended=None)
    assert rec3.pct == 0.0


def test_pdf_html_contains_computed_pct():
    # Create an isolated in-memory SQLite DB for testing
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()

    try:
        # Create student class, student, subject, and attendance record
        test_class = models.Class(name="CS-A", branch="CS", year=3, section="A")
        db.add(test_class)
        db.commit()

        student = models.Student(
            roll_number="0827CS211001",
            name="Test Student",
            class_id=test_class.id,
            active=True,
        )
        db.add(student)
        db.commit()

        subject = models.Subject(name="Operating Systems", code="CS601")
        db.add(subject)
        db.commit()

        rec = models.AttendanceRecord(
            student_id=student.id,
            subject_id=subject.id,
            semester="VI",
            classes_conducted=44,
            classes_attended=29,
        )
        db.add(rec)
        db.commit()

        html = build_student_record_html(student.roll_number, db)
        assert "65.9%" in html
        assert "Operating Systems" in html
        assert "44" in html
        assert "29" in html
    finally:
        db.close()
