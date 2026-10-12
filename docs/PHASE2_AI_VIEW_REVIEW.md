# EduDuty — Stage B3.1: AI View Correctness & Privacy Gate Review Report

**Date:** October 10, 2026  
**Status:** Stage B3.1 Complete  
**Scope:** Independent Review of AI Reporting Views, Semantic Corrections, Privacy Audit, Authorization Scoping, and Alembic Revision `004_fix_ai_views`  
**New Revision ID:** `004_fix_ai_views` (Revises `003_add_ai_views`)  
**Test Suite Verdict:** **`55 PASSED, 0 FAILED`**

---

## 1. Actual AI Query Consumers

The AI read pipeline (`backend/ai_service.py`) routes natural language questions to read-only SQL queries via `_llm_chat()` and `_validate_read_sql()`. The system prompt (`READ_SYSTEM_PROMPT`) restricts queries exclusively to 5 approved views:

1. **`ai_eligibility_summary`**: Consumed for class-level exam eligibility count questions (e.g. *"How many CI-1 students are eligible for MST-1?"*).
2. **`ai_attendance_summary`**: Consumed for student attendance percentage and borderline identification queries (e.g. *"List borderline students in CI-2"*).
3. **`ai_vt_candidates`**: Consumed for candidate lookup based on MST-1 & MST-2 appearance status (e.g. *"Show VT candidates in CS-81"*).
4. **`ai_duty_roster`**: Consumed for invigilation schedule queries (e.g. *"Which faculty is assigned to R-101 for MST-1?"*).
5. **`v_vt_follow_up_status`**: Consumed for VT decision and override tracking queries (e.g. *"Which compulsory VT students have been excused?"*).

---

## 2. Confirmed Semantic Defects & Evidence

During the independent audit of revision `003_add_ai_views`, three critical semantic defects were identified:

### Defect 1: Uncounted `'Borderline'` & `'conditionally_eligible'` Statuses (`ai_eligibility_summary`)
- **Evidence:** `003_add_ai_views.py` defined `eligible_count`, `ineligible_count`, and `missing_count`. `crud.py:93-94` and `models.py` explicitly generate and store `'Borderline'` and `'conditionally_eligible'` status values for attendance between 45% and 49.99%.
- **Impact:** Students with `'Borderline'` or `'conditionally_eligible'` statuses were silently omitted from eligibility count queries, causing summary totals to misrepresent class statistics.
- **Correction:** Added explicit `borderline_count` column (`COUNT(CASE WHEN LOWER(el.status) IN ('borderline', 'conditionally_eligible') THEN 1 END)`).

### Defect 2: String Lexicographical `MAX()` Aggregation Over Attempts (`ai_vt_candidates`)
- **Evidence:** `003_add_ai_views.py` used `MAX(CASE WHEN me.label = 'MST-1' THEN ma.status END)` over raw `mst_attempts` table statuses.
- **Impact:** Statuses like `'Present'`, `'Absent'`, `'Late'`, `'Signature missing'` were aggregated lexicographically (`'Signature missing' > 'Present' > 'Late'`), which is a meaningless alphabetical order rather than a domain rule. Furthermore, `crud.py:218-315` maintains the canonical VT decision engine in `follow_up_statuses` (`mst_1_appeared` and `mst_2_appeared` booleans).
- **Correction:** Re-anchored `ai_vt_candidates` directly to `follow_up_statuses`, using canonical logic: `CASE WHEN fs.mst_1_appeared IS NULL THEN 'Missing' WHEN fs.mst_1_appeared THEN 'Present' ELSE 'Absent' END`.

### Defect 3: Row Duplication Across Multiple Exams (`ai_attendance_summary`)
- **Evidence:** Joining `mst_eligibility` without filtering by exam or grouping by student returned duplicate rows for students with eligibility records across both MST-1 and MST-2.
- **Impact:** Querying `ai_attendance_summary` returned duplicate student entries.
- **Correction:** Grouped by `(c.name, s.roll_number, s.name)` with `MAX(el.overall_pct)` and `MIN(el.lowest_subject_pct)`.

---

## 3. Status Classification & Exam Label Rules

| Entity / Field | System Values | Classification & Business Logic in Revision `004_fix_ai_views` |
| :--- | :--- | :--- |
| **`MstEligibility.status`** | `'Eligible'`, `'Borderline'`, `'conditionally_eligible'`, `'Not eligible'`, `'ineligible'`, `'Missing'` | - `eligible_count`: `LOWER(status) = 'eligible'`<br>- `borderline_count`: `LOWER(status) IN ('borderline', 'conditionally_eligible')`<br>- `ineligible_count`: `LOWER(status) IN ('not eligible', 'ineligible')`<br>- `missing_count`: `LOWER(status) = 'missing'` |
| **`FollowUpStatus` Appearance** | `True` (Present), `False` (Absent), `None` (Missing) | - `mst1_status`: `True` -> `'Present'`, `False` -> `'Absent'`, `None` -> `'Missing'`<br>- `mst2_status`: `True` -> `'Present'`, `False` -> `'Absent'`, `None` -> `'Missing'` |
| **Exam Labels** | `'MST-1'`, `'MST-2'` | Scoped dynamically via class foreign key `follow_up_statuses.mst_1_exam_id` and `mst_2_exam_id` rather than hardcoded string pattern matching. |

