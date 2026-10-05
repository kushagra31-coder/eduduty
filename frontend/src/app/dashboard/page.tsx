"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Users, CheckCircle, Clock, CalendarDays, Upload, PenLine, Activity, ServerOff } from "lucide-react"

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
  recent_activity: ActivityItem[]
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

function StatCard({ title, icon, value, desc }: { title: string; icon: React.ReactNode; value: string; desc: string }) {
  return (
    <Card className="hover:shadow-lg transition-shadow border-t-4 border-t-foreground">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        {icon}
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold font-mono tabular-nums">{value}</div>
        <p className="text-xs text-muted-foreground mt-1">{desc}</p>
      </CardContent>
    </Card>
  )
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    fetch(`${API}/dashboard/stats`)
      .then((r) => {
        if (!r.ok) throw new Error("bad status")
        return r.json()
      })
      .then(setStats)
      .catch(() => setError(true))
  }, [])

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground mt-2">
          Live overview of MST eligibility, attendance imports, and timetabling.
        </p>
      </div>

      {error && (
        <Card className="border-dashed">
          <CardContent className="flex items-start gap-4 py-6">
            <ServerOff className="h-5 w-5 mt-0.5 shrink-0" />
            <div>
              <p className="font-medium">Couldn&apos;t reach the backend</p>
              <p className="text-sm text-muted-foreground mt-1">
                Start the API so the dashboard can load real data — in a terminal, run{" "}
                <code className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded">uvicorn main:app --reload --port 8000</code>{" "}
                inside the <code className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded">backend/</code> folder,
                then refresh this page.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {!stats && !error && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
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

      {stats && (
        <>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <StatCard
              title="Total Students"
              icon={<Users className="h-4 w-4 text-foreground" />}
              value={stats.total_students.toLocaleString("en-IN")}
              desc={
                stats.per_class.length > 0
                  ? `Across ${stats.per_class.length} ${stats.per_class.length === 1 ? "class" : "classes"}: ${stats.per_class.map((c) => c.class).join(", ")}`
                  : "No students imported yet — upload an attendance sheet to begin."
              }
            />
            <StatCard
              title={`${stats.exam_label} Eligible`}
              icon={<CheckCircle className="h-4 w-4 text-foreground" />}
              value={stats.eligible.toLocaleString("en-IN")}
              desc={`${stats.eligible_pct}% eligibility rate · ${stats.overrides} HOD ${stats.overrides === 1 ? "override" : "overrides"} applied`}
            />
            <StatCard
              title="Borderline Cases"
              icon={<Clock className="h-4 w-4 text-foreground" />}
              value={stats.borderline.toLocaleString("en-IN")}
              desc="Attendance between 45–50% — needs HOD review before the exam"
            />
            <StatCard
              title="Timetable Coverage"
              icon={<CalendarDays className="h-4 w-4 text-foreground" />}
              value={
                stats.timetable.classes.length > 0
                  ? `${stats.timetable.classes.length} ${stats.timetable.classes.length === 1 ? "class" : "classes"}`
                  : "—"
              }
              desc={
                stats.timetable.classes.length > 0
                  ? `${stats.timetable.periods.toLocaleString("en-IN")} periods scheduled · ${stats.timetable.classes.join(", ")}`
                  : "No timetable saved yet — add one on the Timetable page."
              }
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-7">
            <Card className="col-span-4">
              <CardHeader>
                <CardTitle>Class-wise Eligibility</CardTitle>
                <CardDescription>
                  {stats.exam_label} status computed from the latest uploaded attendance sheets.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {stats.per_class.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4 text-center">
                    No class data yet. Upload an attendance sheet to see the breakdown here.
                  </p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-left text-muted-foreground">
                          <th className="pb-2 pr-3 font-medium whitespace-nowrap">Class</th>
                          <th className="pb-2 pr-3 font-medium text-right whitespace-nowrap">Students</th>
                          <th className="pb-2 pr-3 font-medium text-right whitespace-nowrap">Eligible</th>
                          <th className="pb-2 pr-3 font-medium text-right whitespace-nowrap">Borderline</th>
                          <th className="pb-2 font-medium text-right whitespace-nowrap">Ineligible</th>
                        </tr>
                      </thead>
                      <tbody className="font-mono tabular-nums">
                        {stats.per_class.map((row) => (
                          <tr key={row.class} className="border-b last:border-0">
                            <td className="py-2 pr-3 font-sans font-medium">{row.class}</td>
                            <td className="py-2 pr-3 text-right">{row.students}</td>
                            <td className="py-2 pr-3 text-right">{row.eligible}</td>
                            <td className="py-2 pr-3 text-right">{row.borderline}</td>
                            <td className="py-2 text-right">{row.ineligible}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="col-span-3">
              <CardHeader>
                <CardTitle>Recent Activity</CardTitle>
                <CardDescription>
                  Attendance imports and HOD override actions, newest first.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {stats.recent_activity.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4 text-center">
                    Nothing yet — uploads and overrides will appear here.
                  </p>
                ) : (
                  <div className="space-y-6">
                    {stats.recent_activity.map((a, i) => (
                      <div key={i} className="flex items-start gap-3">
                        <div className="mt-0.5 shrink-0">
                          {a.kind === "upload" ? (
                            <Upload className="h-4 w-4" />
                          ) : a.kind === "override" ? (
                            <PenLine className="h-4 w-4" />
                          ) : (
                            <Activity className="h-4 w-4" />
                          )}
                        </div>
                        <div className="space-y-1 min-w-0">
                          <p className="text-sm font-medium leading-none">{a.title}</p>
                          <p className="text-sm text-muted-foreground truncate">{a.detail}</p>
                        </div>
                        <div className="ml-auto shrink-0 text-sm text-muted-foreground">
                          {timeAgo(a.at)}
                        </div>
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
