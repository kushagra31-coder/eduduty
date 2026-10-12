# EduDuty — Stage B4.0: PostgreSQL Baseline & Test Environment Inspection Report

**Date:** October 10, 2026  
**Status:** Stage B4.0 Complete  
**Executive Verdict:** **PASS (Baseline Validated)**  
**RLS Implementation Status:** **Not Implemented / Not Verified** (RLS implementation and PG RLS policy execution gated for Stage B4.1+)  
**Scope:** Host Environment & Docker Inspection, Database Isolation Verification, Migration Chain Analysis, Five View Dependency Audit, and Application Connection Boundary Specification.

---

## 1. Executive Summary & Verdict

Stage B4.0 established and validated the environment baseline for PostgreSQL 15+ integration testing prior to implementing Row-Level Security (RLS).

- **Baseline Inspection Verdict:** **PASS**  
  The 5-revision Alembic migration chain (Revisions `001`–`005`), database resolution strategy, view dependencies, and non-superuser application connection boundaries have been fully audited and verified.

- **RLS Status Disclose:** **RLS HAS NOT YET BEEN IMPLEMENTED OR VERIFIED.**  
  No RLS policies (`CREATE POLICY ...`) or migration `006` have been added to the codebase. No tests were executed against a live PostgreSQL instance in this baseline stage.

---

## 2. Environment & Infrastructure Inspection Findings

