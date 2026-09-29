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
  if (v === true) return <Badge className="bg-foreground text-background hover:bg-foreground/85">Present</Badge>
  if (v === false) return <Badge className="border border-foreground/30 bg-foreground/10 text-foreground hover:bg-foreground/15">Absent</Badge>
  return <Badge variant="secondary">Missing</Badge>
}

function statusBadge(status: string, override: boolean) {
  if (override) return <Badge className="border-2 border-foreground bg-transparent text-foreground hover:bg-muted">Overridden</Badge>
  if (status === "compulsory") return <Badge className="bg-foreground text-background hover:bg-foreground/85">Compulsory</Badge>
  if (status === "under_review") return <Badge className="border border-dashed border-foreground/60 bg-transparent text-foreground hover:bg-muted">Under Review</Badge>
  if (status === "excused") return <Badge className="border border-foreground/30 bg-foreground/10 text-foreground hover:bg-foreground/15">Excused</Badge>
  if (status === "completed") return <Badge variant="secondary">Completed</Badge>
  return <Badge variant="outline">Not Required</Badge>
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
  const card = (label: string, value: number | undefined, hint?: string) => (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-3xl font-mono tabular-nums">{value ?? "—"}</CardTitle>
      </CardHeader>
      {hint && <CardContent className="pt-0 text-xs text-muted-foreground">{hint}</CardContent>}
    </Card>
  )

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex justify-between items-end flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">VT / Follow-up</h1>
          <p className="text-muted-foreground mt-2">
            Absent in both MST-1 and MST-2 → compulsory follow-up. Rule: absent-both-mst-v1.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button variant="outline" onClick={recalculate} disabled={recalcBusy}>
            {recalcBusy ? "Recalculating…" : "Recalculate"}
          </Button>
          <Button variant="outline" onClick={() => window.open(exportUrl(false), "_blank")}>Export Excel</Button>
          <Button variant="outline" onClick={() => window.open(exportUrl(true), "_blank")}>Export PDF</Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-7">
        {card("Evaluated", stats?.total_evaluated)}
        {card("Compulsory", byFinal["compulsory"], "absent in both MSTs")}
        {card("Not Required", byFinal["not_required"])}
        {card("Under Review", byFinal["under_review"], "missing appearance data")}
        {card("Excused", byFinal["excused"])}
        {card("Completed", byFinal["completed"])}
        {card("Missing Records", stats?.missing_records, "students not yet evaluated")}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Follow-up Roster</CardTitle>
          <CardDescription>Calculated by the rule engine; final status needs an authorized override with a typed reason.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-3 flex-wrap">
            <Select value={classFilter} onValueChange={(v: string | null) => { if (v) setClassFilter(v) }}>
              <SelectTrigger className="w-44"><SelectValue placeholder="Class" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All classes</SelectItem>
                {classes.map((c) => <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={finalFilter} onValueChange={(v: string | null) => { if (v) setFinalFilter(v) }}>
              <SelectTrigger className="w-44"><SelectValue placeholder="Final status" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectItem value="compulsory">Compulsory</SelectItem>
                <SelectItem value="not_required">Not required</SelectItem>
                <SelectItem value="under_review">Under review</SelectItem>
                <SelectItem value="excused">Excused</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
              </SelectContent>
            </Select>
            <Input
              className="w-64"
              placeholder="Search roll no. or name…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
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
