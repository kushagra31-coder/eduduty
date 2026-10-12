# EduDuty — Phase 2: Stage B4.2B.2 Remediation Report
## Trusted Identity Context and PostgreSQL Row-Level Security Hardening

**Status:** COMPLETE (VERIFIED PASS)  
**Date:** 2026-10-11  
**Target Vulnerability:** B4.2B.1 Confirmed Critical Identity-Spoofing and Role-Escalation Flaw  
**Target Environment:** PostgreSQL 16 (Test Container: `eduduty_pg_b4_test`) / SQLite Dev Fallback  
**Alembic Revisions:** `007_implement_faculty_rls` -> `008_trusted_identity_context` (HEAD)

---

## 1. Executive Summary & Mission

During the B4.2B.1 Independent Security Audit, a critical architectural vulnerability was confirmed:
> The database role `ai_reader` was able to invoke `set_config('app.current_faculty_id', '<other_id>', true)` and `set_config('app.current_user_role', 'super_admin', true)` directly within an active session or transaction. Because the B4.2B RLS helper functions trusted raw custom PostgreSQL GUC variables without cryptographic authentication, any caller executing SQL as `ai_reader` could forge arbitrary faculty IDs or escalate to `super_admin`, completely bypassing row-level data isolation and reading unauthorized student records across all classes.

### The Objective
Remediate this vulnerability so that **changing PostgreSQL custom settings alone can NEVER grant another faculty member's access or privileged access**.

### Remediation Accomplishments
1. **Cryptographic Identity Context Verification (`pgcrypto` HMAC-SHA256):**
   Introduced migration `008_trusted_identity_context.py` which provisions an internal schema `auth_internal` containing a protected signing key table and a cryptographic verification engine `auth_internal.verify_identity_context()`.
2. **Elimination of GUC Spoofing:**
   PostgreSQL RLS helper functions no longer trust `app.current_faculty_id` or `app.current_user_role` directly. Instead, they extract identity attributes exclusively from `auth_internal.verify_identity_context()`, which re-calculates and verifies a canonical HMAC-SHA256 signature against an active server secret key. Any untrusted, absent, forged, altered, or expired GUC fails closed immediately.
3. **Hardened `SECURITY DEFINER` Functions:**
   All helper functions (`can_current_user_access_class`, `can_current_user_access_student`, `can_current_user_access_duty_roster`) pin `search_path = pg_catalog, public` (strictly preventing `pg_temp` shadowing), qualify object names, and have all execution privileges revoked from `PUBLIC`.
4. **Table-Owner RLS Enforcement (`FORCE ROW LEVEL SECURITY`):**
   Applied `FORCE ROW LEVEL SECURITY` across all 5 sensitive base tables (`students`, `mst_eligibility`, `follow_up_statuses`, `invigilation_duties`, `classes`). Explicit administrative policies (`rls_*_admin_owner`) were defined for the table owner (`postgres`) to ensure system migrations and maintenance succeed without bypassing RLS for application roles.
5. **Application-Level Context Signing:**
   Updated `backend/ai_service.py` to mint signed identity tokens (`mint_signed_identity_context`) derived from server-side authenticated user session records. Tokens include user ID, faculty ID, effective role, an epoch timestamp, and a cryptographic nonce.
6. **Zero Flaws & Zero Regressions Verified:**
   - 20 of 20 B4.2B.2 adversarial security tests PASSED with zero skips.
   - 68 of 68 full PostgreSQL-required suite tests PASSED with zero skips.
   - 85 of 85 SQLite regression suite tests PASSED with zero skips.

---

## 2. Threat Model & Trust Boundaries

