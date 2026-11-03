'use client'

import { useState, useEffect, useCallback } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useToast } from "@/components/ui/use-toast"
import {
  Users, AlertTriangle, CheckCircle2, Clock, Sparkles,
  RefreshCw, FileSpreadsheet, FileText, ChevronRight,
  Filter, AlertCircle
} from "lucide-react"

type FollowUpRecord = {
  id: number
  student_id: number
  roll_number: string
  name: string
  class_id: number
  class_name: string
  mst_1_appeared: boolean | null
  mst_2_appeared: boolean | null
  calculated_status: string
  final_status: string
  override: boolean
  override_reason: string | null
  rule_version: string
}

type ClassRow = { id: number; name: string }

type Stats = {
  total_evaluated: number
  total_students: number
  missing_records: number
  by_final_status: Record<string, number>
  by_calculated_status: Record<string, number>
}

const FINAL_OPTIONS = ["under_review", "excused", "completed"]

function pretty(s: string) {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
}

function appearanceBadge(v: boolean | null) {
  if (v === true) return (
    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-700 dark:text-emerald-300 bg-emerald-500/15 border border-emerald-500/30 px-2 py-0.5 rounded-md">
      Present
    </span>
  )
  if (v === false) return (
    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-700 dark:text-rose-300 bg-rose-500/15 border border-rose-500/30 px-2 py-0.5 rounded-md">
      Absent
    </span>
  )
  return (
    <span className="inline-flex items-center text-[10px] font-medium text-muted-foreground bg-muted/60 border border-border/70 px-1.5 py-0.5 rounded-md">
      Missing
    </span>
  )
}

function statusBadge(status: string, override: boolean) {
  if (override) return (
    <Badge className="bg-purple-500/20 text-purple-700 dark:text-purple-300 border-purple-500/40 text-[10px] font-bold">
      Overridden
    </Badge>
  )
  if (status === "compulsory") return (
    <Badge className="bg-rose-500/20 text-rose-700 dark:text-rose-300 border-rose-500/40 text-[10px] font-bold">
      Compulsory
    </Badge>
  )
  if (status === "under_review") return (
    <Badge className="bg-amber-500/20 text-amber-700 dark:text-amber-300 border-amber-500/40 text-[10px] font-semibold">
      Under Review
    </Badge>
  )
  if (status === "excused") return (
    <Badge className="bg-indigo-500/20 text-indigo-700 dark:text-indigo-300 border-indigo-500/40 text-[10px] font-semibold">
      Excused
    </Badge>
  )
  if (status === "completed") return (
    <Badge className="bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 border-emerald-500/40 text-[10px] font-semibold">
      Completed
    </Badge>
  )
  return (
    <Badge variant="outline" className="text-muted-foreground text-[10px] font-medium">
      Not Required
    </Badge>
  )
}

