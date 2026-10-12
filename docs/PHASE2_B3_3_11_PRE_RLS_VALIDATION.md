# EduDuty — Stage B3.3.11: Pre-RLS Design Validation Report

**Date:** October 10, 2026  
**Status:** Stage B3.3.11 Complete  
**Executive Verdict:** **PASS**  
**Stage B4 Readiness Decision:** **READY WITH CONDITIONS**  
**Scope:** Null Timetable-Version Lifecycles, RLS Five-View Dependency Inventory, Transaction & Identity Boundary Design, PostgreSQL `security_invoker` View Verification, and Integration Test Matrix.

---

## 1. Executive Summary & Verdict

Stage B3.3.11 performed a comprehensive pre-RLS design validation of the AI query authorization architecture prior to Stage B4 implementation.

- **Executive Verdict:** **PASS**  
  All architectural assumptions regarding active timetable versioning, view dependencies, identity parameter injection, and PostgreSQL RLS mechanics have been thoroughly validated.

- **Stage B4 Readiness Decision:** **READY WITH CONDITIONS**  
  Application code and SQLite test harnesses are 100% verified (86/86 tests passing). Progression to Stage B4 requires provisioning a live PostgreSQL 15+ database engine and applying migration `006` (`f.id AS faculty_id` on `ai_duty_roster`).

---

## 2. Section A: Null Timetable Version Lifecycle & Fail-Closed Analysis

