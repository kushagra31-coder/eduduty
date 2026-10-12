# EduDuty — System Architecture

**Version:** 1.0  
**Status:** Target Production Architecture  
**Product:** EduDuty — Intelligent Examination Operations & Faculty Duty Management Platform

---

# 1. Architecture Goals

The architecture must transform the existing EduDuty prototype into a secure, maintainable and scalable institutional application.

Primary goals:

- Strong authentication and authorization
- Clear frontend/backend separation
- PostgreSQL as production source of truth
- Versioned database migrations
- Domain-driven backend services
- Controlled AI integration
- Complete auditability
- Transactional business operations
- Explainable scheduling
- Testability
- Production observability

---

# 2. High-Level Architecture

```text
                         USERS
                           │
                           ▼
                 ┌───────────────────┐
                 │   Web Browser     │
                 │ Next.js Frontend  │
                 └─────────┬─────────┘
                           │ HTTPS
                           ▼
                 ┌───────────────────┐
                 │ Reverse Proxy /   │
                 │ Load Balancer     │
                 └───────┬───────────┘
                         │
             ┌───────────┴────────────┐
             │                        │
             ▼                        ▼
   ┌──────────────────┐     ┌──────────────────┐
   │    Next.js       │     │     FastAPI      │
   │  Web Application  │     │    REST API      │
   └──────────────────┘     └────────┬─────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
                    ▼                ▼                ▼
             ┌────────────┐   ┌─────────────┐  ┌─────────────┐
             │ Auth / RBAC│   │ Domain      │  │ AI Service  │
             │            │   │ Services    │  │             │
             └────────────┘   └──────┬──────┘  └──────┬──────┘
                                     │                │
                                     ▼                ▼
                              ┌─────────────┐   ┌─────────────┐
                              │ PostgreSQL  │   │ LLM Provider│
                              │             │   │ / Local LLM │
                              └─────────────┘   └─────────────┘
                                     │
                        ┌────────────┴────────────┐
                        │                         │
                        ▼                         ▼
                 File/Object Storage       Background Jobs
                 Excel/PDF artifacts       Imports/Reports
```

---

# 3. Technology Stack

## Frontend

- Next.js
- React
- TypeScript
- Tailwind CSS
- shadcn/ui or existing compatible component system
- React Hook Form where useful
- Zod for client-side schema validation
- TanStack Query for server-state management where appropriate

## Backend

- Python
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- Pandas/openpyxl for spreadsheet processing
- ReportLab or equivalent PDF engine
- Pytest

## Database

Production:

- PostgreSQL

Development:

- PostgreSQL preferred
- SQLite may be used only as an explicit development convenience if compatibility is maintained

The application must NEVER silently fall back to SQLite in production.

## Authentication

Preferred:

- Supabase Auth

Alternative:

- OIDC/OAuth2-compatible identity provider

The identity provider is responsible for authentication.

FastAPI is responsible for authorization.

## AI

Provider abstraction supporting:

- Cloud LLM
- Local LLM
- Future provider changes

The AI layer must never have unrestricted database access.

---

# 4. Repository Structure

Recommended target structure:

```text
eduduty/
│
├── frontend/
│   ├── app/
│   │   ├── (auth)/
│   │   │   └── login/
│   │   ├── dashboard/
│   │   ├── students/
│   │   ├── faculty/
│   │   ├── academics/
│   │   ├── timetable/
│   │   ├── examinations/
│   │   ├── attendance/
│   │   ├── eligibility/
│   │   ├── seating/
│   │   ├── invigilation/
│   │   ├── roll-call/
│   │   ├── vt/
│   │   ├── reports/
│   │   ├── ai/
│   │   ├── audit/
│   │   └── settings/
│   │
│   ├── components/
│   │   ├── ui/
│   │   ├── forms/
│   │   ├── tables/
│   │   ├── charts/
│   │   └── domain/
│   │
│   ├── lib/
│   │   ├── api/
│   │   ├── auth/
│   │   ├── validation/
│   │   └── utils/
│   │
│   ├── hooks/
│   ├── types/
│   └── tests/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   │
│   │   ├── api/
│   │   │   ├── dependencies.py
│   │   │   ├── routers/
│   │   │   │   ├── auth.py
│   │   │   │   ├── students.py
│   │   │   │   ├── faculty.py
│   │   │   │   ├── academics.py
│   │   │   │   ├── timetable.py
│   │   │   │   ├── examinations.py
│   │   │   │   ├── attendance.py
│   │   │   │   ├── eligibility.py
│   │   │   │   ├── seating.py
│   │   │   │   ├── invigilation.py
│   │   │   │   ├── roll_call.py
│   │   │   │   ├── vt.py
│   │   │   │   ├── reports.py
│   │   │   │   ├── audit.py
│   │   │   │   └── ai.py
│   │   │
│   │   ├── core/
│   │   │   ├── security.py
│   │   │   ├── permissions.py
│   │   │   ├── logging.py
│   │   │   └── errors.py
│   │   │
│   │   ├── db/
│   │   │   ├── session.py
│   │   │   ├── base.py
│   │   │   └── models/
│   │   │
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── eligibility/
│   │   │   ├── attendance/
│   │   │   ├── seating/
│   │   │   ├── scheduling/
│   │   │   ├── vt/
│   │   │   ├── reports/
│   │   │   ├── audit/
│   │   │   └── ai/
│   │   │
│   │   ├── repositories/
│   │   ├── workers/
│   │   └── utils/
│   │
│   ├── alembic/
│   │   └── versions/
│   └── tests/
│
├── docs/
│   ├── PRD.md
│   ├── architecture.md
│   ├── API.md
│   ├── security.md
│   └── deployment.md
│
├── scripts/
├── synthetic-data/
├── docker/
├── .env.example
├── docker-compose.yml
└── README.md
```

The exact names may be adapted to the current repository, but the separation of concerns must remain.

---

# 5. Frontend Architecture

The frontend is responsible for:

- Presentation
- User interaction
- Form handling
- Client-side validation
- API consumption
- Loading/error states
- Navigation
- Permission-aware UI

The frontend is NOT responsible for enforcing security.

A hidden button does not constitute authorization.

---

# 6. Backend Architecture

FastAPI should use layered architecture:

```text
Router
  ↓
Authentication dependency
  ↓
Authorization dependency
  ↓
Pydantic validation
  ↓
Application service
  ↓
Repository
  ↓
SQLAlchemy
  ↓
PostgreSQL
```

Example:

```text
POST /eligibility/override/{id}
        ↓
get_current_user()
        ↓
require_permission("eligibility.override")
        ↓
validate request
        ↓
EligibilityService.override()
        ↓
transaction
        ↓
AuditService.record()
        ↓
response
```

Routers must remain thin.

Business rules must live in services.

---

# 7. Authentication Architecture

```text
Browser
  ↓
Identity Provider
  ↓
Authenticated Session / JWT
  ↓
Frontend
  ↓
Authorization header/session
  ↓
FastAPI
  ↓
Token validation
  ↓
CurrentUser
```

The backend must derive:

```text
user_id
role
faculty_id
permissions
```

from the authenticated identity.

Never trust these values from the request body.

---

# 8. Authorization / RBAC

Use permission-based authorization rather than scattered role checks.

Example permissions:

```text
student.read
student.create
student.update
student.delete

faculty.read
faculty.manage

exam.create
exam.update
exam.approve

attendance.import
attendance.mark

eligibility.read
eligibility.override

seating.generate
seating.approve

duty.generate
duty.assign
duty.override

vt.read
vt.override

reports.export

audit.read

ai.read
ai.write
```

Roles map to permissions.

Example:

```text
EXAM_COORDINATOR
 ├── exam.*
 ├── attendance.*
 ├── eligibility.*
 ├── seating.*
 ├── duty.*
 ├── vt.*
 └── reports.*
```

