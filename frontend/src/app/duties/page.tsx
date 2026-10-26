'use client'

import { useState, useEffect, useMemo, useCallback } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useToast } from "@/components/ui/use-toast"
import {
  Users, Calendar, Clock, Sparkles, CheckCircle2, AlertCircle,
  RefreshCw, UserCheck, ShieldCheck, Printer, UserPlus,
  ChevronRight, Edit3, Trash2
} from 'lucide-react'

type Exam = { id: number; label: string; exam_date: string | null; time_slot: string | null; class_id: number | null }

type Faculty = {
  id: number
  name: string
  abbreviation: string | null
  department: string | null
  exempt_from_duty: boolean
  exempt_reason: string | null
  max_duties_per_day: number | null
}

type Room = { id: number; room_number: string; capacity: number | null }

type ProposalRow = {
  mst_exam_id: number
  exam_label: string
  exam_date: string
  time_slot: string
  room_id: number
  room_number: string
  faculty_id: number
  faculty_name: string
  reason: string
}

type UnfilledRow = {
  mst_exam_id: number
  exam_label: string
  exam_date: string
  time_slot: string
  room_id: number
  room_number: string
  reason: string
  blockers: string[]
  assigned_faculty_id?: number | null
}

type Proposal = {
  proposal: ProposalRow[]
  unfilled: UnfilledRow[]
  skipped_exams: { mst_exam_id: number; label: string; reason: string }[]
  stats: { exams: number; rooms_filled: number; rooms_unfilled: number }
}

type ActiveDuty = {
  id: number
  room_id: number
  room_number: string
  faculty_id: number | null
  faculty_name: string | null
  status: string
}

