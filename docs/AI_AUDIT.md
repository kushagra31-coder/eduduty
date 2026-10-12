# EduDuty — AI Architecture & Integration Audit Report

**Date:** October 6, 2026  
**Status:** Complete  
**Scope:** LLM Provider Pipeline, SQL Generation Safety, Write Proposal Workflow, Compliance with PRD Safeguards  

---

## 1. Provider Chain & Fallback Architecture

The AI module in `backend/ai_service.py` implements a multi-provider fallback architecture:

```text
User Natural Language Input
            │
            ▼
┌────────────────────────┐
│  Provider Chain Check  │
└───────────┬────────────┘
            │
            ├── 1. Groq Cloud API (GROQ_API_KEY) ───► [OpenAI-compatible /chat/completions]
            │
            ├── 2. Gemini Cloud API (GEMINI_API_KEY) ─► [OpenAI-compatible /chat/completions]
            │
            └── 3. Local Ollama (OLLAMA_BASE_URL) ────► [Local HTTP endpoint :11434]
```

### Key Observations:
- **Cloud-First:** Designed to work without local Ollama setup if `GROQ_API_KEY` or `GEMINI_API_KEY` is present.
- **Health Check Endpoint:** Exposes `GET /ai/health` to indicate provider status to the frontend UI banner.

---

## 2. AI Read Path Evaluation

```text
User Question ("How many CI-1 students are eligible for MST-1?")
            │
            ▼
LLM generates SQL SELECT statement using READ_SYSTEM_PROMPT
            │
            ▼
_validate_read_sql(sql) Regex Validation (backend/ai_service.py:228)
  ├── Ensures statement starts with SELECT
  ├── Blocks DDL/DML keywords (INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, etc.)
  └── Restricts referenced tables/views strictly to ALLOWED_READ_VIEWS:
        1. ai_eligibility_summary
        2. ai_attendance_summary
        3. ai_vt_candidates
        4. ai_duty_roster
        5. v_vt_follow_up_status
            │
            ▼
db.execute(text(sql)).fetchall()
            │
            ▼
LLM formats tabular result into plain English summary (FORMAT_SYSTEM_PROMPT)
```

### Safety Assessment:
- ** Strengths:**
  - View restriction prevents AI from reading password hashes or private system audit logs.
  - Regex validator blocks DML and DDL commands.
- ** Security Gaps:**
  - `_validate_read_sql()` relies on Python regex. In a production environment, query execution MUST occur over a dedicated PostgreSQL `ai_readonly` role to enforce SELECT-only permissions at the database engine level.
  - Executed on the main application DB session (`db.execute(text(sql))`), which has full read-write privileges.

---

## 3. AI Write Path Evaluation

The write path implements a strict 2-step Proposal & Confirmation workflow:

```text
User Natural Language Command ("Override eligibility for student 0827CI211001 for MST-1 due to medical certificate")
            │
            ▼
LLM generates structured JSON proposal using WRITE_SYSTEM_PROMPT
            │
            ▼
Pydantic / Allow-List Validation (backend/ai_service.py:416)
  └── Operation MUST be in ALLOWED_WRITE_OPS:
        1. override_eligibility
        2. mark_attempt_status
        3. assign_duty
            │
            ▼
Return Proposal JSON to Frontend:
  {"type": "write_proposal", "content": {"operation": "override_eligibility", ...}}
  (NO DATABASE MUTATION OCCURS AT THIS STAGE)
            │
            ▼
Frontend Renders Interactive Modal with "Confirm" / "Cancel"
            │
            ▼ (User clicks Confirm)
POST /ai/confirm-write (backend/main.py:646)
            │
            ▼
execute_write_op() (backend/ai_service.py:254)
  ├── Executes operation via typed SQLAlchemy ORM calls (never raw SQL)
  └── Creates AuditLog record with reason "[AI] <user_reason>"
```

### Compliance Analysis against PRD Section 22:

| PRD Safeguard Requirement | Current Implementation Status | Evaluation & Audit Notes |
| :--- | :--- | :--- |
| **No arbitrary SQL execution for writes** | **COMPLIANT** | Writes use typed ORM calls in `execute_write_op()`. The LLM never outputs DML SQL. |
| **Operation allow-list enforced** | **COMPLIANT** | Explicitly checked against `ALLOWED_WRITE_OPS` set. |
| **Explicit user confirmation required** | **COMPLIANT** | The API returns `type: "write_proposal"`. Mutation only executes when frontend calls `/ai/confirm-write`. |
| **Every AI write operation audited** | **COMPLIANT** | `execute_write_op()` creates an explicit `AuditLog` row for every mutation. |
| **Role-based authorization for AI writes** | **NON-COMPLIANT** | `execute_write_op()` does not verify if the requesting user possesses the required permission (e.g., `eligibility.override`). |
