# EduDuty — Stage B4.1.2: PostgreSQL Driver and Connection Hardening Report

**Date:** October 11, 2026  
**Status:** Stage B4.1.2 Complete  
**Executive Verdict:** **PASS (Connection Hardening & Automated Testing Validated)**  
**RLS Implementation Status:** **Not Implemented / Deferred** (RLS policies and migration 006 strictly deferred)  
**Target Test Database:** PostgreSQL 16.15 (`eduduty_test_db`) in container `eduduty_pg_b4_test` bound to `127.0.0.1:5433`  
**Preserved Baseline:** `eduduty.db` (SQLite development database 100% untouched)  

---

## 1. Executive Summary & Verdict

EduDuty Stage B4.1.2 resolved the driver and connection defects identified during the B4.1.1 audit:
1. **Driver Standardization:** `pg8000==1.31.5` has been explicitly declared in `backend/requirements.txt`.
2. **AI Reader Engine Compatibility:** Removed the libpq-only `connect_args={"options": ...}` failure on `pg8000`. Configured dialect-agnostic, server-side transaction read-only enforcement using SQLAlchemy's `execution_options={"postgresql_readonly": True}`.
3. **Password & Role Separation:** Removed the brittle, hardcoded `replace("postgres:postgres@", "ai_reader:ai_reader_pass@")` string substitution from `backend/database.py`. The AI reader safely uses `AI_READER_DATABASE_URL` if explicitly set, or falls back to `SQLALCHEMY_DATABASE_URL` with enforced read-only session isolation.
4. **Credential Masking:** Verified that connection URLs, error messages, and engine representations do not expose plaintext passwords.
5. **Automated Testing:** Added 12 automated unit and integration tests in `backend/tests/test_postgres_connection_b412.py`. All 98 tests pass (86 SQLite baseline + 5 SQLite hardening + 7 live PostgreSQL integration).

---

## 2. Files Changed and Rationale

