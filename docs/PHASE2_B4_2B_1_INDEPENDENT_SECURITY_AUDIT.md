# EduDuty Phase 2 — Stage B4.2B.1: Independent PostgreSQL RLS Security Audit

**Audit Date:** October 11, 2026  
**Auditor:** Independent Security Evaluation Agent  
**Target:** Phase 2, Stage B4.2B PostgreSQL Row-Level Security & Identity Context  
**Database Target:** `eduduty_pg_b4_test` (`127.0.0.1:5433`, PostgreSQL 16)  
**Database Head Revision:** `007_implement_faculty_rls`  

---

## 1. Executive Verdict

### **VERDICT: CRITICAL — FAIL**

**Summary Justification:**  
While Stage B4.2B implemented PostgreSQL Row-Level Security policies and passed all 18 positive and negative test cases within its test runner, the database identity context mechanism (`app.current_faculty_id`, `app.current_user_role`) **fails the fundamental database trust boundary requirement**. 

Specifically:
- PostgreSQL custom configuration parameters (`app.*`) can be arbitrarily set or modified by the unprivileged `ai_reader` database connection via `set_config()` or `SET LOCAL`.
- The database engine possesses **no cryptographic or server-side authorization check** verifying whether the `ai_reader` connection is authorized to assume the identity it asserts.
- An attacker with direct query capability under `ai_reader` (e.g. via direct database access or any SQL injection path) can unilaterally execute:
  ```sql
  SELECT set_config('app.current_user_role', 'super_admin', true);
  ```
  and instantly bypass all student and class RLS policies, retrieving 100% of student, eligibility, and timetable data across the institution.
- Similarly, an attacker can execute:
  ```sql
  SELECT set_config('app.current_faculty_id', '<target_faculty_id>', true);
  ```
  to impersonate any faculty member in the system and read their assigned students.

Application-level regex sanitization (`_validate_read_sql`) is an application-tier control, **not a database-tier security boundary**. Because the database identity context can be trivially spoofed directly at the SQL layer, this stage cannot be certified for production readiness until a secure cryptographic or database-enforced identity binding is implemented.

---

## 2. Findings Summary Matrix

| ID | Severity | Category | Title | Status |
| :--- | :--- | :--- | :--- | :--- |
| **SEC-B42B-01** | **CRITICAL** | Authorization / IDOR | Arbitrary Context Manipulation & Privilege Escalation via `set_config` | **Confirmed (Live PoC)** |
| **SEC-B42B-02** | **HIGH** | Function Security | `SECURITY DEFINER` Functions Use Unqualified Table References and Include `pg_temp` | **Confirmed** |
| **SEC-B42B-03** | **MEDIUM** | Information Disclosure | `PUBLIC` Execution of Helper Functions Enables Faculty-to-Class Oracle Probing | **Confirmed** |
| **SEC-B42B-04** | **LOW** | Policy Hardening | Protected Tables Lack `FORCE ROW LEVEL SECURITY` | **Confirmed** |

---

## 3. Detailed Audit Findings

### SEC-B42B-01: [CRITICAL] Arbitrary Context Manipulation & Privilege Escalation via `set_config`

- **Affected Files:**
  - `backend/alembic/versions/007_implement_faculty_rls.py:40-45, 91-96, 141-146`
  - `backend/ai_service.py:388-396, 767-775`
- **Description:**
  Migration 007's helper functions derive identity and authorization exclusively from PostgreSQL GUC parameters:
  ```sql
  cur_role := LOWER(COALESCE(current_setting('app.current_user_role', true), ''));
  cur_faculty_id := current_setting('app.current_faculty_id', true)::int;
  ```
  In PostgreSQL, custom configuration parameters in user namespaces (like `app.*`) are not privileged. Any role permitted to connect and run queries (including the read-only `ai_reader` role) has the built-in capability to call `set_config()` or `SET LOCAL`.