export default function FollowUpPage() {
  const [records, setRecords] = useState<FollowUpRecord[]>([])
  const [classes, setClasses] = useState<ClassRow[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [recalcBusy, setRecalcBusy] = useState(false)
  const [classFilter, setClassFilter] = useState<string>("all")
  const [finalFilter, setFinalFilter] = useState<string>("all")
  const [search, setSearch] = useState("")
  const [dialogOpen, setDialogOpen] = useState(false)
  const [selected, setSelected] = useState<FollowUpRecord | null>(null)
  const [newStatus, setNewStatus] = useState("excused")
  const [reason, setReason] = useState("")
  const { toast } = useToast()

  const fetchData = useCallback(async () => {
    const p = new URLSearchParams()
    if (classFilter !== "all") p.set("class_id", classFilter)
    if (finalFilter !== "all") p.set("final_status", finalFilter)
    if (search.trim()) p.set("search", search.trim())
    const q = p.toString()
    setIsLoading(true)
    try {
      const [recRes, statRes] = await Promise.all([
        fetch(`/api/follow-up${q ? `?${q}` : ""}`),
        fetch(`/api/follow-up/stats${classFilter !== "all" ? `?class_id=${classFilter}` : ""}`),
      ])
      if (recRes.ok) setRecords(await recRes.json())
      if (statRes.ok) setStats(await statRes.json())
    } catch (err) {
      console.error("Failed to fetch follow-up data", err)
    } finally {
      setIsLoading(false)
    }
  }, [classFilter, finalFilter, search])

  useEffect(() => {
    fetch("/api/classes").then((r) => r.ok ? r.json() : []).then(setClasses).catch(() => {})
  }, [])

  useEffect(() => {
    const t = setTimeout(fetchData, search ? 400 : 0)
    return () => clearTimeout(t)
  }, [fetchData, search])

  const recalculate = async () => {
    setRecalcBusy(true)
    try {
      const res = await fetch("/api/follow-up/recalculate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ class_id: classFilter !== "all" ? Number(classFilter) : null }),
      })
      if (!res.ok) throw new Error("recalc failed")
      const data = await res.json()
      if (data.changed > 0) {
        toast({
          title: "Recalculation Complete",
          description: `Evaluated ${data.evaluated} students. Status updated for ${data.changed} students based on MST-1 and MST-2 roll call.`,
        })
      } else {
        toast({
          title: "Recalculation Complete",
          description: `Evaluated ${data.evaluated} students. All students remain 'Under Review' because MST roll-call attendance has not been marked yet. Once roll-call attendance is marked, students absent in both MSTs will move to Compulsory Follow-up.`,
        })
      }
      fetchData()
    } catch {
      toast({ title: "Recalculation failed", variant: "destructive" })
    } finally {
      setRecalcBusy(false)
    }
  }

  const openDialog = (rec: FollowUpRecord) => {
    setSelected(rec)
    setNewStatus(rec.override ? rec.final_status : "excused")
    setReason("")
    setDialogOpen(true)
  }

  const submitOverride = async () => {
    if (!selected || !reason.trim()) {
      toast({ title: "Reason required", description: "A typed reason is mandatory for every override.", variant: "destructive" })
      return
    }
    try {
      const res = await fetch(`/api/follow-up/${selected.id}/override`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ final_status: newStatus, reason: reason.trim() }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || "override failed")
      }
      toast({ title: "Override saved and audited" })
      setDialogOpen(false)
      fetchData()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Could not update the override status."
      toast({ title: "Error", description: msg, variant: "destructive" })
    }
  }

  const restoreCalculated = async () => {
    if (!selected || !reason.trim()) {
      toast({ title: "Reason required", description: "A typed reason is mandatory.", variant: "destructive" })
      return
    }
    try {
      const res = await fetch(`/api/follow-up/${selected.id}/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reason.trim() }),
      })
      if (!res.ok) throw new Error("restore failed")
      toast({ title: "Restored to calculated status" })
      setDialogOpen(false)
      fetchData()
    } catch {
      toast({ title: "Error restoring status", variant: "destructive" })
    }
  }

  const exportUrl = (pdf: boolean) => {
    const q = classFilter !== "all" ? `?class_id=${classFilter}` : ""
    return pdf ? `/api/follow-up/export-pdf${q}` : `/api/follow-up/export${q}`
  }

  const byFinal = stats?.by_final_status ?? {}

  const statusFilters = [
    { key: "all", label: "All Records", count: stats?.total_evaluated ?? 0 },
    { key: "compulsory", label: "Compulsory", count: byFinal["compulsory"] ?? 0 },
    { key: "under_review", label: "Under Review", count: byFinal["under_review"] ?? 0 },
    { key: "not_required", label: "Not Required", count: byFinal["not_required"] ?? 0 },
    { key: "excused", label: "Excused", count: byFinal["excused"] ?? 0 },
    { key: "completed", label: "Completed", count: byFinal["completed"] ?? 0 },
  ]

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex justify-between items-start md:items-end flex-wrap gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-3xl font-bold tracking-tight">VT / Follow-up</h1>
            <Badge variant="outline" className="font-mono text-[11px] font-semibold text-muted-foreground border-border/80">
              Rule: absent-both-mst-v1
            </Badge>
          </div>
          <p className="text-muted-foreground mt-1.5 text-sm">
            Automated compliance engine. Students absent in both MST-1 and MST-2 are flagged for compulsory remedial follow-up.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap items-center">
          <Button variant="outline" size="sm" onClick={recalculate} disabled={recalcBusy} className="gap-1.5">
            <RefreshCw className={`w-3.5 h-3.5 ${recalcBusy ? "animate-spin" : ""}`} />
            {recalcBusy ? "Recalculating…" : "Recalculate"}
          </Button>
          <Button variant="outline" size="sm" onClick={() => window.open(exportUrl(false), "_blank")} className="gap-1.5">
            <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
            Export Excel
          </Button>
          <Button variant="outline" size="sm" onClick={() => window.open(exportUrl(true), "_blank")} className="gap-1.5">
            <FileText className="w-3.5 h-3.5 text-rose-600 dark:text-rose-400" />
            Export PDF
          </Button>
        </div>
      </div>

      {/* Modern KPI Header Cards - Open & Responsive Layout */}
      <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
        {/* Total Evaluated */}
        <div className="rounded-2xl border border-border/80 bg-card/80 backdrop-blur-sm p-5 shadow-sm transition-all hover:shadow-md hover:border-border">
          <div className="flex items-center justify-between text-muted-foreground mb-2">
            <span className="text-[11px] font-bold tracking-wider uppercase">Total Evaluated</span>
            <div className="p-2 rounded-xl bg-indigo-500/10 text-indigo-600 dark:text-indigo-400">
              <Users className="w-4 h-4" />
            </div>
          </div>
          <div className="text-3xl font-mono font-bold tracking-tight text-foreground">
            {stats?.total_evaluated ?? 0}
          </div>
          <p className="text-xs text-muted-foreground mt-1.5">
            Out of <span className="font-semibold text-foreground">{stats?.total_students ?? 0}</span> enrolled students
          </p>
        </div>

        {/* Compulsory Follow-up */}
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 backdrop-blur-sm p-5 shadow-sm transition-all hover:shadow-md hover:border-rose-500/50">
          <div className="flex items-center justify-between text-rose-600 dark:text-rose-400 mb-2">
            <span className="text-[11px] font-bold tracking-wider uppercase">Compulsory Follow-up</span>
            <div className="p-2 rounded-xl bg-rose-500/20 text-rose-600 dark:text-rose-400">
              <AlertTriangle className="w-4 h-4" />
            </div>
          </div>
          <div className="text-3xl font-mono font-bold tracking-tight text-rose-600 dark:text-rose-400">
            {byFinal["compulsory"] ?? 0}
          </div>
          <p className="text-xs text-rose-700/80 dark:text-rose-300/80 mt-1.5">
            Absent in both MST-1 & MST-2
          </p>
        </div>

        {/* Under Review & Excused */}
        <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 backdrop-blur-sm p-5 shadow-sm transition-all hover:shadow-md hover:border-amber-500/50">
          <div className="flex items-center justify-between text-amber-600 dark:text-amber-400 mb-2">
            <span className="text-[11px] font-bold tracking-wider uppercase">Under Review & Excused</span>
            <div className="p-2 rounded-xl bg-amber-500/20 text-amber-600 dark:text-amber-400">
              <Clock className="w-4 h-4" />
            </div>
          </div>
          <div className="text-3xl font-mono font-bold tracking-tight text-amber-600 dark:text-amber-400">
            {(byFinal["under_review"] ?? 0) + (byFinal["excused"] ?? 0)}
          </div>
          <p className="text-xs text-amber-700/80 dark:text-amber-300/80 mt-1.5">
            {byFinal["under_review"] ?? 0} pending data · {byFinal["excused"] ?? 0} excused
          </p>
        </div>

        {/* Completed & Exempted */}
        <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 backdrop-blur-sm p-5 shadow-sm transition-all hover:shadow-md hover:border-emerald-500/50">
          <div className="flex items-center justify-between text-emerald-600 dark:text-emerald-400 mb-2">
            <span className="text-[11px] font-bold tracking-wider uppercase">Completed & Exempted</span>
            <div className="p-2 rounded-xl bg-emerald-500/20 text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="w-4 h-4" />
            </div>
          </div>
          <div className="text-3xl font-mono font-bold tracking-tight text-emerald-600 dark:text-emerald-400">
            {(byFinal["completed"] ?? 0) + (byFinal["not_required"] ?? 0)}
          </div>
          <p className="text-xs text-emerald-700/80 dark:text-emerald-300/80 mt-1.5">
            {byFinal["completed"] ?? 0} completed · {byFinal["not_required"] ?? 0} exempted
          </p>
        </div>
      </div>

      {/* Advisory Status Banner */}
      {(stats?.missing_records ?? 0) > 0 && (
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 text-xs text-amber-900 dark:text-amber-200">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-amber-600 dark:text-amber-400 shrink-0" />
            <span className="leading-relaxed">
              <strong>{stats?.missing_records} students</strong> have missing or pending MST attendance data. Rule <code>absent-both-mst-v1</code> keeps them <strong>Under Review</strong> until both MST roll calls are recorded. Mark attendance in <strong>MST Roll Call</strong> to automatically flag double-absentees for compulsory remedial follow-up.
            </span>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={recalculate}
            disabled={recalcBusy}
            className="h-8 text-xs font-semibold border-amber-400/60 hover:bg-amber-500/20 text-amber-950 dark:text-amber-100 shrink-0 self-end sm:self-auto"
          >
            {recalcBusy ? "Recalculating…" : "Recalculate Now"}
          </Button>
        </div>
      )}

      {/* Follow-up Roster Section */}
      <div className="rounded-2xl border border-border/80 bg-card/60 backdrop-blur-sm shadow-sm overflow-hidden p-5 space-y-4">
        <div className="space-y-1">
          <h2 className="text-xl font-bold tracking-tight">Follow-up Roster</h2>
          <p className="text-xs text-muted-foreground">
            Calculated by the automated compliance engine; final status changes require an authorized coordinator decision with a mandatory typed reason.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 pb-2 border-b border-border/40">
          <span className="text-xs font-semibold text-muted-foreground mr-1 flex items-center gap-1.5">
            <Filter className="w-3.5 h-3.5" /> Filter by:
          </span>
          {statusFilters.map((f) => {
            const active = finalFilter === f.key
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFinalFilter(f.key)}
                className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-all cursor-pointer ${
                  active
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "bg-muted/70 text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                <span>{f.label}</span>
                <span
                  className={`px-1.5 py-0.5 rounded-full text-[10px] font-mono font-bold ${
                    active ? "bg-primary-foreground/20 text-primary-foreground" : "bg-background/90 text-foreground"
                  }`}
                >
                  {f.count}
                </span>
              </button>
            )
          })}
        </div>

        <div className="flex gap-3 flex-wrap items-center">
          <Select value={classFilter} onValueChange={(v: string | null) => { if (v) setClassFilter(v) }}>
            <SelectTrigger className="w-44"><SelectValue placeholder="Class" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All classes</SelectItem>
              {classes.map((c) => <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Input
            className="w-72"
            placeholder="Search roll number or name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {(finalFilter !== "all" || classFilter !== "all" || search.trim() !== "") && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setFinalFilter("all")
                setClassFilter("all")
                setSearch("")
              }}
              className="text-xs text-muted-foreground hover:text-foreground h-9"
            >
              Reset filters
            </Button>
          )}
        </div>

        {/* Clean, Full-Width Table with horizontal scroll if needed to avoid column squishing */}
        <div className="rounded-xl border border-border/80 bg-background overflow-x-auto shadow-sm">
          <table className="w-full text-xs text-left border-collapse min-w-[880px]">
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground font-semibold">
                <th className="px-4 py-3 min-w-[130px]">Roll No.</th>
                <th className="px-4 py-3 min-w-[160px]">Student Name</th>
                <th className="px-3 py-3 w-24">Class</th>
                <th className="px-3 py-3 w-28 text-center">MST-1</th>
                <th className="px-3 py-3 w-28 text-center">MST-2</th>
                <th className="px-3 py-3 min-w-[125px] text-center">Calculated</th>
                <th className="px-3 py-3 min-w-[125px] text-center">Final</th>
                <th className="px-4 py-3 min-w-[100px] text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {isLoading ? (
                <tr><td colSpan={8} className="h-24 text-center text-muted-foreground">Loading roster records…</td></tr>
              ) : records.length === 0 ? (
                <tr><td colSpan={8} className="h-24 text-center text-muted-foreground">No records found. Mark MST attendance or hit Recalculate.</td></tr>
              ) : (
                records.map((r) => (
                  <tr key={r.id} className={`hover:bg-muted/30 transition-colors ${r.override ? "bg-muted/40" : ""}`}>
                    <td className="px-4 py-3 font-medium font-mono whitespace-nowrap">{r.roll_number}</td>
                    <td className="px-4 py-3 font-medium whitespace-nowrap">{r.name}</td>
                    <td className="px-3 py-3 whitespace-nowrap font-semibold text-muted-foreground">{r.class_name}</td>
                    <td className="px-3 py-3 text-center whitespace-nowrap">{appearanceBadge(r.mst_1_appeared)}</td>
                    <td className="px-3 py-3 text-center whitespace-nowrap">{appearanceBadge(r.mst_2_appeared)}</td>
                    <td className="px-3 py-3 text-center whitespace-nowrap">{statusBadge(r.calculated_status, false)}</td>
                    <td className="px-3 py-3 text-center whitespace-nowrap">{statusBadge(r.final_status, r.override)}</td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      <Button variant="ghost" size="sm" onClick={() => openDialog(r)} className="h-7 text-xs font-medium px-2.5">
                        {r.override ? "Review Override" : "Review"}
                      </Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Review follow-up status</DialogTitle>
            <DialogDescription>
              {selected?.name} ({selected?.roll_number}) — rule says: <strong>{selected && pretty(selected.calculated_status)}</strong>.
              The calculated recommendation is never overwritten.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Final status</Label>
              <Select value={newStatus} onValueChange={(v: string | null) => { if (v) setNewStatus(v) }}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {FINAL_OPTIONS.map((o) => (
                    <SelectItem key={o} value={o}>{pretty(o)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="reason">Reason (required)</Label>
              <Input
                id="reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. Medical case approved by HOD"
              />
              <p className="text-xs text-muted-foreground">Logged in the audit trail with your action.</p>
            </div>
            {selected?.override && (
              <div className="text-xs text-muted-foreground border rounded-md p-3">
                Current override: <strong>{selected && pretty(selected.final_status)}</strong>
                {selected.override_reason ? ` — ${selected.override_reason}` : ""}
              </div>
            )}
          </div>
          <DialogFooter className="flex gap-2">
            {selected?.override && (
              <Button variant="outline" onClick={restoreCalculated}>Restore calculated</Button>
            )}
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={submitOverride}>Save override</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
