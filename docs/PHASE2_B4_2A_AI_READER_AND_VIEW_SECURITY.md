# EduDuty — Stage B4.2A: Dedicated AI Reader Role and Secure View Migration Report

**Date:** October 11, 2026  
**Status:** Stage B4.2A Complete  
**Executive Verdict:** **PASS (Migration 006 Deployed & AI Reader Role Hardened)**  
**RLS Implementation Status:** **Architecture Gated for Stage B4.2B** (Prerequisites established: views set to `security_invoker = true`, `ai_reader` role configured with `NOBYPASSRLS`, faculty RLS policy implementation deferred to Stage B4.2B)  
**Target Test Database:** PostgreSQL 16.15 (`eduduty_test_db`) in container `eduduty_pg_b4_test` bound to `127.0.0.1:5433`  
**Preserved Baseline:** `eduduty.db` (SQLite development database 100% untouched)  

---

## 1. Executive Summary & Verification Matrix

Stage B4.2A implements the database-level security layer required before introducing Row-Level Security (RLS) policies:
1. **Migration 006 (`006_secure_ai_views.py`):** Successfully applied after revision `005_ai_views_integrity`. All 5 approved AI reporting views now possess `WITH (security_invoker = true)` semantics on PostgreSQL. Added `f.id AS faculty_id` to `ai_duty_roster`. Verified safe downgrade and upgrade cycle.
2. **Dedicated Unprivileged Role (`ai_reader`):** Provisioned with `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOBYPASSRLS`, `NOINHERIT`. It has zero table ownership and zero write/DDL privileges. Direct table-level `SELECT *` access on base tables (`students`, `users`, `audit_logs`) is denied.
3. **Connection Configuration & Fail-Closed Behavior:** In `backend/database.py`, `_resolve_ai_reader_database_url()` requires a dedicated `AI_READER_DATABASE_URL` in production PostgreSQL environments, failing closed with a `RuntimeError` if missing. SQLite development fallback remains functional.
4. **Automated Testing:** 10 new automated integration and unit tests added in `backend/tests/test_alembic_b42a_ai_reader.py`. All 108 tests pass across the entire suite (94 SQLite tests + 14 live PostgreSQL tests).

| Validation Checkpoint | Specification | Verified Finding | Status |
| :--- | :--- | :--- | :--- |
| **Migration 006 Application** | Alembic upgrade to `006_secure_ai_views` | Applied cleanly; `alembic_version` = `006_secure_ai_views` | **PASS** |
| **View Invoker Semantics** | `WITH (security_invoker = true)` on all 5 views | Confirmed `{security_invoker=true}` in `pg_class.reloptions` | **PASS** |
| **Faculty ID Exposure** | `ai_duty_roster` exposes `faculty_id` | Column exists with type `integer` at ordinal position 5 | **PASS** |
| **Migration Downgrade** | Reversible to revision 005 without CASCADE | Downgraded cleanly to `005_ai_views_integrity` and re-upgraded | **PASS** |
| **AI-Reader Role Privileges** | `NOSUPERUSER`, `NOBYPASSRLS`, `NOCREATEROLE` | Audited in `pg_roles`: `rolsuper=f`, `rolbypassrls=f` | **PASS** |
| **Prohibited Writes & DDL** | DDL, DML, and privilege escalation blocked | `CREATE`, `INSERT`, `UPDATE`, `DELETE`, `ALTER`, `DROP`, `CREATE ROLE` fail | **PASS** |
| **Direct Student Table Access** | No table-level access to base tables | `SELECT * FROM students` fails with `permission denied` | **PASS** |
| **Approved View Reads** | Approved views queryable by `ai_reader` | All 5 views execute cleanly returning valid rows | **PASS** |
| **Fail-Closed Configuration** | Production PostgreSQL fails closed if URL missing | Raises `RuntimeError` on missing `AI_READER_DATABASE_URL` | **PASS** |
| **Regression Preservation** | `eduduty.db` and synthetic containers untouched | 100% preserved; all 108 pytest tests pass | **PASS** |

---

## 2. Migration 006: Secure AI Views & Faculty ID Projection

### 2.1 Migration Script Design (`backend/alembic/versions/006_secure_ai_views.py`)
- **Revision ID:** `006_secure_ai_views`
- **Revises:** `005_ai_views_integrity`
- **Dialect Handling:** Dynamically evaluates `bind.dialect.name == "postgresql"`. Applies `WITH (security_invoker = true)` on PostgreSQL while falling back to standard `CREATE VIEW` on SQLite to maintain test portability.
- **View Grant Persistence:** If role `ai_reader` exists, the migration automatically restores `GRANT SELECT` on all 5 views during both upgrade and downgrade.

