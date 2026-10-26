"use client"

import { useEffect, useState, useMemo, useCallback } from "react"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { useToast } from "@/components/ui/use-toast"
import {
  CheckCircle2, XCircle, MinusCircle, Search, RefreshCw,
  Users, UserCheck, UserX, AlertCircle,
} from "lucide-react"

const API = "/api"

type Exam = {
  id: number
  label: string
  exam_date: string | null
  time_slot: string | null
  class_id: number | null
  class_name?: string | null
  year?: number | null
  display_name?: string | null
}
type Student = {
  student_id: number; roll_number: string; name: string
  batch_number: number | null; class_name: string; status: string | null
  is_borderline?: boolean; eligibility_status?: string | null; override?: boolean
}
type Mark = "Present" | "Absent" | null

async function apiFetch(path: string, init?: RequestInit) {
  const res = await fetch(`${API}${path}`, init)
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(err.detail ?? `HTTP ${res.status}`)
  }
  return res.json()
}

function markStyle(s: Mark) {
  if (s === "Present") return "border-2 border-emerald-500 bg-emerald-500/10 text-foreground"
  if (s === "Absent")  return "border-2 border-red-500 bg-red-500/10 text-foreground"
  return "border border-dashed border-muted-foreground/40 text-muted-foreground hover:border-foreground/50"
}

function StatusIcon({ mark }: { mark: Mark }) {
  if (mark === "Present") return <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
  if (mark === "Absent")  return <XCircle      className="h-4 w-4 text-red-500 shrink-0" />
  return <MinusCircle className="h-4 w-4 text-muted-foreground/40 shrink-0" />
}

function nextMark(m: Mark): Mark {
  return m === "Present" ? "Absent" : "Present"
}

