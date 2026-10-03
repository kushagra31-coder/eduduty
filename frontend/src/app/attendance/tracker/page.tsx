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
import { useToast } from "@/components/ui/use-toast"
import {
  Armchair, Users, UserCheck, UserX, MinusCircle, RefreshCw,
  ServerOff, Plus, ClipboardCheck, GraduationCap,
} from "lucide-react"

const API = "/api"

type Exam = { id: number; label: string; exam_date: string | null; time_slot: string | null; class_id: number | null }
type Room = { id: number; room_number: string; capacity: number | null }
type SeatStudent = { id: number; roll_number: string; name: string; batch_number: number | null }
type Seat = {
  id: number; seat_number: string | null; room_id: number; room_number: string
  left: SeatStudent | null; right: SeatStudent | null
  left_status?: string | null; right_status?: string | null
}
type RoomSeating = { room_id: number; room_number: string; capacity: number | null; seats: Seat[] }
type FacultyStatus = {
  faculty_id: number; faculty_name: string; abbreviation: string | null
  department: string | null; status: "Available" | "Teaching" | "On duty" | "Exempt"; reason: string
}
type Duty = { id: number; room_id: number; room_number: string; faculty_id: number | null; faculty_name: string | null; status: string }
type ClassInfo = { id: number; name: string; branch: string }

type Mark = "Present" | "Absent" | null

async function api(path: string, init?: RequestInit) {
  const res = await fetch(`${API}${path}`, init)
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error((detail as { detail?: string }).detail || `request failed (${res.status})`)
  }
  return res.json()
}

function nextMark(m: Mark): Mark {
  // click toggles: unmarked -> present -> absent -> present ...
  return m === "Present" ? "Absent" : "Present"
}

function StudentHalf({
  student, mark, onToggle,
}: { student: SeatStudent | null; mark: Mark; onToggle: () => void }) {
  if (!student) {
    return (
      <div className="flex-1 rounded-md border border-dashed border-muted-foreground/20 bg-muted/20 px-2 py-3 flex items-center justify-center text-[10px] text-muted-foreground/60 transition-colors">
        empty seat
      </div>
    )
  }
  const style =
    mark === "Present"
      ? "bg-black text-white border-black"
      : mark === "Absent"
        ? "bg-white text-black border-black"
        : "bg-white text-foreground border-dashed border-muted-foreground/50 hover:border-foreground"
  return (
    <button
      onClick={onToggle}
      title={`${student.name} (${student.roll_number}) — click to mark ${mark === "Present" ? "absent" : "present"}`}
      className={`flex-1 rounded-md border-2 px-2 py-2 text-left transition-all active:scale-95 ${style}`}
    >
      <div className={`text-[11px] font-semibold leading-tight truncate ${mark === "Absent" ? "line-through" : ""}`}>
        {student.name}
      </div>
      <div className={`font-mono text-[10px] tabular-nums ${mark === "Present" ? "text-white/70" : "text-muted-foreground"}`}>
        {student.roll_number}
      </div>
      <div className="mt-1 flex items-center gap-1">
        {student.batch_number ? (
          <span className={`text-[9px] font-mono px-1 rounded ${mark === "Present" ? "bg-white/20" : "bg-muted"}`}>
            B{student.batch_number}
          </span>
        ) : null}
        {mark === "Present" && <UserCheck className="h-3 w-3" />}
        {mark === "Absent" && <UserX className="h-3 w-3" />}
        {mark === null && <MinusCircle className="h-3 w-3 opacity-40" />}
      </div>
    </button>
  )
}

