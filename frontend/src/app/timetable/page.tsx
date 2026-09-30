"use client"

import { useEffect, useState, useMemo } from "react"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { RefreshCw, Search, CheckCircle, BookOpen, Shield, Clock, AlertCircle } from "lucide-react"

type FacultyMeta = { id: number; name: string; abbreviation: string | null }
type CellStatus = "free" | "teaching" | "on_duty" | "exempt"
type FacultyCell = { faculty_id: number; status: CellStatus; reason: string }
type ExamRow = {
  exam_id: number
  label: string
  exam_date: string | null
  time_slot: string | null
  faculty: FacultyCell[]
}
type GridData = { exams: ExamRow[]; faculty: FacultyMeta[] }

const STATUS_CONFIG: Record<CellStatus, { label: string; bg: string; text: string; icon: React.ReactNode }> = {
  free:     { label: "Free",     bg: "bg-emerald-500/15 hover:bg-emerald-500/25 border-emerald-500/30", text: "text-emerald-600 dark:text-emerald-400", icon: <CheckCircle className="h-3 w-3" /> },
  teaching: { label: "Teaching", bg: "bg-red-500/10 hover:bg-red-500/15 border-red-500/20",             text: "text-red-600 dark:text-red-400",       icon: <BookOpen className="h-3 w-3" /> },
  on_duty:  { label: "On Duty",  bg: "bg-blue-500/15 hover:bg-blue-500/25 border-blue-500/30",          text: "text-blue-600 dark:text-blue-400",     icon: <Shield className="h-3 w-3" /> },
  exempt:   { label: "Exempt",   bg: "bg-muted/60 border-muted-foreground/20",                          text: "text-muted-foreground",               icon: <Clock className="h-3 w-3" /> },
}

function formatDate(d: string | null) {
  if (!d) return "No date"
  const dt = new Date(d + "T00:00:00")
  return dt.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })
}

export default function TimetablePage() {
  const [grid, setGrid]           = useState<GridData | null>(null)
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState<string | null>(null)
  const [search, setSearch]       = useState("")
  const [filterStatus, setFilter] = useState<CellStatus | "all">("all")

  async function load() {
    setLoading(true); setError(null)
    try {
      const res = await fetch("/api/mst/faculty-grid")
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

  // Summary counts per exam
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

  // highlight columns where a faculty is free for selected filter
  const highlightIds = useMemo(() => {
    if (!grid || filterStatus === "all") return new Set<number>()
    const ids = new Set<number>()
    for (const exam of grid.exams) {
      for (const cell of exam.faculty) {
        if (cell.status === filterStatus) ids.add(cell.faculty_id)
      }
    }
    return ids
  }, [grid, filterStatus])

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
      <span className="ml-3 text-muted-foreground">Loading timetable…</span>
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
      <p className="text-muted-foreground">No MST exams found. Add exams with a date and time slot first.</p>
    </div>
  )

  const visibleFaculty = filteredFaculty

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight">Faculty Free–Busy Grid</h1>
        <p className="text-sm text-muted-foreground">
          Cross-reference of every MST exam slot against every teacher's timetable.
          Green = available for invigilation.
        </p>
      </div>

      {/* Legend + filters */}
      <div className="flex flex-wrap items-center gap-3">
        {(["all", "free", "teaching", "on_duty", "exempt"] as const).map(s => {
          const cfg = s === "all" ? null : STATUS_CONFIG[s]
          const active = filterStatus === s
          return (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-all ${
                active
                  ? "bg-foreground text-background border-foreground"
                  : cfg
                  ? `${cfg.bg} ${cfg.text}`
                  : "border-muted-foreground/30 text-muted-foreground hover:border-foreground/50"
              }`}
            >
              {s === "all" ? "All" : (
                <>{cfg!.icon} {cfg!.label}</>
              )}
            </button>
          )
        })}

        <div className="ml-auto relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            id="timetable-search"
            placeholder="Search faculty…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="pl-8 h-8 w-48 text-sm"
          />
        </div>
        <Button variant="outline" size="sm" onClick={load} className="h-8">
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" />Refresh
        </Button>
      </div>

      {/* Grid */}
      <div className="overflow-x-auto rounded-xl border bg-background shadow-sm">
        <table className="min-w-full text-xs">
          <thead>
            {/* Top header: exam columns */}
            <tr className="border-b">
              <th className="sticky left-0 z-20 bg-background border-r px-3 py-2 text-left font-semibold min-w-[160px]">
                Faculty
              </th>
              {grid.exams.map(exam => (
                <th key={exam.exam_id} className="px-2 py-2 text-center font-semibold min-w-[90px] border-r last:border-r-0">
                  <div className="text-[11px] font-bold">{exam.label}</div>
                  <div className="text-muted-foreground font-normal">{formatDate(exam.exam_date)}</div>
                  <div className="text-muted-foreground font-mono font-normal">{exam.time_slot ?? "—"}</div>
                  {/* mini summary */}
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
            {visibleFaculty.map(f => {
              const isHighlighted = filterStatus !== "all" && highlightIds.has(f.id)
              return (
                <tr
                  key={f.id}
                  className={`transition-colors ${isHighlighted ? "bg-emerald-500/5" : "hover:bg-muted/30"}`}
                >
                  {/* Faculty name cell */}
                  <td className="sticky left-0 z-10 bg-background border-r px-3 py-2">
                    <div className="font-medium truncate max-w-[150px]" title={f.name}>{f.name}</div>
                    {f.abbreviation && (
                      <div className="text-muted-foreground font-mono">{f.abbreviation}</div>
                    )}
                  </td>

                  {/* One cell per exam */}
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
        {visibleFaculty.length} of {grid.faculty.length} faculty shown ·{" "}
        {grid.exams.length} exam slot{grid.exams.length !== 1 ? "s" : ""}
      </p>
    </div>
  )
}
