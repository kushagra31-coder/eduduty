# EduDuty — 24-Hour Product Completion Triage & Action Plan

**Date:** 2026-10-11  
**Target Milestone:** 24-Hour Demonstrable Product Completion  
**Security Baseline:** Phase B4.2B.5 Signing-Key & Replay Security Gate Verified (100% Pass)  
**Status:** TRIAGE COMPLETE — READY FOR IMPLEMENTATION

---

## 1. Executive Summary

EduDuty's security hardening phase (Phases B1 through B4.2B.5) successfully eliminated critical vulnerabilities—including HMAC-signed identity context, least-privilege PostgreSQL RLS ownership, monotonic key rotation, and strict RBAC authorization. Both the PostgreSQL integration suite (93 tests) and SQLite regression suite (86 tests) pass with 100% reliability.

However, an exhaustive end-to-end audit of the application reveals a critical architectural disconnect between frontend and backend:
1. **The application frontend is currently inaccessible without an external Supabase server.** The frontend login page calls `@supabase/supabase-js` pointing to an unconfigured endpoint (`localhost:54321`), while `AuthProvider` redirects all pages to `/login`.
2. **7 out of 9 frontend pages use raw `fetch()` calls without Bearer tokens.** Even if a user were authenticated, calls to `/api/dashboard/stats`, `/api/upload-attendance/`, `/api/mst-rollcall`, `/api/follow-up`, `/api/timetable`, `/api/settings`, and `/api/ai/query` omit the `Authorization` header, triggering immediate `401 UNAUTHORIZED` responses from FastAPI.
3. **The active SQLite database (`backend/eduduty.db`) contains zero records across all 18 tables.** Without populated seed data (classes, faculty, rooms, timetable entries, and attendance uploads), the UI renders empty states even when connected.
4. **Mobile navigation is absent.** The sidebar disappears entirely on viewports below 768px with no hamburger drawer or mobile header.

The core business logic (attendance ingestion, timetable conflict detection, bus-seat seating algorithm, eligibility computation, follow-up state machine, PDF export, and AI assistant reporting) is fully implemented and tested in the backend. 

By systematically addressing the authentication bridge, unifying API client token plumbing, seeding demo data, and adding mobile navigation, EduDuty can become a demonstrable, end-to-end operational product within approximately **14 to 18 hours of focused effort**, well inside the 24-hour deadline.

---

## 2. Test Suite Execution & Verification Results

All tests were executed in clean, non-destructive environments without modifying `backend/eduduty.db` or touching Docker resources.

### A. SQLite Core & Regression Suite
- **Command:** `pytest tests/test_auth.py tests/test_rbac.py tests/test_identity_spoofing.py tests/test_resource_authorization.py tests/test_upload_attendance.py tests/test_alembic_migration.py tests/test_alembic_b2_constraints.py tests/test_alembic_b3_ai_views.py tests/test_alembic_b31_review.py tests/test_alembic_b32_gate.py tests/test_alembic_b33_auth.py tests/test_ai_read_isolation.py -q`
- **Working Directory:** `backend/`
- **Result:** **86 PASSED**, 0 failed, 14 deprecation warnings in 12.18s
- **Coverage:** JWT validation, RBAC permission gating, faculty resource isolation, atomic attendance import rollback, Alembic schema migrations (001-006), AI view integrity, and prompt-injection defenses.

### B. PostgreSQL RLS & Integration Suite
- **Command:** `pytest tests/test_postgres_connection_b412.py tests/test_postgres_gating.py tests/test_alembic_b42a_ai_reader.py tests/test_postgres_rls_b42b.py tests/test_postgres_rls_b42b2_remediation.py tests/test_postgres_rls_b42b4_ownership.py tests/test_postgres_rls_b42b5_lifecycle.py -q`
- **Working Directory:** `backend/`
- **Environment:** Dedicated test container `eduduty_pg_b4_test` (`127.0.0.1:5433`, DB `eduduty_test_db`, head `010_retire_insecure_dev_key`)
- **Result:** **93 PASSED** (when gated with test credentials), 0 failed. When ungated, 17 unit tests pass and 76 integration tests skip cleanly to protect non-PostgreSQL environments.
- **Coverage:** RLS security policies, `ai_reader` unprivileged user restrictions, HMAC-SHA256 signature verification, trusted identity contexts, replay prevention, and secure key rotation.

