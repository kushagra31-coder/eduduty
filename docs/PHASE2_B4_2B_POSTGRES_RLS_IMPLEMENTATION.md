# EduDuty Phase 2 — Stage B4.2B: PostgreSQL Row-Level Security & Transaction-Scoped Identity Context Implementation

**Stage:** B4.2B  
**Author:** AI Engineering & Security Team  
**Date:** October 11, 2026  
**Status:** PASS (Fully Implemented & Verified against Live PostgreSQL 16)  
**Database Head Revision:** `007_implement_faculty_rls`  

---

## 1. Executive Summary

In Stage B4.2B, PostgreSQL Row-Level Security (RLS) and transaction-scoped identity context injection were designed, implemented, and verified for EduDuty's AI reporting path.

This implementation guarantees that:
1. **Cross-Class Student Data Isolation:** Faculty members can read student-related reporting data **only** for classes actively assigned through `FacultyTimetable` linked to an active `TimetableVersion`. Cross-class direct base-table queries and approved reporting view queries are strictly blocked at the database engine level.
2. **Duty Roster Exception Without Student Leaks:** Authorized faculty may view the institution-wide faculty duty roster (`ai_duty_roster` and `invigilation_duties`), but this exception strictly isolates student records, eligibility, attendance, and follow-up data.
3. **Fail-Closed Context Binding:** Requests lacking authenticated identity context, requests with malformed non-integer context, or requests under unauthorized roles fail closed and return 0 rows.
4. **Zero Pooled-Connection Leakage:** Identity context is bound strictly using transaction-local configuration (`set_config(..., true)`), paired with mandatory transaction rollback (`read_db.rollback()`) upon query completion, ensuring no context bleeds into reused pooled connections.
5. **Least-Privileged AI Reader Boundary:** The `ai_reader` role remains strictly unprivileged (`NOSUPERUSER`, `NOBYPASSRLS`, `NOCREATEDB`, `NOCREATEROLE`), owns zero database objects, and is denied all write, DDL, and administrative permissions.

---

## 2. Changed & Created Files

| File | Change Type | Purpose |
| :--- | :--- | :--- |
| `backend/alembic/versions/007_implement_faculty_rls.py` | **Created** | Forward Alembic migration implementing helper functions (`can_current_user_access_class`, `can_current_user_access_student`, `can_current_user_access_duty_roster`), enabling RLS on 5 sensitive base tables, and defining 5 RLS policies. |
| `backend/ai_service.py` | **Modified** | Injected transaction-scoped identity context (`set_config(..., true)`) and cleanup rollback in `execute_structured_reporting_op` and `handle_ai_message` (dev fallback). Enhanced SQL validator to block `SET`, `SET_CONFIG`, and `CURRENT_SETTING`. |
| `backend/tests/test_postgres_rls_b42b.py` | **Created** | Comprehensive test suite containing all 18 required live PostgreSQL 16 integration tests. |
| `backend/tests/test_alembic_b42a_ai_reader.py` | **Modified** | Updated head revision assertion in `test_migration_006_upgrade_and_downgrade` to accept forward revision `007_implement_faculty_rls`. |
| `docs/PHASE2_B4_2B_POSTGRES_RLS_IMPLEMENTATION.md` | **Created** | Comprehensive engineering report and evidence audit. |

---

## 3. Data-Access Contract & Architecture

### 3.1 Policy Rules

1. **Student Data Scope:**
   - Faculty identity is derived exclusively on the server from authoritative JWT verification and the database `users.faculty_id` relationship. No client-supplied faculty ID is trusted.
   - Access requires an active assignment in `faculty_timetable` matching the student's class and an active timetable version (`timetable_versions.active = true`).
   - Inactive versions (`active = false`), unversioned/NULL assignments, or unassigned faculty fail closed (0 rows).
   - Historical attendance records (`attendance_records`) do not grant current student access.
