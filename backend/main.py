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
from difflib import SequenceMatcher

models.Base.metadata.create_all(bind=engine)

# ── Read-only view for the AI + reporting (works on SQLite and Postgres) ──────
_FOLLOW_UP_VIEW_BODY = """
SELECT
    s.roll_number,
    s.name AS student_name,
    c.name AS class_name,
    e1.label AS mst_1_label,
    e2.label AS mst_2_label,
    fs.mst_1_appeared,
    fs.mst_2_appeared,
    fs.calculated_status,
    fs.final_status,
    fs.override AS overridden,
    fs.override_reason,
    fs.rule_version,
    fs.updated_at
FROM follow_up_statuses fs
JOIN students s ON s.id = fs.student_id
JOIN classes c ON c.id = s.class_id
LEFT JOIN mst_exams e1 ON e1.id = fs.mst_1_exam_id
LEFT JOIN mst_exams e2 ON e2.id = fs.mst_2_exam_id
"""

def _ensure_follow_up_view():
    try:
        with engine.begin() as conn:
            if engine.dialect.name == "sqlite":
                # SQLite has no CREATE OR REPLACE VIEW
                conn.execute(models.text("DROP VIEW IF EXISTS v_vt_follow_up_status"))
                conn.execute(models.text(
                    "CREATE VIEW v_vt_follow_up_status AS" + _FOLLOW_UP_VIEW_BODY))
            else:
                conn.execute(models.text(
                    "CREATE OR REPLACE VIEW v_vt_follow_up_status AS" + _FOLLOW_UP_VIEW_BODY))
    except Exception as exc:  # never block app startup on a reporting view
        print(f"warning: could not create v_vt_follow_up_status: {exc}", flush=True)

_ensure_follow_up_view()

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

def _to_int(v) -> int:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0
        s = str(v).strip()
        if not s or s.lower() == "nan":
            return 0
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def _norm_name(n) -> str:
    return re.sub(r"[^a-z]", "", (n or "").lower())


def _parse_subject_sheet(df) -> dict | None:
    """Parse one per-subject attendance sheet.

    Layout (as in CI-1 IV.xlsx):
      rows 0-5 : 'Faculty Name' / 'Subject Name' / 'Subject Code' header block
      row H    : column titles ('s.no.', 'Enrollment NO.', 'Student Name', ...)
                 AND the totals row (numeric total under 'Total Class')
      rows H+1+: one row per student; value under 'Total Class' = classes attended
    Returns None when the sheet is not in this format.
    """
    subj_code = subj_name = faculty_name = None
    header_idx = None
    scan = min(14, len(df))
    for r in range(scan):
        cells = [str(v).strip() for v in df.iloc[r].tolist()]
        low = [c.lower() for c in cells]
        if subj_code is None and any("subject code" in c for c in low):
            v = cells[2] if len(cells) > 2 else ""
            subj_code = "" if v.lower() == "nan" else v
        if subj_name is None and any("subject name" in c for c in low):
            v = cells[2] if len(cells) > 2 else ""
            subj_name = "" if v.lower() == "nan" else v
        if faculty_name is None and any("faculty name" in c for c in low):
            v = cells[2] if len(cells) > 2 else ""
            faculty_name = "" if v.lower() == "nan" else v
        if header_idx is None and any("enrollment no" in c for c in low):
            header_idx = r
    if header_idx is None:
        return None

    # Column positions: labels may sit on the header row or the row above it
    # (the header row doubles as the totals row, so its 'Total Class' cell is numeric).
    col_roll = col_name = col_total = None
    for lr in ({header_idx - 1} if header_idx > 0 else set()) | {header_idx}:
        low = [str(v).strip().lower() for v in df.iloc[lr].tolist()]
        for i, c in enumerate(low):
            if col_roll is None and "enrollment no" in c:
                col_roll = i
            elif col_name is None and "student name" in c:
                col_name = i
            elif col_total is None and "total" in c and "class" in c:
                col_total = i
    if col_roll is None or col_total is None:
        return None

    total = _to_int(df.iloc[header_idx, col_total])
    students = []
    for r in range(header_idx + 1, len(df)):
        cells = [str(v).strip() for v in df.iloc[r].tolist()]
        low3 = [c.lower() for c in cells[:4]]
        # Lab sheets append other classes' sections below, each starting with a
        # repeated 'Faculty Name:' / header block — stop at the second section.
        if any("faculty name" in c for c in low3) or any("enrollment no" in c for c in low3):
            break
        roll = cells[col_roll] if col_roll < len(cells) else ""
        if not roll or roll.lower() == "nan":
            continue
        # skip non-enrollment junk (e.g. repeated header text like 'Enrollment No.')
        if not re.search(r"\d", roll):
            continue
        name = str(df.iloc[r, col_name]).strip() if col_name is not None else ""
        if not name or name.lower() == "nan":
            name = "Unknown"
        students.append((roll, name, _to_int(df.iloc[r, col_total])))
    return {
        "subject_code": (subj_code or "").strip(),
        "subject_name": (subj_name or "").strip(),
        "faculty_name": (faculty_name or "").strip(),
        "total_classes": total,
        "students": students,
    }