| File Path | Change Description | Non-Obvious Rationale / Design Decision |
| :--- | :--- | :--- |
| [backend/requirements.txt:25](file:///d:/Code/eduduty/backend/requirements.txt#L25) | Added `pg8000==1.31.5` in alphabetical order. | Standardizes the pure-Python PostgreSQL driver required on Windows environments where application control (WDAC/AppLocker) blocks C-extension binary DLLs (`_psycopg.pyd`). |
| [backend/database.py:29-35](file:///d:/Code/eduduty/backend/database.py#L29-L35) | Removed `({exc})` print from `_resolve_database_url` exception handler. | Prevents potential credential or socket details from being printed to stdout when fallback to SQLite triggers. |
| [backend/database.py:61-78](file:///d:/Code/eduduty/backend/database.py#L61-L78) | Removed brittle `postgres:postgres@` role string replacement in `_resolve_ai_reader_database_url`. | Prevents silent role substitution failures when using non-default passwords, and prevents referencing nonexistent `ai_reader` role before it is provisioned. Honors `AI_READER_DATABASE_URL` environment variable if present. |
| [backend/database.py:81-98](file:///d:/Code/eduduty/backend/database.py#L81-L98) | Added `execution_options={"postgresql_readonly": True}` and conditional libpq connect options. | Passes `options` only when NOT using pg8000. Leverages SQLAlchemy's built-in PostgreSQL connection characteristic (`SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`) to guarantee all transactions on `ai_reader_engine` are strictly read-only on PostgreSQL. |
| [backend/tests/test_postgres_connection_b412.py](file:///d:/Code/eduduty/backend/tests/test_postgres_connection_b412.py) | Created 12 focused automated tests. | Provides regression safety for SQLite fallback, credential masking, error handling, live PostgreSQL connectivity, and read-only enforcement. |

---

## 3. Driver & Connection Strategy

### 3.1 Driver Selection
- **Driver:** `pg8000` (v1.31.5)
- **Dialect URL:** `postgresql+pg8000://<user>:<password>@127.0.0.1:5433/<database>`
- **Justification:**
  - Pure Python implementation without external C-extensions or compiled DLLs.
  - Fully compatible with Windows Application Control (WDAC) environments where `_psycopg.pyd` fails to load.
  - Native dialect support in SQLAlchemy 2.0.

### 3.2 Read-Only Enforcement Mechanism
- **SQLite Engine:** Uses SQLAlchemy event listener `@event.listens_for(ai_reader_engine, "connect")` executing `PRAGMA query_only = ON;`.
- **PostgreSQL Engine:** Uses SQLAlchemy execution option:
  ```python
  ai_reader_execution_options = {"postgresql_readonly": True}
  ```
  On checkout of any connection from the pool, SQLAlchemy's `PGReadOnlyConnectionCharacteristic` executes:
  ```sql
  SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;
  COMMIT;
  ```
  This guarantees that all subsequent transactions in the session execute in `READ ONLY` mode. Any attempt to perform `INSERT`, `UPDATE`, `DELETE`, `CREATE TABLE`, `DROP TABLE`, or `ALTER TABLE` raises PostgreSQL error `25006: cannot execute ... in a read-only transaction`.

---

## 4. Verification Evidence

### 4.1 Normal Engine & AI Reader Engine Connections
Tested against PostgreSQL container `eduduty_pg_b4_test` (`127.0.0.1:5433`):

```python
with database.engine.connect() as conn:
    assert conn.execute(text("SELECT 1 AS num")).scalar() == 1

with database.ai_reader_engine.connect() as conn:
    assert conn.execute(text("SELECT 100")).scalar() == 100
    assert conn.execute(text("SHOW transaction_read_only")).scalar() == "on"
```
**Result:** Both engines connect successfully without errors.

### 4.2 AI Reader Read-Only Enforcement Evidence
The following operations were tested against `ai_reader_engine`:

1. **SELECT Query:**
   ```sql
   SELECT count(*) FROM classes;
   ```
   **Result:** Succeeded (`count = 0`).
2. **CREATE TABLE:**
   ```sql
   CREATE TABLE should_never_exist (id int);
   ```
   **Result:** Failed with `ProgrammingError: cannot execute CREATE TABLE in a read-only transaction`.
3. **INSERT:**
   ```sql
   INSERT INTO classes (name, branch, year) VALUES ('TEST', 'CSE', 1);
   ```
   **Result:** Failed with `ProgrammingError: cannot execute INSERT in a read-only transaction`.
4. **UPDATE:**
   ```sql
   UPDATE classes SET name = 'HACKED' WHERE id = 1;
   ```
   **Result:** Failed with `ProgrammingError: cannot execute UPDATE in a read-only transaction`.
5. **DELETE:**
   ```sql
   DELETE FROM classes WHERE id = 9999;
   ```
   **Result:** Failed with `ProgrammingError: cannot execute DELETE in a read-only transaction`.

### 4.3 Credential Masking Evidence
1. **Engine String Representation:**
   ```python
   eng = create_engine("postgresql+pg8000://myuser:SecretPass123@127.0.0.1:5433/eduduty_test_db")
   assert "SecretPass123" not in str(eng)
   assert "SecretPass123" not in repr(eng)
   assert "SecretPass123" not in str(eng.url)
   ```
   **Result:** PASSED (`***` displayed in place of password).
2. **Connection Error String:**
   Connecting with invalid credentials or host ports produces error strings devoid of the plaintext password:
   ```text
   (pg8000.exceptions.InterfaceError) Can't create a connection to host 127.0.0.1 and port 54998...
   (pg8000.dbapi.ProgrammingError) {'S': 'FATAL', 'M': 'password authentication failed for user "postgres"'}
   ```
   **Result:** PASSED (zero password leakage).

---

## 5. Test Suite Execution Results

### 5.1 Test Environment Distinction

| Test Environment | Test Target | Test Count | Result |
| :--- | :--- | :--- | :--- |
| **SQLite (In-Memory / Tempfile)** | Baseline application logic, RBAC, Auth, SQLite migrations, Fallback tests | 91 tests | **91 PASSED** |
| **PostgreSQL Integration** | Live container `eduduty_pg_b4_test` (`127.0.0.1:5433`) | 7 tests | **7 PASSED** |
| **Total Test Suite** | Combined pytest run | 98 tests | **98 PASSED, 0 FAILED** |

### 5.2 PostgreSQL Integration Test Breakdown (`tests/test_postgres_connection_b412.py`)
- `test_pg_normal_engine_connection`: **PASSED** (Connects and verifies basic query)
- `test_pg_ai_reader_select_succeeds`: **PASSED** (SELECT queries and `SHOW transaction_read_only` verify `on`)
- `test_pg_ai_reader_write_fails_create_table`: **PASSED** (`CREATE TABLE` blocked)
- `test_pg_ai_reader_write_fails_insert`: **PASSED** (`INSERT` blocked)
- `test_pg_ai_reader_write_fails_update`: **PASSED** (`UPDATE` blocked)
- `test_pg_ai_reader_write_fails_delete`: **PASSED** (`DELETE` blocked)
- `test_application_startup_and_get_db`: **PASSED** (FastAPI dependencies `get_db` and `get_ai_db` verify clean generation)

### 5.3 Pytest Output Summary
```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.1, pluggy-1.6.0
rootdir: D:\Code\eduduty\backend
collected 98 items

tests\test_ai_read_isolation.py ......                                   [  6%]
tests\test_alembic_b2_constraints.py ......                              [ 12%]
tests\test_alembic_b31_review.py ...                                     [ 15%]
tests\test_alembic_b32_gate.py ...                                       [ 18%]
tests\test_alembic_b33_auth.py ............................              [ 46%]
tests\test_alembic_b3_ai_views.py .....                                  [ 52%]
tests\test_alembic_migration.py ...                                      [ 55%]
tests\test_auth.py ..........                                            [ 65%]
tests\test_identity_spoofing.py .                                        [ 66%]
tests\test_postgres_connection_b412.py ............                      [ 78%]
tests\test_rbac.py ...                                                   [ 81%]
tests\test_resource_authorization.py ........                            [ 89%]
tests\test_upload_attendance.py ..........                               [100%]

====================== 98 passed, 15 warnings in 15.25s =======================
```

---

## 6. Remaining Issues & Security Considerations for Subsequent Stages

1. **Dedicated Database Role Provisioning (Stage B4.3):**  
   Currently, both `database.engine` and `database.ai_reader_engine` connect using the test container's `postgres` user credentials, with `ai_reader_engine` enforcing read-only behavior at the transaction session level (`postgresql_readonly=True`). In Stage B4.3, a dedicated non-superuser role (`ai_reader` or `authenticator`) must be provisioned with explicit `GRANT SELECT` privileges and `NOINHERIT` / `NOCREATEDB`.
2. **RLS Invoker Semantics (Stage B4.2):**  
   PostgreSQL views currently lack `WITH (security_invoker = true)`. Migration `006` must add `faculty_id` to `ai_duty_roster` and alter all 5 views to `security_invoker = true` so RLS policies on underlying tables take effect when queried through views.
3. **Automated CI Container Lifecycle:**  
   The new PostgreSQL tests cleanly detect the running test container on port 5433 or gracefully skip if unavailable. For CI pipelines, a Docker service container step must be added to boot PostgreSQL 15+ prior to running pytest.