2. **Faculty Duty Roster Scope:**
   - Authorized faculty (`FACULTY`, `EXAM_COORDINATOR`, `ADMIN`, `SUPER_ADMIN`) may read institution-wide invigilation duty allocations across all rooms and exams.
   - This exception does not broaden access to `students`, `mst_eligibility`, or `follow_up_statuses`.
3. **Five Approved Reporting Views:**
   - `ai_eligibility_summary` (depends on `students`, `mst_eligibility`, `classes`, `mst_exams`)
   - `ai_attendance_summary` (depends on `students`, `classes`, `attendance_records`)
   - `ai_vt_candidates` (depends on `students`, `mst_eligibility`, `classes`, `mst_exams`)
   - `ai_duty_roster` (depends on `invigilation_duties`, `mst_exams`, `rooms`, `faculty`)
   - `v_vt_follow_up_status` (depends on `follow_up_statuses`, `students`, `classes`, `mst_exams`)
   All five views use `security_invoker = true` (PostgreSQL 15+), ensuring RLS policies on the base tables are enforced during view execution.

---

## 4. Protected Tables & Policy Definitions

### 4.1 Protected Base Tables

Row-Level Security is explicitly enabled on the following 5 base tables:
- `students` (`relrowsecurity = true`)
- `mst_eligibility` (`relrowsecurity = true`)
- `follow_up_statuses` (`relrowsecurity = true`)
- `invigilation_duties` (`relrowsecurity = true`)
- `classes` (`relrowsecurity = true`)

### 4.2 Audited Security Definer Helper Functions

To avoid granting `ai_reader` direct `SELECT` access to `faculty_timetable` and `timetable_versions`, helper functions are defined with `SECURITY DEFINER` and a fixed, hardened `search_path`:

```sql
-- 1. Class Access Helper
CREATE OR REPLACE FUNCTION can_current_user_access_class(target_class_id int)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    cur_role text;
    cur_faculty_id int;
    is_assigned boolean;
BEGIN
    cur_role := LOWER(COALESCE(current_setting('app.current_user_role', true), ''));

    -- Administrators and exam coordinators have institution-wide access
    IF cur_role IN ('super_admin', 'admin', 'exam_coordinator') THEN
        RETURN true;
    END IF;

    -- Strict fail-closed for non-faculty roles
    IF cur_role <> 'faculty' THEN
        RETURN false;
    END IF;

    -- Safely parse faculty ID from transaction context
    BEGIN
        cur_faculty_id := current_setting('app.current_faculty_id', true)::int;
    EXCEPTION WHEN OTHERS THEN
        RETURN false;
    END;

    IF cur_faculty_id IS NULL OR target_class_id IS NULL THEN
        RETURN false;
    END IF;

    -- Check active timetable version assignment
    SELECT EXISTS (
        SELECT 1
        FROM faculty_timetable ft
        JOIN timetable_versions tv ON tv.id = ft.timetable_version_id
        WHERE ft.faculty_id = cur_faculty_id
          AND ft.class_id = target_class_id
          AND tv.active = true
    ) INTO is_assigned;

    RETURN COALESCE(is_assigned, false);
END;
$$;

-- 2. Student Access Helper
CREATE OR REPLACE FUNCTION can_current_user_access_student(target_student_id int)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    cur_role text;
    cur_faculty_id int;
    is_assigned boolean;
BEGIN
    cur_role := LOWER(COALESCE(current_setting('app.current_user_role', true), ''));

    IF cur_role IN ('super_admin', 'admin', 'exam_coordinator') THEN
        RETURN true;
    END IF;

    IF cur_role <> 'faculty' THEN
        RETURN false;
    END IF;

    BEGIN
        cur_faculty_id := current_setting('app.current_faculty_id', true)::int;
    EXCEPTION WHEN OTHERS THEN
        RETURN false;
    END;

    IF cur_faculty_id IS NULL OR target_student_id IS NULL THEN
        RETURN false;
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM students s
        JOIN faculty_timetable ft ON ft.class_id = s.class_id
        JOIN timetable_versions tv ON tv.id = ft.timetable_version_id
        WHERE s.id = target_student_id
          AND ft.faculty_id = cur_faculty_id
          AND tv.active = true
    ) INTO is_assigned;

    RETURN COALESCE(is_assigned, false);
END;
$$;

-- 3. Duty Roster Access Helper (Institution-Wide Approved Exception)
CREATE OR REPLACE FUNCTION can_current_user_access_duty_roster()
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    cur_role text;
BEGIN
    cur_role := LOWER(COALESCE(current_setting('app.current_user_role', true), ''));

    IF cur_role IN ('super_admin', 'admin', 'exam_coordinator', 'faculty') THEN
        RETURN true;
    END IF;

    RETURN false;
END;
$$;
```

