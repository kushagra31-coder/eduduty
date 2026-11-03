"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Users, CheckCircle2, Clock, CalendarDays, Upload, PenLine, Activity,
  ServerOff, Armchair, Bot, ArrowUpRight, Sparkles, AlertTriangle,
  ShieldCheck, ClipboardList, TrendingUp, UserCheck, BadgeAlert,
  Trash2, RefreshCw
} from "lucide-react"
import { useToast } from "@/components/ui/use-toast"

const API = "/api"

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
  active_duty: { total: number; assigned: number; unfilled: number }
  recent_activity: ActivityItem[]
}

function timeAgo(iso: string | null): string {
  if (!iso) return ""
  const secs = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000))
  if (secs < 60) return "just now"
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return days === 1 ? "yesterday" : `${days}d ago`
}

function StatCard({
  title, value, sub, icon: Icon, colorClass, iconBg
}: {
  title: string; value: string | number; sub?: string
  icon: React.ElementType; colorClass: string; iconBg: string
}) {
  return (
    <Card className={`border shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5 ${colorClass}`}>
      <CardContent className="p-5 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-bold uppercase tracking-widest text-current/70 truncate">{title}</div>
          <div className="text-3xl font-extrabold font-mono mt-1.5 tabular-nums">{value}</div>
          {sub && <div className="text-xs mt-1 text-current/60 truncate">{sub}</div>}
        </div>
        <div className={`h-12 w-12 rounded-2xl flex items-center justify-center shrink-0 ${iconBg}`}>
          <Icon className="h-5 w-5" />
        </div>
      </CardContent>
    </Card>
  )
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState(false)
  const [resetting, setResetting] = useState(false)
  const { toast } = useToast()

  const loadStats = () => {
    fetch(`${API}/dashboard/stats`)
      .then((r) => {
        if (!r.ok) throw new Error("bad status")
        return r.json()
      })
      .then((data) => {
        setStats(data)
        setError(false)
      })
      .catch(() => setError(true))
  }

  useEffect(() => {
    loadStats()
    // Periodic poll to auto-reconnect if backend starts up
    const interval = setInterval(() => {
      fetch(`${API}/dashboard/stats`)
        .then((r) => {
          if (!r.ok) throw new Error()
          return r.json()
        })
        .then((data) => {
          setStats(data)
          setError(false)
        })
        .catch(() => {})
    }, 4000)
    return () => clearInterval(interval)
  }, [])

  const handleResetData = async () => {
    if (!confirm("Reset database to clean fresh state? This will wipe legacy/dummy student data and keep clean CI-1, CI-2, CY (Cyber Security) classes ready for your upload.")) return
    setResetting(true)
    try {
      const res = await fetch(`${API}/data/reset`, { method: "POST" })
      const data = await res.json().catch(() => null)
      if (res.ok) {
        toast({
          title: "Clean Slate Initialized",
          description: "Classes CI-1, CI-2, CY (Cyber Security) are ready. Legacy demo cache cleared.",
        })
        loadStats()
      } else {
        toast({ title: "Reset Failed", description: data?.detail ?? "Could not reset.", variant: "destructive" })
      }
    } catch {
      toast({ title: "Reset Failed", description: "Network error", variant: "destructive" })
    } finally {
      setResetting(false)
    }
  }

  const dutyPct = stats?.active_duty?.total
    ? Math.round((stats.active_duty.assigned / stats.active_duty.total) * 100)
    : 0

  return (
    <div className="space-y-7 animate-in pb-8">

      {/* ── Hero Banner ─────────────────────────────────────────────────────── */}
      <div className="relative overflow-hidden rounded-2xl border border-primary/25 bg-gradient-to-br from-primary/10 via-card to-primary/5 p-6 sm:p-8 shadow-sm">
        {/* Decorative blobs */}
        <div className="absolute -top-12 -right-12 h-40 w-40 rounded-full bg-primary/15 blur-3xl pointer-events-none" />
        <div className="absolute -bottom-8 -left-8 h-28 w-28 rounded-full bg-primary/10 blur-2xl pointer-events-none" />

        <div className="relative flex flex-col lg:flex-row lg:items-center justify-between gap-6">
          <div className="space-y-2 max-w-xl">
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full border border-primary/30 bg-primary/15 text-primary text-xs font-bold tracking-wide">
              <Sparkles className="h-3.5 w-3.5" />
              <span>EduDuty · MST Operations Center</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-foreground leading-tight">
              Examination Command Center
            </h1>
            <p className="text-sm text-foreground/80 dark:text-zinc-300 leading-relaxed font-normal">
              Automate eligibility audits, B1/B2 seating, conflict-free duty scheduling, and VT follow-up — partitioned cleanly across CI-1, CI-2, CY (Cyber Security).
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 shrink-0">
            <Button size="sm" asChild className="font-semibold shadow-md hover:shadow-lg transition-all">
              <Link href="/attendance/tracker" className="inline-flex items-center gap-2">
                <Armchair className="h-4 w-4 shrink-0" />
                <span>Seating Plan</span>
              </Link>
            </Button>
            <Button size="sm" variant="outline" asChild className="shadow-sm font-medium">
              <Link href="/duties" className="inline-flex items-center gap-2">
                <Users className="h-4 w-4 shrink-0" />
                <span>Duty Scheduler</span>
              </Link>
            </Button>
            <Button size="sm" variant="outline" asChild className="shadow-sm font-medium">
              <Link href="/attendance/upload" className="inline-flex items-center gap-2">
                <Upload className="h-4 w-4 shrink-0" />
                <span>Upload Data</span>
              </Link>
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={handleResetData}
              disabled={resetting}
              className="gap-2 shadow-sm font-medium border-destructive/40 text-destructive hover:bg-destructive/15 hover:border-destructive"
              title="Reset all dummy data to clean CI-1, CI-2, CY state"
            >
              {resetting ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              <span>Clean Slate</span>
            </Button>
          </div>
        </div>
      </div>

      {/* ── Backend Error ─────────────────────────────────────────────────────── */}
      {error && !stats && (
        <Card className="border-destructive/40 bg-destructive/10 shadow-sm">
          <CardContent className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 py-5">
            <div className="flex items-start gap-3.5">
              <ServerOff className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold text-sm text-destructive">Backend Server Offline / Reconnecting</p>
                <p className="text-xs text-foreground/75 mt-0.5">
                  Make sure FastAPI backend is running on{" "}
                  <code className="font-mono text-xs bg-muted/80 text-foreground px-1.5 py-0.5 rounded font-bold">127.0.0.1:8000</code>.
                  (EduDuty will automatically reconnect when online).
                </p>
              </div>
            </div>
            <Button size="sm" variant="outline" onClick={loadStats} className="shrink-0 gap-1.5">
              <RefreshCw className="h-3.5 w-3.5" />
              Retry Connection
            </Button>
          </CardContent>
        </Card>
      )}

      {/* ── Skeleton ─────────────────────────────────────────────────────────── */}
      {!stats && !error && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Card key={i} className="animate-pulse bg-muted/20 border-border/50">
              <CardContent className="p-6">
                <div className="h-3 w-24 bg-muted rounded mb-4" />
                <div className="h-9 w-16 bg-muted rounded" />
                <div className="h-2.5 w-32 bg-muted/60 rounded mt-3" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* ── Live KPI Grid ─────────────────────────────────────────────────────── */}
      {stats && (
        <>
          {/* Exam label pill */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-primary/10 border border-primary/20 text-primary text-xs font-bold">
              <TrendingUp className="h-3 w-3" />
              Active Exam: {stats.exam_label}
            </div>
            <div className="text-xs text-muted-foreground">
              {stats.per_class.length} class{stats.per_class.length !== 1 ? "es" : ""} · {stats.total_students} students
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <StatCard
              title="Total Students"
              value={stats.total_students.toLocaleString("en-IN")}
              sub={`${stats.per_class.length} classes enrolled`}
              icon={Users}
              colorClass="bg-card/70 border-border/60 text-foreground"
              iconBg="bg-primary/10 text-primary"
            />
            <StatCard
              title={`${stats.exam_label} Eligible`}
              value={stats.eligible.toLocaleString("en-IN")}
              sub={`${stats.eligible_pct}% rate · ${stats.overrides} HOD override${stats.overrides !== 1 ? "s" : ""}`}
              icon={CheckCircle2}
              colorClass="bg-emerald-500/5 border-emerald-500/20 text-emerald-700 dark:text-emerald-300"
              iconBg="bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
            />
            <StatCard
              title="Borderline Cases"
              value={stats.borderline.toLocaleString("en-IN")}
              sub="45–49.9% attendance · Needs review"
              icon={Clock}
              colorClass="bg-amber-500/5 border-amber-500/20 text-amber-700 dark:text-amber-300"
              iconBg="bg-amber-500/15 text-amber-700 dark:text-amber-300"
            />
            <StatCard
              title="Not Eligible"
              value={stats.ineligible.toLocaleString("en-IN")}
              sub="Below 45% attendance threshold"
              icon={BadgeAlert}
              colorClass="bg-rose-500/5 border-rose-500/20 text-rose-700 dark:text-rose-300"
              iconBg="bg-rose-500/15 text-rose-700 dark:text-rose-300"
            />
          </div>

          {/* ── Second row: Duty + Timetable ─────────────────────────────────── */}
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {/* Active Duty Coverage */}
            <Card className="border-border/70 shadow-sm bg-card/70 hover:shadow-md transition-all duration-200">
              <CardHeader className="pb-2 pt-4 px-5">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    <UserCheck className="h-4 w-4 text-primary" />
                    Active Duty Coverage
                  </CardTitle>
                  <Button variant="ghost" size="sm" asChild className="text-xs gap-1 h-7 px-2">
                    <Link href="/duties">
                      Manage <ArrowUpRight className="h-3 w-3" />
                    </Link>
                  </Button>
                </div>
                <CardDescription className="text-xs">
                  {stats.exam_label} invigilation slots
                </CardDescription>
              </CardHeader>
              <CardContent className="px-5 pb-4">
                {stats.active_duty.total === 0 ? (
                  <p className="text-xs text-muted-foreground py-3">
                    No duty slots created yet. Generate duties in the Duty Scheduler.
                  </p>
                ) : (
                  <div className="space-y-3">
                    <div className="flex items-end justify-between">
                      <div>
                        <div className="text-3xl font-extrabold font-mono tabular-nums text-foreground">
                          {stats.active_duty.assigned}
                          <span className="text-lg font-medium text-muted-foreground">/{stats.active_duty.total}</span>
                        </div>
                        <div className="text-xs text-muted-foreground mt-0.5">slots assigned</div>
                      </div>
                      <div className="text-right">
                        <Badge
                          className={
                            stats.active_duty.unfilled === 0
                              ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/20 text-xs"
                              : "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/20 text-xs"
                          }
                          variant="outline"
                        >
                          {stats.active_duty.unfilled === 0
                            ? "Fully Covered"
                            : `${stats.active_duty.unfilled} Unfilled`}
                        </Badge>
                      </div>
                    </div>
                    {/* Progress bar */}
                    <div className="w-full h-2 rounded-full bg-muted overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-700 ${
                          dutyPct === 100
                            ? "bg-emerald-500"
                            : dutyPct > 50
                            ? "bg-primary"
                            : "bg-amber-500"
                        }`}
                        style={{ width: `${dutyPct}%` }}
                      />
                    </div>
                    <div className="text-xs text-muted-foreground">{dutyPct}% coverage</div>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Timetable Periods */}
            <Card className="border-border/70 shadow-sm bg-card/70 hover:shadow-md transition-all duration-200">
              <CardHeader className="pb-2 pt-4 px-5">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    <CalendarDays className="h-4 w-4 text-primary" />
                    Timetable Entries
                  </CardTitle>
                  <Button variant="ghost" size="sm" asChild className="text-xs gap-1 h-7 px-2">
                    <Link href="/timetable">
                      View <ArrowUpRight className="h-3 w-3" />
                    </Link>
                  </Button>
                </div>
                <CardDescription className="text-xs">Faculty schedule records loaded</CardDescription>
              </CardHeader>
              <CardContent className="px-5 pb-4">
                <div className="text-3xl font-extrabold font-mono tabular-nums text-foreground mt-1">
                  {stats.timetable.periods.toLocaleString("en-IN")}
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  {stats.timetable.classes.length > 0
                    ? `Classes: ${stats.timetable.classes.slice(0, 3).join(", ")}${stats.timetable.classes.length > 3 ? " +" + (stats.timetable.classes.length - 3) + " more" : ""}`
                    : "No timetable loaded yet"}
                </div>
              </CardContent>
            </Card>

            {/* VT Follow-up Quicklink */}
            <Card className="border-border/70 shadow-sm bg-card/70 hover:shadow-md transition-all duration-200">
              <CardHeader className="pb-2 pt-4 px-5">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    <ClipboardList className="h-4 w-4 text-primary" />
                    Quick Actions
                  </CardTitle>
                </div>
                <CardDescription className="text-xs">Frequently used operations</CardDescription>
              </CardHeader>
              <CardContent className="px-5 pb-4 space-y-2">
                {[
                  { href: "/eligibility", label: "Check Eligibility", icon: CheckCircle2 },
                  { href: "/follow-up", label: "VT Follow-up Status", icon: ClipboardList },
                  { href: "/mst-rollcall", label: "MST Roll Call", icon: ShieldCheck },
                  { href: "/settings", label: "Portal Settings", icon: AlertTriangle },
                ].map(({ href, label, icon: Icon }) => (
                  <Link
                    key={href}
                    href={href}
                    className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-xs font-medium hover:bg-accent hover:text-accent-foreground transition-colors border border-border/50"
                  >
                    <span className="flex items-center gap-2">
                      <Icon className="h-3.5 w-3.5 text-primary" />
                      {label}
                    </span>
                    <ArrowUpRight className="h-3 w-3 text-muted-foreground" />
                  </Link>
                ))}
              </CardContent>
            </Card>
          </div>

          {/* ── Class Breakdown + Activity ────────────────────────────────────── */}
          <div className="grid gap-6 lg:grid-cols-7">
            {/* Class Breakdown Table */}
            <Card className="lg:col-span-4 border-border/70 shadow-sm overflow-hidden hover:shadow-md transition-shadow">
              <CardHeader className="py-4 px-5 bg-muted/20 border-b border-border/50">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-sm font-semibold">Class Eligibility Breakdown</CardTitle>
                    <CardDescription className="text-xs mt-0.5">
                      Live attendance metrics for {stats.exam_label}
                    </CardDescription>
                  </div>
                  <Button variant="ghost" size="sm" asChild className="text-xs gap-1 h-8">
                    <Link href="/eligibility">
                      View All <ArrowUpRight className="h-3.5 w-3.5" />
                    </Link>
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                {stats.per_class.length === 0 ? (
                  <div className="py-12 text-center space-y-2">
                    <Upload className="h-8 w-8 text-muted-foreground/40 mx-auto" />
                    <p className="text-xs text-muted-foreground">
                      No class data. Upload attendance sheets to populate this table.
                    </p>
                    <Button size="sm" variant="outline" asChild className="text-xs mt-1">
                      <Link href="/attendance/upload">Upload Now</Link>
                    </Button>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="bg-muted/30 border-b">
                        <tr className="text-muted-foreground text-left">
                          <th className="py-2.5 px-4 font-semibold">Class</th>
                          <th className="py-2.5 px-4 font-semibold text-right">Students</th>
                          <th className="py-2.5 px-4 font-semibold text-right text-emerald-600 dark:text-emerald-400">Eligible</th>
                          <th className="py-2.5 px-4 font-semibold text-right text-amber-600 dark:text-amber-400">Borderline</th>
                          <th className="py-2.5 px-4 font-semibold text-right text-rose-600 dark:text-rose-400">Ineligible</th>
                          <th className="py-2.5 px-4 font-semibold text-right">Coverage</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border/40 font-mono tabular-nums">
                        {stats.per_class.map((row) => {
                          const pct = row.students > 0 ? Math.round((row.eligible / row.students) * 100) : 0
                          return (
                            <tr key={row.class} className="hover:bg-muted/10 transition-colors">
                              <td className="py-2.5 px-4 font-sans font-semibold text-foreground">{row.class}</td>
                              <td className="py-2.5 px-4 text-right">{row.students}</td>
                              <td className="py-2.5 px-4 text-right text-emerald-600 dark:text-emerald-400 font-bold">{row.eligible}</td>
                              <td className="py-2.5 px-4 text-right text-amber-600 dark:text-amber-400 font-semibold">{row.borderline}</td>
                              <td className="py-2.5 px-4 text-right text-rose-600 dark:text-rose-400">{row.ineligible}</td>
                              <td className="py-2.5 px-4 text-right">
                                <div className="flex items-center justify-end gap-1.5">
                                  <div className="w-16 h-1.5 rounded-full bg-muted overflow-hidden">
                                    <div
                                      className={`h-full rounded-full ${pct >= 75 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-500" : "bg-rose-500"}`}
                                      style={{ width: `${pct}%` }}
                                    />
                                  </div>
                                  <span className="text-[10px] text-muted-foreground w-7 text-right">{pct}%</span>
                                </div>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Recent Activity */}
            <Card className="lg:col-span-3 border-border/70 shadow-sm overflow-hidden hover:shadow-md transition-shadow">
              <CardHeader className="py-4 px-5 bg-muted/20 border-b border-border/50">
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <Activity className="h-4 w-4 text-primary" />
                  Operations Audit Log
                </CardTitle>
                <CardDescription className="text-xs">
                  Recent imports, overrides & schedule changes
                </CardDescription>
              </CardHeader>
              <CardContent className="p-4">
                {stats.recent_activity.length === 0 ? (
                  <div className="py-10 text-center space-y-1">
                    <Activity className="h-8 w-8 text-muted-foreground/30 mx-auto" />
                    <p className="text-xs text-muted-foreground">No audit events recorded yet.</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {stats.recent_activity.map((a, i) => (
                      <div
                        key={i}
                        className="flex items-start gap-3 p-2.5 rounded-lg border border-border/40 bg-background/50 hover:bg-background transition-colors text-xs"
                      >
                        <div className={`h-7 w-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5 ${
                          a.kind === "upload" ? "bg-primary/10" : a.kind === "override" ? "bg-amber-500/10" : "bg-muted"
                        }`}>
                          {a.kind === "upload" ? (
                            <Upload className="h-3.5 w-3.5 text-primary" />
                          ) : a.kind === "override" ? (
                            <PenLine className="h-3.5 w-3.5 text-amber-600" />
                          ) : (
                            <ShieldCheck className="h-3.5 w-3.5 text-muted-foreground" />
                          )}
                        </div>
                        <div className="min-w-0 flex-1 space-y-0.5">
                          <p className="font-semibold text-foreground truncate">{a.title}</p>
                          <p className="text-[11px] text-muted-foreground truncate">{a.detail}</p>
                        </div>
                        <span className="text-[10px] text-muted-foreground shrink-0 font-mono pt-0.5">
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
