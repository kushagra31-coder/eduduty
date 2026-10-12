# EduDuty — Product Requirements Document (PRD)

**Version:** 1.0  
**Status:** Implementation Baseline  
**Product:** EduDuty — Intelligent Examination Operations & Faculty Duty Management Platform  
**Primary Users:** College administration, examination coordinators, faculty, invigilators  
**Target:** Production-grade institutional web application

---

## 1. Product Overview

EduDuty is a centralized examination-operations platform designed to reduce manual work and errors in college examination management.

The system manages the complete operational lifecycle:

- Academic master data
- Student and faculty records
- Attendance and attendance imports
- MST/examination creation
- Eligibility calculation
- Human review and overrides
- Examination seating
- Invigilation duty allocation
- Roll-call/attendance
- VT/follow-up workflows
- Timetable and faculty availability
- Reports and PDF generation
- Audit and compliance history
- Analytics
- AI-assisted read and controlled-write workflows

The current repository is a prototype. This PRD defines the target full-scale product and the rules that future implementation must follow.

---

# 2. Product Goals

## 2.1 Primary Goals

1. Centralize examination operations in one application.
2. Eliminate spreadsheet-driven operational errors.
3. Make eligibility and assignment decisions explainable.
4. Prevent unauthorized data modification.
5. Provide complete auditability for administrative changes.
6. Automate repetitive scheduling and reporting.
7. Provide an AI assistant without allowing uncontrolled AI database access.
8. Support real-world college-scale datasets.
9. Produce professional operational documents.
10. Maintain a clear separation between calculated results and human overrides.

## 2.2 Secondary Goals

- Reduce examination coordinator workload.
- Improve room and faculty utilization.
- Provide fast operational dashboards.
- Make historical examination data searchable.
- Support future integration with institutional ERP/SIS systems.

## 2.3 Non-Goals

The first production release will NOT attempt to become:

- A complete college ERP
- A learning management system
- A fee-management system
- A payroll system
- A student grading/marks-management system
- An unrestricted general-purpose AI agent

---

# 3. Target Users and Roles

## 3.1 SUPER_ADMIN

Full system administration.

Permissions:

- Manage users and roles
- Manage institution configuration
- Manage departments
- Manage academic structure
- View all data
- Manage system settings
- View audit logs
- Manage integrations

## 3.2 ADMIN

Institution-level operational administrator.

Permissions:

- Manage students
- Manage faculty
- Manage classes/sections
- Manage rooms
- Manage subjects
- Manage exams
- View reports
- Manage examination operations

## 3.3 EXAM_COORDINATOR

Responsible for examination operations.

Permissions:

- Create/manage examinations
- Import attendance
- Review eligibility
- Approve eligibility
- Generate seating
- Generate invigilation roster
- Manage roll call
- Manage VT/follow-up
- Generate reports
- View relevant audit history

## 3.4 FACULTY

Permissions:

- View assigned duties
- View own timetable
- View assigned examination information
- Submit availability/unavailability where permitted
- Perform assigned roll-call actions
- View permitted student/exam information

## 3.5 INVIGILATOR

Permissions:

- View assigned room/exam
- View duty instructions
- Mark permitted examination attendance
- Access assigned operational documents

## 3.6 VIEWER

Read-only access to explicitly permitted dashboards and reports.

---

# 4. Core Product Principles

1. **Server-side authorization is mandatory.**
2. UI visibility is never considered authorization.
3. Calculated values and human overrides must remain separate.
4. Missing data must never silently become a negative value.
5. AI must operate through controlled application services.
6. Every sensitive mutation must be auditable.
7. Critical imports must use validation and approval workflows.
8. Production must use PostgreSQL; SQLite is development-only.
9. Business rules must live in backend services, not only in React components.
10. Every important automated decision should be explainable.

---

# 5. Functional Requirements

## 5.1 Authentication

The system shall support:

- Secure login
- Logout
- Session management
- Password/account recovery through the selected identity provider
- Session expiration
- Role-aware access
- Protected backend APIs

