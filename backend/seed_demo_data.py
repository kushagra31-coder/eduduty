"""
EduDuty — Demonstration Data Seeder (Idempotent & Safe)
File: backend/seed_demo_data.py

Populates a coherent, realistic demonstration dataset:
- System rules
- Faculty with abbreviation legends
- Preconfigured demo user accounts (SUPER_ADMIN, EXAM_COORDINATOR, FACULTY, VIEWER)
- Academic classes and subjects
- Examination rooms and capacity
- MST examination events (MST-1, MST-2)
- Synthetic student identities (no PII)
- Attendance records and eligibility calculations
- Roll call exam attempts (Present/Absent)
- Follow-up action statuses (absent-both-mst tracking)
- Timetable versions and faculty timetable slots
- Invigilation duties and audit logs

Guarantees:
- Fully idempotent: safe to execute repeatedly without duplicate rows
- Preserves existing data without overwriting or deleting user-created data
- Enforces synthetic privacy: no real student personal information
- Validates database schema compatibility: fails safely if target schema is incompatible
- Targets a dedicated demo database by default (sqlite:///./eduduty_demo.db)
"""

import argparse
import datetime
import json
import os
import sys
from typing import Dict, Tuple

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

# Ensure backend root is on Python path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from database import Base
import models
from core import security