def _get_or_create_subject(db: Session, code: str, name: str):
    code = (code or "").strip() or (name or "UNKNOWN").strip()
    s = db.query(models.Subject).filter(models.Subject.code == code).first()
    if not s:
        s = models.Subject(code=code[:20], name=(name or code).strip()[:100])
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _canon_faculty_tokens(n) -> set:
    n = (n or "").lower()
    n = re.sub(r"^(prof\.?|dr\.?)\s*", "", n).strip()
    # known spelling variants across sheets
    for a, b in (("shweta", "sweta"), ("aarti", "arti"),
                 ("shrivastava", "shrivastva"), ("anajana", "anjana")):
        n = n.replace(a, b)
    return set(re.sub(r"[^a-z ]", " ", n).split())


def _tok_sim(a: str, b: str) -> float:
    # SequenceMatcher is not perfectly symmetric; take the max so that
    # _same_person(a, b) == _same_person(b, a).
    return max(SequenceMatcher(None, a, b).ratio(),
               SequenceMatcher(None, b, a).ratio())


def _same_person(a, b) -> bool:
    """Token-subset match with per-token fuzzy tolerance.

    Handles 'Purnima Shrivastava' vs 'Poornima Shrivasta' and
    'MANOJ KUMAR GUPTA' vs 'Manoj Gupta', while keeping
    'Anita Agrawal' vs 'Neha Agrawal' and 'Ashish Anjana' vs
    'Ashwinee Gadwal' apart.
    """
    ta, tb = _canon_faculty_tokens(a), _canon_faculty_tokens(b)
    if not ta or not tb:
        return False
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    used = set()
    for t in small:
        best, bj = 0.0, -1
        for j, u in enumerate(large):
            if j in used:
                continue
            r = _tok_sim(t, u)
            if r > best:
                best, bj = r, j
        if best < 0.78:
            return False
        used.add(bj)
    return True


def _title_score(n: str) -> int:
    """Lower is better: penalize ALL-CAPS words ('VANDANA kATE' -> 1)."""
    return sum(1 for w in re.sub(r"[^a-zA-Z ]", " ", n or "").split()
               if w.isupper() and len(w) > 1)


def _fix_name_word(w: str) -> str:
    if w.isupper() and len(w) > 1:      # VANDANA -> Vandana
        return w.title()
    if re.match(r"^[a-z][A-Z]+$", w):   # kATE -> Kate
        return w.title()
    return w


def _normalize_faculty_name(n: str) -> str:
    """Display-quality normalization: space after Prof./Dr., fix ALL-CAPS words."""
    n = re.sub(r"^(prof|dr)\.([A-Za-z])", r"\1. \2", (n or "").strip(), flags=re.IGNORECASE)
    parts = n.split(" ", 1)
    head, rest = parts[0], (parts[1] if len(parts) > 1 else "")
    rest = " ".join(_fix_name_word(w) for w in rest.split())
    return (head + " " + rest).strip()[:100]