- **Live Proof of Concept (PoC):**
  A disposable live fixture was seeded with Faculty A (id 901, assigned to Class A, student 701) and Faculty B (id 902, assigned to Class B, student 702). Under a direct `ai_reader` connection:
  1. *Legitimate Faculty A Context:*
     ```sql
     SELECT set_config('app.current_faculty_id', '901', true), set_config('app.current_user_role', 'faculty', true);
     SELECT id, roll_number, name FROM students;
     -- Result: [(701, 'R-A1', 'Student A')]
     ```
  2. *Forged Faculty B Context:*
     ```sql
     SELECT set_config('app.current_faculty_id', '902', true);
     SELECT id, roll_number, name FROM students;
     -- Result: [(702, 'R-B1', 'Student B')]  <-- UNAUTHORIZED CROSS-CLASS READ
     ```
  3. *Escalation to Super Admin:*
     ```sql
     SELECT set_config('app.current_user_role', 'super_admin', true);
     SELECT id, roll_number, name FROM students;
     -- Result: [(701, 'R-A1', 'Student A'), (702, 'R-B1', 'Student B')] <-- FULL INSTITUTION-WIDE BYPASS
     ```
- **Architectural Flaw:**
  The B4.2B implementation conflated application-tier injection hygiene with database trust boundaries. The application regex (`_validate_read_sql`) blocks `SET` and `SET_CONFIG`, but if an attacker accesses PostgreSQL or finds any query interpolation bypass, the database trust boundary collapses instantly.

---

### SEC-B42B-02: [HIGH] `SECURITY DEFINER` Functions Use Unqualified Table References and Include `pg_temp`

- **Affected Files:**
  - `backend/alembic/versions/007_implement_faculty_rls.py:28-76, 78-128, 130-151`
- **Description:**
  All three helper functions (`can_current_user_access_class`, `can_current_user_access_student`, `can_current_user_access_duty_roster`) are defined as `SECURITY DEFINER` and owned by `postgres` (superuser).
  However:
  1. The function specifies `SET search_path = public, pg_temp;`. In PostgreSQL security guidance, `pg_temp` should be explicitly excluded from `SECURITY DEFINER` functions unless temporary tables are intentionally required.
  2. Tables inside the function bodies are unqualified:
     ```sql
     FROM faculty_timetable ft
     JOIN timetable_versions tv ON tv.id = ft.timetable_version_id
     ```
     instead of `FROM public.faculty_timetable ft JOIN public.timetable_versions tv`.
- **Risk:**
  Running `SECURITY DEFINER` as superuser with unqualified object references creates privilege escalation risks if any schema in the search path is writable or if object resolution behaves unexpectedly under non-standard configurations.

---

### SEC-B42B-03: [MEDIUM] `PUBLIC` Execution of Helper Functions Enables Faculty-to-Class Oracle Probing

- **Affected Files:**
  - `backend/alembic/versions/007_implement_faculty_rls.py:154-156`
- **Description:**
  Migration 007 explicitly grants execution on all helper functions to `PUBLIC`:
  ```sql
  GRANT EXECUTE ON FUNCTION can_current_user_access_class(int) TO PUBLIC;
  GRANT EXECUTE ON FUNCTION can_current_user_access_student(int) TO PUBLIC;
  GRANT EXECUTE ON FUNCTION can_current_user_access_duty_roster() TO PUBLIC;
  ```
- **Risk:**
  Combined with the caller-writable `app.current_faculty_id` setting, any connected user can query:
  ```sql
  SELECT c.id, c.name, can_current_user_access_class(c.id) FROM classes c;
  ```
  Iterating through faculty IDs allows an unauthorized caller to map out every class assigned to every faculty member in the institution, converting the security helper into an enumeration oracle.

---

### SEC-B42B-04: [LOW] Protected Tables Lack `FORCE ROW LEVEL SECURITY`

- **Affected Files:**
  - `backend/alembic/versions/007_implement_faculty_rls.py:159-163`
- **Description:**
  The migration executes `ALTER TABLE <name> ENABLE ROW LEVEL SECURITY;`, which sets `relrowsecurity = true` but leaves `relforcerowsecurity = false`.
