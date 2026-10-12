# EduDuty — Stage B4.1.1: Independent Evidence Audit (Read-Only)

**Date:** October 11, 2026  
**Status:** Audit Completed  
**Scope:** Independent verification of completed PostgreSQL migration validation ([docs/PHASE2_B4_1_POSTGRES_MIGRATION_VALIDATION.md](file:///d:/Code/eduduty/docs/PHASE2_B4_1_POSTGRES_MIGRATION_VALIDATION.md)) against live repository files, test suites, and Docker test database catalogs.  
**Mode:** Strictly read-only audit. No source code, migrations, database objects, Docker containers, or configurations were modified. Migration 006 was not created.

---

## 1. Executive Summary & Verdict Matrix

| # | Audit Item | Status | Key Finding |
| :--- | :--- | :--- | :--- |
| **1** | **`pg8000` Dependency & Engine Compatibility** | **NOT VERIFIED / BLOCKED** | `pg8000` is **missing** from `backend/requirements.txt`. While primary `database.engine` connects via `postgresql+pg8000://`, `database.ai_reader_engine` crashes with `TypeError: connect() got an unexpected keyword argument 'options'`. SQLite fallback remains intact. |
| **2** | **Five AI Views SQL & Base-Table Dependencies** | **VERIFIED** | Exact SQL extracted from `pg_views`. Exact table dependencies verified from PostgreSQL system catalog `pg_depend`. |
| **3** | **Startup Hook `_ensure_ai_views()` View Mutability** | **VERIFIED** | Code analysis of `backend/main.py:110-144` confirms hook cannot replace or modify existing views. Returns in State 1 (0 DDL statements) when all 5 views exist. |
| **4** | **Migrations 001–005 Immutability & DB Revision** | **VERIFIED** | Only 5 migration files exist in `backend/alembic/versions/`. Live test database `alembic_version` query returns `005_ai_views_integrity`. Migration 006 does not exist. |
| **5** | **Test DB Isolation & Non-Production Credentials** | **VERIFIED** | Bound strictly to `127.0.0.1:5433:5432`, database `eduduty_test_db`, volume `eduduty_b4_test_volume`. Uses local random 32-character hex token; no production credentials used or leaked. |
| **6** | **86-Test Test Suite Environment Distinction** | **VERIFIED** | All 86 tests in `backend/tests` execute **strictly against SQLite** (`sqlite:///:memory:` or temporary SQLite files). Zero PostgreSQL integration tests are executed in `pytest`. |
| **7** | **Inconsistencies & Pre-RLS Blockers** | **VERIFIED** | Identified 7 explicit blockers: driver dependency omission, `ai_reader_engine` option failure, role replacement bug, missing automated PG integration tests, lack of `security_invoker = true`, missing `faculty_id` in `ai_duty_roster`, and startup hook DDL divergence. |

---

## 2. Item 1: `pg8000` Dependency & Engine URL Support

### Status: **NOT VERIFIED / BLOCKED**

### 2.1 Dependency Declaration Audit
- Inspected [backend/requirements.txt](file:///d:/Code/eduduty/backend/requirements.txt):
  - Line 27 declares `psycopg2-binary==2.9.13`.
  - `pg8000` is **NOT declared** anywhere in `requirements.txt`.
  - While `pg8000==1.31.5` was installed in the local virtual environment to bypass Windows WDAC/AppLocker blocking of `_psycopg.pyd` DLL, the project dependency specification does not include it. Any clean container build or CI pipeline will lack `pg8000`.

### 2.2 Application Database Engine Support
- **Primary Engine (`database.engine`):**  
  [backend/database.py:7-45](file:///d:/Code/eduduty/backend/database.py#L7-L45) supports `DATABASE_URL` overrides. When passed `postgresql+pg8000://postgres:<REDACTED>@127.0.0.1:5433/eduduty_test_db`, `database.engine.connect()` succeeds cleanly:
  ```text
  database: using DATABASE_URL from environment
  database.engine connect test:
  Connected successfully: <sqlalchemy.engine.base.Connection object>
  ```
- **AI Reader Engine (`database.ai_reader_engine`):** **FAILS / CRASHES**  
  In [backend/database.py:86-89](file:///d:/Code/eduduty/backend/database.py#L86-L89):
  ```python
  elif AI_READER_DATABASE_URL.startswith("postgresql"):
      # Force PostgreSQL session parameter default_transaction_read_only = on
      ai_reader_connect_args = {"options": "-c default_transaction_read_only=on"}
  ```
  Attempting connection on `database.ai_reader_engine` with `postgresql+pg8000` raises:
  ```text
  TypeError: connect() got an unexpected keyword argument 'options'
  ```
  *Root Cause:* Unlike libpq drivers (`psycopg2`), pure-Python `pg8000` does not accept libpq command-line flags in `options`.
- **SQLite Fallback:**  
  When `DATABASE_URL` is unset, `database.py:35` safely falls back to `sqlite:///./eduduty.db` without regression.

---

## 3. Item 2: Exact SQL Definitions & Base-Table Dependencies of the Five Views

### Status: **VERIFIED**

### 3.1 Live Catalog Dependency Verification (`pg_depend`)
Queried directly from PostgreSQL system catalog (`pg_depend` joining `pg_rewrite`, `pg_class`, and `pg_namespace`):

```sql
SELECT v.relname AS view_name, t.relname AS dependency_table
FROM pg_depend d
JOIN pg_rewrite r ON r.oid = d.objid
JOIN pg_class v ON v.oid = r.ev_class
JOIN pg_class t ON t.oid = d.refobjid
JOIN pg_namespace n ON n.oid = v.relnamespace
WHERE n.nspname = 'public' AND v.relkind = 'v' AND t.relkind = 'r'
  AND v.relname IN ('ai_eligibility_summary', 'ai_attendance_summary', 'ai_vt_candidates', 'ai_duty_roster', 'v_vt_follow_up_status')
GROUP BY v.relname, t.relname
ORDER BY v.relname, t.relname;
```

**Catalog Evidence Output:**
```text
       view_name        |  dependency_table   
------------------------+---------------------
 ai_attendance_summary  | classes
 ai_attendance_summary  | mst_eligibility
 ai_attendance_summary  | mst_exams
 ai_attendance_summary  | students
 ai_duty_roster         | faculty
 ai_duty_roster         | invigilation_duties
 ai_duty_roster         | mst_exams
 ai_duty_roster         | rooms
 ai_eligibility_summary | classes
 ai_eligibility_summary | mst_eligibility
 ai_eligibility_summary | mst_exams
 ai_eligibility_summary | students
 ai_vt_candidates       | classes
 ai_vt_candidates       | follow_up_statuses
 ai_vt_candidates       | students
 v_vt_follow_up_status  | classes
 v_vt_follow_up_status  | follow_up_statuses
 v_vt_follow_up_status  | mst_exams
 v_vt_follow_up_status  | students
(19 rows)
```

### 3.2 Exact SQL Definitions from `pg_views`

#### 1. `ai_eligibility_summary`
- **Base Tables:** `mst_eligibility`, `mst_exams`, `students`, `classes`
- **Definition:**
  ```sql
  SELECT c.name AS class_name,
         me.label AS mst_label,
         count(CASE WHEN (lower((el.status)::text) = 'eligible'::text) THEN 1 ELSE NULL::integer END) AS eligible_count,
         count(CASE WHEN (lower((el.status)::text) = ANY (ARRAY['borderline'::text, 'conditionally_eligible'::text])) THEN 1 ELSE NULL::integer END) AS borderline_count,
         count(CASE WHEN (lower((el.status)::text) = ANY (ARRAY['not eligible'::text, 'ineligible'::text])) THEN 1 ELSE NULL::integer END) AS ineligible_count,
         count(CASE WHEN (lower((el.status)::text) = 'missing'::text) THEN 1 ELSE NULL::integer END) AS missing_count
  FROM (((mst_eligibility el
    JOIN mst_exams me ON ((me.id = el.mst_exam_id)))
    JOIN students s ON ((s.id = el.student_id)))
    JOIN classes c ON ((c.id = s.class_id)))
  GROUP BY c.name, me.label;
  ```

#### 2. `ai_attendance_summary`
- **Base Tables:** `students`, `classes`, `mst_eligibility`, `mst_exams`
- **Definition:**
  ```sql
  SELECT c.name AS class_name,
         me.label AS mst_label,
         s.roll_number,
         s.name AS student_name,
         el.overall_pct,
         el.lowest_subject_pct
  FROM (((students s
    JOIN classes c ON ((c.id = s.class_id)))
    JOIN mst_eligibility el ON ((el.student_id = s.id)))
    JOIN mst_exams me ON ((me.id = el.mst_exam_id)));
  ```

#### 3. `ai_vt_candidates`
- **Base Tables:** `students`, `classes`, `follow_up_statuses`
- **Definition:**
  ```sql
  SELECT c.name AS class_name,
         s.roll_number,
         s.name AS student_name,
         CASE
             WHEN (fs.mst_1_appeared IS NULL) THEN 'Missing'::text
             WHEN fs.mst_1_appeared THEN 'Present'::text
             ELSE 'Absent'::text
         END AS mst1_status,
         CASE
             WHEN (fs.mst_2_appeared IS NULL) THEN 'Missing'::text
             WHEN fs.mst_2_appeared THEN 'Present'::text
             ELSE 'Absent'::text
         END AS mst2_status
  FROM ((students s
    JOIN classes c ON ((c.id = s.class_id)))
    LEFT JOIN follow_up_statuses fs ON ((fs.student_id = s.id)));
  ```

#### 4. `ai_duty_roster`
- **Base Tables:** `invigilation_duties`, `mst_exams`, `rooms`, `faculty`
- **Definition:**
  ```sql
  SELECT me.label AS mst_label,
         me.exam_date,
         r.room_number,
         f.name AS faculty_name,
         idut.status AS duty_status
  FROM (((invigilation_duties idut
    JOIN mst_exams me ON ((me.id = idut.mst_exam_id)))
    JOIN rooms r ON ((r.id = idut.room_id)))
    LEFT JOIN faculty f ON ((f.id = idut.faculty_id)));
  ```

#### 5. `v_vt_follow_up_status`
- **Base Tables:** `follow_up_statuses`, `students`, `classes`, `mst_exams`
- **Definition:**
  ```sql
  SELECT s.roll_number,
         s.name AS student_name,
         c.name AS class_name,
         e1.label AS mst_1_label,
         e2.label AS mst_2_label,
         fus.mst_1_appeared,
         fus.mst_2_appeared,
         fus.calculated_status,
         fus.final_status,
         fus.override AS overridden,
         fus.override_reason,
         fus.rule_version,
         fus.updated_at
  FROM ((((follow_up_statuses fus
    JOIN students s ON ((s.id = fus.student_id)))
    JOIN classes c ON ((c.id = s.class_id)))
    LEFT JOIN mst_exams e1 ON ((e1.id = fus.mst_1_exam_id)))
    LEFT JOIN mst_exams e2 ON ((e2.id = fus.mst_2_exam_id)));
  ```

---

## 4. Item 3: Analysis of Startup Hook `_ensure_ai_views()`

### Status: **VERIFIED**

### 4.1 Code Path Citation ([backend/main.py:60-144](file:///d:/Code/eduduty/backend/main.py#L60-L144))
The function operates through a strict tri-state machine:

1. **State 1 — All views present (`len(present) == len(expected_views)`):**
   ```python
   # Lines 116-118:
   if len(present) == len(expected_views):
       # State 1: All views present. Alembic managed. Do nothing.
       return
   ```
   **Finding:** When all 5 views exist (as produced by Alembic migration 005), `_ensure_ai_views()` returns immediately. **Zero DDL statements are executed. It cannot create, replace, or alter existing views.**

2. **State 2 — Schema drift / partial view presence (`len(present) > 0 and len(missing) > 0`):**
   ```python
   # Lines 119-125:
   elif len(present) > 0 and len(missing) > 0:
       raise RuntimeError(
           f"SCHEMA DRIFT ERROR: Database contains partial AI reporting views. "
           f"Present: {sorted(list(present))}, Missing: {sorted(list(missing))}. "
           f"Run 'alembic upgrade head' to reconcile schema."
       )
   ```
   **Finding:** If views are partially present, the hook raises a fatal `RuntimeError` preventing server boot. No DDL is executed.

3. **State 3 — Zero expected views present (`len(present) == 0`):**
   ```python
   # Lines 126-138:
   else:
       app_env = os.environ.get("APP_ENV", "").strip().lower()
       if app_env not in ("development", "dev", "test", "testing"):
           raise RuntimeError("PRODUCTION SCHEMA ERROR: Database contains no AI reporting views...")
       for vname in expected_views:
           vbody = views.get(vname)
           if vbody:
               conn.execute(models.text(f"CREATE VIEW {vname} AS {vbody}"))
   ```
   **Finding:** This path triggers **only** when no views exist at all and the environment is explicitly development/testing. It executes `CREATE VIEW`, never `CREATE OR REPLACE VIEW`.

**Conclusion:** Existing views created by Alembic cannot be replaced, overwritten, or modified by `_ensure_ai_views()`.

---

## 5. Item 4: Migration Chain Status & PostgreSQL Live Revision

### Status: **VERIFIED**

### 5.1 Migration Files Audit
- Inspected directory [backend/alembic/versions/](file:///d:/Code/eduduty/backend/alembic/versions/):
  - `001_baseline_schema.py` (16,840 bytes)
  - `002_add_unique_constraints.py` (2,875 bytes)
  - `003_add_ai_views.py` (4,101 bytes)
  - `004_fix_ai_views.py` (7,834 bytes)
  - `005_ai_views_integrity.py` (1,839 bytes)
- **Finding:** No migration `006` or subsequent migration file exists in the directory. Migrations 001–005 are unmodified.

### 5.2 PostgreSQL Live Revision Query
- Executed read-only catalog query against test container:
  ```sql
  SELECT version_num FROM alembic_version;
  ```
  **Output Evidence:**
  ```text
        version_num       
  ------------------------
   005_ai_views_integrity
  (1 row)
  ```
- **Finding:** The live test database schema matches revision `005_ai_views_integrity`.

---

## 6. Item 5: Database Isolation & Non-Production Credential Audit

### Status: **VERIFIED**

### 6.1 Container & Network Isolation
- **Container Name:** `eduduty_pg_b4_test`
- **Image:** `postgres:16-alpine`
- **Network Port Mapping:** `127.0.0.1:5433 -> 5432/tcp` (Confirmed via `docker inspect`). Not exposed to `0.0.0.0` or external network interfaces.
- **Dedicated Volume:** `eduduty_b4_test_volume` mapped to `/var/lib/postgresql/data` (isolated from other volumes).

### 6.2 Database Name & Credential Audit
- Read-only introspection query:
  ```sql
  SELECT current_database(), current_user;
  ```
  **Output Evidence:**
  ```text
   current_database | current_user 
  ------------------+--------------
   eduduty_test_db  | postgres     
  (1 row)
  ```
- **Credentials Policy Compliance:**
  - Password was generated as a 32-character random hex token (`[System.Guid]::NewGuid().ToString('N')`) for this test container only.
  - No default passwords (`postgres`, `password`, `admin`, etc.) were used.
  - No production credentials, university databases, or shared secrets were accessed.
  - Neither the password nor the full credential-bearing URL is stored in any git-tracked file or printed in this report.

---

## 7. Item 6: Distinction of the 86-Test Test Suite Environment

### Status: **VERIFIED**

### 7.1 Test Suite Configuration Analysis ([backend/tests/conftest.py:15-29](file:///d:/Code/eduduty/backend/tests/conftest.py#L15-L29))
```python
# In-memory SQLite for fast testing
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

### 7.2 Test Environment Breakdown
- **Pytest Suite Scope (86 passed):**
  - All tests in `tests/test_ai_read_isolation.py`, `tests/test_alembic_b2_constraints.py`, `tests/test_alembic_b31_review.py`, `tests/test_alembic_b32_gate.py`, `tests/test_alembic_b33_auth.py`, `tests/test_alembic_b3_ai_views.py`, `tests/test_alembic_migration.py`, `tests/test_auth.py`, `tests/test_identity_spoofing.py`, `tests/test_rbac.py`, `tests/test_resource_authorization.py`, and `tests/test_upload_attendance.py` execute **100% against SQLite**.
  - Specifically, tests use either `sqlite:///:memory:` (via `client` and `db` fixtures) or temporary SQLite database files created with `tempfile.NamedTemporaryFile` (for Alembic SQLite upgrade tests).
- **PostgreSQL Validation Scope:**
  - Zero tests in `pytest` connect to PostgreSQL.
  - PostgreSQL testing in Stage B4.1 was performed solely through out-of-band CLI executions (`alembic upgrade head`, transactional SQL probes, and direct Python scripts targeting `eduduty_test_db`).

**Conclusion:** The claim "86 passed" in the earlier report represents SQLite regression test validity, **NOT PostgreSQL integration test execution**.

---

## 7. Item 7: Missing Evidence, Inconsistencies, & Pre-RLS Blockers

### Status: **VERIFIED**

The audit identified **7 critical blockers and inconsistencies** that must be formally addressed before designing Row-Level Security:

1. **Dependency Omission (`pg8000`):**
   `pg8000` is missing from `backend/requirements.txt`. Without declaring it or standardizing the PostgreSQL driver strategy, deployments and CI environments relying on `requirements.txt` will fail to establish PostgreSQL connections on systems where binary extensions are restricted.
2. **`database.ai_reader_engine` Connect Failure on `pg8000`:**
   In [backend/database.py:88](file:///d:/Code/eduduty/backend/database.py#L88), `connect_args = {"options": "-c default_transaction_read_only=on"}` crashes when used with `pg8000` (`TypeError`). If `pg8000` is used, the read-only session parameter must be enforced via a dialect-compatible hook (e.g. `event.listens_for(engine, 'connect')` executing `SET default_transaction_read_only = on`) rather than libpq connect arguments.
3. **Hardcoded Role String Substitution Bug in `database.py:76`:**
   ```python
   if "@" in SQLALCHEMY_DATABASE_URL and "postgres:" in SQLALCHEMY_DATABASE_URL:
       return SQLALCHEMY_DATABASE_URL.replace("postgres:postgres@", "ai_reader:ai_reader_pass@")
   ```
   If the superuser password is not the literal string `"postgres"`, `database.py` fails to substitute the `ai_reader` role and silently falls back to running AI queries as the superuser (`postgres`).
4. **Lack of Automated PostgreSQL Integration Tests in Pytest:**
   There are currently no automated pytest cases executing migrations or queries against a live PostgreSQL instance. RLS policy enforcement cannot be verified under continuous testing without a PostgreSQL fixture.
5. **Views Lack `WITH (security_invoker = true)`:**
   By default in PostgreSQL 15+, views operate as `security_definer` under the view owner's privileges, bypassing RLS policies applied to underlying tables (`students`, `mst_eligibility`, etc.). In Stage B4.2+, all 5 views must be created or altered with `WITH (security_invoker = true)`.
6. **Missing `faculty_id` in `ai_duty_roster` View:**
   `ai_duty_roster` projects `f.name AS faculty_name`, but neither `f.id` nor `idut.faculty_id`. Faculty-scoped RLS policies cannot filter duties by integer `faculty_id` without joining or projecting `faculty_id`. (Migration 006 is required to resolve this).
7. **Divergent View SQL in `main.py:_ensure_ai_views()`:**
   The fallback SQL in `main.py:86-93` for `ai_attendance_summary` lacks the `mst_label` join introduced in migration 005. While currently bypassed in State 1, this represents schema drift in fallback code that should be harmonized before production.

---

## 8. Summary of Findings & Next Steps

Stage B4.1 successfully demonstrated that Alembic migrations 001–005 run cleanly on PostgreSQL 16. However, this independent audit proves that:
1. Automated tests have only ever run against SQLite.
2. Driver and engine configuration (`pg8000` options handling, role replacement) require immediate refinement before application code can query PostgreSQL in an AI read-only context.
3. RLS design requires migration 006 (`faculty_id` projection) and `security_invoker = true` on all 5 views.
