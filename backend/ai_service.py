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

import hashlib
import hmac
import json
import os
import re
import time
from typing import Optional
import uuid
import httpx
from dotenv import load_dotenv


load_dotenv()

from sqlalchemy.orm import Session
from sqlalchemy import text
import models

# ── Trusted Identity Context Configuration (Stage B4.2B.2 & B4.2B.5) ──────────
KNOWN_INSECURE_DEV_SECRET = "eduduty_insecure_default_hmac_secret_for_dev_only_32b"


def get_rls_hmac_secret() -> str:
    """
    Retrieve and validate the HMAC signing key for PostgreSQL Row-Level Security identity context.
    Fails closed if the secret is missing, empty, matches known insecure development defaults,
    or has insufficient entropy (< 32 characters).
    """
    secret = os.environ.get("EDUDUTY_RLS_HMAC_SECRET", "").strip()
    if not secret:
        raise RuntimeError(
            "CRITICAL SECURITY CONFIGURATION ERROR: EDUDUTY_RLS_HMAC_SECRET environment variable "
            "is missing or empty. A secure high-entropy signing secret must be supplied."
        )
    if secret == KNOWN_INSECURE_DEV_SECRET:
        raise RuntimeError(
            "CRITICAL SECURITY CONFIGURATION ERROR: The known insecure development signing secret "
            "is rejected. Production and deployable environments must configure a unique, high-entropy secret."
        )
    if len(secret) < 32:
        raise RuntimeError(
            "CRITICAL SECURITY CONFIGURATION ERROR: EDUDUTY_RLS_HMAC_SECRET has insufficient entropy "
            "(minimum 32 characters required)."
        )
    return secret


def mint_signed_identity_context(current_user: Optional[models.User]) -> dict:
    """
    Generate an authenticated, cryptographically signed identity context for PostgreSQL queries.
    Prevents unauthorized GUC manipulation or identity spoofing by untrusted database roles.
    """
    user_id_str = str(current_user.id) if (current_user and current_user.id is not None) else ""
    fac_id_str = str(current_user.faculty_id) if (current_user and current_user.faculty_id is not None) else ""
    role_str = (current_user.role or "").strip().lower() if current_user else ""
    issued_at = str(int(time.time()))
    nonce = uuid.uuid4().hex[:16]

    secret = get_rls_hmac_secret()
    canonical_payload = f"{user_id_str}:{fac_id_str}:{role_str}:{issued_at}:{nonce}"
    sig = hmac.new(
        secret.encode("utf-8"),
        canonical_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return {
        "uid": user_id_str,
        "fac_id": fac_id_str,
        "role": role_str,
        "ts": issued_at,
        "nonce": nonce,
        "sig": sig,
    }

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

- ai_eligibility_summary(class_name, mst_label, eligible_count, borderline_count, ineligible_count, missing_count)
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
    # 1. Strip comments before validation
    clean_sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    clean_sql = re.sub(r"--.*$", "", clean_sql, flags=re.MULTILINE)
    stripped = clean_sql.strip().rstrip(";").strip()

    # Reject multi-statement queries
    if ";" in stripped:
        raise ValueError("Multi-statement SQL queries are forbidden.")

    if not stripped.upper().startswith("SELECT"):
        raise ValueError("Only SELECT statements are allowed.")

    # Reject schema prefixes (quoted or unquoted: main., "main"., public., etc.)
    if re.search(r'(?:\b|")?(?:main|public|sqlite_master|information_schema)(?:\b|")?\s*\.', stripped, re.IGNORECASE):
        raise ValueError("Schema-qualified table names are forbidden.")

    # Block any dangerous keywords, session configuration changes, or CTE overrides
    dangerous = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|GRANT|REVOKE|TRUNCATE|EXEC|EXECUTE|PRAGMA|WITH|SET|SET_CONFIG|CURRENT_SETTING)\b",
        re.IGNORECASE,
    )
    if dangerous.search(stripped):
        raise ValueError("Statement contains forbidden keywords or WITH clauses.")

    # Ensure only allowed views are referenced (ignoring optional quotes)
    token_pattern = re.compile(r'\b(?:FROM|JOIN)\s+(?:"?([a-z0-9_]+)"?)', re.IGNORECASE)
    for match in token_pattern.finditer(stripped):
        table = match.group(1).lower()
        if table not in ALLOWED_READ_VIEWS:
            raise ValueError(f"Access to '{table}' is not permitted. Allowed: {ALLOWED_READ_VIEWS}")

    return stripped


