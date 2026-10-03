"use client"

import { useEffect, useState, useMemo } from "react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useToast } from "@/components/ui/use-toast"
import {
  RefreshCw, Search, CheckCircle, BookOpen, Shield, Clock,
  AlertCircle, CalendarDays, Plus, X, Save, Table2,
} from "lucide-react"

const DAYS = ["MON", "TUE", "WED", "THUR", "FRI"] as const
const PERIODS = [
  { label: "10:30-11:20", start: "10:30", end: "11:20" },
  { label: "11:20-12:10", start: "11:20", end: "12:10" },
  { label: "12:10-1:00",  start: "12:10", end: "13:00" },
  { label: "LUNCH",       start: null as null,    end: null as null },
  { label: "1:50-2:40",   start: "13:50", end: "14:40" },
  { label: "2:40-3:30",   start: "14:40", end: "15:30" },
  { label: "3:30-4:15",   start: "15:30", end: "16:15" },
  { label: "4:15-5:00",   start: "16:15", end: "17:00" },
]

const API = "/api"

type ClassMeta = { id: number; name: string; year: number; branch: string }
type FacultyMeta = { id: number; name: string; abbreviation: string | null }
type TimetableEntry = {
  id?: number
  faculty_id: number
  faculty_name?: string
  subject_code: string
  subject_name?: string
  room: string
  batch?: string
}
type CellKey = string
type CellStatus = "free" | "teaching" | "on_duty" | "exempt"
type FacultyCell = { faculty_id: number; status: CellStatus; reason: string }
type ExamRow = { exam_id: number; label: string; exam_date: string | null; time_slot: string | null; faculty: FacultyCell[] }
type GridData = { exams: ExamRow[]; faculty: FacultyMeta[] }

const cellKey = (day: string, i: number): CellKey => `${day}-${i}`

const STATUS_CONFIG: Record<CellStatus, { label: string; bg: string; text: string; icon: React.ReactNode }> = {
  free:     { label: "Free",     bg: "bg-emerald-500/15 hover:bg-emerald-500/25 border-emerald-500/30", text: "text-emerald-600 dark:text-emerald-400", icon: <CheckCircle className="h-3 w-3" /> },
  teaching: { label: "Teaching", bg: "bg-red-500/10 hover:bg-red-500/15 border-red-500/20",             text: "text-red-600 dark:text-red-400",         icon: <BookOpen className="h-3 w-3" /> },
  on_duty:  { label: "On Duty",  bg: "bg-blue-500/15 hover:bg-blue-500/25 border-blue-500/30",          text: "text-blue-600 dark:text-blue-400",       icon: <Shield className="h-3 w-3" /> },
  exempt:   { label: "Exempt",   bg: "bg-muted/60 border-muted-foreground/20",                          text: "text-muted-foreground",                  icon: <Clock className="h-3 w-3" /> },
}

function formatDate(d: string | null) {
  if (!d) return "No date"
  return new Date(d + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })
}

async function apiFetch(path: string, init?: RequestInit) {
  const res = await fetch(`${API}${path}`, init)
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(err.detail ?? `HTTP ${res.status}`)
  }
  return res.json()
}