def _get_or_create_faculty(db: Session, raw_name: str):
    # Sheets sometimes list two faculty as "A / B" — link the first, still register both.
    names = [p.strip() for p in (raw_name or "").split("/") if p.strip()]
    if not names or not names[0] or names[0].lower() == "nan":
        return None
    primary = _normalize_faculty_name(names[0])
    for f in db.query(models.Faculty).all():
        if f.name in ("Unknown", "", None) and primary != "Unknown":
            f.name = primary
            db.commit()
            return f
        if _same_person(f.name, primary):
            # keep the best-cased variant of the name
            for cand in (_normalize_faculty_name(f.name), primary):
                if _title_score(cand) < _title_score(f.name):
                    f.name = cand
                    db.commit()
            return f
    f = models.Faculty(name=primary)
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def _class_from_filename(db: Session, filename: str):
    """Derive the class from workbook names like 'CI-1 IV.xlsx' / 'CY VI.xlsx'."""
    m = re.match(r"\s*([A-Za-z]+-\d+|[A-Za-z]+)", filename or "")
    branch = m.group(1).upper() if m else "CI-1"
    sem_m = re.search(r"\b(II|III|IV|V|VI)\b", (filename or "").upper())
    roman = sem_m.group(1) if sem_m else ""
    year = {"II": 2, "III": 2, "IV": 2, "V": 3, "VI": 3}.get(roman, 2)
    name = f"{branch} {roman}" if roman else branch
    c = crud.get_class_by_name(db, name)
    if not c:
        c = models.Class(name=name, branch=branch, year=year)
        db.add(c)
        db.commit()
        db.refresh(c)
    return c, roman or None


def _ensure_dummy_exam(db: Session) -> int:
    mst_exam_id = 1
    if not db.query(models.MstExam).filter_by(id=mst_exam_id).first():
        db.add(models.MstExam(id=mst_exam_id, label="MST-1"))
        db.commit()
    return mst_exam_id


def _import_subject_workbook(db: Session, xls, filename: str):
    """Import every per-subject sheet in the workbook."""
    cls, semester = _class_from_filename(db, filename)
    mst_exam_id = _ensure_dummy_exam(db)
    sheets_summary = []
    total_records = 0
    students_seen = set()

    for sh in xls.sheet_names:
        df = xls.parse(sh, header=None)
        parsed = _parse_subject_sheet(df)
        if not parsed:
            sheets_summary.append({"sheet": sh, "status": "skipped",
                                   "reason": "not a subject attendance sheet"})
            continue
        if not parsed["students"]:
            sheets_summary.append({"sheet": sh, "status": "skipped",
                                   "reason": "no student rows found"})
            continue
        subject = _get_or_create_subject(db, parsed["subject_code"] or sh,
                                         parsed["subject_name"])
        faculty = _get_or_create_faculty(db, parsed["faculty_name"])
        # Re-upload replaces the previous import of this file+subject (idempotent)
        db.query(models.AttendanceRecord).filter(
            models.AttendanceRecord.subject_id == subject.id,
            models.AttendanceRecord.source_file == filename).delete()
        db.commit()
        n = 0
        for roll, name, attended in parsed["students"]:
            student = crud.get_student_by_roll(db, roll)
            if not student:
                student = models.Student(roll_number=roll, name=name,
                                         class_id=cls.id)
                db.add(student)
                db.commit()
                db.refresh(student)
            elif name != "Unknown" and student.name in ("Unknown", "", None):
                student.name = name
                db.commit()
            db.add(models.AttendanceRecord(
                student_id=student.id,
                faculty_id=faculty.id if faculty else None,
                subject_id=subject.id,
                semester=semester,
                classes_conducted=parsed["total_classes"],
                classes_attended=attended,
                source_file=filename,
            ))
            n += 1
            students_seen.add(student.id)
        db.commit()
        total_records += n
        sheets_summary.append({
            "sheet": sh,
            "subject": subject.code,
            "subject_name": subject.name,
            "faculty": faculty.name if faculty else "—",
            "status": "imported",
            "rows": n,
            "total_classes": parsed["total_classes"],
        })

    for sid in students_seen:
        crud.compute_eligibility_for_student(db, sid, mst_exam_id)

    db.add(models.AuditLog(
        table_name="attendance_records", record_id=0, field_changed="import",
        new_value=f"{total_records} rows across "
                  f"{sum(1 for s in sheets_summary if s['status'] == 'imported')} subjects",
        reason=filename,
    ))
    db.commit()

    imported = [s for s in sheets_summary if s["status"] == "imported"]
    if not imported:
        raise HTTPException(
            status_code=400,
            detail="No subject attendance sheets found. Expected sheets with "
                   "'Subject Code' and 'Enrollment No.' headers. "
                   + "; ".join(f"{s['sheet']}: {s['reason']}" for s in sheets_summary))
    return {"filename": filename, "format": "subject_sheets",
            "class": cls.name,
            "subjects_imported": len(imported),
            "rows_imported": total_records,
            "sheets": sheets_summary}