# ── Structured Reporting Operations (Production Path) ─────────────────────────

STRUCTURED_REPORTING_OPS = {
    "get_eligibility_summary": {
        "description": "Aggregated count of eligible, borderline, ineligible, and missing students per class/exam.",
        "view": "ai_eligibility_summary",
        "permitted_roles": {"ADMIN", "EXAM_COORDINATOR", "FACULTY"},
        "pii": False,
        "allowed_args": {"class_name", "mst_label"},
    },
    "get_attendance_summary": {
        "description": "Per-student overall and lowest subject attendance percentages.",
        "view": "ai_attendance_summary",
        "permitted_roles": {"ADMIN", "EXAM_COORDINATOR", "FACULTY"},
        "pii": True,
        "allowed_args": {"class_name", "roll_number", "min_pct", "max_pct"},
    },
    "get_vt_candidates": {
        "description": "List students flagged for Virtual Test candidates based on MST status.",
        "view": "ai_vt_candidates",
        "permitted_roles": {"ADMIN", "EXAM_COORDINATOR", "FACULTY"},
        "pii": True,
        "allowed_args": {"class_name", "roll_number"},
    },
    "get_duty_roster": {
        "description": "Invigilation duty allocation details per exam date, room, and faculty.",
        "view": "ai_duty_roster",
        "permitted_roles": {"ADMIN", "EXAM_COORDINATOR", "FACULTY"},
        "pii": True,
        "allowed_args": {"mst_label", "room_number", "faculty_name"},
    },
    "get_vt_follow_up_status": {
        "description": "VT follow-up statuses, appearance records, and override reasons.",
        "view": "v_vt_follow_up_status",
        "permitted_roles": {"ADMIN", "EXAM_COORDINATOR", "FACULTY"},
        "pii": True,
        "allowed_args": {"class_name", "roll_number", "final_status"},
    },
}