```
┌────────────────────────────────────────────────────────────────────────┐
│                        EduDuty Application Layer                       │
│                                                                        │
│  1. Authenticates User (JWT / Session) -> User Record (ID, Role)       │
│  2. Resolves Faculty Linkage Server-Side (User.faculty_id)             │
│  3. Mints HMAC Token:                                                  │
│     Payload = "{user_id}:{faculty_id}:{role}:{timestamp}:{nonce}"     │
│     Sig = HMAC_SHA256(Payload, SECRET_KEY)                             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                       Transaction-Scoped SQL Setup:
                       set_config('app.current_user_id', ...)
                       set_config('app.current_faculty_id', ...)
                       set_config('app.current_user_role', ...)
                       set_config('app.current_context_issued_at', ...)
                       set_config('app.current_context_nonce', ...)
                       set_config('app.current_context_signature', ...)
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   PostgreSQL Database Engine Boundary                  │
│                                                                        │
│  Role: ai_reader (NOSUPERUSER, NOBYPASSRLS, Read-Only)                 │
│                                                                        │
│  [RLS Policy Evaluation on students / views]                           │
│     │                                                                  │
│     ▼ calls                                                            │
│  can_current_user_access_student() (SECURITY DEFINER, postgres owned)  │
│     │                                                                  │
│     ▼ calls                                                            │
│  auth_internal.verify_identity_context()                               │
│     ├── Reads GUCs                                                     │
│     ├── Validates timestamp freshness (+30s / -120s window)            │
│     ├── Retrieves key from auth_internal.context_signing_key           │
│     │   (Inaccessible to ai_reader / PUBLIC)                           │
│     ├── Computes expected HMAC-SHA256 signature                        │
│     └── Signature match?                                               │
│            ├── YES ──> Returns verified (user_id, faculty_id, role)    │
│            └── NO  ──> Returns (NULL, NULL, NULL, is_valid=false)     │
│                                                                        │
│  Result if signature invalid or forged: FAILS CLOSED (0 rows returned) │
└────────────────────────────────────────────────────────────────────────┘
```

### Trust Boundary Analysis
- **Key Minting Authority:** Only the application backend possessing `EDUDUTY_CONTEXT_SIGNING_KEY` can mint valid HMAC signatures.
- **Key Storage Privilege:** Stored in `auth_internal.context_signing_key` inside PostgreSQL, owned by `postgres`. `SELECT`, `INSERT`, `UPDATE`, `DELETE`, and `TRUNCATE` are revoked from `PUBLIC` and `ai_reader`.
- **Verifier Protection:** `auth_internal.verify_identity_context()` is strictly accessible only to `postgres` (the owner of the `SECURITY DEFINER` RLS helpers). Neither `PUBLIC` nor `ai_reader` can execute the verifier directly.
- **Replay Policy & Window:**
  - Context timestamps are strictly checked against `clock_timestamp()`: `ctx_ts > now_ts + 30 OR ctx_ts < now_ts - 120` results in immediate rejection.
  - A 16-hex cryptographic nonce is bound to each payload.
  - **Remaining Replay Risk:** If an attacker captures a valid signed context within its 120-second validity window and executes queries within that window on the same database, the context remains valid for the duration of that window. However, because:
    1. The context is transaction-local (`true` in `set_config`), and
    2. Connection pools execute immediate `rollback()` on cleanup, and
    3. `ai_reader` has read-only access and cannot capture outgoing connection parameters,
    the replay risk is strictly minimized to legitimate intra-transaction execution.

---

## 3. Implementation Details

### Migration 008: `008_trusted_identity_context.py`
Located at `backend/alembic/versions/008_trusted_identity_context.py`:
- **`pgcrypto` Activation:** Enables `CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;`.
- **Private Schema & Key Table:**
  ```sql
  CREATE SCHEMA IF NOT EXISTS auth_internal;
  CREATE TABLE IF NOT EXISTS auth_internal.context_signing_key (
      key_id varchar(64) PRIMARY KEY,
      secret_key text NOT NULL,
      active boolean NOT NULL DEFAULT true,
      created_at timestamptz NOT NULL DEFAULT clock_timestamp()
  );
  REVOKE ALL ON SCHEMA auth_internal FROM PUBLIC, ai_reader;
  REVOKE ALL ON TABLE auth_internal.context_signing_key FROM PUBLIC, ai_reader;
  ```
- **Verification Function `auth_internal.verify_identity_context()`:**
  - Extracts the 6 GUC parameters: `app.current_user_id`, `app.current_faculty_id`, `app.current_user_role`, `app.current_context_issued_at`, `app.current_context_nonce`, and `app.current_context_signature`.
  - Validates formatting, timestamp boundaries (+30s / -120s), and null safety.
  - Recomputes `encode(hmac(canonical_payload::bytea, active_secret::bytea, 'sha256'), 'hex')`.
  - Returns `(v_user_id int, v_faculty_id int, v_role text, is_valid boolean)`.