Authentication may use Supabase Auth or another standards-compliant identity provider.

The backend must derive the current user from the authenticated session/token.

The client must never be trusted for:

- user ID
- role
- faculty ID
- audit actor
- approval identity

---

# 6. Academic Master Data

The system shall manage:

### Institution
- Institution
- Campus
- Department
- Program

### Academic Structure
- Academic year
- Semester
- Section/class
- Batch
- Subject
- Subject code

### People
- Student
- Faculty
- Administrative users

### Examination Resources
- Building
- Floor
- Room
- Room capacity
- Room type
- Accessibility information

All entities require:

- Unique identifiers
- Created timestamp
- Updated timestamp
- Active/inactive state where applicable
- Referential integrity

---

# 7. Student Management

Student records shall contain, as appropriate:

- Roll number
- Enrollment number
- Name
- Program
- Department
- Academic year
- Semester
- Section
- Batch
- Contact information where institutionally permitted
- Active/inactive status

Roll numbers and institutional identifiers must use exact matching when referenced by business operations.

---

# 8. Faculty Management

Faculty records shall support:

- Faculty ID
- Employee/institution identifier
- Name
- Department
- Designation
- Active status
- Duty exemption
- Maximum duties per day
- Availability/unavailability
- Timetable assignments

Faculty availability must be represented as structured data, not free-form text.

---

# 9. Timetable

The system shall support:

- Day
- Start time
- End time
- Faculty
- Subject
- Section
- Academic year
- Room where applicable

The scheduler must consider timetable conflicts across all relevant academic years/sections.

A faculty member must not be assigned examination duty during a conflicting teaching period unless an authorized override exists.

---

# 10. Examination Management

An examination shall contain:

- Exam ID
- Examination type
- Label/name
- Subject
- Date
- Start time
- End time
- Duration
- Semester/section scope
- Status
- Created by
- Approval state

Suggested states:

```text
DRAFT
SCHEDULED
READY
IN_PROGRESS
COMPLETED
CANCELLED
ARCHIVED
```

---

# 11. Attendance Import

Supported initial input:

- Excel `.xlsx`
- CSV where applicable

Workflow:

```text
Upload
  ↓
File validation
  ↓
Parse
  ↓
Schema detection
  ↓
Row validation
  ↓
Duplicate detection
  ↓
Preview
  ↓
Coordinator approval
  ↓
Transactional commit
  ↓
Recalculate dependent results
  ↓
Audit log
```

The system shall NOT silently assume:

- MST-1
- CI-1
- a specific class
- a specific examination
- a specific student

Where context is ambiguous, the user must select or confirm it.

Import limits shall be enforced.

---

# 12. Eligibility Engine

Eligibility must be deterministic and explainable.

Inputs may include:

- Attendance percentage
- Required attendance threshold
- Examination
- Student
- Subject/class rules
- Institutional policy

Example:

```text
attendance >= threshold
        ↓
eligible

attendance < threshold
        ↓
not eligible

missing/insufficient evidence
        ↓
under review
```

The exact threshold must be configurable.

The engine shall expose:

- Calculated status
- Reason
- Relevant attendance values
- Rule/threshold used
- Calculation timestamp

---

# 13. Human Override

Human overrides shall never overwrite the original calculation.

Store separately:

```text
calculated_status
final_status
override_reason
overridden_by
overridden_at
```

Overrides require:

- Permission
- Explicit reason
- Audit entry

Restoring the calculated result must also be audited.

---

# 14. MST Attempt / Appearance Tracking

The system must distinguish:

```text
TRUE  = appeared
FALSE = explicitly absent
NULL  = unknown/not recorded
```

This distinction is mandatory.

It must never convert missing information into absence automatically.

---

# 15. VT / Follow-up Engine

The VT engine shall identify students requiring follow-up based on configured institutional rules.

The system shall preserve:

- Calculated VT status
- Final VT status
- Override
- Reason
- Review status
- Follow-up status
- Review notes
- Actor and timestamps

Suggested statuses:

```text
PENDING
COMPULSORY
NOT_REQUIRED
UNDER_REVIEW
OVERRIDDEN
COMPLETED
```

---

# 16. Seating Management

The system shall generate seating based on:

- Eligible students
- Exam
- Room capacity
- Room availability
- Seating rules
- Optional class/section separation rules

The system shall provide:

- Seat map
- Student-to-seat mapping
- Room utilization
- Printable seating plan
- Regeneration support

A generated seating plan must be versioned if later regenerated after changes.

---

# 17. Invigilation Duty Management

The system shall assign faculty using configurable constraints.

Hard constraints:

- Faculty active
- Faculty not exempt
- Faculty available
- No timetable conflict
- No simultaneous duty
- Room/exam compatibility
- Maximum duty limit

Soft objectives:

- Balance workload
- Minimize repeated assignments
- Improve department distribution where configured
- Prefer fair allocation

The scheduler must produce explanations for rejected candidates.

Example:

```text
Rejected:
Faculty A

Reason:
Teaching class from 10:00–11:00
which overlaps the examination.
```

---

# 18. Scheduling Engine

The initial implementation may use a deterministic constraint-aware greedy algorithm.

The architecture must allow future replacement with OR-Tools or another constraint solver.

The scheduler must support:

- Dry-run
- Conflict report
- Proposed roster
- Human approval
- Final assignment
- Manual reassignment
- Re-run after changes

Manual assignments must still undergo server-side validation.

---

# 19. Roll Call

Invigilators shall be able to:

- View assigned room
- View student list
- Mark present/absent
- Record exceptions
- Submit attendance

The system must record:

- Who marked the record
- When
- Examination
- Room
- Student
- Previous state
- New state

---

# 20. Reports and Documents

Required reports:

- Eligible students
- Ineligible students
- Under-review students
- Seating plan
- Invigilation roster
- Room allocation
- Roll-call sheet
- VT list
- Follow-up report
- Faculty duty summary
- Examination summary
- Audit report

Exports:

- PDF
- CSV
- XLSX where appropriate

Sensitive reports must require authorization.

---

# 21. Audit System

Every sensitive mutation shall record:

- Actor
- Action
- Entity
- Entity ID
- Previous value
- New value
- Reason
- Timestamp
- Request/correlation ID where available

Audit records must be append-oriented and protected from ordinary users.

Audited events include:

- Eligibility override
- Eligibility restore
- Attendance mutation
- Duty assignment
- Duty unassignment
- Seating generation
- Seating regeneration
- Examination creation/update
- Student/faculty changes
- Timetable changes
- Imports
- Approvals
- AI write operations
- Administrative configuration changes

---

# 22. AI Assistant

## 22.1 AI Read Mode

Users may ask questions such as:

- "How many students are eligible for MST-2?"
- "Which students need VT follow-up?"
- "Which rooms are underutilized?"
- "Show today's invigilation roster."
- "Which faculty have the highest duty count?"

AI responses must be grounded in application data.

## 22.2 AI Write Mode

Supported operations should initially be limited to an allow-list:

```text
override_eligibility
restore_eligibility
assign_duty
unassign_duty
mark_attempt_status
```

Flow:

```text
Natural language
 ↓
Intent classification
 ↓
Structured operation
 ↓
Schema validation
 ↓
Authorization
 ↓
Conflict/business-rule validation
 ↓
Proposal
 ↓
Explicit user confirmation
 ↓
Transactional execution
 ↓
Audit
```

The AI must NEVER:

- execute arbitrary SQL
- choose its own authorization
- bypass business rules
- impersonate users
- directly modify the database
- fabricate successful operations

---

# 23. Dashboard

Dashboard widgets shall include:

- Upcoming examinations
- Eligible/ineligible/under-review counts
- Pending approvals
- Today's duties
- Room utilization
- Faculty workload
- Attendance/import issues
- VT follow-ups
- System alerts