def execute_structured_reporting_op(
    op_name: str,
    args: dict,
    read_db: Session,
    current_user: Optional[models.User] = None,
    scope_class_names: Optional[set] = None,
    user_faculty_name: Optional[str] = None,
) -> dict:
    """
    Execute a production-grade fixed reporting query with typed arguments and server-enforced scope.
    The LLM chooses the operation and arguments; the server owns SQL generation and authorization.
    """
    if op_name not in STRUCTURED_REPORTING_OPS:
        raise ValueError(f"Unknown reporting operation '{op_name}'. Allowed: {set(STRUCTURED_REPORTING_OPS.keys())}")

    meta = STRUCTURED_REPORTING_OPS[op_name]
    user_role = current_user.role if current_user else "VIEWER"
    if user_role not in meta["permitted_roles"]:
        raise ValueError(f"Role '{user_role}' is not authorized to execute operation '{op_name}'.")

    view_name = meta["view"]
    where_clauses = []
    params = {}

    # 1. Enforce Server-Derived Role Scope
    if scope_class_names is not None and view_name != "ai_duty_roster":
        if scope_class_names:
            p_keys = []
            for idx, cname in enumerate(sorted(scope_class_names)):
                pk = f"scope_cls_{idx}"
                params[pk] = cname
                p_keys.append(f":{pk}")
            where_clauses.append(f"class_name IN ({', '.join(p_keys)})")
        else:
            where_clauses.append("1=0")

    # 2. Process Typed User Arguments
    for key, val in args.items():
        if key not in meta["allowed_args"] or val is None:
            continue
        if key == "class_name":
            params["arg_cname"] = str(val).strip()
            where_clauses.append("class_name = :arg_cname")
        elif key == "mst_label":
            params["arg_mst"] = str(val).strip()
            where_clauses.append("mst_label = :arg_mst")
        elif key == "roll_number":
            params["arg_roll"] = str(val).strip()
            where_clauses.append("roll_number = :arg_roll")
        elif key == "room_number":
            params["arg_room"] = str(val).strip()
            where_clauses.append("room_number = :arg_room")
        elif key == "faculty_name":
            params["arg_fac"] = f"%{str(val).strip()}%"
            where_clauses.append("LOWER(faculty_name) LIKE LOWER(:arg_fac)")
        elif key == "final_status":
            params["arg_status"] = str(val).strip()
            where_clauses.append("final_status = :arg_status")
        elif key == "min_pct":
            try:
                params["arg_min_pct"] = float(val)
                where_clauses.append("overall_pct >= :arg_min_pct")
            except (ValueError, TypeError):
                where_clauses.append("1=0")
        elif key == "max_pct":
            try:
                params["arg_max_pct"] = float(val)
                where_clauses.append("overall_pct <= :arg_max_pct")
            except (ValueError, TypeError):
                where_clauses.append("1=0")

    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    sql = f"SELECT * FROM {view_name}{where_sql}"

    # Enforce transaction-scoped identity context on PostgreSQL
    is_pg = False
    try:
        bind = read_db.get_bind()
        is_pg = (bind.dialect.name == "postgresql") if bind else False
    except Exception:
        pass

    try:
        if is_pg:
            ctx = mint_signed_identity_context(current_user)
            read_db.execute(
                text("""
                    SELECT set_config('app.current_user_id', :uid, true),
                           set_config('app.current_faculty_id', :fac_id, true),
                           set_config('app.current_user_role', :role, true),
                           set_config('app.current_context_issued_at', :ts, true),
                           set_config('app.current_context_nonce', :nonce, true),
                           set_config('app.current_context_signature', :sig, true)
                """),
                ctx,
            )

        rows = read_db.execute(text(sql), params).fetchmany(100)
        data = [dict(r._mapping) for r in rows]
    finally:
        if is_pg:
            try:
                read_db.rollback()
            except Exception:
                pass

    return {
        "operation": op_name,
        "view": view_name,
        "pii_contained": meta["pii"],
        "count": len(data),
        "data": data,
    }


# ── Write op dispatcher ────────────────────────────────────────────────────────