// Timetable Input Tab
function TimetableInputTab() {
  const { toast } = useToast()
  const [classes, setClasses] = useState<ClassMeta[]>([])
  const [faculty, setFaculty] = useState<FacultyMeta[]>([])
  const [classId, setClassId] = useState<number | null>(null)
  const [semester, setSemester] = useState("III")
  const [session, setSession] = useState("Jul-Dec 2026")
  const [grid, setGrid] = useState<Record<CellKey, TimetableEntry[]>>({})
  const [editing, setEditing] = useState<{ day: string; periodIdx: number } | null>(null)
  const [draft, setDraft] = useState<TimetableEntry>({ faculty_id: 0, subject_code: "", room: "", batch: "" })
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    apiFetch("/classes").then(setClasses).catch(() => {})
    apiFetch("/faculty").then(setFaculty).catch(() => {})
  }, [])

  useEffect(() => {
    if (!classId) { setGrid({}); return }
    setLoading(true)
    apiFetch(`/timetable/class/${classId}?semester=${encodeURIComponent(semester)}`)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .then((entries: any[]) => {
        const rebuilt: Record<CellKey, TimetableEntry[]> = {}
        for (const e of entries) {
          const idx = PERIODS.findIndex(p => p.start === e.period_start)
          if (idx === -1) continue
          const k = cellKey(e.day_of_week, idx)
          const fac = faculty.find(f => f.id === e.faculty_id)
          const entry: TimetableEntry = {
            id: e.id,
            faculty_id: e.faculty_id,
            faculty_name: fac?.name ?? e.faculty_name,
            subject_code: e.subject_code ?? "",
            subject_name: e.subject_name ?? "",
            room: e.room ?? "",
            batch: e.batch ?? "",
          }
          if (!rebuilt[k]) rebuilt[k] = []
          rebuilt[k].push(entry)
        }
        setGrid(rebuilt)
      })
      .catch(() => setGrid({}))
      .finally(() => setLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classId, semester])

  function openCell(day: string, periodIdx: number) {
    if (!PERIODS[periodIdx].start) return
    setEditing({ day, periodIdx })
    setDraft({ faculty_id: 0, subject_code: "", room: "", batch: "" })
  }

  function addEntryToCell() {
    if (!editing || !draft.faculty_id || !draft.subject_code.trim()) {
      toast({ title: "Incomplete entry", description: "Select a faculty and enter a subject code.", variant: "destructive" })
      return
    }
    const fac = faculty.find(f => f.id === draft.faculty_id)
    const entry: TimetableEntry = { ...draft, faculty_name: fac?.name }
    const k = cellKey(editing.day, editing.periodIdx)
    setGrid(prev => ({ ...prev, [k]: [...(prev[k] ?? []), entry] }))
    setEditing(null)
  }

  function removeEntry(day: string, pidx: number, i: number) {
    const k = cellKey(day, pidx)
    setGrid(prev => ({ ...prev, [k]: prev[k].filter((_, j) => j !== i) }))
  }

  async function saveAll() {
    if (!classId) { toast({ title: "Select a class first", variant: "destructive" }); return }
    const cls = classes.find(c => c.id === classId)
    setSaving(true)
    try {
      const version = await apiFetch("/timetable/version", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ class_id: classId, semester, session }),
      })
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const entries: any[] = []
      for (const day of DAYS) {
        PERIODS.forEach((p, idx) => {
          if (!p.start) return
          const k = cellKey(day, idx)
          for (const e of grid[k] ?? []) {
            entries.push({
              faculty_id: e.faculty_id,
              day_of_week: day,
              period_start: p.start,
              period_end: p.end,
              subject_code: e.subject_code || null,
              subject_name: e.subject_name || null,
              room: e.room || null,
              batch: e.batch || null,
              class_id: classId,
              year: cls?.year ?? 2,
              semester,
              timetable_version_id: version.id,
            })
          }
        })
      }
      if (entries.length === 0) {
        toast({ title: "Nothing to save", description: "Add at least one class entry.", variant: "destructive" })
        return
      }
      await apiFetch("/timetable/entries/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(entries),
      })
      toast({ title: `Saved ${entries.length} entries`, description: "Timetable committed. The duty scheduler will use this data." })
    } catch (e) {
      toast({ title: "Save failed", description: (e as Error).message, variant: "destructive" })
    } finally {
      setSaving(false)
    }
  }

  const selectedClass = classes.find(c => c.id === classId)

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Class</label>
          <Select onValueChange={v => setClassId(Number(v))}>
            <SelectTrigger id="tt-class-select" className="w-52">
              <SelectValue placeholder="Select class..." />
            </SelectTrigger>
            <SelectContent>
              {classes.map(c => (
                <SelectItem key={c.id} value={String(c.id)}>
                  {c.name} · Yr {c.year}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Semester</label>
          <Input id="tt-semester" className="w-24 h-9" value={semester} onChange={e => setSemester(e.target.value)} placeholder="e.g. III" />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Session</label>
          <Input id="tt-session" className="w-44 h-9" value={session} onChange={e => setSession(e.target.value)} placeholder="e.g. Jul-Dec 2026" />
        </div>
        <Button id="tt-save-btn" onClick={saveAll} disabled={saving || !classId} className="h-9 ml-auto gap-2">
          {saving ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          Save timetable
        </Button>
      </div>

      {selectedClass && (
        <p className="text-xs text-muted-foreground bg-muted/30 rounded-lg px-4 py-2 border">
          Entering timetable for <strong>{selectedClass.name}</strong> (Year {selectedClass.year} · {selectedClass.branch}).
          Include <em>all</em> classes — including non-MST years — so the duty scheduler can detect clashes correctly.
        </p>
      )}

      {loading && (
        <div className="flex items-center justify-center h-40 gap-2 text-muted-foreground">
          <RefreshCw className="h-5 w-5 animate-spin" />
          <span className="text-sm">Loading existing entries...</span>
        </div>
      )}

      {!loading && (
        <div className="overflow-x-auto rounded-xl border bg-background shadow-sm">
          <table className="min-w-full text-xs border-collapse">
            <thead>
              <tr className="border-b bg-muted/40">
                <th className="sticky left-0 z-20 bg-muted/40 px-3 py-3 text-left font-semibold min-w-[60px] border-r">Day</th>
                {PERIODS.map((p, i) => (
                  <th key={i} className={`px-2 py-3 text-center font-semibold min-w-[100px] border-r last:border-r-0 whitespace-nowrap ${!p.start ? "bg-muted/20 text-muted-foreground" : ""}`}>
                    {p.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {DAYS.map(day => (
                <tr key={day} className="hover:bg-muted/10 transition-colors">
                  <td className="sticky left-0 z-10 bg-background border-r px-3 py-2 font-bold text-xs">{day}</td>
                  {PERIODS.map((p, idx) => {
                    if (!p.start) {
                      return (
                        <td key={idx} className="border-r last:border-r-0 px-2 py-2 text-center text-muted-foreground bg-muted/10">
                          <span className="text-[10px]">LUNCH</span>
                        </td>
                      )
                    }
                    const k = cellKey(day, idx)
                    const entries = grid[k] ?? []
                    return (
                      <td
                        key={idx}
                        className="border-r last:border-r-0 px-1.5 py-1.5 align-top cursor-pointer hover:bg-accent/30 transition-colors min-w-[100px] group"
                        onClick={() => openCell(day, idx)}
                        id={`tt-cell-${day}-${idx}`}
                      >
                        {entries.length === 0 ? (
                          <span className="text-muted-foreground/40 group-hover:text-muted-foreground transition-colors flex items-center justify-center h-8">
                            <Plus className="h-3 w-3" />
                          </span>
                        ) : (
                          <div className="space-y-1">
                            {entries.map((e, i) => (
                              <div
                                key={i}
                                className="rounded-md border border-border/60 bg-muted/30 px-1.5 py-1 flex items-start justify-between gap-1 group/entry"
                              >
                                <div className="min-w-0">
                                  <div className="font-semibold truncate">{e.subject_code}{e.batch ? `/${e.batch}` : ""}</div>
                                  <div className="text-muted-foreground truncate text-[10px]">{e.faculty_name ?? `ID:${e.faculty_id}`}</div>
                                  {e.room && <div className="text-muted-foreground/70 font-mono truncate text-[10px]">{e.room}</div>}
                                </div>
                                <button
                                  className="opacity-0 group-hover/entry:opacity-100 text-destructive shrink-0 transition-opacity mt-0.5"
                                  onClick={ev => { ev.stopPropagation(); removeEntry(day, idx, i) }}
                                  aria-label="Remove entry"
                                >
                                  <X className="h-3 w-3" />
                                </button>
                              </div>
                            ))}
                          </div>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Click any cell to add a class. Each cell can hold multiple entries for split batches (B1/B2).
        Saving creates a new timetable version — old data is kept for audit.
      </p>

      <Dialog open={!!editing} onOpenChange={() => setEditing(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              Add class — {editing?.day} {editing !== null ? PERIODS[editing.periodIdx].label : ""}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-1">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Faculty *</label>
              <Select onValueChange={v => setDraft(d => ({ ...d, faculty_id: Number(v) }))}>
                <SelectTrigger id="tt-dialog-faculty">
                  <SelectValue placeholder="Select faculty..." />
                </SelectTrigger>
                <SelectContent>
                  {faculty.map(f => (
                    <SelectItem key={f.id} value={String(f.id)}>
                      {f.name} {f.abbreviation ? `(${f.abbreviation})` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Subject code *</label>
              <Input
                id="tt-dialog-subject"
                placeholder="e.g. CSIT-303"
                value={draft.subject_code}
                onChange={e => setDraft(d => ({ ...d, subject_code: e.target.value }))}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Subject name (optional)</label>
              <Input
                id="tt-dialog-subname"
                placeholder="e.g. Operating Systems"
                value={draft.subject_name ?? ""}
                onChange={e => setDraft(d => ({ ...d, subject_name: e.target.value }))}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Room / lab</label>
                <Input
                  id="tt-dialog-room"
                  placeholder="e.g. LR-349"
                  value={draft.room}
                  onChange={e => setDraft(d => ({ ...d, room: e.target.value }))}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Batch (if split)</label>
                <Input
                  id="tt-dialog-batch"
                  placeholder="B1 or B2"
                  value={draft.batch ?? ""}
                  onChange={e => setDraft(d => ({ ...d, batch: e.target.value }))}
                />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
            <Button id="tt-dialog-add" onClick={addEntryToCell} className="gap-2">
              <Plus className="h-3.5 w-3.5" /> Add to cell
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// Faculty Free-Busy Grid Tab
function FreeBusyGridTab() {
  const [grid, setGrid]           = useState<GridData | null>(null)
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState<string | null>(null)
  const [search, setSearch]       = useState("")
  const [filterStatus, setFilter] = useState<CellStatus | "all">("all")

  async function load() {
    setLoading(true); setError(null)
    try {
      const res = await fetch(`${API}/mst/faculty-grid`)
      if (!res.ok) throw new Error(`Server returned ${res.status}`)
      setGrid(await res.json())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const filteredFaculty = useMemo(() => {
    if (!grid) return []
    const q = search.toLowerCase()
    return grid.faculty.filter(f =>
      f.name.toLowerCase().includes(q) ||
      (f.abbreviation ?? "").toLowerCase().includes(q)
    )
  }, [grid, search])

  const examSummary = useMemo(() => {
    if (!grid) return {}
    const out: Record<number, Record<CellStatus, number>> = {}
    for (const exam of grid.exams) {
      const counts: Record<CellStatus, number> = { free: 0, teaching: 0, on_duty: 0, exempt: 0 }
      for (const cell of exam.faculty) counts[cell.status] = (counts[cell.status] ?? 0) + 1
      out[exam.exam_id] = counts
    }
    return out
  }, [grid])

  const highlightIds = useMemo(() => {
    if (!grid || filterStatus === "all") return new Set<number>()
    const ids = new Set<number>()
    for (const exam of grid.exams)
      for (const cell of exam.faculty)
        if (cell.status === filterStatus) ids.add(cell.faculty_id)
    return ids
  }, [grid, filterStatus])

  if (loading) return (
    <div className="flex items-center justify-center h-64 gap-3 text-muted-foreground">
      <RefreshCw className="h-5 w-5 animate-spin" />
      <span className="text-sm">Loading timetable...</span>
    </div>
  )

  if (error) return (
    <div className="flex flex-col items-center justify-center h-64 gap-4">
      <AlertCircle className="h-10 w-10 text-destructive" />
      <p className="text-sm text-muted-foreground">{error}</p>
      <Button variant="outline" size="sm" onClick={load}><RefreshCw className="h-3 w-3 mr-2" />Retry</Button>
    </div>
  )

  if (!grid || grid.exams.length === 0) return (
    <div className="flex flex-col items-center justify-center h-64 gap-2">
      <Clock className="h-10 w-10 text-muted-foreground" />
      <p className="text-muted-foreground text-sm text-center">
        No MST exams found with date + time slot.<br />
        Add exams first, or enter the timetable in the Input tab.
      </p>
    </div>
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        {(["all", "free", "teaching", "on_duty", "exempt"] as const).map(s => {
          const cfg = s === "all" ? null : STATUS_CONFIG[s]
          const active = filterStatus === s
          return (
            <button
              key={s}
              id={`tt-filter-${s}`}
              onClick={() => setFilter(s)}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-all ${
                active
                  ? "bg-foreground text-background border-foreground"
                  : cfg
                  ? `${cfg.bg} ${cfg.text}`
                  : "border-muted-foreground/30 text-muted-foreground hover:border-foreground/50"
              }`}
            >
              {s === "all" ? "All" : <>{cfg!.icon} {cfg!.label}</>}
            </button>
          )
        })}

        <div className="ml-auto relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            id="tt-grid-search"
            placeholder="Search faculty..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="pl-8 h-8 w-48 text-sm"
          />
        </div>
        <Button variant="outline" size="sm" onClick={load} className="h-8">
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" />Refresh
        </Button>
      </div>

      <div className="overflow-x-auto rounded-xl border bg-background shadow-sm">
        <table className="min-w-full text-xs">
          <thead>
            <tr className="border-b">
              <th className="sticky left-0 z-20 bg-background border-r px-3 py-2 text-left font-semibold min-w-[160px]">Faculty</th>
              {grid.exams.map(exam => (
                <th key={exam.exam_id} className="px-2 py-2 text-center font-semibold min-w-[90px] border-r last:border-r-0">
                  <div className="text-[11px] font-bold">{exam.label}</div>
                  <div className="text-muted-foreground font-normal">{formatDate(exam.exam_date)}</div>
                  <div className="text-muted-foreground font-mono font-normal">{exam.time_slot ?? "—"}</div>
                  <div className="mt-1 flex items-center justify-center gap-1">
                    <span className="text-emerald-600 dark:text-emerald-400 font-bold">
                      {examSummary[exam.exam_id]?.free ?? 0} free
                    </span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y">
            {filteredFaculty.map(f => {
              const isHighlighted = filterStatus !== "all" && highlightIds.has(f.id)
              return (
                <tr
                  key={f.id}
                  className={`transition-colors ${isHighlighted ? "bg-emerald-500/5" : "hover:bg-muted/30"}`}
                >
                  <td className="sticky left-0 z-10 bg-background border-r px-3 py-2">
                    <div className="font-medium truncate max-w-[150px]" title={f.name}>{f.name}</div>
                    {f.abbreviation && <div className="text-muted-foreground font-mono">{f.abbreviation}</div>}
                  </td>
                  {grid.exams.map(exam => {
                    const cellMap = Object.fromEntries(exam.faculty.map(c => [c.faculty_id, c]))
                    const cell = cellMap[f.id] as FacultyCell | undefined
                    const status = cell?.status ?? "free"
                    const cfg = STATUS_CONFIG[status]
                    return (
                      <td key={exam.exam_id} className="px-1.5 py-1.5 text-center border-r last:border-r-0">
                        <div
                          className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 ${cfg.bg} ${cfg.text} font-medium whitespace-nowrap`}
                          title={cell?.reason}
                        >
                          {cfg.icon}
                          <span>{cfg.label}</span>
                        </div>
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-muted-foreground">
        {filteredFaculty.length} of {grid.faculty.length} faculty shown · {grid.exams.length} exam slot{grid.exams.length !== 1 ? "s" : ""}
      </p>
    </div>
  )
}

export default function TimetablePage() {
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <CalendarDays className="h-6 w-6" />
          Timetable
        </h1>
        <p className="text-sm text-muted-foreground">
          Enter class timetables for all years, then view the faculty free–busy grid for MST duty scheduling.
        </p>
      </div>

      <Tabs defaultValue="input" className="space-y-5">
        <TabsList className="grid w-full max-w-xs grid-cols-2">
          <TabsTrigger value="input" className="gap-2">
            <Table2 className="h-3.5 w-3.5" /> Input
          </TabsTrigger>
          <TabsTrigger value="grid" className="gap-2">
            <CheckCircle className="h-3.5 w-3.5" /> Free Grid
          </TabsTrigger>
        </TabsList>

        <TabsContent value="input">
          <TimetableInputTab />
        </TabsContent>

        <TabsContent value="grid">
          <FreeBusyGridTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
