# EduDuty — Phase 2: Stage B4.2B.3 Independent Verification Report
## Independent Audit of Trusted Identity Remediation and RLS Hardening

**Audit Date:** 2026-10-11  
**Audit Scope:** Independent verification of B4.2B.2 remediation against the critical vulnerability confirmed in `docs/PHASE2_B4_2B_1_INDEPENDENT_SECURITY_AUDIT.md`.  
**Auditor Mode:** Verification-only security audit (zero code alterations, zero schema changes, zero secret rotations).  
**Target Database:** PostgreSQL 16 (`eduduty_pg_b4_test` container, database `eduduty_test_db`).  
**Executive Verdict:** **PASS** (with explicit architectural recommendations for production role provisioning).

---

## 1. Executive Summary & Verdict

In Phase 2 Stage B4.2B.1, an independent security audit demonstrated that the unprivileged database role `ai_reader` could forge `app.current_faculty_id` and escalate to `app.current_user_role = 'super_admin'` by invoking PostgreSQL's built-in `set_config()` function, bypassing row-level security and reading unauthorized cross-class student records.

This B4.2B.3 independent audit evaluated the B4.2B.2 remediation across the live PostgreSQL catalogs, application source code, Alembic migrations, and automated adversarial test suites.

### Core Audit Findings
1. **The Primary Impersonation Attack Is Completely Neutralized:**  
   Direct execution of `set_config('app.current_faculty_id', ...)` and `set_config('app.current_user_role', 'super_admin', true)` by `ai_reader` now returns **zero rows**. PostgreSQL no longer trusts raw GUC values. All RLS evaluations pass through `auth_internal.verify_identity_context()`, which validates a canonical HMAC-SHA256 signature against an isolated signing secret.
2. **Access Isolation Between `ai_reader` and Secrets is Enforced:**  
   The signing secret table `auth_internal.context_signing_key` and verification routine `auth_internal.verify_identity_context()` are strictly unreadable and unexecutable by `ai_reader` and `PUBLIC`. Attempts to read the key or execute the verifier trigger SQL error `42501 (permission denied for schema auth_internal)`.
3. **Table Protection Hardened (`FORCE ROW LEVEL SECURITY`):**  
   All 5 sensitive tables (`students`, `mst_eligibility`, `follow_up_statuses`, `invigilation_duties`, `classes`) have both `relrowsecurity = true` and `relforcerowsecurity = true`. Explicit policies (`rls_*_admin_owner`) allow administrative maintenance without bypassing RLS for operational connections.
4. **Function Execution Hardened:**  
   Helper functions (`can_current_user_access_class`, `can_current_user_access_student`, `can_current_user_access_duty_roster`) are configured with pinned `search_path = pg_catalog, public` (strictly preventing `pg_temp` object shadowing), use schema-qualified table references, and have execution privileges revoked from `PUBLIC`.
5. **Architectural Observation on Superuser Function Ownership:**  
   All `SECURITY DEFINER` helper functions remain owned by `postgres` (a superuser). While object shadowing is mitigated via pinned search paths, running `SECURITY DEFINER` functions as a superuser violates least-privilege principles. A dedicated `NOLOGIN` role is recommended before production go-live (detailed in Section 6).

---

## 2. Live PostgreSQL Catalog Evidence (Sanitized)

The following evidence was extracted directly from PostgreSQL 16 catalogs on `eduduty_pg_b4_test`:

### A. FORCE ROW LEVEL SECURITY Enforcement
```sql
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, pg_get_userbyid(c.relowner) as owner
FROM pg_class c
JOIN pg_namespace n ON c.relnamespace = n.oid
WHERE n.nspname = 'public'
  AND c.relname IN ('students', 'mst_eligibility', 'follow_up_statuses', 'invigilation_duties', 'classes');
```
| Table Name | relrowsecurity | relforcerowsecurity | Owner |
| :--- | :---: | :---: | :--- |
| `classes` | **true** | **true** | postgres |
| `students` | **true** | **true** | postgres |
| `mst_eligibility` | **true** | **true** | postgres |
| `invigilation_duties` | **true** | **true** | postgres |
| `follow_up_statuses` | **true** | **true** | postgres |

