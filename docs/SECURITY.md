# EduDuty Security Architecture (Phase 1)

## Overview
EduDuty Phase 1 establishes a zero-trust, server-side verified security architecture. All client requests are authenticated using Supabase JWT tokens, and authorization is enforced via granular Role-Based Access Control (RBAC).

---

## Security Guarantees & Constraints

### 1. Identity Resolution & Anti-Spoofing
- **Client Identity Elimination:** Request bodies and query parameters containing actor IDs (`user_id`, `changed_by`) are strictly ignored or forbidden.
- **Server Identity Token Extraction:** The backend `get_current_user` dependency verifies the Supabase JWT `Authorization: Bearer <token>` header, decodes the claims (`sub`, `email`, `role`), and attaches the authenticated `User` object (`request.state.user`) to the execution scope.
- **Audit Logging Integrity:** All audit log table writes receive `changed_by` directly from `current_user.id`.

### 2. Role-Based Access Control (RBAC)
- **Role Hierarchy:**
  - `SUPER_ADMIN`: Full system control & administrative setup.
  - `ADMIN`: HOD / Academic Administrator.
  - `EXAM_COORDINATOR`: Exam schedule, seating layout, duty assignment, eligibility overrides.
  - `FACULTY`: Course attendance management & duty viewing.
  - `INVIGILATOR`: Room roll-call execution & duty check-in.
  - `VIEWER`: Read-only reporting view.
- **Dependency Guard:** Endpoints enforce permissions via `Depends(require_permission("permission.name"))`. Unauthenticated requests yield HTTP `401 Unauthorized`. Requests with insufficient permissions yield HTTP `403 Forbidden`.

### 3. Data & Exception Handling Sanitization
- **500 Internal Server Error Sanitization:** The custom `safe_exception_handler` intercepts uncaught backend exceptions, logs full stack traces internally to secure log streams, and returns a standardized, sanitized JSON error payload (`INTERNAL_SERVER_ERROR`) with zero stack trace leakage to the client.
- **CORS Protection:** Replaced wildcard CORS (`*`) with configurable origin whitelisting (`CORS_ALLOWED_ORIGINS` environment variable).

### 4. Supabase Service Role Key Isolation
- The Supabase `SERVICE_ROLE_KEY` is strictly reserved for server-side administrative operations (backend only). It is NEVER exposed to the frontend browser or committed to repository source code.

---

## Test Verification
Backend security tests are located in `backend/tests/`:
- `test_auth.py`: Token verification, expired token rejection, valid JWT user creation.
- `test_rbac.py`: Permission checks, HTTP 403 enforcement for unauthorized roles.
- `test_identity_spoofing.py`: Identity spoofing rejection and audit actor validation.
