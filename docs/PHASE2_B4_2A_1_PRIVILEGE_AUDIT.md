# EduDuty — Stage B4.2A.1: Independent Privilege and Test-Integrity Audit

**Date:** October 11, 2026  
**Auditor:** Independent Security Evaluation  
**Status:** Audit Complete  
**Overall Verdict:** **CONDITIONAL PASS WITH CRITICAL BLOCKERS FOR B4.2B**  
**RLS Readiness Status:** **NOT READY / GATED** (Prerequisites established, but column-level grants expose student records directly until RLS policies are implemented in Stage B4.2B)  
**Target Database:** PostgreSQL 16.15 (`eduduty_test_db`) in container `eduduty_pg_b4_test` at `127.0.0.1:5433`  
**Baseline Database:** SQLite `eduduty.db` (100% preserved and untouched)  

---

## 1. Executive Summary & Verification Matrix

This independent audit rigorously verified the implementation delivered in Stage B4.2A against the PostgreSQL 16 test database, migration scripts, application code, test suite, and catalog metadata.

### Verification Matrix

| Section | Audit Requirement | Verdict | File & Line References | Key Finding Summary |
| :--- | :--- | :--- | :--- | :--- |
| **1.1** | Role Provisioning Reproducibility | **BLOCKED** | [docs/PHASE2_B4_2A_AI_READER_AND_VIEW_SECURITY.md:123-154](file:///d:/Code/eduduty/docs/PHASE2_B4_2A_AI_READER_AND_VIEW_SECURITY.md#L123-L154) | No automated provisioning script exists. The role was created manually in the container. Clean container setups will fail. |
| **1.2** | Role Privilege Non-Escalation | **PASS** | `pg_roles` catalog query | `ai_reader` has `rolsuper=f`, `rolbypassrls=f`, `rolcreatedb=f`, `rolcreaterole=f`, `rolinherit=f`. No ownership or superuser rights. |
| **2.1** | Column-Level Privilege Enumeration | **PASS** | `information_schema.column_privileges` | Exact least-privilege columns for 8 base tables and 5 views audited from PostgreSQL catalog. |
| **2.2** | Direct Student Table Column Access | **FAIL / GATED** | Live execution under `ai_reader` | `SELECT * FROM students` is blocked, but `SELECT id, name, roll_number FROM students` succeeds directly without row filtering. RLS is **not** active. |
| **2.3** | Identification of Tables Requiring RLS | **VERIFIED** | Base table dependencies | `students`, `mst_eligibility`, `follow_up_statuses`, `invigilation_duties` require table RLS before direct access is safe. |
| **3.1** | Prohibited DDL/DML/GRANT Tests | **PASS** | [tests/test_alembic_b42a_ai_reader.py:192-216](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py#L192-L216) | Each statement is independently checked with `conn.rollback()`; aborted transaction states do not produce false passes. |
| **3.2** | Actual Role Usage in PG Tests | **PASS** | [tests/test_alembic_b42a_ai_reader.py:61-81](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py#L61-L81) | PG tests connect strictly as `ai_reader` and execute queries with session-level read-only verification. |
| **3.3** | PG Unavailable Failure Mode | **FAIL / DEFECT** | [tests/test_alembic_b42a_ai_reader.py:52-58](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py#L52-L58) | When port 5433 is unreachable, tests call `pytest.skip()` instead of failing clearly or marking as blocked. |
| **4.1** | Migration 006 Upgrade / Downgrade | **PASS** | [alembic/versions/006_secure_ai_views.py:21-235](file:///d:/Code/eduduty/backend/alembic/versions/006_secure_ai_views.py#L21-L235) | Exactly matches 005 view definitions; adds `WITH (security_invoker = true)` and `f.id AS faculty_id`; downgrade is clean and reversible. |
| **4.2** | Schema Drift & Unauthorized Changes | **PASS** | Alembic catalog inspection | Zero unexpected tables, constraints, or schemas modified by migration 006. |
| **5.1** | Credential Hygiene | **FAIL** | [tests/test_alembic_b42a_ai_reader.py:43](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py#L43), [tests/test_postgres_connection_b412.py:116](file:///d:/Code/eduduty/backend/tests/test_postgres_connection_b412.py#L116) | Plaintext database token for `postgres` admin account is hardcoded in test fixtures. Not found in source or documentation. |

---

## 2. Requirement 1: Role Provisioning Audit

### 2.1 Reproducibility on a Clean Database
- **Finding:** **BLOCKED**
- **Analysis:**  
  The `ai_reader` role and its schema/column grants were applied manually via an interactive SQL session in the container. No executable migration, SQL setup script, or provisioning automation (`.sql`, `.sh`, or `.py`) exists in the repository.
- **Evidence:**  
  In [tests/test_alembic_b42a_ai_reader.py:75-78](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py#L75-L78), the test fixture assumes the role already exists:
  ```python
  conn.execute(text(f"ALTER ROLE ai_reader WITH PASSWORD '{ephemeral_token}';"))
  ```
  On a fresh container or CI database running standard Alembic migrations `001` through `006`, the `ai_reader` role **does not exist**, causing the test fixture to fail immediately with:
  ```text
  pg8000.dbapi.ProgrammingError: role "ai_reader" does not exist
  ```
  *Per audit instructions, this requirement is marked **BLOCKED**. No provisioning script was created during this audit.*

### 2.2 Manual Grants Required for Invoker-Security Views
Because PostgreSQL 15+ views with `WITH (security_invoker = true)` evaluate permissions against the *invoking user*, `ai_reader` requires the following 11 database grants:
1. `GRANT CONNECT ON DATABASE eduduty_test_db TO ai_reader;`
2. `GRANT USAGE ON SCHEMA public TO ai_reader;`
3. `GRANT SELECT ON ai_duty_roster, ai_attendance_summary, ai_eligibility_summary, ai_vt_candidates, v_vt_follow_up_status TO ai_reader;`
4. `GRANT SELECT (id, name) ON classes TO ai_reader;`
5. `GRANT SELECT (id, label, exam_date) ON mst_exams TO ai_reader;`
6. `GRANT SELECT (id, class_id, roll_number, name) ON students TO ai_reader;`
7. `GRANT SELECT (id, student_id, mst_exam_id, overall_pct, lowest_subject_pct, status) ON mst_eligibility TO ai_reader;`
8. `GRANT SELECT (student_id, mst_1_appeared, mst_2_appeared, mst_1_exam_id, mst_2_exam_id, calculated_status, final_status, override, override_reason, rule_version, updated_at) ON follow_up_statuses TO ai_reader;`
9. `GRANT SELECT (mst_exam_id, room_id, faculty_id, status) ON invigilation_duties TO ai_reader;`
10. `GRANT SELECT (id, room_number) ON rooms TO ai_reader;`
11. `GRANT SELECT (id, name) ON faculty TO ai_reader;`

### 2.3 Verification of Non-Superuser and NOBYPASSRLS Attributes
- **Finding:** **PASS**
- **Catalog Evidence (`pg_roles`):**
  ```text
    rolname  | rolsuper | rolinherit | rolcreaterole | rolcreatedb | rolcanlogin | rolreplication | rolbypassrls 
  -----------+----------+------------+---------------+-------------+-------------+----------------+--------------
   ai_reader | f        | f          | f             | f           | t           | f              | f
  ```
  The role cannot create roles, databases, or schemas, cannot bypass RLS, and owns no tables or views.

---

## 3. Requirement 2: Column-Level Access & RLS Boundary Audit

### 3.1 Enumeration of Granted Table & Column Privileges
Inspected live PostgreSQL catalog via `information_schema.table_privileges` and `information_schema.column_privileges`:

#### Table-Level Privileges Granted to `ai_reader`:
- `public.ai_attendance_summary`: `SELECT`
- `public.ai_duty_roster`: `SELECT`
- `public.ai_eligibility_summary`: `SELECT`
- `public.ai_vt_candidates`: `SELECT`
- `public.v_vt_follow_up_status`: `SELECT`
- **Base Tables:** **Zero** table-level privileges granted. Direct `SELECT *` fails on all base tables.

#### Column-Level Privileges Granted to `ai_reader`:
| Base Table | Granted Columns | Ungranted (Protected) Columns |
| :--- | :--- | :--- |
| `classes` | `id`, `name` | `branch`, `year`, `section`, `created_at` |
| `faculty` | `id`, `name` | `email`, `department`, `created_at` |
| `follow_up_statuses` | `calculated_status`, `final_status`, `mst_1_appeared`, `mst_1_exam_id`, `mst_2_appeared`, `mst_2_exam_id`, `override`, `override_reason`, `rule_version`, `student_id`, `updated_at` | None |
| `invigilation_duties`| `faculty_id`, `mst_exam_id`, `room_id`, `status` | `id`, `created_at` |
| `mst_eligibility` | `id`, `lowest_subject_pct`, `mst_exam_id`, `overall_pct`, `status`, `student_id` | `created_at`, `updated_at` |
| `mst_exams` | `exam_date`, `id`, `label` | `academic_year`, `semester`, `created_at` |
| `rooms` | `id`, `room_number` | `capacity`, `building`, `floor` |
| `students` | `class_id`, `id`, `name`, `roll_number` | `created_at`, `email`, `phone` |

### 3.2 Direct SELECT Attempts on Granted Student Columns
Tested under independent connections and clean transactions using the `ai_reader` role:

```text
=== DIRECT SELECT TESTS UNDER ai_reader ROLE ===
PASS (ALLOWED): students.id -> returned rows
PASS (ALLOWED): students.name -> returned rows
PASS (ALLOWED): students.roll_number -> returned rows
PASS (ALLOWED): students.class_id -> returned rows
DENIED:         students.* (all columns) -> permission denied for table students
PASS (ALLOWED): mst_eligibility.overall_pct -> returned rows
PASS (ALLOWED): mst_eligibility.lowest_subject_pct -> returned rows
PASS (ALLOWED): mst_eligibility.status -> returned rows
DENIED:         mst_eligibility.* (all columns) -> permission denied for table mst_eligibility
PASS (ALLOWED): follow_up_statuses.student_id -> returned rows
PASS (ALLOWED): follow_up_statuses.calculated_status -> returned rows
PASS (ALLOWED): follow_up_statuses.override_reason -> returned rows
DENIED:         follow_up_statuses.* (all columns) -> permission denied for table follow_up_statuses
```

### 3.3 Critical Architectural Distinction: Column-Level vs Row-Level Protection
- **Finding:** **FAIL / GATED (RLS NOT ACTIVE)**
- **Audit Explanation:**  
  Column-level permissions only restrict *which fields* a query can project. They do **not** restrict *which rows* are returned.
  Because column-level `SELECT (id, class_id, roll_number, name)` is granted to `ai_reader`, any client or rogue AI tool connecting as `ai_reader` can execute:
  ```sql
  SELECT id, roll_number, name FROM students;
  ```
  and retrieve **every student across all classes institution-wide**.
- **Conclusion:**  
  RLS is **not active or verified**. Migration 006 established the invoker semantics necessary for RLS to take effect in the future, but direct student data reads remain completely unconstrained until Stage B4.2B.

### 3.4 Tables Requiring Row-Level Security (RLS) in Stage B4.2B
The following 4 tables require `ENABLE ROW LEVEL SECURITY` and faculty-scoped policies:
1. **`students`**: Restrict rows to classes assigned to the requesting faculty member (`FacultyTimetable`).
2. **`mst_eligibility`**: Restrict eligibility rows to students in assigned classes.
3. **`follow_up_statuses`**: Restrict VT status tracking to assigned student cohorts.
4. **`invigilation_duties`**: Restrict or permit duty visibility based on the approved duty policy (institution-wide or individual).

---

## 4. Requirement 3: Test Validity Audit

### 4.1 Prohibited-Write and Prohibited-DDL Tests
- **Finding:** **PASS**
- **File:** [backend/tests/test_alembic_b42a_ai_reader.py:192-216](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py#L192-L216)
- **Inspection:**
  ```python
  for stmt in prohibited_statements:
      failed = False
      try:
          conn.execute(text(stmt))
      except Exception as e:
          failed = True
          conn.rollback()
          err = str(e).lower()
          assert "permission denied" in err or "must be owner" in err
      assert failed
  ```
  - `conn.rollback()` is invoked immediately in the exception block.
  - The assertion verifies that the specific error message contains `"permission denied"` or `"must be owner"`. If an earlier error had left the transaction in an aborted state without rolling back, PostgreSQL would return `"current transaction is aborted, commands ignored until end of transaction block"`, which fails the assertion. Therefore, false passes due to stale transaction aborts are impossible.

### 4.2 Role Verification in PostgreSQL Tests
- **Finding:** **PASS**
- **Inspection:**  
  In [tests/test_alembic_b42a_ai_reader.py:61-81](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py#L61-L81), `pg_ai_reader_url` provisions an ephemeral session token on `ALTER ROLE ai_reader` and connects as `ai_reader`. The test verifies `rolsuper == False` and `rolbypassrls == False` against `pg_roles`.

### 4.3 Database Unavailability Failure Mode
- **Finding:** **FAIL / DEFECT**
- **File:** [backend/tests/test_alembic_b42a_ai_reader.py:56](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py#L56), [backend/tests/test_postgres_connection_b412.py:129](file:///d:/Code/eduduty/backend/tests/test_postgres_connection_b412.py#L129)
- **Inspection:**
  ```python
  @pytest.fixture(scope="module")
  def pg_admin_url():
      url = _get_pg_admin_url()
      if not url:
          pytest.skip("PostgreSQL test container on 127.0.0.1:5433 is not reachable")
      return url
  ```
  When the PostgreSQL test container is down, tests are marked **SKIPPED** rather than failing the test suite with an error. While this prevents silent SQLite fallback, it allows a CI/CD run to report `0 failures` when live PostgreSQL validation was never executed.
  *Remediation:* Replace `pytest.skip` with `pytest.fail("BLOCKED: PostgreSQL test container on 127.0.0.1:5433 is unreachable")` or a strict command-line gate.

---

## 5. Requirement 4: Migration Integrity Audit

### 5.1 Verification Against Revision 005 Baseline
- **Finding:** **PASS**
- **Inspection:**
  - `ai_eligibility_summary`: Matches revision 004/005 base query with `borderline_count` classification. Added `WITH (security_invoker = true)`.
  - `ai_attendance_summary`: Preserves revision 005 fix with `me.label AS mst_label` joining `mst_exams` without synthetic cross-exam grouping. Added `WITH (security_invoker = true)`.
  - `ai_vt_candidates`: Preserves canonical join on `follow_up_statuses`. Added `WITH (security_invoker = true)`.
  - `ai_duty_roster`: Preserves all 004/005 columns while intentionally projecting `f.id AS faculty_id`. Added `WITH (security_invoker = true)`.
  - `v_vt_follow_up_status`: Preserves full override, rule version, and audit metadata. Added `WITH (security_invoker = true)`.
- **Downgrade Integrity:**  
  [backend/alembic/versions/006_secure_ai_views.py:130-235](file:///d:/Code/eduduty/backend/alembic/versions/006_secure_ai_views.py#L130-L235) downgrade function restores the exact revision 005 SQL definitions without `WITH (security_invoker = true)` and without `faculty_id`, and safely restores `ai_reader` view grants without cascading drops.

### 5.2 Schema Objects and Drift
- **Finding:** **PASS**
- Zero tables, columns, constraints, or sequences outside of the 5 views were modified.

---

## 6. Requirement 5: Credential Hygiene Audit

### 6.1 Audit Across Repository Artifacts
- **Application Source Code (`backend/*.py`):** **PASS** — No hardcoded database credentials or tokens found.
- **Tracked Configuration (`.env`):** **PASS** — Contains only commented localhost examples.
- **Documentation & Reports (`docs/*.md`):** **PASS** — Passwords and tokens are strictly masked as `<REDACTED>` and `<SECRET_LOCAL_TOKEN>`.
- **Automated Test Code:** **FAIL** — Plaintext container tokens were discovered:
  - [backend/tests/test_alembic_b42a_ai_reader.py:43](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py#L43): Hardcoded local container password token in `_get_pg_admin_url()`.
  - [backend/tests/test_postgres_connection_b412.py:116](file:///d:/Code/eduduty/backend/tests/test_postgres_connection_b412.py#L116): Identical hardcoded local container token in `_get_pg_test_url()`.
  *Note: Although these test files are currently untracked in Git, committing them would leak container secrets.*

---

## 7. Test Suite Execution Breakdown

The complete test suite executes 108 tests in total:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.1
rootdir: D:\Code\eduduty\backend
collected 108 items

tests/test_ai_read_isolation.py ......                                   [  5%]
tests/test_alembic_b2_constraints.py ......                              [ 11%]
tests/test_alembic_b31_review.py ...                                     [ 13%]
tests/test_alembic_b32_gate.py ...                                       [ 16%]
tests/test_alembic_b33_auth.py ............................              [ 42%]
tests/test_alembic_b3_ai_views.py .....                                  [ 47%]
tests/test_alembic_b42a_ai_reader.py ..........                          [ 56%]
tests/test_alembic_migration.py ...                                      [ 59%]
tests/test_auth.py ..........                                            [ 68%]
tests/test_identity_spoofing.py .                                        [ 69%]
tests/test_postgres_connection_b412.py ............                      [ 80%]
tests/test_rbac.py ...                                                   [ 83%]
tests/test_resource_authorization.py ........                            [ 90%]
tests/test_upload_attendance.py ..........                               [100%]

====================== 108 passed, 17 warnings in 15.36s ======================
```

### Breakdown by Test Environment

| Environment | Purpose | Test Files | Tests | Result |
| :--- | :--- | :--- | :---: | :---: |
| **SQLite (In-Memory / Tempfile)** | Baseline RBAC, Auth, attendance parsing, SQLite migration compatibility | `test_auth.py`, `test_rbac.py`, `test_alembic_b33_auth.py`, `test_alembic_b2_constraints.py`, etc. | **94** | **94 PASSED** |
| **Live PostgreSQL 16 Integration** | Port 5433 container validation: Migration 006, role privileges, session read-only, DDL/DML rejection | `test_alembic_b42a_ai_reader.py` (7 live tests), `test_postgres_connection_b412.py` (7 live tests) | **14** | **14 PASSED** |
| **Total** | Full repository test suite | 14 test modules | **108** | **108 PASSED** |

---

## 8. Summary of Blockers to Fix Before Stage B4.2B

The following blockers must be addressed before proceeding with Row-Level Security (RLS) implementation in Stage B4.2B:

1. **Role Provisioning Artifact Missing (BLOCKER):**
   Create a repeatable, tracked role-provisioning script (e.g., `scripts/provision_ai_reader.sql` or Alembic-managed bootstrap) that can provision `ai_reader` and its exact required privileges on any fresh PostgreSQL instance.
2. **Column-Level Direct Student Read Exposure (GATED):**
   Do not treat column-level grants as data isolation. Stage B4.2B must immediately enforce RLS on `students`, `mst_eligibility`, and `follow_up_statuses` to prevent raw data extraction by `ai_reader`.
3. **Hardcoded Credentials in Test Code (DEFECT):**
   Remove hardcoded tokens from [test_alembic_b42a_ai_reader.py:43](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py#L43) and [test_postgres_connection_b412.py:116](file:///d:/Code/eduduty/backend/tests/test_postgres_connection_b412.py#L116); require environment variables (`PG_TEST_PASSWORD` or `DATABASE_URL`).
4. **Test Skip Instead of Failure on Missing PostgreSQL (DEFECT):**
   Configure PostgreSQL integration tests to fail explicitly if `127.0.0.1:5433` is unreachable rather than skipping silently.
5. **Session Context Injection Mechanism (PRE-REQUISITE):**
   Design and implement `SET LOCAL app.current_faculty_id = :faculty_id;` within `backend/ai_service.py` to allow PostgreSQL RLS policies to evaluate faculty identity at runtime.