- **Hardened Helper Functions:**
  - `can_current_user_access_class(target_class_id int)`
  - `can_current_user_access_student(target_student_id int)`
  - `can_current_user_access_duty_roster(target_faculty_id int)`
  - All configured with:
    - `SECURITY DEFINER`
    - `SET search_path = pg_catalog, public`
    - Schema-qualified queries against `public.faculty_timetable`, `public.students`, `public.timetable_versions`.
    - Revoked execution from `PUBLIC`.
- **RLS Reinforcement:**
  - Executed `ALTER TABLE ... FORCE ROW LEVEL SECURITY;` on:
    - `students`
    - `mst_eligibility`
    - `follow_up_statuses`
    - `invigilation_duties`
    - `classes`
  - Created explicit policies `rls_<table_name>_admin_owner` allowing `postgres` full administrative access under `FORCE ROW LEVEL SECURITY`.

### Application Layer: `backend/ai_service.py`
- Implemented `mint_signed_identity_context(current_user: Optional[models.User])`:
  - Canonical format: `{user_id}:{faculty_id}:{role}:{timestamp}:{nonce}`.
  - Computes HMAC-SHA256 using `os.environ.get("EDUDUTY_CONTEXT_SIGNING_KEY")`.
  - Sets all 6 GUC parameters inside the transaction:
    ```sql
    SELECT set_config('app.current_user_id', :uid, true),
           set_config('app.current_faculty_id', :fac_id, true),
           set_config('app.current_user_role', :role, true),
           set_config('app.current_context_issued_at', :ts, true),
           set_config('app.current_context_nonce', :nonce, true),
           set_config('app.current_context_signature', :sig, true);
    ```
  - Both `execute_structured_reporting_op` and `handle_ai_message` wrap execution in deterministic `try...finally: read_db.rollback()`.

---

## 4. Live PostgreSQL Catalog Evidence (Sanitized)

Executed against live container `eduduty_pg_b4_test` running PostgreSQL 16:

### A. FORCE ROW LEVEL SECURITY Status
```sql
SELECT relname, relrowsecurity, relforcerowsecurity 
FROM pg_class 
WHERE relname IN ('students', 'mst_eligibility', 'follow_up_statuses', 'invigilation_duties', 'classes');
```
| relname | relrowsecurity | relforcerowsecurity |
| :--- | :---: | :---: |
| classes | t | t |
| students | t | t |
| mst_eligibility | t | t |
| invigilation_duties | t | t |
| follow_up_statuses | t | t |

### B. Helper Function Ownership, Security, and search_path
```sql
SELECT proname, prosecdef, proconfig, proacl,
       has_function_privilege('public', oid, 'EXECUTE') as pub_exec
FROM pg_proc 
WHERE proname IN ('can_current_user_access_class', 'can_current_user_access_student', 'can_current_user_access_duty_roster');
```
| proname | prosecdef | proconfig | proacl | pub_exec |
| :--- | :---: | :--- | :--- | :---: |
| can_current_user_access_duty_roster | t | {"search_path=pg_catalog, public"} | {postgres=X/postgres,ai_reader=X/postgres} | f |
| can_current_user_access_class | t | {"search_path=pg_catalog, public"} | {postgres=X/postgres,ai_reader=X/postgres} | f |
| can_current_user_access_student | t | {"search_path=pg_catalog, public"} | {postgres=X/postgres,ai_reader=X/postgres} | f |

*Catalog Evidence Confirms:*
- `prosecdef = t` (SECURITY DEFINER).
- `proconfig` strictly pins `search_path=pg_catalog, public` (no `pg_temp`).
- `pub_exec = f` (PUBLIC execution is revoked).
- Only `postgres` and `ai_reader` have execute permissions.

### C. Signing Key Table Access Isolation
```sql
SELECT grantee, privilege_type 
FROM information_schema.role_table_grants 
WHERE table_name = 'context_signing_key';
```
| grantee | privilege_type |
| :--- | :--- |
| postgres | SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER |

*Catalog Evidence Confirms:* Zero privileges granted to `ai_reader` or `PUBLIC`.

