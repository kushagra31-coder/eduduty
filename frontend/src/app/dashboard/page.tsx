"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Users,
  CheckCircle,
  Clock,
  CalendarDays,
  Upload,
  PenLine,
  Activity,
  AlertCircle,
  Shield,
  UserCheck,
  ClipboardCheck,
  Armchair,
  BookOpen,
  ArrowRight,
  Eye,
  CheckCircle2,
  Calendar,
  AlertTriangle,
  Server,
  Sparkles,
} from "lucide-react"
import { apiFetch, getApiErrorMessage } from "@/lib/api"
import { useAuth } from "@/lib/auth/context"
import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type ActivityItem = {
  kind: string
  title: string
  detail: string
  at: string | null
}

type ClassRow = {
  class: string
  students: number
  eligible: number
  borderline: number
  ineligible: number
}

type Stats = {
  exam_label: string
  total_students: number
  eligible: number
  eligible_pct: number
  borderline: number
  ineligible: number
  overrides: number
  per_class: ClassRow[]
  timetable: { versions: number; periods: number; classes: string[] }
  recent_activity: ActivityItem[]
}

type MstExam = {
  id: number
  label: string
  exam_date: string | null
  time_slot: string | null
  class_id: number | null
}

type FollowUpStats = {
  total_evaluated: number
  total_students: number
  missing_records: number
  by_final_status: Record<string, number>
  by_calculated_status: Record<string, number>
}

type DutyItem = {
  id: number
  room_id: number
  room_number: string
  faculty_id: number | null
  faculty_name: string | null
  status: string
  exam_label?: string
  exam_date?: string | null
  time_slot?: string | null
}

type TimetableSlot = {
  id: number
  faculty_id: number
  day_of_week: string
  period_start: string
  period_end: string
  subject_code: string | null
  subject_name: string | null
  room: string | null
  batch: string | null
}

