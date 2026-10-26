"""
AI Service — cloud-first LLM integration for MST Operations Portal.

Architecture:
  - LLM provider chain (tried in order, first success wins):
      1. Groq cloud API   (GROQ_API_KEY)   — free tier, no card, fastest
      2. Gemini cloud API (GEMINI_API_KEY) — free tier via Google AI Studio
      3. Local Ollama     (fallback for fully-offline dev)
    Both cloud providers use the OpenAI-compatible /chat/completions API.
    The backend only needs an API key as an environment variable — nothing to
    install or keep running on the host, so the site works the same on a
    laptop, Render, Railway, or any VPS.
  - Read path:  NL question → LLM generates SELECT → validated → run on ai_reader views → LLM formats answer
  - Write path: NL intent   → LLM returns structured JSON → validated Pydantic schema →
                              dispatched to named ORM operation → audit_log entry created
  - PDF path:   triggered by explicit intent keyword → returns download URL

Never executes raw SQL from the model. Writes go through the ORM CRUD layer only.
API keys are never logged or returned to the client.

PRIVACY NOTE: Contextual query views and prompts sent to external LLM providers
(Groq / Gemini) may contain student names and roll numbers. For strict student data
privacy or air-gapped on-premises deployments, configure local Ollama
(e.g., set AI_PROVIDERS=ollama, leaving cloud API keys unset).
"""

import json
import os
import re
import datetime
import httpx
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.orm import Session
from sqlalchemy import text
import sqlglot
from sqlglot import exp

import models
import crud
from database import get_readonly_connection

# ── Configuration ──────────────────────────────────────────────────────────────
# Cloud-first: the AI works wherever the backend is hosted — no local Ollama needed.
# Providers are tried in AI_PROVIDERS order; entries without a key are skipped.
#
#   Get a free Groq key (no credit card): https://console.groq.com/keys
#   Windows PowerShell — set for the current session BEFORE starting uvicorn
#   (do NOT commit the key; backend/.env is tracked in git):
#       $env:GROQ_API_KEY="gsk_..."
#   Optional overrides:
#       $env:GROQ_MODEL="openai/gpt-oss-20b"   # if Groq deprecates the default
#       $env:GEMINI_API_KEY="..."              # backup provider from https://aistudio.google.com/
#       $env:AI_PROVIDERS="groq,gemini,ollama"        # change order / drop providers
#   On Render / Railway / VPS: add GROQ_API_KEY as an environment variable.