### B. Function Attributes, Ownership, Search Path, and Grants
```sql
SELECT p.proname,
       pg_get_userbyid(p.proowner) as owner,
       p.prosecdef as is_secdef,
       p.proconfig as config,
       p.proacl as acl,
       has_function_privilege('public', p.oid, 'EXECUTE') as pub_exec,
       has_function_privilege('ai_reader', p.oid, 'EXECUTE') as ai_reader_exec
FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname IN ('public', 'auth_internal')
  AND p.proname IN ('can_current_user_access_class', 'can_current_user_access_student', 
                    'can_current_user_access_duty_roster', 'verify_identity_context');
```
| Function Name | Schema | Owner | prosecdef | Search Path Config | PUBLIC EXECUTE | ai_reader EXECUTE |
| :--- | :--- | :--- | :---: | :--- | :---: | :---: |
| `verify_identity_context` | `auth_internal` | `postgres` | **true** | `search_path=pg_catalog, public` | **false** | **false** |
| `can_current_user_access_class` | `public` | `postgres` | **true** | `search_path=pg_catalog, public` | **false** | **true** |
| `can_current_user_access_student` | `public` | `postgres` | **true** | `search_path=pg_catalog, public` | **false** | **true** |
| `can_current_user_access_duty_roster` | `public` | `postgres` | **true** | `search_path=pg_catalog, public` | **false** | **true** |

*Verification:*
- `verify_identity_context()` is private to internal callers: execution by `PUBLIC` and `ai_reader` is strictly denied.
- Helper functions strip execution from `PUBLIC` and pin `search_path` without `pg_temp`.

### C. Schema Grants and CREATE Privileges
```sql
SELECT nspname, pg_get_userbyid(nspowner) as owner, nspacl,
       has_schema_privilege('public', nspname, 'CREATE') as pub_create,
       has_schema_privilege('ai_reader', nspname, 'USAGE') as ai_reader_usage,
       has_schema_privilege('ai_reader', nspname, 'CREATE') as ai_reader_create
FROM pg_namespace
WHERE nspname IN ('public', 'auth_internal');
```
| Schema | Owner | PUBLIC CREATE | ai_reader USAGE | ai_reader CREATE |
| :--- | :--- | :---: | :---: | :---: |
| `auth_internal` | `postgres` | **false** | **false** | **false** |
| `public` | `pg_database_owner` | **false** | **true** | **false** |

*Verification:* `ai_reader` has zero `CREATE` privileges in any schema, preventing object creation or function shadowing.

### D. `ai_reader` Role Attributes and Ownership
```sql
SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin, rolbypassrls
FROM pg_roles
WHERE rolname = 'ai_reader';
```
| Role | Superuser | Inherit | Create Role | Create DB | Login | Bypass RLS |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `ai_reader` | **false** | **false** | **false** | **false** | **true** | **false** |

*Verification:*
- Role memberships: `0` (not a member of `postgres`, `pg_read_all_data`, etc.).
- Schema objects owned: `0`.

---

## 3. Adversarial Attack Reproduction

The audit team executed a dedicated test harness directly over the physical `ai_reader` connection to reproduce the original attacks and test edge cases:

| Attack ID | Adversarial Test Scenario | Technical Action | Database Response | Status |
| :---: | :--- | :--- | :--- | :---: |
| **ATK-01** | Direct read of signing secret | `SELECT * FROM auth_internal.context_signing_key;` | `ERROR: 42501 permission denied for schema auth_internal` | **BLOCKED** |
| **ATK-02** | Direct verifier execution | `SELECT * FROM auth_internal.verify_identity_context();` | `ERROR: 42501 permission denied for schema auth_internal` | **BLOCKED** |
| **ATK-03** | B4.2B.1 Role Spoofing (Unsigned) | `SELECT set_config('app.current_user_role', 'super_admin', true); SELECT * FROM students;` | `0 rows returned` (Fails closed) | **DEFENDED** |
| **ATK-04** | Forged Signature for `super_admin` | Injects arbitrary hex signature with role `super_admin` | `0 rows returned` (Signature mismatch) | **DEFENDED** |
| **ATK-05** | Identity Tampering (Faculty B with Faculty A Sig) | Valid signature minted for Faculty A, but GUC set to Faculty B (`1002`) | `0 rows returned` (Signature mismatch) | **DEFENDED** |
| **ATK-06** | Expired Timestamp Replay | Signature minted with timestamp older than 120 seconds (`now - 130s`) | `0 rows returned` (Freshness check failed) | **DEFENDED** |
| **ATK-07** | Future Timestamp Manipulation | Signature minted with timestamp beyond skew tolerance (`now + 40s`) | `0 rows returned` (Future window rejected) | **DEFENDED** |
| **ATK-08** | Direct Base-Table Modification | `CREATE TABLE evil (x int); INSERT INTO students ...` | `ERROR: 42501 permission denied for schema public` | **BLOCKED** |
| **ATK-09** | Connection Pool Residual Context | Queries executed after `rollback()` on reused pooled connection | `0 rows returned` (Clean context) | **DEFENDED** |
| **POS-01** | Positive Baseline (Authorized Faculty A) | Validly signed context for Faculty A (`1001`) | Returns authorized Class A students: `['RLS-A01', 'RLS-A02']` | **VERIFIED** |

