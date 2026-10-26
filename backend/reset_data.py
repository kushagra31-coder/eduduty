"""
EduDuty Data Reset & Clean Class Initialization Utility
Wipes cached demo data (old CI21 students, dummy attendance, duplicate exams)
and establishes clean, distinguished classes: CI-1, CI-2, CY (Cyber Security) with standard rooms.
Leaves student and attendance tables completely clean and ready for user upload.
"""
from database import engine, SessionLocal
from sqlalchemy import text
import models
import datetime

def reset_to_fresh_state(preserve_rooms_and_faculty: bool = True):
    db = SessionLocal()
    try:
        print("Resetting EduDuty database to fresh state...")
        
        # 1. Clear transactional & student data
        db.query(models.FollowUpStatus).delete()
        db.query(models.MstAttempt).delete()
        db.query(models.Seat).delete()
        db.query(models.InvigilationDuty).delete()
        db.query(models.MstEligibility).delete()
        db.query(models.AttendanceRecord).delete()
        db.query(models.Student).delete()
        db.query(models.MstExam).delete()
        db.query(models.Class).delete()

        if not preserve_rooms_and_faculty:
            db.query(models.FacultyTimetable).delete()
            db.query(models.TimetableVersion).delete()
            db.query(models.Room).delete()
            db.query(models.Faculty).delete()
        db.commit()

        # 2. Seed clean, distinct classes: CI-1, CI-2, CY
        classes_data = [
            {"id": 1, "name": "CI-1", "branch": "Computer Science (CI-1)", "year": 2, "section": "A"},
            {"id": 2, "name": "CI-2", "branch": "Computer Science (CI-2)", "year": 2, "section": "B"},
            {"id": 3, "name": "CY", "branch": "Cyber Security", "year": 2, "section": "Cyber"},
        ]
        created_classes = []
        for c in classes_data:
            cls_obj = models.Class(
                id=c["id"],
                name=c["name"],
                branch=c["branch"],
                year=c["year"],
                section=c["section"]
            )
            db.add(cls_obj)
            created_classes.append(cls_obj)
        db.commit()

        # 3. Ensure all CSIT department faculty from 2nd year and department timetables exist with proper Prof./Dr. titles
        f8 = db.query(models.Faculty).filter_by(id=8, name='Vandana maam').first()
        if f8:
            db.delete(f8)
            db.commit()
        for f in db.query(models.Faculty).all():
            f.department = "CSIT"
            if not (f.name.startswith("Prof.") or f.name.startswith("Dr.")):
                f.name = "Prof. " + f.name.strip()
        db.commit()

        # 4. Ensure standard clean rooms exist without duplicates (Rooms 340-349, 353)
        standard_rooms = [
            {"room_number": "340", "capacity": 60},
            {"room_number": "341", "capacity": 60},
            {"room_number": "342", "capacity": 60},
            {"room_number": "343", "capacity": 80},
            {"room_number": "344", "capacity": 60},
            {"room_number": "345", "capacity": 60},
            {"room_number": "346", "capacity": 60},
            {"room_number": "347", "capacity": 60},
            {"room_number": "348", "capacity": 60},
            {"room_number": "349", "capacity": 60},
            {"room_number": "353", "capacity": 60},
        ]
        standard_room_numbers = {r["room_number"] for r in standard_rooms}

        # Remove any obsolete rooms not in standard set
        for old_room in db.query(models.Room).all():
            if old_room.room_number not in standard_room_numbers:
                db.query(models.Seat).filter_by(room_id=old_room.id).delete()
                db.query(models.InvigilationDuty).filter_by(room_id=old_room.id).delete()
                db.delete(old_room)
        db.commit()

        existing_rooms = {r.room_number: r for r in db.query(models.Room).all()}
        for r in standard_rooms:
            if r["room_number"] not in existing_rooms:
                db.add(models.Room(room_number=r["room_number"], capacity=r["capacity"]))
            else:
                existing_rooms[r["room_number"]].capacity = r["capacity"]
        db.commit()

        # 5. Log reset audit
        db.add(models.AuditLog(
            table_name="system",
            record_id=0,
            field_changed="system_reset",
            old_value="legacy_seed_data",
            new_value="Clean initialization with classes CI-1, CI-2, CY. Ready for user upload."
        ))
        db.commit()

        print("Data successfully reset!")
        print("Classes available: CI-1, CI-2, CY (Cyber Security)")
        print("Students count: 0 (Ready for user upload)")
        print("Attendance records: 0")
        return {
            "status": "success",
            "message": "System reset successfully. Initialized clean classes CI-1, CI-2, CY. All demo data wiped.",
            "classes": [c["name"] for c in classes_data],
            "students_count": 0,
            "attendance_count": 0
        }
    finally:
        db.close()

if __name__ == "__main__":
    result = reset_to_fresh_state()
    print(result)