### C. Frontend Compilation & Linting
- **Build Command:** `npm run build` in `frontend/`
- **Result:** **COMPILED CLEANLY** (Next.js 14.2.35). 16 static routes generated in 3.4s with zero TypeScript compilation errors.
- **Lint Command:** `npm run lint` in `frontend/`
- **Result:** **PASS** (Zero ESLint warnings or errors).

---

## 3. Comprehensive Workflow Evaluation Matrix

Every user-facing workflow has been evaluated against the codebase, API contracts, and runtime behavior:

| # | Workflow / Functional Area | Classification | Code Evidence & Root Cause | Impact on Demo |
|---|----------------------------|----------------|----------------------------|----------------|
| **1** | **Authentication & Session Management** | **BROKEN** | Frontend `app/login/page.tsx` calls `supabase.auth.signInWithPassword()` against `localhost:54321`. `lib/auth/context.tsx` redirects all unauthenticated traffic to `/login`. No local dev auth route or demo credentials exist in backend. | **CRITICAL BLOCKER** (Portal cannot be logged into via UI). |
| **2** | **Frontend-to-Backend API Connections** | **BROKEN** | `lib/api.ts` defines `apiFetch` with token injection, but **only 2 pages** (`duties`, `eligibility`) use it. 7 pages (`dashboard`, `attendance/upload`, `attendance/tracker`, `mst-rollcall`, `follow-up`, `timetable`, `settings`, `components/AIChat`) use raw `fetch()` without `Authorization` header. Backend requires `require_permission(...)` on all endpoints. | **CRITICAL BLOCKER** (All dashboard, upload, and data screens return 401 Unauthorized). |
| **3** | **Responsive Navigation & Mobile Layout** | **INCOMPLETE** | In `app/layout.tsx`, `Sidebar` is marked `className="w-64 flex-shrink-0 hidden md:flex"`. On screens `< 768px`, navigation vanishes completely. No mobile drawer, toggle header, or sheet component exists. | **HIGH** (Broken mobile/tablet experience during demonstrations). |
| **4** | **Dashboard (`/dashboard`)** | **BROKEN** | Calls raw `fetch('/api/dashboard/stats')` without auth -> 401. Endpoint hardcodes `mst_exam_id=1`. No role-specific widget scoping (Super Admin, Coordinator, Faculty all see same static layout). | **HIGH** (Landing page fails with "Couldn't reach the backend"). |
| **5** | **Attendance Upload (`/attendance/upload`)** | **COMPLETE (Backend) / BROKEN (Frontend)** | Backend `/upload-attendance/` parser is robust (supports multi-sheet Excel, Theory/Practical detection, atomic rollbacks). Frontend drag-and-drop UI is well designed, but sends raw `fetch()` without Bearer token -> 401. | **HIGH** (Cannot upload sample attendance sheets from UI). |
| **6** | **Attendance Seat Map Tracker (`/attendance/tracker`)** | **COMPLETE (Backend) / BROKEN (Frontend)** | Bus-seat layout with B1/B2 interleaving, room capacity progress, and click-to-toggle attendance marking. Backend `/mst/seating/generate` and `/mst/attendance/mark` are fully operational. Frontend calls raw `fetch()` without auth -> 401. | **HIGH** (Interactive seat map cannot load rooms or record attendance). |
| **7** | **MST Roll Call (`/mst-rollcall`)** | **COMPLETE (Backend) / BROKEN (Frontend)** | Fast checklist UI with search, batch filtering, and Present/Absent toggle. Calls local `apiFetch` without `Authorization` header -> 401. | **MEDIUM** (Roll call fails to load student rosters). |
| **8** | **Eligibility Management (`/eligibility`)** | **COMPLETE** | Properly imports and uses `@/lib/api` `apiFetch`. Allows filtering by exam, viewing overall/subject percentages, and opening the manual coordinator override modal. (Will function immediately once auth session provides a token). | **MINIMAL** (Ready once auth token is plumbed). |
| **9** | **VT Candidates & Follow-up (`/follow-up`)** | **COMPLETE (Backend) / BROKEN (Frontend)** | Follow-up state machine correctly detects students absent from both MST-1 and MST-2, distinguishes missing records from unexcused absence, and supports overrides. Frontend uses raw `fetch()` -> 401. | **HIGH** (VT evaluation table cannot load data or submit overrides). |
| **10** | **Duty Scheduler (`/duties`)** | **COMPLETE** | Uses `apiFetch` from `@/lib/api`. Backend greedy scheduler assigns available faculty avoiding teaching slots and honoring max-duties caps. Proposal review and one-click apply workflow fully implemented. | **MINIMAL** (Ready once auth token is plumbed). |
| **11** | **Timetable Management (`/timetable`)** | **INCOMPLETE / BROKEN** | Comprehensive UI with timetable grid, period tabs, and faculty availability matrix. Uses local `apiFetch` without auth -> 401. Backend CRUD endpoints in `timetable_router` require `faculty.manage` / `faculty.read`. | **HIGH** (Timetable grid displays network failure). |
| **12** | **AI Assistant & Audit Trail (`/ai`)** | **COMPLETE (Backend) / BROKEN (Frontend)** | 4-layer security architecture, read isolation, and safe proposal preview modal are complete. PDF generation for eligibility works via `/api/pdf/...`. `components/AIChat.tsx` calls raw `fetch('/api/ai/query')` without Bearer token -> 401. | **MEDIUM** (Chat assistant returns 401 error). |
| **13** | **Settings & System Info (`/settings`)** | **BROKEN** | Tabs for AI health, faculty management, class management, and database status. Uses local `apiFetch` without auth -> 401. Faculty add/edit modals fail. | **MEDIUM** (Settings views cannot load or save system configurations). |
| **14** | **Database Seeding & Initial State** | **INCOMPLETE** | Both `backend/eduduty.db` and root `eduduty.db` have 0 rows in all tables. Excel files (`CI-1 IV.xlsx`, etc.) and `seed_timetable.py` exist in repo but have not been seeded into an active runtime database. | **HIGH** (App boots completely empty). |
| **15** | **Deployment Readiness & Setup Documentation**| **INCOMPLETE** | No root `README.md`. No unified startup script. Developers cannot easily boot both frontend and backend with single command. | **MEDIUM** (High friction for demo setup and handoff). |

