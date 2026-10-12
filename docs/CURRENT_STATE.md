# EduDuty — Current-State Architecture & Baseline Report

**Date:** October 6, 2026  
**Status:** Complete  
**Scope:** Phase 0 Baseline Audit  

---

## 1. Repository Structure & Artifact Mapping

The existing repository contains a prototype implementation of the EduDuty platform. Below is the file-level structural breakdown:

```text
eduduty/
├── PRD (1).md                         # Authoritative Product Requirements Document
├── architecture (1).md                # Authoritative Target System Architecture
├── schema.sql                         # Raw PostgreSQL DDL schema (Out of sync with models.py)
├── timetable_migration.sql            # Migration script for extended timetable fields
├── timetable_backend_additions.py     # Script helper for timetable seeding
├── timetable-page.tsx                 # Draft/Standalone frontend timetable component
├── mst-portal-plan.md                 # Prototype development notes
├── CI-1 IV.xlsx, CI-1 VI.xlsx...      # Sample institutional attendance Excel sheets (6 files)
├── ci 1 sem 3.jpeg, cy 3rd year.jpeg  # Timetable source image references (5 files)
├── backend/
│   ├── .env                           # Environment configuration
│   ├── main.py                        # FastAPI application entry point & router definitions (1,475 lines)
│   ├── models.py                      # SQLAlchemy ORM model definitions (192 lines)
│   ├── schemas.py                     # Pydantic schemas for request/response validation (173 lines)
│   ├── crud.py                        # Database CRUD & business logic service routines (652 lines)
│   ├── database.py                    # Database connection setup & fallback logic (57 lines)
│   ├── ai_service.py                  # LLM integration provider chain & AI routing (445 lines)
│   ├── pdf_service.py                 # HTML/WeasyPrint PDF rendering engine (384 lines)
│   ├── apply_schema.py                # Schema application helper script (30 lines)
│   ├── seed_timetable.py              # Timetable JSON importer script (224 lines)
│   ├── requirements.txt               # Python package dependencies
│   ├── eduduty.db                     # Active local SQLite database file
│   └── timetable_entries.json         # Seed timetable entries
└── frontend/
    ├── package.json                   # Next.js 14 frontend dependencies
    ├── next.config.mjs                # Next.js configuration with backend rewrite proxy
    ├── tailwind.config.ts             # Tailwind CSS configuration
    └── src/
        ├── app/                       # Next.js App Router pages
        │   ├── page.tsx               # Root redirect / landing
        │   ├── login/page.tsx         # Mock login screen
        │   ├── dashboard/page.tsx     # Operations dashboard
        │   ├── attendance/            # Attendance upload & seat map pages
        │   ├── eligibility/page.tsx   # Student eligibility management page
        │   ├── follow-up/page.tsx     # VT / Follow-up management page
        │   ├── duties/page.tsx        # Invigilation duty scheduler page
        │   ├── mst-rollcall/page.tsx  # Fast roll call attendance page
        │   ├── timetable/page.tsx     # Faculty & class timetable grid page
        │   ├── ai/page.tsx            # AI assistant interface page
        │   └── settings/page.tsx     # Master data & system settings page
        ├── components/
        │   ├── Sidebar.tsx            # Navigation sidebar component
        │   ├── AIChat.tsx             # Floating/page AI chat component
        │   └── AIHealthBanner.tsx     # AI provider health indicator widget
        └── lib/
            └── supabase/client.ts     # Client-side Supabase stub
```

---

## 2. Actual Technology Stack

### Frontend
- **Framework:** Next.js `14.2.35` (App Router)
- **Language:** TypeScript `^5`
- **UI Framework:** Tailwind CSS `^3.4.1`, Radix UI / shadcn (`@base-ui/react`, `lucide-react`)
- **State Management:** React local state (`useState`, `useEffect`), native `fetch` API.
- **Client Validation:** Minimal client validation; uses standard HTML inputs & custom components.

### Backend
- **Framework:** FastAPI `0.141.1`
- **Language:** Python `3.11`
- **ORM:** SQLAlchemy `2.0.54`
- **Data Processing:** Pandas `3.0.6`, OpenPyXL `3.1.5`
- **PDF Generation:** WeasyPrint (with HTML/CSS templates in `pdf_service.py`)
- **Validation:** Pydantic `2.13.5`
- **Authentication:** **NOT IMPLEMENTED** (Mock login page only; backend defaults to `user_id = 1`).

### Database
- **Engine:** SQLite (`eduduty.db` local fallback) / PostgreSQL (via `psycopg2-binary` or `psycopg` connector).
- **Schema Strategy:** `Base.metadata.create_all()` in `backend/main.py`.
- **Migration Strategy:** **NONE** (No Alembic integration exists; loose SQL scripts `schema.sql` and `timetable_migration.sql` exist in project root).