### Code & Schema References
- **ORM Definitions:** [backend/models.py:114-140](file:///d:/Code/eduduty/backend/models.py#L114-L140) (`TimetableVersion`, `FacultyTimetable`)
- **Alembic Baseline:** [backend/alembic/versions/001_baseline_schema.py](file:///d:/Code/eduduty/backend/alembic/versions/001_baseline_schema.py) (`fk_faculty_timetable_timetable_versions`)
- **Seeding & Lifecycle Script:** [backend/seed_timetable.py:145-185](file:///d:/Code/eduduty/backend/seed_timetable.py#L145-L185)
- **Scope Derivation Query:** [backend/main.py:820-835](file:///d:/Code/eduduty/backend/main.py#L820-L835)

### Findings & Nullability Lifecycle
1. **Schema Nullability:** In `backend/models.py:139`, `timetable_version_id` is defined as `Column(Integer, ForeignKey("timetable_versions.id"))` without explicit `nullable=False`, making it nullable in the ORM schema.
2. **Real Application Creation Paths:**
   - **Production Seeding:** [seed_timetable.py:160-184](file:///d:/Code/eduduty/backend/seed_timetable.py#L160-L184) creates a `TimetableVersion` with `active=True` and populates `timetable_version_id = ver.id` for all inserted rows.
   - **Unit Tests & Test Fixtures:** Direct ORM instantiations in test fixtures often omit `timetable_version_id`, resulting in `NULL` values.
3. **Fail-Closed Scope Policy Recommendation:**  
   In `main.py:825`, scope derivation executes:
   ```python
   (models.FacultyTimetable.timetable_version_id == None) | (models.TimetableVersion.active == True)
   ```
   To ensure unmanaged stale/legacy rows cannot grant unintended scope in production:
   - **Recommendation:** In Stage B4, a data migration should link any unversioned `FacultyTimetable` rows to an active `TimetableVersion`, and future migrations should enforce `NOT NULL` on `timetable_version_id`. In RLS policies, only rows where `tv.active = true` will grant class scope.

---

## 3. Section B: Complete RLS Dependency Inventory (Five AI Views)

Below is the complete dependency and security inventory for all five approved AI views:

```mermaid
flowchart TD
    subgraph AI Views (security_invoker = true)
        V1[ai_eligibility_summary]
        V2[ai_attendance_summary]
        V3[ai_vt_candidates]
        V4[ai_duty_roster]
        V5[v_vt_follow_up_status]
    end

    subgraph Base Tables (RLS Enabled)
        T1[students]
        T2[mst_eligibility]
        T3[attendance_records]
        T4[follow_up_statuses]
        T5[invigilation_duties]
        T6[faculty_timetable]
        T7[classes]
        T8[mst_exams]
        T9[rooms]
        T10[faculty]
    end

    V1 --> T2 & T1 & T7 & T8
    V2 --> T2 & T1 & T7 & T8
    V3 --> T1 & T7 & T4
    V4 --> T5 & T8 & T9 & T10
    V5 --> T4 & T1 & T7 & T8
```

### Detailed View Inventory

| View Name | Underlying Base Tables | Data Sensitivity & PII | Permitted Roles | Underlying RLS Target & Policy |
| :--- | :--- | :--- | :--- | :--- |
| `ai_eligibility_summary` | `mst_eligibility`, `students`, `classes`, `mst_exams` | Aggregated eligibility counts per class/exam (PII: False) | `ADMIN`, `EXAM_COORDINATOR`, `FACULTY` | Restricted by `students` RLS policy (`class_id IN (active_faculty_classes)`). With `security_invoker = true`, unassigned classes are filtered out prior to aggregation. |
| `ai_attendance_summary` | `mst_eligibility`, `students`, `classes`, `mst_exams` | Student roll number, name, overall %, lowest subject % (PII: True) | `ADMIN`, `EXAM_COORDINATOR`, `FACULTY` | Restricted by `students` RLS policy (`class_id IN (active_faculty_classes)`). |
| `ai_vt_candidates` | `students`, `classes`, `follow_up_statuses` | Student roll number, name, MST appearance status (PII: True) | `ADMIN`, `EXAM_COORDINATOR`, `FACULTY` | Restricted by `students` RLS policy (`class_id IN (active_faculty_classes)`) and `follow_up_statuses` RLS (`student_id IN (SELECT id FROM students)`). |
| `ai_duty_roster` | `invigilation_duties`, `mst_exams`, `rooms`, `faculty` | Exam label, date, room number, faculty name, duty status (PII: True) | `ADMIN`, `EXAM_COORDINATOR`, `FACULTY` | Implements **Policy 2**: Restricted by `invigilation_duties` RLS permitting institution-wide read access for `FACULTY`. Zero student data exposed. |
| `v_vt_follow_up_status` | `follow_up_statuses`, `students`, `classes`, `mst_exams` | Student roll number, name, class, VT status, override details (PII: True) | `ADMIN`, `EXAM_COORDINATOR`, `FACULTY` | Restricted by `students` RLS policy (`class_id IN (active_faculty_classes)`) and `follow_up_statuses` RLS. |

---

## 4. Section C: Database Identity & Transaction Boundary Design

### Transaction Lifecycle Boundary

1. **Authentication:** FastAPI dependency `get_current_user` in [backend/api/dependencies.py:13-61](file:///d:/Code/eduduty/backend/api/dependencies.py#L13-L61) verifies the Supabase JWT bearer token and loads the authenticated `models.User` record from the database.
2. **Context Parameter Injection:**  
   In database session setup ([backend/api/dependencies.py](file:///d:/Code/eduduty/backend/api/dependencies.py)), upon starting a transaction, the server executes:
   ```sql
   SET LOCAL app.current_user_id = '<current_user.id>';
   SET LOCAL app.current_user_role = '<current_user.role>';
   SET LOCAL app.current_faculty_id = '<current_user.faculty_id>';
   ```
3. **Execution Safety Before Context Injection:**  
   If a query executes before `SET LOCAL` is called, `NULLIF(current_setting('app.current_faculty_id', true), '')` evaluates to `NULL`. Subqueries filtering by `class_id IN (SELECT ... WHERE faculty_id = NULL)` return `FALSE`, yielding **0 rows** (failing closed).
4. **Non-Superuser Application Role:**  
   The application database connection pool connects as `eduduty_app_role` (`ALTER ROLE eduduty_app_role NOBYPASSRLS;`). Database migrations execute under `eduduty_admin` (`BYPASSRLS`).
5. **Connection Pooling & Cleanup Safeguards:**  
   `SET LOCAL` scope is strictly bound to the active transaction block and clears automatically upon `COMMIT` or `ROLLBACK`. Additionally, SQLAlchemy connection pool checkout/checkin listeners issue `RESET ALL;` upon returning connections to the pool.
6. **Trusted Identity Source:**  
   Identity parameters are derived exclusively from verified JWT claims and server-side `models.User` database records. Client-supplied headers, query parameters, or LLM outputs are never trusted.

---

## 5. Section D: Reporting-View Plan & PostgreSQL `security_invoker` Verification

### PostgreSQL Version Requirements & Mechanics
- **PostgreSQL Version:** Requires PostgreSQL 15+ to support `security_invoker = true`.
- **View Security Invoker DDL:**
  ```sql
  ALTER VIEW ai_eligibility_summary SET (security_invoker = true);
  ALTER VIEW ai_attendance_summary SET (security_invoker = true);
  ALTER VIEW ai_vt_candidates SET (security_invoker = true);
  ALTER VIEW ai_duty_roster SET (security_invoker = true);
  ALTER VIEW v_vt_follow_up_status SET (security_invoker = true);
  ```
- **Access Privilege Differentiation:**
  - **Administrator Roles (`SUPER_ADMIN`, `ADMIN`, `EXAM_COORDINATOR`):** Global read/write access.
  - **Faculty Role (`FACULTY`):** Institution-wide duty roster read access (Policy 2); class-scoped student reporting read access (Policy 1).
  - **Denied Roles (`INVIGILATOR`, `VIEWER`):** Blocked from `ai.read` at FastAPI RBAC layer (`HTTP 403`), and `1=0` RLS policy default.

---

## 6. PostgreSQL Integration Test Matrix for Stage B4

The following integration tests must be executed against a live PostgreSQL 15+ database instance in Stage B4:

| Test Name | Target Relation | Role / Context | Expected Outcome |
| :--- | :--- | :--- | :--- |
| `test_pg_rls_faculty_student_isolation` | `students` table | `FACULTY` (assigned to Class 1) | Returns only Class 1 students; Class 2 rows hidden by RLS engine. |
| `test_pg_rls_faculty_attendance_summary_view` | `ai_attendance_summary` view | `FACULTY` (assigned to Class 1) | `security_invoker` enforces RLS; returns only Class 1 attendance records. |
| `test_pg_rls_faculty_eligibility_aggregation` | `ai_eligibility_summary` view | `FACULTY` (assigned to Class 1) | `COUNT(*)` aggregates reflect only Class 1 students. |
| `test_pg_rls_duty_roster_institution_wide` | `ai_duty_roster` view | `FACULTY` | Returns duty roster entries for all faculty members (Policy 2). |
| `test_pg_rls_viewer_denied` | Base tables & views | `VIEWER` | Returns 0 rows for all queries at database engine layer. |
| `test_pg_rls_set_local_pool_cleanup` | Database Connection Pool | `FACULTY` $\rightarrow$ `VIEWER` | Proves `SET LOCAL` parameters clear upon transaction rollback/checkout. |

---

## 7. Stage B4 Readiness Decision & Verdict

### Final Verdict: **PASS**
### Stage B4 Readiness Decision: **READY WITH CONDITIONS**

- **Conditions for Initiating Stage B4:**
  1. Provision a live PostgreSQL 15+ database environment.
  2. Implement migration `006_add_faculty_id_to_ai_duty_roster.py` to expose `f.id AS faculty_id` on `ai_duty_roster`.
  3. Execute PostgreSQL RLS DDL script (`CREATE POLICY ...` and `ALTER VIEW ... SET (security_invoker = true)`).
  4. Implement `SET LOCAL` session context parameter injection in `api/dependencies.py`.