---

## 4. Root Cause Analysis of Primary Blockers

### Blocker 1: Authentication Lockout & Missing Dev/Demo Auth Provider (P0)
- **Problem:** Frontend relies strictly on Supabase Auth SDK (`@supabase/supabase-js`), while backend validates JWTs using `core.security.verify_supabase_jwt(token)`. Without a running Supabase container with configured Auth schemas, users cannot generate a valid JWT through the UI.
- **Root Cause:** Next.js `AuthProvider` enforces:
  ```typescript
  if (!session && !isPublicRoute) router.push('/login');
  ```
  And `LoginPage` calls:
  ```typescript
  const { data, error } = await supabase.auth.signInWithPassword({ email, password });
  ```
  Which throws network errors against `http://localhost:54321`.
- **Solution:** 
  1. Add a lightweight dev/demo auth backend endpoint (e.g. `POST /api/auth/demo-login` or dev token endpoint) that generates an HMAC-signed JWT with configured claims (`sub`, `email`, `role`, `faculty_id`) signed with `SUPABASE_JWT_SECRET`.
  2. Enhance `lib/supabase/client.ts` and `lib/auth/context.tsx` to support a **Demo / Fast Login Mode** with one-click selector for demo personas:
     - **Super Admin** (`admin@eduduty.ac.in`)
     - **Exam Coordinator** (`coord@eduduty.ac.in`)
     - **Faculty Member** (`prof.sweta@eduduty.ac.in`, linked to `faculty_id=1`)
     - **Viewer / Auditor** (`viewer@eduduty.ac.in`)
  3. Store the active session in `localStorage` / cookie so both `apiFetch` and `AuthProvider` work seamlessly without requiring external Supabase infrastructure.

---

### Blocker 2: Frontend API Client Disconnect (Raw `fetch` vs `apiFetch`) (P0)
- **Problem:** 7 out of 9 frontend pages define their own local `fetch` function that does not include the Bearer token:
  ```typescript
  // In attendance/tracker, mst-rollcall, follow-up, timetable, settings, dashboard:
  const res = await fetch(`${API}${path}`, init); // NO Authorization header!
  ```
  Consequently, FastAPI's `get_current_user` rejects every request with `HTTP 401 UNAUTHORIZED`.
- **Root Cause:** Pages were developed incrementally without importing the central API client.
- **Solution:** 
  Refactor all 7 pages to import and utilize the unified `@/lib/api` `apiFetch()`. Update `apiFetch` to automatically pull the token from the active session context or local storage, handle 401 refresh/redirect gracefully, and maintain consistent JSON error handling.

---

