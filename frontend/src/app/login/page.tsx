'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase/client'
import { useAuth, DemoAccount } from '@/lib/auth/context'
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { AlertCircle, Loader2, Sparkles, UserCheck } from 'lucide-react'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [demoLoadingEmail, setDemoLoadingEmail] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const router = useRouter()
  const { loginWithDemo, demoAuthAvailable, demoAccounts } = useAuth()

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)

    try {
      const { data, error } = await supabase.auth.signInWithPassword({
        email,
        password,
      })

      if (error) {
        setError(error.message)
      } else if (data.session) {
        router.push('/dashboard')
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to sign in. Please try again.'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  const handleDemoLogin = async (acc: DemoAccount) => {
    setDemoLoadingEmail(acc.email)
    setError(null)
    try {
      await loginWithDemo(acc.email)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Demo sign-in failed.'
      setError(message)
    } finally {
      setDemoLoadingEmail(null)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4 w-full">
      <Card className="w-full max-w-md shadow-lg border-2">
        <CardHeader className="space-y-1 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-foreground text-background text-xl font-bold shadow">
            E
          </div>
          <CardTitle className="text-2xl font-bold">EduDuty Portal</CardTitle>
          <CardDescription>
            MST Operations & Invigilation Management
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {error && (
            <div className="flex items-center gap-2 p-3 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Standard Supabase Login Form */}
          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="m.doe@college.edu"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>

            <Button type="submit" className="w-full" disabled={loading || Boolean(demoLoadingEmail)}>
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Signing In...
                </>
              ) : (
                'Sign In'
              )}
            </Button>
          </form>

          {/* Development Demo Login (Only rendered if enabled on backend) */}
          {demoAuthAvailable && demoAccounts.length > 0 && (
            <div className="pt-2 border-t space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                  <Sparkles className="h-3.5 w-3.5 text-primary" />
                  Demo Mode (Dev Only)
                </span>
                <Badge variant="outline" className="text-[10px] font-mono">
                  DEV AUTH
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                One-click authentication using server-verified demo identities:
              </p>
              <div className="grid grid-cols-2 gap-2">
                {demoAccounts.map((acc) => (
                  <Button
                    key={acc.email}
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-auto py-2 px-2.5 flex flex-col items-start text-left justify-start gap-1"
                    onClick={() => handleDemoLogin(acc)}
                    disabled={loading || Boolean(demoLoadingEmail)}
                  >
                    <div className="flex items-center gap-1.5 w-full">
                      {demoLoadingEmail === acc.email ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0 text-primary" />
                      ) : (
                        <UserCheck className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      )}
                      <span className="font-semibold text-xs truncate">{acc.name}</span>
                    </div>
                    <span className="text-[10px] text-muted-foreground truncate w-full">
                      {acc.role.replace('_', ' ')}
                    </span>
                  </Button>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