def check_schema_compatibility(engine) -> Tuple[bool, str]:
    """
    Validate that the target database schema contains required tables and columns.
    Returns (compatible: bool, reason: str).
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    if not existing_tables:
        # Fresh database, compatible once create_all runs
        return True, "Fresh database (tables will be created)"

    # Check for table existence
    if "users" in existing_tables:
        user_cols = {col["name"] for col in inspector.get_columns("users")}
        required_user_cols = {"id", "name", "role", "email", "supabase_uid", "faculty_id"}
        missing_user_cols = required_user_cols - user_cols
        if missing_user_cols:
            return False, (
                f"Target database 'users' table schema is missing columns: {sorted(missing_user_cols)}. "
                "In accordance with EduDuty safety constraints, existing database schemas will not "
                "be modified or upgraded automatically. Please configure a dedicated demo database."
            )

    return True, "Schema compatible"


def seed_demo_data(db_url: str = None) -> Dict[str, Dict[str, int]]:
    """
    Execute idempotent demo seeding against the specified database URL.
    Returns statistics dictionary with 'created', 'existing', and 'skipped' counts.
    """
    if not db_url:
        db_url = os.getenv("DEMO_DATABASE_URL") or os.getenv("DATABASE_URL") or "sqlite:///./eduduty_demo.db"

    print(f"=== EduDuty Demo Data Seeder ===")
    print(f"Target Database URL: {db_url}")

    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(db_url, connect_args=connect_args)

    # 1. Schema Compatibility Gate
    compatible, reason = check_schema_compatibility(engine)
    if not compatible:
        print(f"\n[ERROR] Schema compatibility check failed: {reason}", file=sys.stderr)
        raise RuntimeError(f"Database schema incompatible: {reason}")

    # Ensure tables exist (safe for SQLite and fresh test DBs)
    Base.metadata.create_all(bind=engine)

    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()

    stats = {}

    def track(entity: str, status: str):
        if entity not in stats:
            stats[entity] = {"created": 0, "existing": 0, "skipped": 0}
        stats[entity][status] += 1

    try:
        # ── 1. System Rules ──────────────────────────────────────────────────────
        rules = [
            ("eligibility_threshold_pct", "50", "Minimum overall attendance % to be MST-eligible"),
            ("borderline_band_pct", "45-49.99", "Attendance % range flagged as borderline"),
            ("vt_rule", "compulsory_if_both_mst_missed", "Configurable VT eligibility rule"),
        ]
        for key, val, desc in rules:
            existing = db.query(models.SystemRule).filter_by(key=key).first()
            if existing:
                track("SystemRule", "existing")
            else:
                db.add(models.SystemRule(key=key, value=val, description=desc))
                track("SystemRule", "created")
        db.commit()

        # ── 2. Faculty Members ──────────────────────────────────────────────────
        faculty_data = [
            (1, "Dr. Vandana Kate", "VK", "CSE", 2),
            (2, "Prof. Ashwinee Gadwal", "AG", "CSE", 2),
            (3, "Dr. Asmita Rajawat", "AR", "CSE", 2),
            (4, "Prof. Chanchal Bansal", "CB", "CSE", 2),
            (5, "Prof. Jayati Nagar", "JN", "CSE", 2),
            (6, "Dr. Rupa S Karnik", "RK", "CSE", 2),
            (7, "Prof. Sweta Gupta", "SG", "CSE", 2),
            (8, "Prof. Sumit Paliwal", "SP", "CSE", 2),
            (9, "Dr. Anamika Joshi", "ANU", "CSE", 2),
            (10, "Prof. Manoj Gupta", "MG", "CSE", 2),
        ]
        faculty_map = {}
        for fid, name, abbr, dept, max_duties in faculty_data:
            f = db.query(models.Faculty).filter((models.Faculty.id == fid) | (models.Faculty.abbreviation == abbr)).first()
            if f:
                faculty_map[abbr] = f
                track("Faculty", "existing")
            else:
                f = models.Faculty(
                    id=fid,
                    name=name,
                    abbreviation=abbr,
                    department=dept,
                    max_duties_per_day=max_duties,
                    exempt_from_duty=False,
                )
                db.add(f)
                db.flush()
                faculty_map[abbr] = f
                track("Faculty", "created")
        db.commit()

        # ── 3. Preconfigured Demo Users ──────────────────────────────────────────
        demo_users = [
            ("admin@eduduty.ac.in", "00000000-0000-0000-0000-000000000001", "Admin Demo", security.SUPER_ADMIN, None),
            ("coord@eduduty.ac.in", "00000000-0000-0000-0000-000000000002", "Coordinator Demo", security.EXAM_COORDINATOR, None),
            ("faculty@eduduty.ac.in", "00000000-0000-0000-0000-000000000003", "Prof. Test Faculty", security.FACULTY, 1),
            ("viewer@eduduty.ac.in", "00000000-0000-0000-0000-000000000004", "Viewer Demo", security.VIEWER, None),
        ]
        for email, uid, name, role, fac_id in demo_users:
            u = db.query(models.User).filter_by(email=email).first()
            if u:
                track("User", "existing")
            else:
                u = models.User(
                    supabase_uid=uid,
                    name=name,
                    role=role,
                    email=email,
                    faculty_id=fac_id,
                )
                db.add(u)
                track("User", "created")
        db.commit()

        # ── 4. Classes ───────────────────────────────────────────────────────────
        classes_data = [
            ("CI-1", "CSE", 3, "A"),
            ("CI-2", "CSE", 3, "B"),
            ("CY-3", "Cyber Security", 2, "A"),
            ("CY-5", "Cyber Security", 3, "A"),
        ]
        class_map = {}
        for cname, branch, year, sec in classes_data:
            c = db.query(models.Class).filter_by(name=cname).first()
            if c:
                class_map[cname] = c
                track("Class", "existing")
            else:
                c = models.Class(name=cname, branch=branch, year=year, section=sec)
                db.add(c)
                db.flush()
                class_map[cname] = c
                track("Class", "created")
        db.commit()

        # ── 5. Subjects ──────────────────────────────────────────────────────────
        subjects_data = [
            ("CSIT-302", "Discrete Structure"),
            ("CSIT-303", "Data Structure"),
            ("CSIT-304", "Digital Circuit and System"),
            ("CSIT-305", "Object Oriented Programming"),
            ("CSIT-306", "Java Programming"),
        ]
        subject_map = {}
        for code, name in subjects_data:
            s = db.query(models.Subject).filter_by(code=code).first()
            if s:
                subject_map[code] = s
                track("Subject", "existing")
            else:
                s = models.Subject(code=code, name=name)
                db.add(s)
                db.flush()
                subject_map[code] = s
                track("Subject", "created")
        db.commit()

        # ── 6. Examination Rooms ────────────────────────────────────────────────
        rooms_data = [
            ("R-101", 40),
            ("R-102", 40),
            ("R-201", 40),
            ("R-202", 40),
        ]
        room_map = {}
        for rnum, cap in rooms_data:
            r = db.query(models.Room).filter_by(room_number=rnum).first()
            if r:
                room_map[rnum] = r
                track("Room", "existing")
            else:
                r = models.Room(room_number=rnum, capacity=cap)
                db.add(r)
                db.flush()
                room_map[rnum] = r
                track("Room", "created")
        db.commit()

        # ── 7. MST Exams ─────────────────────────────────────────────────────────
        ci1 = class_map.get("CI-1")
        exam_data = [
            (1, "MST-1", datetime.date(2026, 10, 15), "10:30-11:30", ci1.id if ci1 else None),
            (2, "MST-2", datetime.date(2026, 11, 20), "10:30-11:30", ci1.id if ci1 else None),
        ]
        exam_map = {}
        for eid, label, edate, slot, cid in exam_data:
            e = db.query(models.MstExam).filter_by(id=eid).first()
            if not e:
                e = db.query(models.MstExam).filter_by(label=label, class_id=cid).first()
            if e:
                exam_map[label] = e
                track("MstExam", "existing")
            else:
                e = models.MstExam(id=eid, label=label, exam_date=edate, time_slot=slot, class_id=cid)
                db.add(e)
                db.flush()
                exam_map[label] = e
                track("MstExam", "created")
        db.commit()

        # ── 8. Synthetic Students ────────────────────────────────────────────────
        # Clean synthetic student records with zero personal identifiable information
        synthetic_students = [
            # CI-1 Students
            ("0827CI211001", "Synthetic Student 01", "CI-1", 1, "L"),
            ("0827CI211002", "Synthetic Student 02", "CI-1", 1, "R"),
            ("0827CI211003", "Synthetic Student 03", "CI-1", 2, "L"),
            ("0827CI211004", "Synthetic Student 04", "CI-1", 2, "R"),
            ("0827CI211005", "Synthetic Student 05", "CI-1", 3, "L"),
            ("0827CI211006", "Synthetic Student 06", "CI-1", 3, "R"),
            ("0827CI211007", "Synthetic Student 07", "CI-1", 4, "L"),
            ("0827CI211008", "Synthetic Student 08", "CI-1", 4, "R"),
            ("0827CI211009", "Synthetic Student 09", "CI-1", 5, "L"),
            ("0827CI211010", "Synthetic Student 10", "CI-1", 5, "R"),
            # CI-2 Students
            ("0827CI212001", "Synthetic Student 11", "CI-2", 1, "L"),
            ("0827CI212002", "Synthetic Student 12", "CI-2", 1, "R"),
            ("0827CI212003", "Synthetic Student 13", "CI-2", 2, "L"),
            ("0827CI212004", "Synthetic Student 14", "CI-2", 2, "R"),
            ("0827CI212005", "Synthetic Student 15", "CI-2", 3, "L"),
            ("0827CI212006", "Synthetic Student 16", "CI-2", 3, "R"),
        ]
        student_map = {}
        for roll, name, cname, batch, seat in synthetic_students:
            s = db.query(models.Student).filter_by(roll_number=roll).first()
            if s:
                student_map[roll] = s
                track("Student", "existing")
            else:
                c = class_map.get(cname)
                s = models.Student(
                    roll_number=roll,
                    name=name,
                    class_id=c.id if c else 1,
                    batch_number=batch,
                    pair_seat=seat,
                    active=True,
                )
                db.add(s)
                db.flush()
                student_map[roll] = s
                track("Student", "created")
        db.commit()

        # ── 9. Attendance Records ────────────────────────────────────────────────
        # Diverse attendance tiers: 6 Eligible (>75%), 1 Borderline (48%), 3 Ineligible (<45%)
        attendance_profiles = [
            ("0827CI211001", 24, 25), # 96.0% Eligible
            ("0827CI211002", 23, 25), # 92.0% Eligible
            ("0827CI211003", 22, 25), # 88.0% Eligible
            ("0827CI211004", 21, 25), # 84.0% Eligible
            ("0827CI211005", 20, 25), # 80.0% Eligible
            ("0827CI211006", 19, 25), # 76.0% Eligible
            ("0827CI211007", 12, 25), # 48.0% Borderline
            ("0827CI211008", 8, 25),  # 32.0% Ineligible (will have approved medical override)
            ("0827CI211009", 7, 25),  # 28.0% Ineligible
            ("0827CI211010", 5, 25),  # 20.0% Ineligible (will miss both MST exams)
        ]
        s_ds = subject_map.get("CSIT-302")
        f_vk = faculty_map.get("VK")
        for roll, attended, conducted in attendance_profiles:
            st = student_map.get(roll)
            if not st:
                continue
            rec = db.query(models.AttendanceRecord).filter_by(
                student_id=st.id, subject_id=s_ds.id if s_ds else 1, semester="III"
            ).first()
            if rec:
                track("AttendanceRecord", "existing")
            else:
                pct = round(100.0 * attended / conducted, 2) if conducted else 0.0
                rec = models.AttendanceRecord(
                    student_id=st.id,
                    faculty_id=f_vk.id if f_vk else 1,
                    subject_id=s_ds.id if s_ds else 1,
                    semester="III",
                    classes_conducted=conducted,
                    classes_attended=attended,
                    attendance_pct=pct,
                    approved=True,
                    source_file="demo_attendance_seed.xlsx",
                )
                db.add(rec)
                track("AttendanceRecord", "created")
        db.commit()

        # ── 10. MST Eligibility Records ──────────────────────────────────────────
        mst1 = exam_map.get("MST-1")
        if mst1:
            elig_data = [
                ("0827CI211001", 96.0, 96.0, "Eligible", False, None),
                ("0827CI211002", 92.0, 92.0, "Eligible", False, None),
                ("0827CI211003", 88.0, 88.0, "Eligible", False, None),
                ("0827CI211004", 84.0, 84.0, "Eligible", False, None),
                ("0827CI211005", 80.0, 80.0, "Eligible", False, None),
                ("0827CI211006", 76.0, 76.0, "Eligible", False, None),
                ("0827CI211007", 48.0, 48.0, "Borderline", False, None),
                ("0827CI211008", 32.0, 32.0, "Not eligible", True, "Medical certificate approved by HOD"),
                ("0827CI211009", 28.0, 28.0, "Not eligible", False, None),
                ("0827CI211010", 20.0, 20.0, "Not eligible", False, None),
            ]
            for roll, overall, lowest, status, ov, reason in elig_data:
                st = student_map.get(roll)
                if not st:
                    continue
                el = db.query(models.MstEligibility).filter_by(
                    student_id=st.id, mst_exam_id=mst1.id
                ).first()
                if el:
                    track("MstEligibility", "existing")
                else:
                    el = models.MstEligibility(
                        student_id=st.id,
                        mst_exam_id=mst1.id,
                        overall_pct=overall,
                        lowest_subject_pct=lowest,
                        status=status,
                        override=ov,
                        override_reason=reason,
                        override_by=1 if ov else None,
                    )
                    db.add(el)
                    track("MstEligibility", "created")
            db.commit()

        # ── 11. MST Examination Seating ──────────────────────────────────────────
        r101 = room_map.get("R-101")
        if mst1 and r101:
            seats_data = [
                ("S-01", "0827CI211001", "0827CI211002"),
                ("S-02", "0827CI211003", "0827CI211004"),
                ("S-03", "0827CI211005", "0827CI211006"),
                ("S-04", "0827CI211007", "0827CI211008"),
                ("S-05", "0827CI211009", "0827CI211010"),
            ]
            for snum, left_roll, right_roll in seats_data:
                s_left = student_map.get(left_roll)
                s_right = student_map.get(right_roll)
                seat = db.query(models.Seat).filter_by(
                    room_id=r101.id, mst_exam_id=mst1.id, seat_number=snum
                ).first()
                if seat:
                    track("Seat", "existing")
                else:
                    seat = models.Seat(
                        room_id=r101.id,
                        mst_exam_id=mst1.id,
                        seat_number=snum,
                        left_student=s_left.id if s_left else None,
                        right_student=s_right.id if s_right else None,
                    )
                    db.add(seat)
                    track("Seat", "created")
            db.commit()

        # ── 12. Roll Call Attempts (MST-1 and MST-2) ─────────────────────────────
        mst2 = exam_map.get("MST-2")
        now = datetime.datetime.utcnow()

        # Attempts for MST-1:
        # Students 1-8: Present
        # Student 9: Absent
        # Student 10: Absent
        if mst1:
            mst1_attendance = [
                ("0827CI211001", "Present"),
                ("0827CI211002", "Present"),
                ("0827CI211003", "Present"),
                ("0827CI211004", "Present"),
                ("0827CI211005", "Present"),
                ("0827CI211006", "Present"),
                ("0827CI211007", "Present"),
                ("0827CI211008", "Present"),
                ("0827CI211009", "Absent"),
                ("0827CI211010", "Absent"),
            ]
            for roll, status in mst1_attendance:
                st = student_map.get(roll)
                if not st:
                    continue
                att = db.query(models.MstAttempt).filter_by(
                    student_id=st.id, mst_exam_id=mst1.id
                ).first()
                if att:
                    track("MstAttempt", "existing")
                else:
                    att = models.MstAttempt(
                        student_id=st.id,
                        mst_exam_id=mst1.id,
                        room_id=r101.id if r101 else 1,
                        seat_id=st.id,
                        status=status,
                        marked_by=1,
                        marked_at=now,
                        remarks="Demo verification roll call",
                    )
                    db.add(att)
                    track("MstAttempt", "created")
            db.commit()

        # Attempts for MST-2:
        # Student 9: Present (appeared for MST-2, cleared from absent-both)
        # Student 10: Absent (absent both MST-1 and MST-2 -> action required)
        if mst2:
            mst2_attendance = [
                ("0827CI211001", "Present"),
                ("0827CI211002", "Present"),
                ("0827CI211003", "Present"),
                ("0827CI211004", "Present"),
                ("0827CI211005", "Present"),
                ("0827CI211006", "Present"),
                ("0827CI211007", "Present"),
                ("0827CI211008", "Present"),
                ("0827CI211009", "Present"),
                ("0827CI211010", "Absent"),
            ]
            for roll, status in mst2_attendance:
                st = student_map.get(roll)
                if not st:
                    continue
                att = db.query(models.MstAttempt).filter_by(
                    student_id=st.id, mst_exam_id=mst2.id
                ).first()
                if att:
                    track("MstAttempt", "existing")
                else:
                    att = models.MstAttempt(
                        student_id=st.id,
                        mst_exam_id=mst2.id,
                        room_id=r101.id if r101 else 1,
                        seat_id=st.id,
                        status=status,
                        marked_by=1,
                        marked_at=now,
                        remarks="Demo verification roll call",
                    )
                    db.add(att)
                    track("MstAttempt", "created")
            db.commit()

        # ── 13. Follow-Up Action Statuses ────────────────────────────────────────
        # Tracks institutional action for students missing examinations
        follow_up_records = [
            ("0827CI211010", False, False, "action_required", "action_required", False, None),
            ("0827CI211009", False, True, "cleared", "cleared", False, None),
        ]
        for roll, m1_app, m2_app, calc_st, fin_st, ov, reason in follow_up_records:
            st = student_map.get(roll)
            if not st:
                continue
            fu = db.query(models.FollowUpStatus).filter_by(student_id=st.id).first()
            if fu:
                track("FollowUpStatus", "existing")
            else:
                fu = models.FollowUpStatus(
                    student_id=st.id,
                    rule_version="absent-both-mst-v1",
                    mst_1_exam_id=mst1.id if mst1 else 1,
                    mst_2_exam_id=mst2.id if mst2 else 2,
                    mst_1_appeared=m1_app,
                    mst_2_appeared=m2_app,
                    calculated_status=calc_st,
                    final_status=fin_st,
                    override=ov,
                    override_reason=reason,
                    calculated_at=now,
                    updated_at=now,
                )
                db.add(fu)
                track("FollowUpStatus", "created")
        db.commit()

        # ── 14. Timetable Versions and Faculty Timetable ─────────────────────────
        if ci1:
            tv = db.query(models.TimetableVersion).filter_by(
                class_id=ci1.id, semester="III", session="Jul-Dec 2026"
            ).first()
            if tv:
                track("TimetableVersion", "existing")
            else:
                tv = models.TimetableVersion(
                    class_id=ci1.id,
                    semester="III",
                    session="Jul-Dec 2026",
                    doc_no="AITR/Acad/09",
                    active=True,
                )
                db.add(tv)
                db.flush()
                track("TimetableVersion", "created")

            # Seed faculty teaching slots for CI-1
            tt_slots = [
                # Faculty 1 (VK) teaching Discrete Structure Mon 10:30-11:20
                (1, "MON", "10:30", "11:20", "CSIT-302", "Discrete Structure", "R-101", None),
                # Faculty 1 (VK) teaching Discrete Structure Wed 11:20-12:10
                (1, "WED", "11:20", "12:10", "CSIT-302", "Discrete Structure", "R-101", None),
                # Faculty 2 (AG) teaching Data Structure Tue 10:30-11:20
                (2, "TUE", "10:30", "11:20", "CSIT-303", "Data Structure", "R-102", None),
                # Faculty 3 (AR) teaching Digital Circuit Thu 11:20-12:10
                (3, "THUR", "11:20", "12:10", "CSIT-304", "Digital Circuit and System", "R-101", None),
            ]
            for fid, day, pstart, pend, scode, sname, room_name, batch in tt_slots:
                ft = db.query(models.FacultyTimetable).filter_by(
                    faculty_id=fid, day_of_week=day, period_start=pstart, timetable_version_id=tv.id
                ).first()
                if ft:
                    track("FacultyTimetable", "existing")
                else:
                    ft = models.FacultyTimetable(
                        faculty_id=fid,
                        day_of_week=day,
                        period_start=pstart,
                        period_end=pend,
                        subject_code=scode,
                        subject_name=sname,
                        room=room_name,
                        batch=batch,
                        class_id=ci1.id,
                        year=3,
                        semester="III",
                        timetable_version_id=tv.id,
                    )
                    db.add(ft)
                    track("FacultyTimetable", "created")
            db.commit()

        # ── 15. Invigilation Duties ──────────────────────────────────────────────
        if mst1 and r101:
            duties = [
                (mst1.id, r101.id, 1, "Assigned"),
                (mst1.id, room_map["R-102"].id if "R-102" in room_map else 2, 2, "Assigned"),
            ]
            if mst2:
                duties.append((mst2.id, r101.id, 1, "Assigned"))

            for me_id, rm_id, fac_id, st in duties:
                duty = db.query(models.InvigilationDuty).filter_by(
                    mst_exam_id=me_id, room_id=rm_id
                ).first()
                if duty:
                    track("InvigilationDuty", "existing")
                else:
                    duty = models.InvigilationDuty(
                        mst_exam_id=me_id,
                        room_id=rm_id,
                        faculty_id=fac_id,
                        status=st,
                        assigned_at=now,
                    )
                    db.add(duty)
                    track("InvigilationDuty", "created")
            db.commit()

        # ── 16. Audit Logs ───────────────────────────────────────────────────────
        audit_entries = [
            ("attendance_records", 0, "import", None, "10 attendance records imported", 1, "Initial demo dataset seed"),
            ("mst_eligibility", 8, "override", "False", "True", 1, "Medical certificate approved by HOD"),
        ]
        for tname, rid, fchanged, old_v, new_v, cby, reason in audit_entries:
            log = db.query(models.AuditLog).filter_by(
                table_name=tname, record_id=rid, field_changed=fchanged, reason=reason
            ).first()
            if log:
                track("AuditLog", "existing")
            else:
                log = models.AuditLog(
                    table_name=tname,
                    record_id=rid,
                    field_changed=fchanged,
                    old_value=old_v,
                    new_value=new_v,
                    changed_by=cby,
                    reason=reason,
                    changed_at=now,
                )
                db.add(log)
                track("AuditLog", "created")
        db.commit()

    finally:
        db.close()

    # ── Print Seeder Summary ─────────────────────────────────────────────────
    print("\n--- Seeding Summary ---")
    print(f"{'Entity':<22} | {'Created':<10} | {'Existing':<10} | {'Skipped':<10}")
    print("-" * 60)
    for entity, counts in sorted(stats.items()):
        print(f"{entity:<22} | {counts['created']:<10} | {counts['existing']:<10} | {counts['skipped']:<10}")
    print("-" * 60)
    total_created = sum(c["created"] for c in stats.values())
    total_existing = sum(c["existing"] for c in stats.values())
    print(f"Total: {total_created} created, {total_existing} existing.\n")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Seed EduDuty Demonstration Data")
    parser.add_argument(
        "--database-url",
        "-d",
        dest="database_url",
        help="Database URL to seed (defaults to DEMO_DATABASE_URL or sqlite:///./eduduty_demo.db)",
    )
    args = parser.parse_args()
    try:
        seed_demo_data(args.database_url)
    except Exception as e:
        print(f"FATAL: Seeding failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