### Blocker 3: Database Seeding & Demo Data Pipeline (P1)
- **Problem:** `backend/eduduty.db` currently contains 0 rows across all tables. Booting the app results in empty charts, empty dropdowns, and empty tables.
- **Root Cause:** Seeding scripts (`seed_timetable.py`, attendance Excel spreadsheets) exist in the repository but have not been packaged into a reproducible demo seed script.
- **Solution:**
  Create an idempotent seed script (`backend/seed_demo_data.py`) that:
  1. Creates default users (`admin`, `coordinator`, `faculty_vk`, `faculty_tf`, `viewer`).
  2. Runs `seed_timetable.py` logic to populate classes (`CI-1`, `CI-2`, `CY`), faculty (15 members), subjects, and timetable slots.
  3. Creates default rooms (`R-101`, `R-102`, `R-201`, `R-202`) with standard capacities.
  4. Creates upcoming MST exams (`MST-1` and `MST-2` for 3rd and 5th semesters).
  5. Ingests sample attendance records from `CI-1 IV.xlsx` and `CI-2 IV.xlsx`.
  6. Computes initial eligibility records and follow-up states so all dashboard widgets, seat maps, and eligibility tables are rich with real data.

---

### Blocker 4: Missing Mobile Responsive Navigation (P1)
- **Problem:** On screen widths below 768px (`md`), `Sidebar` has `className="hidden md:flex"`. The application becomes completely unusable on mobile devices and small laptop viewports.
- **Root Cause:** No mobile header or hamburger menu sheet was added to `app/layout.tsx`.
- **Solution:**
  Add a responsive mobile navigation bar at the top of `layout.tsx` featuring:
  - EduDuty logo and active page title.
  - Hamburger menu icon triggering a slide-over Sheet drawer containing the navigation links, theme toggle, user badge, and logout button.

---

### Blocker 5: Role-Specific Dashboard Adaptation (P2)
- **Problem:** `/dashboard` hardcodes `mst_exam_id=1` and displays the exact same cards regardless of whether a Super Admin, Exam Coordinator, or Faculty member logs in.
- **Solution:**
  1. Make `/dashboard/stats` dynamically resolve the active exam (or take `?mst_exam_id=`).
  2. Adapt `/dashboard` widgets based on `useAuth().role`:
     - **Exam Coordinator:** Full overview of attendance imports, eligibility rates, duty fill rates, and quick action shortcuts.
     - **Faculty:** Personal invigilation duties, upcoming assigned exam slots, their teaching timetable schedule, and their students' attendance overview.
     - **Super Admin:** System health, audit log summary, database status, and user management shortcuts.

---

### Blocker 6: Setup Documentation & One-Command Launch (P2)
- **Problem:** Missing `README.md` and lack of a single launch command for evaluators.
- **Solution:**
  1. Create a root `README.md` with architectural overview, quickstart instructions, and credentials.
  2. Provide a single PowerShell / bash launch script (`start-dev.ps1` or `npm run dev:all`) that boots FastAPI on `:8000` and Next.js on `:3000`.

---

## 5. Sequenced 24-Hour Implementation Roadmap

To deliver a polished, demonstrable application within 24 hours, the remaining work is divided into 5 focused phases with estimated engineering effort:

```
[Phase 1: Auth Bridge & Token Plumbing] (Hours 1 - 4)  --> P0 Critical
      │
[Phase 2: Frontend API Client Unification] (Hours 5 - 8)  --> P0 Critical
      │
[Phase 3: Database Seeding & Demo Data] (Hours 9 - 11) --> P1 High
      │
[Phase 4: Mobile Navigation & Role Dashboards] (Hours 12 - 15) --> P1 High
      │
[Phase 5: End-to-End Polish & Documentation] (Hours 16 - 18) --> P2 Polish
```

### Phase 1: Authentication Bridge & Demo Provider (Estimated: 3.5 Hours)
- **Task 1.1:** Add `POST /api/auth/demo-token` in backend that generates valid HS256 JWTs signed with `SUPABASE_JWT_SECRET` for predefined roles (`admin`, `coordinator`, `faculty`, `viewer`).
- **Task 1.2:** Update `frontend/src/lib/auth/context.tsx` and `frontend/src/app/login/page.tsx` to provide one-click quick-login buttons for demo personas alongside email/password.
- **Task 1.3:** Ensure token is stored in both `localStorage` and memory so authenticated sessions survive reloads.
- **Deliverable:** Users can log in as any role in 1 click; auth state persists across pages.