### 4.3 RLS Policy Definitions

The following 5 policies are registered in `pg_policies`:

```sql
-- Students
CREATE POLICY rls_students_faculty_class_scope ON students
FOR SELECT TO ai_reader, public
USING (can_current_user_access_class(class_id));

-- Mst Eligibility
CREATE POLICY rls_mst_eligibility_faculty_class_scope ON mst_eligibility
FOR SELECT TO ai_reader, public
USING (can_current_user_access_student(student_id));

-- Follow-Up Statuses
CREATE POLICY rls_follow_up_statuses_faculty_class_scope ON follow_up_statuses
FOR SELECT TO ai_reader, public
USING (can_current_user_access_student(student_id));

-- Classes
CREATE POLICY rls_classes_faculty_class_scope ON classes
FOR SELECT TO ai_reader, public
USING (can_current_user_access_class(id));

-- Invigilation Duties (Approved Duty Roster Exception)
CREATE POLICY rls_invigilation_duties_roster_access ON invigilation_duties
FOR SELECT TO ai_reader, public
USING (can_current_user_access_duty_roster());
```

---

## 5. Identity-Context Mechanism & Connection Isolation

### 5.1 Server-Derived Transaction Context
Identity context is never accepted from client payloads or query parameters. The application server derives the identity through:
1. `current_user = Depends(require_permission("ai.read"))` (cryptographic JWT verification).
2. Authoritative database lookup of `current_user.faculty_id` and `current_user.role`.
3. Parameterized transaction-local injection inside `backend/ai_service.py`:
```python
is_pg = (read_db.get_bind().dialect.name == "postgresql")
try:
    if is_pg:
        fac_id_str = str(current_user.faculty_id) if (current_user and current_user.faculty_id is not None) else ""
        role_str = (current_user.role or "").strip().lower() if current_user else ""
        read_db.execute(
            text("SELECT set_config('app.current_faculty_id', :fac_id, true), set_config('app.current_user_role', :role, true)"),
            {"fac_id": fac_id_str, "role": role_str}
        )

    rows = read_db.execute(text(sql), params).fetchmany(100)
    data = [dict(r._mapping) for r in rows]
finally:
    if is_pg:
        try:
            read_db.rollback()
        except Exception:
            pass
```

### 5.2 Prevention of Identity Spoofing & Connection Pool Leakage
1. **Transaction-Local Setting (`is_local = true`):**
   The third argument to `set_config('app.current_faculty_id', :fac_id, true)` specifies transaction scope. The setting exists only during the active database transaction.
2. **Explicit Rollback Cleanup:**
   The `finally:` block executes `read_db.rollback()`. In PostgreSQL, transaction termination (`COMMIT` or `ROLLBACK`) instantly and unconditionally discards all `is_local = true` variables.
3. **Connection Pool Verification:**
   Test 11 proves that when a pooled connection is returned to the SQLAlchemy pool and reused by a subsequent unauthenticated or different session, `current_setting('app.current_faculty_id', true)` is empty (`''`) and zero student rows are visible.
4. **SQL Injection & GUC Manipulation Defense:**
   In `backend/ai_service.py`, `_validate_read_sql` explicitly blocks `SET`, `SET_CONFIG`, and `CURRENT_SETTING`, preventing callers in development fallback mode from manipulating transaction variables.

