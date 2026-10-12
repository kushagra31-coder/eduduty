'use client'

import React, { createContext, useContext, useEffect, useState } from 'react'
import { User, Session } from '@supabase/supabase-js'
import { supabase } from '@/lib/supabase/client'
import { useRouter, usePathname } from 'next/navigation'

export interface DemoAccount {
  email: string
  name: string
  role: string
  description: string
}

interface AuthContextType {
  user: User | null
  session: Session | null
  loading: boolean
  role: string | null
  facultyId: number | null
  signOut: () => Promise<void>
  loginWithDemo: (email: string) => Promise<void>
  demoAuthAvailable: boolean
  demoAccounts: DemoAccount[]
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  session: null,
  loading: true,
  role: null,
  facultyId: null,
  signOut: async () => {},
  loginWithDemo: async () => {},
  demoAuthAvailable: false,
  demoAccounts: [],
})

const PUBLIC_ROUTES = ['/login']
const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [role, setRole] = useState<string | null>(null)
  const [facultyId, setFacultyId] = useState<number | null>(null)
  const [demoAuthAvailable, setDemoAuthAvailable] = useState(false)
  const [demoAccounts, setDemoAccounts] = useState<DemoAccount[]>([])
  const router = useRouter()
  const pathname = usePathname()

  // 1. Fetch authentication status (checks if dev demo auth is enabled on backend)
  useEffect(() => {
    fetch(`${API_BASE}/auth/status`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) {
          setDemoAuthAvailable(Boolean(data.demo_auth_enabled))
          setDemoAccounts(data.demo_accounts || [])
        }
      })
      .catch(() => {
        // Backend not reachable yet or offline
      })
  }, [])

  // 2. Initial session resolution
  useEffect(() => {
    let resolved = false

    // A. Check Supabase native session
    supabase.auth.getSession().then(({ data: { session: sbSession } }) => {
      if (sbSession?.user) {
        setSession(sbSession)
        setUser(sbSession.user)
        const userRole = sbSession.user.user_metadata?.role || 'EXAM_COORDINATOR'
        setRole(userRole)
        const facId = sbSession.user.user_metadata?.faculty_id ?? null
        setFacultyId(facId)
        resolved = true
        setLoading(false)
        return
      }

      // B. Fallback to stored dev demo session
      if (typeof window !== 'undefined') {
        try {
          const stored = localStorage.getItem('eduduty_auth_session')
          if (stored) {
            const parsed = JSON.parse(stored)
            if (parsed.expires_at && parsed.expires_at > Date.now()) {
              setUser(parsed.user as User)
              setSession({
                access_token: parsed.access_token,
                token_type: 'bearer',
                expires_in: Math.floor((parsed.expires_at - Date.now()) / 1000),
                expires_at: parsed.expires_at,
                user: parsed.user,
              } as unknown as Session)
              setRole(parsed.role)
              const facId = parsed.user?.faculty_id ?? parsed.user?.user_metadata?.faculty_id ?? null
              setFacultyId(facId)
              resolved = true
            } else {
              localStorage.removeItem('eduduty_auth_session')
            }
          }
        } catch {
          // ignore corrupted local storage
        }
      }

      if (!resolved) {
        setSession(null)
        setUser(null)
        setRole(null)
        setFacultyId(null)
      }
      setLoading(false)
    }).catch(() => {
      // Supabase client failure fallback to local storage
      if (typeof window !== 'undefined') {
        try {
          const stored = localStorage.getItem('eduduty_auth_session')
          if (stored) {
            const parsed = JSON.parse(stored)
            if (parsed.expires_at && parsed.expires_at > Date.now()) {
              setUser(parsed.user as User)
              setSession({
                access_token: parsed.access_token,
                token_type: 'bearer',
                expires_in: Math.floor((parsed.expires_at - Date.now()) / 1000),
                expires_at: parsed.expires_at,
                user: parsed.user,
              } as unknown as Session)
              setRole(parsed.role)
              const facId = parsed.user?.faculty_id ?? parsed.user?.user_metadata?.faculty_id ?? null
              setFacultyId(facId)
            }
          }
        } catch {
          // ignore
        }
      }
      setLoading(false)
    })

    // C. Listen for Supabase auth state changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, sbSession) => {
      if (sbSession?.user) {
        setSession(sbSession)
        setUser(sbSession.user)
        const userRole = sbSession.user.user_metadata?.role || 'EXAM_COORDINATOR'
        setRole(userRole)
      } else {
        // If not a demo session, clear state
        const stored = localStorage.getItem('eduduty_auth_session')
        if (!stored) {
          setSession(null)
          setUser(null)
          setRole(null)
        }
      }
      setLoading(false)
    })

    return () => {
      subscription.unsubscribe()
    }
  }, [])

  // 3. Protected route guard
  useEffect(() => {
    if (!loading) {
      const isPublicRoute = PUBLIC_ROUTES.includes(pathname)
      if (!session && !isPublicRoute) {
        router.push('/login')
      }
    }
  }, [loading, session, pathname, router])

  // 4. Sign-in with development demo account (strictly calls server /auth/demo-login)
  const loginWithDemo = async (email: string) => {
    const res = await fetch(`${API_BASE}/auth/demo-login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err?.detail?.error?.message ?? err?.detail ?? 'Demo login failed')
    }

    const data = await res.json()
    const demoSession = {
      access_token: data.access_token,
      expires_at: Date.now() + (data.expires_in * 1000),
      user: {
        id: data.user.id,
        email: data.user.email,
        faculty_id: data.user.faculty_id ?? null,
        user_metadata: {
          name: data.user.name,
          role: data.user.role,
          faculty_id: data.user.faculty_id ?? null,
        },
      },
      role: data.user.role,
    }

    localStorage.setItem('eduduty_auth_session', JSON.stringify(demoSession))
    document.cookie = `sb-access-token=${data.access_token}; path=/; max-age=${data.expires_in}; SameSite=Lax`

    setUser(demoSession.user as unknown as User)
    setSession({
      access_token: data.access_token,
      token_type: 'bearer',
      expires_in: data.expires_in,
      expires_at: demoSession.expires_at,
      user: demoSession.user,
    } as unknown as Session)
    setRole(data.user.role)
    setFacultyId(data.user.faculty_id ?? null)
    router.push('/dashboard')
  }

  // 5. Sign-out clears both Supabase and demo sessions
  const signOut = async () => {
    try {
      await supabase.auth.signOut()
    } catch {
      // ignore
    }
    localStorage.removeItem('eduduty_auth_session')
    document.cookie = 'sb-access-token=; path=/; max-age=0'
    setUser(null)
    setSession(null)
    setRole(null)
    setFacultyId(null)
    router.push('/login')
  }

  return (
    <AuthContext.Provider value={{ user, session, loading, role, facultyId, signOut, loginWithDemo, demoAuthAvailable, demoAccounts }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
