from sqlalchemy.orm import Session
import models, schemas
import datetime
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

# ── VT / follow-up rule engine ─────────────────────────────────────────────────
# Rule version: absent-both-mst-v1
#   absent in BOTH MST-1 and MST-2  -> compulsory
#   missing appearance data        -> under_review (missing != absent)
#   otherwise                      -> not_required
# Never derived from eligibility — an eligible-but-absent student is the target.

FOLLOW_UP_RULE_VERSION = "absent-both-mst-v1"

FOLLOW_UP_STATUSES = ("not_required", "compulsory", "under_review", "excused", "completed")

# final_status values a human may set (calculated_status stays system-owned)
OVERRIDABLE_FINAL_STATUSES = ("under_review", "excused", "completed")


def _find_mst_exam(db: Session, student, label: str):
    """Newest exam with this label, preferring the student's class, else unscoped."""
    exam = (
        db.query(models.MstExam)
        .filter(models.MstExam.label == label,
                models.MstExam.class_id == student.class_id)
        .order_by(models.MstExam.id.desc())
        .first()
    )
    if exam is None:
        exam = (
            db.query(models.MstExam)
            .filter(models.MstExam.label == label,
                    models.MstExam.class_id.is_(None))
            .order_by(models.MstExam.id.desc())
            .first()
        )
    return exam


def _appeared(db: Session, student_id: int, exam):
    """True/False from the attempt record; None when there is no record."""
    if exam is None:
        return None
    att = (
        db.query(models.MstAttempt)
        .filter_by(student_id=student_id, mst_exam_id=exam.id)
        .first()
    )
    if att is None:
        return None
    return att.status == "Present"


def calculate_follow_up_status(mst_1_appeared, mst_2_appeared) -> str:
    if mst_1_appeared is None or mst_2_appeared is None:
        return "under_review"
    if not mst_1_appeared and not mst_2_appeared:
        return "compulsory"
    return "not_required"


def recalculate_follow_up(db: Session, student_id: int):
    """Recompute one student's follow-up record from MST-1/MST-2 appearance.

    Returns the FollowUpStatus row. Writes an audit entry when the
    calculated status changes. A manual override never changes the
    calculated recommendation — only the final status.
    """
    student = db.query(models.Student).filter_by(id=student_id).first()
    if student is None:
        return None

    exam1 = _find_mst_exam(db, student, "MST-1")
    exam2 = _find_mst_exam(db, student, "MST-2")
    m1 = _appeared(db, student_id, exam1)
    m2 = _appeared(db, student_id, exam2)
    calculated = calculate_follow_up_status(m1, m2)

    now = datetime.datetime.utcnow()
    row = (
        db.query(models.FollowUpStatus)
        .filter_by(student_id=student_id)
        .first()
    )
    if row is None:
        row = models.FollowUpStatus(
            student_id=student_id,
            rule_version=FOLLOW_UP_RULE_VERSION,
            mst_1_exam_id=exam1.id if exam1 else None,
            mst_2_exam_id=exam2.id if exam2 else None,
            mst_1_appeared=m1,
            mst_2_appeared=m2,
            calculated_status=calculated,
            final_status=calculated,   # no override yet: final follows calculation
            override=False,
            calculated_at=now,
            updated_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    old_calculated = row.calculated_status
    row.mst_1_exam_id = exam1.id if exam1 else None
    row.mst_2_exam_id = exam2.id if exam2 else None
    row.mst_1_appeared = m1
    row.mst_2_appeared = m2
    row.calculated_status = calculated
    row.calculated_at = now
    row.updated_at = now
    # A fresh calculation refreshes final_status only when nobody overrode it.
    if not row.override:
        row.final_status = calculated

    if old_calculated != calculated:
        db.add(models.AuditLog(
            table_name="follow_up_statuses",
            record_id=row.id,
            field_changed="calculated_status",
            old_value=old_calculated,
            new_value=calculated,
            changed_by=None,   # system action, not a human
            reason=(
                f"Rule {FOLLOW_UP_RULE_VERSION}: "
                f"MST-1={'Present' if m1 else 'Absent' if m1 is False else 'missing'}, "
                f"MST-2={'Present' if m2 else 'Absent' if m2 is False else 'missing'}"
            ),
        ))
    db.commit()
    db.refresh(row)
    return row


def recalculate_all_follow_ups(db: Session, class_id: int = None) -> dict:
    """Batch recalculation for every active student (optionally one class)."""
    q = db.query(models.Student).filter(models.Student.active.is_(True))
    if class_id:
        q = q.filter(models.Student.class_id == class_id)
    counts = {"evaluated": 0, "changed": 0}
    for student in q.all():
        before = (
            db.query(models.FollowUpStatus.calculated_status)
            .filter_by(student_id=student.id)
            .scalar()
        )
        recalculate_follow_up(db, student.id)
        counts["evaluated"] += 1
        if before is not None and before != (
            db.query(models.FollowUpStatus.calculated_status)
            .filter_by(student_id=student.id)
            .scalar()
        ):
            counts["changed"] += 1
    return counts


def override_follow_up(db: Session, follow_up_id: int, final_status: str,
                       reason: str, changed_by: int = None):
    """Authorized human decision. calculated_status is never touched."""
    if final_status not in OVERRIDABLE_FINAL_STATUSES:
        raise ValueError(
            f"final_status must be one of {OVERRIDABLE_FINAL_STATUSES}"
        )
    if not reason or not reason.strip():
        raise ValueError("A typed reason is required for every override.")
    row = db.query(models.FollowUpStatus).filter_by(id=follow_up_id).first()
    if row is None:
        raise ValueError("Follow-up record not found.")

    old_final = row.final_status
    now = datetime.datetime.utcnow()
    row.final_status = final_status
    row.override = True
    row.override_reason = reason.strip()
    row.override_by = changed_by
    row.overridden_at = now
    row.updated_at = now
    db.add(models.AuditLog(
        table_name="follow_up_statuses",
        record_id=row.id,
        field_changed="final_status",
        old_value=old_final,
        new_value=final_status,
        changed_by=changed_by,
        reason=reason.strip(),
    ))
    db.commit()
    db.refresh(row)
    return row


def restore_calculated_follow_up(db: Session, follow_up_id: int,
                                 reason: str, changed_by: int = None):
    """Drop the human override; final_status follows the rule again."""
    if not reason or not reason.strip():
        raise ValueError("A typed reason is required to restore the calculated status.")
    row = db.query(models.FollowUpStatus).filter_by(id=follow_up_id).first()
    if row is None:
        raise ValueError("Follow-up record not found.")
    old_final = row.final_status
    row.final_status = row.calculated_status
    row.override = False
    row.override_reason = None
    row.override_by = None
    row.overridden_at = None
    row.updated_at = datetime.datetime.utcnow()
    db.add(models.AuditLog(
        table_name="follow_up_statuses",
        record_id=row.id,
        field_changed="final_status",
        old_value=old_final,
        new_value=row.calculated_status,
        changed_by=changed_by,
        reason=f"Override cleared — restored calculated status. {reason.strip()}",
    ))
    db.commit()
    db.refresh(row)
    return row
