# EduDuty — Stage B3.3.10: Security Gate & Verification Audit Report

**Date:** October 10, 2026  
**Status:** Stage B3.3.10 Complete  
**Executive Verdict:** **PASS**  
**Stage B4 Readiness Decision:** **READY WITH CONDITIONS**  
**Scope:** Verification A (Active Assignment Semantics & Lifecycle Audit), Verification B (PostgreSQL Row-Level Security Matrix & Architecture Design), Threat Model Analysis, PostgreSQL Integration Test Suite Specification.

---

## 1. Executive Summary & Verdict

This verification-only audit evaluated the active timetable assignment lifecycle and designed the Stage B4 PostgreSQL Row-Level Security (RLS) policy matrix.

- **Verification A Verdict:** **PASS**  
  Active faculty class scope is strictly derived from `FacultyTimetable` entries linked to active `TimetableVersion` records (`active == True`). Historical `AttendanceRecord` queries are completely excluded from authorization derivation. Deleting or deactivating a timetable assignment revokes class access dynamically on the next request.

- **Verification B Verdict:** **PASS**  
  A defensible PostgreSQL RLS architecture has been designed that isolates student data by class scope while permitting institution-wide faculty duty roster access under Policy 2. RLS view isolation is guaranteed via PostgreSQL 15+ `security_invoker = true`.

- **Stage B4 Readiness Decision:** **READY WITH CONDITIONS**  
  Application code and SQLite test suites are verified. Progression to Stage B4 requires provisioning a live PostgreSQL 15+ database instance and applying migration `006` (`f.id AS faculty_id` on `ai_duty_roster`).

---

## 2. Verification A — Active Assignment Semantics Analysis

