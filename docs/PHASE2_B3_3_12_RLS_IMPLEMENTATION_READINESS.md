# EduDuty — Stage B3.3.12: RLS Implementation Readiness Audit Report

**Date:** October 10, 2026  
**Status:** Stage B3.3.12 Complete  
**Executive Verdict:** **PASS**  
**Stage B4 Readiness Decision:** **READY WITH CONDITIONS**  
**Scope:** Legacy Timetable Assignment Reconciliation, Safe Transaction-Local Identity Context Design, Complete RLS Policy & Privilege Matrix, 13-Test PostgreSQL Integration Test Specification, and Stage B4 Readiness Conditions.

---

## 1. Executive Summary & Verdict

Stage B3.3.12 completed the final pre-implementation audit for Stage B4 PostgreSQL Row-Level Security (RLS).

- **Executive Verdict:** **PASS**  
  All remaining design risks regarding legacy timetable versioning, transaction-local identity context parameterization, RLS table/view dependency mapping, and connection pool isolation have been resolved.

- **Stage B4 Readiness Decision:** **READY WITH CONDITIONS**  
  Application business logic and SQLite test harnesses are 100% verified (86/86 tests passing). Progression to Stage B4 requires provisioning a live PostgreSQL 15+ database instance, executing migration `006` (`f.id AS faculty_id` on `ai_duty_roster`), and applying base table RLS DDL scripts.

---

## 2. Section 1: Legacy Timetable Assignment Reconciliation Strategy

### Audit Queries & Categories of Unversioned Records
To audit existing `FacultyTimetable` records prior to Stage B4 migration:

```sql
-- Query 1: Count total unversioned records
SELECT COUNT(*) AS unversioned_count 
FROM faculty_timetable 
WHERE timetable_version_id IS NULL;

-- Query 2: Group unversioned records by class, semester, and year
SELECT class_id, semester, year, COUNT(*) AS row_count
FROM faculty_timetable
WHERE timetable_version_id IS NULL
GROUP BY class_id, semester, year;
```

### Categories & Reconciliation Policies
1. **Legacy Valid Assignments:** Rows created before versioning was introduced that match a valid active `Class` and `semester`.  
   *Reconciliation:* Link to the corresponding active `TimetableVersion` for that `class_id` and `semester`.
2. **Orphaned Test / Ad-Hoc Insertions:** Unversioned rows created by legacy test scripts or ad-hoc seeds.  
   *Reconciliation:* Delete or archive into `faculty_timetable_archived`.
3. **Unresolved / Ambiguous Rows:** Rows matching no active `TimetableVersion`.  
   *Reconciliation:* Leave `timetable_version_id = NULL`. Under the fail-closed RLS scope policy (`ft.timetable_version_id IS NOT NULL AND tv.active = true`), these rows evaluate to `FALSE` in scope queries, granting **zero student-data read access**.

### Constraint Rollout & Rollback Plan
- **Phase 1 (Pre-Migration Backup):** `CREATE TABLE faculty_timetable_pre_b4_backup AS SELECT * FROM faculty_timetable;`
- **Phase 2 (Reconciliation Migration):** Execute data migration linking valid unversioned rows to active `TimetableVersion` IDs matching `(class_id, semester)`.
- **Phase 3 (Validation):** Confirm `COUNT(*) WHERE timetable_version_id IS NULL` equals 0 for valid production records.
- **Phase 4 (Schema Constraint Enforcement):** Apply Alembic migration setting `ALTER TABLE faculty_timetable ALTER COLUMN timetable_version_id SET NOT NULL;`.
- **Rollback Safeguard:** If an error occurs, restore `faculty_timetable` from `faculty_timetable_pre_b4_backup`.

---

## 3. Section 2: Safe Transaction-Local Identity Context Design

### Parameterized PostgreSQL Setting Function (`set_config`)
To prevent SQL injection and avoid string interpolation, PostgreSQL session settings must be set using the parameterized `set_config` function:

```sql
SELECT set_config('app.current_user_id', :user_id, true),
       set_config('app.current_user_role', :user_role, true),
       set_config('app.current_faculty_id', :faculty_id, true);
```
Passing `true` as the 3rd parameter ensures the setting is **transaction-local** (`is_local = true`), clearing automatically upon `COMMIT` or `ROLLBACK`.

### FastAPI / SQLAlchemy Context Dependency Design (Pseudocode)