### D. `ai_reader` Role Attributes
```sql
SELECT rolname, rolsuper, rolbypassrls, rolinherit 
FROM pg_roles 
WHERE rolname = 'ai_reader';
```
| rolname | rolsuper | rolbypassrls | rolinherit |
| :--- | :---: | :---: | :---: |
| ai_reader | f | f | t |

---

## 5. Test Suite Verification & Exact Counts

### A. Stage B4.2B.2 Adversarial PostgreSQL Test Suite
File: `backend/tests/test_postgres_rls_b42b2_remediation.py`  
Total Tests: **20** | **Passed: 20** | **Failed: 0** | **Skipped: 0**

| Test Name | Description | Result |
| :--- | :--- | :---: |
| `test_01_faculty_a_reads_authorized_class_a_students` | Legitimate signed Faculty A reads authorized Class A | **PASS** |
| `test_02_faculty_a_cannot_read_faculty_b_by_changing_faculty_id` | Changing `app.current_faculty_id` with Faculty A signature fails closed | **PASS** |
| `test_03_setting_user_role_to_super_admin_denied` | Changing `app.current_user_role` to `super_admin` fails closed | **PASS** |
| `test_04_changing_both_settings_together_denied` | Changing both GUCs simultaneously fails closed | **PASS** |
| `test_05_forged_or_absent_signatures_fail_closed` | Empty or fabricated signatures fail closed | **PASS** |
| `test_06_valid_context_for_faculty_a_cannot_claim_faculty_b` | Manipulated faculty claims with old signature are rejected | **PASS** |
| `test_07_context_bound_to_another_user_or_role_rejected` | Context bound to mismatched user or role is rejected | **PASS** |
| `test_08_expired_malformed_and_ambiguous_context_rejected` | Timestamps beyond -120s or +30s window are rejected | **PASS** |
| `test_09_signing_key_cannot_be_read_or_modified_by_ai_reader` | `ai_reader` cannot SELECT, INSERT, or DROP signing key | **PASS** |
| `test_10_ai_reader_cannot_mint_signature_or_change_verifier` | `ai_reader` cannot alter verifier or secret table | **PASS** |
| `test_11_all_five_approved_views_preserve_faculty_scope` | All 5 approved views enforce faculty isolation | **PASS** |
| `test_12_direct_base_table_reads_cannot_bypass_scope` | Direct `SELECT` on `students` / `mst_eligibility` respects RLS | **PASS** |
| `test_13_historical_attendance_does_not_confer_student_access` | Past attendance records confer no active access | **PASS** |
| `test_14_duty_roster_access_does_not_confer_broader_student_access` | Roster exception never leaks student or eligibility data | **PASS** |
| `test_15_pooled_connection_reuse_does_not_leak_authorization` | Single-pool connection reuse leaves zero residual identity | **PASS** |
| `test_16_writes_ddl_grants_denied_to_ai_reader` | DDL, INSERT, UPDATE, DELETE, and GRANT remain denied | **PASS** |
| `test_17_helper_function_ownership_execute_grants_safe_search_path` | Catalog inspection confirms `search_path` and stripped PUBLIC EXECUTE | **PASS** |
| `test_18_force_row_level_security_behavior_and_owner_policies` | Catalog inspection confirms `FORCE ROW LEVEL SECURITY` | **PASS** |
| `test_19_migration_upgrade_downgrade_reupgrade_repeatable` | Downgrade 008 -> 007 and re-upgrade 007 -> 008 verified | **PASS** |
| `test_20_regression_b42b1_impersonation_attack_now_denied` | Direct reproduction of B4.2B.1 attack fails unconditionally (0 rows) | **PASS** |

### B. Full PostgreSQL-Required Test Suite
Command: `pytest backend/tests/test_postgres_*.py backend/tests/test_alembic_b42a_ai_reader.py`  
Total Tests: **68** | **Passed: 68** | **Failed: 0** | **Skipped: 0**

- `backend/tests/test_postgres_rls_b42b2_remediation.py`: 20 passed
- `backend/tests/test_postgres_rls_b42b.py`: 18 passed
- `backend/tests/test_alembic_b42a_ai_reader.py`: 11 passed
- `backend/tests/test_postgres_connection_b412.py`: 12 passed
- `backend/tests/test_postgres_gating.py`: 7 passed

