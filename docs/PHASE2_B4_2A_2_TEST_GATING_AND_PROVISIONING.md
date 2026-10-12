# EduDuty — Phase 2, Stage B4.2A.2: Credential Hygiene, PostgreSQL Test Gating, and Reproducible AI Reader Provisioning Report

**Date:** October 11, 2026  
**Status:** Stage B4.2A.2 Complete  
**Overall Verdict:** **PASS (All B4.2A.1 Audit Defects Remediated; Ready for B4.2B RLS)**  
**RLS Implementation Status:** **Architecture Gated for Stage B4.2B** (Prerequisites established: invoker-security views active, least-privilege role provisioned via tracked script, column vs RLS boundaries explicitly tested and validated)  
**Target Database:** PostgreSQL 16.15 (`eduduty_test_db`) in container `eduduty_pg_b4_test` bound to `127.0.0.1:5433`  
**Baseline Database:** SQLite `eduduty.db` (100% preserved and untouched)  

---

## 1. Executive Summary & Verification Matrix

Stage B4.2A.2 addresses the five critical blockers and defects identified during the independent B4.2A.1 audit:
1. **Hardcoded Credentials Removed (Task A):** Removed all fallback container password tokens from test files ([test_alembic_b42a_ai_reader.py](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py) and [test_postgres_connection_b412.py](file:///d:/Code/eduduty/backend/tests/test_postgres_connection_b412.py)). Test connections resolve strictly from environment variables without printing secrets or embedding them in reports or source code.
2. **Explicit PostgreSQL Test Gating (Task B):** Introduced `EDUDUTY_REQUIRE_POSTGRES_TESTS=1`. When active, missing configuration or unreachable PostgreSQL instances fail the test suite immediately (`pytest.fail`) rather than skipping. When unset/disabled, PostgreSQL tests skip cleanly (`pytest.skip`), preserving local SQLite workflows.
3. **Reproducible AI Reader Provisioning (Task C):** Created and validated [scripts/provision_ai_reader.sql](file:///d:/Code/eduduty/scripts/provision_ai_reader.sql). The script is tracked, idempotent, and configures the unprivileged `ai_reader` role with `NOSUPERUSER`, `NOBYPASSRLS`, `NOCREATEDB`, `NOCREATEROLE`, `NOINHERIT`, with zero table ownership. Reconciles privileges to grant only the required column-level permissions for PostgreSQL 15+ `security_invoker = true` views.
4. **Revalidated Test Independence & Boundaries (Task D):** Updated all prohibited DDL/DML/GRANT checks to execute in independent connections. Added explicit boundary tests documenting that column-level access to student records is currently permitted, establishing why table-level RLS in Stage B4.2B is strictly necessary.
5. **Full Suite Execution:** All 116 tests pass under PostgreSQL-required mode (101 SQLite/unit tests + 15 live PostgreSQL tests). Under SQLite-only mode, 101 tests pass and 15 PostgreSQL tests skip cleanly.

### Verification Matrix

| Checkpoint | Task | Specification | Result | Verdict |
| :--- | :---: | :--- | :--- | :---: |
| **Hardcoded Secret Removal** | A | Zero credentials in tests, reports, or source | Scanned repository; zero hardcoded passwords found | **PASS** |
| **Connection Configuration** | A | URLs resolved from environment only | Resolves via `DATABASE_URL`, `POSTGRES_TEST_DATABASE_URL`, or `PG_TEST_PASSWORD` | **PASS** |
| **Explicit Test Gating** | B | `EDUDUTY_REQUIRE_POSTGRES_TESTS=1` fails on missing PG | Exits with `pytest.fail` and code 1 when config missing | **PASS** |
| **SQLite Preservation** | B | SQLite workflow preserved when switch is unset | 101 tests pass, 15 PG tests cleanly skip without error | **PASS** |
| **Gating Unit Tests** | B | 7 automated unit tests for gating variants | [tests/test_postgres_gating.py](file:///d:/Code/eduduty/backend/tests/test_postgres_gating.py) all 7 pass | **PASS** |
| **Repeatable Provisioning** | C | Tracked, idempotent script [scripts/provision_ai_reader.sql](file:///d:/Code/eduduty/scripts/provision_ai_reader.sql) | Executed twice on live test database; reconciled cleanly | **PASS** |
| **Role Attributes** | C | `NOSUPERUSER`, `NOBYPASSRLS`, `NOCREATEROLE` | Verified in `pg_roles`: `rolsuper=f`, `rolbypassrls=f` | **PASS** |
| **Prohibited Operations** | D | Independent connections per statement | Verified: DDL, DML, role creation rejected with permission denied | **PASS** |
| **Column vs RLS Boundary** | D | Documented & tested expected pre-RLS state | `SELECT id, name, roll_number FROM students` tested and documented | **PASS** |
| **Downgrade Isolation** | D | Migration 006 downgrade wrapped in `try...finally` | Active test database guaranteed to remain at `head` | **PASS** |
| **Baseline Untouched** | - | SQLite databases & Docker containers intact | `backend/eduduty.db` mtime Oct 10; containers untouched | **PASS** |

---

## 2. Changed Files and Rationale

1. **[scripts/provision_ai_reader.sql](file:///d:/Code/eduduty/scripts/provision_ai_reader.sql) (NEW):**
   - *Rationale:* Resolves B4.2A.1 Blocker 1. Provides a tracked, repeatable, auditable administrative SQL script to provision or reconcile the `ai_reader` role on any clean PostgreSQL instance without hardcoding passwords.
2. **[backend/tests/pg_test_config.py](file:///d:/Code/eduduty/backend/tests/pg_test_config.py) (NEW):**
   - *Rationale:* Centralizes test database connection resolution, password masking, and explicit gating for `EDUDUTY_REQUIRE_POSTGRES_TESTS=1`. Eliminates code duplication and prevents hardcoded credential fallbacks.
3. **[backend/tests/test_postgres_gating.py](file:///d:/Code/eduduty/backend/tests/test_postgres_gating.py) (NEW):**
   - *Rationale:* Provides 7 automated unit tests validating that the gating mechanism fails when required, skips when disabled, rejects SQLite URLs, and redacts passwords.
4. **[backend/tests/test_alembic_b42a_ai_reader.py](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py) (UPDATED):**
   - *Rationale:* Removed hardcoded token fallback. Switched to `pg_test_config`. Updated prohibited-operation checks to execute in independent connection contexts. Wrapped migration 006 downgrade in `try...finally` to ensure head restoration. Added `test_ai_reader_granted_columns_accessible_until_rls`.
5. **[backend/tests/test_postgres_connection_b412.py](file:///d:/Code/eduduty/backend/tests/test_postgres_connection_b412.py) (UPDATED):**
   - *Rationale:* Removed hardcoded token fallback. Switched to `get_pg_admin_url()` fixture from `pg_test_config`.

---

## 3. Environment Variable Specification

Configuration values must be supplied via environment variables. Secret values are never committed or printed.

| Environment Variable | Required For | Allowed Values / Format | Description |
| :--- | :--- | :--- | :--- |
| `EDUDUTY_REQUIRE_POSTGRES_TESTS` | PostgreSQL integration gating | `1`, `true`, `yes` (or unset / `0`) | When enabled, missing PostgreSQL configuration or connection failures cause tests to **fail** immediately. |
| `DATABASE_URL` | Application & tests | `postgresql+pg8000://<user>:<password>@<host>:<port>/<dbname>` | Primary database connection string. |
| `POSTGRES_TEST_DATABASE_URL` | Integration tests | `postgresql+pg8000://<user>:<password>@<host>:<port>/<dbname>` | Dedicated test database connection string. Takes priority over `DATABASE_URL` for integration tests. |
| `PG_TEST_PASSWORD` | Integration tests | Plaintext password | Optional alternative to providing full connection string. Used with `PG_TEST_USER`, `PG_TEST_HOST`, `PG_TEST_PORT`, `PG_TEST_DB`. |
| `AI_READER_DATABASE_URL` | AI read queries | `postgresql+pg8000://ai_reader:<password>@<host>:<port>/<dbname>` | Mandatory in production PostgreSQL environments. Evaluated by `_resolve_ai_reader_database_url()`. |

---

## 4. Execution Commands

### 4.1 SQLite-Only Local Test Suite (No PostgreSQL Container Needed)
Runs all 101 core unit and integration tests. PostgreSQL tests are cleanly skipped.
```powershell
# Run from backend directory
cd D:\Code\eduduty\backend
Remove-Item Env:\EDUDUTY_REQUIRE_POSTGRES_TESTS -ErrorAction SilentlyContinue
python -m pytest tests/
```
*Output Summary:* `101 passed, 15 skipped`

### 4.2 Required PostgreSQL Integration Test Suite
Enforces live PostgreSQL validation against `127.0.0.1:5433`. If the container or configuration is unavailable, the suite fails immediately.
```powershell
# Run from backend directory
cd D:\Code\eduduty\backend
$env:EDUDUTY_REQUIRE_POSTGRES_TESTS = '1'
$env:PG_TEST_PASSWORD = (docker exec eduduty_pg_b4_test printenv POSTGRES_PASSWORD)
python -m pytest tests/
```
*Output Summary:* `116 passed, 0 skipped, 0 failed`

### 4.3 Clean Database Role Provisioning Procedure
Administrative command to run [scripts/provision_ai_reader.sql](file:///d:/Code/eduduty/scripts/provision_ai_reader.sql) against a fresh PostgreSQL deployment:
```powershell
# Execute provisioning script as administrator
Get-Content scripts/provision_ai_reader.sql -Raw | docker exec -i eduduty_pg_b4_test psql -U postgres -d eduduty_test_db

# Securely set or rotate password without committing secrets
docker exec -i eduduty_pg_b4_test psql -U postgres -d eduduty_test_db -c "ALTER ROLE ai_reader WITH LOGIN PASSWORD '<STRONG_SECRET_TOKEN>';"
```

---

## 5. Catalog Evidence of Role & Privileges

Inspected PostgreSQL catalog after executing [scripts/provision_ai_reader.sql](file:///d:/Code/eduduty/scripts/provision_ai_reader.sql):

### 5.1 Role Attributes (`pg_roles`)
```text
  rolname  | rolsuper | rolinherit | rolcreaterole | rolcreatedb | rolcanlogin | rolreplication | rolbypassrls 
-----------+----------+------------+---------------+-------------+-------------+----------------+--------------
 ai_reader | f        | f          | f             | f           | t           | f              | f
```

### 5.2 Table-Level Privileges (`information_schema.table_privileges`)
```text
table_name             | privilege_type 
-----------------------+----------------
ai_attendance_summary  | SELECT
ai_duty_roster         | SELECT
ai_eligibility_summary | SELECT
ai_vt_candidates       | SELECT
v_vt_follow_up_status  | SELECT
```
*Base Tables:* Exactly **zero** table-level privileges granted. Direct `SELECT *` fails on all base tables.

### 5.3 Column-Level Privileges (`information_schema.column_privileges`)
| Base Table | Columns Granted to `ai_reader` | Justification (`security_invoker = true` views) |
| :--- | :--- | :--- |
| `classes` | `id`, `name` | Referenced by `ai_eligibility_summary`, `ai_attendance_summary`, `ai_vt_candidates`, `v_vt_follow_up_status` |
| `faculty` | `id`, `name` | Referenced by `ai_duty_roster` |
| `follow_up_statuses` | `calculated_status`, `final_status`, `mst_1_appeared`, `mst_1_exam_id`, `mst_2_appeared`, `mst_2_exam_id`, `override`, `override_reason`, `rule_version`, `student_id`, `updated_at` | Referenced by `ai_vt_candidates`, `v_vt_follow_up_status` |
| `invigilation_duties`| `faculty_id`, `mst_exam_id`, `room_id`, `status` | Referenced by `ai_duty_roster` |
| `mst_eligibility` | `id`, `lowest_subject_pct`, `mst_exam_id`, `overall_pct`, `status`, `student_id` | Referenced by `ai_eligibility_summary`, `ai_attendance_summary` |
| `mst_exams` | `exam_date`, `id`, `label` | Referenced by `ai_eligibility_summary`, `ai_attendance_summary`, `ai_duty_roster`, `v_vt_follow_up_status` |
| `rooms` | `id`, `room_number` | Referenced by `ai_duty_roster` |
| `students` | `class_id`, `id`, `name`, `roll_number` | Referenced by `ai_eligibility_summary`, `ai_attendance_summary`, `ai_vt_candidates`, `v_vt_follow_up_status` |

---

## 6. Verification of Prohibited Operations Under Independent Transactions

Tested with distinct database connections per operation:

| Prohibited Operation | Statement | Isolation Mode | Result |
| :--- | :--- | :--- | :--- |
| **CREATE TABLE** | `CREATE TABLE hack_tab (id int);` | Independent connection | **FAILED** (`permission denied for schema public`) |
| **INSERT** | `INSERT INTO classes (name, branch, year) VALUES ('HACK', 'CSE', 1);` | Independent connection | **FAILED** (`permission denied for table classes`) |
| **UPDATE** | `UPDATE classes SET name = 'HACKED';` | Independent connection | **FAILED** (`permission denied for table classes`) |
| **DELETE** | `DELETE FROM classes WHERE id = 1;` | Independent connection | **FAILED** (`permission denied for table classes`) |
| **ALTER TABLE** | `ALTER TABLE classes ADD COLUMN hack_col int;` | Independent connection | **FAILED** (`must be owner of table classes`) |
| **DROP TABLE** | `DROP TABLE classes;` | Independent connection | **FAILED** (`must be owner of table classes`) |
| **CREATE ROLE** | `CREATE ROLE attacker;` | Independent connection | **FAILED** (`permission denied to create role`) |
| **ALTER ROLE** | `ALTER ROLE postgres WITH SUPERUSER;` | Independent connection | **FAILED** (`must have admin option on role "postgres"`) |

---

## 7. Evidence of Explicit Failure Mode When PostgreSQL is Missing

When `EDUDUTY_REQUIRE_POSTGRES_TESTS=1` is active and database configuration is missing:
```text
FAILED tests/test_alembic_b42a_ai_reader.py::test_migration_006_upgrade_and_downgrade
...
Failed: BLOCKED: EDUDUTY_REQUIRE_POSTGRES_TESTS=1 is set, but PostgreSQL test configuration is missing. To enable PostgreSQL integration tests, set DATABASE_URL, POSTGRES_TEST_DATABASE_URL, or PG_TEST_PASSWORD.
=========================== 8 errors, 3 passed in 0.41s ===========================
```
Verified that the test suite exits with return code `1` and refuses to fall back to SQLite.

---

## 8. Readiness Checklist for Stage B4.2B (Row-Level Security)

With Stage B4.2A.2 completed, all architectural prerequisites for Row-Level Security are satisfied:

- [x] Views define `WITH (security_invoker = true)` semantics (Migration 006).
- [x] Dedicated unprivileged role `ai_reader` provisioned with `NOBYPASSRLS`.
- [x] Zero hardcoded passwords in test files, source code, or reports.
- [x] Explicit gating switch `EDUDUTY_REQUIRE_POSTGRES_TESTS=1` enforced.
- [x] Repeatable provisioning script [scripts/provision_ai_reader.sql](file:///d:/Code/eduduty/scripts/provision_ai_reader.sql) tracked in repository.
- [x] Baseline SQLite `eduduty.db` and SecureMailScope Docker containers 100% preserved.

### Immediate Focus for Stage B4.2B:
1. **Migration 007 (`007_implement_faculty_rls.py`):**
   - Enable RLS on `students`, `mst_eligibility`, `follow_up_statuses`, and `invigilation_duties`.
   - Create faculty class-scope policy using `FacultyTimetable` assignments.
   - Enforce policy on `ai_reader` (`FORCE ROW LEVEL SECURITY` or standard policy since `ai_reader` has `NOBYPASSRLS`).
2. **Session Context Injection:**
   - Implement `SET LOCAL app.current_faculty_id = :faculty_id;` inside `backend/ai_service.py` to populate PostgreSQL runtime context during structured reporting query execution.
