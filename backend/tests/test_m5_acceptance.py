import pytest
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

import models
import crud


def test_m5_eligibility_thresholds():
    """Eligibility thresholds:
    44.99 -> Not eligible
    45.00 -> Borderline
    49.99 -> Borderline
    50.00 -> Eligible
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()

    cls = models.Class(name="CS-A", branch="CS", year=2)
    exam = models.MstExam(label="MST-1")
    db.add_all([cls, exam])
    db.commit()

    # Create 4 students
    s1 = models.Student(roll_number="R4499", name="S 44.99", class_id=cls.id)
    s2 = models.Student(roll_number="R4500", name="S 45.00", class_id=cls.id)
    s3 = models.Student(roll_number="R4999", name="S 49.99", class_id=cls.id)
    s4 = models.Student(roll_number="R5000", name="S 50.00", class_id=cls.id)
    db.add_all([s1, s2, s3, s4])
    db.commit()

    # 44.99%: 4499 attended out of 10000 conducted
    rec1 = models.AttendanceRecord(student_id=s1.id, classes_conducted=10000, classes_attended=4499)
    # 45.00%: 45 attended out of 100 conducted
    rec2 = models.AttendanceRecord(student_id=s2.id, classes_conducted=100, classes_attended=45)
    # 49.99%: 4999 attended out of 10000 conducted
    rec3 = models.AttendanceRecord(student_id=s3.id, classes_conducted=10000, classes_attended=4999)
    # 50.00%: 50 attended out of 100 conducted
    rec4 = models.AttendanceRecord(student_id=s4.id, classes_conducted=100, classes_attended=50)
    db.add_all([rec1, rec2, rec3, rec4])
    db.commit()

    crud.compute_eligibility_for_student(db, s1.id, exam.id)
    crud.compute_eligibility_for_student(db, s2.id, exam.id)
    crud.compute_eligibility_for_student(db, s3.id, exam.id)
    crud.compute_eligibility_for_student(db, s4.id, exam.id)

    el1 = db.query(models.MstEligibility).filter_by(student_id=s1.id, mst_exam_id=exam.id).first()
    el2 = db.query(models.MstEligibility).filter_by(student_id=s2.id, mst_exam_id=exam.id).first()
    el3 = db.query(models.MstEligibility).filter_by(student_id=s3.id, mst_exam_id=exam.id).first()
    el4 = db.query(models.MstEligibility).filter_by(student_id=s4.id, mst_exam_id=exam.id).first()

    assert float(el1.overall_pct) == 44.99
    assert el1.status == "Not eligible"

    assert float(el2.overall_pct) == 45.00
    assert el2.status == "Borderline"

    assert float(el3.overall_pct) == 49.99
    assert el3.status == "Borderline"

    assert float(el4.overall_pct) == 50.00
    assert el4.status == "Eligible"

    db.close()


def test_m5_vt_rule_absent_both_mst_v1():
    """VT rule absent-both-mst-v1:
    - absent both -> compulsory
    - present in one -> not_required
    - missing data -> under_review
    - approved absence still compulsory
    """
    assert crud.calculate_follow_up_status(False, False) == "compulsory"
    assert crud.calculate_follow_up_status(True, False) == "not_required"
    assert crud.calculate_follow_up_status(False, True) == "not_required"
    assert crud.calculate_follow_up_status(True, True) == "not_required"
    assert crud.calculate_follow_up_status(None, False) == "under_review"
    assert crud.calculate_follow_up_status(False, None) == "under_review"
    assert crud.calculate_follow_up_status(None, None) == "under_review"

    # End-to-end check with DB and appearance records
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()

    cls = models.Class(name="CI-1", branch="CI", year=2)
    exam1 = models.MstExam(label="MST-1", class_id=cls.id)
    exam2 = models.MstExam(label="MST-2", class_id=cls.id)
    db.add_all([cls, exam1, exam2])
    db.commit()

    # Student 1: absent both -> compulsory
    st1 = models.Student(roll_number="VT001", name="Absent Both", class_id=cls.id)
    # Student 2: present in one -> not_required
    st2 = models.Student(roll_number="VT002", name="Present in MST-1", class_id=cls.id)
    # Student 3: missing data (no attempt in MST-2) -> under_review
    st3 = models.Student(roll_number="VT003", name="Missing MST-2", class_id=cls.id)
    # Student 4: approved absence note -> still compulsory
    st4 = models.Student(roll_number="VT004", name="Approved Absence", class_id=cls.id)
    db.add_all([st1, st2, st3, st4])
    db.commit()

    att1_1 = models.MstAttempt(mst_exam_id=exam1.id, student_id=st1.id, status="Absent")
    att1_2 = models.MstAttempt(mst_exam_id=exam2.id, student_id=st1.id, status="Absent")

    att2_1 = models.MstAttempt(mst_exam_id=exam1.id, student_id=st2.id, status="Present")
    att2_2 = models.MstAttempt(mst_exam_id=exam2.id, student_id=st2.id, status="Absent")

    att3_1 = models.MstAttempt(mst_exam_id=exam1.id, student_id=st3.id, status="Absent")
    # att3_2 omitted -> missing data

    att4_1 = models.MstAttempt(mst_exam_id=exam1.id, student_id=st4.id, status="Absent")
    att4_2 = models.MstAttempt(mst_exam_id=exam2.id, student_id=st4.id, status="Absent")

    db.add_all([att1_1, att1_2, att2_1, att2_2, att3_1, att4_1, att4_2])
    db.commit()

    res1 = crud.recalculate_follow_up(db, st1.id)
    res2 = crud.recalculate_follow_up(db, st2.id)
    res3 = crud.recalculate_follow_up(db, st3.id)
    res4 = crud.recalculate_follow_up(db, st4.id)

    assert res1.calculated_status == "compulsory"
    assert res1.final_status == "compulsory"

    assert res2.calculated_status == "not_required"
    assert res2.final_status == "not_required"

    assert res3.calculated_status == "under_review"
    assert res3.final_status == "under_review"

    # Even with human approved absence note on file, calculated_status remains compulsory
    assert res4.calculated_status == "compulsory"
    db.close()


def test_m5_clash_overlap_boundaries():
    """Clash overlap boundaries:
    Faculty busy 13:50-14:40
    -> 13:00-14:00 is Blocked (overlaps 13:50-14:00)
    -> 14:40-15:30 is Available (touches boundary at 14:40, no overlap)
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()

    cls = models.Class(name="CI-1", branch="CI", year=2)
    fac = models.Faculty(name="Prof. Boundary Test", abbreviation="PBT")
    db.add_all([cls, fac])
    db.commit()

    ver = models.TimetableVersion(class_id=cls.id, semester="III", session="Jul-Dec 2026", active=True)
    db.add(ver)
    db.commit()

    entry = models.FacultyTimetable(
        faculty_id=fac.id,
        day_of_week="MON",
        period_start="13:50",
        period_end="14:40",
        subject_code="CS301",
        class_id=cls.id,
        year=2,
        semester="III",
        timetable_version_id=ver.id,
    )
    db.add(entry)
    db.commit()

    # Slot 1: 13:00-14:00 -> MUST BE BLOCKED
    res_blocked = crud.check_faculty_availability(db, "MON", "13:00", "14:00")
    f_blocked = next(r for r in res_blocked if r.faculty_id == fac.id)
    assert f_blocked.status == "Blocked"
    assert "13:50–14:40" in f_blocked.reason or "13:50" in f_blocked.reason

    # Slot 2: 14:40-15:30 -> MUST BE AVAILABLE
    res_avail = crud.check_faculty_availability(db, "MON", "14:40", "15:30")
    f_avail = next(r for r in res_avail if r.faculty_id == fac.id)
    assert f_avail.status == "Available"

    db.close()