export default function RollCallPage() {
  const [exams,    setExams]    = useState<Exam[]>([])
  const [examId,   setExamId]   = useState<number | null>(null)
  const [students, setStudents] = useState<Student[]>([])
  const [marks,    setMarks]    = useState<Record<number, Mark>>({})
  const [search,   setSearch]   = useState("")
  const [filter,   setFilter]   = useState<"all" | "present" | "absent" | "unmarked">("all")
  const [loading,  setLoading]  = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [saving,   setSaving]   = useState<Record<number, boolean>>({})
  const [error, setError] = useState<string | null>(null)
  const { toast } = useToast()

  // Load exams on mount
  useEffect(() => {
    apiFetch("/mst/exams").then((e: Exam[]) => {
      setExams(e)
      if (e.length > 0) setExamId(e[0].id)
    }).catch(() => {})
  }, [])

  // Load roll-call when exam changes (stable dependency array)
  const loadRollcall = useCallback(async (id: number) => {
    setLoading(true)
    setError(null)
    try {
      const data: Student[] = await apiFetch(`/mst/attendance/rollcall/${id}`)
      setStudents(data)
      const m: Record<number, Mark> = {}
      for (const s of data) m[s.student_id] = (s.status as Mark) ?? null
      setMarks(m)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (examId) loadRollcall(examId)
  }, [examId, loadRollcall])

  // Mark a student
  async function toggle(studentId: number) {
    if (!examId) return
    const next = nextMark(marks[studentId] ?? null)
    setMarks(prev => ({ ...prev, [studentId]: next }))  // optimistic
    setSaving(prev => ({ ...prev, [studentId]: true }))
    try {
      await apiFetch("/mst/attendance/mark", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mst_exam_id: examId, student_id: studentId, status: next }),
      })
    } catch (e) {
      toast({ title: "Save failed", description: (e as Error).message, variant: "destructive" })
      setMarks(prev => ({ ...prev, [studentId]: marks[studentId] ?? null })) // revert
    } finally {
      setSaving(prev => ({ ...prev, [studentId]: false }))
    }
  }

  // Mark ALL visible students as present in one atomic bulk request
  async function markAllPresent() {
    if (!examId) return
    const toMark = filtered.filter(s => marks[s.student_id] !== "Present")
    if (toMark.length === 0) return

    try {
      await apiFetch("/mst/attendance/mark-bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mst_exam_id: examId,
          student_ids: toMark.map(s => s.student_id),
          status: "Present",
        }),
      })
      setMarks(prev => {
        const next = { ...prev }
        for (const s of toMark) next[s.student_id] = "Present"
        return next
      })
      toast({ title: `${toMark.length} students marked Present` })
    } catch (e) {
      toast({ title: "Bulk save failed", description: (e as Error).message, variant: "destructive" })
    }
  }

  // Submit and finalize attendance to backend + trigger VT recalculation
  async function submitAttendance() {
    if (!examId) return
    setSubmitting(true)
    try {
      const res = await apiFetch("/mst/attendance/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mst_exam_id: examId,
          records: marks,
        }),
      })
      toast({
        title: "Attendance Submitted Successfully",
        description: `${res.present_count} Present, ${res.absent_count} Absent. VT compliance & AI assistant synced (${res.vt_recalculated} records updated).`,
      })
      await loadRollcall(examId)
    } catch (e) {
      toast({
        title: "Attendance submission failed",
        description: (e as Error).message,
        variant: "destructive",
      })
    } finally {
      setSubmitting(false)
    }
  }

  // Counts
  const counts = useMemo(() => {
    let present = 0, absent = 0, unmarked = 0
    for (const m of Object.values(marks)) {
      if (m === "Present") present++
      else if (m === "Absent") absent++
      else unmarked++
    }
    return { present, absent, unmarked, total: students.length }
  }, [marks, students])

  // Filtered list
  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return students.filter(s => {
      const matchSearch = !q || s.roll_number.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)
      const matchFilter =
        filter === "all" ? true :
        filter === "present" ? marks[s.student_id] === "Present" :
        filter === "absent"  ? marks[s.student_id] === "Absent" :
        !marks[s.student_id]
      return matchSearch && matchFilter
    })
  }, [students, marks, search, filter])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <Users className="h-6 w-6" />
          MST Roll Call
        </h1>
        <p className="text-sm text-muted-foreground">
          Click any student to toggle Present / Absent. Saves instantly.
        </p>
      </div>

      {/* Exam selector */}
      <div className="flex flex-wrap items-center gap-3">
        <Select value={examId ? String(examId) : ""} onValueChange={v => setExamId(Number(v))}>
          <SelectTrigger id="rollcall-exam-select" className="min-w-[320px] max-w-md">
            <SelectValue placeholder="Pick an exam…" />
          </SelectTrigger>
          <SelectContent>
            {exams.map(e => (
              <SelectItem key={e.id} value={String(e.id)}>
                {e.display_name || `${e.label} · ${e.class_name || ""} (Yr ${e.year || ""})`} {e.exam_date ? `· ${e.exam_date}` : ""} {e.time_slot ? `· ${e.time_slot}` : ""}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {examId && (
          <Button variant="outline" size="sm" onClick={() => loadRollcall(examId)}>
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Refresh
          </Button>
        )}
      </div>

      {!examId && (
        <div className="flex flex-col items-center justify-center min-h-[300px] gap-3 text-muted-foreground border rounded-2xl bg-card/50">
          <AlertCircle className="h-10 w-10 text-muted-foreground/50" />
          <p className="text-sm font-medium">Select an exam above to view student list & mark attendance.</p>
        </div>
      )}

      {examId && (
        <>
          {/* Stats bar */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: "Total", value: counts.total,    icon: <Users className="h-4 w-4" />,        color: "" },
              { label: "Present", value: counts.present, icon: <UserCheck className="h-4 w-4" />,   color: "text-emerald-600 dark:text-emerald-400" },
              { label: "Absent",  value: counts.absent,  icon: <UserX className="h-4 w-4" />,       color: "text-red-600 dark:text-red-400" },
              { label: "Unmarked",value: counts.unmarked,icon: <MinusCircle className="h-4 w-4" />, color: "text-muted-foreground" },
            ].map(stat => (
              <div key={stat.label} className={`rounded-xl border bg-muted/20 px-4 py-3 flex items-center gap-3 ${stat.color}`}>
                {stat.icon}
                <div>
                  <div className="text-2xl font-bold">{stat.value}</div>
                  <div className="text-xs text-muted-foreground">{stat.label}</div>
                </div>
              </div>
            ))}
          </div>

          {/* Sticky filter + search + bulk actions + SUBMIT ATTENDANCE */}
          <div className="sticky top-0 z-20 bg-background/95 backdrop-blur-sm py-2.5 border-y flex flex-wrap items-center gap-3">
            {(["all", "present", "absent", "unmarked"] as const).map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`rounded-full border px-3 py-1 text-xs font-medium capitalize transition-all ${
                  filter === f
                    ? "bg-foreground text-background border-foreground shadow-sm"
                    : "border-muted-foreground/30 text-muted-foreground hover:border-foreground/50"
                }`}
              >
                {f}
              </button>
            ))}

            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                id="rollcall-search"
                placeholder="Roll or name…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="pl-8 h-8 w-40 md:w-52 text-sm"
              />
            </div>

            <Button variant="outline" size="sm" className="h-8" onClick={markAllPresent}>
              <CheckCircle2 className="h-3.5 w-3.5 mr-1.5 text-emerald-500" />
              All Present
            </Button>

            {/* Main Submit Attendance Button */}
            <Button
              id="submit-attendance-btn"
              size="sm"
              className="h-8 ml-auto bg-emerald-600 hover:bg-emerald-700 text-white font-semibold gap-1.5 shadow-sm px-4"
              onClick={submitAttendance}
              disabled={submitting || students.length === 0}
            >
              {submitting ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
              {submitting ? "Submitting..." : `Submit Attendance (${counts.present + counts.absent}/${counts.total})`}
            </Button>
          </div>

          {/* Error, Loading, Empty, or List */}
          {error ? (
            <div className="flex flex-col items-center justify-center min-h-[300px] gap-3 text-center p-6 border rounded-2xl bg-destructive/5 border-destructive/20">
              <AlertCircle className="h-10 w-10 text-destructive/80" />
              <div className="max-w-md">
                <p className="font-semibold text-base text-foreground">Could not load students for this exam</p>
                <p className="text-sm text-muted-foreground mt-1">{error}</p>
              </div>
              <div className="flex gap-3 mt-2">
                <Button variant="outline" size="sm" onClick={() => examId && loadRollcall(examId)}>
                  Try Again
                </Button>
                <a
                  href="/attendance/upload"
                  className="inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground hover:bg-primary/90 h-9 px-3 text-xs font-medium shadow-sm transition-colors"
                >
                  Upload Attendance & Compute
                </a>
              </div>
            </div>
          ) : loading ? (
            <div className="flex flex-col items-center justify-center min-h-[400px] border rounded-xl bg-muted/5">
              <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground mb-4" />
              <span className="text-muted-foreground text-sm font-medium">Loading students…</span>
            </div>
          ) : students.length === 0 ? (
            <div className="flex flex-col items-center justify-center min-h-[360px] gap-3 text-center p-6 border rounded-2xl bg-card/40">
              <Users className="h-10 w-10 text-muted-foreground/60" />
              <div className="max-w-md">
                <p className="font-semibold text-base text-foreground">No students enrolled yet for this exam</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Upload student attendance data from your excel sheets to populate the roll call roster.
                </p>
              </div>
              <a
                href="/attendance/upload"
                className="mt-2 inline-flex items-center justify-center rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 h-8 px-4 text-xs font-semibold shadow-sm transition-colors"
              >
                Upload Attendance Data
              </a>
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center min-h-[300px] gap-2 text-muted-foreground border rounded-2xl bg-card/40">
              <AlertCircle className="h-8 w-8 text-muted-foreground/60" />
              <p className="text-sm font-medium">No students match filter &ldquo;{filter}&rdquo; or search &ldquo;{search}&rdquo;</p>
              <Button variant="ghost" size="sm" onClick={() => { setSearch(""); setFilter("all"); }}>
                Reset Filters
              </Button>
            </div>
          ) : (
            /* Roll call list with smooth scrolling and sticky header */
            <div className="rounded-xl border bg-card/50 overflow-hidden shadow-sm">
              <div className="grid grid-cols-[auto_1fr_auto_auto] text-xs font-semibold text-muted-foreground uppercase tracking-wide bg-muted/70 border-b px-4 py-3 gap-4">
                <span>#</span>
                <span>Student</span>
                <span>Batch</span>
                <span className="text-right pr-2">Status</span>
              </div>
              <div className="divide-y max-h-[600px] overflow-y-auto overscroll-contain">
                {filtered.map((s, i) => {
                  const mark = marks[s.student_id] ?? null
                  const isSaving = saving[s.student_id]
                  return (
                    <button
                      key={s.student_id}
                      id={`rollcall-row-${s.roll_number}`}
                      onClick={() => toggle(s.student_id)}
                      disabled={isSaving}
                      className={`w-full grid grid-cols-[auto_1fr_auto_auto] items-center gap-4 px-4 py-3 text-left transition-colors ${markStyle(mark)} ${isSaving ? "opacity-60" : ""}`}
                    >
                      {/* Row number + status icon */}
                      <div className="flex items-center gap-2 min-w-[2.5rem]">
                        <StatusIcon mark={mark} />
                        <span className="font-mono text-xs text-muted-foreground w-6 text-right">{i + 1}</span>
                      </div>

                      {/* Name + roll */}
                      <div className="min-w-0">
                        <div className="font-medium text-sm truncate flex items-center gap-2">
                          <span>{s.name}</span>
                          {s.is_borderline && (
                            <Badge className="bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30 text-[10px] px-1.5 py-0 font-normal">
                              Borderline
                            </Badge>
                          )}
                        </div>
                        <div className="font-mono text-xs text-muted-foreground">{s.roll_number}</div>
                      </div>

                      {/* Batch */}
                      <div>
                        {s.batch_number ? (
                          <Badge variant="outline" className="text-xs">B{s.batch_number}</Badge>
                        ) : <span className="text-muted-foreground text-xs">—</span>}
                      </div>

                      {/* Status badge */}
                      <div className="pr-2">
                        {mark === "Present" && <Badge className="bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20 font-medium">Present</Badge>}
                        {mark === "Absent"  && <Badge className="bg-red-500/20 text-red-700 dark:text-red-400 border-red-500/30 hover:bg-red-500/20 font-medium">Absent</Badge>}
                        {!mark && <span className="text-xs text-muted-foreground italic">Tap to mark</span>}
                      </div>
                    </button>
                  )
                })}
              </div>

              {/* Bottom submission footer */}
              <div className="p-3 bg-muted/30 border-t flex flex-wrap items-center justify-between gap-3">
                <span className="text-xs text-muted-foreground font-medium">
                  {counts.present} Present · {counts.absent} Absent · {counts.unmarked} Unmarked
                </span>
                <Button
                  size="sm"
                  className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold gap-1.5 shadow-sm"
                  onClick={submitAttendance}
                  disabled={submitting || students.length === 0}
                >
                  {submitting ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                  Submit & Sync VT Compliance
                </Button>
              </div>
            </div>
          )}

          {/* Progress bar */}
          {!loading && students.length > 0 && (
            <div className="space-y-1">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>{counts.present + counts.absent} of {counts.total} marked</span>
                <span>{Math.round(((counts.present + counts.absent) / counts.total) * 100)}%</span>
              </div>
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full bg-foreground transition-all duration-300"
                  style={{ width: `${((counts.present + counts.absent) / counts.total) * 100}%` }}
                />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