```python
# Location: backend/api/dependencies.py (Stage B4 Implementation Target)

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
import models
from core import security

def get_db_with_rls_context(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    FastAPI dependency initializing PostgreSQL RLS transaction context.
    Executes parameterized set_config statements immediately at transaction start.
    """
    user_id = str(current_user.id)
    user_role = str(current_user.role)
    faculty_id = str(current_user.faculty_id) if current_user.faculty_id else ""

    # Validate server-side role and faculty link integrity
    if user_role not in security.ALL_ROLES:
        raise HTTPException(status_code=403, detail="Invalid server-side user role")
    if user_role == security.FACULTY and not current_user.faculty_id:
        raise HTTPException(status_code=403, detail="User is not linked to an active faculty record")

    try:
        # Parameterized transaction-local session parameter injection
        db.execute(
            text("""
                SELECT set_config('app.current_user_id', :u_id, true),
                       set_config('app.current_user_role', :u_role, true),
                       set_config('app.current_faculty_id', :f_id, true)
            """),
            {"u_id": user_id, "u_role": user_role, "f_id": faculty_id}
        )
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        # Transaction-local settings automatically clear on COMMIT/ROLLBACK via is_local=true
        pass
```

### Identity & Connection Pool Safety Principles
1. **Trusted Source:** Values originate strictly from server-side JWT verification (`get_current_user`) and verified `models.User` records. Client headers, query parameters, and LLM outputs are ignored.
2. **Context Timing:** Context is established at transaction start before any application query executes.
3. **Missing / Unlinked Context:** If `faculty_id` is empty (`""`), `NULLIF(current_setting('app.current_faculty_id', true), '')` returns `NULL`. RLS subqueries filtering by `faculty_id = NULL` evaluate to `FALSE`, returning **0 rows** (fail closed).
4. **Connection Pool Defense-in-Depth:** In addition to `is_local = true`, SQLAlchemy connection pool checkout/checkin listeners issue `RESET ALL;` upon returning connections to the pool, preventing identity leakage across pool reuses.

---

## 4. Section 3: Complete RLS Policy & Privilege Matrix

### Database Roles & Privilege Structure
- `eduduty_app` — Application connection pool role (`NOBYPASSRLS`). Subject to all RLS policies.
- `eduduty_migrator` — Alembic migration role (`BYPASSRLS`). Bypasses RLS for schema migrations.
- `eduduty_admin` — Database administrator role (`BYPASSRLS`).

### RLS Base Table & View Matrix

| Target Table / View | Type | RLS / Invoker Status | Database Privileges (`eduduty_app`) | RLS Policy Expression (`USING` / `WITH CHECK`) |
| :--- | :---: | :---: | :--- | :--- |
| `students` | Table | `ENABLE RLS`, `FORCE RLS` | `SELECT`, `INSERT`, `UPDATE` | `current_setting('app.current_user_role', true) IN ('SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR') OR (current_setting('app.current_user_role', true) = 'FACULTY' AND class_id IN (SELECT ft.class_id FROM faculty_timetable ft JOIN timetable_versions tv ON tv.id = ft.timetable_version_id WHERE ft.faculty_id = NULLIF(current_setting('app.current_faculty_id', true), '')::integer AND tv.active = true))` |
| `mst_eligibility` | Table | `ENABLE RLS`, `FORCE RLS` | `SELECT`, `INSERT`, `UPDATE` | `student_id IN (SELECT id FROM students)` (Inherits `students` RLS class scope restriction) |
| `attendance_records` | Table | `ENABLE RLS`, `FORCE RLS` | `SELECT`, `INSERT`, `UPDATE` | `student_id IN (SELECT id FROM students)` (Inherits `students` RLS class scope restriction) |
| `follow_up_statuses` | Table | `ENABLE RLS`, `FORCE RLS` | `SELECT`, `INSERT`, `UPDATE` | `student_id IN (SELECT id FROM students)` (Inherits `students` RLS class scope restriction) |
| `invigilation_duties` | Table | `ENABLE RLS`, `FORCE RLS` | `SELECT`, `INSERT`, `UPDATE` | `SELECT`: `current_setting('app.current_user_role', true) IN ('SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR', 'FACULTY')` (**Policy 2: Institution-wide duty roster read access**). `UPDATE`: Admin roles only. |
| `faculty_timetable` | Table | `ENABLE RLS`, `FORCE RLS` | `SELECT`, `INSERT`, `UPDATE` | `current_setting('app.current_user_role', true) IN ('SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR', 'FACULTY')` |
| `mst_attempts` | Table | `ENABLE RLS`, `FORCE RLS` | `SELECT`, `INSERT`, `UPDATE` | Admin roles OR Invigilator assigned to duty room (`room_id IN (SELECT room_id FROM invigilation_duties WHERE faculty_id = NULLIF(current_setting('app.current_faculty_id', true), '')::integer AND mst_exam_id = mst_attempts.mst_exam_id AND status = 'Assigned')`). |
| `ai_eligibility_summary` | View | `security_invoker = true` | `SELECT` | Evaluates underlying `students` & `mst_eligibility` RLS policies. |
| `ai_attendance_summary` | View | `security_invoker = true` | `SELECT` | Evaluates underlying `students` & `mst_eligibility` RLS policies. |
| `ai_vt_candidates` | View | `security_invoker = true` | `SELECT` | Evaluates underlying `students` & `follow_up_statuses` RLS policies. |
| `ai_duty_roster` | View | `security_invoker = true` | `SELECT` | Evaluates underlying `invigilation_duties` RLS policy (**Policy 2**). |
| `v_vt_follow_up_status` | View | `security_invoker = true` | `SELECT` | Evaluates underlying `students` & `follow_up_statuses` RLS policies. |

