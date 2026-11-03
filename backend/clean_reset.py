"""
Clean slate reset for EduDuty.
- Wipes ALL transactional data (students, attendance, exams, seats, duties, follow-ups, eligibility)
- Sets up 6 correct classes: CI-1, CI-2, CY for Year 2 AND Year 3
- Sets up 6 correct exam rooms: 335, 336, 346, 347, 348, 349, each with capacity 80 (75-80 students, 2 per desk)
- Preserves faculty and their timetables
- Does NOT create any mock MST exams — portal starts fresh, ready for real data upload
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal
import models

def full_clean_reset():
    db = SessionLocal()
    try:
        print("=== EduDuty Clean Reset ===")

        # ── 1. Wipe all transactional / student data ─────────────────────────
        print("Wiping transactional data...")
        db.query(models.FollowUpStatus).delete()
        db.query(models.MstAttempt).delete()
        db.query(models.Seat).delete()
        db.query(models.InvigilationDuty).delete()
        db.query(models.DutyReplacement).delete()
        db.query(models.MstEligibility).delete()
        db.query(models.AttendanceRecord).delete()
        db.query(models.Student).delete()
        db.query(models.MstExam).delete()
        db.query(models.Class).delete()
        db.query(models.AuditLog).delete()
        db.commit()

        # ── 2. Wipe & rebuild rooms ──────────────────────────────────────────
        print("Rebuilding rooms: 335, 336, 346, 347, 348, 349 @ capacity 80...")
        db.query(models.Room).delete()
        db.commit()

        # Only the 6 actual classrooms (labs are excluded — they're not exam venues)
        classroom_rooms = [
            {"room_number": "335", "capacity": 80},
            {"room_number": "336", "capacity": 80},
            {"room_number": "346", "capacity": 80},
            {"room_number": "347", "capacity": 80},
            {"room_number": "348", "capacity": 80},
            {"room_number": "349", "capacity": 80},
        ]
        for r in classroom_rooms:
            db.add(models.Room(room_number=r["room_number"], capacity=r["capacity"]))
        db.commit()
        print(f"  Rooms created: {[r['room_number'] for r in classroom_rooms]}")

        # ── 3. Seed classes ──────────────────────────────────────────────────
        print("Seeding classes: CI-1, CI-2, CY for Year 2 and Year 3...")
        classes_data = [
            # Year 2
            {"name": "CI-1",       "branch": "Computer Science & IT (CI-1)", "year": 2, "section": "A"},
            {"name": "CI-2",       "branch": "Computer Science & IT (CI-2)", "year": 2, "section": "B"},
            {"name": "CY",         "branch": "Cyber Security",               "year": 2, "section": "CY"},
            # Year 3
            {"name": "CI-1 (Y3)", "branch": "Computer Science & IT (CI-1)", "year": 3, "section": "A"},
            {"name": "CI-2 (Y3)", "branch": "Computer Science & IT (CI-2)", "year": 3, "section": "B"},
            {"name": "CY (Y3)",   "branch": "Cyber Security",               "year": 3, "section": "CY"},
        ]
        for c in classes_data:
            db.add(models.Class(
                name=c["name"],
                branch=c["branch"],
                year=c["year"],
                section=c["section"],
            ))
        db.commit()
        created = db.query(models.Class).order_by(models.Class.year, models.Class.name).all()
        for c in created:
            print(f"  Class id={c.id}: {c.name}  Year {c.year}")

        # ── 4. Log the reset ─────────────────────────────────────────────────
        db.add(models.AuditLog(
            table_name="system",
            record_id=0,
            field_changed="clean_reset",
            old_value="junk_seed_data",
            new_value=(
                "Clean reset 2026-11-02. "
                "Classes: CI-1, CI-2, CY (Yr2 & Yr3). "
                "Rooms: 335, 336, 346, 347, 348, 349 @ cap 80. "
                "No mock students/exams. Ready for real data."
            ),
        ))
        db.commit()

        print("\n=== Reset complete ===")
        print("Students: 0  |  Attendance: 0  |  MST Exams: 0")
        print("Rooms: 335, 336, 346, 347, 348, 349  (capacity 80 each)")
        print("Classes: CI-1, CI-2, CY  (Year 2)  +  CI-1 (Y3), CI-2 (Y3), CY (Y3)  (Year 3)")
        print("Faculty & timetables: preserved as-is")
        print("\nPortal is clean and ready for real attendance upload and MST setup.")

    finally:
        db.close()

if __name__ == "__main__":
    full_clean_reset()