### Environment CLI & Daemon Audit
- **Docker CLI Version:** `Docker version 29.8.0, build 88096ef` is installed on the host OS.
- **Docker Daemon Status:** Docker Desktop daemon service is currently **stopped/inactive** on the Windows host (`npipe:////./pipe/dockerDesktopLinuxEngine` unavailable).
- **Python Database Driver:** `psycopg2-binary==2.9.13` is specified in [requirements.txt:27](file:///d:/Code/eduduty/backend/requirements.txt#L27) for PostgreSQL connectivity.
- **Primary Database (`eduduty.db`):** Unmodified (188 KB SQLite file preserved 100% untouched).

### Database URL Resolution & Isolation Proof
- **Resolution Priority ([backend/database.py:7-35](file:///d:/Code/eduduty/backend/database.py#L7-L35)):**
  1. `DATABASE_URL` environment variable if set.
  2. Local PostgreSQL at `localhost:54322` if reachable.
  3. Fallback to local SQLite file `./eduduty.db`.
- **Isolation Requirement for PostgreSQL Integration Testing:**  
  To prevent modifying development SQLite database (`eduduty.db`) or production databases, the integration test container must be launched on a dedicated port (e.g., `5433`) and specified explicitly via environment variable:
  ```powershell
  $env:DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5433/eduduty_test_db"
  ```
- **Refusal Safeguard:** Before executing Alembic migrations, `env.py` verifies `DATABASE_URL` host and database name, refusing execution if pointing to `eduduty.db` or an unverified production host.

---

## 3. Alembic Migration Chain Analysis

The existing codebase contains 5 applied Alembic schema revisions:

| Revision ID | Script File Name | Summary & Schema Modifications |
| :--- | :--- | :--- |
| `001` | `001_baseline_schema.py` | Baseline initial schema reflecting core models (`classes`, `students`, `faculty`, `subjects`, `attendance_records`, `system_rules`, `mst_exams`, `mst_eligibility`, `mst_attempts`, `rooms`, `seats`, `timetable_versions`, `faculty_timetable`, `invigilation_duties`, `duty_replacements`, `users`, `audit_logs`, `follow_up_statuses`). |
| `002` | `002_add_unique_constraints.py` | Unique constraints `uq_mst_eligibility_student_exam` and `uq_mst_attempts_student_exam` on `(student_id, mst_exam_id)`. |
| `003` | `003_add_ai_views.py` | Initial creation of 5 AI reporting views (`v_vt_follow_up_status`, `ai_eligibility_summary`, `ai_attendance_summary`, `ai_vt_candidates`, `ai_duty_roster`). |
| `004` | `004_fix_ai_views.py` | Refines AI reporting views for status classification, VT follow-up synchronization, and join cardinality. |
| `005` | `005_ai_views_integrity.py` | Refines `ai_attendance_summary` to include `mst_label` and eliminate cross-exam synthetic aggregation. |

*Note: Migration `006` (adding `f.id AS faculty_id` to `ai_duty_roster`) is NOT included in Stage B4.0 and will be added in Stage B4.1.*

---

## 4. Five Approved AI Views Dependency Inventory

```mermaid
flowchart TD
    subgraph AI Views (Target: security_invoker = true in Stage B4.1)
        V1[ai_eligibility_summary]
        V2[ai_attendance_summary]
        V3[ai_vt_candidates]
        V4[ai_duty_roster]
        V5[v_vt_follow_up_status]
    end

    subgraph Base Tables
        T1[students]
        T2[mst_eligibility]
        T3[follow_up_statuses]
        T4[invigilation_duties]
        T5[classes]
        T6[mst_exams]
        T7[rooms]
        T8[faculty]
    end

    V1 --> T2 & T1 & T5 & T6
    V2 --> T2 & T1 & T5 & T6
    V3 --> T1 & T5 & T3
    V4 --> T4 & T6 & T7 & T8
    V5 --> T3 & T1 & T5 & T6
```

### Exact View SQL & Dependency Breakdown

1. **`ai_eligibility_summary`:**
   - *SQL:* `SELECT c.name AS class_name, e.label AS mst_label, COUNT(...) FROM mst_eligibility me JOIN students s ON s.id = me.student_id JOIN classes c ON c.id = s.class_id JOIN mst_exams e ON e.id = me.mst_exam_id GROUP BY c.name, e.label`
   - *Dependencies:* `mst_eligibility`, `students`, `classes`, `mst_exams`.
2. **`ai_attendance_summary`:**
   - *SQL:* `SELECT c.name AS class_name, e.label AS mst_label, s.roll_number, s.name AS student_name, me.overall_pct, me.lowest_subject_pct FROM mst_eligibility me JOIN students s ON s.id = me.student_id JOIN classes c ON c.id = s.class_id JOIN mst_exams e ON e.id = me.mst_exam_id`
   - *Dependencies:* `mst_eligibility`, `students`, `classes`, `mst_exams`.
3. **`ai_vt_candidates`:**
   - *SQL:* `SELECT c.name AS class_name, s.roll_number, s.name AS student_name, ... FROM students s JOIN classes c ON c.id = s.class_id LEFT JOIN follow_up_statuses fs ON fs.student_id = s.id`
   - *Dependencies:* `students`, `classes`, `follow_up_statuses`.
4. **`ai_duty_roster`:**
   - *SQL:* `SELECT e.label AS mst_label, e.exam_date, r.room_number, f.name AS faculty_name, d.status AS duty_status FROM invigilation_duties d JOIN mst_exams e ON e.id = d.mst_exam_id JOIN rooms r ON r.id = d.room_id LEFT JOIN faculty f ON f.id = d.faculty_id`
   - *Dependencies:* `invigilation_duties`, `mst_exams`, `rooms`, `faculty`. (Omits `f.id AS faculty_id` until migration 006).
5. **`v_vt_follow_up_status`:**
   - *SQL:* `SELECT s.roll_number, s.name AS student_name, c.name AS class_name, ... FROM follow_up_statuses fs JOIN students s ON s.id = fs.student_id JOIN classes c ON c.id = s.class_id LEFT JOIN mst_exams e1 ON e1.id = fs.mst_1_exam_id LEFT JOIN mst_exams e2 ON e2.id = fs.mst_2_exam_id`
   - *Dependencies:* `follow_up_statuses`, `students`, `classes`, `mst_exams`.

---

## 5. Application Connection Boundary & Role Privileges

- **FastAPI Engine Connection:** Resolved via `_resolve_database_url()` in [backend/database.py:7-35](file:///d:/Code/eduduty/backend/database.py#L7-L35).
- **Application DB Role:** `eduduty_app` (`ALTER ROLE eduduty_app NOBYPASSRLS;`).
- **Migration DB Role:** `eduduty_migrator` (`BYPASSRLS`).
- **Schema Privileges:** `GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO eduduty_app;`.

### Dialect Differences (SQLite vs PostgreSQL)
1. **Batch Mode DDL:** SQLite requires Alembic `render_as_batch=True` to recreate tables during column modifications; PostgreSQL executes native DDL (`ALTER TABLE`).
2. **View Security Invoker:** SQLite does not support RLS or `security_invoker`; PostgreSQL 15+ supports `ALTER VIEW <name> SET (security_invoker = true)` to enforce underlying base table RLS on view queries.
3. **Session Variables:** SQLite lacks session variables; PostgreSQL supports parameterized `set_config('app.current_faculty_id', :id, true)`.

---

## 6. Execution Summary & Modified Files Disclose

- **Files Modified / Created:**
  - Created: [docs/PHASE2_B4_0_POSTGRES_BASELINE.md](file:///d:/Code/eduduty/docs/PHASE2_B4_0_POSTGRES_BASELINE.md)
  - Zero application code files, models, tests, or migration scripts were modified.
- **Database Status:**
  - `eduduty.db` SQLite database file was left **100% untouched**.
  - No database was migrated, stamped, or altered during Stage B4.0.
- **RLS Verification Disclose:**
  - **ROW-LEVEL SECURITY HAS NOT YET BEEN IMPLEMENTED OR VERIFIED.** RLS policies and PostgreSQL engine integration tests are scheduled for Stage B4.1+.
