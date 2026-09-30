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
"""

import json
import os
import re
import httpx
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.orm import Session
from sqlalchemy import text
import models

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
#       $env:AI_PROVIDERS="groq,ollama"        # change order / drop providers
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

- ai_eligibility_summary(class_name, mst_label, eligible_count, ineligible_count, missing_count)
- ai_attendance_summary(class_name, roll_number, student_name, overall_pct, lowest_subject_pct)
- ai_vt_candidates(class_name, roll_number, student_name, mst1_status, mst2_status)
- ai_duty_roster(mst_label, exam_date, room_number, faculty_name, duty_status)
- v_vt_follow_up_status(roll_number, student_name, class_name, mst_1_label, mst_2_label,
    mst_1_appeared, mst_2_appeared, calculated_status, final_status, overridden,
    override_reason, rule_version, updated_at)
  calculated_status/final_status are one of: not_required, compulsory, under_review, excused, completed.
  mst_1_appeared/mst_2_appeared are TRUE (present), FALSE (absent), or NULL (missing record).

Rules:
1. Only generate SELECT statements.
2. No subqueries that touch tables not in the list above.
3. Return ONLY the SQL, nothing else. No markdown, no explanation.

Examples:
Q: How many CI-1 students are eligible for MST-1?
A: SELECT eligible_count FROM ai_eligibility_summary WHERE class_name='CI-1' AND mst_label='MST-1';

Q: List borderline students in CI-2
A: SELECT roll_number, student_name, overall_pct FROM ai_attendance_summary WHERE class_name='CI-2' AND overall_pct >= 45 AND overall_pct < 50;

Q: How many CI-1 students are compulsory for VT?
A: SELECT COUNT(*) FROM v_vt_follow_up_status WHERE class_name='CI-1' AND final_status='compulsory';

Q: Which compulsory VT students have been excused?
A: SELECT roll_number, student_name, override_reason FROM v_vt_follow_up_status WHERE final_status='excused';
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
    """Try each configured provider in order; the first success wins."""
    errors = []
    for provider in AI_PROVIDERS:
        try:
            if provider == "groq":
                if not GROQ_API_KEY:
                    errors.append("groq: GROQ_API_KEY not set")
                    continue
                return await _openai_compat_chat(
                    GROQ_BASE_URL, GROQ_API_KEY, GROQ_MODEL, system, user, temperature)
            elif provider == "gemini":
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
        ". Get a free Groq key at https://console.groq.com/keys and set GROQ_API_KEY, "
        "or run Ollama locally."
    )

# ── SQL validator (read path) ──────────────────────────────────────────────────

def _validate_read_sql(sql: str) -> str:
    """Raise ValueError if SQL is not a safe SELECT over allowed views."""
    stripped = sql.strip().rstrip(";").strip()

    if not stripped.upper().startswith("SELECT"):
        raise ValueError("Only SELECT statements are allowed.")

    # Block any dangerous keywords
    dangerous = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|GRANT|TRUNCATE|EXEC|EXECUTE)\b",
        re.IGNORECASE,
    )
    if dangerous.search(stripped):
        raise ValueError("Statement contains forbidden keywords.")

    # Ensure only allowed views are referenced
    token_pattern = re.compile(r"\b(FROM|JOIN)\s+([a-z_]+)", re.IGNORECASE)
    for match in token_pattern.finditer(stripped):
        table = match.group(2).lower()
        if table not in ALLOWED_READ_VIEWS:
            raise ValueError(f"Access to '{table}' is not permitted. Allowed: {ALLOWED_READ_VIEWS}")

    return stripped

# ── Write op dispatcher ────────────────────────────────────────────────────────

def execute_write_op(op_json: dict, db: Session, ai_user_label: str = "AI_AGENT") -> dict:
    """
    Execute a validated write operation through the ORM (never raw SQL).
    Returns a dict describing what changed.
    """
    op = op_json.get("operation")

    if op == "override_eligibility":
        roll    = op_json["roll_number"]
        label   = op_json["mst_label"]
        reason  = op_json["reason"]

        student = db.query(models.Student).filter(models.Student.roll_number == roll).first()
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
            reason=f"[AI] {reason}",
        )
        db.add(log)
        db.commit()
        return {"changed": "override_eligibility", "roll_number": roll, "exam": label, "reason": reason}

    elif op == "mark_attempt_status":
        roll   = op_json["roll_number"]
        label  = op_json["mst_label"]
        status = op_json["status"]
        allowed_statuses = {"Present", "Absent", "Late", "Excused", "Signature missing"}
        if status not in allowed_statuses:
            raise ValueError(f"Invalid status '{status}'. Must be one of {allowed_statuses}")

        student = db.query(models.Student).filter(models.Student.roll_number == roll).first()
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
            reason=f"[AI] mark_attempt_status",
        )
        db.add(log)
        db.commit()
        return {"changed": "mark_attempt_status", "roll_number": roll, "exam": label, "status": status}

    elif op == "assign_duty":
        faculty_name = op_json["faculty_name"]
        label        = op_json["mst_label"]
        room_number  = op_json["room_number"]

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

        duty = db.query(models.InvigilationDuty).filter_by(
            mst_exam_id=exam.id, room_id=room.id
        ).first()
        if not duty:
            raise ValueError("No duty slot found for that exam+room combination.")
        if duty.status == "Assigned":
            raise ValueError(f"Duty already assigned to another faculty. Use replace workflow.")

        duty.faculty_id = faculty.id
        duty.status = "Assigned"

        log = models.AuditLog(
            table_name="invigilation_duties",
            record_id=duty.id,
            field_changed="faculty_id",
            old_value="None",
            new_value=str(faculty.id),
            reason=f"[AI] assign_duty",
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
    if any(k in msg_lower for k in ["pdf", "report", "download", "print"]):
        # Look for a roll number pattern
        roll_match = re.search(r"\b\d{4,}\b", message)
        if roll_match:
            roll = roll_match.group()
            return {
                "type": "pdf_link",
                "content": f"/pdf/student/{roll}",
                "message": f"Here is the PDF report link for roll number {roll}.",
            }
        return {
            "type": "pdf_link",
            "content": "/pdf/seating/1/1",
            "message": "Here is the seating chart PDF link.",
        }

    # ── Write intent detection ────────────────────────────────────────────────
    write_keywords = ["override", "mark", "assign", "update", "change", "set"]
    if any(k in msg_lower for k in write_keywords):
        try:
            raw_json = await _llm_chat(WRITE_SYSTEM_PROMPT, message)
            # Strip any accidental markdown fences
            raw_json = re.sub(r"```[a-z]*\n?", "", raw_json).strip()
            op_json  = json.loads(raw_json)

            if op_json.get("operation") == "unsupported":
                return {"type": "answer", "content": "I'm not sure how to make that change safely. Could you rephrase or use the UI?"}

            # Validate it has required fields before proposing
            if op_json.get("operation") not in ALLOWED_WRITE_OPS:
                raise ValueError("Operation not in allow-list.")

            # Return the proposal — the frontend will show a confirm modal
            return {"type": "write_proposal", "content": op_json}

        except (json.JSONDecodeError, ValueError) as e:
            return {"type": "error", "content": f"Could not parse write intent: {e}"}
        except (ConnectionError, RuntimeError) as e:
            return {"type": "error", "content": str(e)}

    # ── Read / Q&A path ───────────────────────────────────────────────────────
    try:
        sql_raw = await _llm_chat(READ_SYSTEM_PROMPT, message)
        sql     = _validate_read_sql(sql_raw)

        rows = db.execute(text(sql)).fetchall()
        result_str = str([dict(r._mapping) for r in rows])

        # Format result in plain English
        formatted = await _llm_chat(
            FORMAT_SYSTEM_PROMPT,
            f"Question: {message}\nQuery result: {result_str}",
            temperature=0.3,
        )
        return {"type": "answer", "content": formatted}

    except Exception as e:
        return {"type": "error", "content": f"Query failed: {e}"}