### 2.2 View Schemas & Security Invoker Options
Inspected PostgreSQL catalog `pg_class` for all 5 views following migration:

```sql
SELECT relname, reloptions
FROM pg_class
WHERE relname IN ('ai_eligibility_summary', 'ai_attendance_summary', 'ai_vt_candidates', 'ai_duty_roster', 'v_vt_follow_up_status')
ORDER BY relname;
```

**Evidence / Output:**
```text
        relname         |       reloptions        
------------------------+-------------------------
 ai_attendance_summary  | {security_invoker=true}
 ai_duty_roster         | {security_invoker=true}
 ai_eligibility_summary | {security_invoker=true}
 ai_vt_candidates       | {security_invoker=true}
 v_vt_follow_up_status  | {security_invoker=true}
(5 rows)
```

### 2.3 `ai_duty_roster` Column Definition
Inspected column metadata from `information_schema.columns`:

```sql
SELECT column_name, data_type, ordinal_position
FROM information_schema.columns
WHERE table_name = 'ai_duty_roster'
ORDER BY ordinal_position;
```

**Evidence / Output:**
```text
 column_name  |     data_type     | ordinal_position 
--------------+-------------------+------------------
 mst_label    | character varying |                1
 exam_date    | date              |                2
 room_number  | character varying |                3
 faculty_name | character varying |                4
 faculty_id   | integer           |                5
 duty_status  | character varying |                6
(6 rows)
```

### 2.4 Downgrade & Re-Upgrade Evidence
Tested downgrade to `005_ai_views_integrity` and re-upgrade to `head`:

```powershell
# Downgrade
$env:DATABASE_URL="postgresql+pg8000://postgres:<REDACTED>@127.0.0.1:5433/eduduty_test_db"
python -m alembic downgrade 005_ai_views_integrity
```
```text
database: using DATABASE_URL from environment
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade 006_secure_ai_views -> 005_ai_views_integrity, Secure AI reporting views with PostgreSQL security_invoker semantics and faculty_id projection
```
*Verification:* Querying `alembic_version` confirmed revision `005_ai_views_integrity`. `pg_class.reloptions` confirmed `security_invoker` was absent, and `faculty_id` was absent from `ai_duty_roster`.

```powershell
# Re-upgrade to head
python -m alembic upgrade head
```
```text
database: using DATABASE_URL from environment
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 005_ai_views_integrity -> 006_secure_ai_views, Secure AI reporting views with PostgreSQL security_invoker semantics and faculty_id projection
```
*Verification:* Querying `alembic_version` confirmed revision `006_secure_ai_views` was restored cleanly.

---

## 3. Dedicated AI-Reader Role Specification & Privileges

### 3.1 Role Definition & Setup Procedure
The dedicated AI reader role was provisioned using least-privilege principles:

```sql
-- 1. Create role with strict negative attributes
CREATE ROLE ai_reader WITH LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOBYPASSRLS
    NOINHERIT
    PASSWORD '<SECRET_LOCAL_TOKEN>';

-- 2. Grant minimum connection and namespace traversal
GRANT CONNECT ON DATABASE eduduty_test_db TO ai_reader;
GRANT USAGE ON SCHEMA public TO ai_reader;

-- 3. Revoke creation privileges on public schema
REVOKE CREATE ON SCHEMA public FROM ai_reader;
REVOKE ALL PRIVILEGES ON DATABASE eduduty_test_db FROM ai_reader;
GRANT CONNECT ON DATABASE eduduty_test_db TO ai_reader;

-- 4. Grant SELECT exclusively on approved views
GRANT SELECT ON ai_duty_roster, ai_attendance_summary, ai_eligibility_summary, ai_vt_candidates, v_vt_follow_up_status TO ai_reader;

-- 5. Grant column-level SELECT on underlying view columns
GRANT SELECT (id, name) ON classes TO ai_reader;
GRANT SELECT (id, label, exam_date) ON mst_exams TO ai_reader;
GRANT SELECT (id, class_id, roll_number, name) ON students TO ai_reader;
GRANT SELECT (id, student_id, mst_exam_id, overall_pct, lowest_subject_pct, status) ON mst_eligibility TO ai_reader;
GRANT SELECT (student_id, mst_1_appeared, mst_2_appeared, mst_1_exam_id, mst_2_exam_id, calculated_status, final_status, override, override_reason, rule_version, updated_at) ON follow_up_statuses TO ai_reader;
GRANT SELECT (mst_exam_id, room_id, faculty_id, status) ON invigilation_duties TO ai_reader;
GRANT SELECT (id, room_number) ON rooms TO ai_reader;
GRANT SELECT (id, name) ON faculty TO ai_reader;
```

