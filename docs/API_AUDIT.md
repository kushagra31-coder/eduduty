# EduDuty — API Audit & Endpoint Specifications

**Date:** October 6, 2026  
**Status:** Complete  
**Scope:** Backend Endpoint Inventory, Route Structure, Validation & Response Formats  

---

## 1. Existing Endpoint Inventory

The current FastAPI backend (`backend/main.py`) exposes the following endpoints:

| Method | Endpoint Path | Summary / Description | Authorization Check | Data Validation | Response Format |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET` | `/` | Root status message | None | N/A | `{"message": "..."}` |
| `POST` | `/upload-attendance/` | Uploads Excel workbook and parses per-subject sheets | None | File extension check | `{"filename": "...", "rows_imported": N}` |
| `GET` | `/dashboard/stats` | Aggregated dashboard statistics & recent activity | None | N/A | JSON Object |
| `GET` | `/eligibility/{mst_exam_id}` | Lists student eligibility records for exam | None | Path parameter | Array of `MstEligibilityDisplay` |
| `POST` | `/eligibility/override/{eligibility_id}` | Applies human override to eligibility record | None | Body validation | `{"message": "..."}` |
| `POST` | `/ai/query` | Natural language AI routing (Read / Write Proposal / PDF) | None | `AIMessageRequest` Pydantic | `{"type": "...", "content": ...}` |
| `POST` | `/ai/confirm-write` | Executes an explicit AI write proposal | None | `WriteConfirmRequest` Pydantic | `{"success": true, "changed": ...}` |
| `GET` | `/ai/health` | Provider health status check | None | N/A | `{"ready": true, "providers": [...]}` |
| `GET` | `/pdf/student/{roll_number}` | Generates formal PDF student record | None | Path parameter | `application/pdf` binary stream |
| `GET` | `/pdf/seating/{mst_exam_id}/{room_id}` | Generates seating chart PDF | None | Path parameter | `application/pdf` binary stream |
| `GET` | `/pdf/student/{roll_number}/html` | Debug HTML view of student record | None | Path parameter | `text/html` |
| `POST` | `/timetable/version` | Creates a new timetable version | None | `TimetableVersionCreate` | `TimetableVersionOut` |
| `POST` | `/timetable/entry` | Creates a single timetable entry | None | `TimetableEntryCreate` | `TimetableEntryOut` |
| `POST` | `/timetable/entries/bulk` | Bulk creates timetable entries | None | Array of `TimetableEntryCreate` | `{"created": N}` |
| `GET` | `/timetable/class/{class_id}` | Fetches timetable entries for class | None | Path parameter | Array of `TimetableEntryOut` |
| `POST` | `/timetable/availability` | Checks faculty clash availability for day/time | None | `FacultyAvailabilityCheck` | Array of `FacultyAvailabilityResult` |
| `GET` | `/classes` | Lists all academic classes | None | N/A | Array of `ClassOut` |
| `POST` | `/classes` | Creates a new academic class | None | `ClassCreate` | `ClassOut` |
| `GET` | `/faculty` | Lists all faculty members | None | N/A | Array of Faculty Objects |
| `POST` | `/faculty` | Creates a faculty member | None | `FacultyCreate` | Faculty Object |
| `PATCH` | `/faculty/{faculty_id}` | Updates a faculty member | None | `FacultyUpdate` | Faculty Object |
| `GET` | `/mst/exams` | Lists all MST examinations | None | N/A | Array of `MstExamOut` |
| `POST` | `/mst/exams` | Creates an MST examination | None | `MstExamCreate` | `MstExamOut` |
| `GET` | `/rooms` | Lists all examination rooms | None | N/A | Array of `RoomOut` |
| `POST` | `/rooms` | Creates an examination room | None | `RoomCreate` | `RoomOut` |
| `POST` | `/mst/seating/generate` | Generates seat plan pairs for exam | None | `SeatingGenerateIn` | `{"seats_created": N, ...}` |
| `GET` | `/mst/seating/{mst_exam_id}` | Fetches seating layout grouped by room | None | Path parameter | Array of Room Seats Objects |
| `POST` | `/mst/attendance/mark` | Marks roll call attendance (Present/Absent) | None | `MarkAttendanceIn` | `AttendanceMarkOut` |
| `GET` | `/mst/attendance/{mst_exam_id}` | Fetches attempt status for exam | None | Path parameter | Array of Attempt Objects |
| `GET` | `/mst/attendance/rollcall/{mst_exam_id}` | Fast roll call student list | None | Path parameter | Array of Student Roll Call Objects |
| `GET` | `/follow-up` | Lists VT follow-up status records with filters | None | Query params | Array of Follow-Up Objects |
| `GET` | `/follow-up/stats` | Aggregated VT follow-up statistics | None | Query params | JSON Object |
| `POST` | `/follow-up/recalculate` | Batch recalculates VT follow-up statuses | None | `FollowUpRecalcIn` | `{"evaluated": N, "changed": N}` |
| `POST` | `/follow-up/{follow_up_id}/override` | Sets human override for VT status | None | `FollowUpOverrideIn` | Follow-Up Object |
| `POST` | `/follow-up/{follow_up_id}/restore` | Restores calculated VT status | None | `FollowUpRestoreIn` | Follow-Up Object |
| `GET` | `/follow-up/export` | Exports compulsory VT list as XLSX | None | Query params | `application/vnd.openxmlformats...` |
| `GET` | `/follow-up/export-pdf` | Exports compulsory VT list as PDF | None | Query params | `application/pdf` binary stream |
| `GET` | `/mst/duties/{mst_exam_id}` | Lists invigilation duties for exam | None | Path parameter | Array of `DutyOut` |
| `POST` | `/mst/duties/assign` | Assigns faculty to duty slot | None | `DutyAssignIn` | `{"ok": true}` |
| `POST` | `/mst/duties/unassign/{duty_id}` | Unassigns faculty from duty slot | None | Path parameter | `{"ok": true}` |
| `POST` | `/mst/duties/auto-schedule` | Proposes invigilation roster (greedy algorithm) | None | `AutoScheduleIn` | Roster Proposal Object |
| `POST` | `/mst/duties/auto-schedule/apply` | Applies reviewed duty roster proposal | None | `ApplyProposalIn` | `{"applied": N, ...}` |
| `GET` | `/mst/faculty-status` | Faculty status for exam slot (Free/Teaching/Duty) | None | Query param | Array of `FacultyExamStatusOut` |
| `GET` | `/mst/faculty-grid` | Full faculty x exam timetable grid | None | N/A | Grid Object |

---

## 2. API Design & Versioning Deficiencies

1. **Missing `/api/v1` Prefix:**
   - Current routes are mounted directly at root level (e.g., `/eligibility/1`, `/classes`, `/follow-up`).
   - Target architecture requires all REST endpoints to be versioned under `/api/v1/` (e.g., `/api/v1/eligibility/1`).
2. **Inconsistent Error Response Envelopes:**
   - Errors currently throw standard FastAPI `HTTPException(status_code=..., detail="...")`.
   - Target architecture specifies structured error responses:
     ```json
     {
       "error": {
         "code": "ELIGIBILITY_OVERRIDE_FORBIDDEN",
         "message": "You do not have permission to override eligibility.",
         "request_id": "req_123"
       }
     }
     ```
3. **Frontend API URL Inconsistencies:**
   - Next.js frontend pages contain mixed API endpoint calls:
     - Some pages use relative `/api/...` paths relying on `next.config.mjs` rewrite rules.
     - Other pages hardcode `const API = "http://localhost:8000"`.