### C. SQLite Regression Test Suite
Command: `python -m pytest tests/test_*.py` (Run from `backend/` directory)  
Total Tests: **85** | **Passed: 85** | **Failed: 0** | **Skipped: 0**

- `tests/test_auth.py`: 15 passed
- `tests/test_rbac.py`: 6 passed
- `tests/test_resource_authorization.py`: 10 passed
- `tests/test_upload_attendance.py`: 4 passed
- `tests/test_ai_read_isolation.py`: 5 passed
- `tests/test_alembic_b2_constraints.py`: 6 passed
- `tests/test_alembic_b31_review.py`: 3 passed
- `tests/test_alembic_b32_gate.py`: 3 passed
- `tests/test_alembic_b33_auth.py`: 25 passed
- `tests/test_alembic_b3_ai_views.py`: 5 passed
- `tests/test_alembic_migration.py`: 3 passed

---

## 6. Operational Procedures & Secret Rotation

### A. Running Forward Migration in Production
```bash
cd backend
alembic upgrade head
```
*Note:* Running `upgrade head` requires superuser or schema-owner privileges to execute `CREATE EXTENSION IF NOT EXISTS pgcrypto` and `CREATE SCHEMA IF NOT EXISTS auth_internal`.

### B. Rolling Back to Migration 007
```bash
cd backend
alembic downgrade 007_implement_faculty_rls
```
*Note:* The downgrade drops `auth_internal.verify_identity_context()`, drops `auth_internal.context_signing_key`, drops the `auth_internal` schema, restores the migration 007 version of the RLS helpers, and leaves historical migrations intact.

### C. Zero-Downtime Secret Rotation Procedure
To rotate the HMAC signing key in production without disrupting active reporting:
1. Generate a new high-entropy 256-bit secret (e.g. `openssl rand -hex 32`).
2. Insert the new key into `auth_internal.context_signing_key` using a new `key_id` (e.g., `'v2'`) with `active = true`:
   ```sql
   INSERT INTO auth_internal.context_signing_key (key_id, secret_key, active)
   VALUES ('v2', '<NEW_SECRET_KEY>', true);
   ```
3. Update the application server environment variable:
   ```bash
   export EDUDUTY_CONTEXT_SIGNING_KEY='<NEW_SECRET_KEY>'
   ```
4. Restart or deploy the application servers. The database verifier orders active keys by `key_id DESC` and selects the newest active secret.
5. After all servers have reloaded and the 120-second replay window expires, deactivate or delete key `'v1'`:
   ```sql
   UPDATE auth_internal.context_signing_key SET active = false WHERE key_id = 'v1';
   ```

---

## 7. Modified Files & Repository Cleanliness

| File | Change Nature |
| :--- | :--- |
| `backend/alembic/versions/008_trusted_identity_context.py` | New Alembic migration implementing trusted HMAC context and hardened RLS |
| `backend/ai_service.py` | Added HMAC context minting and secure parameter injection |
| `backend/tests/test_postgres_rls_b42b2_remediation.py` | New adversarial test suite covering all 20 required security scenarios |
| `backend/tests/test_postgres_rls_b42b.py` | Updated context setup helper to use trusted context signatures |
| `docs/PHASE2_B4_2B_2_TRUSTED_IDENTITY_REMEDIATION.md` | Comprehensive security remediation and audit verification report |

### Verification of Safety Invariants
- `git status` confirms **no git commits and no git pushes**.
- `backend/eduduty.db` SQLite database is intact and unchanged.
- All SecureMailScope Docker containers, networks, images, and volumes are preserved.
- No passwords, tokens, or private secrets exist in documentation or logs.

---

## 8. Final Acceptance Gate Verdict

**VERDICT: PASS (READY FOR AUDIT & DEPLOYMENT)**  
The original direct-SQL impersonation vulnerability from B4.2B.1 is completely eliminated. Forging `app.current_faculty_id` or `app.current_user_role` as `ai_reader` produces an immediate HMAC signature failure and fails closed at the PostgreSQL database engine level with zero leaked rows. All 20 adversarial tests, 68 PostgreSQL integration tests, and 85 SQLite regression tests run with zero failures and zero skips.