---

## 6. Live PostgreSQL 16 Integration Test Results

Integration tests were executed against the live PostgreSQL 16 container (`eduduty_pg_b4_test` at `127.0.0.1:5433`, database `eduduty_test_db`) with `EDUDUTY_REQUIRE_POSTGRES_TESTS=1`.

### 6.1 Test Suite 1: Stage B4.2B RLS Suite (`test_postgres_rls_b42b.py`)

Command:
```powershell
$env:PG_TEST_PASSWORD = $(docker exec eduduty_pg_b4_test printenv POSTGRES_PASSWORD)
$env:EDUDUTY_REQUIRE_POSTGRES_TESTS = "1"
python -m pytest backend/tests/test_postgres_rls_b42b.py -v
```

Results:
```
backend/tests/test_postgres_rls_b42b.py::test_01_faculty_a_reads_authorized_class_a_student_data PASSED [  5%]
backend/tests/test_postgres_rls_b42b.py::test_02_faculty_a_cannot_read_class_b_student_rows_direct_query PASSED [ 11%]
backend/tests/test_postgres_rls_b42b.py::test_03_faculty_a_cannot_obtain_class_b_data_via_all_five_views PASSED [ 16%]
backend/tests/test_postgres_rls_b42b.py::test_04_faculty_b_reads_only_assigned_class_b_data PASSED [ 22%]
backend/tests/test_postgres_rls_b42b.py::test_05_unassigned_faculty_receives_no_student_rows PASSED [ 27%]
backend/tests/test_postgres_rls_b42b.py::test_06_inactive_timetable_version_grants_no_access PASSED [ 33%]
backend/tests/test_postgres_rls_b42b.py::test_07_null_or_unversioned_assignments_grant_no_access PASSED [ 38%]
backend/tests/test_postgres_rls_b42b.py::test_08_historical_attendance_does_not_grant_current_access PASSED [ 44%]
backend/tests/test_postgres_rls_b42b.py::test_09_missing_identity_context_fails_closed PASSED [ 50%]
backend/tests/test_postgres_rls_b42b.py::test_10_malformed_or_unauthorized_context_fails_closed PASSED [ 55%]
backend/tests/test_postgres_rls_b42b.py::test_11_pooled_connection_reuse_does_not_leak_context PASSED [ 61%]
backend/tests/test_postgres_rls_b42b.py::test_12_rollback_or_exception_clears_active_identity PASSED [ 66%]
backend/tests/test_postgres_rls_b42b.py::test_13_authorized_duty_roster_exception_permits_institution_wide_roster PASSED [ 72%]
backend/tests/test_postgres_rls_b42b.py::test_14_duty_roster_access_does_not_grant_additional_student_data PASSED [ 77%]
backend/tests/test_postgres_rls_b42b.py::test_15_direct_writes_ddl_grants_denied_to_ai_reader PASSED [ 83%]
backend/tests/test_postgres_rls_b42b.py::test_16_rls_effective_for_direct_and_view_queries PASSED [ 88%]
backend/tests/test_postgres_rls_b42b.py::test_17_migration_007_upgrade_and_downgrade_cycle PASSED [ 94%]
backend/tests/test_postgres_rls_b42b.py::test_18_catalogs_confirm_rls_flags_policies_ownership_privileges PASSED [100%]

======================= 18 passed in 1.71s =======================
```

### 6.2 Full PostgreSQL Integration Suite (All 48 Tests)

Command:
```powershell
python -m pytest backend/tests/test_postgres_rls_b42b.py backend/tests/test_alembic_b42a_ai_reader.py backend/tests/test_postgres_connection_b412.py backend/tests/test_postgres_gating.py -v
```

Results:
```
======================= 48 passed, 15 warnings in 6.22s =======================
```
- Total Tests: **48**
- Passed: **48**
- Failed: **0**
- Skipped: **0**

---

## 7. SQLite Regression Test Results

SQLite regression test suites were executed independently to verify that SQLite development and testing paths remain fully operational.