export default function DutiesPage() {
  const [activeTab, setActiveTab] = useState<"proposal" | "active">("proposal")
  const [exams, setExams] = useState<Exam[]>([])
  const [facultyList, setFacultyList] = useState<Faculty[]>([])
  const [rooms, setRooms] = useState<Room[]>([])
  const [selectedExams, setSelectedExams] = useState<number[]>([])

  // Auto-schedule proposal state
  const [proposalResult, setProposalResult] = useState<Proposal | null>(null)
  const [editableProposal, setEditableProposal] = useState<ProposalRow[]>([])
  const [editableUnfilled, setEditableUnfilled] = useState<UnfilledRow[]>([])
  const [busy, setBusy] = useState(false)
  const [applying, setApplying] = useState(false)

  // Active roster state
  const [activeExamId, setActiveExamId] = useState<number | null>(null)
  const [activeDuties, setActiveDuties] = useState<ActiveDuty[]>([])
  const [loadingActive, setLoadingActive] = useState(false)

  // Manual assign modal state
  const [showManualModal, setShowManualModal] = useState(false)
  const [manualRoomId, setManualRoomId] = useState<string>("")
  const [manualFacultyId, setManualFacultyId] = useState<string>("")

  const { toast } = useToast()

  // Load initial exams, faculty, rooms
  useEffect(() => {
    Promise.all([
      fetch("/api/mst/exams").then((r) => (r.ok ? r.json() : [])),
      fetch("/api/faculty").then((r) => (r.ok ? r.json() : [])),
      fetch("/api/rooms").then((r) => (r.ok ? r.json() : [])),
    ])
      .then(([e, f, r]) => {
        setExams(e)
        setFacultyList(f)
        setRooms(r)
        if (e.length > 0) {
          setSelectedExams(e.map((x: Exam) => x.id))
          setActiveExamId(e[0].id)
        }
      })
      .catch(() => {})
  }, [])

  // Load active duties for the selected exam
  const loadActiveDuties = useCallback(async (id: number) => {
    setLoadingActive(true)
    try {
      const res = await fetch(`/api/mst/duties/${id}`)
      if (res.ok) {
        const data = await res.json()
        setActiveDuties(Array.isArray(data) ? data : (data ? [data] : []))
      } else {
        setActiveDuties([])
      }
    } catch {
      setActiveDuties([])
      toast({ title: "Failed to load active duties", variant: "destructive" })
    } finally {
      setLoadingActive(false)
    }
  }, [])

  useEffect(() => {
    if (activeExamId != null) {
      loadActiveDuties(activeExamId)
    }
  }, [activeExamId, loadActiveDuties])

  // Faculty workload map (counts duties assigned across current active list)
  const facultyWorkload = useMemo(() => {
    const counts: Record<number, number> = {}
    for (const d of activeDuties) {
      if (d.faculty_id) {
        counts[d.faculty_id] = (counts[d.faculty_id] || 0) + 1
      }
    }
    return counts
  }, [activeDuties])

  const toggleExam = (id: number) => {
    setSelectedExams((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  // Generate automated proposal
  const generateProposal = async () => {
    if (selectedExams.length === 0) {
      toast({ title: "Pick at least one exam", variant: "destructive" })
      return
    }
    setBusy(true)
    setProposalResult(null)
    try {
      const res = await fetch("/api/mst/duties/auto-schedule", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mst_exam_ids: selectedExams }),
      })
      if (!res.ok) throw new Error("Scheduler calculation failed")
      const data: Proposal = await res.json()
      setProposalResult(data)
      setEditableProposal(data.proposal)
      setEditableUnfilled(data.unfilled)
      toast({
        title: "Duty Proposal Generated",
        description: `Proposed ${data.proposal.length} invigilation assignments. You can edit any faculty assignment before applying.`,
      })
    } catch (e) {
      toast({ title: "Could not generate proposal", description: (e as Error).message, variant: "destructive" })
    } finally {
      setBusy(false)
    }
  }

  // Edit proposed faculty for a specific room
  const handleEditProposedFaculty = (index: number, newFacultyId: number) => {
    const faculty = facultyList.find((f) => f.id === newFacultyId)
    if (!faculty) return

    setEditableProposal((prev) => {
      const updated = [...prev]
      updated[index] = {
        ...updated[index],
        faculty_id: faculty.id,
        faculty_name: faculty.name,
        reason: "Manually customized by examination coordinator",
      }
      return updated
    })

    toast({
      title: "Assignment Updated",
      description: `Assigned ${faculty.name} to Room ${editableProposal[index]?.room_number}`,
    })
  }

  // Fill an unfilled room manually in the proposal
  const handleAssignUnfilledRoom = (unfilledIdx: number, facultyId: number) => {
    const faculty = facultyList.find((f) => f.id === facultyId)
    const target = editableUnfilled[unfilledIdx]
    if (!faculty || !target) return

    // Add to editable proposal
    const newRow: ProposalRow = {
      mst_exam_id: target.mst_exam_id,
      exam_label: target.exam_label,
      exam_date: target.exam_date,
      time_slot: target.time_slot,
      room_id: target.room_id,
      room_number: target.room_number,
      faculty_id: faculty.id,
      faculty_name: faculty.name,
      reason: "Manual coordinator override for unfilled hall",
    }
    setEditableProposal((prev) => [...prev, newRow])

    // Remove from unfilled list
    setEditableUnfilled((prev) => prev.filter((_, idx) => idx !== unfilledIdx))

    toast({
      title: "Room Filled",
      description: `Assigned ${faculty.name} to Room ${target.room_number}`,
    })
  }

  // Apply all reviewed assignments
  const applyProposal = async () => {
    if (editableProposal.length === 0) return
    setApplying(true)
    try {
      const payload = {
        assignments: editableProposal.map((p) => ({
          mst_exam_id: p.mst_exam_id,
          room_id: p.room_id,
          faculty_id: p.faculty_id,
        })),
      }
      const res = await fetch("/api/mst/duties/auto-schedule/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error("Application failed")
      const data = await res.json()
      toast({
        title: `Applied ${data.applied} duties successfully`,
        description: "Scheduled roster is now live and active.",
      })
      setProposalResult(null)
      // Switch to active roster view to show results
      setActiveTab("active")
      if (editableProposal.length > 0) {
        setActiveExamId(editableProposal[0].mst_exam_id)
      }
    } catch (e) {
      toast({ title: "Could not apply proposal", description: (e as Error).message, variant: "destructive" })
    } finally {
      setApplying(false)
    }
  }

  // Reassign active duty directly
  const handleReassignActiveDuty = async (roomId: number, facultyId: number) => {
    if (activeExamId == null) return
    try {
      await fetch("/api/mst/duties/assign", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mst_exam_id: activeExamId, room_id: roomId, faculty_id: facultyId }),
      })
      toast({ title: "Duty Reassigned" })
      loadActiveDuties(activeExamId)
    } catch (e) {
      toast({ title: "Reassign failed", description: (e as Error).message, variant: "destructive" })
    }
  }

  // Unassign active duty
  const handleUnassignActiveDuty = async (dutyId: number) => {
    if (activeExamId == null) return
    try {
      await fetch(`/api/mst/duties/unassign/${dutyId}`, { method: "POST" })
      toast({ title: "Duty unassigned" })
      loadActiveDuties(activeExamId)
    } catch (e) {
      toast({ title: "Unassign failed", description: (e as Error).message, variant: "destructive" })
    }
  }

  // Manual assign in active tab
  const handleManualAssign = async () => {
    if (!activeExamId || !manualRoomId || !manualFacultyId) return
    try {
      await fetch("/api/mst/duties/assign", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mst_exam_id: activeExamId,
          room_id: Number(manualRoomId),
          faculty_id: Number(manualFacultyId),
        }),
      })
      toast({ title: "Invigilator assigned" })
      setShowManualModal(false)
      setManualRoomId("")
      setManualFacultyId("")
      loadActiveDuties(activeExamId)
    } catch (e) {
      toast({ title: "Assign failed", description: (e as Error).message, variant: "destructive" })
    }
  }

  // Group editable proposal by exam key
  const groupedProposal = useMemo(() => {
    return editableProposal.reduce<Record<string, { exam_label: string; exam_date: string; time_slot: string; rows: (ProposalRow & { index: number })[] }>>(
      (acc, p, idx) => {
        const k = `${p.exam_label} · ${p.exam_date} · ${p.time_slot}`
        if (!acc[k]) {
          acc[k] = { exam_label: p.exam_label, exam_date: p.exam_date, time_slot: p.time_slot, rows: [] }
        }
        acc[k].rows.push({ ...p, index: idx })
        return acc
      },
      {}
    )
  }, [editableProposal])

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-border/50">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-1 uppercase tracking-wider">
            <span>Faculty Operations</span>
            <ChevronRight className="h-3 w-3" />
            <span className="text-foreground font-semibold">Duty Scheduler</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight flex items-center gap-2.5">
            <Users className="h-7 w-7 text-primary" />
            Faculty Invigilation Scheduler
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Automated conflict-free duty assignment based on teaching timetables. Editable before applying.
          </p>
        </div>

        {/* Global Tab Switcher */}
        <div className="flex items-center gap-2">
          <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as "proposal" | "active")}>
            <TabsList className="h-9">
              <TabsTrigger value="proposal" className="text-xs gap-1.5">
                <Sparkles className="h-3.5 w-3.5" />
                Auto-Scheduler & Edit
              </TabsTrigger>
              <TabsTrigger value="active" className="text-xs gap-1.5">
                <ShieldCheck className="h-3.5 w-3.5" />
                Active Duty Roster
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      </div>

      {/* ── TAB 1: AUTO-SCHEDULER & EDITABLE PROPOSAL ────────────────────────── */}
      {activeTab === "proposal" && (
        <div className="space-y-6">
          {/* Exam Selection Card */}
          <Card className="border-border/70 shadow-sm bg-card/60 backdrop-blur-sm">
            <CardHeader className="py-4 px-5">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <CardTitle className="text-base font-semibold flex items-center gap-2">
                    <Calendar className="h-4 w-4 text-primary shrink-0" />
                    <span>1. Select Examinations to Schedule</span>
                  </CardTitle>
                  <CardDescription className="text-xs mt-1">
                    Exams with scheduled date and time slot will be checked against teaching timetables.
                  </CardDescription>
                </div>
                <div className="flex flex-wrap items-center gap-2 shrink-0">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-xs"
                    onClick={() => setSelectedExams(exams.map((e) => e.id))}
                  >
                    Select All
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 text-xs text-muted-foreground"
                    onClick={() => setSelectedExams([])}
                  >
                    Clear
                  </Button>
                  <Button
                    size="sm"
                    onClick={generateProposal}
                    disabled={busy || selectedExams.length === 0}
                    className="h-8 text-xs gap-1.5 bg-primary font-semibold shadow-sm"
                  >
                    {busy ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                    <span>{busy ? "Calculating..." : "Generate Proposal"}</span>
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="px-5 pb-5">
              {exams.length === 0 ? (
                <p className="text-sm text-muted-foreground py-2">No exams found. Register exams in the Seating tab.</p>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5 pt-1">
                  {exams.map((e) => {
                    const isSelected = selectedExams.includes(e.id)
                    const canSchedule = Boolean(e.exam_date && e.time_slot)
                    return (
                      <label
                        key={e.id}
                        className={`flex items-start gap-3 p-3 rounded-lg border text-left cursor-pointer transition-all ${
                          !canSchedule
                            ? "opacity-60 bg-muted/20 border-dashed cursor-not-allowed"
                            : isSelected
                            ? "border-primary bg-primary/10 ring-1 ring-primary/20 shadow-xs"
                            : "border-border hover:border-foreground/30 bg-card"
                        }`}
                      >
                        <Input
                          type="checkbox"
                          disabled={!canSchedule}
                          checked={isSelected}
                          onChange={() => toggleExam(e.id)}
                          className="h-4 w-4 mt-0.5 accent-primary"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="text-xs font-bold font-mono text-foreground flex items-center justify-between">
                            <span>{e.label}</span>
                            {!canSchedule && <Badge variant="secondary" className="text-[9px]">no slot</Badge>}
                          </div>
                          <div className="text-[11px] text-muted-foreground mt-0.5 flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            <span>{e.time_slot || "09:30-12:30"}</span>
                          </div>
                          <div className="text-[11px] text-muted-foreground font-mono mt-0.5">
                            {e.exam_date || "No date set"}
                          </div>
                        </div>
                      </label>
                    )
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Proposal Results View */}
          {proposalResult && (
            <div className="space-y-6">
              {/* Proposal KPI Stats */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <Card className="border-emerald-500/20 bg-emerald-500/5 shadow-sm">
                  <CardContent className="p-4 flex items-center justify-between">
                    <div>
                      <div className="text-xs font-semibold text-emerald-800 dark:text-emerald-300 uppercase tracking-wider">
                        Rooms Filled
                      </div>
                      <div className="text-3xl font-bold font-mono text-emerald-700 dark:text-emerald-300 tabular-nums mt-0.5">
                        {editableProposal.length}
                      </div>
                      <div className="text-[11px] text-emerald-600/80 mt-0.5">Assigned free faculty</div>
                    </div>
                    <div className="h-10 w-10 rounded-xl bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 flex items-center justify-center">
                      <UserCheck className="h-5 w-5" />
                    </div>
                  </CardContent>
                </Card>

                <Card className={`shadow-sm ${editableUnfilled.length > 0 ? "border-amber-500/20 bg-amber-500/5" : "border-border/70 bg-card/60"}`}>
                  <CardContent className="p-4 flex items-center justify-between">
                    <div>
                      <div className="text-xs font-semibold text-amber-800 dark:text-amber-300 uppercase tracking-wider">
                        Rooms Unfilled
                      </div>
                      <div className="text-3xl font-bold font-mono text-amber-700 dark:text-amber-300 tabular-nums mt-0.5">
                        {editableUnfilled.length}
                      </div>
                      <div className="text-[11px] text-muted-foreground mt-0.5">Need manual allocation</div>
                    </div>
                    <div className="h-10 w-10 rounded-xl bg-amber-500/20 text-amber-700 dark:text-amber-300 flex items-center justify-center">
                      <AlertCircle className="h-5 w-5" />
                    </div>
                  </CardContent>
                </Card>

                <Card className="border-border/70 bg-card/60 backdrop-blur-sm shadow-sm">
                  <CardContent className="p-4 flex items-center justify-between">
                    <div>
                      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                        Exams Covered
                      </div>
                      <div className="text-3xl font-bold font-mono text-foreground tabular-nums mt-0.5">
                        {proposalResult.stats.exams}
                      </div>
                      <div className="text-[11px] text-muted-foreground mt-0.5">Ready to review & apply</div>
                    </div>
                    <div className="h-10 w-10 rounded-xl bg-primary/10 text-primary flex items-center justify-center">
                      <Calendar className="h-5 w-5" />
                    </div>
                  </CardContent>
                </Card>
              </div>

              {/* Editable Duty Proposal Review */}
              <Card className="border-border/70 shadow-sm">
                <CardHeader className="py-4 px-5 border-b bg-muted/20">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div>
                      <CardTitle className="text-base font-semibold flex items-center gap-2">
                        <Edit3 className="h-4 w-4 text-primary" />
                        2. Review & Edit Proposed Faculty
                      </CardTitle>
                      <CardDescription className="text-xs">
                        You can change any assigned teacher using the dropdown. Changes are audit-logged once applied.
                      </CardDescription>
                    </div>
                    <Button
                      onClick={applyProposal}
                      disabled={applying || editableProposal.length === 0}
                      className="bg-primary font-semibold text-xs h-9 gap-1.5 shadow-md hover:shadow-lg"
                    >
                      {applying ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                      {applying ? "Applying to Live Database..." : `Apply ${editableProposal.length} Duty Assignments`}
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="p-5 space-y-6">
                  {Object.entries(groupedProposal).map(([examKey, group]) => (
                    <div key={examKey} className="space-y-3">
                      <div className="flex items-center gap-2 pb-1 border-b">
                        <span className="font-mono text-xs font-bold bg-primary/10 text-primary px-2 py-0.5 rounded">
                          {group.exam_label}
                        </span>
                        <span className="text-xs text-muted-foreground">{group.exam_date}</span>
                        <span className="text-xs text-muted-foreground font-mono">({group.time_slot})</span>
                      </div>

                      <div className="rounded-xl border overflow-hidden shadow-xs">
                        <Table>
                          <TableHeader className="bg-muted/30">
                            <TableRow>
                              <TableHead className="w-[120px] text-xs font-semibold">Room</TableHead>
                              <TableHead className="w-[280px] text-xs font-semibold">Assigned Teacher (Editable)</TableHead>
                              <TableHead className="text-xs font-semibold">Assignment Criteria / Reason</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {group.rows.map((row) => (
                              <TableRow key={`${row.mst_exam_id}-${row.room_id}`} className="hover:bg-muted/10">
                                <TableCell className="font-mono font-bold text-xs">
                                  Room {row.room_number}
                                </TableCell>
                                <TableCell>
                                  {/* Interactive Faculty Selector */}
                                  <Select
                                    value={String(row.faculty_id)}
                                    onValueChange={(val) => handleEditProposedFaculty(row.index, Number(val))}
                                  >
                                    <SelectTrigger className="h-8 text-xs font-medium w-full max-w-[260px] bg-background">
                                      <SelectValue>{row.faculty_name}</SelectValue>
                                    </SelectTrigger>
                                    <SelectContent>
                                      {facultyList.map((f) => (
                                        <SelectItem key={f.id} value={String(f.id)} className="text-xs">
                                          <div className="flex items-center justify-between gap-2 w-full">
                                            <span>{f.name}</span>
                                            {f.department && (
                                              <span className="text-[10px] text-muted-foreground">({f.department})</span>
                                            )}
                                          </div>
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                </TableCell>
                                <TableCell className="text-xs text-muted-foreground">
                                  <span className="bg-muted/50 px-2 py-0.5 rounded border border-border/50 text-[11px]">
                                    {row.reason}
                                  </span>
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </div>
                  ))}

                  {editableProposal.length === 0 && (
                    <div className="text-center py-8 text-xs text-muted-foreground">
                      No duty assignments proposed. Check unfilled rooms below.
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Unfilled Rooms Section with Manual Quick-Assign */}
              {editableUnfilled.length > 0 && (
                <Card className="border-amber-500/30 bg-amber-500/5 shadow-sm">
                  <CardHeader className="py-4 px-5">
                    <CardTitle className="text-sm font-semibold text-amber-900 dark:text-amber-200 flex items-center gap-2">
                      <AlertCircle className="h-4 w-4 text-amber-600" />
                      Unfilled Examination Halls ({editableUnfilled.length})
                    </CardTitle>
                    <CardDescription className="text-xs">
                      All eligible teachers were blocked (clashing lectures, daily limit reached, or exempt). You can assign a faculty manually:
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="px-5 pb-5 space-y-3">
                    <div className="grid gap-3 sm:grid-cols-2">
                      {editableUnfilled.map((u, uIdx) => (
                        <div
                          key={`${u.mst_exam_id}-${u.room_id}`}
                          className="rounded-xl border border-amber-500/20 bg-background/80 p-3.5 space-y-2 shadow-xs"
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-mono font-bold text-xs">Room {u.room_number}</span>
                            <Badge variant="outline" className="text-[10px] bg-amber-500/10 text-amber-800 dark:text-amber-300 border-amber-500/30">
                              {u.exam_label} · {u.time_slot}
                            </Badge>
                          </div>

                          <div className="text-[11px] text-muted-foreground">
                            <strong>Blockers:</strong>
                            <ul className="list-disc pl-4 mt-1 space-y-0.5 text-[10px]">
                              {u.blockers.slice(0, 2).map((b, bIdx) => (
                                <li key={bIdx} className="truncate">{b}</li>
                              ))}
                            </ul>
                          </div>

                          <div className="pt-2 border-t flex items-center gap-2">
                            <Select onValueChange={(val) => handleAssignUnfilledRoom(uIdx, Number(val))}>
                              <SelectTrigger className="h-8 text-xs flex-1">
                                <SelectValue placeholder="Override & Assign Teacher" />
                              </SelectTrigger>
                              <SelectContent>
                                {facultyList.map((f) => (
                                  <SelectItem key={f.id} value={String(f.id)} className="text-xs">
                                    {f.name} ({f.department || "Faculty"})
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── TAB 2: ACTIVE LIVE DUTY ROSTER ──────────────────────────────────── */}
      {activeTab === "active" && (
        <div className="space-y-6">
          {/* Active Roster Toolbar */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 rounded-xl border bg-card/80 backdrop-blur-sm shadow-sm">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Select Examination:
              </span>
              <Select
                value={activeExamId != null ? String(activeExamId) : ""}
                onValueChange={(v) => setActiveExamId(Number(v))}
              >
                <SelectTrigger className="w-[200px] h-9 text-xs font-medium">
                  <SelectValue placeholder="Pick Exam" />
                </SelectTrigger>
                <SelectContent>
                  {exams.map((e) => (
                    <SelectItem key={e.id} value={String(e.id)} className="text-xs">
                      <span className="font-semibold">{e.label}</span>
                      {e.exam_date && <span className="text-muted-foreground ml-1.5 font-mono">({e.exam_date})</span>}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                className="h-9 gap-1.5 text-xs shadow-sm"
                onClick={() => setShowManualModal(true)}
              >
                <UserPlus className="h-3.5 w-3.5" />
                Assign Duty
              </Button>
              {activeExamId != null && (
                <a
                  href={`/api/pdf/duties/${activeExamId}`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center justify-center rounded-md border border-input bg-background hover:bg-accent hover:text-accent-foreground h-9 px-3 text-xs gap-1.5 shadow-sm font-medium transition-colors"
                >
                  <Printer className="h-3.5 w-3.5" />
                  Print Roster
                </a>
              )}
            </div>
          </div>

          {/* Active Duties Table */}
          <Card className="border-border/70 shadow-sm overflow-hidden">
            <CardHeader className="py-4 px-5 bg-muted/20 border-b">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-base font-semibold flex items-center gap-2">
                    <ShieldCheck className="h-4 w-4 text-primary" />
                    Live Examination Duty Roster
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Current faculty allocated to halls. Coordinators can swap or unassign directly.
                  </CardDescription>
                </div>
                <Badge variant="secondary" className="font-mono text-xs">
                  {activeDuties.length} assignments
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {loadingActive ? (
                <div className="flex items-center justify-center py-12 text-xs text-muted-foreground gap-2">
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  Loading duty roster...
                </div>
              ) : activeDuties.length === 0 ? (
                <div className="text-center py-14 space-y-3">
                  <p className="text-sm font-semibold">No duties scheduled yet for this exam.</p>
                  <p className="text-xs text-muted-foreground max-w-sm mx-auto">
                    Generate an automated proposal in the Auto-Scheduler tab, or assign teachers manually.
                  </p>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setActiveTab("proposal")}
                    className="gap-1.5 text-xs mt-2"
                  >
                    <Sparkles className="h-3.5 w-3.5" />
                    Go to Auto-Scheduler
                  </Button>
                </div>
              ) : (
                <Table>
                  <TableHeader className="bg-muted/30">
                    <TableRow>
                      <TableHead className="w-[120px] text-xs font-semibold">Room</TableHead>
                      <TableHead className="w-[140px] text-xs font-semibold">Status</TableHead>
                      <TableHead className="text-xs font-semibold">Assigned Invigilator</TableHead>
                      <TableHead className="w-[240px] text-xs font-semibold">Reassign Faculty</TableHead>
                      <TableHead className="w-[100px] text-right text-xs font-semibold">Action</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {activeDuties.map((d) => (
                      <TableRow key={d.id} className="hover:bg-muted/10">
                        <TableCell className="font-mono font-bold text-xs">
                          Room {d.room_number}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={d.status === "Assigned" ? "default" : "secondary"}
                            className="text-[10px] font-medium"
                          >
                            {d.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold text-foreground">
                              {d.faculty_name || "Unassigned"}
                            </span>
                            {d.faculty_id && facultyWorkload[d.faculty_id] && (
                              <Badge variant="outline" className="text-[9px] font-mono px-1 py-0">
                                {facultyWorkload[d.faculty_id]} duty
                              </Badge>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          {/* Live Reassignment Dropdown */}
                          <Select
                            value={d.faculty_id ? String(d.faculty_id) : ""}
                            onValueChange={(val) => handleReassignActiveDuty(d.room_id, Number(val))}
                          >
                            <SelectTrigger className="h-8 text-xs font-medium w-full max-w-[200px]">
                              <SelectValue placeholder="Swap Teacher" />
                            </SelectTrigger>
                            <SelectContent>
                              {facultyList.map((f) => (
                                <SelectItem key={f.id} value={String(f.id)} className="text-xs">
                                  {f.name}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleUnassignActiveDuty(d.id)}
                            className="h-8 px-2 text-xs text-muted-foreground hover:text-destructive"
                            title="Unassign invigilator"
                          >
                            <Trash2 className="h-3.5 w-3.5 mr-1" />
                            Remove
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── MANUAL ASSIGN MODAL ──────────────────────────────────────────────── */}
      <Dialog open={showManualModal} onOpenChange={setShowManualModal}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-base flex items-center gap-2">
              <UserPlus className="h-4 w-4 text-primary" />
              Assign Invigilator
            </DialogTitle>
            <DialogDescription className="text-xs">
              Assign a faculty member to an exam hall for the active examination slot.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-2 text-xs">
            <div>
              <label className="text-muted-foreground font-medium block mb-1">Examination Hall</label>
              <Select value={manualRoomId} onValueChange={(v) => setManualRoomId(v ?? "")}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue placeholder="Select Room" />
                </SelectTrigger>
                <SelectContent>
                  {rooms.map((r) => (
                    <SelectItem key={r.id} value={String(r.id)} className="text-xs">
                      Room {r.room_number} (Capacity: {r.capacity || 60})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <label className="text-muted-foreground font-medium block mb-1">Faculty Member</label>
              <Select value={manualFacultyId} onValueChange={(v) => setManualFacultyId(v ?? "")}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue placeholder="Select Faculty" />
                </SelectTrigger>
                <SelectContent>
                  {facultyList.map((f) => (
                    <SelectItem key={f.id} value={String(f.id)} className="text-xs">
                      {f.name} ({f.department || "Faculty"})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setShowManualModal(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleManualAssign}
              disabled={!manualRoomId || !manualFacultyId}
              className="bg-primary text-xs"
            >
              Assign Duty
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
