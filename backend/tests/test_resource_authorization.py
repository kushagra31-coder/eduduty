import time
import jwt
import pytest
from core import security
import models
from tests.conftest import TEST_JWT_SECRET


def make_token(uid: str, email: str, role: str) -> str:
    payload = {
        "sub": uid,
        "email": email,
        "user_metadata": {"role": role},
        "iss": "https://test.supabase.co/auth/v1",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def test_assigned_invigilator_can_mark_attendance(client, db):
    """An assigned invigilator can successfully mark attendance for a student in their room."""
    # Ensure duty assignment exists: Faculty 1 assigned to Room 1 for Exam 1
    duty = db.query(models.InvigilationDuty).filter_by(mst_exam_id=1, room_id=1).first()
    if not duty:
        duty = models.InvigilationDuty(id=10, mst_exam_id=1, room_id=1, faculty_id=1, status="Assigned")
        db.add(duty)
    else:
        duty.faculty_id = 1
        duty.status = "Assigned"
    
    # Ensure student 1 is seated in room 1
    seat = db.query(models.Seat).filter_by(mst_exam_id=1, room_id=1).first()
    if not seat:
        seat = models.Seat(id=10, room_id=1, mst_exam_id=1, seat_number="1", left_student=1)
        db.add(seat)

    db.commit()

    # User 3 is FACULTY with faculty_id=1
    token = make_token("uid-fac-789", "fac@eduduty.ac.in", "FACULTY")
    res = client.post(
        "/mst/attendance/mark",
        json={"mst_exam_id": 1, "student_id": 1, "status": "Present"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "Present"


def test_unassigned_invigilator_cannot_mark_attendance(client, db):
    """An invigilator NOT assigned to the room/exam is rejected with HTTP 403."""
    # Create Faculty 2 & User 6 (FACULTY role, faculty_id=2) without duty assignment
    f2 = db.query(models.Faculty).filter_by(id=2).first()
    if not f2:
        f2 = models.Faculty(id=2, name="Unassigned Faculty", abbreviation="UF", department="ECE")
        db.add(f2)
    u6 = db.query(models.User).filter_by(id=6).first()
    if not u6:
        u6 = models.User(id=6, supabase_uid="uid-fac-unassigned-202", name="Unassigned Faculty User", role="FACULTY", email="unassigned@eduduty.ac.in", faculty_id=2)
        db.add(u6)
    db.commit()

    token = make_token("uid-fac-unassigned-202", "unassigned@eduduty.ac.in", "FACULTY")
    res = client.post(
        "/mst/attendance/mark",
        json={"mst_exam_id": 1, "student_id": 1, "status": "Present"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 403
    data = res.json()
    assert data["detail"]["error"]["code"] == "FORBIDDEN"
    assert "not assigned to invigilate" in data["detail"]["error"]["message"].lower()


def test_invigilator_cannot_mark_attendance_in_unassigned_room(client, db):
    """An invigilator assigned to Room 1 cannot mark attendance for a student seated in Room 2."""
    # Create Room 2 and Student 2 seated in Room 2
    r2 = db.query(models.Room).filter_by(id=2).first()
    if not r2:
        r2 = models.Room(id=2, room_number="102", capacity=30)
        db.add(r2)
    s2 = db.query(models.Student).filter_by(id=2).first()
    if not s2:
        s2 = models.Student(id=2, roll_number="0827ECE211002", name="ECE Student", class_id=1, batch_number=1)
        db.add(s2)
    seat2 = db.query(models.Seat).filter_by(id=20).first()
    if not seat2:
        seat2 = models.Seat(id=20, room_id=2, mst_exam_id=1, seat_number="1", left_student=2)
        db.add(seat2)
    
    # Ensure Faculty 1 is ONLY assigned to Room 1 (not Room 2)
    db.query(models.InvigilationDuty).filter_by(mst_exam_id=1, room_id=2).delete()
    db.commit()

    # User 3 (Faculty 1) attempts to mark Student 2 in Room 2
    token = make_token("uid-fac-789", "fac@eduduty.ac.in", "FACULTY")
    res = client.post(
        "/mst/attendance/mark",
        json={"mst_exam_id": 1, "student_id": 2, "status": "Present"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 403
    assert "not assigned to invigilate room 2" in res.json()["detail"]["error"]["message"].lower()


def test_faculty_student_scope_access_granted(client, db):
    """Faculty member can export student record HTML for a student in a class they teach."""
    # Add FacultyTimetable entry for Faculty 1 and Class 1
    tt = db.query(models.FacultyTimetable).filter_by(faculty_id=1, class_id=1).first()
    if not tt:
        tt = models.FacultyTimetable(id=100, faculty_id=1, day_of_week="MON", period_start="10:30", period_end="11:20", class_id=1, year=3)
        db.add(tt)
        db.commit()

    token = make_token("uid-fac-789", "fac@eduduty.ac.in", "FACULTY")
    res = client.get("/pdf/student/0827CI211001/html", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert "Student Academic Record" in res.text


def test_faculty_student_scope_access_denied(client, db):
    """Faculty member attempting to access a student outside their class scope receives HTTP 403 IDOR rejection."""
    # Create Class 2 and Student 3 in Class 2
    c2 = db.query(models.Class).filter_by(id=2).first()
    if not c2:
        c2 = models.Class(id=2, name="ME-1", branch="ME", year=3)
        db.add(c2)
    s3 = db.query(models.Student).filter_by(id=3).first()
    if not s3:
        s3 = models.Student(id=3, roll_number="0827ME211003", name="Mechanical Student", class_id=2, batch_number=1)
        db.add(s3)
    db.commit()

    # Faculty 1 has no timetable or attendance records for Class 2 / Student 3
    token = make_token("uid-fac-789", "fac@eduduty.ac.in", "FACULTY")
    res = client.get("/pdf/student/0827ME211003/html", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
    data = res.json()
    assert data["detail"]["error"]["code"] == "FORBIDDEN"
    assert "outside your assigned academic class scope" in data["detail"]["error"]["message"].lower()


def test_administrator_can_override_and_export_any_scope(client, db):
    """EXAM_COORDINATOR / ADMIN / SUPER_ADMIN retain global resource authorization."""
    token = make_token("uid-coord-456", "coord@eduduty.ac.in", "EXAM_COORDINATOR")
    # Coordinator can mark attendance for any room/student
    res_mark = client.post(
        "/mst/attendance/mark",
        json={"mst_exam_id": 1, "student_id": 1, "status": "Present"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_mark.status_code == 200

    # Coordinator can export any student HTML
    res_html = client.get("/pdf/student/0827CI211001/html", headers={"Authorization": f"Bearer {token}"})
    assert res_html.status_code == 200


def test_ai_write_exact_roll_matching_required(client):
    """AI write operation rejects partial or non-matching roll number substring search."""
    token = make_token("uid-coord-456", "coord@eduduty.ac.in", "EXAM_COORDINATOR")
    # Attempting to override eligibility with partial roll "0827" instead of exact "0827CI211001"
    res = client.post(
        "/ai/confirm-write",
        json={
            "op_json": {
                "operation": "override_eligibility",
                "roll_number": "0827",
                "mst_label": "MST-1",
                "reason": "Test exact roll match requirement"
            }
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 400
    assert "not found" in res.json()["detail"].lower()


def test_ai_write_duty_assignment_conflict_rejected(client, db):
    """AI duty assignment is rejected if faculty member has a timetable teaching conflict."""
    # Ensure Faculty 1 has a timetable entry during MON 09:00-12:00
    tt = db.query(models.FacultyTimetable).filter_by(faculty_id=1, day_of_week="MON").first()
    if not tt:
        tt = models.FacultyTimetable(id=101, faculty_id=1, day_of_week="MON", period_start="09:00", period_end="12:00", class_id=1, year=3)
        db.add(tt)
    
    # Set Exam 1 to Monday
    import datetime
    exam1 = db.query(models.MstExam).filter_by(id=1).first()
    if exam1:
        exam1.exam_date = datetime.date(2026, 10, 12)  # Monday
        exam1.time_slot = "09:00-12:00"
    
    # Ensure duty slot exists
    d = db.query(models.InvigilationDuty).filter_by(mst_exam_id=1, room_id=1).first()
    if not d:
        d = models.InvigilationDuty(id=1, mst_exam_id=1, room_id=1, status="Unfilled")
        db.add(d)
    else:
        d.status = "Unfilled"
        d.faculty_id = None
    db.commit()

    token = make_token("uid-coord-456", "coord@eduduty.ac.in", "EXAM_COORDINATOR")
    res = client.post(
        "/ai/confirm-write",
        json={
            "op_json": {
                "operation": "assign_duty",
                "faculty_name": "Prof. Test Faculty",
                "mst_label": "MST-1",
                "room_number": "101"
            }
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 400
    assert "conflict" in res.json()["detail"].lower()