### 3.2 Role Privilege Inspection (`pg_roles`)
```sql
SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin, rolreplication, rolbypassrls
FROM pg_roles WHERE rolname = 'ai_reader';
```
**Evidence / Output:**
```text
  rolname  | rolsuper | rolinherit | rolcreaterole | rolcreatedb | rolcanlogin | rolreplication | rolbypassrls 
-----------+----------+------------+---------------+-------------+-------------+----------------+--------------
 ai_reader | f        | f          | f             | f           | t           | f              | f
(1 row)
```

### 3.3 Reconciliation of `security_invoker` with Direct Table Access
- **PostgreSQL 15+ Security Invoker Behavior:**  
  When `security_invoker = true` is set on a view, PostgreSQL checks permissions on underlying relations as the *invoking user* (`ai_reader`). If the invoking user lacks read permissions on the underlying columns, PostgreSQL aborts the query with `ERROR: permission denied for table <name>`.
- **Least-Privilege Column Grant Strategy:**  
  To satisfy both requirements (approved views must work, while direct table access is denied):
  1. No table-level `SELECT` was granted to `ai_reader` on any base table (`students`, `users`, `audit_logs`, `classes`, etc.).
  2. Only column-level `SELECT` was granted for the exact columns referenced in the view definitions.
  3. Direct queries (`SELECT * FROM students`) fail immediately because ungranted columns cannot be read.
  4. Non-reporting tables (`users`, `audit_logs`, `system_rules`) have zero permissions granted and remain 100% inaccessible.

### 3.4 Verification of Prohibited Actions
Tested under `ai_reader` connection:

| Attempted Action | SQL Command | Result |
| :--- | :--- | :--- |
| **CREATE TABLE** | `CREATE TABLE hack_tab (id int);` | **FAILED** (`ERROR: permission denied for schema public`) |
| **INSERT** | `INSERT INTO classes (name, branch, year) VALUES ('HACK', 'CSE', 1);` | **FAILED** (`ERROR: permission denied for table classes`) |
| **UPDATE** | `UPDATE classes SET name = 'HACKED';` | **FAILED** (`ERROR: permission denied for table classes`) |
| **DELETE** | `DELETE FROM classes WHERE id = 1;` | **FAILED** (`ERROR: permission denied for table classes`) |
| **ALTER TABLE** | `ALTER TABLE classes ADD COLUMN hack_col int;` | **FAILED** (`ERROR: must be owner of table classes`) |
| **DROP TABLE** | `DROP TABLE classes;` | **FAILED** (`ERROR: must be owner of table classes`) |
| **CREATE ROLE** | `CREATE ROLE attacker;` | **FAILED** (`ERROR: permission denied to create role`) |
| **ALTER ROLE** | `ALTER ROLE postgres WITH SUPERUSER;` | **FAILED** (`ERROR: must have admin option on role "postgres"`) |
| **DIRECT SELECT** | `SELECT * FROM students;` | **FAILED** (`ERROR: permission denied for table students`) |
| **DIRECT SELECT** | `SELECT * FROM users;` | **FAILED** (`ERROR: permission denied for table users`) |
| **DIRECT SELECT** | `SELECT * FROM audit_logs;` | **FAILED** (`ERROR: permission denied for table audit_logs`) |

---

## 4. Connection Configuration & Fail-Closed Behavior

### 4.1 Updated Resolution Logic ([backend/database.py:61-82](file:///d:/Code/eduduty/backend/database.py#L61-L82))
```python
def _resolve_ai_reader_database_url() -> str:
    """
    Pick a dedicated read-only database URL for AI read query execution.

    1. AI_READER_DATABASE_URL or AI_DATABASE_URL env var wins if set.
    2. In production PostgreSQL environments, a dedicated AI_READER_DATABASE_URL is mandatory.
       Fails closed with a RuntimeError if missing to prevent superuser privilege leakage.
    3. In local dev/test or SQLite environments, falls back with session-level read-only enforcement.
    """
    env_url = os.getenv("AI_READER_DATABASE_URL") or os.getenv("AI_DATABASE_URL")
    if env_url:
        print("database: using AI_READER_DATABASE_URL from environment", flush=True)
        return env_url

    # Check if primary database is PostgreSQL
    if SQLALCHEMY_DATABASE_URL.startswith("postgresql"):
        app_env = os.getenv("APP_ENV", "production").strip().lower()
        if app_env not in ("development", "dev", "test", "testing"):
            raise RuntimeError(
                "CONFIGURATION ERROR: Dedicated AI_READER_DATABASE_URL is mandatory for "
                "PostgreSQL operation in production. Falling back to primary application "
                "credentials is strictly forbidden."
            )
        print("database: warning: using primary database URL for AI reader in development/test", flush=True)

    return SQLALCHEMY_DATABASE_URL
```