---

## 4. Column-Level Privacy Assessment

| View Name | Exposed Columns | PII Exposed? | Privacy Minimization Justification |
| :--- | :--- | :---: | :--- |
| `ai_eligibility_summary` | `class_name`, `mst_label`, `eligible_count`, `borderline_count`, `ineligible_count`, `missing_count` | **No** | 100% aggregated counts. Zero personal student identifiers. |
| `ai_attendance_summary` | `class_name`, `roll_number`, `student_name`, `overall_pct`, `lowest_subject_pct` | **Yes** (`roll_number`, `student_name`) | Required for exam coordinator outreach to borderline/ineligible students. Excludes upload file names and raw attendance dates. |
| `ai_vt_candidates` | `class_name`, `roll_number`, `student_name`, `mst1_status`, `mst2_status` | **Yes** (`roll_number`, `student_name`) | Required for VT candidate list generation. Excludes seating assignments and marks. |
| `ai_duty_roster` | `mst_label`, `exam_date`, `room_number`, `faculty_name`, `duty_status` | **Yes** (`faculty_name`) | Required for invigilation roster verification. Excludes faculty phone/email, department exemption reasons, and daily limits. |
| `v_vt_follow_up_status` | `roll_number`, `student_name`, `class_name`, `mst_1_label`, `mst_2_label`, `mst_1_appeared`, `mst_2_appeared`, `calculated_status`, `final_status`, `overridden`, `override_reason`, `rule_version`, `updated_at` | **Yes** (`roll_number`, `student_name`) | Required for VT status review. Excludes `override_by` staff user IDs. |

---

## 5. Authorization & Scope Findings

- **View Allowlist Security:** The SQL validator in `backend/ai_service.py` (`_validate_read_sql`) rejects all queries referencing base tables (`students`, `users`, `classes`, etc.), multi-statement injection attempts, and DDL/DML keywords (`INSERT`, `UPDATE`, `DELETE`, `DROP`).
- **Database Read Isolation:** All AI read queries execute over `AIReaderSessionLocal()`, which enforces `PRAGMA query_only = ON;` in SQLite and read-only sessions in PostgreSQL.
- **Unresolved Policy Decision (Row-Level Authorization Scoping):**
  - **Finding:** A user with `ai.read` permission (e.g. a Faculty member or Exam Coordinator) can query all rows exposed by the 5 database views.
  - **Gap:** The database view allowlist restricts *which entities* can be queried, but does *not* filter rows by department or class scope.
  - **Recommendation before Production:** Enforce tenant/departmental row scoping at the application layer or via parameterized view filters prior to production deployment.

---

## 6. Alembic Revision `004_fix_ai_views` Summary

Revision `004_fix_ai_views` (parent: `003_add_ai_views`) updates all 5 database views:
1. Re-creates `ai_eligibility_summary` with `borderline_count`.
2. Re-creates `ai_attendance_summary` with student `GROUP BY` to eliminate join duplication.
3. Re-creates `ai_vt_candidates` re-anchored to `follow_up_statuses`.
4. Re-creates `ai_duty_roster` and `v_vt_follow_up_status`.
5. Includes full downgrade path reverting view DDL to revision `003` definitions.

---

## 7. Automated Test Results & Verification

- **Total Backend Tests:** **55 Passed, 0 Failed, 0 Skipped** (in 6.51s).
- **Stage B3.1 Tests (`test_alembic_b31_review.py`):**
  - `test_b31_eligibility_status_classification`: Validated status counts for `Eligible`, `Borderline`, `conditionally_eligible`, `Not eligible`, `Missing`.
  - `test_b31_vt_candidates_canonical_follow_up_integration`: Validated `ai_vt_candidates` integration with `follow_up_statuses`.
  - `test_b31_migration_003_to_004_upgrade_downgrade`: Validated migration `003` -> `004` upgrade, view results, downgrade to `003`, and re-upgrade.
- **Database Safety:** `eduduty.db` modification timestamp confirmed unchanged.
- **PostgreSQL Status:** Unverified locally on a live PostgreSQL instance. View DDL uses standard portable ANSI SQL.

---

## 8. Stop Condition & Next Steps

Stage B3.1 is complete. Stage B4 (PostgreSQL production deployment controls) has **not** been started.

**Awaiting review before proceeding to Stage B4.**