---

## 4. Trust Chain & Cryptographic Analysis

### A. Trace of the Identity Flow
1. **Application Authentication:**  
   The application authenticates the caller server-side (via JWT / session in `backend/api/dependencies.py`), resolving `current_user.id`, `current_user.faculty_id`, and `current_user.role`.
2. **Signature Generation (`backend/ai_service.py`):**  
   `mint_signed_identity_context(current_user)` serializes the claims into a canonical string:
   $$\text{canonical\_payload} = \text{user\_id} : \text{faculty\_id} : \text{role} : \text{issued\_at} : \text{nonce}$$
   Computes HMAC-SHA256 signature using `EDUDUTY_RLS_HMAC_SECRET`.
3. **Transaction-Scoped Injection:**  
   The application sets 6 GUC parameters with `is_local = true` on the dedicated `ai_reader` session:
   - `app.current_user_id`
   - `app.current_faculty_id`
   - `app.current_user_role`
   - `app.current_context_issued_at`
   - `app.current_context_nonce`
   - `app.current_context_signature`
4. **Database Verification (`auth_internal.verify_identity_context()`):**  
   - Reads GUC values.
   - Enforces timestamp boundary: $now - 120 \le \text{ctx\_ts} \le now + 30$ using `clock_timestamp()`.
   - Retrieves active key from `auth_internal.context_signing_key`.
   - Computes expected HMAC-SHA256 via `pgcrypto`'s `hmac()`.
   - Asserts string equality: `LOWER(raw_sig) = LOWER(expected_sig)`.
   - Safely parses integer identifiers.
5. **RLS Authorization:**  
   RLS policies invoke helper functions, which inspect `ctx_record.is_valid` and the verified attributes. If verification fails, functions return `false`, causing all protected tables and views to return zero rows.

### B. Resistance to Canonical Delimiter Injection
The canonical string format uses `:` as a delimiter. If a malicious input contained `:`, could delimiter collision occur?
- `user_id`, `faculty_id`, and `issued_at` are strictly parsed as integers (`::int`, `::bigint`). If an injected `:` exists, PostgreSQL casts raise an error and fail closed.
- `nonce` is generated server-side as hex characters (`0-9a-f`).
- `role` is derived server-side from authenticated records.
Consequently, canonical delimiter injection is not feasible.

---

## 5. Data Access Contract Verification

Independent verification proved all business authorization invariants hold:
1. **Active Timetable Assignment Scope:**  
   Faculty A (`1001`) reads only Class A students (`['RLS-A01', 'RLS-A02']`).
2. **Inactive Timetable Assignments Fail Closed:**  
   Draft assignment (`5003` under inactive version `4003`) returns `0 rows`.
3. **Unversioned Timetable Assignments Fail Closed:**  
   Unversioned assignment (`5004` with `NULL` version) returns `0 rows`.
4. **Historical Attendance Records Confers No Access:**  
   Faculty Delta (`1004`), possessing historical attendance records for Class A students but no active timetable assignment, returns `0 rows`.
5. **Duty Roster Exception Isolation:**  
   Faculty A querying `ai_duty_roster` can view institution-wide duty slots across all faculty (`2 rows visible`), but querying `students` or `mst_eligibility` still yields `0 rows` for unassigned classes.