Dashboard data must be permission-aware.

---

# 24. Notifications

Future-ready notification architecture should support:

- In-app notifications
- Email
- Exam duty notifications
- Approval reminders
- Conflict alerts
- Import completion
- Scheduling completion

Notification delivery must not block critical transactions.

---

# 25. Search and Filtering

Major administrative screens shall support:

- Search
- Pagination
- Sorting
- Filtering
- Date range
- Status filters
- Export of filtered results where permitted

Search must use parameterized queries and exact matching for sensitive identifiers.

---

# 26. Non-Functional Requirements

## Security

- HTTPS in production
- Secure authentication
- Server-side RBAC
- Input validation
- Parameterized queries
- CORS restrictions
- File validation
- File size limits
- Rate limiting on sensitive endpoints
- Secure secrets management
- No secrets in source control
- Audit logging
- Secure headers

## Performance

Target for normal institutional datasets:

- Dashboard load: < 2 seconds where practical
- Standard API response: < 500 ms where practical
- Search/filter: < 1 second where practical
- Large imports processed asynchronously when needed

## Reliability

- Database transactions
- Automated backups
- Migration strategy
- Error recovery
- Idempotent import handling
- Health checks

## Accessibility

Target WCAG 2.1 AA where practical.

## Observability

- Structured logs
- Error tracking
- Request IDs
- Health endpoint
- Metrics-ready architecture

---

# 27. Testing Requirements

Minimum test layers:

### Unit
- Eligibility rules
- VT rules
- Scheduler constraints
- Seat generation
- AI operation validation

### Integration
- API + database
- Authentication
- RBAC
- Import workflow
- Audit logging

### End-to-End
- Login
- Create exam
- Import attendance
- Review eligibility
- Generate seating
- Generate duties
- Roll call
- Reports
- AI read/write workflow

### Security
- Unauthorized API calls
- Role escalation
- IDOR
- malformed imports
- SQL injection
- arbitrary AI operation attempts
- sensitive export access

---

# 28. Acceptance Criteria

EduDuty is considered production-ready only when:

1. Every protected API requires authentication.
2. Every sensitive operation enforces server-side RBAC.
3. No hardcoded user identity remains.
4. Production uses PostgreSQL.
5. Database migrations are version-controlled.
6. Eligibility calculation is deterministic and tested.
7. Missing attendance is not treated as absence.
8. Overrides are separately stored and audited.
9. Attendance imports use preview/validation/approval.
10. Scheduling detects timetable and availability conflicts.
11. Manual assignments cannot bypass hard constraints without explicit authorized override.
12. Sensitive PDFs/exports are protected.
13. AI cannot execute arbitrary SQL.
14. AI writes require permission and explicit confirmation.
15. All AI writes are audited.
16. Critical mutations are transactional.
17. Automated tests pass.
18. Production build passes.
19. No critical/high unresolved security issues remain.
20. Documentation matches actual implementation.

---

# 29. Development Strategy

Implementation must be incremental.

Recommended order:

```text
Phase 0  Architecture + baseline audit
Phase 1  Authentication + RBAC
Phase 2  Database + migrations
Phase 3  Academic master data
Phase 4  Examination management
Phase 5  Attendance + eligibility
Phase 6  Seating + roll call
Phase 7  Timetable + faculty availability
Phase 8  Invigilation scheduler
Phase 9  VT/follow-up
Phase 10 Reports + PDFs
Phase 11 AI assistant
Phase 12 Analytics + notifications
Phase 13 Testing + security hardening
Phase 14 Production deployment
```

No phase should silently rewrite unrelated modules.

---

# 30. Definition of Done

A feature is done only when:

- Backend implementation exists
- Frontend workflow exists
- Validation exists
- Authorization exists
- Audit requirements are handled
- Database migration exists
- Unit/integration tests exist
- Error states exist
- Loading states exist
- Documentation is updated
- Existing functionality remains intact
