"use client"

import { useEffect, useMemo, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import { useToast } from "@/components/ui/use-toast"
import {
  Armchair, Users, UserCheck, UserX, MinusCircle, RefreshCw,
  ServerOff, Plus, GraduationCap, Sparkles, Search, Printer,
  Building2, ChevronRight, Check
} from "lucide-react"

const API = "/api"

type Exam = { id: number; label: string; exam_date: string | null; time_slot: string | null; class_id: number | null }
type Room = { id: number; room_number: string; capacity: number | null }
type SeatStudent = { id: number; roll_number: string; name: string; batch_number: number | null; status?: string | null }
type Seat = {
  id: number
  seat_number: string | null
  room_id: number
  room_number: string
  left: SeatStudent | null
  right: SeatStudent | null
  left_status?: string | null
  right_status?: string | null
}
type RoomSeating = { room_id: number; room_number: string; capacity: number | null; seats: Seat[] }
type FacultyStatus = {
  faculty_id: number
  faculty_name: string
  abbreviation: string | null
  department: string | null
  status: "Available" | "Teaching" | "On duty" | "Exempt"
  reason: string
}
type Duty = { id: number; room_id: number; room_number: string; faculty_id: number | null; faculty_name: string | null; status: string }
type ClassInfo = { id: number; name: string; branch: string }

type Mark = "Present" | "Absent" | null

async function api(path: string, init?: RequestInit) {
  const res = await fetch(`${API}${path}`, init)
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error((detail as { detail?: string }).detail || `Request failed (${res.status})`)
  }
  return res.json()
}

function nextMark(m: Mark): Mark {
  return m === "Present" ? "Absent" : "Present"
}

function getRollRange(students: SeatStudent[]): string {
  if (students.length === 0) return "No students"
  if (students.length === 1) return students[0].roll_number
  return `${students[0].roll_number} → ${students[students.length - 1].roll_number}`
}

function StudentRow({
  student,
  index,
  mark,
  onToggle,
  isHighlighted = false,
}: {
  student: SeatStudent
  index: number
  mark: Mark
  onToggle: () => void
  isHighlighted?: boolean
}) {
  return (
    <div
      onClick={onToggle}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          onToggle()
        }
      }}
      title={`${student.name} (${student.roll_number}) — Click to toggle attendance`}
      className={`group flex items-center justify-between px-3 py-2 rounded-lg border transition-all cursor-pointer select-none outline-none focus-visible:ring-2 focus-visible:ring-primary ${
        mark === "Present"
          ? "bg-emerald-500/10 border-emerald-500/40 hover:border-emerald-500 text-emerald-950 dark:text-emerald-100 shadow-2xs"
          : mark === "Absent"
          ? "bg-rose-500/10 border-rose-500/40 hover:border-rose-500 text-rose-950 dark:text-rose-100 shadow-2xs"
          : "bg-background/90 hover:bg-muted/50 border-border/70 text-foreground shadow-2xs"
      } ${isHighlighted ? "ring-2 ring-primary ring-offset-1" : ""}`}
    >
      <div className="flex items-center gap-2.5 min-w-0">
        <span className="text-[11px] font-mono text-muted-foreground/60 w-5 text-right shrink-0">
          {index + 1}
        </span>
        <div className="min-w-0">
          <div className="font-mono text-xs font-bold tabular-nums tracking-tight text-foreground truncate">
            {student.roll_number}
          </div>
          <div
            className={`text-xs font-medium truncate ${
              mark === "Absent" ? "line-through opacity-70 text-muted-foreground" : "text-foreground/85"
            }`}
          >
            {student.name}
          </div>
        </div>
      </div>

      <div className="shrink-0 ml-2">
        {mark === "Present" && (
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-700 dark:text-emerald-300 bg-emerald-500/20 px-2 py-0.5 rounded-md border border-emerald-500/30">
            <UserCheck className="h-3 w-3" />
            <span>Present</span>
          </span>
        )}
        {mark === "Absent" && (
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-700 dark:text-rose-300 bg-rose-500/20 px-2 py-0.5 rounded-md border border-rose-500/30">
            <UserX className="h-3 w-3" />
            <span>Absent</span>
          </span>
        )}
        {mark === null && (
          <span className="inline-flex items-center text-[11px] font-medium text-muted-foreground bg-muted/60 px-2 py-0.5 rounded-md border border-border/70 group-hover:border-primary/40 group-hover:text-primary transition-colors">
            <MinusCircle className="h-3 w-3 mr-1 opacity-50" />
            <span>Mark</span>
          </span>
        )}
      </div>
    </div>
  )
}

