import { supabase } from '@/lib/supabase/client'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

/**
 * Retrieve current valid access token from Supabase session or stored dev session.
 */
export async function getAccessToken(): Promise<string | null> {
  // 1. Check native Supabase session
  try {
    const { data: { session } } = await supabase.auth.getSession()
    if (session?.access_token) {
      return session.access_token
    }
  } catch {
    // Supabase client error or unreachable
  }

  // 2. Check stored dev demo session
  if (typeof window !== 'undefined') {
    try {
      const stored = localStorage.getItem('eduduty_auth_session')
      if (stored) {
        const parsed = JSON.parse(stored)
        if (parsed.expires_at && parsed.expires_at > Date.now()) {
          return parsed.access_token
        } else {
          localStorage.removeItem('eduduty_auth_session')
        }
      }
    } catch {
      // storage parsing error
    }
  }

  return null
}

/**
 * Centralized, authenticated API fetch client.
 * Attaches Bearer JWT token, sets standard headers, and normalizes API paths.
 */
export async function apiFetch(endpoint: string, options: RequestInit = {}): Promise<Response> {
  const token = await getAccessToken()
  const headers = new Headers(options.headers || {})

  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  // Normalize endpoint: strip leading /api if present, since FastAPI routes are mounted at root
  const cleanEndpoint = endpoint.replace(/^\/api(?=\/|$)/, '')
  const fullEndpoint = cleanEndpoint.startsWith('/') ? cleanEndpoint : `/${cleanEndpoint}`
  const url = endpoint.startsWith('http') ? endpoint : `${BASE_URL}${fullEndpoint}`

  const response = await fetch(url, {
    ...options,
    headers,
  })

  return response
}

/**
 * Extract clean, human-readable error messages from FastAPI responses.
 * Handles { detail: string }, { detail: { error: { message } } }, and raw status codes.
 */
export async function getApiErrorMessage(res: Response, fallback = `Request failed (HTTP ${res.status})`): Promise<string> {
  try {
    const data = await res.json()
    if (typeof data?.detail === 'string') return data.detail
    if (data?.detail?.error?.message) return data.detail.error.message
    if (data?.error?.message) return data.error.message
    if (data?.message) return data.message
    return fallback
  } catch {
    return fallback
  }
}
