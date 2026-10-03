'use client'

import { useState, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import { useToast } from "@/components/ui/use-toast"
import {
  Settings, Database, Server, RefreshCw, CheckCircle, XCircle,
  Users, ShieldOff, Pencil, Plus,
} from 'lucide-react'

type AIProvider = { name: string; configured: boolean; hint?: string }
type HealthData = { ready: boolean; providers: AIProvider[] }
type SystemInfo = { classes: number; faculty: number; rooms: number; exams: number }

type FacultyRow = {
  id: number
  name: string
  abbreviation: string | null
  department: string | null
  exempt_from_duty: boolean
  exempt_reason: string | null
  max_duties_per_day: number | null
}

type ClassRow = { id: number; name: string; branch: string; year: number; section: string | null }

const API = '/api'

async function apiFetch(path: string, init?: RequestInit) {
  const res = await fetch(`${API}${path}`, init)
  if (!res.ok) {
    const e = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(e.detail ?? `HTTP ${res.status}`)
  }
  return res.json()
}

// Faculty management tab
function FacultyTab() {
  const { toast } = useToast()
  const [faculty, setFaculty] = useState<FacultyRow[]>([])
  const [editing, setEditing] = useState<FacultyRow | null>(null)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState<Partial<FacultyRow>>({})
  const [busy, setBusy] = useState(false)

  const load = () =>
    apiFetch('/faculty').then(setFaculty).catch(() => {})

  useEffect(() => { load() }, [])

  function openEdit(f: FacultyRow) {
    setEditing(f)
    setDraft({ ...f })
  }

  function openAdd() {
    setDraft({ name: '', abbreviation: '', department: '', exempt_from_duty: false, exempt_reason: '', max_duties_per_day: 2 })
    setAdding(true)
  }

  async function save() {
    if (!draft.name?.trim()) {
      toast({ title: 'Name is required', variant: 'destructive' }); return
    }
    setBusy(true)
    try {
      if (adding) {
        await apiFetch('/faculty', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(draft),
        })
        toast({ title: 'Faculty added' })
        setAdding(false)
      } else if (editing) {
        await apiFetch(`/faculty/${editing.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(draft),
        })
        toast({ title: 'Saved' })
        setEditing(null)
      }
      load()
    } catch (e) {
      toast({ title: 'Save failed', description: (e as Error).message, variant: 'destructive' })
    } finally {
      setBusy(false)
    }
  }

  async function toggleExempt(f: FacultyRow) {
    const newExempt = !f.exempt_from_duty
    if (newExempt && !f.exempt_reason) {
      // open dialog so user can provide reason
      openEdit(f)
      return
    }
    try {
      await apiFetch(`/faculty/${f.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ exempt_from_duty: newExempt }),
      })
      load()
    } catch (e) {
      toast({ title: 'Update failed', description: (e as Error).message, variant: 'destructive' })
    }
  }

  const dialogOpen = !!editing || adding
  const onClose = () => { setEditing(null); setAdding(false) }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Manage faculty exemptions, duty limits, and abbreviations used by the timetable and duty scheduler.
        </p>
        <Button size="sm" onClick={openAdd} className="gap-2">
          <Plus className="h-3.5 w-3.5" /> Add faculty
        </Button>
      </div>

      <div className="rounded-xl border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 border-b">
            <tr>
              <th className="px-4 py-2 text-left font-semibold">Name</th>
              <th className="px-3 py-2 text-left font-semibold">Abbr</th>
              <th className="px-3 py-2 text-left font-semibold">Dept</th>
              <th className="px-3 py-2 text-center font-semibold">Max duties/day</th>
              <th className="px-3 py-2 text-center font-semibold">Exempt</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y">
            {faculty.map(f => (
              <tr key={f.id} className="hover:bg-muted/20 transition-colors">
                <td className="px-4 py-2.5 font-medium">{f.name}</td>
                <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{f.abbreviation ?? '—'}</td>
                <td className="px-3 py-2.5 text-muted-foreground text-xs">{f.department ?? '—'}</td>
                <td className="px-3 py-2.5 text-center font-mono">{f.max_duties_per_day ?? 2}</td>
                <td className="px-3 py-2.5 text-center">
                  {f.exempt_from_duty ? (
                    <button
                      onClick={() => toggleExempt(f)}
                      title={f.exempt_reason ?? 'Exempt'}
                      className="inline-flex items-center gap-1 text-xs font-medium text-destructive hover:underline"
                    >
                      <ShieldOff className="h-3.5 w-3.5" /> Exempt
                    </button>
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right">
                  <Button variant="ghost" size="sm" onClick={() => openEdit(f)} className="h-7 gap-1.5">
                    <Pencil className="h-3 w-3" /> Edit
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={dialogOpen} onOpenChange={onClose}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{adding ? 'Add faculty member' : `Edit — ${editing?.name}`}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-1">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Name *</label>
              <Input
                id="fac-dialog-name"
                value={draft.name ?? ''}
                onChange={e => setDraft(d => ({ ...d, name: e.target.value }))}
                placeholder="Prof. Full Name"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Abbreviation</label>
                <Input
                  id="fac-dialog-abbr"
                  value={draft.abbreviation ?? ''}
                  onChange={e => setDraft(d => ({ ...d, abbreviation: e.target.value }))}
                  placeholder="e.g. VK"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Max duties / day</label>
                <Input
                  id="fac-dialog-maxduty"
                  type="number"
                  min={0}
                  max={5}
                  value={draft.max_duties_per_day ?? 2}
                  onChange={e => setDraft(d => ({ ...d, max_duties_per_day: Number(e.target.value) }))}
                />
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Department</label>
              <Input
                id="fac-dialog-dept"
                value={draft.department ?? ''}
                onChange={e => setDraft(d => ({ ...d, department: e.target.value }))}
                placeholder="e.g. CSE"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground flex items-center gap-2">
                <input
                  id="fac-dialog-exempt"
                  type="checkbox"
                  className="rounded"
                  checked={!!draft.exempt_from_duty}
                  onChange={e => setDraft(d => ({ ...d, exempt_from_duty: e.target.checked }))}
                />
                Exempt from invigilation duty
              </label>
            </div>
            {draft.exempt_from_duty && (
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Exemption reason *</label>
                <Input
                  id="fac-dialog-exempt-reason"
                  value={draft.exempt_reason ?? ''}
                  onChange={e => setDraft(d => ({ ...d, exempt_reason: e.target.value }))}
                  placeholder="e.g. HOD — excluded by department policy"
                />
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button id="fac-dialog-save" onClick={save} disabled={busy} className="gap-2">
              {busy && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// Classes tab
function ClassesTab() {
  const { toast } = useToast()
  const [classes, setClasses] = useState<ClassRow[]>([])
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState({ name: '', branch: '', year: '2', section: '' })
  const [busy, setBusy] = useState(false)

  const load = () =>
    apiFetch('/classes').then(setClasses).catch(() => {})

  useEffect(() => { load() }, [])

  async function add() {
    if (!draft.name.trim() || !draft.branch.trim()) {
      toast({ title: 'Name and branch are required', variant: 'destructive' }); return
    }
    setBusy(true)
    try {
      await apiFetch('/classes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: draft.name.trim(),
          branch: draft.branch.trim(),
          year: Number(draft.year),
          section: draft.section.trim() || null,
        }),
      })
      toast({ title: 'Class added' })
      setAdding(false)
      load()
    } catch (e) {
      toast({ title: 'Failed', description: (e as Error).message, variant: 'destructive' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Classes define which students belong to which branch and year. Timetable entries are attached to a class.
        </p>
        <Button size="sm" onClick={() => setAdding(true)} className="gap-2">
          <Plus className="h-3.5 w-3.5" /> Add class
        </Button>
      </div>

      <div className="rounded-xl border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 border-b">
            <tr>
              <th className="px-4 py-2 text-left font-semibold">Name</th>
              <th className="px-4 py-2 text-left font-semibold">Branch</th>
              <th className="px-4 py-2 text-center font-semibold">Year</th>
              <th className="px-4 py-2 text-left font-semibold">Section</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {classes.map(c => (
              <tr key={c.id} className="hover:bg-muted/20 transition-colors">
                <td className="px-4 py-2.5 font-mono font-medium">{c.name}</td>
                <td className="px-4 py-2.5">{c.branch}</td>
                <td className="px-4 py-2.5 text-center">{c.year}</td>
                <td className="px-4 py-2.5 text-muted-foreground">{c.section ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={adding} onOpenChange={() => setAdding(false)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader><DialogTitle>Add class</DialogTitle></DialogHeader>
          <div className="space-y-3 py-1">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Name * (e.g. CI-1 III)</label>
              <Input id="cls-name" value={draft.name} onChange={e => setDraft(d => ({ ...d, name: e.target.value }))} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Branch * (e.g. CI-1)</label>
                <Input id="cls-branch" value={draft.branch} onChange={e => setDraft(d => ({ ...d, branch: e.target.value }))} />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Year *</label>
                <Input id="cls-year" type="number" min={1} max={5} value={draft.year} onChange={e => setDraft(d => ({ ...d, year: e.target.value }))} />
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Section (optional)</label>
              <Input id="cls-section" value={draft.section} onChange={e => setDraft(d => ({ ...d, section: e.target.value }))} placeholder="A / B" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAdding(false)}>Cancel</Button>
            <Button id="cls-add-btn" onClick={add} disabled={busy}>
              {busy && <RefreshCw className="h-3.5 w-3.5 animate-spin mr-1.5" />}Add
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// System status tab
function SystemTab() {
  const [health, setHealth] = useState<HealthData | null>(null)
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const loadAll = async () => {
    setRefreshing(true)
    try {
      const [healthRes, classesRes, facultyRes, roomsRes, examsRes] = await Promise.all([
        fetch('/api/ai/health').then(r => r.ok ? r.json() : null),
        fetch('/api/classes').then(r => r.ok ? r.json() : []),
        fetch('/api/faculty').then(r => r.ok ? r.json() : []),
        fetch('/api/rooms').then(r => r.ok ? r.json() : []),
        fetch('/api/mst/exams').then(r => r.ok ? r.json() : []),
      ])
      setHealth(healthRes)
      setInfo({ classes: classesRes.length, faculty: facultyRes.length, rooms: roomsRes.length, exams: examsRes.length })
    } catch { /* ignore */ } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => { loadAll() }, [])

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Server className="h-4 w-4" /> Backend Connection
            </CardTitle>
            <CardDescription>FastAPI server on localhost:8000</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {info ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-400 font-medium">
                  <CheckCircle className="h-4 w-4" /> Connected
                </div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm text-muted-foreground">
                  <span>Classes</span><span className="font-mono font-medium text-foreground">{info.classes}</span>
                  <span>Faculty</span><span className="font-mono font-medium text-foreground">{info.faculty}</span>
                  <span>Rooms</span><span className="font-mono font-medium text-foreground">{info.rooms}</span>
                  <span>MST Exams</span><span className="font-mono font-medium text-foreground">{info.exams}</span>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
                <XCircle className="h-4 w-4" /> Cannot reach backend — is uvicorn running?
              </div>
            )}
            <Button variant="outline" size="sm" onClick={loadAll} disabled={refreshing}>
              <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${refreshing ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Database className="h-4 w-4" /> AI Providers
            </CardTitle>
            <CardDescription>Configure keys in backend/.env to enable AI</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {health ? (
              health.providers.map(p => (
                <div key={p.name} className="flex items-start gap-2">
                  {p.configured
                    ? <CheckCircle className="h-4 w-4 text-emerald-500 shrink-0 mt-0.5" />
                    : <XCircle className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                  }
                  <div>
                    <span className="text-sm font-medium capitalize">{p.name}</span>
                    <Badge className="ml-2 text-[10px]" variant={p.configured ? 'default' : 'secondary'}>
                      {p.configured ? 'Active' : 'Not set'}
                    </Badge>
                    {p.hint && <p className="text-xs text-muted-foreground mt-0.5">{p.hint}</p>}
                  </div>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">Loading AI status...</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Eligibility Rules</CardTitle>
          <CardDescription>These thresholds govern automatic eligibility computation after each upload.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-3">
            {[
              { label: 'Eligible threshold', value: '>= 50%', desc: 'Overall attendance required to sit the exam' },
              { label: 'Borderline zone', value: '45–49%', desc: 'HOD review required before final decision' },
              { label: 'Not eligible', value: '< 45%', desc: 'Student is barred unless HOD grants an override' },
            ].map(rule => (
              <div key={rule.label} className="rounded-lg border p-4 space-y-1">
                <div className="text-xs text-muted-foreground font-medium uppercase tracking-wide">{rule.label}</div>
                <div className="text-xl font-bold font-mono">{rule.value}</div>
                <div className="text-xs text-muted-foreground">{rule.desc}</div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">VT / Follow-up Rule</CardTitle>
          <CardDescription>Rule: absent-both-mst-v1</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            A student is marked Compulsory VT if they were absent in <strong>both</strong> MST-1 and MST-2.
            Appearing in at least one exam removes the VT requirement.
            An approved absence (medical, HOD override) does <em>not</em> exempt from VT — it only affects eligibility bookkeeping.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Data Flow</CardTitle>
          <CardDescription>How the pieces connect end-to-end</CardDescription>
        </CardHeader>
        <CardContent>
          <ol className="space-y-2 text-sm text-muted-foreground list-decimal pl-5">
            <li><strong className="text-foreground">Upload Attendance</strong> — import Excel sheets (.xlsx). Each subject sheet data is stored per student.</li>
            <li><strong className="text-foreground">Eligibility</strong> — automatically computed from the latest records. View and HOD-override here.</li>
            <li><strong className="text-foreground">MST Seat Map</strong> — create exams + rooms, generate seating (B1/B2 interleaved), mark attendance during exam.</li>
            <li><strong className="text-foreground">MST Roll Call</strong> — alternative list-based roll-call view, syncs the same attendance records.</li>
            <li><strong className="text-foreground">VT / Follow-up</strong> — auto-calculated after marking. Export as Excel or PDF.</li>
            <li><strong className="text-foreground">Duty Scheduler</strong> — auto-assigns free faculty to rooms based on timetable data.</li>
            <li><strong className="text-foreground">Timetable</strong> — enter class schedules for all years; view faculty free-busy grid for clash detection.</li>
            <li><strong className="text-foreground">AI Assistant</strong> — query data or propose writes in plain English (all writes need confirmation).</li>
          </ol>
        </CardContent>
      </Card>
    </div>
  )
}

export default function SettingsPage() {
  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
          <Settings className="h-8 w-8" />
          Settings
        </h1>
        <p className="text-muted-foreground mt-2">
          System configuration, faculty management, and status overview.
        </p>
      </div>

      <Tabs defaultValue="faculty" className="space-y-5">
        <TabsList>
          <TabsTrigger value="faculty" className="gap-2">
            <Users className="h-3.5 w-3.5" /> Faculty
          </TabsTrigger>
          <TabsTrigger value="classes" className="gap-2">
            <Database className="h-3.5 w-3.5" /> Classes
          </TabsTrigger>
          <TabsTrigger value="system" className="gap-2">
            <Server className="h-3.5 w-3.5" /> System
          </TabsTrigger>
        </TabsList>

        <TabsContent value="faculty">
          <FacultyTab />
        </TabsContent>
        <TabsContent value="classes">
          <ClassesTab />
        </TabsContent>
        <TabsContent value="system">
          <SystemTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