export default function SeatingTrackerPage() {
  const { toast } = useToast()
  const [exams, setExams] = useState<Exam[]>([])
  const [examId, setExamId] = useState<number | null>(null)
  const [rooms, setRooms] = useState<Room[]>([])
  const [classes, setClasses] = useState<ClassInfo[]>([])
  const [seating, setSeating] = useState<RoomSeating[]>([])
  const [marks, setMarks] = useState<Record<number, Mark>>({})
  const [faculty, setFaculty] = useState<FacultyStatus[]>([])
  const [duties, setDuties] = useState<Duty[]>([])
  const [offline, setOffline] = useState(false)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)

  // Filtering & UI state
  const [activeRoomTab, setActiveRoomTab] = useState<string>("all")
  const [searchQuery, setSearchQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState<"all" | "present" | "absent" | "unmarked">("all")
  const [facultyFilter, setFacultyFilter] = useState("all")
  const [assignSel, setAssignSel] = useState<Record<number, string>>({})

  // Seating Generator Dialog state
  const [showGenerateModal, setShowGenerateModal] = useState(false)
  const [selectedRoomIds, setSelectedRoomIds] = useState<number[]>([])

  // Setup modal state
  const [showSetupModal, setShowSetupModal] = useState(false)
  const [newExam, setNewExam] = useState({ label: "MST-1", exam_date: "", time_slot: "09:30-12:30", class_id: "" })
  const [newRoom, setNewRoom] = useState({ room_number: "", capacity: "60" })

  const exam = exams.find((e) => e.id === examId) ?? null

  // Load all exam details
  async function loadAll(id: number) {
    setLoading(true)
    try {
      const [seatData, attData, facData, dutyData] = await Promise.all([
        api(`/mst/seating/${id}`),
        api(`/mst/attendance/${id}`),
        api(`/mst/faculty-status?mst_exam_id=${id}`).catch(() => []),
        api(`/mst/duties/${id}`).catch(() => []),
      ])
      setSeating(seatData)
      const m: Record<number, Mark> = {}
      for (const a of attData as { student_id: number; status: string }[]) {
        m[a.student_id] = a.status as Mark
      }
      setMarks(m)
      setFaculty(facData)
      setDuties(dutyData)
    } catch {
      setOffline(true)
    } finally {
      setLoading(false)
    }
  }

  // Initial load
  useEffect(() => {
    Promise.all([api("/mst/exams"), api("/rooms"), api("/classes")])
      .then(([e, r, c]) => {
        setExams(e)
        setRooms(r)
        setClasses(c)
        if (e.length > 0) {
          setExamId(e[0].id)
        }
        // Pre-select all rooms by default for generator
        setSelectedRoomIds(r.map((x: Room) => x.id))
      })
      .catch(() => setOffline(true))
  }, [])

  // Exam changed
  useEffect(() => {
    if (examId == null) return
    setOffline(false)
    loadAll(examId)
  }, [examId])

  // Flattened seated students
  const seatedStudents = useMemo(() => {
    const list: SeatStudent[] = []
    for (const room of seating) {
      for (const s of room.seats) {
        if (s.left) list.push(s.left)
        if (s.right) list.push(s.right)
      }
    }
    return list
  }, [seating])

  // Counts & stats
  const counts = useMemo(() => {
    let present = 0, absent = 0
    for (const s of seatedStudents) {
      if (marks[s.id] === "Present") present++
      else if (marks[s.id] === "Absent") absent++
    }
    const total = seatedStudents.length
    const unmarked = total - present - absent
    const pct = total > 0 ? Math.round((present / total) * 100) : 0
    return { present, absent, unmarked, total, pct }
  }, [seatedStudents, marks])

  // Total capacity of selected rooms in generator modal
  const selectedRoomsCapacity = useMemo(() => {
    return rooms
      .filter((r) => selectedRoomIds.includes(r.id))
      .reduce((acc, r) => acc + (r.capacity || 60), 0)
  }, [rooms, selectedRoomIds])

  // Toggle mark with instant optimistic update
  async function toggle(student: SeatStudent) {
    if (examId == null) return
    const current = marks[student.id] ?? null
    const next = nextMark(current)
    setMarks((prev) => ({ ...prev, [student.id]: next })) // instant 0ms feedback

    try {
      await api("/mst/attendance/mark", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mst_exam_id: examId, student_id: student.id, status: next }),
      })
    } catch (err) {
      // Revert on error
      setMarks((prev) => ({ ...prev, [student.id]: current }))
      toast({ title: "Couldn't save mark", description: (err as Error).message, variant: "destructive" })
    }
  }

  // Generate seating plan
  async function handleGenerateSeating() {
    if (examId == null) {
      toast({ title: "Select an exam first", variant: "destructive" })
      return
    }
    if (selectedRoomIds.length === 0) {
      toast({ title: "Select at least one room", description: "Pick which examination halls to allocate.", variant: "destructive" })
      return
    }

    setBusy(true)
    try {
      const res = await api("/mst/seating/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mst_exam_id: examId, room_ids: selectedRoomIds }),
      })

      toast({
        title: "Seating Plan Generated Successfully",
        description: `Allocated ${res.seats_created} desks (${res.students_seated} students seated with B1/B2 interleaving).`,
      })
      setShowGenerateModal(false)
      await loadAll(examId)
    } catch (err) {
      toast({
        title: "Seating Generation Failed",
        description: (err as Error).message,
        variant: "destructive",
      })
    } finally {
      setBusy(false)
    }
  }

  // Create new exam
  async function createExam() {
    if (!newExam.label.trim()) return
    setBusy(true)
    try {
      const created = await api("/mst/exams", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: newExam.label,
          exam_date: newExam.exam_date || null,
          time_slot: newExam.time_slot || null,
          class_id: newExam.class_id ? Number(newExam.class_id) : null,
        }),
      })
      const e = await api("/mst/exams")
      setExams(e)
      setExamId(created.id)
      toast({ title: "Exam Created", description: `${created.label} is ready for seating allocation.` })
      setShowSetupModal(false)
    } catch (err) {
      toast({ title: "Couldn't create exam", description: (err as Error).message, variant: "destructive" })
    } finally {
      setBusy(false)
    }
  }

  // Add room
  async function addRoom() {
    if (!newRoom.room_number.trim()) return
    try {
      await api("/rooms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ room_number: newRoom.room_number.trim(), capacity: Number(newRoom.capacity) || 60 }),
      })
      const updatedRooms = await api("/rooms")
      setRooms(updatedRooms)
      setSelectedRoomIds((prev) => [...prev, updatedRooms[updatedRooms.length - 1].id])
      setNewRoom({ room_number: "", capacity: "60" })
      toast({ title: "Room added" })
    } catch (err) {
      toast({ title: "Couldn't add room", description: (err as Error).message, variant: "destructive" })
    }
  }

  // Assign duty to room
  async function assignDuty(roomId: number) {
    const fid = assignSel[roomId]
    if (!fid || examId == null) return
    try {
      await api("/mst/duties/assign", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mst_exam_id: examId, room_id: roomId, faculty_id: Number(fid) }),
      })
      const [d, f] = await Promise.all([api(`/mst/duties/${examId}`), api(`/mst/faculty-status?mst_exam_id=${examId}`)])
      setDuties(d)
      setFaculty(f)
      toast({ title: "Invigilator assigned" })
    } catch (err) {
      toast({ title: "Assign failed", description: (err as Error).message, variant: "destructive" })
    }
  }

  // Remove duty
  async function unassignDuty(dutyId: number) {
    if (examId == null) return
    try {
      await api(`/mst/duties/unassign/${dutyId}`, { method: "POST" })
      const [d, f] = await Promise.all([api(`/mst/duties/${examId}`), api(`/mst/faculty-status?mst_exam_id=${examId}`)])
      setDuties(d)
      setFaculty(f)
      toast({ title: "Duty unassigned" })
    } catch (err) {
      toast({ title: "Couldn't unassign", description: (err as Error).message, variant: "destructive" })
    }
  }

  // Duty lookup by room
  const dutyByRoom = useMemo(() => {
    const m: Record<number, Duty> = {}
    for (const d of duties) m[d.room_id] = d
    return m
  }, [duties])

  // Rooms sorted strictly in ascending natural order (Room 101, 102, 201...)
  const sortedRooms = useMemo(() => {
    return [...seating].sort((a, b) =>
      a.room_number.localeCompare(b.room_number, undefined, { numeric: true })
    )
  }, [seating])

  // Filtered rooms to display based on active room tab
  const displayedRooms = useMemo(() => {
    if (activeRoomTab === "all") return sortedRooms
    return sortedRooms.filter((r) => String(r.room_id) === activeRoomTab)
  }, [sortedRooms, activeRoomTab])

  // Filter faculty by availability
  const filteredFaculty = faculty.filter((f) =>
    facultyFilter === "all"
      ? true
      : facultyFilter === "free"
      ? f.status === "Available"
      : f.status === (facultyFilter === "onduty" ? "On duty" : facultyFilter === "teaching" ? "Teaching" : "Exempt")
  )

  const facultyStatusStyle = (s: FacultyStatus["status"]) => {
    if (s === "Available") return "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30"
    if (s === "On duty") return "bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30"
    if (s === "Teaching") return "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30"
    return "bg-muted text-muted-foreground line-through"
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* Top Header Bar */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 pb-2 border-b border-border/50">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-1 uppercase tracking-wider">
            <span>Examination Operations</span>
            <ChevronRight className="h-3 w-3" />
            <span className="text-foreground font-semibold">Seating Arrangement</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight flex items-center gap-2.5">
            <Armchair className="h-7 w-7 text-primary" />
            Seating Plan & Attendance Tracker
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Automated B1/B2 interleaving by roll number. Click any student desk slot to mark attendance in real-time.
          </p>
        </div>

        {/* Global Toolbar */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Exam Selector */}
          <Select value={examId != null ? String(examId) : ""} onValueChange={(v) => { if (v) setExamId(Number(v)) }}>
            <SelectTrigger className="min-w-[230px] sm:w-[280px] h-9 text-xs font-medium shadow-sm">
              <SelectValue placeholder="Select Exam">
                {exam ? `${exam.label} ${exam.exam_date ? `(${exam.exam_date})` : ""}` : "Select Exam"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent className="z-50 min-w-[280px] bg-popover/95 backdrop-blur-md shadow-xl border border-border">
              {exams.map((e) => (
                <SelectItem key={e.id} value={String(e.id)} className="text-xs py-1.5 cursor-pointer">
                  <span className="font-semibold">{e.label}</span>
                  {e.exam_date && <span className="text-muted-foreground ml-1.5 font-mono text-[11px]">({e.exam_date})</span>}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Setup Button */}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowSetupModal(true)}
            className="h-9 gap-1.5 shadow-sm text-xs"
          >
            <Plus className="h-3.5 w-3.5" />
            Setup Rooms
          </Button>

          {/* Prominent Generate Seating Button */}
          <Button
            size="sm"
            onClick={() => setShowGenerateModal(true)}
            className="h-9 gap-1.5 bg-primary text-primary-foreground shadow-md hover:shadow-lg transition-all text-xs font-semibold"
          >
            <Sparkles className="h-3.5 w-3.5" />
            {seating.length > 0 ? "Regenerate Seating Plan" : "Generate Seating Plan"}
          </Button>
        </div>
      </div>

      {/* Offline Notice */}
      {offline && (
        <Card className="border-destructive/30 bg-destructive/5 shadow-sm">
          <CardContent className="flex items-start gap-4 py-4">
            <ServerOff className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-sm text-destructive">Backend Server Offline</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                The FastAPI backend could not be reached. Ensure uvicorn is running on port 8000.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Stat KPI Cards (Apple / Linear style) */}
      {exam && (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          <Card className="shadow-sm border-border/70 bg-card/60 backdrop-blur-sm">
            <CardContent className="p-4 flex items-center justify-between">
              <div>
                <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Total Seated</div>
                <div className="text-2xl font-bold font-mono tabular-nums mt-0.5">{counts.total}</div>
                <div className="text-[11px] text-muted-foreground mt-0.5">{seating.length} halls allocated</div>
              </div>
              <div className="h-9 w-9 rounded-lg bg-primary/10 text-primary flex items-center justify-center">
                <Users className="h-4 w-4" />
              </div>
            </CardContent>
          </Card>

          <Card className="shadow-sm border-emerald-500/20 bg-emerald-500/5">
            <CardContent className="p-4 flex items-center justify-between">
              <div>
                <div className="text-xs font-medium text-emerald-800 dark:text-emerald-300 uppercase tracking-wider">Present</div>
                <div className="text-2xl font-bold font-mono text-emerald-700 dark:text-emerald-300 tabular-nums mt-0.5">
                  {counts.present}
                </div>
                <div className="text-[11px] text-emerald-600/80 dark:text-emerald-400 mt-0.5">{counts.pct}% of seated</div>
              </div>
              <div className="h-9 w-9 rounded-lg bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 flex items-center justify-center">
                <UserCheck className="h-4 w-4" />
              </div>
            </CardContent>
          </Card>

          <Card className="shadow-sm border-rose-500/20 bg-rose-500/5">
            <CardContent className="p-4 flex items-center justify-between">
              <div>
                <div className="text-xs font-medium text-rose-800 dark:text-rose-300 uppercase tracking-wider">Absent</div>
                <div className="text-2xl font-bold font-mono text-rose-700 dark:text-rose-300 tabular-nums mt-0.5">
                  {counts.absent}
                </div>
                <div className="text-[11px] text-rose-600/80 dark:text-rose-400 mt-0.5">Flagged for follow-up</div>
              </div>
              <div className="h-9 w-9 rounded-lg bg-rose-500/20 text-rose-700 dark:text-rose-300 flex items-center justify-center">
                <UserX className="h-4 w-4" />
              </div>
            </CardContent>
          </Card>

          <Card className="shadow-sm border-border/70 bg-card/60 backdrop-blur-sm">
            <CardContent className="p-4 flex items-center justify-between">
              <div>
                <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Unmarked</div>
                <div className="text-2xl font-bold font-mono text-muted-foreground tabular-nums mt-0.5">
                  {counts.unmarked}
                </div>
                <div className="text-[11px] text-muted-foreground mt-0.5">Pending invigilator mark</div>
              </div>
              <div className="h-9 w-9 rounded-lg bg-muted text-muted-foreground flex items-center justify-center">
                <MinusCircle className="h-4 w-4" />
              </div>
            </CardContent>
          </Card>

          <Card className="shadow-sm border-border/70 bg-card/60 backdrop-blur-sm col-span-2 lg:col-span-1">
            <CardContent className="p-4 flex flex-col justify-between h-full">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Exam Slot</span>
                <Badge variant="outline" className="text-[10px] font-mono">
                  {exam.time_slot || "09:30-12:30"}
                </Badge>
              </div>
              <div className="mt-2">
                <div className="text-xs font-semibold">{exam.label}</div>
                <div className="text-[11px] text-muted-foreground font-mono">{exam.exam_date || "No date set"}</div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Empty State when no examinations are registered */}
      {exams.length === 0 && !loading && !offline && (
        <Card className="border-dashed border-2 border-border/80 bg-muted/5 shadow-sm">
          <CardContent className="py-14 flex flex-col items-center justify-center text-center max-w-lg mx-auto">
            <div className="h-16 w-16 rounded-2xl bg-primary/10 text-primary flex items-center justify-center mb-4 shadow-inner">
              <Armchair className="h-8 w-8" />
            </div>
            <h3 className="text-xl font-bold tracking-tight">No Examinations Found</h3>
            <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
              Upload your student attendance sheets or register an examination to start generating seating arrangements and tracking attendance.
            </p>
            <div className="flex flex-wrap items-center justify-center gap-3 mt-6">
              <Button asChild className="gap-2 bg-primary text-primary-foreground font-medium shadow-md">
                <a href="/attendance/upload">
                  <Plus className="h-4 w-4" />
                  Upload Attendance Sheet
                </a>
              </Button>
              <Button variant="outline" onClick={() => setShowSetupModal(true)} className="gap-2">
                <Building2 className="h-4 w-4" />
                Manage Examination Rooms
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Empty State when no seating has been generated */}
      {exam && seating.length === 0 && !loading && !offline && (
        <Card className="border-dashed border-2 border-border/80 bg-muted/5 shadow-sm">
          <CardContent className="py-14 flex flex-col items-center justify-center text-center max-w-lg mx-auto">
            <div className="h-16 w-16 rounded-2xl bg-primary/10 text-primary flex items-center justify-center mb-4 shadow-inner">
              <Armchair className="h-8 w-8" />
            </div>
            <h3 className="text-xl font-bold tracking-tight">No Seating Plan Generated Yet</h3>
            <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
              Generate an interleaved bus-style seating arrangement for <strong>{exam.label}</strong>.
              Eligible students from B1 and B2 will be automatically paired desk-by-desk across your selected examination halls.
            </p>
            <div className="flex flex-wrap items-center justify-center gap-3 mt-6">
              <Button
                onClick={() => setShowGenerateModal(true)}
                className="gap-2 bg-primary text-primary-foreground font-medium shadow-md hover:shadow-lg"
              >
                <Sparkles className="h-4 w-4" />
                Generate Seating Plan Now
              </Button>
              <Button variant="outline" onClick={() => setShowSetupModal(true)} className="gap-2">
                <Building2 className="h-4 w-4" />
                Manage Rooms
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Active Seating Layout View */}
      {seating.length > 0 && (
        <div className="grid gap-6 xl:grid-cols-4">
          {/* Main Seating Content (3 cols) */}
          <div className="xl:col-span-3 space-y-4">
            {/* Filter and Tab Navigation Bar */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 rounded-xl border bg-card/80 backdrop-blur-sm shadow-sm">
              {/* Room Switcher Pills */}
              <div className="flex flex-wrap items-center gap-1.5">
                <Button
                  size="sm"
                  variant={activeRoomTab === "all" ? "default" : "outline"}
                  onClick={() => setActiveRoomTab("all")}
                  className="h-8 text-xs gap-1.5"
                >
                  <Building2 className="h-3.5 w-3.5" />
                  All Rooms ({sortedRooms.length})
                </Button>
                {sortedRooms.map((r) => {
                  const roomSeatsCount = r.seats.reduce((acc, s) => acc + (s.left ? 1 : 0) + (s.right ? 1 : 0), 0)
                  return (
                    <Button
                      key={r.room_id}
                      size="sm"
                      variant={activeRoomTab === String(r.room_id) ? "default" : "outline"}
                      onClick={() => setActiveRoomTab(String(r.room_id))}
                      className="h-8 text-xs font-mono"
                    >
                      Room {r.room_number}
                      <span className="opacity-60 ml-1 text-[10px]">({roomSeatsCount})</span>
                    </Button>
                  )
                })}
              </div>

              {/* Search & Quick Filter */}
              <div className="flex items-center gap-2">
                <div className="relative">
                  <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    placeholder="Search roll / name..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="h-8 pl-8 text-xs w-[180px] shadow-none"
                  />
                </div>

                <Select
                  value={statusFilter}
                  onValueChange={(v) => setStatusFilter(v as "all" | "present" | "absent" | "unmarked")}
                >
                  <SelectTrigger className="h-8 text-xs w-[110px]">
                    <SelectValue placeholder="Status" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all" className="text-xs">All Marks</SelectItem>
                    <SelectItem value="present" className="text-xs">Present Only</SelectItem>
                    <SelectItem value="absent" className="text-xs">Absent Only</SelectItem>
                    <SelectItem value="unmarked" className="text-xs">Unmarked</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Master Seating Overview Table (Ascending by Room Number) */}
            {activeRoomTab === "all" && sortedRooms.length > 0 && (
              <Card className="shadow-sm border-border/80 overflow-hidden bg-card/60">
                <CardHeader className="py-3 px-4 bg-muted/30 border-b border-border/60">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                      <Building2 className="h-3.5 w-3.5 text-primary" />
                      <span>Room Allocation Summary (Ascending Order)</span>
                    </CardTitle>
                    <span className="text-[11px] text-muted-foreground font-mono">
                      {sortedRooms.length} Examination Halls
                    </span>
                  </div>
                </CardHeader>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead className="bg-muted/20 border-b border-border/60 text-muted-foreground font-semibold">
                      <tr>
                        <th className="py-2.5 px-4 font-mono">Room No.</th>
                        <th className="py-2.5 px-3">Seated / Cap</th>
                        <th className="py-2.5 px-4 text-indigo-700 dark:text-indigo-300">Batch 1 (B1) Roll Range</th>
                        <th className="py-2.5 px-4 text-teal-700 dark:text-teal-300">Batch 2 (B2) Roll Range</th>
                        <th className="py-2.5 px-3">Invigilator</th>
                        <th className="py-2.5 px-4 text-right">PDF</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/40">
                      {sortedRooms.map((r) => {
                        const b1 = r.seats
                          .map((s) => s.left)
                          .filter((s): s is SeatStudent => Boolean(s))
                          .sort((a, b) => a.roll_number.localeCompare(b.roll_number, undefined, { numeric: true }))
                        const b2 = r.seats
                          .map((s) => s.right)
                          .filter((s): s is SeatStudent => Boolean(s))
                          .sort((a, b) => a.roll_number.localeCompare(b.roll_number, undefined, { numeric: true }))
                        const duty = dutyByRoom[r.room_id]
                        return (
                          <tr key={r.room_id} className="hover:bg-muted/20 transition-colors">
                            <td className="py-2.5 px-4 font-mono font-bold text-foreground">
                              Room {r.room_number}
                            </td>
                            <td className="py-2.5 px-3 font-mono">
                              {b1.length + b2.length} / {r.capacity || 60}
                            </td>
                            <td className="py-2.5 px-4 font-mono text-indigo-700 dark:text-indigo-300">
                              {getRollRange(b1)} <span className="text-muted-foreground text-[10px]">({b1.length})</span>
                            </td>
                            <td className="py-2.5 px-4 font-mono text-teal-700 dark:text-teal-300">
                              {getRollRange(b2)} <span className="text-muted-foreground text-[10px]">({b2.length})</span>
                            </td>
                            <td className="py-2.5 px-3">
                              {duty?.faculty_name ? (
                                <span className="font-medium text-foreground">{duty.faculty_name}</span>
                              ) : (
                                <span className="text-muted-foreground/60 italic text-[11px]">Unassigned</span>
                              )}
                            </td>
                            <td className="py-2.5 px-4 text-right">
                              {examId && (
                                <a
                                  href={`/api/pdf/seating/${examId}/${r.room_id}`}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline font-medium"
                                >
                                  <Printer className="h-3 w-3" /> PDF
                                </a>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}

            {/* Room Halls with Batch 1 and Batch 2 Separately (Alag-Alag) */}
            {displayedRooms.map((room) => {
              const duty = dutyByRoom[room.room_id]
              const availableFaculty = faculty.filter((f) => f.status === "Available")

              // Extract Batch 1 and Batch 2 students for this room in ascending order
              const b1Students = room.seats
                .map((s) => s.left)
                .filter((s): s is SeatStudent => Boolean(s))
                .sort((a, b) => a.roll_number.localeCompare(b.roll_number, undefined, { numeric: true }))

              const b2Students = room.seats
                .map((s) => s.right)
                .filter((s): s is SeatStudent => Boolean(s))
                .sort((a, b) => a.roll_number.localeCompare(b.roll_number, undefined, { numeric: true }))

              // Filter students according to search and status
              const filterFn = (s: SeatStudent) => {
                const q = searchQuery.toLowerCase().trim()
                const matchSearch = !q || s.roll_number.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)
                if (!matchSearch) return false

                const mark = marks[s.id] ?? (s.status as Mark) ?? null
                if (statusFilter === "present") return mark === "Present"
                if (statusFilter === "absent") return mark === "Absent"
                if (statusFilter === "unmarked") return mark === null
                return true
              }

              const filteredB1 = b1Students.filter(filterFn)
              const filteredB2 = b2Students.filter(filterFn)

              return (
                <Card key={room.room_id} className="shadow-sm border-border/80 overflow-hidden bg-card/90">
                  {/* Room Card Header */}
                  <CardHeader className="py-3.5 px-5 bg-muted/20 border-b border-border/60">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <div className="h-9 w-9 rounded-lg bg-primary/15 text-primary flex items-center justify-center font-mono font-bold text-sm shadow-xs border border-primary/20">
                          {room.room_number}
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <CardTitle className="text-base font-bold font-mono">
                              Room {room.room_number}
                            </CardTitle>
                            <Badge variant="secondary" className="font-sans text-[11px] font-medium">
                              {b1Students.length + b2Students.length} / {room.capacity || 60} seated
                            </Badge>
                          </div>
                          <div className="flex flex-wrap items-center gap-2 mt-0.5 text-xs text-muted-foreground">
                            <span className="text-indigo-600 dark:text-indigo-400 font-medium">
                              B1: {getRollRange(b1Students)} ({b1Students.length})
                            </span>
                            <span>·</span>
                            <span className="text-teal-600 dark:text-teal-400 font-medium">
                              B2: {getRollRange(b2Students)} ({b2Students.length})
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Room Actions & Invigilator Assign Bar */}
                      <div className="flex flex-wrap items-center gap-2">
                        {duty?.faculty_name ? (
                          <div className="flex items-center gap-1.5 bg-background border px-2.5 py-1 rounded-md shadow-sm">
                            <GraduationCap className="h-3.5 w-3.5 text-primary" />
                            <span className="text-xs font-medium">{duty.faculty_name}</span>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-5 px-1 text-[10px] text-muted-foreground hover:text-destructive"
                              onClick={() => unassignDuty(duty.id)}
                            >
                              Remove
                            </Button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5">
                            <Select
                              value={assignSel[room.room_id] ?? ""}
                              onValueChange={(v) => setAssignSel((p) => ({ ...p, [room.room_id]: v ?? "" }))}
                            >
                              <SelectTrigger className="w-[160px] h-8 text-xs">
                                <SelectValue placeholder="Assign Invigilator" />
                              </SelectTrigger>
                              <SelectContent>
                                {availableFaculty.map((f) => (
                                  <SelectItem key={f.faculty_id} value={String(f.faculty_id)} className="text-xs">
                                    {f.abbreviation ? `${f.abbreviation} — ` : ""}{f.faculty_name}
                                  </SelectItem>
                                ))}
                                {availableFaculty.length === 0 && (
                                  <div className="p-2 text-xs text-muted-foreground">No available faculty for this slot</div>
                                )}
                              </SelectContent>
                            </Select>
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-8 text-xs"
                              disabled={!assignSel[room.room_id]}
                              onClick={() => assignDuty(room.room_id)}
                            >
                              Assign
                            </Button>
                          </div>
                        )}

                        {/* Export PDF Button */}
                        {examId && (
                          <a
                            href={`/api/pdf/seating/${examId}/${room.room_id}`}
                            target="_blank"
                            rel="noreferrer"
                            title="Download seating chart printable PDF"
                            className="inline-flex items-center justify-center rounded-md border border-input bg-background hover:bg-accent hover:text-accent-foreground h-8 px-3 text-xs gap-1.5 shadow-sm font-medium transition-colors"
                          >
                            <Printer className="h-3.5 w-3.5" />
                            PDF Chart
                          </a>
                        )}
                      </div>
                    </div>
                  </CardHeader>

                  {/* Body: Batch 1 (B1) and Batch 2 (B2) Alag-Alag */}
                  <CardContent className="p-4 sm:p-5">
                    <div className="grid gap-4 md:grid-cols-2">
                      {/* ──── BATCH 1 (B1) COLUMN ──── */}
                      <div className="rounded-xl border border-indigo-500/25 bg-indigo-500/5 p-4 space-y-3">
                        <div className="flex items-center justify-between pb-2.5 border-b border-indigo-500/20">
                          <div className="flex items-center gap-2">
                            <span className="px-2 py-0.5 rounded-md font-mono font-bold text-xs bg-indigo-600 text-white shadow-xs">
                              Batch 1 (B1)
                            </span>
                            <span className="text-xs font-semibold text-foreground">
                              {filteredB1.length} {filteredB1.length === 1 ? "Student" : "Students"}
                            </span>
                          </div>
                          <span className="text-[11px] font-mono text-indigo-700 dark:text-indigo-300 font-medium truncate max-w-[200px]">
                            {getRollRange(b1Students)}
                          </span>
                        </div>

                        <div className="space-y-1.5 max-h-[560px] overflow-y-auto pr-1">
                          {filteredB1.map((student, idx) => (
                            <StudentRow
                              key={student.id}
                              student={student}
                              index={idx}
                              mark={marks[student.id] ?? (student.status as Mark) ?? null}
                              onToggle={() => toggle(student)}
                              isHighlighted={Boolean(
                                searchQuery &&
                                (student.roll_number.toLowerCase().includes(searchQuery.toLowerCase()) ||
                                 student.name.toLowerCase().includes(searchQuery.toLowerCase()))
                              )}
                            />
                          ))}
                          {filteredB1.length === 0 && (
                            <div className="py-8 text-center text-xs text-muted-foreground">
                              {b1Students.length === 0
                                ? "No Batch 1 students allocated in this room."
                                : "No students match your filter."}
                            </div>
                          )}
                        </div>
                      </div>

                      {/* ──── BATCH 2 (B2) COLUMN ──── */}
                      <div className="rounded-xl border border-teal-500/25 bg-teal-500/5 p-4 space-y-3">
                        <div className="flex items-center justify-between pb-2.5 border-b border-teal-500/20">
                          <div className="flex items-center gap-2">
                            <span className="px-2 py-0.5 rounded-md font-mono font-bold text-xs bg-teal-600 text-white shadow-xs">
                              Batch 2 (B2)
                            </span>
                            <span className="text-xs font-semibold text-foreground">
                              {filteredB2.length} {filteredB2.length === 1 ? "Student" : "Students"}
                            </span>
                          </div>
                          <span className="text-[11px] font-mono text-teal-700 dark:text-teal-300 font-medium truncate max-w-[200px]">
                            {getRollRange(b2Students)}
                          </span>
                        </div>

                        <div className="space-y-1.5 max-h-[560px] overflow-y-auto pr-1">
                          {filteredB2.map((student, idx) => (
                            <StudentRow
                              key={student.id}
                              student={student}
                              index={idx}
                              mark={marks[student.id] ?? (student.status as Mark) ?? null}
                              onToggle={() => toggle(student)}
                              isHighlighted={Boolean(
                                searchQuery &&
                                (student.roll_number.toLowerCase().includes(searchQuery.toLowerCase()) ||
                                 student.name.toLowerCase().includes(searchQuery.toLowerCase()))
                              )}
                            />
                          ))}
                          {filteredB2.length === 0 && (
                            <div className="py-8 text-center text-xs text-muted-foreground">
                              {b2Students.length === 0
                                ? "No Batch 2 students allocated in this room."
                                : "No students match your filter."}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>

          {/* Sidebar / Faculty Availability Status Panel (1 col) */}
          <div className="space-y-4">
            <Card className="sticky top-6 shadow-sm border-border/70 bg-card/90 backdrop-blur-sm">
              <CardHeader className="py-4 px-4 pb-2">
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <GraduationCap className="h-4 w-4 text-primary" />
                  Faculty Availability
                </CardTitle>
                <CardDescription className="text-xs">
                  {exam ? `${exam.label} (${exam.time_slot || "09:30-12:30"})` : "Select an exam"}
                </CardDescription>
              </CardHeader>
              <CardContent className="p-4 pt-1 space-y-3">
                {/* Filter Pills */}
                <div className="flex flex-wrap gap-1 text-[11px]">
                  {[
                    ["all", "All"],
                    ["free", "Free"],
                    ["onduty", "On Duty"],
                    ["teaching", "Teaching"],
                    ["exempt", "Exempt"],
                  ].map(([val, label]) => (
                    <button
                      key={val}
                      type="button"
                      onClick={() => setFacultyFilter(val)}
                      className={`px-2 py-0.5 rounded text-xs transition-colors ${
                        facultyFilter === val
                          ? "bg-primary text-primary-foreground font-medium shadow-xs"
                          : "bg-muted text-muted-foreground hover:bg-muted/80"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                {/* Faculty List */}
                <div className="max-h-[500px] overflow-y-auto space-y-2 pr-1 pb-3 scroll-smooth">
                  {filteredFaculty.map((f) => (
                    <div
                      key={f.faculty_id}
                      className="p-2.5 rounded-lg border border-border/70 bg-card/70 hover:bg-card transition-colors shadow-2xs"
                    >
                      <div className="flex items-center justify-between gap-1.5 mb-1">
                        <span className="text-xs font-semibold truncate text-foreground">{f.faculty_name}</span>
                        <Badge variant="outline" className={`shrink-0 text-[9px] px-1.5 py-0 font-medium ${facultyStatusStyle(f.status)}`}>
                          {f.status}
                        </Badge>
                      </div>
                      <div className="text-[11px] text-muted-foreground truncate">
                        {f.department ? `${f.department} • ` : ""}
                        {f.reason}
                      </div>
                    </div>
                  ))}
                  {filteredFaculty.length === 0 && (
                    <p className="text-xs text-muted-foreground text-center py-6">No faculty in this category.</p>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Legend Guide */}
            <Card className="border-border/60 bg-muted/10 shadow-none">
              <CardContent className="p-3.5 space-y-2 text-xs text-muted-foreground">
                <span className="font-semibold text-foreground text-xs block mb-1">Seating Legend</span>
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center justify-center h-4 w-4 rounded bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 font-bold text-[10px]">
                    P
                  </span>
                  <span>Present (Eligible & Sitting)</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center justify-center h-4 w-4 rounded bg-rose-500/20 text-rose-700 dark:text-rose-300 font-bold text-[10px]">
                    A
                  </span>
                  <span>Absent (Recorded for VT rule)</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center justify-center h-4 w-4 rounded bg-muted text-muted-foreground font-bold text-[10px]">
                    —
                  </span>
                  <span>Unmarked slot</span>
                </div>
                <div className="text-[11px] pt-1 border-t border-border/40">
                  <span className="font-semibold text-foreground">B1 / B2:</span> Interleaved batches for anti-cheating exam seating.
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* ── SEATING PLAN GENERATOR DIALOG ────────────────────────────────────── */}
      <Dialog open={showGenerateModal} onOpenChange={setShowGenerateModal}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-lg">
              <Sparkles className="h-5 w-5 text-primary" />
              Generate Seating Plan
            </DialogTitle>
            <DialogDescription className="text-xs">
              Automated examination seating generator with B1/B2 interleaving. Pick the exam and halls to allocate.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* Exam info */}
            <div className="p-3 rounded-lg border bg-muted/20 space-y-1">
              <div className="text-xs text-muted-foreground font-medium">Selected Examination</div>
              <div className="text-sm font-bold flex items-center gap-2">
                {exam?.label || "MST Exam"}
                <Badge variant="outline" className="text-[10px] font-mono">
                  {exam?.time_slot || "09:30-12:30"}
                </Badge>
              </div>
            </div>

            {/* Room Multi-select */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <Label className="text-xs font-semibold">Select Examination Halls</Label>
                <div className="flex items-center gap-2 text-[11px]">
                  <button
                    type="button"
                    onClick={() => setSelectedRoomIds(rooms.map((r) => r.id))}
                    className="text-primary hover:underline"
                  >
                    Select All
                  </button>
                  <span className="text-muted-foreground">•</span>
                  <button
                    type="button"
                    onClick={() => setSelectedRoomIds([])}
                    className="text-muted-foreground hover:underline"
                  >
                    Clear
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 max-h-[220px] overflow-y-auto pr-1">
                {rooms.map((r) => {
                  const isSelected = selectedRoomIds.includes(r.id)
                  return (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() =>
                        setSelectedRoomIds((prev) =>
                          isSelected ? prev.filter((id) => id !== r.id) : [...prev, r.id]
                        )
                      }
                      className={`flex items-center justify-between p-2.5 rounded-lg border text-left transition-all ${
                        isSelected
                          ? "border-primary bg-primary/10 text-primary font-semibold ring-1 ring-primary/20"
                          : "border-border hover:border-foreground/30 bg-card text-foreground"
                      }`}
                    >
                      <div className="min-w-0">
                        <div className="font-mono text-xs font-bold">Room {r.room_number}</div>
                        <div className="text-[11px] text-muted-foreground font-normal">Cap: {r.capacity || 60} seats</div>
                      </div>
                      <div
                        className={`h-5 w-5 rounded-md flex items-center justify-center border transition-colors ${
                          isSelected ? "bg-primary border-primary text-primary-foreground" : "border-border"
                        }`}
                      >
                        {isSelected && <Check className="h-3.5 w-3.5" />}
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Capacity Summary Box */}
            <div className="rounded-lg border p-3 bg-muted/30 text-xs space-y-1.5">
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Halls Selected:</span>
                <span className="font-mono font-semibold">{selectedRoomIds.length} rooms</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Total Capacity:</span>
                <span className="font-mono font-bold text-primary">{selectedRoomsCapacity} student desks</span>
              </div>
              <p className="text-[11px] text-muted-foreground pt-1 border-t border-border/40">
                Eligible students (attendance &ge; 45% or authorized override) will be seated in B1/B2 sequence.
              </p>
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" size="sm" onClick={() => setShowGenerateModal(false)} disabled={busy}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleGenerateSeating}
              disabled={busy || selectedRoomIds.length === 0}
              className="gap-1.5 bg-primary font-semibold"
            >
              {busy ? <RefreshCw className="h-3.5 w-3.5 animate-spin mr-1" /> : <Sparkles className="h-3.5 w-3.5 mr-1" />}
              {busy ? "Generating..." : "Generate Seating Arrangement"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── SETUP ROOMS & EXAMS MODAL ────────────────────────────────────────── */}
      <Dialog open={showSetupModal} onOpenChange={setShowSetupModal}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base flex items-center gap-2">
              <Building2 className="h-4 w-4 text-primary" />
              Examination Setup
            </DialogTitle>
            <DialogDescription className="text-xs">
              Add examination rooms or register a new MST examination slot.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* Add Room Section */}
            <div className="space-y-2 border-b pb-4">
              <Label className="text-xs font-semibold">Add Examination Room</Label>
              <div className="flex gap-2">
                <Input
                  placeholder="Room No (e.g. 104)"
                  value={newRoom.room_number}
                  onChange={(e) => setNewRoom({ ...newRoom, room_number: e.target.value })}
                  className="h-8 text-xs"
                />
                <Input
                  type="number"
                  placeholder="Capacity (60)"
                  value={newRoom.capacity}
                  onChange={(e) => setNewRoom({ ...newRoom, capacity: e.target.value })}
                  className="h-8 text-xs w-28"
                />
                <Button size="sm" variant="outline" onClick={addRoom} className="h-8 text-xs">
                  Add
                </Button>
              </div>
            </div>

            {/* Add Exam Section */}
            <div className="space-y-3">
              <Label className="text-xs font-semibold">Schedule New Exam</Label>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <Label className="text-[11px] text-muted-foreground">Label</Label>
                  <Input
                    placeholder="MST-1 / MST-2"
                    value={newExam.label}
                    onChange={(e) => setNewExam({ ...newExam, label: e.target.value })}
                    className="h-8 text-xs mt-1"
                  />
                </div>
                <div>
                  <Label className="text-[11px] text-muted-foreground">Date</Label>
                  <Input
                    type="date"
                    value={newExam.exam_date}
                    onChange={(e) => setNewExam({ ...newExam, exam_date: e.target.value })}
                    className="h-8 text-xs mt-1"
                  />
                </div>
                <div>
                  <Label className="text-[11px] text-muted-foreground">Time Slot</Label>
                  <Input
                    placeholder="09:30-12:30"
                    value={newExam.time_slot}
                    onChange={(e) => setNewExam({ ...newExam, time_slot: e.target.value })}
                    className="h-8 text-xs mt-1"
                  />
                </div>
                <div>
                  <Label className="text-[11px] text-muted-foreground">Class</Label>
                  <Select value={newExam.class_id} onValueChange={(v) => setNewExam({ ...newExam, class_id: v ?? "" })}>
                    <SelectTrigger className="h-8 text-xs mt-1">
                      <SelectValue placeholder="Pick class" />
                    </SelectTrigger>
                    <SelectContent>
                      {classes.map((c) => (
                        <SelectItem key={c.id} value={String(c.id)} className="text-xs">
                          {c.name} · {c.branch}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <Button size="sm" onClick={createExam} disabled={busy} className="w-full text-xs h-8 mt-2">
                Create MST Exam Slot
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