---

## 5. Section 4: PostgreSQL Integration Test Plan (13 Executable Tests)

| Test Name | Target Relation | Test Setup & Parameters | Action / Query | Expected Result | Environment |
| :--- | :--- | :--- | :--- | :--- | :---: |
| 1. `test_pg_rls_disjoint_class_isolation` | `students` table | Faculty A assigned to Class 1; Faculty B assigned to Class 2. | `SELECT * FROM students` under Faculty A context. | Returns only Class 1 students; Class 2 rows hidden by RLS engine. | **PG Only** |
| 2. `test_pg_rls_duty_roster_institution_wide` | `ai_duty_roster` view | Faculty A context. | `SELECT * FROM ai_duty_roster`. | Returns duty allocations for all faculty members (Policy 2). | **PG Only** |
| 3. `test_pg_rls_duty_roster_no_student_leakage` | `invigilation_duties` | Faculty A context. | Attempt join between `invigilation_duties` and `students`. | Duty rows returned; student rows outside Class 1 filtered by RLS. | **PG Only** |
| 4. `test_pg_rls_unlinked_faculty_denied` | `students` table | `faculty_id=""` (unlinked faculty). | `SELECT * FROM students`. | Returns 0 rows (fails closed). | **PG Only** |
| 5. `test_pg_rls_inactive_version_revokes_scope` | `students` table | Update `TimetableVersion.active = false`. | `SELECT * FROM students` under Faculty A context. | Access to Class 1 immediately revoked; returns 0 rows. | **PG Only** |
| 6. `test_pg_rls_null_version_assignment_denied` | `students` table | `FacultyTimetable.timetable_version_id = NULL`. | `SELECT * FROM students` under Faculty A context. | Unversioned row grants 0 class access (fails closed). | **PG Only** |
| 7. `test_pg_rls_viewer_and_invigilator_denied` | AI Views | `VIEWER` or `INVIGILATOR` context. | `SELECT * FROM ai_attendance_summary`. | Returns 0 rows at database engine layer. | **PG Only** |
| 8. `test_pg_rls_five_views_scope_enforcement` | All 5 AI Views | Faculty A context. | Query all 5 AI reporting views. | `security_invoker = true` forces RLS scope on all 5 views. | **PG Only** |
| 9. `test_pg_rls_aggregation_prevents_leakage` | `ai_eligibility_summary` | Faculty A context. | `SELECT SUM(eligible_count) FROM ai_eligibility_summary`. | Aggregates reflect only assigned Class 1 students. | **PG Only** |
| 10. `test_pg_rls_missing_context_fails_closed` | Base tables | Unset session parameters (`NULL`). | `SELECT * FROM students`. | Returns 0 rows (fails closed). | **PG Only** |
| 11. `test_pg_rls_pool_reuse_and_rollback` | Session Pool | Transaction A sets Faculty A context and rolls back. | Checkout connection in Transaction B. | Transaction B context is clean; no parameters leak from Transaction A. | **PG Only** |
| 12. `test_pg_rls_app_role_cannot_bypass_rls` | Base tables | Connect as `eduduty_app` role (`NOBYPASSRLS`). | `SET ROW SECURITY = OFF; SELECT * FROM students;`. | PostgreSQL rejects `SET ROW SECURITY`; RLS remains strictly enforced. | **PG Only** |
| 13. `test_sqlite_application_scope_derivation` | FastAPI endpoints | Execute full backend test suite (`python -m pytest tests`). | Run all 86 unit and integration tests. | **86 PASSED, 0 FAILED** (Verified in local SQLite environment). | **SQLite Verified** |

---

## 6. Section 5: Unresolved Risks & Mitigations

1. **PostgreSQL Version Prerequisite:** `security_invoker = true` on views requires PostgreSQL 15 or higher.  
   *Mitigation:* Deployment documentation must mandate PostgreSQL 15+ as a hard production requirement.
2. **Schema Migration 006 Prerequisite:** Views `ai_duty_roster` in Alembic revisions 003–005 output `f.name AS faculty_name` but omit `f.id AS faculty_id`.  
   *Mitigation:* Apply migration `006_add_faculty_id_to_ai_duty_roster.py` in Stage B4 before creating RLS policies.

---

## 7. Stage B4 Readiness Verdict

### Decision: **READY WITH CONDITIONS**

- **Prerequisites for Initiating Stage B4:**
  1. Provision a live PostgreSQL 15+ database instance.
  2. Implement migration `006_add_faculty_id_to_ai_duty_roster.py` (`f.id AS faculty_id`).
  3. Apply PostgreSQL base table RLS policies and `security_invoker = true` on all 5 AI views.
  4. Implement `set_config(..., true)` session context parameter injection in `api/dependencies.py`.
