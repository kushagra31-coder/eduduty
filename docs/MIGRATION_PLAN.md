# EduDuty — Full Implementation Baseline & Migration Plan

**Date:** October 6, 2026  
**Status:** Complete  
**Scope:** Incremental Phase-by-Phase Roadmap (Phase 0 through Phase 14)  

---

## 1. Subsystem Disposition & Preservation Mapping

To avoid unnecessary rewrites and leverage the high-quality core prototype logic, all major existing subsystems have been audited and classified:

| Subsystem / Component | Disposition Status | Justification & Refactoring Scope |
| :--- | :--- | :--- |
| **Eligibility Engine** (`crud.compute_eligibility_for_student`) | **KEEP AS-IS** | Deterministic, handles 50%/45% thresholds accurately. Needs threshold parameterization. |
| **VT / Follow-Up Engine** (`crud.recalculate_follow_up`) | **KEEP AS-IS** | Implements `absent-both-mst-v1` cleanly, preserves NULL handling, supports override & restore. |
| **Invigilation Scheduler** (`crud.propose_invigilation_duties`) | **KEEP WITH REFACTOR** | Excellent greedy heuristic with 4 hard constraints. Refactor to introduce solver abstraction interface. |
| **Seating Pair Generator** (`generate_seating`) | **KEEP WITH REFACTOR** | Natural sorting & Batch 1/2 zip pairing works well. Refactor to attach to parent `SeatingPlan` entity. |
| **AI Read/Write Pipeline** (`ai_service.py`) | **KEEP WITH REFACTOR** | Proposal-confirm-audit flow is solid. Refactor SQL execution to use dedicated `ai_readonly` DB connection. |
| **PDF Generation Engine** (`pdf_service.py`) | **KEEP AS-IS** | Excellent HTML/WeasyPrint templates for student records, seating charts, and VT lists. |
| **Frontend UI Pages & Dashboard** (`frontend/src/app`) | **KEEP WITH REFACTOR** | Modern Next.js 14 design system. Refactor API calls to point to unified `/api/v1` client. |
| **Authentication & RBAC** | **REBUILD** | Replace mock login with Supabase Auth / JWT verification & FastAPI permission dependencies. |
| **Database & Migration Strategy** (`database.py`) | **REBUILD** | Replace SQLite fallback with PostgreSQL + Alembic migration version control. |

---

## 2. Phase-by-Phase Implementation Roadmap

```text
Phase 0 ──► Baseline Audit & Architectural Mapping (COMPLETED)
Phase 1 ──► Authentication & Server-Side RBAC Integration
Phase 2 ──► PostgreSQL Engine & Alembic Database Migrations
Phase 3 ──► Academic Master Data Domain Service
Phase 4 ──► Examination Operations & State Lifecycle
Phase 5 ──► Attendance Importer & Eligibility Engine Hardening
Phase 6 ──► Versioned Seating Plans & Roll Call Systems
Phase 7 ──► Timetable Integration & Faculty Availability Engine
Phase 8 ──► Constraint-Aware Invigilation Duty Scheduler
Phase 9 ──► VT / Follow-up Workflow Hardening
Phase 10 ─► PDF / XLSX Document Reporting Services
Phase 11 ─► Controlled AI Assistant Security Hardening
Phase 12 ─► Analytics Engine & Asynchronous Notifications
Phase 13 ─► Test Suite Coverage & Security Hardening
Phase 14 ─► Containerized Production Deployment
```

---

### Phase 1: Authentication & Server-Side RBAC Integration
- **Objective:** Secure every backend API with mandatory token authentication and granular role-based permissions.
- **Affected Files:** `backend/main.py`, `backend/core/security.py`, `backend/core/permissions.py`, `frontend/src/app/login/page.tsx`
- **New Files:** `backend/app/api/dependencies.py`, `backend/app/core/permissions.py`, `frontend/src/lib/auth.ts`
- **API & DB Changes:** Add `users`, `roles`, `permissions`, `user_roles` schemas. Secure all routes via `Depends(get_current_user)` and `Depends(require_permission(...))`.
- **Acceptance Criteria:** Unauthenticated API calls return HTTP 401; unauthorized requests return HTTP 403. No hardcoded `user_id = 1` remains.

---

### Phase 2: PostgreSQL Engine & Alembic Database Migrations
- **Objective:** Transition database layer to production PostgreSQL with Alembic version-controlled migrations.
- **Affected Files:** `backend/database.py`, `backend/models.py`, `backend/requirements.txt`
- **New Files:** `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/`
- **API & DB Changes:** Enforce PostgreSQL `DATABASE_URL`; remove SQLite silent fallback; create baseline Alembic migration script. Add explicit UNIQUE constraints to ORM models.
- **Acceptance Criteria:** `alembic upgrade head` executes cleanly on PostgreSQL. Schema drift eliminated.

---

### Phase 3: Academic Master Data Domain Service
- **Objective:** Implement domain services and routers for institutional hierarchy (Institutions, Campuses, Departments, Programs, Courses, Rooms).
- **Affected Files:** `backend/models.py`, `backend/schemas.py`, `backend/crud.py`
- **New Files:** `backend/app/services/academics.py`, `backend/app/api/routers/academics.py`
- **API & DB Changes:** Add `departments`, `programs`, `academic_years`, `buildings` entities. Expose `/api/v1/academics/` endpoints.
- **Acceptance Criteria:** Complete institutional hierarchy CRUD supported with server-side validation.

