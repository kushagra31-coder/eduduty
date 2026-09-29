# MST Operations Portal — Full Plan

## 1. Problem

Department currently runs MST (midterm) attendance eligibility, seating, and
invigilation duty entirely on paper: printed attendance sheets, physical
signatures, manual eligibility checks, manual duty rosters. No single source
of truth, no audit trail, error-prone at 80-students-per-class scale.

## 2. Goal

One web portal, per department, covering:
1. Attendance import → eligibility calculation
2. MST-1 / MST-2 event management (seating, exam-day marking)
3. Faculty timetable-aware invigilation duty scheduling
4. Edit/replace workflow with full audit trail
5. VT (remedial exam) determination
6. Read-only local AI for natural-language queries over the data

## 3. Non-negotiable design rule

**Three states are tracked separately and never collapsed into one field:**

| State | What it answers | Depends on |
|---|---|---|
| MST eligibility | Can this student sit the exam? | Attendance % (+ optional override) |
| MST appearance | Did they actually sit it? | Exam-day marking |
| VT status | Do they need the remedial exam? | Appearance in MST-1 **and** MST-2 |

A student can be eligible-but-absent, ineligible-but-approved, or
appeared-in-MST-1-only. The system must represent all of these without
losing information.

---

## 4. Core entities

(Full column-level detail lives in `schema.sql` — this is the relationship map.)

- **classes** — CI-1, CI-2, Cyber-3, CS-81, etc. Has `year` (2/3/4).
- **students** — keyed by `roll_number` (never name). Belongs to a class,
  has a `batch_number` + `pair_seat` (L/R) for exam pairing.
- **faculty** — `exempt_from_duty` flag + reason, `max_duties_per_day`.
- **subjects**
- **attendance_records** — one row per faculty/subject/student/semester
  upload; `attendance_pct` is computed, not stored raw.
- **mst_exams** — one row per (MST-1 or MST-2) × class × date/slot.
- **mst_eligibility** — one row per student × mst_exam. Status +
  override fields.
- **mst_attempts** — one row per student × mst_exam. Actual exam-day
  outcome (Present/Absent/Late/Excused/Signature missing), who marked it,
  when.
- **rooms**, **seats** — seating per mst_exam, left/right student per bench.
- **faculty_timetable** — one row per faculty × day × time_slot × class ×
  **year** (this is the field the clash-checker reads — see §6).
- **invigilation_duties** — one row per mst_exam × room, assigned faculty
  or unfilled.
- **duty_replacements** — append-only log of every reassignment, never
  overwrites the original.
- **audit_logs** — generic before/after/who/when/why log for every
  editable field in the system.
- **users** — role-based accounts (Admin/HOD, Exam Coordinator, Faculty,
  Invigilator, AI read-only).
- **system_rules** — key/value config table so thresholds and the VT rule
  are editable without a code change.

---

## 5. Business rules

### 5.1 Attendance eligibility
```
attendance_pct = classes_attended / classes_conducted × 100
```
- **≥ 50%** → Eligible
- **45%–49.99%** → Borderline (still flagged for review, shown distinctly)
- **< 45%** → Not eligible
- **No data uploaded** → Missing (grey, blocks nothing automatically, just
  flags for follow-up)
- Both **overall** and **subject-wise** percentages are computed and shown;
  eligibility is based on overall, but the lowest subject % is always
  visible next to it.
- Ineligibility is **never a hard block**. An HOD/coordinator can Override,
  which requires a typed reason and is logged to `audit_logs`.

### 5.2 MST appearance
- Independent of eligibility. An eligible student can still be marked
  Absent; an overridden/approved student can still appear.
- Every mark is an event, not just a final flag: student, exam, room,
  seat, status, marked-by, marked-at. This is what makes the audit trail
  possible.

### 5.3 VT (remedial exam) — **confirmed rule**
- **Mandatory** only if the student **missed both** MST-1 and MST-2.
- Appearing in **at least one** of the two → **no VT**.
- An **approved absence** (medical leave, HOD override) does **not**
  exempt the student from VT — approval affects eligibility bookkeeping,
  not the VT trigger.
- Implemented as a config row in `system_rules` (`vt_rule =
  compulsory_if_both_mst_missed`) so the rule can change later without a
  schema migration.

### 5.4 Faculty invigilation duty — clash detection
A faculty member is **assignable** to a given MST slot only if **all** of
the following are true:
1. No regular class during that slot, **in any year** — this is the rule
   that's easy to get wrong: a faculty member is blocked by a **third-year
   or final-year** class even when only **second-year** students are
   sitting the MST. The checker must read the faculty's full timetable
   across every year they teach, not just the years taking the exam.
2. No other MST/exam duty already assigned in that slot.
3. Not on the exemption list (e.g. HOD, or any admin-excluded faculty).
4. Not marked absent/unavailable for that date.
5. Under their configured max-duties-per-day.

For every faculty member, the scheduler must be able to show **why** they
were blocked, not just that they were — e.g. "Blocked — third-year class
10:00–11:00", not just "Blocked". This is a hard requirement, not a
nice-to-have: it's what makes the tool trustworthy to a human reviewing
the roster.

### 5.5 Editing / replacement
- Every editable record (eligibility override, appearance status, seat
  assignment, duty assignment, timetable, exam date/time, room capacity,
  exemption list, thresholds, VT rule) requires: previous value, new
  value, who changed it, when, and a reason.