### 7.1 Security & Authentication Regression Suite
Command:
```powershell
python -m pytest backend/tests/test_auth.py backend/tests/test_rbac.py backend/tests/test_resource_authorization.py backend/tests/test_upload_attendance.py backend/tests/test_identity_spoofing.py backend/tests/test_ai_read_isolation.py -v
```
Results:
```
======================= 38 passed, 14 warnings in 3.22s =======================
```

### 7.2 Alembic & End-to-End Auth Regression Suite
Command:
```powershell
cd backend
python -m pytest tests/test_alembic_b33_auth.py -v
```
Results:
```
======================= 28 passed, 12 warnings in 5.09s =======================
```

---

## 8. Catalog Verification & Security Flags

Execution against PostgreSQL system catalogs (`pg_class`, `pg_policies`, `pg_proc`, `pg_roles`):

1. **Table RLS Status:**
   - `classes`: `relrowsecurity = True`, `relforcerowsecurity = False`
   - `students`: `relrowsecurity = True`, `relforcerowsecurity = False`
   - `mst_eligibility`: `relrowsecurity = True`, `relforcerowsecurity = False`
   - `follow_up_statuses`: `relrowsecurity = True`, `relforcerowsecurity = False`
   - `invigilation_duties`: `relrowsecurity = True`, `relforcerowsecurity = False`
2. **Policy Definitions:**
   - `classes` $\rightarrow$ `rls_classes_faculty_class_scope` (SELECT, `can_current_user_access_class(id)`)
   - `students` $\rightarrow$ `rls_students_faculty_class_scope` (SELECT, `can_current_user_access_class(class_id)`)
   - `mst_eligibility` $\rightarrow$ `rls_mst_eligibility_faculty_class_scope` (SELECT, `can_current_user_access_student(student_id)`)
   - `follow_up_statuses` $\rightarrow$ `rls_follow_up_statuses_faculty_class_scope` (SELECT, `can_current_user_access_student(student_id)`)
   - `invigilation_duties` $\rightarrow$ `rls_invigilation_duties_roster_access` (SELECT, `can_current_user_access_duty_roster()`)
3. **Helper Function Hardening:**
   - `can_current_user_access_class`: `SECURITY DEFINER = True`, `search_path = ['search_path=public, pg_temp']`
   - `can_current_user_access_student`: `SECURITY DEFINER = True`, `search_path = ['search_path=public, pg_temp']`
   - `can_current_user_access_duty_roster`: `SECURITY DEFINER = True`, `search_path = ['search_path=public, pg_temp']`
4. **Role Privileges (`ai_reader`):**
   - `rolsuper = False`
   - `rolbypassrls = False`
   - `rolcreaterole = False`
   - `rolcreatedb = False`
   - Zero object ownership across all public schema objects.
   - Denied direct `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `ALTER`, and `GRANT`.

---

## 9. Final Acceptance Gate Verification

- [x] **Migration Succeeded on Live PostgreSQL:** Revision `007_implement_faculty_rls` upgraded and verified.
- [x] **Cross-Class Direct Queries Blocked:** Faculty A querying Class B receives 0 rows.
- [x] **Cross-Class View Queries Blocked:** Faculty A querying reporting views receives 0 rows for Class B.
- [x] **Missing Context Fails Closed:** Unset context returns 0 rows.
- [x] **Malformed Context Fails Closed:** Non-integer faculty ID or non-faculty role returns 0 rows.
- [x] **Duty-Roster Exception Works Without Student Leakage:** Duty roster displays institution-wide duties while student tables remain strictly filtered.
- [x] **Zero Skips in Required Mode:** All 18 B4.2B tests and all 48 PostgreSQL tests passed with zero skips.
- [x] **`ai_reader` Remains Unprivileged:** Read-only transaction enforcement and negative permissions intact.
- [x] **Data Integrity Preserved:** `backend/eduduty.db` and SecureMailScope assets untouched.

**VERDICT: PASS**