def execute_write_op(op_json: dict, db: Session, current_user: Optional[models.User] = None, ai_user_label: str = "AI_AGENT") -> dict:
    """
    Execute a validated write operation through the ORM (never raw SQL).
    Enforces exact matching, actor audit tracking, and hard business constraint validation.
    Returns a dict describing what changed.
    """
    op = op_json.get("operation")
    user_id = current_user.id if current_user else None

    if op == "override_eligibility":
        roll    = str(op_json["roll_number"]).strip()
        label   = str(op_json["mst_label"]).strip()
        reason  = str(op_json["reason"]).strip()

        # Enforce exact roll number matching (IDOR and precision protection)
        student = db.query(models.Student).filter(models.Student.roll_number == roll).first()
        if not student:
            raise ValueError(f"Student with roll number '{roll}' not found.")
        exam = db.query(models.MstExam).filter(models.MstExam.label == label).first()
        if not exam:
            raise ValueError(f"Exam '{label}' not found.")
        el = db.query(models.MstEligibility).filter_by(
            student_id=student.id, mst_exam_id=exam.id
        ).first()
        if not el:
            raise ValueError("Eligibility record not found for this student/exam.")

        old_override = el.override
        el.override = True
        el.override_reason = reason
        el.override_by = user_id

        log = models.AuditLog(
            table_name="mst_eligibility",
            record_id=el.id,
            field_changed="override",
            old_value=str(old_override),
            new_value="True",
            changed_by=user_id,
            reason=f"[AI] {reason}",
        )
        db.add(log)
        db.commit()
        return {"changed": "override_eligibility", "roll_number": roll, "exam": label, "reason": reason}

    elif op == "mark_attempt_status":
        roll   = str(op_json["roll_number"]).strip()
        label  = str(op_json["mst_label"]).strip()
        status = str(op_json["status"]).strip()
        allowed_statuses = {"Present", "Absent", "Late", "Excused", "Signature missing"}
        if status not in allowed_statuses:
            raise ValueError(f"Invalid status '{status}'. Must be one of {allowed_statuses}")

        student = db.query(models.Student).filter(models.Student.roll_number == roll).first()
        if not student:
            raise ValueError(f"Student '{roll}' not found.")
        exam = db.query(models.MstExam).filter(models.MstExam.label == label).first()
        if not exam:
            raise ValueError(f"Exam '{label}' not found.")

        # Enforce invigilator room assignment authorization if caller is operational user
        if current_user and current_user.role in ("FACULTY", "INVIGILATOR"):
            from api.dependencies import verify_invigilator_room_assignment
            verify_invigilator_room_assignment(db, current_user, mst_exam_id=exam.id, student_id=student.id)

        attempt = db.query(models.MstAttempt).filter_by(
            student_id=student.id, mst_exam_id=exam.id
        ).first()
        if attempt:
            old_status = attempt.status
            attempt.status = status
            attempt.marked_by = current_user.faculty_id if (current_user and current_user.faculty_id) else attempt.marked_by
        else:
            attempt = models.MstAttempt(
                student_id=student.id,
                mst_exam_id=exam.id,
                status=status,
                marked_by=current_user.faculty_id if (current_user and current_user.faculty_id) else None
            )
            db.add(attempt)
            old_status = "None"

        log = models.AuditLog(
            table_name="mst_attempts",
            record_id=attempt.id if attempt.id else 0,
            field_changed="status",
            old_value=old_status,
            new_value=status,
            changed_by=user_id,
            reason="[AI] mark_attempt_status",
        )
        db.add(log)
        db.commit()
        return {"changed": "mark_attempt_status", "roll_number": roll, "exam": label, "status": status}

    elif op == "assign_duty":
        faculty_name = str(op_json["faculty_name"]).strip()
        label        = str(op_json["mst_label"]).strip()
        room_number  = str(op_json["room_number"]).strip()

        faculty = db.query(models.Faculty).filter(
            models.Faculty.name.ilike(f"%{faculty_name}%")
        ).first()
        if not faculty:
            raise ValueError(f"Faculty '{faculty_name}' not found.")
        exam = db.query(models.MstExam).filter(models.MstExam.label == label).first()
        if not exam:
            raise ValueError(f"Exam '{label}' not found.")
        room = db.query(models.Room).filter(models.Room.room_number == room_number).first()
        if not room:
            raise ValueError(f"Room '{room_number}' not found.")

        # Hard constraint check: faculty duty exemption and timetable availability
        if faculty.exempt_from_duty:
            raise ValueError(f"Faculty '{faculty.name}' is exempt from invigilation duty ({faculty.exempt_reason or 'Exempt'}).")

        import crud
        day = exam.exam_date.strftime("%a").upper() if exam.exam_date else None
        if day:
            day = {"THU": "THUR"}.get(day, day)
            start, end = "09:00", "12:00"
            if exam.time_slot and "-" in exam.time_slot:
                parts = [p.strip() for p in exam.time_slot.split("-", 1)]
                if len(parts) == 2 and all(parts):
                    start, end = parts
            avail = crud.check_faculty_availability(db, day, start, end)
            f_avail = next((a for a in avail if a.faculty_id == faculty.id), None)
            if f_avail and f_avail.status == "Blocked":
                raise ValueError(f"Faculty '{faculty.name}' has a timetable teaching conflict: {f_avail.reason}")

        duty = db.query(models.InvigilationDuty).filter_by(
            mst_exam_id=exam.id, room_id=room.id
        ).first()
        if not duty:
            raise ValueError("No duty slot found for that exam+room combination.")
        if duty.status == "Assigned":
            raise ValueError("Duty already assigned to another faculty. Use replace workflow.")

        duty.faculty_id = faculty.id
        duty.status = "Assigned"

        log = models.AuditLog(
            table_name="invigilation_duties",
            record_id=duty.id,
            field_changed="faculty_id",
            old_value="None",
            new_value=str(faculty.id),
            changed_by=user_id,
            reason="[AI] assign_duty",
        )
        db.add(log)
        db.commit()
        return {"changed": "assign_duty", "faculty": faculty.name, "exam": label, "room": room_number}

    else:
        raise ValueError(f"Unsupported or unrecognised operation: '{op}'")


