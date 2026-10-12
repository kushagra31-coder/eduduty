# EduDuty — Phase 2 Stage B3.3.9 Architecture Decision Record (ADR)
## Implementation of Approved AI Authorization Policies & Stage B4 Handoff

**Date:** October 10, 2026  
**Status:** Stage B3.3.9 Complete — **PASS**  
**Gate Verdict:** PASS (Approved authorization policies fully implemented and verified; 86 tests passing; eduduty.db untouched)

---

## 1. Approved Policy Decisions & Architectural Impact

| Policy | Status | Architectural Implementation | Code References |
| :--- | :--- | :--- | :--- |
| **Policy 1: Active Faculty Class Assignments Only** | Implemented | Scope derived exclusively from active `FacultyTimetable` entries (`TimetableVersion.active == True` or null version). `AttendanceRecord` queries completely removed from authorization derivation. | [backend/main.py:820-835](file:///d:/Code/eduduty/backend/main.py#L820-L835) |
| **Policy 2: Faculty May View Institution-Wide Duty Roster** | Implemented | `execute_structured_reporting_op` no longer appends server requester-name filter for `ai_duty_roster`. Authenticated `FACULTY` can view all invigilation duties. Optional `faculty_name` argument filtering retained. Metadata updated to `"pii": True`. | [backend/ai_service.py:294,330-345](file:///d:/Code/eduduty/backend/ai_service.py#L294), [backend/main.py:857](file:///d:/Code/eduduty/backend/main.py#L857) |
| **Policy 3: Viewer AI Access Remains Blocked** | Implemented | `VIEWER` and `INVIGILATOR` denied `ai.read` permission in `ROLE_PERMISSIONS`. `/ai/query` endpoint returns `HTTP 403 FORBIDDEN`. No aggregate-only exceptions added. | [backend/core/security.py:72-90](file:///d:/Code/eduduty/backend/core/security.py#L72-L90), [backend/api/dependencies.py:70-82](file:///d:/Code/eduduty/backend/api/dependencies.py#L70-L82) |

---

## 2. Updated Request Path & Execution Controls

| Execution Step | Source File & Line Range | Security Controls & Enforcement |
| :--- | :--- | :--- |
| **1. Authentication & RBAC** | [backend/main.py:800](file:///d:/Code/eduduty/backend/main.py#L800) | `require_permission("ai.read")` verifies JWT token. `INVIGILATOR` and `VIEWER` lack `ai.read` and receive **HTTP 403 FORBIDDEN**. |
| **2. Trusted Scope Derivation** | [backend/main.py:820-835](file:///d:/Code/eduduty/backend/main.py#L820-L835) | Server derives `permitted_classes` from active `FacultyTimetable` entries $\rightarrow$ `Class.name`. Scope comes exclusively from trusted DB records. |
| **3. Identity Resolution** | [backend/main.py:809-818](file:///d:/Code/eduduty/backend/main.py#L809-L818) | Verified `current_user.faculty_id` $\rightarrow$ `Faculty` table. Unlinked/invalid faculty IDs fail closed with **HTTP 403 FORBIDDEN**. |
| **4. Environment Check** | [backend/ai_service.py:663-666](file:///d:/Code/eduduty/backend/ai_service.py#L663-L666) | Environment checked using `.strip().lower()`. Non-dev environments force free-form SQL disabled **unconditionally**. |
| **5. Primary Production Path** | [backend/ai_service.py:668-702](file:///d:/Code/eduduty/backend/ai_service.py#L668-L702) | LLM selects structured reporting operation via `STRUCTURED_READ_PROMPT`, executed through `execute_structured_reporting_op`. |
| **6. Isolated Read Execution** | [backend/ai_service.py:381](file:///d:/Code/eduduty/backend/ai_service.py#L381) | `read_db.execute(text(sql), params)` executed over isolated `AIReaderSessionLocal()` connection (`?mode=ro`). |

---

## 3. Structured AI Reporting Operations Catalog

| Operation Name | Target View | Permitted Roles | PII Flag | Scope Controls |
| :--- | :--- | :--- | :--- | :--- |
| `get_eligibility_summary` | `ai_eligibility_summary` | `ADMIN`, `EXAM_COORDINATOR`, `FACULTY` | False | Filtered by server `scope_class_names` |
| `get_attendance_summary` | `ai_attendance_summary` | `ADMIN`, `EXAM_COORDINATOR`, `FACULTY` | True | Filtered by server `scope_class_names` |
| `get_vt_candidates` | `ai_vt_candidates` | `ADMIN`, `EXAM_COORDINATOR`, `FACULTY` | True | Filtered by server `scope_class_names` |
| `get_duty_roster` | `ai_duty_roster` | `ADMIN`, `EXAM_COORDINATOR`, `FACULTY` | True | Institution-wide (optional `faculty_name` argument) |
| `get_vt_follow_up_status` | `v_vt_follow_up_status` | `ADMIN`, `EXAM_COORDINATOR`, `FACULTY` | True | Filtered by server `scope_class_names` |

---

## 4. PostgreSQL Migration & RLS Plan for Stage B4

When Stage B4 is initiated on a live PostgreSQL database:
1. **Migration 006 (`006_add_faculty_id_to_ai_duty_roster.py`):**
   Expose `f.id AS faculty_id` on `ai_duty_roster` view for integer-based RLS joins: `faculty_id = current_setting('app.current_faculty_id')::integer`.
2. **PostgreSQL Security Invoker Configuration:**
   Apply `security_invoker = true` to all 5 reporting views.
3. **Session Parameter Injection:**
   Use `SET LOCAL app.current_user_role = ...` within transaction blocks.

---

## 5. Verification & Test Suite Outcome

Executed full backend test suite:
```powershell
$env:APP_ENV="test"; python -m pytest tests
```
Result: **`86 PASSED, 0 FAILED`** (in 28.92s).

---

## 6. Stage B3.3.9 Verdict

### Verdict: **PASS**

All approved authorization policies have been fully implemented, validated with 86 passing tests, and documented. Database `eduduty.db` was left 100% untouched.

**Stop condition met. Ready for Stage B4 handoff.**