---

# 9. Database Architecture

PostgreSQL is the production source of truth.

Recommended major tables:

```text
users
roles
permissions
user_roles

departments
programs
academic_years
semesters
sections
subjects

students
faculty

buildings
rooms

faculty_availability
timetable_entries

examinations
examination_subjects
examination_enrollments

attendance_imports
attendance_import_rows

student_attendance

mst_eligibility
mst_attempts

vt_cases
vt_follow_ups

seating_plans
seating_plan_versions
seats
seat_assignments

invigilation_duties
duty_assignments

notifications

audit_logs

ai_interactions
ai_write_proposals
```

---

# 10. Database Rules

All critical relationships must use foreign keys.

Important uniqueness constraints:

```text
student.roll_number
faculty.employee_id
subject.code

(student_id, examination_id)
(student_id, mst_exam_id)

(examination_id, room_id)

(seating_plan_id, seat_id)

(duty_assignment, examination_id, faculty_id)
```

Do not rely only on application-level checks for uniqueness.

Use database constraints.

---

# 11. Database Migrations

Use Alembic.

Do not maintain several competing schema sources such as:

```text
schema.sql
create_all()
runtime CREATE TABLE
manual migration scripts
```

as independent sources of truth.

Preferred:

```text
SQLAlchemy Models
       ↓
Alembic migration
       ↓
PostgreSQL
```

`Base.metadata.create_all()` must not be the production migration mechanism.

---

# 12. Transaction Strategy

Critical workflows must be transactional.

Examples:

### Eligibility override

```text
BEGIN
 ↓
lock eligibility
 ↓
update final status
 ↓
create audit
 ↓
COMMIT
```

### Attendance import

```text
BEGIN
 ↓
validate dataset
 ↓
insert/update attendance
 ↓
recalculate affected eligibility
 ↓
create import audit
 ↓
COMMIT
```

### Duty assignment

```text
BEGIN
 ↓
lock relevant duty records
 ↓
revalidate conflicts
 ↓
assign faculty
 ↓
audit
 ↓
COMMIT
```

Never rely solely on frontend validation.

---

# 13. Eligibility Service

Recommended service interface:

```python
EligibilityService.calculate(
    student_id,
    examination_id
)

EligibilityService.calculate_bulk(
    examination_id
)

EligibilityService.override(
    eligibility_id,
    final_status,
    reason,
    actor
)

EligibilityService.restore(
    eligibility_id,
    actor
)
```

The service owns the business rules.

---

# 14. Attendance Service

Responsibilities:

- Parse
- Validate
- Normalize
- Deduplicate
- Preview
- Commit
- Recalculate affected results

The importer must not contain UI assumptions.

Context such as:

```text
exam_id
section_id
subject_id
```

must be explicit.

---

# 15. Seating Service

```text
Input:
  eligible students
  available rooms
  capacities
  seating rules

Output:
  versioned seating plan
```

Every generated plan should have:

```text
plan_id
version
generated_by
generated_at
rules_snapshot
status
```

---

# 16. Scheduling Service

Initial architecture:

```text
Exam
Faculty
Timetable
Availability
Existing duties
Constraints
        ↓
Candidate generation
        ↓
Hard constraint filtering
        ↓
Scoring
        ↓
Assignment
        ↓
Conflict report
```

Future solver:

```text
SchedulingService
       │
       ├── GreedyScheduler
       └── OrToolsScheduler
```

This abstraction lets the optimization engine evolve without rewriting the rest of the application.

---

# 17. Scheduling Constraints

Hard constraints:

```text
faculty active
faculty available
not exempt
no timetable clash
no overlapping duty
daily maximum
room/exam compatibility
```

Soft constraints:

```text
fair workload
department balancing
minimize repeated room assignment
minimize consecutive duties
```

Every rejected candidate should have a reason.