### 4.2 Fail-Closed Evidence
When `DATABASE_URL` points to PostgreSQL and `APP_ENV = "production"` without `AI_READER_DATABASE_URL`:
```text
RuntimeError: CONFIGURATION ERROR: Dedicated AI_READER_DATABASE_URL is mandatory for PostgreSQL operation in production. Falling back to primary application credentials is strictly forbidden.
```
Verified that the application fails closed prior to connection establishment or query routing.

---

## 5. Test Suite Execution & Database Breakdown

### 5.1 Test Count Segregation

| Environment | Test Target | Test Files | Count | Result |
| :--- | :--- | :--- | :--- | :--- |
| **SQLite (In-Memory / Tempfile)** | Baseline RBAC, Auth, SQLite migrations, attendance import | `test_auth.py`, `test_rbac.py`, `test_alembic_b33_auth.py`, etc. | **94** | **94 PASSED** |
| **Live PostgreSQL Integration** | Container `eduduty_pg_b4_test` (`127.0.0.1:5433`) | `test_postgres_connection_b412.py`, `test_alembic_b42a_ai_reader.py` | **14** | **14 PASSED** |
| **Total Test Suite** | Full regression run (`python -m pytest`) | 14 test modules | **108** | **108 PASSED, 0 FAILED** |

### 5.2 Live PostgreSQL Tests Breakdown
1. `test_migration_006_upgrade_and_downgrade`: **PASSED** (Verifies Alembic 005 -> 006 upgrade, downgrade, and re-upgrade)
2. `test_all_five_views_have_security_invoker`: **PASSED** (Verifies `{security_invoker=true}` on all 5 views)
3. `test_ai_duty_roster_exposes_faculty_id`: **PASSED** (Verifies integer `faculty_id` column projection)
4. `test_ai_reader_role_is_not_superuser_and_no_bypassrls`: **PASSED** (Verifies `rolsuper=f`, `rolbypassrls=f`)
5. `test_ai_reader_cannot_write_ddl_or_grant`: **PASSED** (Verifies DDL, write, and role creation denial)
6. `test_ai_reader_approved_view_reads_succeed`: **PASSED** (Verifies all 5 views read cleanly under `ai_reader`)
7. `test_ai_reader_direct_student_table_access_denied`: **PASSED** (Verifies `SELECT * FROM students` fails with permission denied)
8. `test_missing_production_ai_reader_url_fails_closed`: **PASSED** (Verifies fail-closed behavior)
9. `test_sqlite_fallback_and_existing_tests_continue_to_work`: **PASSED** (Verifies SQLite fallback intact)
10. `test_no_password_leaks_in_ai_reader_engine`: **PASSED** (Verifies password masking across string representations)
11. `test_pg_normal_engine_connection`: **PASSED** (Verifies primary engine connectivity)
12. `test_pg_ai_reader_select_succeeds`: **PASSED** (Verifies session parameter `transaction_read_only=on`)
13. `test_pg_ai_reader_write_fails_create_table`: **PASSED** (Verifies session-level write rejection)
14. `test_application_startup_and_get_db`: **PASSED** (Verifies FastAPI dependency injection under PostgreSQL)

---

## 6. Remaining Blockers & Next Steps for Stage B4.2B

With Stage B4.2A complete, the security prerequisites for Row-Level Security are in place:
1. Views operate as `security_invoker = true`, ensuring queries check invoking user policies.
2. The AI reader connects as unprivileged user `ai_reader` (`rolbypassrls = false`), ensuring RLS policies cannot be bypassed.
3. `ai_duty_roster` exposes `faculty_id`, providing the column needed for faculty-scoped duty filtering.

### Remaining Prerequisites for Stage B4.2B:
- **Session Variable / JWT Context Injection:** RLS policies need to identify the authenticated caller (e.g., via `SET LOCAL app.current_faculty_id = :fac_id` or JWT claims).
- **Table-Level RLS Activation & Policy Definitions:**
  - `ALTER TABLE students ENABLE ROW LEVEL SECURITY;`
  - `ALTER TABLE mst_eligibility ENABLE ROW LEVEL SECURITY;`
  - `ALTER TABLE invigilation_duties ENABLE ROW LEVEL SECURITY;`
  - Define faculty-scoped policies that restrict rows to assigned classes and faculty invigilation duties.