### AI Integration
- **Providers Supported:** Multi-provider fallback chain:
  1. Groq Cloud API (`GROQ_API_KEY`)
  2. Google Gemini API (`GEMINI_API_KEY`)
  3. Local Ollama (`http://localhost:11434`)
- **Capabilities:**
  - **Read:** NL to SQL over 5 specific database views (`ai_eligibility_summary`, `ai_attendance_summary`, `ai_vt_candidates`, `ai_duty_roster`, `v_vt_follow_up_status`).
  - **Write:** NL to structured operation proposal (`override_eligibility`, `mark_attempt_status`, `assign_duty`). Requires explicit frontend confirmation before execution via `execute_write_op()`.

---

## 3. High-Level Current Architecture

```text
               ┌────────────────────────────────────────┐
               │           User Web Browser             │
               └───────────────────┬────────────────────┘
                                   │
                         HTTP / REST API Requests
                                   │
                                   ▼
               ┌────────────────────────────────────────┐
               │    Next.js 14 Web Application          │
               │   (Client-side fetch / App Router)     │
               └───────────────────┬────────────────────┘
                                   │
                     Proxy Rewrite / Direct HTTP
                                   │
                                   ▼
               ┌────────────────────────────────────────┐
               │           FastAPI Backend              │
               │      (backend/main.py : 8000)          │
               └───────┬───────────┬───────────┬────────┘
                       │           │           │
       ┌───────────────┘           │           └──────────────┐
       ▼                           ▼                          ▼
┌──────────────┐            ┌──────────────┐           ┌──────────────┐
│  SQLAlchemy  │            │  AI Service  │           │ PDF Service  │
│ CRUD Layer   │            │ (ai_service) │           │ (pdf_service)│
└──────┬───────┘            └──────┬───────┘           └──────────────┘
       │                           │
       ▼                           ▼
┌──────────────┐            ┌──────────────┐
│ SQLite DB /  │            │ Groq/Gemini/ │
│ PostgreSQL   │            │ Ollama LLM   │
└──────────────┘            └──────────────┘
```

---

## 4. End-to-End Data Flow Traces

### 4.1 Authentication & Session Flow

```text
Login Page UI (/login)
        │
        ▼ (User submits credentials - static form)
  No Backend API Hit
        │
        ▼
Default Backend Context:
  Hardcoded user_id = 1 (backend/main.py:620, backend/crud.py:51)
  Zero Session Management / Zero JWT Validation
```
- **Files:** `frontend/src/app/login/page.tsx`, `backend/main.py`
- **Endpoints:** None. Protected API routes do not inspect HTTP headers for authorization tokens.

---

### 4.2 Attendance Upload & Import Flow

```text
User uploads Excel file (.xlsx)
        │
        ▼
POST /upload-attendance/ (backend/main.py:419)
        │
        ▼
_import_subject_workbook() (backend/main.py:322)
  ├── _parse_subject_sheet() (Parses faculty name, subject code, enrollment numbers, attendance counts)
  ├── _get_or_create_subject() & _get_or_create_faculty()
  ├── Replaces old AttendanceRecord entries for same file + subject (Idempotent)
  ├── Computes student batch numbers (splits class 50/50 by roll number)
  ├── compute_eligibility_for_student() (recalculates eligibility)
  └── Writes AuditLog entry ("table_name": "attendance_records")
```
- **Files:** `backend/main.py#L419-L514`, `backend/crud.py#L74-L119`
- **Endpoints:** `POST /upload-attendance/`

---

### 4.3 Eligibility Calculation & Override Flow

```text
Attendance Records Ingested
        │
        ▼
crud.compute_eligibility_for_student() (backend/crud.py:74)
  ├── Sums total conducted & attended classes across subjects
  ├── Calculates overall_pct and lowest_subject_pct
  ├── Evaluates status:
  │     overall_pct >= 50%     → 'Eligible'
  │     45% <= overall_pct < 50% → 'Borderline'
  │     overall_pct < 45%      → 'Not eligible'
  │     conducted == 0         → 'Missing'
  └── Saves/updates record in `mst_eligibility` table

Human Override Action:
POST /eligibility/override/{eligibility_id} (backend/main.py:613)
  ├── Updates `mst_eligibility.override = True`, `override_reason`, `override_by = 1`
  └── Inserts row into `audit_logs`
```
- **Files:** `backend/crud.py#L22-L119`, `backend/main.py#L609-L625`
- **Endpoints:** `GET /eligibility/{mst_exam_id}`, `POST /eligibility/override/{eligibility_id}`