@app.post("/upload-attendance/")
async def upload_attendance(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    if not file.filename.endswith(('.xls', '.xlsx')):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload an Excel file.")

    contents = await file.read()
    try:
        xls = pd.ExcelFile(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read Excel file: {e}")

    # Per-subject workbook (e.g. CI-1 IV.xlsx): one sheet per subject with
    # 'Subject Code' / 'Enrollment No.' headers — parse every subject sheet.
    try:
        probe = [_parse_subject_sheet(xls.parse(sh, header=None))
                 for sh in xls.sheet_names]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read Excel file: {e}")
    if any(p for p in probe):
        return _import_subject_workbook(db, xls, file.filename)

    try:
        df = xls.parse(xls.sheet_names[0])
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

# Timetable rows store abbreviated days: MON, TUE, WED, THUR, FRI.
# strftime("%a") gives MON, TUE, WED, THU, FRI — normalize THU -> THUR.
_DAY_ALIASES = {"THU": "THUR"}


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
    # Appearance changed -> VT/follow-up rule must be re-evaluated
    crud.recalculate_follow_up(db, att.student_id)
    return {"student_id": att.student_id, "status": att.status, "marked_at": att.marked_at}


@app.get("/mst/attendance/{mst_exam_id}")
def get_attendance(mst_exam_id: int, db: Session = Depends(get_db)):
    rows = db.query(models.MstAttempt).filter_by(mst_exam_id=mst_exam_id).all()
    return [{"student_id": a.student_id, "status": a.status, "marked_at": a.marked_at}
            for a in rows]


# ── VT / follow-up ────────────────────────────────────────────────────────────

def _follow_up_row_out(row, student, class_name):
    return {
        "id": row.id,
        "student_id": row.student_id,
        "roll_number": student.roll_number if student else None,
        "name": student.name if student else None,
        "class_id": student.class_id if student else None,
        "class_name": class_name,
        "mst_1_appeared": row.mst_1_appeared,
        "mst_2_appeared": row.mst_2_appeared,
        "calculated_status": row.calculated_status,
        "final_status": row.final_status,
        "override": row.override,
        "override_reason": row.override_reason,
        "rule_version": row.rule_version,
        "updated_at": row.updated_at,
    }

@app.get("/follow-up")
def list_follow_up(
    class_id: int = None,
    calculated_status: str = None,
    final_status: str = None,
    overridden: bool = None,
    search: str = None,
    db: Session = Depends(get_db),
):
    q = (
        db.query(models.FollowUpStatus, models.Student, models.Class.name)
        .join(models.Student, models.FollowUpStatus.student_id == models.Student.id)
        .join(models.Class, models.Student.class_id == models.Class.id)
    )
    if class_id:
        q = q.filter(models.Student.class_id == class_id)
    if calculated_status:
        q = q.filter(models.FollowUpStatus.calculated_status == calculated_status)
    if final_status:
        q = q.filter(models.FollowUpStatus.final_status == final_status)
    if overridden is not None:
        q = q.filter(models.FollowUpStatus.override.is_(overridden))
    if search:
        like = f"%{search}%"
        q = q.filter(
            (models.Student.roll_number.ilike(like)) |
            (models.Student.name.ilike(like))
        )
    rows = q.order_by(models.Student.roll_number).all()
    return [_follow_up_row_out(f, s, cname) for f, s, cname in rows]


@app.get("/follow-up/stats")
def follow_up_stats(class_id: int = None, db: Session = Depends(get_db)):
    from sqlalchemy import func
    q = db.query(
        models.FollowUpStatus.final_status,
        func.count(models.FollowUpStatus.id),
    )
    if class_id:
        q = q.join(models.Student,
                   models.FollowUpStatus.student_id == models.Student.id)\
             .filter(models.Student.class_id == class_id)
    by_final = dict(q.group_by(models.FollowUpStatus.final_status).all())

    q2 = db.query(
        models.FollowUpStatus.calculated_status,
        func.count(models.FollowUpStatus.id),
    )
    if class_id:
        q2 = q2.join(models.Student,
                     models.FollowUpStatus.student_id == models.Student.id)\
               .filter(models.Student.class_id == class_id)
    by_calculated = dict(q2.group_by(models.FollowUpStatus.calculated_status).all())

    total = sum(by_final.values())
    students_total = db.query(func.count(models.Student.id))\
        .filter(models.Student.active.is_(True))
    if class_id:
        students_total = students_total.filter(models.Student.class_id == class_id)
    students_total = students_total.scalar()

    return {
        "total_evaluated": total,
        "total_students": students_total,
        "missing_records": max(students_total - total, 0),
        "by_final_status": by_final,
        "by_calculated_status": by_calculated,
    }


class FollowUpRecalcIn(BaseModel):
    class_id: int = None

@app.post("/follow-up/recalculate")
def recalculate_follow_ups(req: FollowUpRecalcIn, db: Session = Depends(get_db)):
    result = crud.recalculate_all_follow_ups(db, class_id=req.class_id)
    _ensure_follow_up_view()  # keep the AI view in sync
    return result


class FollowUpOverrideIn(BaseModel):
    final_status: str
    reason: str
    changed_by: int = None

@app.post("/follow-up/{follow_up_id}/override")
def override_follow_up(follow_up_id: int, req: FollowUpOverrideIn,
                       db: Session = Depends(get_db)):
    try:
        row = crud.override_follow_up(
            db, follow_up_id, req.final_status, req.reason, req.changed_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    student = db.query(models.Student).filter_by(id=row.student_id).first()
    return _follow_up_row_out(
        row, student, student and db.query(models.Class.name)
        .filter_by(id=student.class_id).scalar())


class FollowUpRestoreIn(BaseModel):
    reason: str
    changed_by: int = None

@app.post("/follow-up/{follow_up_id}/restore")
def restore_follow_up(follow_up_id: int, req: FollowUpRestoreIn,
                      db: Session = Depends(get_db)):
    try:
        row = crud.restore_calculated_follow_up(
            db, follow_up_id, req.reason, req.changed_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    student = db.query(models.Student).filter_by(id=row.student_id).first()
    return _follow_up_row_out(
        row, student, student and db.query(models.Class.name)
        .filter_by(id=student.class_id).scalar())


def _compulsory_follow_up_rows(db: Session, class_id: int = None):
    q = (
        db.query(models.FollowUpStatus, models.Student, models.Class.name)
        .join(models.Student, models.FollowUpStatus.student_id == models.Student.id)
        .join(models.Class, models.Student.class_id == models.Class.id)
        .filter(models.FollowUpStatus.final_status == "compulsory")
    )
    if class_id:
        q = q.filter(models.Student.class_id == class_id)
    return q.order_by(models.Class.name, models.Student.roll_number).all()


@app.get("/follow-up/export")
def export_follow_up_excel(class_id: int = None, db: Session = Depends(get_db)):
    rows = _compulsory_follow_up_rows(db, class_id)
    data = [{
        "Roll Number": s.roll_number,
        "Name": s.name,
        "Class": cname,
        "MST-1": "Present" if f.mst_1_appeared else "Absent" if f.mst_1_appeared is False else "Missing",
        "MST-2": "Present" if f.mst_2_appeared else "Absent" if f.mst_2_appeared is False else "Missing",
        "Calculated": f.calculated_status,
        "Final": f.final_status,
        "Overridden": "Yes" if f.override else "No",
        "Override Reason": f.override_reason or "",
    } for f, s, cname in rows]
    df = pd.DataFrame(data, columns=[
        "Roll Number", "Name", "Class", "MST-1", "MST-2",
        "Calculated", "Final", "Overridden", "Override Reason"])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="VT Compulsory", index=False)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=vt_compulsory_list.xlsx"},
    )


@app.get("/follow-up/export-pdf")
def export_follow_up_pdf(class_id: int = None, db: Session = Depends(get_db)):
    rows = _compulsory_follow_up_rows(db, class_id)
    html = pdf_service.build_follow_up_list_html(rows)
    pdf_bytes = pdf_service.render_pdf(html)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=vt_compulsory_list.pdf"},
    )


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


class AutoScheduleIn(BaseModel):
    mst_exam_ids: list[int]

@app.post("/mst/duties/auto-schedule")
def auto_schedule_duties(req: AutoScheduleIn, db: Session = Depends(get_db)):
    """Propose invigilation duties. Nothing is saved — review first, then apply."""
    if not req.mst_exam_ids:
        raise HTTPException(status_code=400, detail="Pick at least one exam")
    return crud.propose_invigilation_duties(db, req.mst_exam_ids)


class ApplyProposalIn(BaseModel):
    assignments: list[dict]   # [{mst_exam_id, room_id, faculty_id}]
    changed_by: int = None

@app.post("/mst/duties/auto-schedule/apply")
def apply_scheduled_duties(req: ApplyProposalIn, db: Session = Depends(get_db)):
    """Save a reviewed proposal. Every assignment is audit-logged."""
    for a in req.assignments:
        if not all(k in a for k in ("mst_exam_id", "room_id", "faculty_id")):
            raise HTTPException(status_code=400, detail=f"Bad assignment: {a}")
    return crud.apply_duty_proposal(db, req.assignments, req.changed_by)


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

    day = exam.exam_date.strftime("%a").upper() if exam.exam_date else None
    if day:
        day = _DAY_ALIASES.get(day, day)  # match stored MON/TUE/WED/THUR/FRI values
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


# ── Faculty × MST timetable grid ─────────────────────────────────────────────

@app.get("/mst/faculty-grid")
def faculty_exam_grid(db: Session = Depends(get_db)):
    """
    Returns every exam slot × every faculty member so the frontend can render
    a full free/busy timetable grid without multiple round-trips.
    """
    exams = db.query(models.MstExam).order_by(
        models.MstExam.exam_date, models.MstExam.time_slot).all()
    all_faculty = db.query(models.Faculty).order_by(models.Faculty.name).all()
    all_duties = db.query(models.InvigilationDuty).all()
    rooms_map = {r.id: r.room_number for r in db.query(models.Room).all()}

    # duty lookup: {(exam_id, faculty_id): room_number}
    duty_lookup: dict[tuple, str] = {}
    for d in all_duties:
        if d.faculty_id:
            duty_lookup[(d.mst_exam_id, d.faculty_id)] = rooms_map.get(d.room_id, "?")

    exam_rows = []
    for exam in exams:
        day = exam.exam_date.strftime("%a").upper() if exam.exam_date else None
        if day:
            day = _DAY_ALIASES.get(day, day)
        start, end = "09:00", "12:00"
        if exam.time_slot and "-" in exam.time_slot:
            parts = [p.strip() for p in exam.time_slot.split("-", 1)]
            if len(parts) == 2 and all(parts):
                start, end = parts

        if day:
            avail_list = crud.check_faculty_availability(db, day, start, end)
            avail_map = {r.faculty_id: r.status for r in avail_list}
        else:
            avail_map = {}

        faculty_cells = []
        for f in all_faculty:
            if (exam.id, f.id) in duty_lookup:
                cell_status = "on_duty"
                cell_reason = f"Room {duty_lookup[(exam.id, f.id)]}"
            elif f.exempt_from_duty:
                cell_status = "exempt"
                cell_reason = f.exempt_reason or "Exempt"
            else:
                raw = avail_map.get(f.id, "Available")
                if raw == "Blocked":
                    cell_status = "teaching"
                    cell_reason = "Teaching"
                else:
                    cell_status = "free"
                    cell_reason = "Free"
            faculty_cells.append({
                "faculty_id": f.id,
                "status": cell_status,
                "reason": cell_reason,
            })

        exam_rows.append({
            "exam_id": exam.id,
            "label": exam.label,
            "exam_date": exam.exam_date.isoformat() if exam.exam_date else None,
            "time_slot": exam.time_slot,
            "faculty": faculty_cells,
        })

    return {
        "exams": exam_rows,
        "faculty": [{"id": f.id, "name": f.name, "abbreviation": f.abbreviation} for f in all_faculty],
    }


# ── MST Roll-call attendance (no seating plan required) ──────────────────────

@app.get("/mst/attendance/rollcall/{mst_exam_id}")
def get_rollcall(mst_exam_id: int, db: Session = Depends(get_db)):
    """
    Returns all eligible/seatable students for an exam with their current
    attendance status so the teacher can do a fast roll-call.
    Works even when no seating plan has been generated.
    """
    exam = db.query(models.MstExam).filter_by(id=mst_exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    # Fetch students scoped to the exam's class (or all if no class attached)
    q = db.query(models.Student).filter_by(active=True)
    if exam.class_id:
        q = q.filter_by(class_id=exam.class_id)
    students = q.order_by(models.Student.roll_number).all()

    # Fetch existing attempt records
    attempts = {
        a.student_id: a.status
        for a in db.query(models.MstAttempt).filter_by(mst_exam_id=mst_exam_id).all()
    }

    classes_map = {c.id: c.name for c in db.query(models.Class).all()}

    return [
        {
            "student_id": s.id,
            "roll_number": s.roll_number,
            "name": s.name,
            "batch_number": s.batch_number,
            "class_name": classes_map.get(s.class_id, ""),
            "status": attempts.get(s.id),  # None if not yet marked
        }
        for s in students
    ]


# ── AI health (provider status for the UI banner) ──────────────────────────────

@app.get("/ai/health")
async def ai_health():
    """Returns which AI providers are configured so the UI can show a status."""
    import os
    providers = []
    if os.environ.get("GROQ_API_KEY"):
        providers.append({"name": "groq", "configured": True})
    else:
        providers.append({"name": "groq", "configured": False, "hint": "Set GROQ_API_KEY in backend/.env"})
    if os.environ.get("GEMINI_API_KEY"):
        providers.append({"name": "gemini", "configured": True})
    else:
        providers.append({"name": "gemini", "configured": False, "hint": "Set GEMINI_API_KEY in backend/.env"})
    import httpx
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get("http://localhost:11434/api/tags")
            ollama_ok = r.status_code == 200
    except Exception:
        pass
    providers.append({"name": "ollama", "configured": ollama_ok})
    any_ok = any(p["configured"] for p in providers)
    return {"ready": any_ok, "providers": providers}
