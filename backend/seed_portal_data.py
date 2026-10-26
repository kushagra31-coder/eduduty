"""
Seed and normalize examination rooms, exams, eligibility, and duties.
"""
from database import engine, SessionLocal
import models
from sqlalchemy import text

def seed_portal_data():
    db = SessionLocal()
    try:
        # 1. Seed examination rooms (Rooms 340-349, 353)
        desired_rooms = [
            ("340", 60),
            ("341", 60),
            ("342", 60),
            ("343", 80),
            ("344", 60),
            ("345", 60),
            ("346", 60),
            ("347", 60),
            ("348", 60),
            ("349", 60),
            ("353", 60),
        ]
        desired_room_numbers = {room_no for room_no, _ in desired_rooms}
        
        # Remove any obsolete rooms (e.g. 101, 102, 201, 202, 301)
        for old_room in db.query(models.Room).all():
            if old_room.room_number not in desired_room_numbers:
                # Check if there are any seats or duties referencing this room
                db.query(models.Seat).filter_by(room_id=old_room.id).delete()
                db.query(models.InvigilationDuty).filter_by(room_id=old_room.id).delete()
                db.delete(old_room)
        db.commit()

        for room_no, cap in desired_rooms:
            r = db.query(models.Room).filter_by(room_number=room_no).first()
            if not r:
                db.add(models.Room(room_number=room_no, capacity=cap))
            else:
                r.capacity = cap
        db.commit()

        import datetime as _dt
        d1 = _dt.date(2026, 10, 21)
        d2 = _dt.date(2026, 11, 18)

        # 2. Ensure existing exams have date & slot if present
        e1 = db.query(models.MstExam).filter_by(id=1).first()
        if e1:
            if not e1.exam_date:
                e1.exam_date = d1
            e1.time_slot = e1.time_slot or "09:30-12:30"
            e1.label = e1.label or "MST-1"

            e2 = db.query(models.MstExam).filter_by(id=2).first()
            if e2:
                e2.label = e2.label or "MST-2"
                if not e2.exam_date:
                    e2.exam_date = d2
                e2.time_slot = e2.time_slot or "09:30-12:30"
            db.commit()

        # 3. Ensure all exams have eligibility records
        base_eligs = db.query(models.MstEligibility).filter_by(mst_exam_id=1).all()
        if base_eligs:
            all_exams = db.query(models.MstExam).all()
            for ex in all_exams:
                ex_elig_count = db.query(models.MstEligibility).filter_by(mst_exam_id=ex.id).count()
                if ex_elig_count == 0:
                    for b in base_eligs:
                        new_el = models.MstEligibility(
                            student_id=b.student_id,
                            mst_exam_id=ex.id,
                            overall_pct=b.overall_pct,
                            lowest_subject_pct=b.lowest_subject_pct,
                            status=b.status,
                            override=False,
                            override_reason=None,
                        )
                        db.add(new_el)
            db.commit()

        # 4. Generate initial seating for MST-1 in Room 343 and Room 101 so seating map is immediately viewable
        r343 = db.query(models.Room).filter_by(room_number="343").first()
        seats_count = db.query(models.Seat).filter_by(mst_exam_id=1).count()
        if seats_count == 0 and r343:
            # Generate seats for exam 1
            students = db.query(models.Student).filter_by(class_id=1, active=True).order_by(models.Student.roll_number).all()
            for idx in range(0, len(students), 2):
                s_left = students[idx]
                s_right = students[idx+1] if idx+1 < len(students) else None
                seat_no = f"S{idx//2 + 1:02d}"
                seat = models.Seat(
                    mst_exam_id=1,
                    room_id=r343.id,
                    seat_number=seat_no,
                    left_student=s_left.id if s_left else None,
                    right_student=s_right.id if s_right else None,
                )
                db.add(seat)
            db.commit()

        # 5. Populate follow_up_statuses if empty
        fu_count = db.query(models.FollowUpStatus).count()
        if fu_count == 0:
            import crud
            crud.recalculate_all_follow_ups(db)

        print("Portal data successfully seeded and normalized.")
    finally:
        db.close()

if __name__ == "__main__":
    seed_portal_data()
