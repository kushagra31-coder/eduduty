from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import engine, get_db
import models, schemas, crud
import ai_service, pdf_service
import pandas as pd
import io
import re

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="MST Operations Portal API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "MST Operations Portal Backend"}

# ── Attendance upload ──────────────────────────────────────────────────────────

@app.post("/upload-attendance/")
async def upload_attendance(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    if not file.filename.endswith(('.xls', '.xlsx')):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload an Excel file.")

    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
        # Normalize column names for lookup (case/space/underscore-insensitive)
        colmap = {str(c).strip().lower().replace("_", " ").replace("-", " "): c for c in df.columns}
        def col(*names):
            for n in names:
                if n in colmap:
                    return colmap[n]
            return None
        c_roll = col("roll number", "roll no", "roll")
        c_name = col("name", "student name")
        c_total = col("total classes", "classes conducted", "total")
        c_att = col("attended", "classes attended", "attended classes")
        c_batch = [colmap[k] for k in ("batch", "batch number", "batch no") if k in colmap]
        def row_batch(row):
            for cb in c_batch:
                raw = str(row.get(cb, "")).strip().upper()
                if not raw or raw == "NAN":
                    continue
                m = re.search(r"[12]", raw)
                if m:
                    return int(m.group(0))
            return None
        mst_exam_id = 1
        dummy_exam = db.query(models.MstExam).filter_by(id=mst_exam_id).first()
        if not dummy_exam:
            dummy_exam = models.MstExam(id=mst_exam_id, label="MST-1")
            db.add(dummy_exam)
            db.commit()

        imported_count = 0
        for _, row in df.iterrows():
            roll_number = str(row.get(c_roll, '')).strip() if c_roll else ''
            if not roll_number or roll_number == 'nan':
                continue
            name     = str(row.get(c_name, 'Unknown')).strip() if c_name else 'Unknown'
            total    = int(row.get(c_total, 0)) if c_total else 0
            attended = int(row.get(c_att, 0)) if c_att else 0
            batch_number = row_batch(row)
            student  = crud.get_student_by_roll(db, roll_number)
            if not student:
                c = crud.get_class_by_name(db, "CI-1")
                if not c:
                    c = models.Class(name="CI-1", branch="CSE", year=3)
                    db.add(c); db.commit(); db.refresh(c)
                student = models.Student(roll_number=roll_number, name=name, class_id=c.id,
                                         batch_number=batch_number)
                db.add(student); db.commit(); db.refresh(student)
            elif batch_number and not student.batch_number:
                student.batch_number = batch_number
                db.commit()
            att = schemas.AttendanceRecordBase(
                student_id=student.id,
                classes_conducted=total,
                classes_attended=attended
            )
            crud.create_attendance_record(db, att)
            crud.compute_eligibility_for_student(db, student.id, mst_exam_id)
            imported_count += 1
        # Record the import so the dashboard activity feed can show it
        db.add(models.AuditLog(
            table_name="attendance_records",
            record_id=0,
            field_changed="import",
            new_value=f"{imported_count} rows",
            reason=file.filename,
        ))
        db.commit()
        return {"filename": file.filename, "rows_imported": imported_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

# ── Dashboard ──────────────────────────────────────────────────────────────

@app.get("/dashboard/stats")
def dashboard_stats(db: Session = Depends(get_db)):
    exam = db.query(models.MstExam).filter_by(id=1).first()
    exam_label = exam.label if exam else "MST-1"

    students = db.query(models.Student).all()
    classes = {c.id: c for c in db.query(models.Class).all()}
    elig_rows = db.query(models.MstEligibility).filter_by(mst_exam_id=1).all()
    elig_by_student = {e.student_id: e for e in elig_rows}

    total = len(students)
    n_eligible = sum(1 for e in elig_rows if e.status == "Eligible")
    n_borderline = sum(1 for e in elig_rows if e.status == "Borderline")
    n_ineligible = sum(1 for e in elig_rows if e.status == "Not eligible")
    n_overrides = sum(1 for e in elig_rows if e.override)

    per_class: dict[str, dict] = {}
    for s in students:
        c = classes.get(s.class_id)
        cname = c.name if c else "—"
        bucket = per_class.setdefault(cname, {
            "class": cname, "students": 0,
            "eligible": 0, "borderline": 0, "ineligible": 0,
        })
        bucket["students"] += 1
        e = elig_by_student.get(s.id)
        st = e.status if e and e.status else "Missing"
        if st == "Eligible":
            bucket["eligible"] += 1
        elif st == "Borderline":
            bucket["borderline"] += 1
        elif st == "Not eligible":
            bucket["ineligible"] += 1

    n_versions = db.query(models.TimetableVersion).count()
    tt_entries = db.query(models.FacultyTimetable).all()
    tt_classes = sorted({classes[e.class_id].name
                         for e in tt_entries if e.class_id in classes})

    logs = db.query(models.AuditLog)\
        .order_by(models.AuditLog.changed_at.desc()).limit(8).all()
    activity = []
    # changed_at is stored as naive UTC (utcnow) — mark it so browsers parse it right
    def ts(dt):
        return dt.isoformat() + "Z" if dt else None
    for log in logs:
        at = ts(log.changed_at)
        if log.field_changed == "import":
            activity.append({
                "kind": "upload",
                "title": "Attendance uploaded",
                "detail": f"{log.new_value} from {log.reason or 'file'}",
                "at": at,
            })
        elif log.table_name == "mst_eligibility" and log.field_changed == "override":
            e = db.query(models.MstEligibility).filter_by(id=log.record_id).first()
            s = db.query(models.Student).filter_by(id=e.student_id).first() if e else None
            who = f"roll {s.roll_number}" if s else f"record {log.record_id}"
            action = "approved" if log.new_value == "True" else "revoked"
            activity.append({
                "kind": "override",
                "title": f"Override {action} for {who}",
                "detail": log.reason or "—",
                "at": at,
            })
        else:
            activity.append({
                "kind": "other",
                "title": f"{log.table_name} · {log.field_changed}",
                "detail": log.reason or "",
                "at": at,
            })

    return {
        "exam_label": exam_label,
        "total_students": total,
        "eligible": n_eligible,
        "eligible_pct": round(n_eligible / total * 100, 1) if total else 0,
        "borderline": n_borderline,
        "ineligible": n_ineligible,
        "overrides": n_overrides,
        "per_class": sorted(per_class.values(), key=lambda b: b["class"]),
        "timetable": {
            "versions": n_versions,
            "periods": len(tt_entries),
            "classes": tt_classes,
        },
        "recent_activity": activity,
    }

# ── Eligibility ────────────────────────────────────────────────────────────────

@app.get("/eligibility/{mst_exam_id}", response_model=list[schemas.MstEligibilityDisplay])
def get_eligibility(mst_exam_id: int, db: Session = Depends(get_db)):
    return crud.get_mst_eligibility(db, mst_exam_id)

@app.post("/eligibility/override/{eligibility_id}")
def override_eligibility(
    eligibility_id: int,
    override: bool = Body(...),
    reason: str = Body(...),
    db: Session = Depends(get_db)
):
    user_id = 1
    record = crud.update_eligibility_override(db, eligibility_id, override, reason, user_id)
    if not record:
        raise HTTPException(status_code=404, detail="Eligibility record not found")
    return {"message": "Override applied successfully"}

# ── AI assistant ───────────────────────────────────────────────────────────────

class AIMessageRequest(BaseModel):
    message: str

class WriteConfirmRequest(BaseModel):
    op_json: dict

@app.post("/ai/query")
async def ai_query(req: AIMessageRequest, db: Session = Depends(get_db)):
    """
    Route a natural language message to read / write-proposal / pdf path.
    Returns { type, content }
    """
    try:
        result = await ai_service.handle_ai_message(req.message, db)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ai/confirm-write")
def ai_confirm_write(req: WriteConfirmRequest, db: Session = Depends(get_db)):
    """
    Execute an AI-proposed write ONLY after the user has explicitly confirmed in the UI.
    """
    try:
        result = ai_service.execute_write_op(req.op_json, db)
        return {"success": True, "changed": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── PDF generation ─────────────────────────────────────────────────────────────

@app.get("/pdf/student/{roll_number}")
def get_student_pdf(roll_number: str, db: Session = Depends(get_db)):
    """Generate and stream a formal student record PDF."""
    try:
        html      = pdf_service.build_student_record_html(roll_number, db)
        pdf_bytes = pdf_service.render_pdf(html)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename=student_{roll_number}.pdf"},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

@app.get("/pdf/seating/{mst_exam_id}/{room_id}")
def get_seating_pdf(mst_exam_id: int, room_id: int, db: Session = Depends(get_db)):
    """Generate and stream a seating chart + signature sheet PDF."""
    try:
        html      = pdf_service.build_seating_chart_html(mst_exam_id, room_id, db)
        pdf_bytes = pdf_service.render_pdf(html)
        exam  = db.query(models.MstExam).filter_by(id=mst_exam_id).first()
        room  = db.query(models.Room).filter_by(id=room_id).first()
        fname = f"seating_{exam.label if exam else mst_exam_id}_room{room.room_number if room else room_id}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename={fname}"},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

@app.get("/pdf/student/{roll_number}/html")
def get_student_html(roll_number: str, db: Session = Depends(get_db)):
    """Debug: returns raw HTML preview without WeasyPrint installed."""
    try:
        html = pdf_service.build_student_record_html(roll_number, db)
        return Response(content=html, media_type="text/html")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Timetable ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter

timetable_router = APIRouter(prefix="/timetable", tags=["timetable"])

@timetable_router.post("/version", response_model=schemas.TimetableVersionOut)
def create_timetable_version(v: schemas.TimetableVersionCreate, db: Session = Depends(get_db)):
    return crud.create_timetable_version(db, v)

@timetable_router.post("/entry", response_model=schemas.TimetableEntryOut)
def create_timetable_entry(e: schemas.TimetableEntryCreate, db: Session = Depends(get_db)):
    return crud.create_timetable_entry(db, e)

@timetable_router.post("/entries/bulk")
def create_timetable_entries_bulk(
    entries: list[schemas.TimetableEntryCreate],
    db: Session = Depends(get_db),
):
    crud.bulk_create_timetable_entries(db, entries)
    return {"created": len(entries)}

@timetable_router.get("/class/{class_id}", response_model=list[schemas.TimetableEntryOut])
def get_class_timetable(
    class_id: int,
    semester: str = None,
    db: Session = Depends(get_db),
):
    return crud.get_timetable_for_class(db, class_id, semester)

@timetable_router.post("/availability", response_model=list[schemas.FacultyAvailabilityResult])
def faculty_availability(
    check: schemas.FacultyAvailabilityCheck,
    db: Session = Depends(get_db),
):
    return crud.check_faculty_availability(
        db, check.day_of_week, check.period_start, check.period_end
    )

app.include_router(timetable_router)


# ── Classes / Faculty helpers (used by timetable frontend) ─────────────────────

@app.get("/classes", response_model=list[schemas.ClassOut])
def list_classes(db: Session = Depends(get_db)):
    return crud.get_classes(db)

@app.get("/faculty")
def list_faculty(db: Session = Depends(get_db)):
    rows = db.query(models.Faculty).all()
    return [
        {
            "id": f.id,
            "name": f.name,
            "abbreviation": f.abbreviation,
            "department": f.department,
            "exempt_from_duty": f.exempt_from_duty,
        }
        for f in rows
    ]

# ── MST seat-map attendance tracker ──────────────────────────────────────────
# Seating rule: Batch 1 roll n sits beside Batch 2 roll n (sorted by roll
# number, zipped in order). Students outside batches 1/2 sit alone.

from itertools import zip_longest as _zip_longest
import datetime as _dt

_DAY_MAP = {"MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday", "THU": "Thursday",
            "FRI": "Friday", "SAT": "Saturday", "SUN": "Sunday"}


def _seat_student_out(s):
    if not s:
        return None
    return {"id": s.id, "roll_number": s.roll_number, "name": s.name,
            "batch_number": s.batch_number}


@app.get("/mst/exams", response_model=list[schemas.MstExamOut])
def list_mst_exams(db: Session = Depends(get_db)):
    return db.query(models.MstExam).order_by(models.MstExam.id.desc()).all()


@app.post("/mst/exams", response_model=schemas.MstExamOut)
def create_mst_exam(req: schemas.MstExamCreate, db: Session = Depends(get_db)):
    exam = models.MstExam(label=req.label, exam_date=req.exam_date,
                          time_slot=req.time_slot, class_id=req.class_id)
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return exam


@app.get("/rooms", response_model=list[schemas.RoomOut])
def list_rooms(db: Session = Depends(get_db)):
    return db.query(models.Room).order_by(models.Room.room_number).all()


@app.post("/rooms", response_model=schemas.RoomOut)
def create_room(req: schemas.RoomCreate, db: Session = Depends(get_db)):
    room = models.Room(room_number=req.room_number, capacity=req.capacity)
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


@app.post("/mst/seating/generate")
def generate_seating(req: schemas.SeatingGenerateIn, db: Session = Depends(get_db)):
    exam = db.query(models.MstExam).filter_by(id=req.mst_exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    # clear any previous chart for this exam
    db.query(models.Seat).filter_by(mst_exam_id=exam.id).delete()
    db.commit()

    q = db.query(models.Student).filter_by(active=True)
    if exam.class_id:
        q = q.filter_by(class_id=exam.class_id)
    students = q.all()
    b1 = sorted([s for s in students if s.batch_number == 1], key=lambda s: s.roll_number or "")
    b2 = sorted([s for s in students if s.batch_number == 2], key=lambda s: s.roll_number or "")
    others = sorted([s for s in students if s.batch_number not in (1, 2)],
                    key=lambda s: s.roll_number or "")
    pairs = [(l, r) for l, r in _zip_longest(b1, b2)]
    pairs += [(s, None) for s in others]

    rooms = db.query(models.Room).filter(models.Room.id.in_(req.room_ids)).order_by(models.Room.room_number).all()
    if not rooms:
        raise HTTPException(status_code=400, detail="No valid rooms selected")

    created, seated, unseated = 0, 0, []
    it = iter(pairs)
    for room in rooms:
        cap = room.capacity or 30
        for n in range(1, cap + 1):
            try:
                left, right = next(it)
            except StopIteration:
                break
            db.add(models.Seat(room_id=room.id, mst_exam_id=exam.id,
                               seat_number=str(n),
                               left_student=left.id if left else None,
                               right_student=right.id if right else None))
            created += 1
            seated += (1 if left else 0) + (1 if right else 0)
    for left, right in it:
        for s in (left, right):
            if s:
                unseated.append(s.roll_number)
    db.commit()
    return {"seats_created": created, "students_seated": seated, "unseated": unseated}


@app.get("/mst/seating/{mst_exam_id}")
def get_seating(mst_exam_id: int, db: Session = Depends(get_db)):
    seats = db.query(models.Seat).filter_by(mst_exam_id=mst_exam_id).all()
    if not seats:
        return []
    rooms = {r.id: r for r in db.query(models.Room).all()}
    want_ids = {s.left_student for s in seats} | {s.right_student for s in seats}
    want_ids.discard(None)
    students = (
        {s.id: s for s in
         db.query(models.Student).filter(models.Student.id.in_(want_ids)).all()}
        if want_ids else {}
    )
    attempts = {
        a.student_id: a.status
        for a in db.query(models.MstAttempt).filter_by(mst_exam_id=mst_exam_id).all()
    }
    by_room: dict[int, list] = {}
    for s in seats:
        by_room.setdefault(s.room_id, []).append(s)
    out = []
    for room_id in sorted(by_room, key=lambda i: rooms.get(i).room_number if rooms.get(i) else ""):
        room = rooms.get(room_id)
        rseats = sorted(
            by_room[room_id],
            key=lambda x: int(x.seat_number) if str(x.seat_number).isdigit() else 9999,
        )
        out.append({
            "room_id": room_id,
            "room_number": room.room_number if room else str(room_id),
            "capacity": room.capacity if room else None,
            "seats": [
                {
                    "id": s.id,
                    "seat_number": s.seat_number,
                    "room_id": s.room_id,
                    "room_number": room.room_number if room else str(room_id),
                    "left": _seat_student_out(students.get(s.left_student)),
                    "right": _seat_student_out(students.get(s.right_student)),
                    "left_status": attempts.get(s.left_student),
                    "right_status": attempts.get(s.right_student),
                }
                for s in rseats
            ],
        })
    return out


@app.post("/mst/attendance/mark", response_model=schemas.AttendanceMarkOut)
def mark_attendance(req: schemas.MarkAttendanceIn, db: Session = Depends(get_db)):
    if req.status not in ("Present", "Absent"):
        raise HTTPException(status_code=400, detail="status must be Present or Absent")
    att = db.query(models.MstAttempt).filter_by(
        mst_exam_id=req.mst_exam_id, student_id=req.student_id).first()
    if not att:
        att = models.MstAttempt(
            mst_exam_id=req.mst_exam_id, student_id=req.student_id,
            status=req.status,
        )
        db.add(att)
    else:
        att.status = req.status
    att.marked_at = _dt.datetime.utcnow()
    db.commit()
    db.refresh(att)
    return {"student_id": att.student_id, "status": att.status, "marked_at": att.marked_at}


@app.get("/mst/attendance/{mst_exam_id}")
def get_attendance(mst_exam_id: int, db: Session = Depends(get_db)):
    rows = db.query(models.MstAttempt).filter_by(mst_exam_id=mst_exam_id).all()
    return [{"student_id": a.student_id, "status": a.status, "marked_at": a.marked_at}
            for a in rows]


@app.get("/mst/duties/{mst_exam_id}", response_model=list[schemas.DutyOut])
def list_duties(mst_exam_id: int, db: Session = Depends(get_db)):
    duties = db.query(models.InvigilationDuty).filter_by(mst_exam_id=mst_exam_id).all()
    rooms = {r.id: r.room_number for r in db.query(models.Room).all()}
    fac = {f.id: f.name for f in db.query(models.Faculty).all()}
    return [{
        "id": d.id,
        "room_id": d.room_id,
        "room_number": rooms.get(d.room_id, str(d.room_id)),
        "faculty_id": d.faculty_id,
        "faculty_name": fac.get(d.faculty_id),
        "status": d.status,
    } for d in duties]


@app.post("/mst/duties/assign")
def assign_duty(req: schemas.DutyAssignIn, db: Session = Depends(get_db)):
    d = db.query(models.InvigilationDuty).filter_by(
        mst_exam_id=req.mst_exam_id, room_id=req.room_id).first()
    if not d:
        d = models.InvigilationDuty(mst_exam_id=req.mst_exam_id, room_id=req.room_id,
                                    status="Unfilled")
        db.add(d)
    d.faculty_id = req.faculty_id
    d.status = "Assigned"
    d.assigned_at = _dt.datetime.utcnow()
    db.commit()
    return {"ok": True}


@app.post("/mst/duties/unassign/{duty_id}")
def unassign_duty(duty_id: int, db: Session = Depends(get_db)):
    d = db.query(models.InvigilationDuty).filter_by(id=duty_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Duty not found")
    d.faculty_id = None
    d.status = "Unfilled"
    db.commit()
    return {"ok": True}


@app.get("/mst/faculty-status", response_model=list[schemas.FacultyExamStatusOut])
def faculty_status_for_exam(mst_exam_id: int, db: Session = Depends(get_db)):
    """
    Who can invigilate this exam: faculty with a class overlapping the exam
    slot are 'Teaching', already-assigned invigilators are 'On duty',
    exempt staff are 'Exempt', everyone else is 'Available'.
    """
    exam = db.query(models.MstExam).filter_by(id=mst_exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    day = _DAY_MAP.get(exam.exam_date.strftime("%a").upper()) if exam.exam_date else None
    start, end = "09:00", "12:00"
    if exam.time_slot and "-" in exam.time_slot:
        parts = [p.strip() for p in exam.time_slot.split("-", 1)]
        if len(parts) == 2 and all(parts):
            start, end = parts

    if day:
        base = crud.check_faculty_availability(db, day, start, end)
    else:
        base = [
            schemas.FacultyAvailabilityResult(
                faculty_id=f.id, faculty_name=f.name,
                status="Exempt" if f.exempt_from_duty else "Available",
                reason=(f.exempt_reason or "No exam date set") if f.exempt_from_duty
                else "No exam date set",
            )
            for f in db.query(models.Faculty).all()
        ]

    duties = db.query(models.InvigilationDuty).filter_by(mst_exam_id=exam.id).all()
    rooms = {r.id: r.room_number for r in db.query(models.Room).all()}
    on_duty = {d.faculty_id: d for d in duties if d.faculty_id}
    faculty = {f.id: f for f in db.query(models.Faculty).all()}

    out = []
    for r in base:
        f = faculty.get(r.faculty_id)
        if r.faculty_id in on_duty:
            d = on_duty[r.faculty_id]
            status, reason = "On duty", f"Invigilating room {rooms.get(d.room_id, d.room_id)}"
        elif r.status == "Blocked":
            status, reason = "Teaching", r.reason
        elif r.status == "Exempt":
            status, reason = "Exempt", r.reason
        else:
            status, reason = "Available", "Free for invigilation duty"
        out.append({
            "faculty_id": r.faculty_id,
            "faculty_name": r.faculty_name,
            "abbreviation": f.abbreviation if f else None,
            "department": f.department if f else None,
            "status": status,
            "reason": reason,
        })
    return out