---

## 6. Architectural Observations & Production Recommendations

While the implementation achieves its security objective and passes all adversarial tests, the audit team highlights four architectural considerations:

### Observation 1: Superuser Ownership of `SECURITY DEFINER` Functions (Medium Severity)
- **Current State:** `can_current_user_access_class`, `can_current_user_access_student`, and `can_current_user_access_duty_roster` are owned by `postgres`.
- **Risk Assessment:** While `search_path` is pinned to `pg_catalog, public` and all object names are schema-qualified, executing helper routines under superuser context increases blast radius in the event of unforeseen SQL injection or engine vulnerabilities.
- **Recommendation:** Prior to production provisioning, introduce a dedicated `NOLOGIN` role (e.g. `eduduty_definer_owner`) that owns these functions, granting `eduduty_definer_owner` only `SELECT` on `public.students`, `public.faculty_timetable`, `public.timetable_versions`, and `auth_internal.context_signing_key`.

### Observation 2: Secret Rotation Concurrency (Low Severity)
- **Current State:** `auth_internal.verify_identity_context()` retrieves the active secret using `ORDER BY key_id DESC LIMIT 1`.
- **Operational Impact:** If a new key is inserted, any in-flight requests or tokens minted seconds earlier with the previous key will immediately fail verification.
- **Recommendation:** For zero-downtime key rotation, the verifier can test the signature against all rows where `active = true`, allowing an overlap window during deployment.

### Observation 3: Stateless Replay Window (Low Severity)
- **Current State:** The database enforces a 120-second replay window using `ctx_ts`, but does not record consumed nonces in a persistent replay table.
- **Risk Assessment:** A valid token captured within its 120-second window could technically be replayed on another connection before expiration.
- **Mitigation in Place:** Mitigated because tokens are transaction-local, network traffic is encrypted via TLS in production, and connection pool cleanups execute `rollback()`.

### Observation 4: Development Default Secret Overriding (Low Severity)
- **Current State:** Migration 008 and `ai_service.py` contain a fallback default secret (`eduduty_insecure_default_hmac_secret_for_dev_only_32b`) to maintain seamless developer workflow.
- **Recommendation:** Production deployment pipelines must ensure `EDUDUTY_RLS_HMAC_SECRET` is explicitly injected as a high-entropy secret.

---

## 7. Migration Safety & Repeatability

The audit verified migration 008 lifecycle repeatability:
1. **Downgrade to 007 (`alembic downgrade 007_implement_faculty_rls`):**  
   - Safely removes `auth_internal` schema, `context_signing_key` table, `verify_identity_context()`, and admin policies.
   - Restores the original 007 definitions of helper functions.
   - Historical migrations 001–006 remain completely untouched.
2. **Re-upgrade to 008 (`alembic upgrade head`):**  
   - Restores the trusted HMAC context and hardened functions without error or schema drift.

---

## 8. Test Suite Verification Summary

| Test Suite | Execution Command | Total Tests | Passed | Failed | Skipped | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **B4.2B.2 Adversarial Security Suite** | `pytest backend/tests/test_postgres_rls_b42b2_remediation.py` | 20 | **20** | 0 | 0 | **PASS** |
| **Full PostgreSQL-Required Suite** | `pytest backend/tests/test_postgres_*.py backend/tests/test_alembic_b42a_ai_reader.py` | 68 | **68** | 0 | 0 | **PASS** |
| **SQLite Development Regression Suite** | `python -m pytest tests/test_*.py` | 85 | **85** | 0 | 0 | **PASS** |

*Gating Check:* Confirmed that with `EDUDUTY_REQUIRE_POSTGRES_TESTS=1`, missing configuration or unreachable databases trigger immediate test failures (`pytest.fail()`), ensuring zero required tests can silently skip or substitute SQLite.

---

## 9. Conclusion & Acceptance Gate Sign-Off

**Final Assessment:** **PASS**

The trusted identity context architecture successfully closes the B4.2B.1 vulnerability. Changing PostgreSQL custom settings alone can no longer grant another faculty member's access or escalate privileges. Data isolation across base tables and approved views is cryptographically bound and strictly enforced by the PostgreSQL database engine.