---

### Phase 4: Examination Operations & State Lifecycle
- **Objective:** Implement comprehensive examination lifecycle management (`DRAFT`, `SCHEDULED`, `READY`, `IN_PROGRESS`, `COMPLETED`).
- **Affected Files:** `backend/models.py`, `backend/schemas.py`, `backend/crud.py`, `backend/main.py`
- **New Files:** `backend/app/services/examinations.py`, `backend/app/api/routers/examinations.py`
- **API & DB Changes:** Extend `MstExam` model with status state machine, approval states, and created_by metadata.
- **Acceptance Criteria:** Exam creation and status transitions enforced transactionally with audit logs.

---

### Phase 5: Attendance Importer & Eligibility Engine Hardening
- **Objective:** Add staged preview/approval workflow to Excel attendance imports and parameterize eligibility thresholds.
- **Affected Files:** `backend/main.py`, `backend/crud.py`, `frontend/src/app/attendance/upload/page.tsx`
- **New Files:** `backend/app/services/attendance_importer.py`
- **API & DB Changes:** Add `attendance_imports` and `attendance_import_rows` staging tables. Store eligibility thresholds in `system_rules`.
- **Acceptance Criteria:** Import requires explicit coordinator preview and approval before committing. Eligibility rules fully explainable and deterministic.

---

### Phase 6: Versioned Seating Plans & Roll Call Systems
- **Objective:** Upgrade seating generator to produce versioned plan records and link roll call attendance directly to seating positions.
- **Affected Files:** `backend/models.py`, `backend/crud.py`, `backend/main.py`, `frontend/src/app/mst-rollcall/page.tsx`
- **New Files:** `backend/app/services/seating.py`
- **API & DB Changes:** Add `seating_plans` and `seating_plan_versions` tables.
- **Acceptance Criteria:** Seating plan regeneration preserves historical versions; roll call records invigilator identity and timestamp.

---

### Phase 7: Timetable Integration & Faculty Availability Engine
- **Objective:** Hardened clash detection algorithm considering all academic sections and custom faculty unavailability blocks.
- **Affected Files:** `backend/crud.py`, `backend/models.py`
- **New Files:** `backend/app/services/timetable.py`
- **API & DB Changes:** Add `faculty_unavailability` table.
- **Acceptance Criteria:** Clash checker blocks duty allocation if faculty has a teaching class or registered unavailability.

---

### Phase 8: Constraint-Aware Invigilation Duty Scheduler
- **Objective:** Wrap greedy scheduler in an interface abstraction (`SchedulingService`) to support future OR-Tools integration.
- **Affected Files:** `backend/crud.py`, `backend/main.py`, `frontend/src/app/duties/page.tsx`
- **New Files:** `backend/app/services/scheduling/`
- **API & DB Changes:** `/api/v1/invigilation/auto-schedule`.
- **Acceptance Criteria:** Scheduler produces explainable conflict reports for rejected candidates; manual assignments undergo server validation.

---

### Phase 9: VT / Follow-up Workflow Hardening
- **Objective:** Connect VT follow-up recalculations to background events and harden human review/excuse workflows.
- **Affected Files:** `backend/crud.py`, `backend/main.py`, `frontend/src/app/follow-up/page.tsx`
- **New Files:** `backend/app/services/vt.py`
- **Acceptance Criteria:** Override and restore operations transactionally record actor identity and mandatory reason text.

---

### Phase 10: PDF / XLSX Document Reporting Services
- **Objective:** Protect PDF generation endpoints with authentication and stream generated documents securely.
- **Affected Files:** `backend/pdf_service.py`, `backend/main.py`
- **New Files:** `backend/app/services/reports.py`
- **Acceptance Criteria:** PDF generation runs without blocking main event loop; sensitive report URLs require authorization headers.

---

### Phase 11: Controlled AI Assistant Security Hardening
- **Objective:** Connect AI query execution to a restricted `ai_readonly` PostgreSQL user connection.
- **Affected Files:** `backend/ai_service.py`, `backend/main.py`, `frontend/src/components/AIChat.tsx`
- **Acceptance Criteria:** AI can never execute raw DML or bypass permission checks; write proposals require authorized user confirmation.

---

### Phase 12: Analytics Engine & Asynchronous Notifications
- **Objective:** Add operational analytics widgets and email/in-app notification delivery for duty assignments.
- **Affected Files:** `backend/main.py`, `frontend/src/app/dashboard/page.tsx`
- **New Files:** `backend/app/services/notifications.py`
- **Acceptance Criteria:** Notification delivery runs asynchronously without blocking core database transactions.

---

### Phase 13: Test Suite Coverage & Security Hardening
- **Objective:** Achieve comprehensive unit, integration, and security test coverage across backend and frontend.
- **New Files:** `backend/tests/unit/`, `backend/tests/integration/`, `backend/tests/security/`
- **Acceptance Criteria:** Automated test suite passes; Pytest coverage > 85%; zero unresolved P0/P1 security findings.

---

### Phase 14: Containerized Production Deployment
- **Objective:** Package EduDuty into production Docker containers with Nginx reverse proxy, health checks, and CI/CD pipelines.
- **New Files:** `Dockerfile.backend`, `Dockerfile.frontend`, `docker-compose.yml`, `.github/workflows/ci.yml`
- **Acceptance Criteria:** `docker-compose up` launches fully functional production environment with PostgreSQL and Next.js frontend.