- **Risk:**
  Table owners (`postgres` or `eduduty_user`) automatically bypass RLS on all operations. If an operational error, configuration mistake, or connection pool fallback causes reporting queries to execute under the table owner's credentials instead of `ai_reader`, RLS is silently bypassed without warning.

---

## 4. Live PostgreSQL Catalog Evidence

Catalog inspection executed directly against live PostgreSQL 16 container (`eduduty_pg_b4_test`):

### 4.1 Roles & Privileges
```
Role: ai_reader    | super=False | inherit=False | createrole=False | createdb=False | login=True | bypassrls=False
Role: postgres     | super=True  | inherit=True  | createrole=True  | createdb=True  | login=True | bypassrls=True
Role: eduduty_user | super=False | inherit=True  | createrole=False | createdb=False | login=True | bypassrls=False
```
*Verification:* `ai_reader` correctly has `bypassrls=False` and `super=False`.

### 4.2 Table Ownership & RLS Flags
```
Table: classes             | Owner: postgres | RLS: True | FORCE RLS: False
Table: follow_up_statuses  | Owner: postgres | RLS: True | FORCE RLS: False
Table: invigilation_duties | Owner: postgres | RLS: True | FORCE RLS: False
Table: mst_eligibility     | Owner: postgres | RLS: True | FORCE RLS: False
Table: students            | Owner: postgres | RLS: True | FORCE RLS: False
Table: faculty_timetable   | Owner: postgres | RLS: False| FORCE RLS: False
Table: timetable_versions  | Owner: postgres | RLS: False| FORCE RLS: False
```
*Verification:* RLS is enabled on all 5 sensitive tables, but `FORCE RLS` is `False`.

### 4.3 Helper Function Catalog Details
```
Function: can_current_user_access_class   | Owner: postgres | SecDef: True | Config: ['search_path=public, pg_temp'] | ACL: {=X/postgres,postgres=X/postgres}
Function: can_current_user_access_student | Owner: postgres | SecDef: True | Config: ['search_path=public, pg_temp'] | ACL: {=X/postgres,postgres=X/postgres}
Function: can_current_user_access_duty_roster | Owner: postgres | SecDef: True | Config: ['search_path=public, pg_temp'] | ACL: {=X/postgres,postgres=X/postgres}
```
*Verification:* Helper functions execute as superuser (`postgres`) and are granted to PUBLIC (`=X/postgres`).

### 4.4 Reporting Views & Security Invoker
```
View: ai_eligibility_summary    | Owner: postgres | Options: ['security_invoker=true']
View: ai_attendance_summary     | Owner: postgres | Options: ['security_invoker=true']
View: ai_vt_candidates          | Owner: postgres | Options: ['security_invoker=true']
View: ai_duty_roster            | Owner: postgres | Options: ['security_invoker=true']
View: v_vt_follow_up_status     | Owner: postgres | Options: ['security_invoker=true']
```
*Verification:* All 5 views enforce `security_invoker = true`.

---

## 5. Test Suite Verification & Results

### 5.1 Stage B4.2B Integration Tests (`test_postgres_rls_b42b.py`)
- **Execution Command:**
  ```powershell
  $env:PG_TEST_PASSWORD = $(docker exec eduduty_pg_b4_test printenv POSTGRES_PASSWORD)
  $env:EDUDUTY_REQUIRE_POSTGRES_TESTS = "1"
  python -m pytest backend/tests/test_postgres_rls_b42b.py -v
  ```
- **Result:** **18 Passed, 0 Failed, 0 Skipped** (Duration: 1.71s).
- **Audit Assessment:**
  The test suite proves that *when the application correctly sets context and does not attempt to change it*, RLS filters rows as specified. However, the test suite **failed to test adversarial modification of the context by `ai_reader` itself**, which allowed the spoofing vulnerability (SEC-B42B-01) to escape undetected.

### 5.2 Full PostgreSQL Integration Suite
- **Execution Command:**
  ```powershell
  python -m pytest backend/tests/test_postgres_rls_b42b.py backend/tests/test_alembic_b42a_ai_reader.py backend/tests/test_postgres_connection_b412.py backend/tests/test_postgres_gating.py -v
  ```
