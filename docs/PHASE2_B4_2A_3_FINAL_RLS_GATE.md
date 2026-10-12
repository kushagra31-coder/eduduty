# EduDuty — Phase 2, Stage B4.2A.3: Final Pre-RLS Security Gate Report

**Date:** October 11, 2026  
**Status:** Pre-RLS Security Gate Complete  
**Final Recommendation:** **READY FOR STAGE B4.2B (ROW-LEVEL SECURITY IMPLEMENTATION)**  
**Target Database:** PostgreSQL 16.15 (`eduduty_test_db`) in container `eduduty_pg_b4_test` at `127.0.0.1:5433`  
**Baseline Database:** SQLite `eduduty.db` (100% preserved and untouched)  

---

## 1. Executive Summary & Gate Verdict Matrix

Stage B4.2A.3 performs the final independent security gate verification before implementing Row-Level Security (RLS) in Stage B4.2B. All four gates were rigorously evaluated against PostgreSQL 16 catalogs, source code, test execution traces, and isolation boundaries.

### Gate Evaluation Matrix

| Gate | Title | Verdict | Primary Scope & Verification Method |
| :---: | :--- | :---: | :--- |
| **A** | **Provisioning Privilege Reconciliation** | **PASS** | Live execution and catalog audit of [scripts/provision_ai_reader.sql](file:///d:/Code/eduduty/scripts/provision_ai_reader.sql). Confirmed stripping of stale table/column privileges, role memberships, and default ACLs. Role has zero object ownership and zero write/DDL rights. |
| **B** | **PostgreSQL Test Validity** | **PASS** | Verified failure modes, SQLite non-substitution, explicit role authentication (`current_user = 'ai_reader'`), zero skipped tests in required mode (116/116 passed), and downgrade safety wrappers. |
| **C** | **Credential Hygiene & Rotation** | **PASS** | Repository scan confirmed zero hardcoded secrets. Identified previously exposed container token and provided a safe, non-destructive operator rotation procedure. |
| **D** | **RLS Readiness Assessment** | **PASS** | Detailed the exact security contract for Stage B4.2B (active `FacultyTimetable` and `timetable_versions.active = true` scoping, fail-closed unversioned access, institution-wide duty roster exception, transaction-scoped `SET LOCAL` context). |

---

## 2. Gate A: Provisioning Privilege Reconciliation Audit

### 2.1 Privilege Stripping & Reconciliation Design ([scripts/provision_ai_reader.sql](file:///d:/Code/eduduty/scripts/provision_ai_reader.sql))
The provisioning artifact was enhanced and verified against the PostgreSQL test container:
1. **Idempotent Role Definition:**
   Enforces `NOSUPERUSER`, `NOBYPASSRLS`, `NOCREATEDB`, `NOCREATEROLE`, `NOINHERIT` whether the role is being created from scratch or reconciled.
2. **Role Membership Stripping:**
   Explicitly queries `pg_auth_members` and revokes any group memberships granted to `ai_reader`, guaranteeing the role cannot inherit administrative privileges.
3. **Stale Privilege Purging:**
   Executes `REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM ai_reader;` which PostgreSQL 15+ confirms strips **both** table-level and column-level privileges.
   Revokes all sequences, routines, and schema `CREATE` privileges.
4. **Default Privilege Immunity:**
   Executes `ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES/SEQUENCES/ROUTINES FROM ai_reader;` ensuring future table creations by `postgres` or other users never grant permissions to `ai_reader`.
5. **Approved Least-Privilege Re-granting:**
   - Table-level `SELECT` strictly on the 5 approved views: `ai_duty_roster`, `ai_attendance_summary`, `ai_eligibility_summary`, `ai_vt_candidates`, `v_vt_follow_up_status`.
   - Column-level `SELECT` on only the exact base columns queried by the views (`classes`, `mst_exams`, `students`, `mst_eligibility`, `follow_up_statuses`, `invigilation_duties`, `rooms`, `faculty`).
6. **Object Ownership Assertion:**
   A trailing PL/pgSQL block asserts `ai_reader` owns 0 objects in `pg_class`, aborting with an exception if ownership is detected.

### 2.2 Live PostgreSQL Catalog Evidence
Inspected `pg_roles`, `pg_auth_members`, and `information_schema`:

#### 1. Role Attributes (`pg_roles`):
```text
  rolname  | rolsuper | rolinherit | rolcreaterole | rolcreatedb | rolcanlogin | rolreplication | rolbypassrls 
-----------+----------+------------+---------------+-------------+-------------+----------------+--------------
 ai_reader | f        | f          | f             | f           | t           | f              | f
```

#### 2. Role Memberships (`pg_auth_members`):
```text
 role | member 
------+--------
(0 rows)
```

#### 3. Table Privileges (`information_schema.table_privileges`):
```text
table_name             | privilege_type 
-----------------------+----------------
ai_attendance_summary  | SELECT
ai_duty_roster         | SELECT
ai_eligibility_summary | SELECT
ai_vt_candidates       | SELECT
v_vt_follow_up_status  | SELECT
```
*Base Tables:* Exactly **0** table-level privileges granted. Direct `SELECT *` fails on all base tables.

---

## 3. Gate B: PostgreSQL Test Validity Audit

### 3.1 Failure Mode & Dialect Gate Validation
- **Missing Configuration:** When `EDUDUTY_REQUIRE_POSTGRES_TESTS=1` is active and configuration is missing, tests exit immediately with `pytest.fail`:
  ```text
  Failed: BLOCKED: EDUDUTY_REQUIRE_POSTGRES_TESTS=1 is set, but PostgreSQL test configuration is missing.
  ```
- **Unreachable Database:** When `EDUDUTY_REQUIRE_POSTGRES_TESTS=1` points to an unreachable port, tests fail immediately without silent skips or fallbacks.
- **Dialect Non-Substitution:** If `POSTGRES_TEST_DATABASE_URL` is set to an SQLite URL (e.g. `sqlite:///...`), the test suite aborts with:
  ```text
  BLOCKED: EDUDUTY_REQUIRE_POSTGRES_TESTS=1 is set, but Configured database URL dialect is not PostgreSQL. SQLite databases cannot satisfy PostgreSQL integration tests.
  ```

### 3.2 Live Identity Verification in Integration Tests
In [backend/tests/test_alembic_b42a_ai_reader.py:192-195](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py#L192-L195), live tests query PostgreSQL:
```python
curr_user = conn.execute(text("SELECT current_user;")).scalar()
assert curr_user == "ai_reader"
```
Confirmed: The tests genuinely authenticate as `ai_reader`, not as an administrator.

### 3.3 Column vs Row Access Distinction
Tests explicitly separate:
1. `SELECT * FROM students;` $\rightarrow$ **DENIED** (`permission denied for table students`).
2. `SELECT id, name, roll_number FROM students;` $\rightarrow$ **ALLOWED** (column-level grant).
The test suite explicitly asserts and documents that column-level access remains possible until Stage B4.2B enables table-level RLS.

### 3.4 Migration Downgrade Isolation
In [backend/tests/test_alembic_b42a_ai_reader.py:94-124](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py#L94-L124), Alembic downgrade to `005_ai_views_integrity` is wrapped in `try...finally`:
```python
try:
    command.downgrade(cfg, "005_ai_views_integrity")
    ...
finally:
    command.upgrade(cfg, "head")
```
Guarantees that even if an assertion in the downgrade phase fails, the shared test database is restored to `006_secure_ai_views`.

### 3.5 Test Suite Execution Counts

| Mode | Command | Passed | Skipped | Failed |
| :--- | :--- | :---: | :---: | :---: |
| **SQLite-Only** | `python -m pytest tests/` | **101** | **15** | **0** |
| **PostgreSQL-Required** | `$env:EDUDUTY_REQUIRE_POSTGRES_TESTS='1'; python -m pytest tests/` | **116** | **0** | **0** |

*Verified:* Zero PostgreSQL tests were skipped in required mode.

---

## 4. Gate C: Credential Hygiene & Rotation Assessment

### 4.1 Repository Secret Scan
- **Source Code (`backend/*.py`):** Zero hardcoded passwords found.
- **Tracked Configuration (`.env`):** Contains only commented example URLs.
- **Test Code:** Zero active container tokens found. All previous test fallbacks replaced with `pg_test_config.py`.
- **Masking Strings in Tests:** Only mock test tokens used exclusively for testing URL redaction regexes (`test_redact_url_masks_plaintext_secrets`).

### 4.2 Exposed Credential Categories & Operator Rotation Procedure
The initial random token generated in Stage B4.1 for `eduduty_pg_b4_test` was previously recorded in early test commits before remediation. Although restricted to the local Docker network on port 5433, it is classified as **previously exposed**.

#### Safe Operator Rotation Instructions:
To rotate the container administrator and `ai_reader` passwords without recreating the volume or disrupting data:

```powershell
# 1. Generate strong, unique local secrets (e.g. 32-character hex)
$NEW_ADMIN_SECRET = [System.Guid]::NewGuid().ToString("N")
$NEW_AI_READER_SECRET = [System.Guid]::NewGuid().ToString("N")

# 2. Update passwords inside the container via local psql
docker exec -i eduduty_pg_b4_test psql -U postgres -d eduduty_test_db -c "ALTER ROLE postgres WITH PASSWORD '$NEW_ADMIN_SECRET';"
docker exec -i eduduty_pg_b4_test psql -U postgres -d eduduty_test_db -c "ALTER ROLE ai_reader WITH LOGIN PASSWORD '$NEW_AI_READER_SECRET';"

# 3. Export new credentials into operator session (never commit to git)
$env:PG_TEST_PASSWORD = $NEW_ADMIN_SECRET
$env:AI_READER_DATABASE_URL = "postgresql+pg8000://ai_reader:$NEW_AI_READER_SECRET@127.0.0.1:5433/eduduty_test_db"
```

---

## 5. Gate D: RLS Security Contract for Stage B4.2B

Stage B4.2B must implement the following non-negotiable security requirements:

### 5.1 Timetable-Scoped Access Policy
- **Active Version Scope:** Access to student records (`students`) and exam eligibility (`mst_eligibility`) must be restricted to classes currently assigned to the requesting faculty member in `faculty_timetable`:
  ```sql
  students.class_id IN (
      SELECT ft.class_id 
      FROM faculty_timetable ft
      JOIN timetable_versions tv ON tv.id = ft.timetable_version_id
      WHERE tv.active = true 
        AND ft.faculty_id = current_setting('app.current_faculty_id', true)::int
  )
  ```
- **Historical Attendance Protection:** Historical attendance records do **not** expand access. Even if a faculty member taught class X in a previous semester, they have zero access once the timetable version is archived (`tv.active = false`).
- **Fail-Closed on Unversioned Data:** Null, missing, or unversioned assignments return 0 rows.

### 5.2 Institution-Wide Duty Roster Exception (Approved Policy 2)
- As approved in Stage B3.3.9, authorized faculty may view the institution-wide exam duty schedule (`invigilation_duties` and `ai_duty_roster`) for operational coordination across exam halls.
- This exception is restricted strictly to `invigilation_duties` and does **not** expand student data access or allow cross-class reporting.

### 5.3 Server-Side Context Injection (`SET LOCAL`)
- **Untrusted Client Parameters Prohibited:** The client/frontend must never supply `faculty_id` in SQL statements or request bodies to define security scope.
- **Transaction-Scoped Injection:**
  Within `backend/ai_service.py` (and relevant database sessions), FastAPI extracts `user.faculty_id` from the verified JWT claim, begins a transaction, and executes:
  ```sql
  SET LOCAL app.current_faculty_id = :faculty_id;
  SET LOCAL app.current_user_role = :role;
  ```
- **Connection Pool Safety:** `SET LOCAL` automatically expires upon transaction commit or rollback, preventing context leakage across pooled database connections.

### 5.4 Base Tables Requiring RLS Activation
Because all 5 reporting views specify `WITH (security_invoker = true)`, enabling RLS on the base tables automatically enforces policies on both views and direct table queries:
1. `ALTER TABLE students ENABLE ROW LEVEL SECURITY;`
2. `ALTER TABLE mst_eligibility ENABLE ROW LEVEL SECURITY;`
3. `ALTER TABLE follow_up_statuses ENABLE ROW LEVEL SECURITY;`
4. `ALTER TABLE invigilation_duties ENABLE ROW LEVEL SECURITY;`

### 5.5 Unresolved Policy Choices & Schema Details
- **Super Admin / Exam Coordinator Scope:**
  The RLS policy will include:
  ```sql
  current_setting('app.current_user_role', true) IN ('super_admin', 'exam_coordinator')
  ```
  to allow administrators and exam coordinators institution-wide reporting access.
- **Schema Alignment:**
  PostgreSQL catalog inspection confirms `timetable_versions` uses column `active boolean` (not string status) and `faculty_timetable` links via `timetable_version_id integer`. Stage B4.2B policies will match these exact column names.

---

## 6. Changed Files in B4.2A.3

1. **[scripts/provision_ai_reader.sql](file:///d:/Code/eduduty/scripts/provision_ai_reader.sql):**
   - Added role membership revocation loop.
   - Added `ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ...`.
   - Re-executed cleanly on `eduduty_pg_b4_test`.
2. **[backend/tests/test_alembic_b42a_ai_reader.py](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py):**
   - Added live session identity assertion (`SELECT current_user == 'ai_reader'`) in view read test.

---

## 7. Final Recommendation

# **READY FOR STAGE B4.2B**

All pre-RLS security criteria are satisfied. The database views operate with `security_invoker = true`, the unprivileged `ai_reader` role has `NOBYPASSRLS`, test gating prevents accidental bypass, all 116 tests pass, and zero credentials exist in repository tracking. Stage B4.2B can proceed to implement Row-Level Security policies.