---

### 4.4 Seating Generation Flow

```text
Coordinator triggers seating generation
        │
        ▼
POST /mst/seating/generate (backend/main.py:893)
  ├── Clears existing `seats` for `mst_exam_id`
  ├── Fetches active students for class; sorts naturally by roll number
  ├── Groups students into Batch 1 and Batch 2
  ├── Pairs Batch 1 roll `n` with Batch 2 roll `n` using itertools.zip_longest
  ├── Iterates over selected `rooms` (capacity = 30 default)
  └── Creates `Seat` records with `left_student` & `right_student` FKs
```
- **Files:** `backend/main.py#L893-L940`
- **Endpoints:** `POST /mst/seating/generate`, `GET /mst/seating/{mst_exam_id}`

---

### 4.5 Invigilation Scheduling Flow

```text
Coordinator requests duty proposal
        │
        ▼
POST /mst/duties/auto-schedule (backend/main.py:1253)
  ├── Calls crud.propose_invigilation_duties() (backend/crud.py:477)
  ├── Determines exam time slot & day of week
  ├── Iterates over rooms; checks candidate faculty against hard constraints:
  │     1. f.exempt_from_duty == False
  │     2. No class timetable clash (FacultyTimetable overlap)
  │     3. No existing duty overlap in DB or current proposal
  │     4. Daily duty limit not exceeded (max_duties_per_day)
  ├── Picks free candidate with lowest total assigned duties (workload balance)
  └── Returns proposal JSON with audit explanations for rejected candidates

Coordinator approves proposal:
POST /mst/duties/auto-schedule/apply (backend/main.py:1266)
  ├── Saves assignments to `invigilation_duties` table
  └── Writes `AuditLog` entry per assigned duty slot
```
- **Files:** `backend/crud.py#L477-L651`, `backend/main.py#L1253-L1273`
- **Endpoints:** `GET /mst/duties/{mst_exam_id}`, `POST /mst/duties/assign`, `POST /mst/duties/auto-schedule`, `POST /mst/duties/auto-schedule/apply`

---

### 4.6 VT / Follow-Up Flow

```text
Student attendance marked or recalculated
        │
        ▼
crud.recalculate_follow_up() (backend/crud.py:275)
  ├── Checks MST-1 and MST-2 attempt records (`mst_1_appeared`, `mst_2_appeared`)
  ├── Evaluates rule `absent-both-mst-v1`:
  │     mst1 == False AND mst2 == False → 'compulsory'
  │     mst1 is None OR mst2 is None    → 'under_review' (missing != absent)
  │     otherwise                       → 'not_required'
  ├── Updates `follow_up_statuses` table (`calculated_status`, `final_status`)
  └── Writes audit log if `calculated_status` changed

Human Override / Restore:
  POST /follow-up/{id}/override → sets final_status to 'excused'/'completed' with reason
  POST /follow-up/{id}/restore  → restores calculated_status as final_status
```
- **Files:** `backend/crud.py#L218-L432`, `backend/main.py#L1040-L1208`
- **Endpoints:** `GET /follow-up`, `POST /follow-up/recalculate`, `POST /follow-up/{id}/override`, `POST /follow-up/{id}/restore`, `GET /follow-up/export-pdf`

---

### 4.7 AI Query & Controlled Write Flow

```text
User submits natural language prompt
        │
        ▼
POST /ai/query (backend/main.py:634)
  ├── ai_service.handle_ai_message() (backend/ai_service.py:377)
  ├── Intent Classification:
  │     A. PDF Intent ("pdf", "report", "download")
  │        └── Returns direct PDF route link
  │
  │     B. Write Intent ("override", "mark", "assign", "set")
  │        ├── Calls LLM with WRITE_SYSTEM_PROMPT
  │        ├── Returns structured JSON proposal (e.g., {"operation": "override_eligibility", ...})
  │        └── Frontend displays confirmation modal (NO DB changes yet)
  │
  │     C. Read Intent (Default Q&A)
  │        ├── Calls LLM with READ_SYSTEM_PROMPT to generate SELECT query
  │        ├── _validate_read_sql() validates query against 5 allowed views
  │        ├── Executes query against database views
  │        └── LLM formats response into plain English
  │
Explicit User Confirmation (Write Path):
POST /ai/confirm-write (backend/main.py:646)
  └── execute_write_op() executes typed ORM operation + inserts AuditLog record
```
- **Files:** `backend/ai_service.py#L1-L445`, `backend/main.py#L628-L658`, `frontend/src/components/AIChat.tsx`
- **Endpoints:** `POST /ai/query`, `POST /ai/confirm-write`, `GET /ai/health`