GROQ_API_KEY  = os.environ.get("GROQ_API_KEY")
GROQ_MODEL    = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL    = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_BASE_URL = os.environ.get(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL", "gemma2:2b")

AI_PROVIDERS = [
    p.strip().lower()
    for p in os.environ.get("AI_PROVIDERS", "groq,gemini,ollama").split(",")
    if p.strip()
]


def _is_cloud_allowed() -> bool:
    """Return True if external cloud LLM providers (Groq, Gemini) are permitted. Default is False."""
    return os.environ.get("AI_ALLOW_CLOUD", "false").strip().lower() in ("true", "1", "yes")


# Only these views are queryable by the AI (read path)
ALLOWED_READ_VIEWS = {
    "ai_eligibility_summary",
    "ai_attendance_summary",
    "ai_vt_candidates",
    "ai_duty_roster",
    "v_vt_follow_up_status",
}

# Only these operations can be triggered by the AI (write path)
ALLOWED_WRITE_OPS = {
    "override_eligibility",
    "mark_attempt_status",
    "assign_duty",
}

# ── Prompts ────────────────────────────────────────────────────────────────────
READ_SYSTEM_PROMPT = """
You are a read-only SQL assistant for an MST (midterm exam) operations database.
You may ONLY query these views (no other tables):

- ai_eligibility_summary(class_name, class_year, mst_label, mst_exam_id, eligible_count, ineligible_count, missing_count)
- ai_attendance_summary(class_name, class_year, roll_number, student_name, overall_pct, lowest_subject_pct, mst_exam_id, mst_label)
- ai_vt_candidates(class_name, class_year, roll_number, student_name, mst1_status, mst2_status)
- ai_duty_roster(mst_label, exam_date, room_number, faculty_name, duty_status)
- v_vt_follow_up_status(roll_number, student_name, class_name, class_year, mst_1_label, mst_2_label,
    mst_1_appeared, mst_2_appeared, calculated_status, final_status, overridden,
    override_reason, rule_version, updated_at)
  calculated_status/final_status are one of: not_required, compulsory, under_review, excused, completed.
  mst_1_appeared/mst_2_appeared are TRUE (present), FALSE (absent), or NULL (missing record).
  class_year is 2 for 2nd Year (Semester 3/4) and 3 for 3rd Year (Semester 5/6).
  class_name is 'CI-1', 'CI-2', 'CY', or 'CI-1 (Yr 3)', etc.

Rules:
1. Only generate SELECT statements.
2. No subqueries that touch tables not in the list above.
3. Return ONLY the SQL, nothing else. No markdown, no explanation.
4. Distinguish clearly between MST-1 and MST-2, between classes (CI-1, CI-2, CY), and between years (class_year=2 vs class_year=3).

Examples:
Q: How many 2nd year CI-1 students are eligible for MST-1?
A: SELECT eligible_count FROM ai_eligibility_summary WHERE class_name LIKE '%CI-1%' AND class_year=2 AND mst_label='MST-1';

Q: List borderline students in CI-2
A: SELECT roll_number, student_name, overall_pct FROM ai_attendance_summary WHERE class_name LIKE '%CI-2%' AND overall_pct >= 45 AND overall_pct < 50;

Q: Who is absent in both MST-1 and MST-2 in 2nd year?
A: SELECT roll_number, student_name, class_name FROM v_vt_follow_up_status WHERE class_year=2 AND final_status='compulsory';

Q: What are the VT candidate stats for 3rd year?
A: SELECT final_status, COUNT(*) FROM v_vt_follow_up_status WHERE class_year=3 GROUP BY final_status;
"""

WRITE_SYSTEM_PROMPT = """
You are a controlled write assistant for an MST operations database.
You may ONLY produce JSON for one of these three operations:

1. override_eligibility
   {"operation": "override_eligibility", "roll_number": "...", "mst_label": "MST-1 or MST-2", "reason": "..."}

2. mark_attempt_status
   {"operation": "mark_attempt_status", "roll_number": "...", "mst_label": "MST-1 or MST-2", "status": "Present|Absent|Late|Excused|Signature missing"}

3. assign_duty
   {"operation": "assign_duty", "faculty_name": "...", "mst_label": "MST-1 or MST-2", "room_number": "..."}

Rules:
1. Return ONLY valid JSON. No markdown fences, no explanation.
2. If the request is ambiguous or doesn't fit any operation, return: {"operation": "unsupported"}
3. Reason fields must be non-empty strings.
"""

FORMAT_SYSTEM_PROMPT = """
You are a helpful assistant summarising database query results for a college exam coordinator.
Format the result clearly and concisely. Use plain English. No SQL. No JSON. No markdown tables.
Keep it under 4 sentences.
"""

# ── LLM provider chain ─────────────────────────────────────────────────────────

async def _openai_compat_chat(base_url: str, api_key: str, model: str,
                              system: str, user: str, temperature: float) -> str:
    """POST to an OpenAI-compatible /chat/completions endpoint (Groq, Gemini)."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature": temperature,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if resp.status_code == 401:
            raise RuntimeError("API key rejected (401) — check the key and try again.")
        if resp.status_code == 404:
            raise RuntimeError(
                f"Model '{model}' not found (404) — it may have been deprecated. "
                f"Check the provider's current model list and set the *_MODEL env var."
            )
        if resp.status_code == 429:
            raise RuntimeError("Rate limit hit (429) — wait a minute and retry.")
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


async def _ollama_chat(system: str, user: str, temperature: float = 0.1) -> str:
    """Send a chat completion request to the local Ollama instance (offline fallback)."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "stream": False,
        "options": {"temperature": temperature},
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()
    except httpx.ConnectError:
        raise ConnectionError(
            f"Cannot reach Ollama at {OLLAMA_BASE_URL}. "
            f"Start Ollama (https://ollama.com/download) and run: ollama pull {OLLAMA_MODEL}"
        )


async def _llm_chat(system: str, user: str, temperature: float = 0.1) -> str:
    """Try each configured provider in order; the first success wins. Respects AI_ALLOW_CLOUD."""
    allow_cloud = _is_cloud_allowed()
    errors = []
    for provider in AI_PROVIDERS:
        try:
            if provider == "groq":
                if not allow_cloud:
                    # Cloud provider disabled by AI_ALLOW_CLOUD policy
                    continue
                if not GROQ_API_KEY:
                    errors.append("groq: GROQ_API_KEY not set")
                    continue
                return await _openai_compat_chat(
                    GROQ_BASE_URL, GROQ_API_KEY, GROQ_MODEL, system, user, temperature)
            elif provider == "gemini":
                if not allow_cloud:
                    # Cloud provider disabled by AI_ALLOW_CLOUD policy
                    continue
                if not GEMINI_API_KEY:
                    errors.append("gemini: GEMINI_API_KEY not set")
                    continue
                return await _openai_compat_chat(
                    GEMINI_BASE_URL, GEMINI_API_KEY, GEMINI_MODEL, system, user, temperature)
            elif provider == "ollama":
                return await _ollama_chat(system, user, temperature)
            else:
                errors.append(f"{provider}: unknown provider name")
        except Exception as e:
            errors.append(f"{provider}: {e}")
    raise RuntimeError(
        "AI is unreachable — " + " | ".join(errors) +
        ". Configure Ollama locally or enable AI_ALLOW_CLOUD=true with valid cloud API keys."
    )


def _aggregate_for_cloud(rows: list[dict]) -> str:
    """Strip all PII (names, roll numbers) and aggregate data to summary numbers only."""
    if not rows:
        return json.dumps({"count": 0, "summary": "No matching records found."})

    sensitive_keys = {"student_name", "name", "roll_number", "roll"}
    has_pii = any(sensitive_keys.intersection(k.lower() for k in r.keys()) for r in rows)
    if has_pii:
        return json.dumps({
            "total_records": len(rows),
            "summary_counts": f"{len(rows)} matching records retrieved.",
            "privacy_notice": "Individual names and roll numbers were stripped before cloud summarisation."
        })
    return json.dumps(rows)


# ── SQL validator (read path) ──────────────────────────────────────────────────

def _validate_read_sql(sql: str) -> str:
    """Raise ValueError if SQL is not a safe SELECT over allowed views using sqlglot AST."""
    if not sql or not sql.strip():
        raise ValueError("Empty query.")

    raw = sql.strip()

    # Reject comments
    if "/*" in raw or "--" in raw:
        raise ValueError("Comments are not allowed in queries.")

    # Reject semicolon chaining
    stripped = raw.rstrip(";").strip()
    if ";" in stripped:
        raise ValueError("Multiple statements or semicolon-chaining are forbidden.")

    # Reject PRAGMA or ATTACH
    upper_raw = raw.upper()
    if re.search(r"\b(PRAGMA|ATTACH)\b", upper_raw):
        raise ValueError("PRAGMA and ATTACH commands are forbidden.")

    try:
        tokens = sqlglot.tokenize(stripped)
        if any(t.comments for t in tokens):
            raise ValueError("Comments are not allowed in queries.")
        statements = sqlglot.parse(stripped)
    except Exception as e:
        if isinstance(e, ValueError):
            raise
        raise ValueError(f"Failed to parse SQL: {e}")

    if len(statements) != 1:
        raise ValueError("Exactly one SQL statement is allowed.")

    stmt = statements[0]
    if stmt is None or not isinstance(stmt, exp.Select):
        raise ValueError("Only SELECT statements are allowed.")

    # Block destructive or administrative operations inside CTEs or subqueries
    forbidden_types = (
        exp.Insert, exp.Update, exp.Delete, exp.Drop,
        exp.Alter, exp.Create, exp.Command, exp.Pragma
    )
    for forbidden in forbidden_types:
        if list(stmt.find_all(forbidden)):
            raise ValueError("Query contains forbidden data manipulation or administrative operations.")

    # Collect CTE aliases
    cte_names = set()
    if stmt.ctes:
        for cte in stmt.ctes:
            if cte.alias_or_name:
                cte_names.add(cte.alias_or_name.lower())

    # Ensure all tables/views referenced are in ALLOWED_READ_VIEWS
    tables = [t.name.lower() for t in stmt.find_all(exp.Table) if t.name]
    for table in tables:
        if table in cte_names:
            continue
        if table not in ALLOWED_READ_VIEWS:
            raise ValueError(f"Access to '{table}' is not permitted. Allowed: {sorted(ALLOWED_READ_VIEWS)}")

    return stripped


# ── Write op dispatcher ────────────────────────────────────────────────────────

def execute_write_op(
    op_json: dict,
    db: Session,
    ai_user_label: str = "AI_AGENT",
    confirming_user_id: int | None = None
) -> dict:
    """
    Execute a validated write operation through the ORM (never raw SQL).
    Returns a dict describing what changed.
    """
    op = op_json.get("operation")

    if op == "override_eligibility":
        roll    = op_json.get("roll_number")
        label   = op_json.get("mst_label")
        reason  = (op_json.get("reason") or "").strip()
        if not reason:
            raise ValueError("Reason is required for override_eligibility.")

        student = db.query(models.Student).filter(models.Student.roll_number.ilike(f"%{roll}%")).first()
        if not student:
            raise ValueError(f"Student with roll number {roll} not found.")
        exam = db.query(models.MstExam).filter(models.MstExam.label == label).first()
        if not exam:
            raise ValueError(f"Exam {label} not found.")
        el = db.query(models.MstEligibility).filter_by(
            student_id=student.id, mst_exam_id=exam.id
        ).first()
        if not el:
            raise ValueError("Eligibility record not found for this student/exam.")

        old_override = el.override
        el.override = True
        el.override_reason = reason

        log = models.AuditLog(
            table_name="mst_eligibility",
            record_id=el.id,
            field_changed="override",
            old_value=str(old_override),
            new_value="True",
            changed_by=confirming_user_id,
            reason=f"[AI] {reason}",
        )
        db.add(log)
        db.commit()
        return {"changed": "override_eligibility", "roll_number": roll, "exam": label, "reason": reason}

    elif op == "mark_attempt_status":
        roll   = op_json.get("roll_number")
        label  = op_json.get("mst_label")
        status = op_json.get("status")
        allowed_statuses = {"Present", "Absent", "Late", "Excused", "Signature missing"}
        if status not in allowed_statuses:
            raise ValueError(f"Invalid status '{status}'. Must be one of {allowed_statuses}")

        student = db.query(models.Student).filter(models.Student.roll_number.ilike(f"%{roll}%")).first()
        if not student:
            raise ValueError(f"Student {roll} not found.")
        exam = db.query(models.MstExam).filter(models.MstExam.label == label).first()
        if not exam:
            raise ValueError(f"Exam {label} not found.")

        attempt = db.query(models.MstAttempt).filter_by(
            student_id=student.id, mst_exam_id=exam.id
        ).first()
        if attempt:
            old_status = attempt.status
            attempt.status = status
        else:
            attempt = models.MstAttempt(student_id=student.id, mst_exam_id=exam.id, status=status)
            db.add(attempt)
            old_status = "None"

        log = models.AuditLog(
            table_name="mst_attempts",
            record_id=attempt.id if attempt.id else 0,
            field_changed="status",
            old_value=old_status,
            new_value=status,
            changed_by=confirming_user_id,
            reason="[AI] mark_attempt_status",
        )
        db.add(log)
        db.commit()
        return {"changed": "mark_attempt_status", "roll_number": roll, "exam": label, "status": status}

    elif op == "assign_duty":
        faculty_name = op_json.get("faculty_name")
        label        = op_json.get("mst_label")
        room_number  = op_json.get("room_number")

        faculty = db.query(models.Faculty).filter(
            models.Faculty.name.ilike(f"%{faculty_name}%")
        ).first()
        if not faculty:
            raise ValueError(f"Faculty '{faculty_name}' not found.")
        exam = db.query(models.MstExam).filter(models.MstExam.label == label).first()
        if not exam:
            raise ValueError(f"Exam {label} not found.")
        room = db.query(models.Room).filter(models.Room.room_number == room_number).first()
        if not room:
            raise ValueError(f"Room {room_number} not found.")

        # Check clash availability via the exact same clash checker as UI path
        day = exam.exam_date.strftime("%a").upper() if exam.exam_date else None
        day_aliases = {
            "MONDAY": "MON", "TUESDAY": "TUE", "WEDNESDAY": "WED",
            "THURSDAY": "THUR", "FRIDAY": "FRI", "SATURDAY": "SAT", "THU": "THUR"
        }
        if day:
            day = day_aliases.get(day, day)
        start, end = "09:00", "12:00"
        if exam.time_slot and "-" in exam.time_slot:
            parts = [p.strip() for p in exam.time_slot.split("-", 1)]
            if len(parts) == 2 and all(parts):
                start, end = parts

        avail_list = crud.check_faculty_availability(db, day or "MON", start, end)
        fac_avail = next((a for a in avail_list if a.faculty_id == faculty.id), None)
        if fac_avail and fac_avail.status in ("Blocked", "Exempt"):
            raise ValueError(f"Faculty '{faculty.name}' cannot be assigned: {fac_avail.status} ({fac_avail.reason})")

        existing_duty = db.query(models.InvigilationDuty).filter(
            models.InvigilationDuty.mst_exam_id == exam.id,
            models.InvigilationDuty.faculty_id == faculty.id,
            models.InvigilationDuty.room_id != room.id
        ).first()
        if existing_duty:
            raise ValueError(f"Faculty '{faculty.name}' is already assigned to another room for {label}.")

        duty = db.query(models.InvigilationDuty).filter_by(
            mst_exam_id=exam.id, room_id=room.id
        ).first()
        if not duty:
            duty = models.InvigilationDuty(mst_exam_id=exam.id, room_id=room.id, status="Unfilled")
            db.add(duty)
        elif duty.status == "Assigned" and duty.faculty_id != faculty.id:
            raise ValueError("Duty already assigned to another faculty. Use replace workflow.")

        duty.faculty_id = faculty.id
        duty.status = "Assigned"
        duty.assigned_at = datetime.datetime.utcnow()

        log = models.AuditLog(
            table_name="invigilation_duties",
            record_id=duty.id if duty.id else 0,
            field_changed="faculty_id",
            old_value="None",
            new_value=str(faculty.id),
            changed_by=confirming_user_id,
            reason="[AI] assign_duty",
        )
        db.add(log)
        db.commit()
        return {"changed": "assign_duty", "faculty": faculty.name, "exam": label, "room": room_number}

    else:
        raise ValueError(f"Unsupported or unrecognised operation: '{op}'")

# ── Main AI query handler ──────────────────────────────────────────────────────

async def handle_ai_message(message: str, db: Session) -> dict:
    """
    Route a user message to read, write, or PDF path.
    Returns a dict:
      { "type": "answer"|"write_proposal"|"pdf_link"|"error",
        "content": str | dict }
    """
    msg_lower = message.lower()

    # ── PDF intent detection ──────────────────────────────────────────────────
    if any(k in msg_lower for k in ["pdf", "download", "print"]):
        # 1. Look for roll number candidate and verify against DB
        roll_matches = re.findall(r"\b[A-Za-z0-9_-]{4,}\b", message)
        for cand in roll_matches:
            student = db.query(models.Student).filter(models.Student.roll_number.ilike(cand)).first()
            if student:
                return {
                    "type": "pdf_link",
                    "content": f"/pdf/student/{student.roll_number}",
                    "message": f"Here is the PDF report link for {student.name} ({student.roll_number}).",
                }

        # 2. Look for exam + room for seating chart PDF
        if "seating" in msg_lower or ("exam" in msg_lower and "room" in msg_lower):
            rooms = db.query(models.Room).all()
            matched_room = None
            for r in rooms:
                if r.room_number and r.room_number.lower() in msg_lower:
                    matched_room = r
                    break

            exams = db.query(models.MstExam).all()
            matched_exam = None
            for e in exams:
                if e.label and (e.label.lower() in msg_lower or e.label.lower().replace("-", " ") in msg_lower):
                    matched_exam = e
                    break

            if matched_room and matched_exam:
                return {
                    "type": "pdf_link",
                    "content": f"/pdf/seating/{matched_exam.id}/{matched_room.id}",
                    "message": f"Here is the seating chart PDF link for {matched_exam.label} in {matched_room.room_number}.",
                }

        # If entity could not be resolved, fall through to normal query path.
        # Do not return a hardcoded /pdf/seating/1/1 shortcut.

    # ── Missing Class Attendance Guard ────────────────────────────────────────
    # If user explicitly asked for attendance, eligibility, or borderline data of a class
    # that has NO student attendance uploaded yet, inform them directly and helpfully!
    classes_with_students = [
        r[0] for r in db.execute(
            text("SELECT DISTINCT c.name FROM students s JOIN classes c ON c.id = s.class_id WHERE s.active = 1")
        ).fetchall()
    ]
    all_classes = [c.name for c in db.query(models.Class).all()]
    target_class = None
    for cname in all_classes:
        digits = re.findall(r"\d+", cname)
        synonyms = [cname.lower(), cname.lower().replace("-", " "), cname.lower().replace("-", "")]
        if digits:
            num = digits[0]
            synonyms.extend([f"csit{num}", f"csit {num}", f"csit-{num}", f"ci{num}", f"ci {num}", f"ci-{num}", f"cs{num}", f"cs {num}"])
        if any(re.search(rf"\b{re.escape(syn)}\b", msg_lower) for syn in synonyms):
            target_class = cname
            break

    if target_class and target_class not in classes_with_students and not any(w in msg_lower for w in ["timetable", "schedule"]):
        classes_list_str = ", ".join(f"**{c}**" for c in classes_with_students) if classes_with_students else "None"
        return {
            "type": "answer",
            "content": (
                f"### ⚠️ No Attendance Data Uploaded for {target_class}\n\n"
                f"You requested attendance or borderline data for **{target_class}**, but student attendance records have **not been uploaded** for {target_class} yet.\n\n"
                f"- **Classes currently in database with attendance**: {classes_list_str}\n"
                f"- **Timetable Data**: Timetable entries are active in the **[Timetable](/timetable)** section.\n\n"
                f"Please upload the {target_class} Excel attendance sheet on the **[Upload Attendance](/attendance/upload)** page to evaluate its students."
            )
        }

    # ── Write intent detection ────────────────────────────────────────────────
    write_keywords = ["override", "mark", "assign", "update", "change", "set"]
    if any(k in msg_lower for k in write_keywords):
        try:
            raw_json = await _llm_chat(WRITE_SYSTEM_PROMPT, message)
            raw_json = re.sub(r"```[a-z]*\n?", "", raw_json).strip()
            op_json  = json.loads(raw_json)

            if op_json.get("operation") == "unsupported":
                return {"type": "answer", "content": "I'm not sure how to make that change safely. Could you rephrase or use the UI?"}

            if op_json.get("operation") not in ALLOWED_WRITE_OPS:
                raise ValueError("Operation not in allow-list.")

            return {"type": "write_proposal", "content": op_json}

        except (ConnectionError, RuntimeError):
            # Fallback local write intent parser when LLM is offline
            fb_op = _fallback_write_intent(message, db)
            if fb_op:
                return {"type": "write_proposal", "content": fb_op}
            return {"type": "error", "content": "AI write parser offline. Please specify the operation clearly, e.g., 'Override roll 0827CI241101 for MST-1 with reason Medical ground'."}
        except (json.JSONDecodeError, ValueError) as e:
            return {"type": "error", "content": f"Could not parse write intent: {e}"}

    # ── Read / Q&A path ───────────────────────────────────────────────────────
    try:
        sql_raw = await _llm_chat(READ_SYSTEM_PROMPT, message)
        sql     = _validate_read_sql(sql_raw)

        with get_readonly_connection() as ro_conn:
            rows = ro_conn.execute(text(sql)).fetchall()

        dict_rows = [dict(r._mapping) for r in rows]

        if _is_cloud_allowed():
            result_str = _aggregate_for_cloud(dict_rows)
        else:
            result_str = str(dict_rows)

        # Format result in plain English
        formatted = await _llm_chat(
            FORMAT_SYSTEM_PROMPT,
            f"Question: {message}\nQuery result: {result_str}",
            temperature=0.3,
        )
        return {"type": "answer", "content": formatted}

    except Exception:
        # LLM unreachable or failed — answer using intelligent local SQL engine
        return _heuristic_answer(message, db)


def _fallback_write_intent(message: str, db: Session) -> dict | None:
    """Extract structured write intent from plain English when LLM is offline."""
    msg = message.strip()
    msg_lower = msg.lower()

    # 1. Override eligibility: "override roll 0827CI241101 for MST-1"
    if "override" in msg_lower:
        roll_match = re.search(r"\b([0-9]{4}[A-Za-z0-9_-]+|[0-9]{3,})\b", msg)
        exam_match = re.search(r"\b(mst[- ]?[1234])\b", msg_lower)
        exam_label = exam_match.group(1).upper().replace(" ", "-") if exam_match else "MST-1"
        if roll_match:
            roll = roll_match.group(1)
            reason_match = re.search(r"reason[:\s]+(.+)", msg, re.IGNORECASE)
            reason = reason_match.group(1).strip() if reason_match else "Authorized coordinator approval via AI Assistant"
            return {
                "operation": "override_eligibility",
                "roll_number": roll,
                "mst_label": exam_label,
                "reason": reason,
            }

    # 2. Mark attendance: "mark roll 0827CI241101 present for MST-1"
    if "mark" in msg_lower:
        roll_match = re.search(r"\b([0-9]{4}[A-Za-z0-9_-]+|[0-9]{3,})\b", msg)
        exam_match = re.search(r"\b(mst[- ]?[1234])\b", msg_lower)
        exam_label = exam_match.group(1).upper().replace(" ", "-") if exam_match else "MST-1"
        status = "Present" if "present" in msg_lower else "Absent" if "absent" in msg_lower else "Present"
        if roll_match:
            return {
                "operation": "mark_attempt_status",
                "roll_number": roll_match.group(1),
                "mst_label": exam_label,
                "status": status,
            }

    # 3. Assign duty: "assign [Faculty] to room 101 for MST-1"
    if "assign" in msg_lower and "room" in msg_lower:
        room_match = re.search(r"room\s*([0-9A-Za-z-]+)", msg, re.IGNORECASE)
        exam_match = re.search(r"\b(mst[- ]?[1234])\b", msg_lower)
        exam_label = exam_match.group(1).upper().replace(" ", "-") if exam_match else "MST-1"
        faculty_name = None
        for f in db.query(models.Faculty).all():
            if f.name.lower() in msg_lower:
                faculty_name = f.name
                break
        if room_match and faculty_name:
            return {
                "operation": "assign_duty",
                "faculty_name": faculty_name,
                "mst_label": exam_label,
                "room_number": room_match.group(1),
            }

    return None


def _heuristic_answer(message: str, db: Session) -> dict:
    """Accurately answers queries directly from the database views with clear distinction of year, class, and exam."""
    msg = message.lower().strip()

    # 1. Parse Year
    target_year = None
    if any(w in msg for w in ["3rd year", "year 3", "yr 3", "3rd yr", "sem 5", "sem v", "semester 5", "semester v"]):
        target_year = 3
    elif any(w in msg for w in ["2nd year", "year 2", "yr 2", "2nd yr", "sem 3", "sem iii", "semester 3", "semester iii"]):
        target_year = 2

    # 2. Parse Exam (MST-1 vs MST-2)
    target_exam = None
    if any(w in msg for w in ["mst 2", "mst-2", "mst2", "second mst"]):
        target_exam = "MST-2"
    elif any(w in msg for w in ["mst 1", "mst-1", "mst1", "first mst"]):
        target_exam = "MST-1"

    with get_readonly_connection() as conn:
        classes_with_data = [
            r[0] for r in conn.execute(
                text("SELECT DISTINCT c.name FROM students s JOIN classes c ON c.id = s.class_id WHERE s.active = 1")
            ).fetchall()
        ]
        all_classes_in_db = [r[0] for r in conn.execute(text("SELECT name FROM classes")).fetchall()]

        # 3. Parse Class
        target_class = None
        if target_year == 3:
            if any(w in msg for w in ["cyber", "cy"]):
                target_class = "CY (Yr 3)"
            elif any(w in msg for w in ["ci 2", "ci-2", "csit 2", "csit-2", "ci2", "csit2"]):
                target_class = "CI-2 (Yr 3)"
            elif any(w in msg for w in ["ci 1", "ci-1", "csit 1", "csit-1", "ci1", "csit1"]):
                target_class = "CI-1 (Yr 3)"
        else:
            if any(w in msg for w in ["cyber", "cy"]):
                target_class = "CY"
            elif any(w in msg for w in ["ci 2", "ci-2", "csit 2", "csit-2", "ci2", "csit2"]):
                target_class = "CI-2"
            elif any(w in msg for w in ["ci 1", "ci-1", "csit 1", "csit-1", "ci1", "csit1"]):
                target_class = "CI-1"

        # Missing class attendance guard
        if target_class and target_class not in classes_with_data and not any(w in msg for w in ["timetable", "schedule"]):
            classes_list_str = ", ".join(f"**{c}**" for c in classes_with_data) if classes_with_data else "None"
            yr_str = f" ({target_year}rd Year)" if target_year == 3 else f" ({target_year}nd Year)" if target_year else ""
            return {
                "type": "answer",
                "content": (
                    f"### ⚠️ No Attendance Data Uploaded for {target_class}{yr_str}\n\n"
                    f"You requested data for **{target_class}**, but student attendance records have **not been uploaded** for {target_class} yet.\n\n"
                    f"- **Classes currently in database with uploaded attendance**: {classes_list_str}\n"
                    f"- **Timetable Data**: Timetable entries are active in the **[Timetable](/timetable)** section.\n\n"
                    f"Please upload the {target_class} Excel attendance sheet on the **[Upload Attendance](/attendance/upload)** page first."
                )
            }

        # Check for roll number lookup
        roll_match = re.search(r"\b([0-9]{4}[A-Za-z0-9_-]+|[0-9]{4,})\b", message)
        if roll_match:
            roll = roll_match.group(1)
            row = conn.execute(
                text("SELECT * FROM ai_attendance_summary WHERE roll_number LIKE :r"),
                {"r": f"%{roll}%"}
            ).fetchone()
            if row:
                m = dict(row._mapping)
                elig_row = conn.execute(
                    text("SELECT status, override FROM mst_eligibility me JOIN students s ON s.id = me.student_id WHERE s.roll_number LIKE :r"),
                    {"r": f"%{roll}%"}
                ).fetchone()
                status = elig_row[0] if elig_row else "Unknown"
                override = " (Overridden)" if elig_row and elig_row[1] else ""
                yr_val = m.get('class_year', 2)
                content = (
                    f"### Student Record: {m.get('student_name')} (`{m.get('roll_number')}`)\n\n"
                    f"- **Class & Year**: {m.get('class_name')} · Year {yr_val}\n"
                    f"- **Overall Attendance**: `{m.get('overall_pct', 0):.1f}%`\n"
                    f"- **Lowest Subject Attendance**: `{m.get('lowest_subject_pct', 0):.1f}%`\n"
                    f"- **MST Eligibility Status**: **{status}**{override}\n"
                )
                return {"type": "answer", "content": content}

        # Check for teaching / timetable clashes during exams
        if any(w in msg for w in ["teaching", "clash", "free faculty", "available faculty", "duty free"]):
            rows = conn.execute(
                text("""
                    SELECT ft.day_of_week, ft.period_start, ft.period_end, ft.subject_code, ft.room,
                           c.name AS class_name, ft.year, f.name AS faculty_name
                    FROM faculty_timetable ft
                    JOIN faculty f ON f.id = ft.faculty_id
                    JOIN classes c ON c.id = ft.class_id
                    ORDER BY ft.day_of_week, ft.period_start
                    LIMIT 20
                """)
            ).fetchall()
            if rows:
                table_lines = ["| Faculty | Class & Year | Day | Time Slot | Subject | Room |", "| :--- | :--- | :--- | :--- | :--- | :--- |"]
                for r in rows:
                    m = dict(r._mapping)
                    table_lines.append(f"| **{m['faculty_name']}** | {m['class_name']} (Yr {m['year']}) | {m['day_of_week']} | {m['period_start']}-{m['period_end']} | {m['subject_code']} | {m.get('room') or '—'} |")
                content = (
                    f"### Faculty Teaching Schedule & Exam Clash Matrix\n\n"
                    f"The duty scheduler automatically cross-references these teaching periods to prevent booking faculty who are actively teaching other classes during exam hours:\n\n" +
                    "\n".join(table_lines)
                )
                return {"type": "answer", "content": content}

        # Check for borderline queries
        if "borderline" in msg or "border line" in msg:
            conds = ["overall_pct >= 45", "overall_pct < 50"]
            params = {}
            if target_class:
                conds.append("class_name = :cls")
                params["cls"] = target_class
            if target_year:
                conds.append("class_year = :yr")
                params["yr"] = target_year
            if target_exam:
                conds.append("mst_label = :exam")
                params["exam"] = target_exam

            where_str = " WHERE " + " AND ".join(conds)
            rows = conn.execute(
                text(f"SELECT roll_number, student_name, class_name, class_year, mst_label, overall_pct FROM ai_attendance_summary{where_str} ORDER BY overall_pct ASC LIMIT 30"),
                params
            ).fetchall()

            if rows:
                table_lines = ["| Roll Number | Student Name | Class | Year | Exam | Attendance |", "| :--- | :--- | :--- | :--- | :--- | :--- |"]
                for r in rows:
                    m = dict(r._mapping)
                    table_lines.append(f"| `{m['roll_number']}` | {m['student_name']} | {m['class_name']} | Yr {m['class_year']} | {m.get('mst_label') or 'MST-1'} | **{m['overall_pct']:.1f}%** |")
                sub_title_parts = []
                if target_class: sub_title_parts.append(target_class)
                if target_year: sub_title_parts.append(f"Year {target_year}")
                if target_exam: sub_title_parts.append(target_exam)
                sub_title = f" ({', '.join(sub_title_parts)})" if sub_title_parts else ""
                content = (
                    f"### Borderline Students (45% - 49.9% Attendance){sub_title}\n\n"
                    f"Found **{len(rows)}** borderline candidates requiring departmental review:\n\n" +
                    "\n".join(table_lines)
                )
                return {"type": "answer", "content": content}
            desc_parts = []
            if target_class: desc_parts.append(f"for {target_class}")
            if target_year: desc_parts.append(f"in Year {target_year}")
            if target_exam: desc_parts.append(f"for {target_exam}")
            desc = " " + " ".join(desc_parts) if desc_parts else ""
            return {"type": "answer", "content": f"No borderline students found with attendance between 45% and 50%{desc}."}

        # Check for VT candidates / remedial queries
        if any(w in msg for w in ["vt", "remedial", "follow-up", "follow up", "candidate"]):
            conds = []
            params = {}
            if target_class:
                conds.append("class_name = :cls")
                params["cls"] = target_class
            if target_year:
                conds.append("class_year = :yr")
                params["yr"] = target_year

            where_str = (" WHERE " + " AND ".join(conds)) if conds else ""

            total_evaluated = conn.execute(
                text(f"SELECT COUNT(*) FROM v_vt_follow_up_status{where_str}"), params
            ).scalar() or 0

            status_rows = conn.execute(
                text(f"SELECT final_status, COUNT(*) FROM v_vt_follow_up_status{where_str} GROUP BY final_status"), params
            ).fetchall()
            counts = {r[0]: r[1] for r in status_rows}

            compulsory = counts.get("compulsory", 0)
            under_review = counts.get("under_review", 0)
            excused = counts.get("excused", 0)
            not_required = counts.get("not_required", 0)
            completed = counts.get("completed", 0)

            action_conds = ["final_status IN ('compulsory', 'under_review', 'excused')"]
            if target_class: action_conds.append("class_name = :cls")
            if target_year: action_conds.append("class_year = :yr")
            action_where = " WHERE " + " AND ".join(action_conds)

            action_rows = conn.execute(
                text(f"SELECT roll_number, student_name, class_name, class_year, mst_1_label, mst_2_label, final_status, override_reason FROM v_vt_follow_up_status{action_where} ORDER BY CASE WHEN final_status = 'compulsory' THEN 1 WHEN final_status = 'excused' THEN 2 ELSE 3 END, roll_number ASC LIMIT 30"),
                params
            ).fetchall()

            table_section = ""
            if action_rows:
                table_lines = ["| Roll Number | Student Name | Class | Year | VT Status | Reason / Notes |", "| :--- | :--- | :--- | :--- | :--- | :--- |"]
                for r in action_rows:
                    m = dict(r._mapping)
                    badge_status = f"**{m['final_status'].upper()}**" if m['final_status'] == 'compulsory' else m['final_status']
                    table_lines.append(f"| `{m['roll_number']}` | {m['student_name']} | {m['class_name']} | Yr {m['class_year']} | {badge_status} | {m.get('override_reason') or 'Absent in both MST-1 & MST-2'} |")
                table_section = "\n\n### Students Flagged for Follow-Up Action\n" + "\n".join(table_lines)
            elif compulsory == 0:
                table_section = f"\n\n*Zero students are currently flagged as compulsory for VT follow-up. All {total_evaluated} evaluated students have cleared MST or are excused.*"

            title_parts = []
            if target_class: title_parts.append(target_class)
            if target_year: title_parts.append(f"Year {target_year}")
            title_suffix = f" ({', '.join(title_parts)})" if title_parts else ""

            content = (
                f"### Vocational Training (VT) / Follow-up Status Overview{title_suffix}\n\n"
                f"- **Rule Engine**: Students absent in **both MST-1 and MST-2** are flagged for compulsory remedial VT.\n"
                f"- **Total Students Evaluated**: `{total_evaluated}`\n"
                f"- **Compulsory Follow-Up** (Absent in both MST-1 & MST-2): `{compulsory}`\n"
                f"- **Completed & Exempted** (Cleared MST): `{not_required + completed}`\n"
                f"- **Under Review** (Pending roll-call data): `{under_review}`\n"
                f"- **Excused / Approved** (Authorized overrides): `{excused}`"
                f"{table_section}"
            )
            return {"type": "answer", "content": content}

        # Check for Duty roster queries
        if any(w in msg for w in ["duty", "duties", "invigilat", "roster"]):
            rows = conn.execute(
                text("SELECT mst_label, exam_date, room_number, faculty_name, duty_status FROM ai_duty_roster ORDER BY exam_date DESC LIMIT 15")
            ).fetchall()
            if rows:
                table_lines = ["| Exam | Date | Room | Faculty Assigned | Duty Status |", "| :--- | :--- | :--- | :--- | :--- |"]
                for r in rows:
                    m = dict(r._mapping)
                    table_lines.append(f"| {m['mst_label']} | {m.get('exam_date') or 'Scheduled'} | **{m['room_number']}** | {m.get('faculty_name') or 'Unassigned'} | {m['duty_status']} |")
                content = (
                    f"### Examination Invigilation Roster\n\n"
                    f"Live duty assignments from the exam schedule:\n\n" +
                    "\n".join(table_lines)
                )
                return {"type": "answer", "content": content}
            return {"type": "answer", "content": "No duty assignments have been created yet. Generate them in the Duty Scheduler tab."}

        # Check for Eligibility count / general stats
        conds = []
        params = {}
        if target_class:
            conds.append("class_name = :cls")
            params["cls"] = target_class
        if target_year:
            conds.append("class_year = :yr")
            params["yr"] = target_year
        if target_exam:
            conds.append("mst_label = :exam")
            params["exam"] = target_exam

        where_str = (" WHERE " + " AND ".join(conds)) if conds else ""
        rows = conn.execute(
            text(f"SELECT class_name, class_year, mst_label, eligible_count, ineligible_count, missing_count FROM ai_eligibility_summary{where_str} ORDER BY class_year, class_name, mst_label"),
            params
        ).fetchall()

        if rows:
            total_eligible = sum(dict(r._mapping).get("eligible_count", 0) for r in rows)
            total_ineligible = sum(dict(r._mapping).get("ineligible_count", 0) for r in rows)
            total_missing = sum(dict(r._mapping).get("missing_count", 0) for r in rows)
            table_lines = ["| Class | Year | Exam | Eligible (>=45%) | Ineligible (<45%) | Pending Attendance |", "| :--- | :--- | :--- | :--- | :--- | :--- |"]
            for r in rows:
                m = dict(r._mapping)
                table_lines.append(f"| **{m['class_name']}** | Yr {m['class_year']} | {m['mst_label']} | **{m['eligible_count']}** eligible | {m['ineligible_count']} ineligible | {m['missing_count']} pending |")

            title_parts = []
            if target_class: title_parts.append(target_class)
            if target_year: title_parts.append(f"Year {target_year}")
            if target_exam: title_parts.append(target_exam)
            title_suffix = f" ({', '.join(title_parts)})" if title_parts else ""

            content = (
                f"### Examination Eligibility Summary{title_suffix}\n\n"
                f"- **Total Eligible Records**: `{total_eligible}`\n"
                f"- **Total Ineligible Records**: `{total_ineligible}`\n"
                f"- **Pending Attendance Records**: `{total_missing}`\n\n" +
                "\n".join(table_lines)
            )
            return {"type": "answer", "content": content}

        # Default fallback overview
        total_students = conn.execute(text("SELECT COUNT(*) FROM students")).scalar() or 0
        total_classes = conn.execute(text("SELECT COUNT(*) FROM classes")).scalar() or 0
        total_rooms = conn.execute(text("SELECT COUNT(*) FROM rooms")).scalar() or 0
        return {
            "type": "answer",
            "content": (
                f"### MST Operations Portal Assistant\n\n"
                f"System status: **{total_students} students**, **{total_classes} classes (2nd & 3rd Year)**, and **{total_rooms} examination rooms** loaded.\n\n"
                f"You can ask me to:\n"
                f"- Check eligibility: *'How many students are eligible for MST-1 in CI-1?'*\n"
                f"- Compare MSTs: *'Show eligibility comparison for MST-1 and MST-2'* \n"
                f"- List borderline students: *'List borderline students in 2nd year'* \n"
                f"- Check VT candidates: *'Who are the VT candidates after MST-2 in CI-1?'*\n"
                f"- Check teaching clashes: *'Show teachers who are teaching other classes during exam'* \n"
                f"- Inspect a student: *'Attendance for roll 0827CI241001'*"
            )
        }