STRUCTURED_READ_PROMPT = """
You are a reporting assistant for an MST (midterm exam) operations database.
Your job is to select the appropriate reporting operation and extract typed arguments as JSON.

Available operations:
1. get_eligibility_summary
   Arguments: {"class_name": "...", "mst_label": "MST-1 or MST-2"}

2. get_attendance_summary
   Arguments: {"class_name": "...", "roll_number": "...", "min_pct": float, "max_pct": float}

3. get_vt_candidates
   Arguments: {"class_name": "...", "roll_number": "..."}

4. get_duty_roster
   Arguments: {"mst_label": "...", "room_number": "...", "faculty_name": "..."}

5. get_vt_follow_up_status
   Arguments: {"class_name": "...", "roll_number": "...", "final_status": "compulsory|excused|completed|not_required|under_review"}

Rules:
1. Return ONLY valid JSON: {"operation": "<op_name>", "arguments": {...}}
2. Omit any arguments that are not explicitly present in the query.
3. If the request is ambiguous or does not match these operations, return: {"operation": "unsupported", "arguments": {}}
"""


# ── Main AI query handler ──────────────────────────────────────────────────────

async def handle_ai_message(
    message: str,
    db: Session,
    read_db: Optional[Session] = None,
    scope_class_names: Optional[set] = None,
    user_faculty_name: Optional[str] = None,
    current_user: Optional[models.User] = None,
) -> dict:
    """
    Route a user message to read, write, or PDF path.
    Enforces database isolation by executing all AI read queries strictly over read_db.
    Enforces Layer 2 scope wrapping across all 5 approved views.
    Production path uses Structured Reporting Operations (ENABLE_FREEFORM_SQL_READ=False).
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

    # ── Read / Q&A path (SEC-04 Isolated Database Reader Execution) ───────────
    _created_local_read_db = False
    if read_db is None:
        try:
            from database import AIReaderSessionLocal
            read_db = AIReaderSessionLocal()
            _created_local_read_db = True
        except Exception:
            return {
                "type": "error",
                "content": "AI reader database connection is currently unavailable. Please contact system administrator."
            }

    try:
        app_env = os.environ.get("APP_ENV", "").strip().lower()
        is_dev_env = app_env in ("development", "dev", "test", "testing")
        raw_freeform = os.environ.get("ENABLE_FREEFORM_SQL_READ", "false").strip().lower() in ("true", "1", "yes")
        enable_freeform = raw_freeform and is_dev_env

        if not enable_freeform:
            # ── Production Path: Structured Reporting Operations ───────────────
            try:
                raw_json = await _llm_chat(STRUCTURED_READ_PROMPT, message)
                raw_json = re.sub(r"```[a-z]*\n?", "", raw_json).strip()
                op_json  = json.loads(raw_json)

                op_name = op_json.get("operation")
                op_args = op_json.get("arguments", {})

                if op_name == "unsupported" or op_name not in STRUCTURED_REPORTING_OPS:
                    return {
                        "type": "answer",
                        "content": "I could not map your query to a supported reporting operation. Please specify a class, exam label, or roll number."
                    }

                op_res = execute_structured_reporting_op(
                    op_name=op_name,
                    args=op_args,
                    read_db=read_db,
                    current_user=current_user,
                    scope_class_names=scope_class_names,
                    user_faculty_name=user_faculty_name,
                )

                formatted = await _llm_chat(
                    FORMAT_SYSTEM_PROMPT,
                    f"Question: {message}\nQuery result: {op_res['data']}",
                    temperature=0.3,
                )
                return {
                    "type": "answer",
                    "content": formatted,
                    "structured_op": op_res
                }

            except (json.JSONDecodeError, ValueError) as e:
                return {"type": "error", "content": f"Structured reporting classification failed: {e}"}

        # ── Dev Fallback Path: Text-to-SQL + CTE Scope Injection ──────────────
        sql_raw = await _llm_chat(READ_SYSTEM_PROMPT, message)
        sql     = _validate_read_sql(sql_raw)

        # Apply CTE Scope Header across all 5 approved views if restricted scope is active
        query_params = {}
        if scope_class_names is not None:
            if scope_class_names:
                param_names = []
                for idx, cname in enumerate(sorted(scope_class_names)):
                    pkey = f"scope_cls_{idx}"
                    query_params[pkey] = cname
                    param_names.append(f":{pkey}")
                class_list_str = ", ".join(param_names)
                where_class_clause = f"WHERE class_name IN ({class_list_str})"
            else:
                where_class_clause = "WHERE 1=0"

            if user_faculty_name:
                query_params["user_fac_name"] = user_faculty_name
                where_fac_clause = "WHERE LOWER(faculty_name) = LOWER(:user_fac_name)"
            else:
                where_fac_clause = "WHERE 1=0"

            cte_prefix = f"""WITH
