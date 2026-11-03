'use client'

import { useEffect, useState } from 'react'
import { CheckCircle2, AlertTriangle, XCircle } from 'lucide-react'

type Provider = { name: string; configured: boolean; hint?: string }
type HealthData = { ready: boolean; providers: Provider[] }

export default function AIHealthBanner() {
  const [health, setHealth] = useState<HealthData | null>(null)

  useEffect(() => {
    fetch('/api/ai/health').then(r => r.ok ? r.json() : null).then(setHealth).catch(() => {})
  }, [])

  if (!health) return null

  if (health.ready) {
    const active = health.providers.find(p => p.configured)
    return (
      <div className="flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-sm text-emerald-700 dark:text-emerald-400">
        <CheckCircle2 className="h-4 w-4 shrink-0" />
        <span>AI ready — using <strong>{active?.name ?? 'cloud'}</strong></span>
      </div>
    )
  }

  const hints = health.providers.filter(p => !p.configured && p.hint)
  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm space-y-1">
      <div className="flex items-center gap-2 text-amber-700 dark:text-amber-400 font-medium">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        No AI provider configured — the assistant won&apos;t work yet.
      </div>
      {hints.map(p => (
        <div key={p.name} className="flex items-center gap-2 text-xs text-amber-600 dark:text-amber-500 pl-6">
          <XCircle className="h-3 w-3 shrink-0" />
          <span>{p.hint}</span>
        </div>
      ))}
      <p className="text-xs text-muted-foreground pl-6 pt-1">
        Open <code className="bg-muted px-1 rounded">backend/.env</code>, paste your key, and restart the backend.
      </p>
    </div>
  )
}