---

# 18. AI Architecture

The AI system must be isolated from unrestricted database access.

```text
                    AI Assistant
                         │
                         ▼
                Intent Classifier
                         │
              ┌──────────┴──────────┐
              │                     │
            READ                  WRITE
              │                     │
              ▼                     ▼
      Read Service Layer     Operation Schema
              │                     │
              │                Validation
              │                     │
              │                Authorization
              │                     │
              │                Conflict Check
              │                     │
              │                  Proposal
              │                     │
              │                User Confirm
              │                     │
              │                 Transaction
              │                     │
              └──────────┬──────────┘
                         ▼
                    Audit Service
```

---

# 19. AI Read Architecture

Do not allow arbitrary generated SQL if avoidable.

Prefer typed application operations:

```python
get_eligibility_summary(...)
get_vt_candidates(...)
get_duty_roster(...)
get_room_utilization(...)
get_attendance_summary(...)
```

If SQL generation is retained, it must be constrained by:

- read-only database role
- allow-listed views
- SQL parser/validator
- statement type restrictions
- query timeout
- row limits
- parameterization
- no DDL/DML

---

# 20. AI Write Architecture

Allowed operations must be explicit.

Example:

```python
class AssignDutyOperation:
    examination_id: int
    room_id: int
    faculty_id: int
```

Pipeline:

```text
LLM
 ↓
structured JSON
 ↓
Pydantic validation
 ↓
permission check
 ↓
domain validation
 ↓
proposal ID
 ↓
human confirmation
 ↓
execute proposal
 ↓
audit
```

The LLM never receives a database connection.

---

# 21. Audit Architecture

Every mutation should call:

```python
AuditService.record(...)
```

Audit entry:

```json
{
  "actor_id": 123,
  "action": "eligibility.override",
  "entity_type": "mst_eligibility",
  "entity_id": 456,
  "old_value": {...},
  "new_value": {...},
  "reason": "Approved by examination coordinator",
  "timestamp": "...",
  "request_id": "..."
}
```

Audit records should not be editable through ordinary application APIs.

---

# 22. File Processing Architecture

Uploaded files should be treated as untrusted input.

Pipeline:

```text
Upload
 ↓
Size validation
 ↓
Extension/MIME validation
 ↓
Temporary storage
 ↓
Parser
 ↓
Schema validation
 ↓
Row validation
 ↓
Duplicate detection
 ↓
Preview
 ↓
Approval
 ↓
Transactional import
 ↓
Archive/reference file
```

Do not process arbitrary uploaded files directly from memory without limits.

For large imports, use a background worker.

---

# 23. Reporting Architecture

Reports should use dedicated service functions.

```text
ReportRequest
     ↓
Authorization
     ↓
Query service
     ↓
Template
     ↓
PDF/XLSX generator
     ↓
Artifact storage
     ↓
Secure download
```

Sensitive reports must not be public URLs without access control.

---

# 24. Background Jobs

Introduce asynchronous jobs for:

- Large attendance imports
- Bulk eligibility recalculation
- Large PDF generation
- Bulk report generation
- Notifications
- Heavy analytics

Possible stack:

```text
FastAPI
  ↓
Redis
  ↓
Celery/RQ/Arq
  ↓
Worker
```

The exact worker technology can be selected during implementation.

Do not add a queue just for small synchronous operations.

---

# 25. API Design

Base path:

```text
/api/v1
```

Examples:

```text
GET    /students
POST   /students
GET    /students/{id}
PATCH  /students/{id}

GET    /faculty
POST   /faculty

GET    /examinations
POST   /examinations
POST   /examinations/{id}/approve

POST   /attendance/imports
GET    /attendance/imports/{id}
POST   /attendance/imports/{id}/approve

GET    /eligibility
POST   /eligibility/recalculate
POST   /eligibility/{id}/override
POST   /eligibility/{id}/restore

POST   /seating/generate
GET    /seating/{id}

POST   /invigilation/generate
POST   /invigilation/{id}/assign
POST   /invigilation/{id}/unassign

GET    /vt/cases
POST   /vt/{id}/override

GET    /reports/...
GET    /audit

POST   /ai/query
POST   /ai/proposals
POST   /ai/proposals/{id}/confirm
POST   /ai/proposals/{id}/reject
```

