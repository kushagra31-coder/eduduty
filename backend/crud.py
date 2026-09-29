from sqlalchemy.orm import Session
import models, schemas
from decimal import Decimal

def get_classes(db: Session):
    return db.query(models.Class).all()

def get_class_by_name(db: Session, name: str):
    return db.query(models.Class).filter(models.Class.name == name).first()

def get_student_by_roll(db: Session, roll_number: str):
    return db.query(models.Student).filter(models.Student.roll_number == roll_number).first()

def create_attendance_record(db: Session, record: schemas.AttendanceRecordBase):
    db_record = models.AttendanceRecord(**record.dict())
    db.add(db_record)
    db.commit()
    db.refresh(db_record)
    return db_record

def get_mst_eligibility(db: Session, mst_exam_id: int):
    # Join MstEligibility and Student
    records = db.query(
        models.MstEligibility.id,
        models.MstEligibility.student_id,
        models.Student.roll_number,
        models.Student.name,
        models.MstEligibility.mst_exam_id,
        models.MstEligibility.overall_pct,
        models.MstEligibility.lowest_subject_pct,
        models.MstEligibility.status,
        models.MstEligibility.override,
        models.MstEligibility.override_reason
    ).join(models.Student, models.MstEligibility.student_id == models.Student.id)\
     .filter(models.MstEligibility.mst_exam_id == mst_exam_id).all()
    
    return [schemas.MstEligibilityDisplay(
        id=r.id,
        student_id=r.student_id,
        roll_number=r.roll_number,
        name=r.name,
        mst_exam_id=r.mst_exam_id,
        overall_pct=r.overall_pct,
        lowest_subject_pct=r.lowest_subject_pct,
        status=r.status,
        override=r.override,
        override_reason=r.override_reason
    ) for r in records]

def update_eligibility_override(db: Session, eligibility_id: int, override: bool, reason: str, user_id: int = None):
    db_record = db.query(models.MstEligibility).filter(models.MstEligibility.id == eligibility_id).first()
    if db_record:
        db_record.override = override
        db_record.override_reason = reason
        db_record.override_by = user_id
        
        # Log to audit (simplified)
        log = models.AuditLog(
            table_name="mst_eligibility",
            record_id=eligibility_id,
            field_changed="override",
            old_value=str(not override),
            new_value=str(override),
            changed_by=user_id,
            reason=reason
        )
        db.add(log)
        
        db.commit()
        db.refresh(db_record)
    return db_record

def compute_eligibility_for_student(db: Session, student_id: int, mst_exam_id: int):
    # Dummy logic to calculate eligibility from attendance_records
    records = db.query(models.AttendanceRecord).filter(models.AttendanceRecord.student_id == student_id).all()
    if not records:
        return
        
    total_conducted = sum(r.classes_conducted for r in records)
    total_attended = sum(r.classes_attended for r in records)
    
    overall_pct = (Decimal(total_attended) / Decimal(total_conducted) * 100) if total_conducted > 0 else 0
    overall_pct = round(overall_pct, 2)
    
    lowest_pct = min([(Decimal(r.classes_attended) / Decimal(r.classes_conducted) * 100) if r.classes_conducted > 0 else 0 for r in records]) if records else 0
    lowest_pct = round(lowest_pct, 2)
    
    status = "Missing"
    if total_conducted > 0:
        if overall_pct >= 50:
            status = "Eligible"
        elif 45 <= overall_pct < 50:
            status = "Borderline"
        else:
            status = "Not eligible"
            
    el_record = db.query(models.MstEligibility).filter(
        models.MstEligibility.student_id == student_id,
        models.MstEligibility.mst_exam_id == mst_exam_id
    ).first()
    
    if el_record:
        el_record.overall_pct = overall_pct
        el_record.lowest_subject_pct = lowest_pct
        # Status won't change if it was already manually overridden (unless we want to recalculate base status)
        el_record.status = status
    else:
        el_record = models.MstEligibility(
            student_id=student_id,
            mst_exam_id=mst_exam_id,
            overall_pct=overall_pct,
            lowest_subject_pct=lowest_pct,
            status=status
        )
        db.add(el_record)
        
    db.commit()


# ── Timetable ──────────────────────────────────────────────────────────────────

def create_timetable_version(db: Session, v: schemas.TimetableVersionCreate):
    """
    Create a new timetable version for a class+semester.
    Any previously active version for the same class+semester is deactivated so
    old data is preserved but no longer treated as current.
    """
    db.query(models.TimetableVersion).filter(
        models.TimetableVersion.class_id == v.class_id,
        models.TimetableVersion.semester == v.semester,
        models.TimetableVersion.active == True,
    ).update({"active": False})
    obj = models.TimetableVersion(**v.dict(), active=True)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

def create_timetable_entry(db: Session, e: schemas.TimetableEntryCreate):
    obj = models.FacultyTimetable(**e.dict())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

def bulk_create_timetable_entries(db: Session, entries: list):
    """Insert a list of TimetableEntryCreate dicts/objects in one transaction."""
    objs = [models.FacultyTimetable(**e.dict()) for e in entries]
    db.add_all(objs)
    db.commit()
    return objs

def get_timetable_for_class(db: Session, class_id: int, semester: str = None):
    q = db.query(models.FacultyTimetable).filter(models.FacultyTimetable.class_id == class_id)
    if semester:
        q = q.filter(models.FacultyTimetable.semester == semester)
    return q.all()

def check_faculty_availability(db: Session, day_of_week: str, period_start: str, period_end: str):
    """
    Core clash rule (from timetable images):
    A faculty member is BLOCKED if they have ANY class, in ANY year/class, whose
    period overlaps this slot. This correctly catches cases like 'MG' (Prof. Manoj
    Gupta) who appears in both CI-1 and CI-2 sheets — one clash row in any sheet
    is enough to block them.

    Overlap condition: existing.start < new.end  AND  existing.end > new.start
    (string comparison works because times are zero-padded HH:MM format)
    """
    results = []
    for f in db.query(models.Faculty).all():
        if f.exempt_from_duty:
            results.append(schemas.FacultyAvailabilityResult(
                faculty_id=f.id,
                faculty_name=f.name,
                status="Exempt",
                reason=f.exempt_reason or "Excluded by administrator",
            ))
            continue

        clash = db.query(models.FacultyTimetable).filter(
            models.FacultyTimetable.faculty_id == f.id,
            models.FacultyTimetable.day_of_week == day_of_week,
            # standard interval-overlap test
            models.FacultyTimetable.period_start < period_end,
            models.FacultyTimetable.period_end   > period_start,
        ).first()

        if clash:
            results.append(schemas.FacultyAvailabilityResult(
                faculty_id=f.id,
                faculty_name=f.name,
                status="Blocked",
                reason=(
                    f"Year {clash.year} class — {clash.subject_code or 'class'} "
                    f"({clash.period_start}–{clash.period_end})"
                ),
            ))
        else:
            results.append(schemas.FacultyAvailabilityResult(
                faculty_id=f.id,
                faculty_name=f.name,
                status="Available",
                reason="No class or duty conflict",
            ))
    return results