- Duty replacement specifically: original assignment is **never deleted**,
  only superseded — old and new both remain queryable via
  `duty_replacements`.

### 5.6 Local AI assistant
- **Read-only in v1.** No write path from the AI into any table.
- Runs locally (Ollama) — data never leaves the department's
  infrastructure.
- Talks only to a dedicated read-only DB role, ideally through pre-approved
  views (like `ai_eligibility_summary`) rather than raw table access, so
  it can't be prompted into a full-table dump.
- Answers with aggregated results (counts, filtered small tables), not
  raw per-student rows, unless the requesting user's role permits it.
- Row/time limits on generated queries; no access to `users`/auth data or
  `audit_logs` internals.

---

## 6. Workflows

**Attendance import**
Faculty uploads Excel → system parses & matches roll numbers → shows
invalid/duplicate rows → coordinator approves → eligibility recalculated
→ previous version retained for audit.

**MST eligibility → seating → exam day**
Eligibility computed → coordinator reviews/overrides borderline & missing
cases → batches paired (roll-number order, 2 per bench) → room/seat
assigned per batch → printable seating chart + signature sheet generated
→ on exam day, invigilator marks each student's actual status → results
feed both the absentee dashboard and the VT calculation.

**Duty scheduling**
Exam slots + rooms defined → clash-checker runs against full timetable →
available/blocked/exempt list generated with reasons → coordinator
assigns (or accepts auto-suggested) faculty → if someone is absent on the
day, coordinator opens Replace → sees only currently-available faculty →
picks replacement + reason → old assignment logged, new one published.

**VT determination**
After both MSTs are closed: for each student, check `mst_attempts` for
MST-1 and MST-2 → if both are Absent/no-record → status = Compulsory VT →
otherwise Not required. Recompute automatically whenever a late appearance
correction is made (with audit trail).

---

## 7. Roles

| Role | Can do |
|---|---|
| Admin / HOD | Everything, incl. exemption list & threshold config |
| Exam Coordinator | Import attendance, approve overrides, manage seating & duty, replace faculty |
| Faculty | View own duty, own timetable, own students' attendance |
| Invigilator | Mark exam-day attendance for their assigned room only |
| AI (read-only) | Query approved views only, no writes |

---

## 8. Tech stack

- **Frontend:** Next.js + TypeScript + Tailwind + shadcn/ui
- **Backend:** Next.js API routes (CRUD) + Python FastAPI (Excel parsing,
  OR-Tools scheduling, AI query service)
- **Database:** PostgreSQL (Supabase for auth/storage, or self-hosted)
- **Excel:** SheetJS (JS) or Pandas (Python) for import/validation
- **Scheduling:** Google OR-Tools — clash detection is a constraint
  problem (hard constraints: no double-booking, no year-agnostic class
  clash, no exempt assignment; soft constraints: fair duty distribution,
  avoid consecutive duties)
- **PDF:** PDFKit / Puppeteer for seating charts & signature sheets
- **Local AI:** Ollama + a small instruction model (Gemma/Qwen), read-only
  DB role
- **Deployment:** Docker on a department/college server

---

## 9. Build phases

**Phase 1 — Core**
Login/roles · student & faculty import · class/batch setup · attendance
Excel upload · eligibility dashboard · MST-1/MST-2 records · present/absent
marking.

**Phase 2 — Exam operations**
Room/seat creation · batch pairing · printable seating chart & signature
sheet · absentee/compulsory lists · VT rule engine.

**Phase 3 — Faculty scheduling**
Full all-year timetable import · exemption config · clash detection ·
auto duty assignment (OR-Tools) · manual edit/replace workflow · audit
history.

**Phase 4 — Local AI**
Natural-language reporting over approved views · charts/exports ·
(optional, later) voice input.

Do not build Phase 4 before Phases 1–3 are correct — the AI is only as
trustworthy as the data underneath it.

---

## 10. Edge cases the system must handle correctly

- Student has attendance for some subjects but not others → subject-wise
  gaps shown, overall % still computable from what exists, "Missing"
  status only if there's no data at all.
- Student changes class/section mid-semester → batch/seat reassignment
  needed without losing MST-1 history tied to the old class.
- Faculty teaches across multiple years with overlapping-looking but
  distinct time slots → clash-checker must match on exact slot, not just
  "has a class that day".
- Two faculty members both marked absent on the same exam day →
  replacement workflow must handle multiple simultaneous replacements
  without room-duty gaps.
- MST-2 seating differs from MST-1 (different room, same class) →
  MST-2's seating plan is a distinct record, optionally cloned from MST-1
  and edited, never assumed identical.
- A student marked "Eligible" then later found ineligible after a
  corrected attendance upload → eligibility recalculation must not
  silently overwrite a prior signed-off exam-day appearance record.
- Override approvals must require a reason every time — no silent
  overrides, even by Admin/HOD.

---

## 11. Data still needed before real data replaces the mock prototype

- MST-1 / MST-2 dates, time slots, rooms, and which classes sit each
- Full timetable for second, third, and final year (not just second year)
- A sample attendance Excel sheet exactly as faculty currently produce it
- Final exemption list (currently: HOD Vandana ma'am + one more faculty —
  confirm full list and reasons)
- Confirmation attendance threshold is overall, subject-wise, or both
- Room capacities and per-room invigilator counts required