All API endpoints must return consistent error structures.

---

# 26. API Error Format

Recommended:

```json
{
  "error": {
    "code": "ELIGIBILITY_OVERRIDE_FORBIDDEN",
    "message": "You do not have permission to override eligibility.",
    "request_id": "req_123"
  }
}
```

Do not expose:

- stack traces
- SQL statements
- database credentials
- internal file paths
- LLM secrets

---

# 27. Frontend Data Flow

Prefer:

```text
React component
      ↓
domain hook
      ↓
API client
      ↓
FastAPI
```

Avoid scattering raw `fetch()` calls throughout UI components.

Example:

```text
useEligibility()
      ↓
eligibilityApi.list()
      ↓
GET /api/v1/eligibility
```

---

# 28. Frontend Authorization

Frontend permissions are used for UX:

```text
if can("eligibility.override"):
    show Override button
```

But backend must independently enforce:

```text
require_permission("eligibility.override")
```

A user must never gain access by manually constructing an API request.

---

# 29. Security Architecture

Required controls:

### Authentication
- Secure session/token validation
- Session expiry
- Secure cookie configuration where applicable

### Authorization
- RBAC
- Permission checks
- Resource-level checks

### API
- Pydantic validation
- Rate limiting
- CORS allow-list
- Request size limits
- Timeouts

### Database
- Parameterized SQL
- Least-privilege credentials
- Foreign keys
- Unique constraints
- Transactions

### Files
- Upload limits
- MIME/type validation
- Safe temporary storage
- Sanitized filenames

### AI
- No unrestricted SQL
- Operation allow-list
- Permission check
- Human confirmation
- Audit

### Secrets
- Environment variables/secrets manager
- `.env` excluded from Git
- Rotation support

---

# 30. Deployment Architecture

Recommended:

```text
                     Internet
                        │
                  Cloudflare / LB
                        │
              ┌─────────┴─────────┐
              │                   │
              ▼                   ▼
        Next.js App          FastAPI App
                                  │
                         ┌────────┴────────┐
                         │                 │
                         ▼                 ▼
                    PostgreSQL          Redis
                         │
                         ▼
                  Backup / Storage
```

Containers:

```text
frontend
backend
worker
postgres
redis
```

Development can use Docker Compose.

Production should use managed PostgreSQL where possible.

---

# 31. Environment Configuration

Required environment variables should be documented in `.env.example`.

Examples:

```text
DATABASE_URL
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
AI_PROVIDER
AI_API_KEY
REDIS_URL
STORAGE_BUCKET
CORS_ALLOWED_ORIGINS
ENVIRONMENT
LOG_LEVEL
```

Never commit real values.

The service-role key must never be exposed to the browser.

---

# 32. Observability

Backend should provide:

```text
GET /health
GET /health/ready
```

Log:

- request ID
- user ID where safe
- route
- status
- duration
- error code

Do not log:

- passwords
- access tokens
- sensitive student data unnecessarily
- AI secrets

---

# 33. Testing Architecture

Backend:

```text
tests/
├── unit/
│   ├── test_eligibility.py
│   ├── test_vt.py
│   ├── test_seating.py
│   └── test_scheduler.py
│
├── integration/
│   ├── test_auth.py
│   ├── test_import.py
│   ├── test_audit.py
│   └── test_ai.py
│
└── security/
    ├── test_rbac.py
    ├── test_idor.py
    └── test_ai_write_security.py
```

Frontend:

```text
tests/
├── unit/
├── integration/
└── e2e/
```

Critical business rules must have deterministic tests.

---