function timeAgo(iso: string | null): string {
  if (!iso) return ""
  const secs = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000))
  if (secs < 60) return "just now"
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} hr ago`
  const days = Math.floor(hrs / 24)
  return days === 1 ? "yesterday" : `${days} days ago`
}

function StatCard({
  title,
  icon,
  value,
  desc,
  highlight,
}: {
  title: string
  icon: React.ReactNode
  value: string
  desc: string
  highlight?: boolean
}) {
  return (
    <Card className={`hover:shadow-md transition-shadow border-t-4 ${highlight ? "border-t-primary shadow-xs" : "border-t-foreground/40"}`}>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        {icon}
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold font-mono tabular-nums">{value}</div>
        <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{desc}</p>
      </CardContent>
    </Card>
  )
}

export default function Dashboard() {
  const { user, role, facultyId } = useAuth()
  const [stats, setStats] = useState<Stats | null>(null)
  const [exams, setExams] = useState<MstExam[]>([])
  const [followUpStats, setFollowUpStats] = useState<FollowUpStats | null>(null)
  const [myDuties, setMyDuties] = useState<DutyItem[]>([])
  const [myTimetable, setMyTimetable] = useState<TimetableSlot[]>([])
  const [aiHealth, setAiHealth] = useState<{ status: string; provider?: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true

    async function loadDashboardData() {
      setLoading(true)
      try {
        // 1. Core Statistics (accessible to all authenticated roles)
        const statsRes = await apiFetch("/dashboard/stats")
        if (!statsRes.ok) {
          const msg = await getApiErrorMessage(statsRes, "Could not load dashboard statistics")
          throw new Error(msg)
        }
        const statsData: Stats = await statsRes.json()
        if (isMounted) setStats(statsData)

        // 2. Fetch Exams List
        const examsRes = await apiFetch("/mst/exams")
        let examsData: MstExam[] = []
        if (examsRes.ok) {
          examsData = await examsRes.json()
          if (isMounted) setExams(examsData)
        }

        // 3. Role-specific supplementary fetches
        if (role === "EXAM_COORDINATOR" || role === "SUPER_ADMIN" || role === "ADMIN") {
          // Follow-up statistics
          apiFetch("/follow-up/stats")
            .then((r) => (r.ok ? r.json() : null))
            .then((data) => {
              if (isMounted && data) setFollowUpStats(data)
            })
            .catch(() => {})

          // AI Health check for Super Admin
          if (role === "SUPER_ADMIN") {
            apiFetch("/ai/health")
              .then((r) => (r.ok ? r.json() : null))
              .then((data) => {
                if (isMounted && data) setAiHealth(data)
              })
              .catch(() => {})
          }
        }

        // 4. Faculty-specific duties and timetable
        if (role === "FACULTY") {
          const fid = facultyId ?? 1 // default to demo faculty ID 1 if not explicitly in session
          const allDuties: DutyItem[] = []

          // Probe duties for the exams
          for (const exam of examsData) {
            try {
              const dRes = await apiFetch(`/mst/duties/${exam.id}`)
              if (dRes.ok) {
                const dutiesList: DutyItem[] = await dRes.json()
                for (const d of dutiesList) {
                  if (d.faculty_id === fid) {
                    allDuties.push({
                      ...d,
                      exam_label: exam.label,
                      exam_date: exam.exam_date,
                      time_slot: exam.time_slot,
                    })
                  }
                }
              }
            } catch {
              // Ignore single-exam duty fetch errors
            }
          }
          if (isMounted) setMyDuties(allDuties)

          // Load timetable slots for faculty
          try {
            const classesRes = await apiFetch("/classes")
            if (classesRes.ok) {
              const classesList = await classesRes.json()
              const slots: TimetableSlot[] = []
              for (const c of classesList.slice(0, 3)) {
                const ttRes = await apiFetch(`/timetable/class/${c.id}`)
                if (ttRes.ok) {
                  const ttData: TimetableSlot[] = await ttRes.json()
                  for (const slot of ttData) {
                    if (slot.faculty_id === fid) {
                      slots.push(slot)
                    }
                  }
                }
              }
              if (isMounted) setMyTimetable(slots)
            }
          } catch {
            // Ignore timetable auxiliary error
          }
        }

        if (isMounted) setErrorMessage(null)
      } catch (err) {
        if (isMounted) {
          setErrorMessage(err instanceof Error ? err.message : "Error connecting to backend API")
        }
      } finally {
        if (isMounted) setLoading(false)
      }
    }

    loadDashboardData()

    return () => {
      isMounted = false
    }
  }, [role, facultyId])

  return (
    <div className="space-y-8 animate-in fade-in duration-300">
      {/* ── Dashboard Header ─────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
            {role && (
              <span className="inline-flex items-center rounded-md bg-secondary px-2.5 py-0.5 text-xs font-semibold text-secondary-foreground font-mono">
                {role.replace("_", " ")}
              </span>
            )}
          </div>
          <p className="text-muted-foreground mt-1.5 text-sm">
            {user?.email && <span className="text-foreground font-medium">{user.email} · </span>}
            {role === "EXAM_COORDINATOR" && "Institutional readiness, attendance thresholds, and examination duty management."}
            {role === "FACULTY" && "My assigned examination duties, teaching schedule, and roll-call roster."}
            {role === "SUPER_ADMIN" && "System administration, academic infrastructure metrics, and portal operations."}
            {role === "VIEWER" && "Read-only institutional summary of attendance and midterm examination readiness."}
            {!role && "Live overview of midterm operations, eligibility, and scheduling."}
          </p>
        </div>

        {role === "VIEWER" && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground bg-muted/60 border rounded-lg px-3 py-1.5 self-start sm:self-auto">
            <Eye className="h-4 w-4 text-muted-foreground shrink-0" />
            <span>Observational Read-Only Mode</span>
          </div>
        )}
      </div>

      {/* ── Error Notice ──────────────────────────────────────────────────── */}
      {errorMessage && (
        <Card className="border-destructive/30 bg-destructive/5">
          <CardContent className="flex items-start gap-4 py-6">
            <AlertCircle className="h-5 w-5 mt-0.5 shrink-0 text-destructive" />
            <div>
              <p className="font-medium text-destructive">Backend Communication Notice</p>
              <p className="text-sm text-muted-foreground mt-1">{errorMessage}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Loading Skeleton ──────────────────────────────────────────────── */}
      {loading && !errorMessage && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Card key={i} className="animate-pulse">
              <CardContent className="py-8">
                <div className="h-4 w-24 bg-muted rounded mb-3" />
                <div className="h-8 w-16 bg-muted rounded" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* ── Loaded Dashboard Content ───────────────────────────────────────── */}
      {!loading && stats && (
        <>
          {/* ══════════════════════════════════════════════════════════════════
              ROLE VIEW: FACULTY
             ══════════════════════════════════════════════════════════════════ */}
          {role === "FACULTY" && (
            <div className="space-y-6">
              {/* Faculty Action Bar */}
              <div className="grid gap-4 sm:grid-cols-3">
                <Card className="hover:border-primary/50 transition-colors">
                  <CardContent className="p-4 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                        <ClipboardCheck className="h-5 w-5" />
                      </div>
                      <div>
                        <p className="font-semibold text-sm">Exam Roll Call</p>
                        <p className="text-xs text-muted-foreground">Conduct room attendance</p>
                      </div>
                    </div>
                    <Link href="/mst-rollcall" className={buttonVariants({ variant: "ghost", size: "sm" })}>
                      <ArrowRight className="h-4 w-4" />
                    </Link>
                  </CardContent>
                </Card>

                <Card className="hover:border-primary/50 transition-colors">
                  <CardContent className="p-4 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                        <Armchair className="h-5 w-5" />
                      </div>
                      <div>
                        <p className="font-semibold text-sm">Room Seat Map</p>
                        <p className="text-xs text-muted-foreground">Inspect hall layout</p>
                      </div>
                    </div>
                    <Link href="/attendance/tracker" className={buttonVariants({ variant: "ghost", size: "sm" })}>
                      <ArrowRight className="h-4 w-4" />
                    </Link>
                  </CardContent>
                </Card>

                <Card className="hover:border-primary/50 transition-colors">
                  <CardContent className="p-4 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                        <Sparkles className="h-5 w-5" />
                      </div>
                      <div>
                        <p className="font-semibold text-sm">AI Teaching Assistant</p>
                        <p className="text-xs text-muted-foreground">Ask queries & lookups</p>
                      </div>
                    </div>
                    <Link href="/ai" className={buttonVariants({ variant: "ghost", size: "sm" })}>
                      <ArrowRight className="h-4 w-4" />
                    </Link>
                  </CardContent>
                </Card>
              </div>

              {/* Faculty Personal Duties & Timetable */}
              <div className="grid gap-6 md:grid-cols-2">
                {/* My Assigned Invigilation Duties */}
                <Card>
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-base flex items-center gap-2">
                        <Calendar className="h-4 w-4 text-primary" />
                        My Assigned Invigilation Duties
                      </CardTitle>
                      <span className="text-xs font-mono bg-muted px-2 py-0.5 rounded">
                        {myDuties.length} {myDuties.length === 1 ? "Duty" : "Duties"}
                      </span>
                    </div>
                    <CardDescription>
                      Upcoming duties scheduled for your faculty profile.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {myDuties.length === 0 ? (
                      <div className="text-center py-6 text-sm text-muted-foreground border border-dashed rounded-lg">
                        <CheckCircle2 className="h-6 w-6 mx-auto mb-2 text-muted-foreground/60" />
                        No invigilation duties currently assigned for upcoming exams.
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {myDuties.map((duty) => (
                          <div
                            key={duty.id}
                            className="flex items-center justify-between p-3 rounded-lg border bg-card hover:bg-muted/40 transition-colors"
                          >
                            <div className="space-y-1">
                              <p className="font-semibold text-sm">
                                {duty.exam_label || "MST Exam"} · Room {duty.room_number}
                              </p>
                              <p className="text-xs text-muted-foreground">
                                {duty.exam_date || "Scheduled Date"} {duty.time_slot ? `· ${duty.time_slot}` : ""}
                              </p>
                            </div>
                            <span className="inline-flex items-center rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 px-2.5 py-0.5 text-xs font-medium">
                              {duty.status}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* My Teaching Timetable */}
                <Card>
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-base flex items-center gap-2">
                        <BookOpen className="h-4 w-4 text-primary" />
                        My Teaching Commitments
                      </CardTitle>
                      <Link href="/timetable" className={cn(buttonVariants({ variant: "link", size: "sm" }), "h-auto p-0 text-xs")}>
                        Full Timetable
                      </Link>
                    </div>
                    <CardDescription>
                      Active teaching periods used for invigilation conflict detection.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {myTimetable.length === 0 ? (
                      <div className="text-center py-6 text-sm text-muted-foreground border border-dashed rounded-lg">
                        No individual teaching slots indexed for this semester version.
                      </div>
                    ) : (
                      <div className="space-y-2.5">
                        {myTimetable.slice(0, 4).map((slot) => (
                          <div
                            key={slot.id}
                            className="flex items-center justify-between p-2.5 rounded-lg border text-sm"
                          >
                            <div>
                              <p className="font-medium text-xs">
                                {slot.subject_code ? `${slot.subject_code} · ` : ""}
                                {slot.subject_name || "Lecture"}
                              </p>
                              <p className="text-[11px] text-muted-foreground">
                                {slot.day_of_week} {slot.period_start}–{slot.period_end}
                                {slot.room ? ` · Room ${slot.room}` : ""}
                              </p>
                            </div>
                            <span className="text-[11px] font-mono bg-muted px-2 py-0.5 rounded">
                              Teaching
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════════
              ROLE VIEW: SUPER ADMIN
             ══════════════════════════════════════════════════════════════════ */}
          {role === "SUPER_ADMIN" && (
            <div className="space-y-6">
              {/* Admin Infrastructure & Health Banner */}
              <div className="grid gap-4 sm:grid-cols-3">
                <Card className="border-l-4 border-l-primary">
                  <CardContent className="p-4 flex items-center gap-3">
                    <Server className="h-8 w-8 text-primary shrink-0" />
                    <div>
                      <p className="text-xs text-muted-foreground font-medium">AI & System Services</p>
                      <p className="font-bold text-sm">
                        {aiHealth?.status === "ok" ? "Operational" : "Active (Fallback Ready)"}
                      </p>
                      <p className="text-[11px] text-muted-foreground">
                        Provider: {aiHealth?.provider || "groq/gemini/local"}
                      </p>
                    </div>
                  </CardContent>
                </Card>

                <Card className="border-l-4 border-l-emerald-500">
                  <CardContent className="p-4 flex items-center gap-3">
                    <UserCheck className="h-8 w-8 text-emerald-500 shrink-0" />
                    <div>
                      <p className="text-xs text-muted-foreground font-medium">Security & RBAC</p>
                      <p className="font-bold text-sm">Strict Server-Enforced</p>
                      <p className="text-[11px] text-muted-foreground">6 roles mapped</p>
                    </div>
                  </CardContent>
                </Card>

                <Card className="border-l-4 border-l-blue-500">
                  <CardContent className="p-4 flex items-center gap-3">
                    <Shield className="h-8 w-8 text-blue-500 shrink-0" />
                    <div>
                      <p className="text-xs text-muted-foreground font-medium">Data Environment</p>
                      <p className="font-bold text-sm">Demo DB Connected</p>
                      <p className="text-[11px] text-muted-foreground">eduduty.db preserved</p>
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════════
              ROLE VIEW: EXAM COORDINATOR
             ══════════════════════════════════════════════════════════════════ */}
          {role === "EXAM_COORDINATOR" && followUpStats && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Card className="border-amber-500/30 bg-amber-500/5">
                <CardContent className="p-4 flex items-start gap-3">
                  <AlertTriangle className="h-5 w-5 text-amber-500 mt-0.5 shrink-0" />
                  <div className="space-y-1">
                    <p className="font-semibold text-sm text-foreground">Follow-Up & VT Action Required</p>
                    <p className="text-xs text-muted-foreground">
                      {followUpStats.by_final_status?.action_required || 0} student(s) missed both MST examinations and require institutional intervention.
                    </p>
                    <Link href="/follow-up" className={cn(buttonVariants({ variant: "outline", size: "sm" }), "h-7 text-xs mt-2 inline-flex items-center")}>
                      Manage Follow-Up List
                    </Link>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-primary/30 bg-primary/5">
                <CardContent className="p-4 flex items-start gap-3">
                  <Users className="h-5 w-5 text-primary mt-0.5 shrink-0" />
                  <div className="space-y-1">
                    <p className="font-semibold text-sm text-foreground">Invigilation Duty Readiness</p>
                    <p className="text-xs text-muted-foreground">
                      {exams.length} active exam(s) configured. Automatic conflict avoidance available against teaching timetable.
                    </p>
                    <Link href="/duties" className={cn(buttonVariants({ variant: "outline", size: "sm" }), "h-7 text-xs mt-2 inline-flex items-center")}>
                      Open Duty Scheduler
                    </Link>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════════
              INSTITUTIONAL METRIC CARDS (All Roles)
             ══════════════════════════════════════════════════════════════════ */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              title="Total Students"
              icon={<Users className="h-4 w-4 text-foreground" />}
              value={stats.total_students.toLocaleString("en-IN")}
              desc={
                stats.per_class.length > 0
                  ? `Across ${stats.per_class.length} classes: ${stats.per_class.map((c) => c.class).join(", ")}`
                  : "No students loaded."
              }
            />
            <StatCard
              title={`${stats.exam_label} Eligible`}
              icon={<CheckCircle className="h-4 w-4 text-foreground" />}
              value={stats.eligible.toLocaleString("en-IN")}
              desc={`${stats.eligible_pct}% eligibility rate · ${stats.overrides} HOD override(s)`}
              highlight
            />
            <StatCard
              title="Borderline Cases"
              icon={<Clock className="h-4 w-4 text-foreground" />}
              value={stats.borderline.toLocaleString("en-IN")}
              desc="45–50% attendance · Flagged for review"
            />
            <StatCard
              title="Timetable Coverage"
              icon={<CalendarDays className="h-4 w-4 text-foreground" />}
              value={
                stats.timetable.classes.length > 0
                  ? `${stats.timetable.classes.length} Classes`
                  : "—"
              }
              desc={
                stats.timetable.classes.length > 0
                  ? `${stats.timetable.periods} scheduled periods`
                  : "No timetable registered."
              }
            />
          </div>

          {/* ══════════════════════════════════════════════════════════════════
              CLASS BREAKDOWN & RECENT ACTIVITY
             ══════════════════════════════════════════════════════════════════ */}
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-7">
            {/* Class Breakdown Table */}
            <Card className="col-span-full lg:col-span-4">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>Class-wise Eligibility</CardTitle>
                    <CardDescription>
                      {stats.exam_label} attendance calculation breakdown.
                    </CardDescription>
                  </div>
                  {role !== "VIEWER" && (
                    <Link href="/eligibility" className={cn(buttonVariants({ variant: "outline", size: "sm" }), "text-xs h-8 inline-flex items-center")}>
                      View Roster
                    </Link>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                {stats.per_class.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4 text-center">
                    No class attendance records available.
                  </p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-left text-muted-foreground text-xs uppercase tracking-wider">
                          <th className="pb-2 pr-3 font-medium">Class</th>
                          <th className="pb-2 pr-3 font-medium text-right">Students</th>
                          <th className="pb-2 pr-3 font-medium text-right text-emerald-600 dark:text-emerald-400">Eligible</th>
                          <th className="pb-2 pr-3 font-medium text-right text-amber-600 dark:text-amber-400">Borderline</th>
                          <th className="pb-2 font-medium text-right text-rose-600 dark:text-rose-400">Ineligible</th>
                        </tr>
                      </thead>
                      <tbody className="font-mono tabular-nums text-xs sm:text-sm">
                        {stats.per_class.map((row) => (
                          <tr key={row.class} className="border-b last:border-0 hover:bg-muted/30">
                            <td className="py-2.5 pr-3 font-sans font-medium">{row.class}</td>
                            <td className="py-2.5 pr-3 text-right">{row.students}</td>
                            <td className="py-2.5 pr-3 text-right text-emerald-600 dark:text-emerald-400 font-semibold">{row.eligible}</td>
                            <td className="py-2.5 pr-3 text-right text-amber-600 dark:text-amber-400">{row.borderline}</td>
                            <td className="py-2.5 text-right text-rose-600 dark:text-rose-400">{row.ineligible}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Recent Activity / Audit Log Feed */}
            <Card className="col-span-full lg:col-span-3">
              <CardHeader>
                <CardTitle>Recent Activity</CardTitle>
                <CardDescription>
                  Audit log trail of imports and coordinator overrides.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {stats.recent_activity.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4 text-center">
                    No recorded actions yet.
                  </p>
                ) : (
                  <div className="space-y-5">
                    {stats.recent_activity.slice(0, 6).map((a, i) => (
                      <div key={i} className="flex items-start gap-3">
                        <div className="mt-0.5 shrink-0 p-1.5 rounded-full bg-muted">
                          {a.kind === "upload" ? (
                            <Upload className="h-3.5 w-3.5 text-foreground" />
                          ) : a.kind === "override" ? (
                            <PenLine className="h-3.5 w-3.5 text-foreground" />
                          ) : (
                            <Activity className="h-3.5 w-3.5 text-foreground" />
                          )}
                        </div>
                        <div className="space-y-0.5 min-w-0 flex-1">
                          <p className="text-xs font-semibold leading-tight">{a.title}</p>
                          <p className="text-xs text-muted-foreground truncate">{a.detail}</p>
                        </div>
                        <span className="shrink-0 text-[11px] text-muted-foreground font-mono">
                          {timeAgo(a.at)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
