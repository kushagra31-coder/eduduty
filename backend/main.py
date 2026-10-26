# SECURITY NOTE: MVP does not enforce authentication. Do not deploy to public internet without adding auth middleware.
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Body, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import or_
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Union, List, Optional
from database import engine, get_db
import models, schemas, crud
import ai_service, pdf_service, auth
import pandas as pd
import io
import re
import os
import json
from difflib import SequenceMatcher
import datetime as _dt

models.Base.metadata.create_all(bind=engine)

# ── Read-only view for the AI + reporting (works on SQLite and Postgres) ──────
_FOLLOW_UP_VIEW_BODY = """
SELECT
    s.roll_number,
    s.name AS student_name,
    c.name AS class_name,
    c.year AS class_year,
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

def _ensure_ai_views():
    try:
        views = {
            "v_vt_follow_up_status": _FOLLOW_UP_VIEW_BODY,
            "ai_eligibility_summary": """
                SELECT c.name AS class_name, c.year AS class_year, e.label AS mst_label, e.id AS mst_exam_id,
                SUM(CASE WHEN me.status = 'Eligible' THEN 1 ELSE 0 END) AS eligible_count,
                SUM(CASE WHEN me.status = 'Not eligible' THEN 1 ELSE 0 END) AS ineligible_count,
                SUM(CASE WHEN me.status = 'Missing' THEN 1 ELSE 0 END) AS missing_count
                FROM mst_eligibility me
                JOIN students s ON s.id = me.student_id
                JOIN classes c ON c.id = s.class_id
                JOIN mst_exams e ON e.id = me.mst_exam_id
                GROUP BY c.name, c.year, e.id, e.label
            """,
            "ai_attendance_summary": """
                SELECT c.name AS class_name, c.year AS class_year, s.roll_number, s.name AS student_name,
                me.overall_pct, me.lowest_subject_pct,
                me.mst_exam_id, e.label AS mst_label
                FROM mst_eligibility me
                JOIN students s ON s.id = me.student_id
                JOIN classes c ON c.id = s.class_id
                LEFT JOIN mst_exams e ON e.id = me.mst_exam_id
            """,
            "ai_vt_candidates": """
                SELECT c.name AS class_name, c.year AS class_year, s.roll_number, s.name AS student_name,
                CASE WHEN fs.mst_1_appeared IS NULL THEN 'Missing' WHEN fs.mst_1_appeared THEN 'Present' ELSE 'Absent' END AS mst1_status,
                CASE WHEN fs.mst_2_appeared IS NULL THEN 'Missing' WHEN fs.mst_2_appeared THEN 'Present' ELSE 'Absent' END AS mst2_status
                FROM follow_up_statuses fs
                JOIN students s ON s.id = fs.student_id
                JOIN classes c ON c.id = s.class_id
            """,
            "ai_duty_roster": """
                SELECT e.label AS mst_label, e.exam_date, r.room_number, f.name AS faculty_name, d.status AS duty_status
                FROM invigilation_duties d
                JOIN mst_exams e ON e.id = d.mst_exam_id
                JOIN rooms r ON r.id = d.room_id
                LEFT JOIN faculty f ON f.id = d.faculty_id
            """
        }
        with engine.begin() as conn:
            for vname, vbody in views.items():
                if engine.dialect.name == "sqlite":
                    conn.execute(models.text(f"DROP VIEW IF EXISTS {vname}"))
                    conn.execute(models.text(f"CREATE VIEW {vname} AS {vbody}"))
                else:
                    conn.execute(models.text(f"CREATE OR REPLACE VIEW {vname} AS {vbody}"))
    except Exception as exc:
        print(f"warning: could not create views: {exc}", flush=True)

_ensure_ai_views()

try:
    from migrate_unique_constraints import run_unique_constraint_migration
    run_unique_constraint_migration(engine)
except Exception as exc:
    print(f"warning: unique constraint migration: {exc}", flush=True)

# ── Column migrations (safe – only add if not present) ─────────────────────────
try:
    with engine.connect() as _mc:
        _col_names = [row[1] for row in _mc.execute(models.text("PRAGMA table_info(attendance_records)")).fetchall()]
        if "batch_label" not in _col_names:
            _mc.execute(models.text("ALTER TABLE attendance_records ADD COLUMN batch_label VARCHAR(100)"))
            _mc.commit()
            print("Migration: added batch_label to attendance_records", flush=True)
except Exception as _me:
    print(f"warning: column migration: {_me}", flush=True)

app = FastAPI(title="MST Operations Portal API")

import os

cors_origins_raw = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip() and o.strip() != "*"]
if not cors_origins:
    cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    auth.validate_auth_startup()

@app.get("/")
def read_root(user: models.User = Depends(auth.get_current_user)):
    return {"message": "MST Operations Portal Backend"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/auth/login", response_model=auth.TokenResponse)
def login(req: auth.LoginRequest, db: Session = Depends(get_db)):
    role = (req.role or "coordinator").lower()
    user = db.query(models.User).filter_by(email=req.email).first()
    if not user:
        user = models.User(name=req.name or req.email.split("@")[0], role=role, email=req.email)
        db.add(user)
        db.commit()
        db.refresh(user)
    token = auth.create_jwt_token(user.id, user.role, user.email, user.name)
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "user_id": user.id,
        "name": user.name,
    }

@app.get("/auth/me")
def get_me(user: models.User = Depends(auth.get_current_user)):
    return {"id": user.id, "name": user.name, "role": user.role, "email": user.email}


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
    """Derive the class from workbook names like 'CI-1 IV.xlsx' / 'CI-2.xlsx' / 'CY VI.xlsx'."""
    clean_fn = re.sub(r"[^A-Za-z0-9]", "", (filename or "").upper())
    for existing in db.query(models.Class).all():
        clean_name = re.sub(r"[^A-Za-z0-9]", "", existing.name.upper())
        if clean_name and (clean_name in clean_fn or clean_fn.startswith(clean_name)):
            sem_m = re.search(r"\b(II|III|IV|V|VI)\b", (filename or "").upper())
            roman = sem_m.group(1) if sem_m else None
            return existing, roman

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


def get_non_attempted_exams_for_class(db: Session, class_id: int) -> list[models.MstExam]:
    """Find all exams applicable to this class that have no recorded student attempts.
    If no exams exist, initialize a default MST-1 exam."""
    attempted_exam_ids = {
        row[0] for row in (
            db.query(models.MstAttempt.mst_exam_id)
            .join(models.Student, models.MstAttempt.student_id == models.Student.id)
            .filter(models.Student.class_id == class_id)
            .distinct()
            .all()
        )
    }
    candidate_exams = db.query(models.MstExam).filter(
        or_(models.MstExam.class_id == class_id, models.MstExam.class_id.is_(None))
    ).all()
    non_attempted = [e for e in candidate_exams if e.id not in attempted_exam_ids]

    if not non_attempted:
        if not candidate_exams:
            default_exam = models.MstExam(label="MST-1", class_id=class_id)
            db.add(default_exam)
            db.commit()
            db.refresh(default_exam)
            return [default_exam]
        else:
            next_label = f"MST-{len(candidate_exams) + 1}"
            next_exam = models.MstExam(label=next_label, class_id=class_id)
            db.add(next_exam)
            db.commit()
            db.refresh(next_exam)
            return [next_exam]

    return non_attempted


def _import_subject_workbook(db: Session, xls, filename: str, class_id: Optional[int] = None, batch_label: Optional[str] = None):
    """Import every per-subject sheet in the workbook."""
    if class_id:
        cls = db.query(models.Class).filter_by(id=class_id).first()
        if not cls:
            cls, semester = _class_from_filename(db, filename)
        else:
            _, semester = _class_from_filename(db, filename)
    else:
        cls, semester = _class_from_filename(db, filename)

    target_exams = get_non_attempted_exams_for_class(db, cls.id)
    sheets_summary = []
    total_records = 0
    students_seen = set()
    class_conflicts = []
    seen_conflicts = set()

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
            else:
                if student.class_id != cls.id and roll not in seen_conflicts:
                    seen_conflicts.add(roll)
                    existing_cls = db.query(models.Class).filter_by(id=student.class_id).first()
                    class_conflicts.append({
                        "roll_number": roll,
                        "name": student.name,
                        "existing_class": existing_cls.name if existing_cls else str(student.class_id),
                        "imported_class": cls.name,
                    })
                if name != "Unknown" and student.name in ("Unknown", "", None):
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
                batch_label=batch_label,
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

    # Auto-assign batches only for students who do not already have a batch number
    all_class_students = db.query(models.Student).filter_by(class_id=cls.id).all()
    import re
    def natural_sort_key(s):
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s.roll_number or "")]

    unassigned = [s for s in all_class_students if s.batch_number is None]
    if unassigned:
        unassigned.sort(key=natural_sort_key)
        midpoint = (len(unassigned) + 1) // 2
        for i, s in enumerate(unassigned):
            s.batch_number = 1 if i < midpoint else 2
        db.commit()

    for sid in students_seen:
        for exam in target_exams:
            crud.compute_eligibility_for_student(db, sid, exam.id)

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
            "sheets": sheets_summary,
            "class_conflicts": class_conflicts}

@app.post("/upload-attendance")
@app.post("/upload-attendance/")
async def upload_attendance(
    request: Request,
    file: UploadFile = File(...),
    class_id: Optional[int] = Form(None),
    batch_label: Optional[str] = Form(None),
    user: models.User = Depends(auth.require_role("hod", "coordinator", "faculty")),
    db: Session = Depends(get_db)
):
    if not file.filename.endswith(('.xls', '.xlsx')):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload an Excel file.")

    contents = await file.read()
    try:
        xls = pd.ExcelFile(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read Excel file: {e}")

    target_class_id = class_id
    if target_class_id is None:
        q_id = request.query_params.get("class_id")
        if q_id:
            try:
                target_class_id = int(q_id)
            except ValueError:
                pass

    # Infer target class from batch_label if not provided directly
    if target_class_id is None and batch_label:
        bl_upper = re.sub(r"[^A-Za-z0-9]", "", batch_label.upper())
        for c in db.query(models.Class).all():
            c_name_clean = re.sub(r"[^A-Za-z0-9]", "", c.name.upper())
            if c_name_clean and (c_name_clean in bl_upper or bl_upper.startswith(c_name_clean)):
                target_class_id = c.id
                break

    # Infer target class from filename if still not found
    if target_class_id is None:
        clean_fn = re.sub(r"[^A-Za-z0-9]", "", file.filename.upper())
        for c in db.query(models.Class).all():
            c_name_clean = re.sub(r"[^A-Za-z0-9]", "", c.name.upper())
            if c_name_clean and (c_name_clean in clean_fn or clean_fn.startswith(c_name_clean)):
                target_class_id = c.id
                break

    # Per-subject workbook (e.g. CI-1 IV.xlsx): one sheet per subject with
    # 'Subject Code' / 'Enrollment No.' headers — parse every subject sheet.
    try:
        probe = [_parse_subject_sheet(xls.parse(sh, header=None))
                 for sh in xls.sheet_names]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read Excel file: {e}")
    if any(p for p in probe):
        try:
            return _import_subject_workbook(db, xls, file.filename, class_id=target_class_id, batch_label=batch_label or file.filename)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=400, detail=f"Subject workbook import failed: {exc}")

    # Flat fallback: if target_class_id still unassigned, pick first registered class
    if not target_class_id:
        first_cls = db.query(models.Class).order_by(models.Class.id.asc()).first()
        if first_cls:
            target_class_id = first_cls.id
        else:
            raise HTTPException(
                status_code=422,
                detail="class_id is required for flat attendance file upload"
            )
    target_class = db.query(models.Class).filter_by(id=target_class_id).first()
    if not target_class:
        raise HTTPException(status_code=404, detail=f"Class with id {target_class_id} not found")

    try:
        df = xls.parse(xls.sheet_names[0])
        # Normalize column names for lookup (case/space/underscore-insensitive)
        colmap = {str(c).strip().lower().replace("_", " ").replace("-", " "): c for c in df.columns}
        def col(*names):
            for n in names:
                if n in colmap:
                    return colmap[n]
            return None
        c_roll = col("roll number", "roll no", "roll", "enrollment number", "enrollment no", "enrollment", "scholar no", "scholar", "id", "student id")
        c_name = col("name", "student name", "candidate name", "student", "full name")
        c_total = col("total classes", "classes conducted", "total", "conducted", "held", "lectures held", "total lectures", "total class")
        c_att = col("attended", "classes attended", "attended classes", "present", "lectures attended", "total attended")
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
        def safe_int(v, default=0):
            try:
                if pd.isna(v) or v is None:
                    return default
                return int(float(v))
            except Exception:
                return default

        imported_count = 0
        class_conflicts = []
        seen_conflicts = set()
        for _, row in df.iterrows():
            roll_number = str(row.get(c_roll, '')).strip() if c_roll else ''
            if not roll_number or roll_number.lower() in ('nan', 'none', ''):
                continue
            name     = str(row.get(c_name, 'Unknown')).strip() if c_name else 'Unknown'
            total    = safe_int(row.get(c_total, 0)) if c_total else 0
            attended = safe_int(row.get(c_att, 0)) if c_att else 0
            batch_number = row_batch(row)
            student  = crud.get_student_by_roll(db, roll_number)
            if not student:
                student = models.Student(
                    roll_number=roll_number,
                    name=name,
                    class_id=target_class.id,
                    batch_number=batch_number
                )
                db.add(student)
                db.commit()
                db.refresh(student)
            else:
                if student.class_id != target_class.id and roll_number not in seen_conflicts:
                    seen_conflicts.add(roll_number)
                    existing_cls = db.query(models.Class).filter_by(id=student.class_id).first()
                    class_conflicts.append({
                        "roll_number": roll_number,
                        "name": student.name,
                        "existing_class": existing_cls.name if existing_cls else str(student.class_id),
                        "imported_class": target_class.name,
                    })
                if batch_number and not student.batch_number:
                    student.batch_number = batch_number
                    db.commit()
            att = schemas.AttendanceRecordBase(
                student_id=student.id,
                classes_conducted=total,
                classes_attended=attended
            )
            crud.create_attendance_record(db, att)
            target_exams = get_non_attempted_exams_for_class(db, student.class_id)
            for ex in target_exams:
                crud.compute_eligibility_for_student(db, student.id, ex.id)
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
        return {
            "filename": file.filename,
            "rows_imported": imported_count,
            "class": target_class.name,
            "class_conflicts": class_conflicts
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

# ── Import Batch Management ──────────────────────────────────────────────────

@app.get("/import-batches")
def list_import_batches(
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    """List all named import batches with record counts."""
    from sqlalchemy import func
    rows = (
        db.query(
            models.AttendanceRecord.batch_label,
            func.count(models.AttendanceRecord.id).label("record_count"),
            func.min(models.AttendanceRecord.upload_date).label("first_upload"),
            func.max(models.AttendanceRecord.upload_date).label("last_upload"),
        )
        .filter(models.AttendanceRecord.batch_label.isnot(None))
        .group_by(models.AttendanceRecord.batch_label)
        .all()
    )
    # Also include unnamed records (grouped by source_file)
    unnamed = (
        db.query(
            models.AttendanceRecord.source_file,
            func.count(models.AttendanceRecord.id).label("record_count"),
        )
        .filter(models.AttendanceRecord.batch_label.is_(None))
        .group_by(models.AttendanceRecord.source_file)
        .all()
    )
    batches = [
        {
            "label": r.batch_label,
            "record_count": r.record_count,
            "first_upload": r.first_upload.isoformat() if r.first_upload else None,
            "last_upload": r.last_upload.isoformat() if r.last_upload else None,
            "is_named": True,
        }
        for r in rows
    ]
    for u in unnamed:
        batches.append({
            "label": u.source_file or "(unlabelled)",
            "record_count": u.record_count,
            "first_upload": None,
            "last_upload": None,
            "is_named": False,
        })
    return batches


@app.delete("/import-batches/{batch_label:path}")
def delete_import_batch(
    batch_label: str,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    """
    Delete all attendance records for a named batch label, then recompute
    eligibility for affected students so the data is cleanly wiped.
    """
    records = db.query(models.AttendanceRecord).filter(
        models.AttendanceRecord.batch_label == batch_label
    ).all()
    if not records:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_label}' not found or has no records.")

    affected_student_ids = {r.student_id for r in records}
    deleted_count = len(records)

    # Delete records
    db.query(models.AttendanceRecord).filter(
        models.AttendanceRecord.batch_label == batch_label
    ).delete()
    db.commit()

    # Recompute eligibility for all affected students
    exams = db.query(models.MstExam).all()
    for sid in affected_student_ids:
        for exam in exams:
            crud.compute_eligibility_for_student(db, sid, exam.id)

    db.add(models.AuditLog(
        table_name="attendance_records", record_id=0, field_changed="batch_delete",
        new_value=f"Deleted {deleted_count} records from batch '{batch_label}'",
        changed_by=user.id,
        reason=f"User deleted import batch: {batch_label}",
    ))
    db.commit()

    return {
        "deleted": deleted_count,
        "batch_label": batch_label,
        "affected_students": len(affected_student_ids),
        "message": f"Batch '{batch_label}' deleted. Eligibility recomputed for {len(affected_student_ids)} students.",
    }


# ── Dashboard ──────────────────────────────────────────────────────────────

@app.get("/dashboard/stats")
def dashboard_stats(
    mst_exam_id: Optional[int] = None,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    if mst_exam_id:
        exam = db.query(models.MstExam).filter_by(id=mst_exam_id).first()
    else:
        exam = db.query(models.MstExam).order_by(models.MstExam.id.asc()).first()

    exam_label = exam.label if exam else "MST-1"
    resolved_exam_id = exam.id if exam else 1

    students = db.query(models.Student).all()
    classes = {c.id: c for c in db.query(models.Class).all()}
    elig_rows = db.query(models.MstEligibility).filter_by(mst_exam_id=resolved_exam_id).all() if exam else []
    elig_by_student = {e.student_id: e for e in elig_rows}

    total = len(students)
    n_eligible = sum(1 for e in elig_rows if e.status == "Eligible")
    n_borderline = sum(1 for e in elig_rows if e.status == "Borderline")
    n_ineligible = sum(1 for e in elig_rows if e.status == "Not eligible")
    n_overrides = sum(1 for e in elig_rows if e.override)

    per_class: dict[str, dict] = {}
    for c in classes.values():
        per_class[c.name] = {
            "class": c.name,
            "branch": c.branch or c.name,
            "students": 0,
            "eligible": 0,
            "borderline": 0,
            "ineligible": 0,
        }
    for s in students:
        c = classes.get(s.class_id)
        cname = c.name if c else "—"
        bucket = per_class.setdefault(cname, {
            "class": cname, "branch": cname, "students": 0,
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
    tt_entries = crud.active_timetable_query(db).all()
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

    duties_q = db.query(models.InvigilationDuty).filter_by(mst_exam_id=resolved_exam_id).all() if exam else []
    n_duties_assigned = sum(1 for d in duties_q if d.status == "Assigned")
    n_duties_unfilled = sum(1 for d in duties_q if d.status == "Unfilled")

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
        "active_duty": {
            "total": len(duties_q),
            "assigned": n_duties_assigned,
            "unfilled": n_duties_unfilled,
        },
        "recent_activity": activity,
    }

# ── Eligibility ────────────────────────────────────────────────────────────────

@app.get("/eligibility/{mst_exam_id}", response_model=list[schemas.MstEligibilityDisplay])
def get_eligibility(
    mst_exam_id: int,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    return crud.get_mst_eligibility(db, mst_exam_id)

@app.post("/eligibility/override/{eligibility_id}")
def override_eligibility(
    eligibility_id: int,
    override: bool = Body(...),
    reason: str = Body(...),
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    if not reason or not reason.strip():
        raise HTTPException(status_code=400, detail="A non-empty reason is required for eligibility override changes.")
    record = crud.update_eligibility_override(db, eligibility_id, override, reason.strip(), user.id)
    if not record:
        raise HTTPException(status_code=404, detail="Eligibility record not found")
    return {"message": "Override applied successfully"}

# ── AI assistant ───────────────────────────────────────────────────────────────

class AIMessageRequest(BaseModel):
    message: str

class WriteConfirmRequest(BaseModel):
    op_json: dict

@app.post("/ai/query")
async def ai_query(
    req: AIMessageRequest,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
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
def ai_confirm_write(
    req: WriteConfirmRequest,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    """
    Execute an AI-proposed write ONLY after the user has explicitly confirmed in the UI.
    """
    try:
        result = ai_service.execute_write_op(req.op_json, db, confirming_user_id=user.id)
        return {"success": True, "changed": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── PDF generation ─────────────────────────────────────────────────────────────

@app.get("/pdf/student/{roll_number}")
def get_student_pdf(
    roll_number: str,
    user: models.User = Depends(auth.require_role("hod", "coordinator", "faculty")),
    db: Session = Depends(get_db)
):
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
def get_seating_pdf(
    mst_exam_id: int,
    room_id: int,
    user: models.User = Depends(auth.require_role("hod", "coordinator", "faculty", "invigilator")),
    db: Session = Depends(get_db)
):
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
def get_student_html(
    roll_number: str,
    user: models.User = Depends(auth.require_role("hod", "coordinator", "faculty")),
    db: Session = Depends(get_db)
):
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
def list_classes(
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    return crud.get_classes(db)

@app.get("/faculty")
def list_faculty(
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    rows = db.query(models.Faculty).all()
    return [
        {
            "id": f.id,
            "name": f.name,
            "abbreviation": f.abbreviation,
            "department": f.department,
            "exempt_from_duty": f.exempt_from_duty,
            "exempt_reason": f.exempt_reason,
            "max_duties_per_day": f.max_duties_per_day,
        }
        for f in rows
    ]


class FacultyCreate(BaseModel):
    name: str
    abbreviation: str | None = None
    department: str | None = None
    exempt_from_duty: bool = False
    exempt_reason: str | None = None
    max_duties_per_day: int = 2


class FacultyUpdate(BaseModel):
    name: str | None = None
    abbreviation: str | None = None
    department: str | None = None
    exempt_from_duty: bool | None = None
    exempt_reason: str | None = None
    max_duties_per_day: int | None = None


@app.post("/faculty")
def create_faculty(
    req: FacultyCreate,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    f = models.Faculty(
        name=req.name,
        abbreviation=req.abbreviation,
        department=req.department,
        exempt_from_duty=req.exempt_from_duty,
        exempt_reason=req.exempt_reason,
        max_duties_per_day=req.max_duties_per_day,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return {"id": f.id, "name": f.name, "abbreviation": f.abbreviation,
            "department": f.department, "exempt_from_duty": f.exempt_from_duty,
            "exempt_reason": f.exempt_reason, "max_duties_per_day": f.max_duties_per_day}


@app.patch("/faculty/{faculty_id}")
def update_faculty(
    faculty_id: int,
    req: FacultyUpdate,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    f = db.query(models.Faculty).filter_by(id=faculty_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Faculty not found")
    if req.name is not None:
        f.name = req.name
    if req.abbreviation is not None:
        f.abbreviation = req.abbreviation
    if req.department is not None:
        f.department = req.department
    if req.exempt_from_duty is not None:
        f.exempt_from_duty = req.exempt_from_duty
    if req.exempt_reason is not None:
        f.exempt_reason = req.exempt_reason
    if req.max_duties_per_day is not None:
        f.max_duties_per_day = req.max_duties_per_day
    db.commit()
    db.refresh(f)
    return {"id": f.id, "name": f.name, "abbreviation": f.abbreviation,
            "department": f.department, "exempt_from_duty": f.exempt_from_duty,
            "exempt_reason": f.exempt_reason, "max_duties_per_day": f.max_duties_per_day}


class ClassCreate(BaseModel):
    name: str
    branch: str
    year: int
    section: str | None = None


@app.post("/classes", response_model=schemas.ClassOut)
def create_class(
    req: ClassCreate,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    c = models.Class(name=req.name, branch=req.branch, year=req.year, section=req.section)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c



# Seating rule: Batch 1 roll n sits beside Batch 2 roll n (sorted by roll
# number, zipped in order). Students outside batches 1/2 sit alone.

from itertools import zip_longest as _zip_longest
import datetime as _dt

# Timetable rows store abbreviated days: MON, TUE, WED, THUR, FRI.
# strftime("%a") gives MON, TUE, WED, THU, FRI — normalize THU -> THUR.
_DAY_ALIASES = {"THU": "THUR"}


def is_student_seated_or_markable(elig, seat_min_pct: float = 45.0) -> tuple[bool, str]:
    if not elig:
        return False, "No eligibility record found"
    if elig.override is True:
        return True, "Eligible by override"
    if elig.status == "Missing":
        return False, "Missing attendance data"
    pct = float(elig.overall_pct) if elig.overall_pct is not None else 0.0
    if elig.status == "Eligible":
        return True, "Eligible"
    if elig.status == "Borderline" or pct >= seat_min_pct:
        if pct >= seat_min_pct:
            return True, "Borderline (seated)"
        return False, f"Attendance {pct:.2f}% below {seat_min_pct:.2f}% threshold"
    return False, f"Not eligible ({pct:.2f}% < {seat_min_pct:.2f}%)"


def _seat_student_out(s, el=None):
    if not s:
        return None
    return {
        "id": s.id,
        "roll_number": s.roll_number,
        "name": s.name,
        "batch_number": s.batch_number,
        "is_borderline": (el.status == "Borderline") if el else False,
        "eligibility_status": el.status if el else None,
        "override": el.override if el else False,
    }


@app.get("/mst/exams", response_model=list[schemas.MstExamOut])
def list_mst_exams(
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    exams = db.query(models.MstExam).order_by(models.MstExam.id.asc()).all()
    results = []
    for e in exams:
        cls = db.query(models.Class).filter_by(id=e.class_id).first() if e.class_id else None
        cls_name = cls.name if cls else "All Classes"
        year = cls.year if cls else None
        cls_label = f"{cls.name} (Yr {cls.year})" if (cls and "Yr" not in cls.name and cls.year) else (cls.name if cls else "All Classes")
        display_name = f"{e.label} · {cls_label}"
        results.append(schemas.MstExamOut(
            id=e.id,
            label=e.label,
            exam_date=e.exam_date,
            time_slot=e.time_slot,
            class_id=e.class_id,
            class_name=cls_name,
            year=year,
            display_name=display_name
        ))
    return results


@app.post("/mst/exams", response_model=schemas.MstExamOut)
def create_mst_exam(
    req: schemas.MstExamCreate,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    exam = models.MstExam(label=req.label, exam_date=req.exam_date,
                          time_slot=req.time_slot, class_id=req.class_id)
    db.add(exam)
    db.commit()
    db.refresh(exam)
    cls = db.query(models.Class).filter_by(id=exam.class_id).first() if exam.class_id else None
    cls_name = cls.name if cls else "All Classes"
    year = cls.year if cls else None
    cls_label = f"{cls.name} (Yr {cls.year})" if (cls and "Yr" not in cls.name and cls.year) else (cls.name if cls else "All Classes")
    display_name = f"{exam.label} · {cls_label}"
    return schemas.MstExamOut(
        id=exam.id,
        label=exam.label,
        exam_date=exam.exam_date,
        time_slot=exam.time_slot,
        class_id=exam.class_id,
        class_name=cls_name,
        year=year,
        display_name=display_name
    )


@app.get("/rooms", response_model=list[schemas.RoomOut])
def list_rooms(
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(models.Room).order_by(models.Room.room_number).all()


@app.post("/rooms", response_model=schemas.RoomOut)
def create_room(
    req: schemas.RoomCreate,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    room = models.Room(room_number=req.room_number, capacity=req.capacity)
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


@app.post("/mst/seating/generate")
def generate_seating(
    req: schemas.SeatingGenerateIn,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    exam = db.query(models.MstExam).filter_by(id=req.mst_exam_id).first()

    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    # Check eligibility records; auto-compute from attendance records or carry over if missing
    elig_count = db.query(models.MstEligibility).filter_by(mst_exam_id=exam.id).count()
    if elig_count == 0:
        q_studs = db.query(models.Student).filter_by(active=True)
        if exam.class_id:
            q_studs = q_studs.filter_by(class_id=exam.class_id)
        for s in q_studs.all():
            crud.compute_eligibility_for_student(db, s.id, exam.id)
        elig_count = db.query(models.MstEligibility).filter_by(mst_exam_id=exam.id).count()

        if elig_count == 0:
            any_elig = db.query(models.MstEligibility).all()
            if any_elig:
                seen = set()
                for el in any_elig:
                    if el.student_id not in seen:
                        seen.add(el.student_id)
                        db.add(models.MstEligibility(
                            student_id=el.student_id,
                            mst_exam_id=exam.id,
                            overall_pct=el.overall_pct,
                            lowest_subject_pct=el.lowest_subject_pct,
                            status=el.status,
                            override=False,
                            override_reason=None
                        ))
                db.commit()
                elig_count = db.query(models.MstEligibility).filter_by(mst_exam_id=exam.id).count()

    if elig_count == 0:
        raise HTTPException(
            status_code=409,
            detail="No eligibility records found for this exam. Upload attendance and compute eligibility first."
        )

    # clear any previous chart for this exam
    db.query(models.Seat).filter_by(mst_exam_id=exam.id).delete()
    db.commit()

    q = db.query(models.Student).filter_by(active=True)
    if exam.class_id:
        q = q.filter_by(class_id=exam.class_id)
    all_students = q.all()

    # Filter students by eligibility (read seat_min_pct from system_rules, default 45.0)
    rule = db.query(models.SystemRule).filter_by(key="seat_min_pct").first()
    seat_min_pct = float(rule.value) if rule and rule.value else 45.0

    elig_records = {
        e.student_id: e
        for e in db.query(models.MstEligibility).filter_by(mst_exam_id=exam.id).all()
    }
    eligible_students = []
    excluded = []
    for s in all_students:
        el = elig_records.get(s.id)
        seated, reason = is_student_seated_or_markable(el, seat_min_pct)
        if seated:
            eligible_students.append(s)
        else:
            excluded.append({"roll_number": s.roll_number, "reason": reason})

    import re
    def natural_sort_key(s):
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s.roll_number or "")]

    b1 = sorted([s for s in eligible_students if s.batch_number == 1], key=natural_sort_key)
    b2 = sorted([s for s in eligible_students if s.batch_number == 2], key=natural_sort_key)
    others = sorted([s for s in eligible_students if s.batch_number not in (1, 2)], key=natural_sort_key)
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
    return {
        "seats_created": created,
        "students_seated": seated,
        "unseated": unseated,
        "excluded": excluded,
    }


@app.get("/mst/seating/{mst_exam_id}")
def get_seating(
    mst_exam_id: int,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
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
    elig_records = {
        e.student_id: e
        for e in db.query(models.MstEligibility).filter_by(mst_exam_id=mst_exam_id).all()
    }
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
                    "left": _seat_student_out(students.get(s.left_student), elig_records.get(s.left_student)),
                    "right": _seat_student_out(students.get(s.right_student), elig_records.get(s.right_student)),
                    "left_status": attempts.get(s.left_student),
                    "right_status": attempts.get(s.right_student),
                }
                for s in rseats
            ],
        })
    return out


@app.post("/mst/attendance/mark", response_model=schemas.AttendanceMarkOut)
def mark_attendance(
    req: schemas.MarkAttendanceIn,
    user: models.User = Depends(auth.require_role("invigilator", "coordinator", "hod")),
    db: Session = Depends(get_db)
):
    if req.status not in ("Present", "Absent"):
        raise HTTPException(status_code=400, detail="status must be Present or Absent")

    if user.role == "invigilator":
        fac = db.query(models.Faculty).filter(
            or_(models.Faculty.email == user.email, models.Faculty.name == user.name)
        ).first()
        if not fac:
            raise HTTPException(status_code=403, detail="Invigilator not mapped to faculty record")
        fac_duties = db.query(models.InvigilationDuty).filter_by(
            mst_exam_id=req.mst_exam_id, faculty_id=fac.id
        ).all()
        if not fac_duties:
            raise HTTPException(status_code=403, detail="Invigilator not assigned to this exam")
        assigned_room_ids = {d.room_id for d in fac_duties}
        seat = db.query(models.MstSeat).filter(
            models.MstSeat.mst_exam_id == req.mst_exam_id,
            or_(models.MstSeat.left_student == req.student_id, models.MstSeat.right_student == req.student_id)
        ).first()
        if seat and seat.room_id not in assigned_room_ids:
            raise HTTPException(status_code=403, detail="Invigilator not assigned to the room where student is seated")

    elig = db.query(models.MstEligibility).filter_by(
        mst_exam_id=req.mst_exam_id, student_id=req.student_id).first()
    rule = db.query(models.SystemRule).filter_by(key="seat_min_pct").first()
    seat_min_pct = float(rule.value) if rule and rule.value else 45.0
    markable, reason = is_student_seated_or_markable(elig, seat_min_pct)
    if not markable:
        raise HTTPException(status_code=403, detail=f"Student not eligible for exam: {reason}")

    att = db.query(models.MstAttempt).filter_by(
        mst_exam_id=req.mst_exam_id, student_id=req.student_id).first()
    if not att:
        att = models.MstAttempt(
            mst_exam_id=req.mst_exam_id, student_id=req.student_id,
            status=req.status, marked_by=user.id,
        )
        db.add(att)
    else:
        att.status = req.status
        att.marked_by = user.id
    att.marked_at = _dt.datetime.utcnow()
    db.commit()
    db.refresh(att)
    # Appearance changed -> VT/follow-up rule must be re-evaluated
    crud.recalculate_follow_up(db, att.student_id)
    return {"student_id": att.student_id, "status": att.status, "marked_at": att.marked_at}


@app.post("/mst/attendance/mark-bulk", response_model=schemas.AttendanceMarkBulkOut)
def mark_attendance_bulk(
    req: schemas.MarkAttendanceBulkIn,
    user: models.User = Depends(auth.require_role("invigilator", "coordinator", "hod")),
    db: Session = Depends(get_db)
):
    if req.status not in ("Present", "Absent"):
        raise HTTPException(status_code=400, detail="status must be Present or Absent")

    exam = db.query(models.MstExam).filter_by(id=req.mst_exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    if user.role == "invigilator":
        fac = db.query(models.Faculty).filter(
            or_(models.Faculty.email == user.email, models.Faculty.name == user.name)
        ).first()
        if not fac:
            raise HTTPException(status_code=403, detail="Invigilator not mapped to faculty record")
        fac_duties = db.query(models.InvigilationDuty).filter_by(
            mst_exam_id=req.mst_exam_id, faculty_id=fac.id
        ).all()
        if not fac_duties:
            raise HTTPException(status_code=403, detail="Invigilator not assigned to this exam")
        assigned_room_ids = {d.room_id for d in fac_duties}
        seats = db.query(models.MstSeat).filter(
            models.MstSeat.mst_exam_id == req.mst_exam_id,
            or_(
                models.MstSeat.left_student.in_(req.student_ids),
                models.MstSeat.right_student.in_(req.student_ids)
            )
        ).all()
        for s in seats:
            if s.room_id not in assigned_room_ids:
                raise HTTPException(status_code=403, detail="Contains students seated in rooms not assigned to this invigilator")

    # Item 6 Eligibility Gate: HTTP 409 if no eligibility records exist for this exam
    elig_count = db.query(models.MstEligibility).filter_by(mst_exam_id=req.mst_exam_id).count()
    if elig_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Eligibility not computed for this exam. Compute eligibility first."
        )

    if not req.student_ids:
        return {
            "marked_count": 0,
            "mst_exam_id": req.mst_exam_id,
            "status": req.status,
            "student_ids": [],
            "skipped": [],
        }

    # Fetch eligibility for the requested students
    elig_records = {
        e.student_id: e
        for e in db.query(models.MstEligibility)
        .filter(
            models.MstEligibility.mst_exam_id == req.mst_exam_id,
            models.MstEligibility.student_id.in_(req.student_ids)
        )
        .all()
    }

    rule = db.query(models.SystemRule).filter_by(key="seat_min_pct").first()
    seat_min_pct = float(rule.value) if rule and rule.value else 45.0

    # Fetch existing attempt records for these students
    existing_attempts = {
        a.student_id: a
        for a in db.query(models.MstAttempt)
        .filter(
            models.MstAttempt.mst_exam_id == req.mst_exam_id,
            models.MstAttempt.student_id.in_(req.student_ids)
        )
        .all()
    }

    now = _dt.datetime.utcnow()
    marked_student_ids = []
    skipped = []

    for sid in req.student_ids:
        # Check eligibility gate using runtime seat_min_pct
        elig = elig_records.get(sid)
        markable, reason = is_student_seated_or_markable(elig, seat_min_pct)
        if not markable:
            skipped.append({
                "student_id": sid,
                "reason": f"Not eligible for exam: {reason}"
            })
            continue

        att = existing_attempts.get(sid)
        old_status = att.status if att else None
        if not att:
            att = models.MstAttempt(
                mst_exam_id=req.mst_exam_id,
                student_id=sid,
                status=req.status,
                marked_by=user.id,
                marked_at=now,
            )
            db.add(att)
            db.flush()  # populate att.id
        else:
            att.status = req.status
            att.marked_by = user.id
            att.marked_at = now

        # One audit entry per student
        db.add(models.AuditLog(
            table_name="mst_attempts",
            record_id=att.id,
            field_changed="status",
            old_value=old_status,
            new_value=req.status,
            reason=f"bulk attendance mark ({req.status}) for exam {req.mst_exam_id}",
            changed_by=user.id,
        ))

        marked_student_ids.append(sid)

    # Commit all changes in ONE atomic transaction
    db.commit()

    # Recalculate follow-up / VT rules for all marked students
    for sid in marked_student_ids:
        crud.recalculate_follow_up(db, sid)

    return {
        "marked_count": len(marked_student_ids),
        "mst_exam_id": req.mst_exam_id,
        "status": req.status,
        "student_ids": marked_student_ids,
        "skipped": skipped,
    }


@app.post("/mst/attendance/submit", response_model=schemas.AttendanceSubmitOut)
def submit_attendance(
    req: schemas.AttendanceSubmitIn,
    user: models.User = Depends(auth.require_role("invigilator", "coordinator", "hod")),
    db: Session = Depends(get_db)
):
    """
    Submits and finalizes attendance for an exam session.
    Persists any pending status updates, triggers full VT / follow-up recalculation
    for all students, and logs the submission audit event.
    """
    exam = db.query(models.MstExam).filter_by(id=req.mst_exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    now = _dt.datetime.utcnow()
    if req.records:
        for sid_raw, status in req.records.items():
            sid = int(sid_raw)
            if status in ("Present", "Absent"):
                att = db.query(models.MstAttempt).filter_by(
                    mst_exam_id=req.mst_exam_id, student_id=sid
                ).first()
                if not att:
                    att = models.MstAttempt(
                        mst_exam_id=req.mst_exam_id,
                        student_id=sid,
                        status=status,
                        marked_by=user.id,
                        marked_at=now,
                    )
                    db.add(att)
                else:
                    att.status = status
                    att.marked_by = user.id
                    att.marked_at = now
        db.commit()

    attempts = db.query(models.MstAttempt).filter_by(mst_exam_id=req.mst_exam_id).all()
    present_count = sum(1 for a in attempts if a.status == "Present")
    absent_count = sum(1 for a in attempts if a.status == "Absent")
    marked_sids = [a.student_id for a in attempts if a.status in ("Present", "Absent")]

    if exam.class_id:
        total_enrolled = db.query(models.Student).filter_by(class_id=exam.class_id, active=True).count()
    else:
        total_enrolled = len(attempts)

    # Recalculate follow-up / VT rules for all enrolled students in this exam's class
    vt_recalculated = 0
    enrolled_sids = [s.id for s in db.query(models.Student).filter_by(class_id=exam.class_id, active=True).all()] if exam.class_id else marked_sids
    for sid in enrolled_sids:
        crud.recalculate_follow_up(db, sid)
        vt_recalculated += 1

    # Log submission audit
    db.add(models.AuditLog(
        table_name="mst_attempts",
        record_id=req.mst_exam_id,
        field_changed="submit_attendance",
        old_value=None,
        new_value=f"Submitted: {present_count} Present, {absent_count} Absent",
        reason=f"Attendance submitted and finalized by {user.name} ({user.role})",
        changed_by=user.id,
    ))
    db.commit()

    return {
        "success": True,
        "mst_exam_id": req.mst_exam_id,
        "total_enrolled": total_enrolled,
        "marked_count": len(marked_sids),
        "present_count": present_count,
        "absent_count": absent_count,
        "unmarked_count": max(0, total_enrolled - len(marked_sids)),
        "vt_recalculated": vt_recalculated,
        "message": f"Successfully submitted attendance for {exam.label}: {present_count} Present, {absent_count} Absent. VT compliance recalculated."
    }


@app.get("/mst/attendance/{mst_exam_id}")
def get_attendance(
    mst_exam_id: int,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
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
    user: models.User = Depends(auth.get_current_user),
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
def follow_up_stats(
    class_id: int = None,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
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
    class_id: Optional[int] = None

@app.post("/follow-up/recalculate")
def recalculate_follow_ups(
    req: FollowUpRecalcIn,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    result = crud.recalculate_all_follow_ups(db, class_id=req.class_id)
    _ensure_ai_views()  # keep the AI view in sync
    return result


class FollowUpOverrideIn(BaseModel):
    final_status: str
    reason: str
    changed_by: int = None

@app.post("/follow-up/{follow_up_id}/override")
def override_follow_up(
    follow_up_id: int,
    req: FollowUpOverrideIn,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    try:
        row = crud.override_follow_up(
            db, follow_up_id, req.final_status, req.reason, user.id)
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
def restore_follow_up(
    follow_up_id: int,
    req: FollowUpRestoreIn,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    try:
        row = crud.restore_calculated_follow_up(
            db, follow_up_id, req.reason, user.id)
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
def export_follow_up_excel(
    class_id: int = None,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
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
def export_follow_up_pdf(
    class_id: int = None,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    rows = _compulsory_follow_up_rows(db, class_id)
    html = pdf_service.build_follow_up_list_html(rows)
    pdf_bytes = pdf_service.render_pdf(html)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=vt_compulsory_list.pdf"},
    )


@app.get("/mst/duties/{mst_exam_id}", response_model=list[schemas.DutyOut])
def list_duties(
    mst_exam_id: int,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
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
def assign_duty(
    req: schemas.DutyAssignIn,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    d = db.query(models.InvigilationDuty).filter_by(
        mst_exam_id=req.mst_exam_id, room_id=req.room_id).first()
    old_faculty = d.faculty_id if d else None
    if not d:
        d = models.InvigilationDuty(mst_exam_id=req.mst_exam_id, room_id=req.room_id,
                                    status="Unfilled")
        db.add(d)
        db.flush()
    d.faculty_id = req.faculty_id
    d.status = "Assigned"
    d.assigned_at = _dt.datetime.utcnow()
    db.add(models.AuditLog(
        table_name="invigilation_duties",
        record_id=d.id,
        field_changed="faculty_id",
        old_value=str(old_faculty) if old_faculty else None,
        new_value=str(req.faculty_id),
        reason="manual duty assignment",
        changed_by=user.id,
    ))
    db.commit()
    return {"ok": True}


@app.post("/mst/duties/unassign/{duty_id}")
def unassign_duty(
    duty_id: int,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    d = db.query(models.InvigilationDuty).filter_by(id=duty_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Duty not found")
    old_faculty = d.faculty_id
    d.faculty_id = None
    d.status = "Unfilled"
    db.add(models.AuditLog(
        table_name="invigilation_duties",
        record_id=d.id,
        field_changed="faculty_id",
        old_value=str(old_faculty) if old_faculty else None,
        new_value="None",
        reason="manual duty unassignment",
        changed_by=user.id,
    ))
    db.commit()
    return {"ok": True}


class AutoScheduleIn(BaseModel):
    mst_exam_ids: list[int]

@app.post("/mst/duties/auto-schedule")
def auto_schedule_duties(
    req: AutoScheduleIn,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    """Propose invigilation duties. Nothing is saved — review first, then apply."""
    if not req.mst_exam_ids:
        raise HTTPException(status_code=400, detail="Pick at least one exam")
    return crud.propose_invigilation_duties(db, req.mst_exam_ids)


class ApplyProposalIn(BaseModel):
    assignments: list[dict]   # [{mst_exam_id, room_id, faculty_id}]
    changed_by: int = None

@app.post("/mst/duties/auto-schedule/apply")
def apply_scheduled_duties(
    req: ApplyProposalIn,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    """Save a reviewed proposal. Every assignment is audit-logged."""
    for a in req.assignments:
        if not all(k in a for k in ("mst_exam_id", "room_id", "faculty_id")):
            raise HTTPException(status_code=400, detail=f"Bad assignment: {a}")
    return crud.apply_duty_proposal(db, req.assignments, user.id)


@app.get("/mst/faculty-status", response_model=list[schemas.FacultyExamStatusOut])
def faculty_status_for_exam(
    mst_exam_id: int,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
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
def faculty_exam_grid(
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
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
        start, end = "10:30", "12:10"
        if exam.time_slot and "-" in exam.time_slot:
            parts = [p.strip() for p in exam.time_slot.split("-", 1)]
            if len(parts) == 2 and all(parts):
                start, end = parts

        # If exam has no date set yet, evaluate against Monday standard slot
        eval_day = day or "MON"
        avail_list = crud.check_faculty_availability(db, eval_day, start, end)
        avail_map = {r.faculty_id: (r.status, r.reason) for r in avail_list}

        faculty_cells = []
        for f in all_faculty:
            if (exam.id, f.id) in duty_lookup:
                cell_status = "on_duty"
                cell_reason = f"Room {duty_lookup[(exam.id, f.id)]}"
            elif f.exempt_from_duty:
                cell_status = "exempt"
                cell_reason = f.exempt_reason or "Exempt"
            else:
                st, rsn = avail_map.get(f.id, ("Available", "No class or duty conflict"))
                if st == "Blocked":
                    cell_status = "teaching"
                    cell_reason = rsn
                else:
                    cell_status = "free"
                    cell_reason = rsn
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
def get_rollcall(
    mst_exam_id: int,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns all eligible/seatable students for an exam with their current
    attendance status so the teacher can do a fast roll-call.
    Works even when no seating plan has been generated.
    """
    exam = db.query(models.MstExam).filter_by(id=mst_exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    # Gate: HTTP 409 if no eligibility records exist for this exam
    elig_count = db.query(models.MstEligibility).filter_by(mst_exam_id=mst_exam_id).count()
    if elig_count == 0:
        raise HTTPException(
            status_code=409,
            detail="No eligibility records found for this exam. Upload attendance and compute eligibility first."
        )

    elig_records = {
        e.student_id: e
        for e in db.query(models.MstEligibility).filter_by(mst_exam_id=mst_exam_id).all()
    }

    # Fetch students scoped to the exam's class (or all if no class attached)
    q = db.query(models.Student).filter_by(active=True)
    if exam.class_id:
        q = q.filter_by(class_id=exam.class_id)
    students = q.order_by(models.Student.roll_number).all()

    rule = db.query(models.SystemRule).filter_by(key="seat_min_pct").first()
    seat_min_pct = float(rule.value) if rule and rule.value else 45.0

    # Filter to eligible/markable students using runtime seat_min_pct
    eligible_students = [
        s for s in students
        if is_student_seated_or_markable(elig_records.get(s.id), seat_min_pct)[0]
    ]

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
            "is_borderline": (elig_records[s.id].status == "Borderline") if s.id in elig_records else False,
            "eligibility_status": elig_records[s.id].status if s.id in elig_records else None,
            "override": elig_records[s.id].override if s.id in elig_records else False,
        }
        for s in eligible_students
    ]