# 34. CI/CD

Pipeline:

```text
Pull Request
    ↓
Lint
    ↓
Type Check
    ↓
Unit Tests
    ↓
Integration Tests
    ↓
Security Checks
    ↓
Build
    ↓
Migration Check
    ↓
Preview Deployment
    ↓
Approval
    ↓
Production
```

No production deployment should occur if critical tests fail.

---

# 35. Migration Strategy From Current Prototype

The existing project must be upgraded incrementally.

## Stage 1

Preserve:

- Existing UI
- Eligibility logic
- VT logic
- Seating logic
- Scheduler concepts
- AI view concepts

## Stage 2

Replace:

- Hardcoded `user_id = 1`
- Client-supplied actor IDs
- permissive CORS
- localhost-only production proxy
- SQLite production fallback
- unprotected PDF endpoints

## Stage 3

Introduce:

- Auth
- RBAC
- Alembic
- PostgreSQL
- Audit service
- transaction boundaries

## Stage 4

Refactor:

- Attendance importer
- Scheduler
- AI service
- report generation

## Stage 5

Add:

- comprehensive tests
- observability
- background jobs
- production deployment

---

# 36. Architectural Rules for Antigravity

Antigravity MUST:

1. Inspect existing code before changing it.
2. Preserve working domain logic unless a change is justified.
3. Avoid unnecessary rewrites.
4. Never remove existing functionality without documenting why.
5. Never hardcode authentication identity.
6. Never trust client-supplied role/user IDs.
7. Never add unrestricted AI database access.
8. Never bypass backend authorization because a frontend route is protected.
9. Use migrations for database changes.
10. Add tests for changed business logic.
11. Run relevant tests after every substantial change.
12. Keep secrets out of source control.
13. Keep API contracts documented.
14. Keep PRD and architecture synchronized with implementation.
15. Prefer small, reviewable phases over one massive rewrite.

---

# 37. Definition of Architectural Completion

The architecture is considered implemented when:

```text
Authentication
      ✓
RBAC
      ✓
PostgreSQL
      ✓
Alembic
      ✓
Domain services
      ✓
Audit
      ✓
Transactional mutations
      ✓
Controlled AI
      ✓
Secure imports
      ✓
Explainable scheduling
      ✓
Protected reports
      ✓
Automated tests
      ✓
CI/CD
      ✓
Observability
      ✓
Production deployment
      ✓
```

---

# 38. Final Target Architecture

```text
                         ┌────────────────────┐
                         │       USERS        │
                         └─────────┬──────────┘
                                   │
                                   ▼
                         ┌────────────────────┐
                         │     Next.js        │
                         │   TypeScript UI    │
                         └─────────┬──────────┘
                                   │ HTTPS
                                   ▼
                         ┌────────────────────┐
                         │      FastAPI       │
                         │    API Gateway     │
                         └─────────┬──────────┘
                                   │
             ┌─────────────────────┼─────────────────────┐
             │                     │                     │
             ▼                     ▼                     ▼
       ┌───────────┐        ┌──────────────┐       ┌────────────┐
       │ Auth/RBAC │        │ Domain       │       │ AI Service │
       │           │        │ Services     │       │            │
       └───────────┘        └──────┬───────┘       └─────┬──────┘
                                   │                     │
                    ┌──────────────┼─────────────┐       │
                    │              │             │       │
                    ▼              ▼             ▼       ▼
               Eligibility     Scheduling     Reports   LLM
               Attendance      Seating        Audit
               Examination     VT             Import
                    │              │             │
                    └──────────────┼─────────────┘
                                   ▼
                         ┌────────────────────┐
                         │    PostgreSQL      │
                         └─────────┬──────────┘
                                   │
                         ┌─────────┴─────────┐
                         ▼                   ▼
                   Object Storage          Backup
                   Excel/PDF files
```

This architecture is the target state. Implementation should proceed incrementally from the current prototype rather than attempting a single rewrite.
