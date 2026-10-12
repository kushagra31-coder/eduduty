# EduDuty — Comprehensive Security Audit Report

**Date:** October 6, 2026  
**Status:** Complete  
**Scope:** Vulnerability Assessment & Compliance Analysis against Target Security Architecture  

---

## 1. Security Overview & Severity Matrix

The security audit evaluated the EduDuty prototype repository across 5 core security domains. A total of **8 Critical/High Vulnerabilities (P0/P1)** were identified.

| Vulnerability Category | Severity | Findings Summary | Target Architecture Requirement |
| :--- | :--- | :--- | :--- |
| **Authentication** | **CRITICAL (P0)** | Zero token/session verification; hardcoded `user_id = 1` in backend mutations | Mandatory JWT/Session verification on every protected route |
| **Authorization / RBAC** | **CRITICAL (P0)** | Zero backend permission checks; UI visibility is treated as authorization | Server-side role & permission check middleware |
| **API & CORS** | **CRITICAL (P0)** | Wildcard CORS (`allow_origins=["*"]`); raw traceback leakage in 500 error responses | Restrict CORS allow-list; return sanitized JSON error envelopes |
| **File Upload** | **HIGH (P1)** | In-memory file reads without length limits (`await file.read()`); missing MIME validation | Enforcement of file size limits, MIME type validation, safe temporary storage |
| **AI Security** | **HIGH (P1)** | LLM generates SQL directly; regex validator active but lacks read-only DB role isolation | AI query isolation via dedicated unprivileged DB user & views |

---

## 2. Domain-by-Domain Security Findings

### 2.1 Authentication Audit

#### Finding SEC-01: Complete Absence of Backend Authentication (P0)
- **Location:** `backend/main.py` (all endpoints)
- **Trace:**
  ```python
  @app.post("/eligibility/override/{eligibility_id}")
  def override_eligibility(
      eligibility_id: int,
      override: bool = Body(...),
      reason: str = Body(...),
      db: Session = Depends(get_db)
  ):
      user_id = 1  # <--- HARDCODED ACTOR IDENTITY
      record = crud.update_eligibility_override(db, eligibility_id, override, reason, user_id)
  ```
- **Risk:** Any HTTP client (cURL, Postman, external browser) can execute sensitive administrative actions (overriding eligibility, reassigning duties, marking roll call attendance, exporting confidential student reports) without supplying a session token or credentials.
- **Evidence:** None of the FastAPI route handlers depend on an authentication verification function (e.g., `get_current_user`).

---

### 2.2 Authorization & RBAC Audit

#### Finding SEC-02: Client-Centric Authorization Fallacy (P0)
- **Location:** `frontend/src/app/eligibility/page.tsx`, `frontend/src/app/follow-up/page.tsx`, `backend/main.py`
- **Trace:**
  - The frontend hides or shows "Override" buttons based on local component state.
  - The backend endpoints (e.g., `/follow-up/{id}/override`, `/mst/duties/assign`) contain **zero permission checks**.
- **Risk:** Insecure Direct Object Reference (IDOR) and broken access control. An unauthenticated viewer or student can craft a POST request directly to `/eligibility/override/1` or `/follow-up/1/override` to alter academic eligibility records.

---

### 2.3 API Security Audit

#### Finding SEC-03: Wildcard CORS Configuration (P0)
- **Location:** `backend/main.py:91-97`
- **Trace:**
  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=["*"],
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
- **Risk:** Allowing `allow_origins=["*"]` with `allow_credentials=True` exposes the API to Cross-Origin Resource Sharing (CORS) exploits and malicious cross-domain requests.

#### Finding SEC-04: Internal Exception Leakage (P1)
- **Location:** `backend/main.py:644`, `main.py:657`
- **Trace:**
  ```python
  except Exception as e:
      raise HTTPException(status_code=500, detail=str(e))
  ```
- **Risk:** Exposes raw Python tracebacks, database table names, SQL syntax errors, or internal file paths to public API consumers.

---

### 2.4 File Upload Security Audit

#### Finding SEC-05: Unrestricted Memory Buffer File Parsing (P1)
- **Location:** `backend/main.py:427-429`
- **Trace:**
  ```python
  @app.post("/upload-attendance/")
  async def upload_attendance(file: UploadFile = File(...), db: Session = Depends(get_db)):
      contents = await file.read()  # <--- READS ENTIRE UPLOAD INTO RAM WITHOUT SIZE CAP
      xls = pd.ExcelFile(io.BytesIO(contents))
  ```
- **Risk:** Memory Exhaustion / Denial of Service (DoS). Uploading a 500MB malicious file will attempt to allocate memory inside the Uvicorn worker process, potentially crashing the backend daemon.
- **Missing Controls:** No file size limit check (e.g., 10MB cap), no MIME content-type validation (`file.content_type`), relies solely on filename extension check `.endswith(('.xls', '.xlsx'))`.

---

### 2.5 AI Pipeline Security Audit

#### Finding SEC-06: Direct LLM SQL Generation & Reliance on Regex (P0)
- **Location:** `backend/ai_service.py:228-250`, `ai_service.py:429-434`
- **Trace:**
  - The AI assistant uses `_llm_chat()` to ask the LLM to write raw SQL SELECT queries.
  - Query safety relies entirely on Python regex matching (`_validate_read_sql()`):
    ```python
    if not stripped.upper().startswith("SELECT"):
        raise ValueError("Only SELECT statements are allowed.")
    ```
- **Risk:** Prompt Injection & Evasion. Regex-based SQL validation is notoriously vulnerable to SQL obfuscation, comment injection (`SELECT /*...*/`), nested subselects, or vendor-specific SQL functions.
- **Target Compliance:** The architecture document explicitly requires:
  1. Typed application query operations instead of raw SQL generation.
  2. If SQL generation is retained, it MUST run under a restricted, read-only PostgreSQL database connection (`ai_readonly` DB user).
  3. Currently, the query executes via `db.execute(text(sql))` using the main read-write database session connection!

---

## 3. Mandatory Remediation Checklist for Phase 1 & Subsequent Phases

1. **Authentication:** Implement `get_current_user` dependency validating Supabase JWTs / session tokens.
2. **Authorization:** Implement `require_permission(perm)` dependency enforcing server-side RBAC.
3. **CORS:** Restrict `allow_origins` to explicit environment configuration (`CORS_ALLOWED_ORIGINS`).
4. **File Uploads:** Implement file size ceiling (10 MB), validate magic bytes / MIME types, store temporary files safely.
5. **AI Hardening:** Connect AI read operations to a separate `ai_reader` PostgreSQL engine instance with strict `SELECT`-only view permissions.