- **Result:** **48 Passed, 0 Failed, 0 Skipped** (Duration: 6.22s).

### 5.3 SQLite Regression Suite
- **Execution Command:**
  ```powershell
  python -m pytest backend/tests/test_auth.py backend/tests/test_rbac.py backend/tests/test_resource_authorization.py backend/tests/test_upload_attendance.py backend/tests/test_identity_spoofing.py backend/tests/test_ai_read_isolation.py -v
  ```
- **Result:** **38 Passed, 0 Failed, 0 Skipped** (Duration: 3.22s).
- `backend/tests/test_alembic_b33_auth.py`: **28 Passed, 0 Failed, 0 Skipped** (Duration: 5.09s).

---

## 6. Distinction: Verified Results vs. Unverified Claims

| Area | Status | Evidence |
| :--- | :--- | :--- |
| **RLS Row Filtering (Happy Path)** | **VERIFIED** | Live queries under legitimate faculty context filter rows strictly by assigned class. |
| **Duty Roster Exception** | **VERIFIED** | Faculty can view institution-wide duties without exposing student data. |
| **Connection Pooling Cleanup** | **VERIFIED** | Transaction rollback clears `set_config(..., true)` and does not leak to subsequent pooled sessions. |
| **Database Identity Tamper Resistance** | **DISPROVEN (FAIL)** | `ai_reader` can arbitrarily overwrite `app.current_faculty_id` and `app.current_user_role` via SQL. |
| **Application Layer Defense Only** | **VERIFIED** | Only `_validate_read_sql` regex blocks `SET_CONFIG`; the database engine provides zero trust boundary. |

---

## 7. Recommended Remediation Architecture

To achieve production certification, the identity context must be securely bound at the database engine level so that `ai_reader` cannot forge or alter it.

### Recommendation 1: Cryptographic Context Signing (HMAC Token)
Instead of trusting plaintext GUC settings, the application server computes an HMAC signature using a shared server secret:
1. When setting context, the server sets:
   - `app.current_faculty_id`
   - `app.current_user_role`
   - `app.current_context_ts` (Unix epoch timestamp to prevent replay attacks)
   - `app.current_context_signature` = `HMAC_SHA256(faculty_id || ':' || role || ':' || ts, SECRET_KEY)`
2. The `SECURITY DEFINER` functions in PostgreSQL:
   - Read the values and compute `extensions.hmac(...)` using `pgcrypto`.
   - Verify the computed HMAC matches `app.current_context_signature`.
   - Verify that `ts` is within a narrow validity window (e.g., 60 seconds).
   - If the signature is missing or does not match, the function immediately returns `FALSE`.
3. **Impact:** Even if an attacker executes `SELECT set_config('app.current_user_role', 'super_admin', true)`, the missing or invalid signature causes the helper function to fail closed, completely stopping identity spoofing.

### Recommendation 2: Hardening Helper Functions
1. Revoke `EXECUTE` on helper functions from `PUBLIC`.
2. Grant `EXECUTE` exclusively to `ai_reader` and required internal roles.
3. In `SET search_path`: use `SET search_path = public, pg_catalog` (omit `pg_temp`).
4. Schema-qualify all table queries inside functions (`public.faculty_timetable`, `public.timetable_versions`, `public.students`).

### Recommendation 3: Enable `FORCE ROW LEVEL SECURITY`
Add `ALTER TABLE <name> FORCE ROW LEVEL SECURITY;` to ensure that table owners and future application roles cannot accidentally bypass policies during reporting queries.

---

## 8. Audit Conclusion

The B4.2B implementation establishes proper table policies, view invoker semantics, and transaction-local cleanup, but **fails the critical database trust boundary test**. The identity context is a caller-writable GUC variable that can be manipulated by `ai_reader` to impersonate any faculty member or escalate to `super_admin`.

**Stage B4.2B is marked CRITICAL — FAIL. Operator remediation is required before promoting to production.**