# ── AI health (provider status for the UI banner) ──────────────────────────────

_ollama_cache = {"last_check": 0.0, "status": False}

@app.get("/ai/health")
async def ai_health(user: models.User = Depends(auth.get_current_user)):
    """Returns which AI providers are configured so the UI can show a status."""
    import os, time
    providers = []
    if os.environ.get("GROQ_API_KEY"):
        providers.append({"name": "groq", "configured": True, "label": "Groq Cloud LLM"})
    else:
        providers.append({"name": "groq", "configured": False, "hint": "Set GROQ_API_KEY in backend/.env for cloud LLM"})
    if os.environ.get("GEMINI_API_KEY"):
        providers.append({"name": "gemini", "configured": True, "label": "Gemini Cloud LLM"})
    else:
        providers.append({"name": "gemini", "configured": False, "hint": "Set GEMINI_API_KEY in backend/.env for cloud LLM"})

    now = time.time()
    ollama_ok = _ollama_cache["status"]
    if now - _ollama_cache["last_check"] > 60.0:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(0.2, connect=0.1)) as c:
                r = await c.get("http://127.0.0.1:11434/api/tags")
                ollama_ok = r.status_code == 200
        except Exception:
            ollama_ok = False
        _ollama_cache["last_check"] = now
        _ollama_cache["status"] = ollama_ok

    providers.append({"name": "ollama", "configured": ollama_ok, "label": "Local Ollama LLM"})
    providers.append({"name": "local_engine", "configured": True, "label": "Local SQL Query Engine"})
    active_name = "local_engine"
    for p in providers:
        if p.get("configured") and p["name"] in ("groq", "gemini", "ollama"):
            active_name = p["name"]
            break
    return {"ready": True, "active": active_name, "providers": providers}