export default function AttendanceTracker() {
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
  const [busy, setBusy] = useState(false)
  const [genRooms, setGenRooms] = useState<number[]>([])
  const [facultyFilter, setFacultyFilter] = useState("all")
  const [assignSel, setAssignSel] = useState<Record<number, string>>({})
  // setup forms
  const [showSetup, setShowSetup] = useState(false)
  const [newExam, setNewExam] = useState({ label: "MST-1", exam_date: "", time_slot: "09:30-12:30", class_id: "" })
  const [newRoom, setNewRoom] = useState({ room_number: "", capacity: "60" })

  const exam = exams.find((e) => e.id === examId) ?? null

  async function loadAll(id: number) {
    const [seatData, attData, facData, dutyData] = await Promise.all([
      api(`/mst/seating/${id}`),
      api(`/mst/attendance/${id}`),
      api(`/mst/faculty-status?mst_exam_id=${id}`),
      api(`/mst/duties/${id}`),
    ])
    setSeating(seatData)
    const m: Record<number, Mark> = {}
    for (const a of attData as { student_id: number; status: string }[]) {
      m[a.student_id] = a.status as Mark
    }
    setMarks(m)
    setFaculty(facData)
    setDuties(dutyData)
  }

  useEffect(() => {
    Promise.all([api("/mst/exams"), api("/rooms"), api("/classes")])
      .then(([e, r, c]) => {
        setExams(e); setRooms(r); setClasses(c)
        if (e.length > 0) setExamId(e[0].id)
      })
      .catch(() => setOffline(true))
  }, [])

  useEffect(() => {
    if (examId == null) return
    setOffline(false)
    loadAll(examId).catch(() => setOffline(true))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [examId])

  const seatedStudents = useMemo(() => {
    const list: SeatStudent[] = []
    for (const room of seating) for (const s of room.seats) {
      if (s.left) list.push(s.left)
      if (s.right) list.push(s.right)
    }
    return list
  }, [seating])

  const counts = useMemo(() => {
    let present = 0, absent = 0
    for (const s of seatedStudents) {
      if (marks[s.id] === "Present") present++
      else if (marks[s.id] === "Absent") absent++
    }
    return { present, absent, unmarked: seatedStudents.length - present - absent, total: seatedStudents.length }
  }, [seatedStudents, marks])

  async function toggle(student: SeatStudent) {
    if (examId == null) return
    const next = nextMark(marks[student.id] ?? null)
    setMarks((prev) => ({ ...prev, [student.id]: next })) // optimistic
    try {
      await api("/mst/attendance/mark", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mst_exam_id: examId, student_id: student.id, status: next }),
      })
    } catch (err) {
      toast({ title: "Couldn't save", description: (err as Error).message })
      if (examId != null) loadAll(examId).catch(() => {})
    }
  }

  async function generate() {
    if (examId == null || genRooms.length === 0) {
      toast({ title: "Pick at least one room", description: "Select the rooms to seat students in." })
      return
    }
    setBusy(true)
    try {
      const res = await api("/mst/seating/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mst_exam_id: examId, room_ids: genRooms }),
      })
      toast({
        title: "Seating generated",
        description: `${res.seats_created} seats — B1/B2 interleaved by roll number.` +
          (res.unseated?.length ? ` ${res.unseated.length} students didn't fit.` : ""),
      })
      await loadAll(examId)
    } catch (err) {
      toast({ title: "Seating failed", description: (err as Error).message })
    } finally {
      setBusy(false)
    }
  }

  async function createExam() {
    if (!newExam.label) return
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
      toast({ title: "Exam created", description: `${created.label} is ready for seating.` })
    } catch (err) {
      toast({ title: "Couldn't create exam", description: (err as Error).message })
    } finally {
      setBusy(false)
    }
  }

  async function addRoom() {
    if (!newRoom.room_number) return
    try {
      await api("/rooms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ room_number: newRoom.room_number, capacity: Number(newRoom.capacity) || 60 }),
      })
      setRooms(await api("/rooms"))
      setNewRoom({ room_number: "", capacity: "60" })
    } catch (err) {
      toast({ title: "Couldn't add room", description: (err as Error).message })
    }
  }

  async function assign(roomId: number) {
    const fid = assignSel[roomId]
    if (!fid || examId == null) return
    try {
      await api("/mst/duties/assign", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mst_exam_id: examId, room_id: roomId, faculty_id: Number(fid) }),
      })
      const [d, f] = await Promise.all([api(`/mst/duties/${examId}`), api(`/mst/faculty-status?mst_exam_id=${examId}`)])
      setDuties(d); setFaculty(f)
      toast({ title: "Duty assigned" })
    } catch (err) {
      toast({ title: "Assign failed", description: (err as Error).message })
    }
  }

  async function unassign(dutyId: number) {
    if (examId == null) return
    try {
      await api(`/mst/duties/unassign/${dutyId}`, { method: "POST" })
      const [d, f] = await Promise.all([api(`/mst/duties/${examId}`), api(`/mst/faculty-status?mst_exam_id=${examId}`)])
      setDuties(d); setFaculty(f)
    } catch (err) {
      toast({ title: "Couldn't unassign", description: (err as Error).message })
    }
  }

  const dutyByRoom = useMemo(() => {
    const m: Record<number, Duty> = {}
    for (const d of duties) m[d.room_id] = d
    return m
  }, [duties])

  const filteredFaculty = faculty.filter((f) =>
    facultyFilter === "all" ? true
      : facultyFilter === "free" ? f.status === "Available"
        : f.status === (facultyFilter === "onduty" ? "On duty" : facultyFilter === "teaching" ? "Teaching" : "Exempt"))

  const statusStyle = (s: FacultyStatus["status"]) =>
    s === "Available" ? "bg-black text-white"
      : s === "On duty" ? "bg-white text-black border-2 border-black"
        : s === "Teaching" ? "bg-white text-black border border-black"
          : "bg-muted text-muted-foreground line-through"

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <Armchair className="h-7 w-7" /> MST Attendance Tracker
          </h1>
          <p className="text-muted-foreground mt-2">
            Bus-seat style seating map — B1/B2 interleaved by roll number. Click a student to toggle present / absent.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={examId != null ? String(examId) : ""} onValueChange={(v) => setExamId(Number(v))}>
            <SelectTrigger className="w-44"><SelectValue placeholder="Select exam" /></SelectTrigger>
            <SelectContent>
              {exams.map((e) => <SelectItem key={e.id} value={String(e.id)}>{e.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" onClick={() => setShowSetup((s) => !s)}>
            <Plus className="h-4 w-4 mr-1" /> Setup
          </Button>
        </div>
      </div>

      {offline && (
        <Card className="border-dashed">
          <CardContent className="flex items-start gap-4 py-6">
            <ServerOff className="h-5 w-5 mt-0.5 shrink-0" />
            <div>
              <p className="font-medium">Couldn&apos;t reach the backend</p>
              <p className="text-sm text-muted-foreground mt-1">
                In a terminal, run <code className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded">uvicorn main:app --reload --port 8000</code> inside{" "}
                <code className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded">backend/</code>, then refresh.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {showSetup && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader><CardTitle className="text-base">New MST exam</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Label</Label><Input value={newExam.label} onChange={(e) => setNewExam({ ...newExam, label: e.target.value })} placeholder="MST-1" /></div>
                <div><Label>Date</Label><Input type="date" value={newExam.exam_date} onChange={(e) => setNewExam({ ...newExam, exam_date: e.target.value })} /></div>
                <div><Label>Time slot</Label><Input value={newExam.time_slot} onChange={(e) => setNewExam({ ...newExam, time_slot: e.target.value })} placeholder="09:30-12:30" /></div>
                <div>
                  <Label>Class / branch</Label>
                  <Select value={newExam.class_id} onValueChange={(v) => setNewExam({ ...newExam, class_id: v ?? "" })}>
                    <SelectTrigger><SelectValue placeholder="Pick class" /></SelectTrigger>
                    <SelectContent>
                      {classes.map((c) => <SelectItem key={c.id} value={String(c.id)}>{c.name} · {c.branch}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <Button size="sm" onClick={createExam} disabled={busy}>Create exam</Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="text-base">Rooms</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {rooms.map((r) => <Badge key={r.id} variant="outline" className="font-mono">{r.room_number} · {r.capacity}</Badge>)}
                {rooms.length === 0 && <span className="text-sm text-muted-foreground">No rooms yet.</span>}
              </div>
              <div className="flex gap-2">
                <Input className="w-32" placeholder="R-101" value={newRoom.room_number} onChange={(e) => setNewRoom({ ...newRoom, room_number: e.target.value })} />
                <Input className="w-24" type="number" placeholder="60" value={newRoom.capacity} onChange={(e) => setNewRoom({ ...newRoom, capacity: e.target.value })} />
                <Button size="sm" variant="outline" onClick={addRoom}>Add</Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {exam && (
        <div className="grid gap-4 md:grid-cols-4">
          {[
            { label: "Seated", value: counts.total, icon: <Users className="h-4 w-4" /> },
            { label: "Present", value: counts.present, icon: <UserCheck className="h-4 w-4" /> },
            { label: "Absent", value: counts.absent, icon: <UserX className="h-4 w-4" /> },
            { label: "Unmarked", value: counts.unmarked, icon: <MinusCircle className="h-4 w-4" /> },
          ].map((s) => (
            <Card key={s.label}>
              <CardContent className="py-4 flex items-center justify-between">
                <div>
                  <div className="text-2xl font-bold font-mono tabular-nums">{s.value}</div>
                  <div className="text-xs text-muted-foreground">{s.label}</div>
                </div>
                {s.icon}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {exam && seating.length === 0 && !offline && (
        <Card className="border-dashed">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2"><ClipboardCheck className="h-4 w-4" /> Generate the seating chart</CardTitle>
            <CardDescription>
              Students of {exam.label} are paired B1-roll-1 with B2-roll-1, B1-roll-2 with B2-roll-2, and so on —
              then dealt into the rooms you pick, in order.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-2">
              {rooms.map((r) => (
                <label key={r.id} className={`cursor-pointer rounded-md border-2 px-3 py-1.5 font-mono text-sm transition-all ${genRooms.includes(r.id) ? "bg-black text-white border-black" : "border-muted hover:border-foreground"}`}>
                  <input
                    type="checkbox" className="sr-only"
                    checked={genRooms.includes(r.id)}
                    onChange={() => setGenRooms((p) => p.includes(r.id) ? p.filter((x) => x !== r.id) : [...p, r.id])}
                  />
                  {r.room_number} <span className="opacity-60">· {r.capacity}</span>
                </label>
              ))}
              {rooms.length === 0 && <span className="text-sm text-muted-foreground">Add rooms in Setup first.</span>}
            </div>
            <Button onClick={generate} disabled={busy}>
              <RefreshCw className={`h-4 w-4 mr-2 ${busy ? "animate-spin" : ""}`} />
              Generate seating
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="xl:col-span-2 space-y-6">
          {seating.map((room) => {
            const duty = dutyByRoom[room.room_id]
            const available = faculty.filter((f) => f.status === "Available")
            return (
              <Card key={room.room_id}>
                <CardHeader className="pb-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <CardTitle className="text-lg font-mono flex items-center gap-4">
                      Room {room.room_number}
                      {room.capacity ? (
                        <div className="flex items-center gap-2 text-xs text-muted-foreground font-sans font-normal">
                          <div className="w-24 h-2 bg-muted rounded-full overflow-hidden">
                            <div
                              className="h-full bg-black transition-all"
                              style={{ width: `${Math.min(100, (room.seats.reduce((acc, s) => acc + (s.left ? 1 : 0) + (s.right ? 1 : 0), 0) / room.capacity) * 100)}%` }}
                            />
                          </div>
                          {room.seats.reduce((acc, s) => acc + (s.left ? 1 : 0) + (s.right ? 1 : 0), 0)} / {room.capacity} seated
                        </div>
                      ) : null}
                    </CardTitle>
                    <div className="flex items-center gap-2 text-sm">
                      {duty?.faculty_name ? (
                        <span className="flex items-center gap-2">
                          <Badge className="bg-black text-white">
                            <GraduationCap className="h-3 w-3 mr-1" /> {duty.faculty_name}
                          </Badge>
                          <Button variant="ghost" size="sm" onClick={() => unassign(duty.id)}>remove</Button>
                        </span>
                      ) : (
                        <span className="flex items-center gap-2">
                          <Select value={assignSel[room.room_id] ?? ""} onValueChange={(v) => setAssignSel((p) => ({ ...p, [room.room_id]: v ?? "" }))}>
                            <SelectTrigger className="w-44 h-8 text-xs"><SelectValue placeholder="Assign invigilator" /></SelectTrigger>
                            <SelectContent>
                              {available.map((f) => (
                                <SelectItem key={f.faculty_id} value={String(f.faculty_id)}>
                                  {f.abbreviation ? `${f.abbreviation} — ` : ""}{f.faculty_name}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <Button size="sm" variant="outline" onClick={() => assign(room.room_id)}>Assign</Button>
                        </span>
                      )}
                    </div>
                  </div>
                  <CardDescription>{room.seats.length} seats · click a student to toggle present / absent</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {room.seats.map((s) => (
                      <div key={s.id} className="rounded-lg border bg-muted/30 p-1.5">
                        <div className="font-mono text-[10px] text-muted-foreground px-1 pb-1">seat {s.seat_number}</div>
                        <div className="flex gap-1.5">
                          <StudentHalf student={s.left} mark={s.left ? (marks[s.left.id] ?? s.left_status as Mark ?? null) : null} onToggle={() => s.left && toggle(s.left)} />
                          <StudentHalf student={s.right} mark={s.right ? (marks[s.right.id] ?? s.right_status as Mark ?? null) : null} onToggle={() => s.right && toggle(s.right)} />
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>

        <div>
          <Card className="xl:sticky xl:top-4">
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2"><GraduationCap className="h-4 w-4" /> Faculty — exam slot</CardTitle>
              <CardDescription>
                {exam ? `${exam.label}${exam.exam_date ? ` · ${exam.exam_date}` : ""}${exam.time_slot ? ` · ${exam.time_slot}` : ""}` : "Pick an exam to see who's free."}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-1.5">
                {[["all", "All"], ["free", "Free"], ["teaching", "Teaching"], ["onduty", "On duty"], ["exempt", "Exempt"]].map(([v, l]) => (
                  <Button key={v} size="sm" variant={facultyFilter === v ? "default" : "outline"}
                    className={facultyFilter === v ? "bg-black text-white" : ""}
                    onClick={() => setFacultyFilter(v)}>
                    {l}
                  </Button>
                ))}
              </div>
              <div className="max-h-[480px] overflow-y-auto space-y-1.5 pr-1">
                {filteredFaculty.map((f) => (
                  <div key={f.faculty_id} className="flex items-center justify-between gap-2 rounded-md border px-2.5 py-1.5">
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate">
                        {f.abbreviation ? <span className="font-mono text-xs mr-1.5 text-muted-foreground">{f.abbreviation}</span> : null}
                        {f.faculty_name}
                      </div>
                      <div className="text-[11px] text-muted-foreground truncate">{f.reason}</div>
                    </div>
                    <Badge className={`shrink-0 text-[10px] ${statusStyle(f.status)}`}>{f.status}</Badge>
                  </div>
                ))}
                {filteredFaculty.length === 0 && (
                  <p className="text-sm text-muted-foreground py-4 text-center">No faculty in this bucket.</p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <Card className="border-dashed">
        <CardContent className="py-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Legend</span>
          <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-3 rounded-sm bg-black" /> present</span>
          <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-3 rounded-sm border-2 border-black bg-white" /> absent</span>
          <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-3 rounded-sm border-2 border-dashed border-muted-foreground" /> unmarked</span>
          <span className="font-mono">B1 / B2 = batch</span>
        </CardContent>
      </Card>
    </div>
  )
}
