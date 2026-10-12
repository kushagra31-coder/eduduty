# EduDuty Role-Based Access Control (RBAC) Matrix (Phase 1)

## Overview
Server-side RBAC ensures every API action is explicitly guarded by permission requirements. Roles and permissions are defined centrally in `backend/core/security.py`.

---

## Role Definitions

| Role | Description |
| :--- | :--- |
| `SUPER_ADMIN` | Platform administrator with full access to all system resources. |
| `ADMIN` | HOD or Academic Administrator. Access to system configurations and operational views. |
| `EXAM_COORDINATOR` | Exam Coordinator. Full operational control over timetables, seating, duties, and overrides. |
| `FACULTY` | Faculty member. Access to upload attendance and view assigned invigilation duties. |
| `INVIGILATOR` | Invigilator on duty. Access to execute room roll-call. |
| `VIEWER` | Read-only access to published timetables and reports. |

---

## Permission Matrix

| Permission Key | SUPER_ADMIN | ADMIN | EXAM_COORDINATOR | FACULTY | INVIGILATOR | VIEWER |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `attendance.upload` | ✓ | ✓ | ✓ | ✓ | - | - |
| `attendance.view` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `eligibility.view` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `eligibility.override` | ✓ | ✓ | ✓ | - | - | - |
| `seating.generate` | ✓ | ✓ | ✓ | - | - | - |
| `seating.view` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `duties.schedule` | ✓ | ✓ | ✓ | - | - | - |
| `duties.apply` | ✓ | ✓ | ✓ | - | - | - |
| `duties.view` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `rollcall.execute` | ✓ | ✓ | ✓ | ✓ | ✓ | - |
| `system.manage` | ✓ | - | - | - | - | - |

---

## Endpoint Enforcement Pattern

```python
@app.post("/eligibility/override/{eligibility_id}")
def override_eligibility(
    eligibility_id: int,
    req: schemas.EligibilityOverrideRequest,
    current_user: models.User = Depends(require_permission("eligibility.override")),
    db: Session = Depends(get_db)
):
    ...
```

---

## Resource-Level Authorization (Layer 2)

While Role-Based Access Control (Layer 1) restricts operations by user role, EduDuty enforces **Resource-Level Authorization (Layer 2)** to prevent Insecure Direct Object Reference (IDOR) vulnerabilities and unauthorized cross-scope access:

1. **Invigilator Room Scoping (`verify_invigilator_room_assignment`):**
   - Invigilators marking attendance (`POST /mst/attendance/mark`) or retrieving room roll-call (`GET /mst/attendance/rollcall/{mst_exam_id}`) must be actively assigned to the target examination room via `InvigilationDuty`.
   - Administrative roles (`SUPER_ADMIN`, `ADMIN`, `EXAM_COORDINATOR`) bypass room restriction for oversight.

2. **Faculty Student Record Scoping (`verify_faculty_student_access`):**
   - Faculty accessing student PDF records (`GET /pdf/student/{roll_number}`) or HTML previews are restricted to students in classes assigned to them via `TimetableEntry` or matching their `Faculty.department`.
   - Administrative roles (`SUPER_ADMIN`, `ADMIN`, `EXAM_COORDINATOR`) maintain full student record access.

3. **AI Pipeline Resource Safeguards:**
   - Write proposals executed via `POST /ai/confirm-write` enforce exact roll number equality (`Student.roll_number == roll`), invigilator room assignment checks, and timetable conflict validation prior to committing duty assignments.