### Phase 2: Unify API Client Across All Frontend Pages (Estimated: 3.5 Hours)
- **Task 2.1:** Standardize `frontend/src/lib/api.ts` with automatic Bearer token injection, relative URL handling (`/api/...`), and clear error extraction.
- **Task 2.2:** Refactor `dashboard/page.tsx` to use `apiFetch`.
- **Task 2.3:** Refactor `attendance/upload/page.tsx` to use `apiFetch` (with `FormData` support).
- **Task 2.4:** Refactor `attendance/tracker/page.tsx` to use `apiFetch`.
- **Task 2.5:** Refactor `mst-rollcall/page.tsx` to use `apiFetch`.
- **Task 2.6:** Refactor `follow-up/page.tsx` to use `apiFetch`.
- **Task 2.7:** Refactor `timetable/page.tsx` to use `apiFetch`.
- **Task 2.8:** Refactor `settings/page.tsx` to use `apiFetch`.
- **Task 2.9:** Refactor `components/AIChat.tsx` to use `apiFetch`.
- **Deliverable:** Zero unauthenticated 401 errors across the entire frontend.

### Phase 3: Demo Data Pipeline & Database Seeding (Estimated: 2.5 Hours)
- **Task 3.1:** Create `backend/seed_demo_data.py` (idempotent, safe, preserves existing structures).
- **Task 3.2:** Seed 4 classes, 15 faculty members with timetable legends, 4 exam rooms, and 2 MST exams (`MST-1`, `MST-2`).
- **Task 3.3:** Populate faculty timetable schedule from `timetable_seed.json` and `timetable_entries.json`.
- **Task 3.4:** Seed 60 student records with imported attendance from `CI-1 IV.xlsx` and calculate realistic eligibility records.
- **Task 3.5:** Verify that `backend/eduduty.db` contains populated rows across all tables.
- **Deliverable:** Application boots with rich, realistic data ready for presentation.

### Phase 4: Responsive Mobile Layout & Role Dashboard (Estimated: 3.5 Hours)
- **Task 4.1:** Implement mobile navigation header with hamburger drawer in `frontend/src/app/layout.tsx` using Radix Sheet/Dialog.
- **Task 4.2:** Make tables horizontally scrollable with responsive padding on mobile screens.
- **Task 4.3:** Update `/dashboard/page.tsx` to show role-specific views:
  - Faculty view: "My Assigned Duties", "My Class Attendance Summary", "My Schedule".
  - Coordinator view: "Institution-wide MST Readiness", "Unfilled Duties", "Eligibility Alerts".
- **Deliverable:** Flawless responsive layout on mobile, tablet, and desktop viewports.

### Phase 5: Verification, Documentation & Developer Launch Script (Estimated: 2 Hours)
- **Task 5.1:** Create root `README.md` with project architecture, role matrix, features, and setup instructions.
- **Task 5.2:** Create a one-command dev startup script (`start-dev.ps1` / `npm run dev`) that boots FastAPI on 8000 and Next.js on 3000 concurrently.
- **Task 5.3:** Perform end-to-end user journey smoke tests across all 10 pages in the browser.
- **Deliverable:** Complete, demonstrably functioning product with clean documentation.

---

## 6. Definition of Done for 24-Hour Release

The 24-hour product completion will be declared complete when all of the following criteria are satisfied:
1. **One-Click Demo Authentication:** Any user can open `http://localhost:3000`, select a demo persona (Coordinator, Faculty, Admin), and immediately enter the portal.
2. **Zero 401 Errors:** All 10 frontend pages communicate with FastAPI using authenticated Bearer tokens with zero unhandled network or authorization errors.
3. **End-to-End Workflow Verification:**
   - [x] Upload Excel attendance sheet and see records processed.
   - [x] Generate seating arrangement and view interleaved seat map.
   - [x] Toggle student attendance in seat map and roll call.
   - [x] Review eligibility percentages and apply a coordinator override.
   - [x] View VT candidates and update follow-up statuses.
   - [x] Run auto-scheduling for exam duties and accept proposals.
   - [x] Query AI Assistant for attendance/duty data and download PDF report.
   - [x] View and modify faculty timetable and check availability grid.
4. **Mobile Responsive:** All pages and navigation drawers display cleanly on screens down to 375px width.
5. **Safe & Clean State:** All 86 SQLite tests and 93 PostgreSQL tests continue to pass 100%. `backend/eduduty.db` and SecureMailScope Docker assets remain preserved.

---

## 7. Immediate Next Step

With this triage complete, all highest-priority blockers, architectural root causes, and estimated tasks have been documented. 

**Recommended immediate action upon approval:** Begin **Phase 1** (Authentication Bridge & Demo Provider) followed by **Phase 2** (API Client Unification) to unlock full frontend-to-backend communication.
