# EduDuty — Phase 1 Endpoint Security Matrix

**Date:** October 10, 2026  
**Status:** Verification Baseline  
**Scope:** Complete inventory of all 45 FastAPI backend endpoints in `backend/main.py` and `backend/api/dependencies.py`.

---

## 1. Executive Summary

| Total Endpoints | Protected (Auth + RBAC) | Public / Unprotected | Resource-Level Checks Present | Compliance Status |
| :---: | :---: | :---: | :---: | :---: |
| **45** | **42** | **3** (`/`, `/health`, `/ai/health`) | **6 Key Endpoints Enforced** | **Remediation Active** |

- **Authentication & RBAC:** All 42 operational endpoints require `get_current_user` authentication via the `require_permission(...)` dependency factory.
- **Resource-Level Authorization:** Enforced on key sensitive operations including attendance marking, roll-call, student PDF/HTML exports, seating chart PDFs, and AI-proposed write executions.
- **Public Endpoints:** Root (`/`), Health Check (`/health`), and AI Health (`/ai/health`) are publicly accessible without authentication.

---

## 2. Complete Endpoint Inventory Matrix

| # | HTTP Method | Endpoint Path | Authentication Requirement | Required Permission | Resource-Level Check | Security Notes / Risk Assessment |
| :-: | :--- | :--- | :--- | :--- | :---: | :--- |
| 1 | `GET` | `/` | None | None | None | Public welcome message. Safe. |
| 2 | `GET` | `/health` | None | None | None | Public system status check. Safe. |
| 3 | `POST` | `/upload-attendance/` | `get_current_user` | `attendance.import` | Enforced | **Remediated (SEC-05):** 10 MiB streaming size cap (HTTP 413), XLS/XLSX magic bytes check, dimensions bounds, & transaction rollback. |
| 4 | `GET` | `/dashboard/stats` | `get_current_user` | `reports.read` | None | Aggregates system metrics. Safe coarse-grained read. |
| 5 | `GET` | `/eligibility/{mst_exam_id}` | `get_current_user` | `eligibility.read` | None | Coarse RBAC enforced. No class/dept scope check. |
| 6 | `POST` | `/eligibility/override/{eligibility_id}` | `get_current_user` | `eligibility.override` | None | Uses `current_user.id` for audit log actor. |
| 7 | `POST` | `/ai/query` | `get_current_user` | `ai.read` | Enforced | **Remediated (SEC-04):** Isolated read-only engine (`ai_reader`), session read-only mode, view allow-list, & multi-statement rejection. |
| 8 | `POST` | `/ai/confirm-write` | `get_current_user` | `ai.write` | Enforced | **Remediated:** Exact roll matching, invigilator room check, & duty conflict validation. |
| 9 | `GET` | `/pdf/student/{roll_number}` | `get_current_user` | `reports.read` | Enforced | **Remediated:** IDOR protected via `verify_faculty_student_access`. |
| 10 | `GET` | `/pdf/seating/{mst_exam_id}/{room_id}` | `get_current_user` | `reports.read` | Enforced | **Remediated:** Room duty assignment scope checked via `verify_invigilator_room_assignment`. |
| 11 | `GET` | `/pdf/student/{roll_number}/html` | `get_current_user` | `reports.read` | Enforced | **Remediated:** IDOR protected via `verify_faculty_student_access`. |
| 12 | `POST` | `/timetable/version` | `get_current_user` | `faculty.manage` | None | Timetable versioning. |
| 13 | `POST` | `/timetable/entry` | `get_current_user` | `faculty.manage` | None | Timetable single entry creation. |
| 14 | `POST` | `/timetable/entries/bulk` | `get_current_user` | `faculty.manage` | None | Bulk timetable entries creation. |
| 15 | `GET` | `/timetable/class/{class_id}` | `get_current_user` | `faculty.read` | None | Class timetable lookup. |
| 16 | `POST` | `/timetable/availability` | `get_current_user` | `faculty.read` | None | Faculty availability check. |
| 17 | `GET` | `/classes` | `get_current_user` | `faculty.read` | None | Lists all classes. |
| 18 | `GET` | `/faculty` | `get_current_user` | `faculty.read` | None | Lists all faculty records. |
| 19 | `POST` | `/faculty` | `get_current_user` | `faculty.manage` | None | Creates faculty record. |
| 20 | `PATCH` | `/faculty/{faculty_id}` | `get_current_user` | `faculty.manage` | None | Updates faculty record. |
| 21 | `POST` | `/classes` | `get_current_user` | `faculty.manage` | None | Creates class record. |
| 22 | `GET` | `/mst/exams` | `get_current_user` | `exam.read` | None | Lists MST exams. |
| 23 | `POST` | `/mst/exams` | `get_current_user` | `exam.create` | None | Creates MST exam. |
| 24 | `GET` | `/rooms` | `get_current_user` | `seating.read` | None | Lists rooms. |
| 25 | `POST` | `/rooms` | `get_current_user` | `seating.manage` | None | Creates room record. |
| 26 | `POST` | `/mst/seating/generate` | `get_current_user` | `seating.generate` | None | Generates seating plan. |
| 27 | `GET` | `/mst/seating/{mst_exam_id}` | `get_current_user` | `seating.read` | None | Retrieves seating plan. |
| 28 | `POST` | `/mst/attendance/mark` | `get_current_user` | `attendance.mark` | Enforced | **Remediated:** Invigilator room assignment verified via `verify_invigilator_room_assignment`. |
| 29 | `GET` | `/mst/attendance/{mst_exam_id}` | `get_current_user` | `attendance.read` | None | Retrieves exam attempt records. |
| 30 | `GET` | `/follow-up` | `get_current_user` | `vt.read` | None | Lists VT follow-up cases. |
| 31 | `GET` | `/follow-up/stats` | `get_current_user` | `vt.read` | None | Aggregates VT stats. |
| 32 | `POST` | `/follow-up/recalculate` | `get_current_user` | `vt.override` | None | Recalculates VT follow-ups. |
| 33 | `POST` | `/follow-up/{follow_up_id}/override` | `get_current_user` | `vt.override` | None | Uses `current_user.id` as actor. Ignores body `changed_by`. |
| 34 | `POST` | `/follow-up/{follow_up_id}/restore` | `get_current_user` | `vt.override` | None | Restores VT rule calculation. |
| 35 | `GET` | `/follow-up/export` | `get_current_user` | `reports.export` | None | Exports compulsory VT list (Excel). |
| 36 | `GET` | `/follow-up/export-pdf` | `get_current_user` | `reports.export` | None | Exports compulsory VT list (PDF). |
| 37 | `GET` | `/mst/duties/{mst_exam_id}` | `get_current_user` | `duty.read` | None | Lists invigilation duties. |
| 38 | `POST` | `/mst/duties/assign` | `get_current_user` | `duty.assign` | None | Manually assigns duty slot. |
| 39 | `POST` | `/mst/duties/unassign/{duty_id}` | `get_current_user` | `duty.assign` | None | Unassigns duty slot. |
| 40 | `POST` | `/mst/duties/auto-schedule` | `get_current_user` | `duty.generate` | None | Generates duty proposal. |
| 41 | `POST` | `/mst/duties/auto-schedule/apply` | `get_current_user` | `duty.assign` | None | Applies proposed duties using `current_user.id`. |
| 42 | `GET` | `/mst/faculty-status` | `get_current_user` | `duty.read` | None | Checks faculty availability for exam slot. |
| 43 | `GET` | `/mst/faculty-grid` | `get_current_user` | `duty.read` | None | Returns full free/busy faculty grid. |
| 44 | `GET` | `/mst/attendance/rollcall/{mst_exam_id}` | `get_current_user` | `attendance.read` | Enforced | **Remediated:** Invigilator room assignment verified via `verify_invigilator_room_assignment`. |
| 45 | `GET` | `/ai/health` | None | None | None | Public AI health provider check. |


---

## 3. High-Priority Endpoint Vulnerability Summary

1. **JWT Verification Flaw (P0):** `backend/core/security.py` falls back to unverified signature decoding when `SUPABASE_JWT_SECRET` is missing/short, skips `aud` verification (`verify_aud: False`), lacks `iss` verification, and incorrectly falls back to `SUPABASE_ANON_KEY` as a secret.
2. **Missing Resource-Level Authorization (P1):** Endpoints such as `POST /mst/attendance/mark` and `GET /pdf/student/{roll_number}` verify global role permissions (`attendance.mark`, `reports.export`) but do not verify student, room, or assigned invigilator boundaries.
3. **Uncapped File Upload Memory Consumption (P1):** `POST /upload-attendance/` reads the full file into memory (`await file.read()`) without an explicit size cap (e.g. 10 MB limit).
4. **AI Connection Isolation & Fuzzy Matching (P1):** `POST /ai/query` executes AI SQL on the main read-write database connection. `POST /ai/confirm-write` uses `ilike` substring search for roll numbers and bypasses duty availability constraints.