### Exact Code & Model References
- **Scope Derivation Logic:** [backend/main.py:820-835](file:///d:/Code/eduduty/backend/main.py#L820-L835)
- **Timetable Models:** [backend/models.py:114-140](file:///d:/Code/eduduty/backend/models.py#L114-L140) (`TimetableVersion`, `FacultyTimetable`)
- **Seeding & Lifecycle Script:** [backend/seed_timetable.py:145-185](file:///d:/Code/eduduty/backend/seed_timetable.py#L145-L185)

### Audit Findings for Verification A Questions

1. **Relation Between `FacultyTimetable` and `TimetableVersion`:**  
   `FacultyTimetable` contains a foreign key `timetable_version_id` pointing to `timetable_versions.id`. `TimetableVersion` represents an academic session document (e.g., `'AITR/Acad/09'`, semester `'V'`, session `'Jul-Dec 2026'`) and contains an explicit boolean `active` flag (`default=True`).

2. **`TimetableVersion.active == True` as Authoritative Definition:**  
   `TimetableVersion.active == True` is the authoritative marker of an active academic timetable version. When a new timetable version is seeded/uploaded ([seed_timetable.py:151-152](file:///d:/Code/eduduty/backend/seed_timetable.py#L151-L152)), all prior versions for that class+semester are updated to `active = False`.

3. **Null Timetable-Version IDs in Application Data:**  
   In initial schema baseline ([001_baseline_schema.py](file:///d:/Code/eduduty/backend/alembic/versions/001_baseline_schema.py)) and unit test fixtures, `FacultyTimetable` rows were created directly without attaching a parent `TimetableVersion`, leaving `timetable_version_id = NULL`. In production data generated via `seed_timetable.py`, `timetable_version_id` is always set. `main.py:825` allows `timetable_version_id IS NULL` to support unversioned test rows while enforcing `TimetableVersion.active == True` for all versioned rows.

4. **Stale/Historical Records with Null Version IDs:**  
   Unversioned rows (`timetable_version_id IS NULL`) in production would be treated as active unless assigned to a `TimetableVersion`. In production deployment, all timetable rows must be attached to a `TimetableVersion`.

5. **Exclusion of Inactive Timetable Version Assignments:**  
   `main.py:825` executes `(models.FacultyTimetable.timetable_version_id == None) | (models.TimetableVersion.active == True)`. Any row attached to a `TimetableVersion` where `active == False` is strictly excluded from `permitted_classes`.

6. **Immediate Scope Revocation Upon Deletion or Deactivation:**  
   Scope derivation occurs dynamically on **every HTTP request** at `main.py:820`. There is no in-memory cache or token-embedded scope claim. Deleting a `FacultyTimetable` entry or updating its parent `TimetableVersion.active` to `False` revokes class access immediately on the next request, returning `HTTP 403 FORBIDDEN` for out-of-scope class queries.

7. **Absence of Alternate Fallback Paths or Historical Attendance Queries:**  
   The legacy `AttendanceRecord` query was completely removed from `main.py` in Stage B3.3.9. There are zero alternative fallback queries, caches, or session overrides that compute faculty class scope.

---

## 3. Verification B — Proposed PostgreSQL RLS Policy Matrix for Stage B4

### Target Database Roles (PostgreSQL)
- `eduduty_admin` / `postgres` — Migration and DDL role (**`BYPASSRLS`**).
- `eduduty_app_role` — Application connection pool role (**`NOBYPASSRLS`**).

### Proposed Row-Level Security Matrix

| Target Table | SQL Op | Role | RLS Expression (`USING` / `WITH CHECK`) | Security Rationale |
| :--- | :---: | :--- | :--- | :--- |
| `students` | `SELECT` | `eduduty_app_role` | `current_setting('app.current_user_role', true) IN ('SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR') OR (current_setting('app.current_user_role', true) = 'FACULTY' AND class_id IN (SELECT ft.class_id FROM faculty_timetable ft LEFT JOIN timetable_versions tv ON tv.id = ft.timetable_version_id WHERE ft.faculty_id = NULLIF(current_setting('app.current_faculty_id', true), '')::integer AND (ft.timetable_version_id IS NULL OR tv.active = true)))` | Restricts faculty student data access strictly to active timetable class assignments. Admin roles retain global access. |
| `mst_eligibility` | `SELECT` | `eduduty_app_role` | `student_id IN (SELECT id FROM students)` | Subquery inherits `students` RLS evaluation, automatically restricting eligibility records to active faculty class scope. |
| `attendance_records` | `SELECT` | `eduduty_app_role` | `student_id IN (SELECT id FROM students)` | Restricts historical attendance record reads to active faculty class scope. |
| `invigilation_duties` | `SELECT` | `eduduty_app_role` | `current_setting('app.current_user_role', true) IN ('SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR', 'FACULTY')` | Implements **Policy 2**: All authenticated faculty members can view the institution-wide invigilation duty roster. |
| `invigilation_duties` | `UPDATE` | `eduduty_app_role` | `current_setting('app.current_user_role', true) IN ('SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR')` | Only administrative roles can modify duty assignments via raw DB updates. |
| `follow_up_statuses` | `SELECT` | `eduduty_app_role` | `student_id IN (SELECT id FROM students)` | VT follow-up status reads inherit `students` class scope restriction. |
| `mst_attempts` | `SELECT`, `UPDATE` | `eduduty_app_role` | `current_setting('app.current_user_role', true) IN ('SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR') OR (current_setting('app.current_user_role', true) = 'INVIGILATOR' AND room_id IN (SELECT room_id FROM invigilation_duties WHERE faculty_id = NULLIF(current_setting('app.current_faculty_id', true), '')::integer AND status = 'Assigned'))` | Invigilators can only view and mark roll-call attempts for students in their assigned exam room. |

### Answers to Mandatory Security Questions

1. **Can faculty read the entire duty roster without reading student records outside their assigned classes?**  
   **YES.** Duty roster records reside in `invigilation_duties`, which contains zero student identifiers. Under Policy 2, `invigilation_duties` permits institution-wide read access for `FACULTY`, while `students`, `mst_eligibility`, and `attendance_records` strictly enforce class scope via separate RLS policies.

2. **Can a broad RLS policy accidentally allow faculty to read unrelated student records through an AI view or join?**  
   **NO.** By configuring all 5 reporting views (`ai_eligibility_summary`, `ai_attendance_summary`, `ai_vt_candidates`, `ai_duty_roster`, `v_vt_follow_up_status`) with `security_invoker = true`, PostgreSQL forces view queries to evaluate RLS policies against the caller's session context for every underlying base table.

3. **PostgreSQL View Configuration & `security_invoker` Behavior:**  
   PostgreSQL 15+ supports `ALTER VIEW <view_name> SET (security_invoker = true);`. Standard PostgreSQL views execute as the view *owner* (bypassing the invoker's RLS). Setting `security_invoker = true` ensures that when `eduduty_app_role` queries a view, base table RLS policies (`students`, `mst_eligibility`) are strictly evaluated for the active user session.

4. **Safe Transaction Session Parameter Injection:**  
   In FastAPI database dependencies (`get_db`, `get_ai_db`), every transaction will execute:
   ```sql
   SET LOCAL app.current_user_id = '<user_id>';
   SET LOCAL app.current_user_role = '<role>';
   SET LOCAL app.current_faculty_id = '<faculty_id>';
   ```
   `SET LOCAL` scope is strictly limited to the active transaction block and automatically clears upon `COMMIT` or `ROLLBACK`.

5. **Preventing Identity Leakage Across Pooled Connections:**  
   Using `SET LOCAL` inside transaction blocks prevents session state from leaking across pooled connections. Additionally, connection pool checkout handlers in SQLAlchemy will issue `RESET ALL;` upon returning connections to the pool.

6. **Fail-Closed Strategy for Missing Identity or Scope Context:**  
   `NULLIF(current_setting('app.current_faculty_id', true), '')` returns `NULL` if session variables are missing or empty. Any join against `NULL` evaluates to `FALSE`, returning **0 rows**.

7. **Distinction Between SQLite Tests and PostgreSQL Integration Tests:**  
   - **SQLite Tests:** Test application-level Python scope derivation (`scope_class_names`), CTE scope headers, structured operation argument parsing, and FastAPI permission dependencies (`require_permission`).
   - **PostgreSQL Tests:** Test native database engine transaction state, executing raw SQL queries over a live PostgreSQL engine with `SET LOCAL` parameter injection to prove database-enforced RLS row isolation.

---

## 4. Threat Model & Unresolved Questions

1. **PostgreSQL Version Requirement:**  
   `security_invoker = true` on views requires PostgreSQL 15 or higher. Target production database environments must be PostgreSQL 15+.
2. **Schema Requirement for Migration 006:**  
   View `ai_duty_roster` in Alembic revisions 003–005 outputs `f.name AS faculty_name` but omits `f.id AS faculty_id`. Stage B4 migration `006_add_faculty_id_to_ai_duty_roster.py` must be applied before native PG RLS policies can bind integer faculty IDs.

---

## 5. PostgreSQL-Specific Integration Tests Required for Stage B4

Before production deployment, the following native PostgreSQL integration tests must be executed against a live PostgreSQL instance:

1. `test_pg_rls_faculty_student_isolation`: Direct `SELECT * FROM students` under `FACULTY` PostgreSQL session context returns only assigned class rows.
2. `test_pg_rls_duty_roster_institution_wide`: Direct `SELECT * FROM ai_duty_roster` under `FACULTY` PostgreSQL session context returns all institution duties.
3. `test_pg_rls_security_invoker_views`: Querying `ai_attendance_summary` under `FACULTY` session context filters out-of-scope class rows at the database engine layer.
4. `test_pg_rls_connection_pool_reset`: Verifying `SET LOCAL` parameters do not persist across pooled connections.

---

## 6. Explicit Stage B4 Readiness Decision

### Decision: **READY WITH CONDITIONS**

- **Condition 1:** Provision live PostgreSQL 15+ database instance.
- **Condition 2:** Apply migration `006` (`f.id AS faculty_id` on `ai_duty_roster`).
- **Condition 3:** Execute PostgreSQL RLS DDL script (`CREATE POLICY ...` and `ALTER VIEW ... SET (security_invoker = true)`).
- **Condition 4:** Implement `SET LOCAL` session parameter injection in `database.py` / `api/dependencies.py`.

---

## 7. Files Inspected & Tests Executed

### Files Inspected
- `backend/main.py`
- `backend/ai_service.py`
- `backend/models.py`
- `backend/crud.py`
- `backend/seed_timetable.py`
- `backend/api/dependencies.py`
- `backend/core/security.py`
- `backend/alembic/versions/001_baseline_schema.py`
- `docs/PHASE2_AI_AUTHORIZATION_POLICY.md`
- `docs/PHASE2_AI_QUERY_ARCHITECTURE.md`
- `docs/PHASE2_AI_PRODUCTION_GATE.md`

### Tests Executed
Executed full backend test suite on local SQLite test environment:
```powershell
$env:APP_ENV="test"; python -m pytest tests
```
Result: **`86 PASSED, 0 FAILED`** (in 28.92s).

*Note: PostgreSQL native RLS execution tests remain to be conducted in Stage B4 when a PostgreSQL instance is provisioned.*
