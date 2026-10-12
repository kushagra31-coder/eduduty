# EduDuty Authentication Specification (Phase 1 — Remediation 1)

## Overview
EduDuty uses Supabase Auth for identity management, authentication, and session persistence.
The backend FastAPI service strictly enforces fail-closed token validation on every protected route.

---

## Authentication Flow

```text
+----------------+          1. Sign In (email/password)          +--------------------+
|                | --------------------------------------------> |                    |
| Next.js Client |                                               | Supabase Auth API  |
|                | <-------------------------------------------- |                    |
+----------------+            2. JWT Bearer Token                +--------------------+
        |
        | 3. HTTP Request + Header [Authorization: Bearer <JWT>]
        v
+----------------+
| FastAPI        | 4. Verify Signature & Validate Claims (exp, iss, aud, alg)
| Backend        | 5. Resolve Local User (Unmapped roles default to VIEWER)
+----------------+
```

---

## Fail-Closed Backend Token Verification (`backend/core/security.py`)

- **Strict Signature Verification:** Validates signature using `SUPABASE_JWT_SECRET` (HMAC SHA-256) or `SUPABASE_JWT_PUBLIC_KEY` (asymmetric RS256/ES256). Unverified token fallbacks are strictly prohibited.
- **Fail-Closed Configuration:** If `SUPABASE_JWT_SECRET` or verification key configuration is missing or invalid, all authenticated API requests are rejected with HTTP 401 (`INVALID_TOKEN`).
- **Anon Key Isolation:** `SUPABASE_ANON_KEY` is a client API key and is NEVER used as a JWT signing secret.
- **Claims Enforcement:**
  - **Expiration (`exp`):** Rejects expired tokens.
  - **Audience (`aud`):** Validates expected audience (defaults to `"authenticated"`, configurable via `SUPABASE_JWT_AUDIENCE`).
  - **Issuer (`iss`):** Validates expected issuer (derived from `SUPABASE_URL` or `SUPABASE_JWT_ISSUER`).
  - **Algorithm (`alg`):** Restricts signing algorithms to `SUPABASE_JWT_ALGORITHM` (defaults to `HS256`). Rejects `alg: "none"` and unsupported algorithms.
- **User Resolution & Default Role:** Matches `sub` (Supabase UID) or `email` against the `users` table. If unmapped or unknown roles are supplied, the user defaults to `VIEWER` (read-only, minimal privilege), preventing privilege escalation.

---

## Required Environment Variables

| Variable Name | Description | Default / Example |
| :--- | :--- | :--- |
| `SUPABASE_JWT_SECRET` | Trusted HMAC secret for verifying Supabase JWT signatures (min 16 chars). | *Required for production (e.g., `your-supabase-jwt-secret-min32-chars`)* |
| `SUPABASE_URL` | Base URL of the Supabase project (used to derive expected issuer). | `https://<project-ref>.supabase.co` |
| `SUPABASE_JWT_ISSUER` | Explicit expected issuer claim override. | `https://<project-ref>.supabase.co/auth/v1` |
| `SUPABASE_JWT_AUDIENCE` | Expected audience claim override. | `authenticated` |
| `SUPABASE_JWT_ALGORITHM` | Allowed signing algorithm(s). | `HS256` |
| `SUPABASE_JWT_PUBLIC_KEY` | Public key PEM string for asymmetric RS256/ES256 verification. | *Optional for RS256/ES256 setups* |

---

## Frontend Integration (`frontend/src/lib/auth/context.tsx`)

- **Auth Context (`AuthProvider`):** Maintains current user, session, and role state.
- **Route Protection:** Unauthenticated users attempting to access protected pages are automatically redirected to `/login`.
- **API Fetch Client (`frontend/src/lib/api.ts`):** Automatically injects `Authorization: Bearer <token>` into HTTP headers for backend requests.

