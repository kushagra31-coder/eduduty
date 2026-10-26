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
      toast({ title: `Recalculated ${data.evaluated} students (${data.changed} changed)` })
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

      <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="relative overflow-hidden border shadow-sm">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between text-muted-foreground">
              <span className="text-xs font-semibold tracking-wide uppercase">Total Evaluated</span>
              <div className="p-2 rounded-lg bg-indigo-500/10 text-indigo-600 dark:text-indigo-400">
                <Users className="w-4 h-4" />
              </div>
            </div>
            <CardTitle className="text-3xl font-mono font-bold tabular-nums mt-1">
              {stats?.total_evaluated ?? 0}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0 text-xs text-muted-foreground">
            Out of <span className="font-semibold text-foreground">{stats?.total_students ?? 0}</span> enrolled students
          </CardContent>
        </Card>

        <Card className="relative overflow-hidden border border-rose-200 dark:border-rose-900/50 bg-rose-50/40 dark:bg-rose-950/20 shadow-sm">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between text-rose-700 dark:text-rose-300">
              <span className="text-xs font-semibold tracking-wide uppercase">Compulsory Follow-up</span>
              <div className="p-2 rounded-lg bg-rose-500/15 text-rose-600 dark:text-rose-400">
                <AlertTriangle className="w-4 h-4" />
              </div>
            </div>
            <CardTitle className="text-3xl font-mono font-bold text-rose-600 dark:text-rose-400 tabular-nums mt-1">
              {byFinal["compulsory"] ?? 0}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0 text-xs text-rose-700/80 dark:text-rose-300/80">
            Absent in both MST-1 & MST-2
          </CardContent>
        </Card>

        <Card className="relative overflow-hidden border border-amber-200 dark:border-amber-900/50 bg-amber-50/30 dark:bg-amber-950/20 shadow-sm">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between text-amber-700 dark:text-amber-300">
              <span className="text-xs font-semibold tracking-wide uppercase">Under Review & Excused</span>
              <div className="p-2 rounded-lg bg-amber-500/15 text-amber-600 dark:text-amber-400">
                <Clock className="w-4 h-4" />
              </div>
            </div>
            <CardTitle className="text-3xl font-mono font-bold text-amber-600 dark:text-amber-400 tabular-nums mt-1">
              {(byFinal["under_review"] ?? 0) + (byFinal["excused"] ?? 0)}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0 text-xs text-amber-700/80 dark:text-amber-300/80">
            {byFinal["under_review"] ?? 0} pending data · {byFinal["excused"] ?? 0} excused
          </CardContent>
        </Card>

        <Card className="relative overflow-hidden border border-emerald-200 dark:border-emerald-900/50 bg-emerald-50/30 dark:bg-emerald-950/20 shadow-sm">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between text-emerald-700 dark:text-emerald-300">
              <span className="text-xs font-semibold tracking-wide uppercase">Completed & Exempted</span>
              <div className="p-2 rounded-lg bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="w-4 h-4" />
              </div>
            </div>
            <CardTitle className="text-3xl font-mono font-bold text-emerald-600 dark:text-emerald-400 tabular-nums mt-1">
              {(byFinal["completed"] ?? 0) + (byFinal["not_required"] ?? 0)}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0 text-xs text-emerald-700/80 dark:text-emerald-300/80">
            {byFinal["completed"] ?? 0} completed · {byFinal["not_required"] ?? 0} exempted
          </CardContent>
        </Card>
      </div>

      {(stats?.missing_records ?? 0) > 0 && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-amber-300/60 bg-amber-500/10 p-3.5 text-xs text-amber-900 dark:text-amber-200">
          <div className="flex items-center gap-2.5">
            <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
            <span>
              <strong>{stats?.missing_records} students</strong> have missing or pending MST attendance data. Mark attendance in MST Roll Call or click Recalculate to evaluate.
            </span>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={recalculate}
            disabled={recalcBusy}
            className="h-7 text-xs border-amber-400/60 hover:bg-amber-500/20 text-amber-950 dark:text-amber-100 shrink-0"
          >
            {recalcBusy ? "Recalculating…" : "Recalculate Now"}
          </Button>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Follow-up Roster</CardTitle>
          <CardDescription>Calculated by the rule engine; final status needs an authorized override with a typed reason.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
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

          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Roll No.</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Class</TableHead>
                  <TableHead>MST-1</TableHead>
                  <TableHead>MST-2</TableHead>
                  <TableHead>Calculated</TableHead>
                  <TableHead>Final</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  <TableRow><TableCell colSpan={8} className="h-24 text-center">Loading…</TableCell></TableRow>
                ) : records.length === 0 ? (
                  <TableRow><TableCell colSpan={8} className="h-24 text-center">No records. Mark MST attendance or hit Recalculate.</TableCell></TableRow>
                ) : (
                  records.map((r) => (
                    <TableRow key={r.id} className={r.override ? "bg-muted/60" : ""}>
                      <TableCell className="font-medium font-mono">{r.roll_number}</TableCell>
                      <TableCell>{r.name}</TableCell>
                      <TableCell>{r.class_name}</TableCell>
                      <TableCell>{appearanceBadge(r.mst_1_appeared)}</TableCell>
                      <TableCell>{appearanceBadge(r.mst_2_appeared)}</TableCell>
                      <TableCell>{statusBadge(r.calculated_status, false)}</TableCell>
                      <TableCell>{statusBadge(r.final_status, r.override)}</TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="sm" onClick={() => openDialog(r)}>
                          {r.override ? "Review Override" : "Review"}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

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