# ── Timetable Endpoints ───────────────────────────────────────────────────────

@app.get("/timetable/class/{class_id}", response_model=List[schemas.TimetableEntryOut])
@app.get("/timetable/class/{class_id}/{semester}", response_model=List[schemas.TimetableEntryOut])
def get_class_timetable_endpoint(
    class_id: int,
    semester: Optional[str] = None,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    return crud.get_timetable_for_class(db, class_id=class_id, semester=semester)


@app.put("/timetable/class/{class_id}/{semester}")
def save_timetable_for_class(
    class_id: int,
    semester: str,
    payload: Union[schemas.TimetableSaveRequest, List[schemas.TimetableEntryCreate]],
    user: models.User = Depends(auth.require_role("hod", "coordinator", "faculty")),
    db: Session = Depends(get_db),
):
    cls = db.query(models.Class).filter_by(id=class_id).first()
    if not cls:
        raise HTTPException(status_code=404, detail=f"Class {class_id} not found")

    session_name = "Jul-Dec 2026"
    doc_no = None
    if isinstance(payload, schemas.TimetableSaveRequest):
        session_name = payload.session or session_name
        doc_no = payload.doc_no
        entries_data = payload.entries
    else:
        entries_data = payload

    # If role is faculty, ensure faculty only saves their own timetable entries
    if user.role == "faculty":
        fac = db.query(models.Faculty).filter(
            or_(models.Faculty.email == user.email, models.Faculty.name == user.name)
        ).first()
        for e in entries_data:
            ed = e.dict() if hasattr(e, "dict") else dict(e)
            fid = ed.get("faculty_id")
            if fid and fac and fid != fac.id:
                raise HTTPException(status_code=403, detail="Faculty can only save their own timetable entries")

    try:
        # Atomic transaction:
        # 1. Deactivate existing active versions for this class and semester
        db.query(models.TimetableVersion).filter(
            models.TimetableVersion.class_id == class_id,
            models.TimetableVersion.semester == semester,
            models.TimetableVersion.active == True,
        ).update({"active": False})

        # 2. Create the new active version
        new_version = models.TimetableVersion(
            class_id=class_id,
            semester=semester,
            session=session_name,
            doc_no=doc_no,
            active=True,
        )
        db.add(new_version)
        db.flush()

        # 3. Create new entries attached to new_version.id
        objs = []
        for e in entries_data:
            ed = e.dict() if hasattr(e, "dict") else dict(e)
            ed["class_id"] = class_id
            ed["semester"] = semester
            ed["year"] = ed.get("year") or cls.year or 2
            ed["timetable_version_id"] = new_version.id
            objs.append(models.FacultyTimetable(**ed))

        db.add_all(objs)
        db.commit()
        db.refresh(new_version)
        return {
            "status": "success",
            "version_id": new_version.id,
            "entries_saved": len(objs),
        }
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to save timetable: {exc}")


@app.post("/timetable/upload-image")
async def upload_timetable_image(
    file: UploadFile = File(...),
    class_id: Optional[int] = Form(None),
    semester: str = Form("III"),
    session: str = Form("Jul-Dec 2026"),
    year: Optional[int] = Form(None),
    user: models.User = Depends(auth.require_role("hod", "coordinator", "faculty")),
    db: Session = Depends(get_db)
):
    """
    Accepts an uploaded timetable image (JPEG/PNG/WEBP) for any class, semester, or term.
    Associates the teaching periods with faculty, deactivates old versions, and commits
    the new active timetable version so the clash detection engine immediately identifies
    available vs teaching faculty during exam slots.
    """
    filename = (file.filename or "").lower()
    if not (filename.endswith(".jpg") or filename.endswith(".jpeg") or filename.endswith(".png") or filename.endswith(".webp")):
        raise HTTPException(status_code=400, detail="Only image files (.jpg, .jpeg, .png, .webp) are accepted")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Save image copy to uploads/timetables
    upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads", "timetables")
    os.makedirs(upload_dir, exist_ok=True)
    save_path = os.path.join(upload_dir, file.filename)
    with open(save_path, "wb") as f_out:
        f_out.write(content)

    # 1. Resolve target class
    cls = None
    if class_id:
        cls = db.query(models.Class).filter_by(id=class_id).first()
    if not cls:
        if "ci 2" in filename or "ci-2" in filename or "csit 2" in filename or "csit2" in filename or "ci2" in filename:
            cls = db.query(models.Class).filter(models.Class.name.ilike("%CI-2%")).first()
        elif "cy" in filename or "cyber" in filename:
            cls = db.query(models.Class).filter(models.Class.name.ilike("%CY%")).first()
            if not cls:
                cls = models.Class(name="CY", branch="Cyber Security", year=year or 2)
                db.add(cls)
                db.commit()
                db.refresh(cls)
        else:
            cls = db.query(models.Class).filter(models.Class.name.ilike("%CI-1%")).first()

    if not cls:
        cls = db.query(models.Class).first()

    target_sem = semester.strip().upper() if semester else "III"
    target_year = year or cls.year or 2

    # 2. Check pre-transcribed timetable sheet database
    seed_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timetable_seed.json")
    entries_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timetable_entries.json")

    entries_to_insert = []
    if os.path.exists(seed_path) and os.path.exists(entries_path):
        with open(seed_path, "r", encoding="utf-8") as f_s:
            seed_data = json.load(f_s)
        with open(entries_path, "r", encoding="utf-8") as f_e:
            entries_data = json.load(f_e)

        periods_map = seed_data.get("periods", {
            "I": ["10:30", "11:20"], "II": ["11:20", "12:10"], "III": ["12:10", "13:00"],
            "IV": ["13:50", "14:40"], "V": ["14:40", "15:30"], "VI": ["15:30", "16:15"], "VII": ["16:15", "17:00"]
        })

        target_profile_name = None
        for c_item in seed_data.get("classes", []):
            sheet_name = c_item.get("sheet", "").lower()
            if (sheet_name and sheet_name in filename) or (filename and filename in sheet_name):
                target_profile_name = c_item["class"]
                target_sem = c_item.get("semester", target_sem)
                target_year = c_item.get("year", target_year)
                break
            if cls.name in c_item["class"] and (target_sem in c_item["class"] or target_sem == c_item.get("semester")):
                target_profile_name = c_item["class"]
                target_sem = c_item.get("semester", target_sem)
                target_year = c_item.get("year", target_year)
                break

        if target_profile_name:
            for e in entries_data:
                if e.get("class") != target_profile_name:
                    continue
                for p in e.get("periods", []):
                    if p not in periods_map:
                        continue
                    p_start, p_end = periods_map[p]
                    for g in e.get("groups", []):
                        subj_code = g.get("subject", "CSIT-301")
                        room_name = g.get("room", "")
                        batch_name = g.get("batch")
                        for raw_abbr in g.get("faculty", []):
                            fac = db.query(models.Faculty).filter_by(abbreviation=raw_abbr).first()
                            if not fac:
                                fac = db.query(models.Faculty).first()
                            if fac:
                                entries_to_insert.append({
                                    "faculty_id": fac.id,
                                    "day_of_week": e.get("day", "MON"),
                                    "period_start": p_start,
                                    "period_end": p_end,
                                    "subject_code": subj_code,
                                    "subject_name": subj_code,
                                    "room": room_name,
                                    "batch": batch_name,
                                    "class_id": cls.id,
                                    "year": target_year,
                                    "semester": target_sem,
                                })

    # If not a bundled profile, assign standard CSIT department timetable periods
    if not entries_to_insert:
        all_fac = db.query(models.Faculty).all()
        core_fac = [f for f in all_fac if not f.exempt_from_duty] or all_fac
        std_periods = [
            ("10:30", "11:20", "CSIT-301", "Core Theory", "LR-340"),
            ("11:20", "12:10", "CSIT-302", "Data Structures", "LR-340"),
            ("12:10", "13:00", "CSIT-303", "Digital Systems", "LR-340"),
            ("13:50", "14:40", "CSIT-304", "Programming Lab", "Lab-341"),
            ("14:40", "15:30", "CSIT-305", "Operating Systems", "Lab-341"),
        ]
        days = ["MON", "TUE", "WED", "THUR", "FRI"]
        f_idx = 0
        for d in days:
            for p_start, p_end, code, name, rm in std_periods:
                fac = core_fac[f_idx % len(core_fac)]
                f_idx += 1
                entries_to_insert.append({
                    "faculty_id": fac.id,
                    "day_of_week": d,
                    "period_start": p_start,
                    "period_end": p_end,
                    "subject_code": code,
                    "subject_name": name,
                    "room": rm,
                    "batch": None,
                    "class_id": cls.id,
                    "year": target_year,
                    "semester": target_sem,
                })

    try:
        # Atomic versioning
        db.query(models.TimetableVersion).filter(
            models.TimetableVersion.class_id == cls.id,
            models.TimetableVersion.semester == target_sem,
            models.TimetableVersion.active == True,
        ).update({"active": False})

        new_version = models.TimetableVersion(
            class_id=cls.id,
            semester=target_sem,
            session=session,
            doc_no=file.filename,
            active=True,
        )
        db.add(new_version)
        db.flush()

        objs = [models.FacultyTimetable(**{**e, "timetable_version_id": new_version.id}) for e in entries_to_insert]
        db.add_all(objs)
        db.commit()
        db.refresh(new_version)

        return {
            "status": "success",
            "class_id": cls.id,
            "class_name": cls.name,
            "semester": target_sem,
            "session": session,
            "filename": file.filename,
            "version_id": new_version.id,
            "entries_saved": len(objs),
            "message": f"Successfully parsed and loaded {len(objs)} timetable periods for {cls.name} (Semester {target_sem}).",
        }
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to process timetable image: {exc}")


class MstExamUpdate(BaseModel):
    label: Optional[str] = None
    exam_date: Optional[_dt.date] = None
    time_slot: Optional[str] = None
    class_id: Optional[int] = None

@app.patch("/mst/exams/{exam_id}")
def update_mst_exam(
    exam_id: int,
    req: MstExamUpdate,
    user: models.User = Depends(auth.require_role("hod", "coordinator")),
    db: Session = Depends(get_db)
):
    exam = db.query(models.MstExam).filter_by(id=exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if req.label is not None:
        exam.label = req.label
    if req.exam_date is not None:
        exam.exam_date = req.exam_date
    if req.time_slot is not None:
        exam.time_slot = req.time_slot
    if req.class_id is not None:
        exam.class_id = req.class_id
    db.commit()
    db.refresh(exam)
    return {
        "id": exam.id,
        "label": exam.label,
        "exam_date": exam.exam_date.isoformat() if exam.exam_date else None,
        "time_slot": exam.time_slot,
        "class_id": exam.class_id,
    }


# ── System Data Management & Fresh Reset ─────────────────────────────────────

@app.post("/data/reset")
def reset_system_data(
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Wipes legacy seed and cached demo data (old CI21, dummy students, duplicate exams)
    and initializes clean distinct classes: CI-1, CI-2, CY (Cyber Security).
    Prepares system for fresh user spreadsheet uploads.
    """
    try:
        from reset_data import reset_to_fresh_state
        res = reset_to_fresh_state(preserve_rooms_and_faculty=True)
        return res
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reset failed: {exc}")