ai_eligibility_summary AS (SELECT * FROM main.ai_eligibility_summary {where_class_clause}),
ai_attendance_summary AS (SELECT * FROM main.ai_attendance_summary {where_class_clause}),
ai_vt_candidates AS (SELECT * FROM main.ai_vt_candidates {where_class_clause}),
v_vt_follow_up_status AS (SELECT * FROM main.v_vt_follow_up_status {where_class_clause}),
ai_duty_roster AS (SELECT * FROM main.ai_duty_roster {where_fac_clause})
"""
            final_sql = f"{cte_prefix}\n{sql}"
        else:
            final_sql = sql

        # Route query STRICTLY through read_db connection
        is_pg = False
        try:
            bind = read_db.get_bind()
            is_pg = (bind.dialect.name == "postgresql") if bind else False
        except Exception:
            pass

        try:
            if is_pg:
                ctx = mint_signed_identity_context(current_user)
                read_db.execute(
                    text("""
                        SELECT set_config('app.current_user_id', :uid, true),
                               set_config('app.current_faculty_id', :fac_id, true),
                               set_config('app.current_user_role', :role, true),
                               set_config('app.current_context_issued_at', :ts, true),
                               set_config('app.current_context_nonce', :nonce, true),
                               set_config('app.current_context_signature', :sig, true)
                    """),
                    ctx,
                )

            rows = read_db.execute(text(final_sql), query_params).fetchmany(100)
            result_str = str([dict(r._mapping) for r in rows])
        finally:
            if is_pg:
                try:
                    read_db.rollback()
                except Exception:
                    pass

        # Format result in plain English
        formatted = await _llm_chat(
            FORMAT_SYSTEM_PROMPT,
            f"Question: {message}\nQuery result: {result_str}",
            temperature=0.3,
        )
        return {"type": "answer", "content": formatted}

    except Exception as e:
        err_msg = str(e)
        if any(k in err_msg.lower() for k in ["read-only", "readonly", "query_only", "permission denied", "cannot execute"]):
            return {"type": "error", "content": "Database operation rejected: AI reader is restricted to read-only queries."}
        return {"type": "error", "content": f"Query failed: {err_msg}"}
    finally:
        if _created_local_read_db and read_db:
            try:
                read_db.close()
            except Exception:
                pass


