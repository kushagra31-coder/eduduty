'use client'

import { useState, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useToast } from "@/components/ui/use-toast"

type Exam = { id: number; label: string; exam_date: string | null; time_slot: string | null; class_id: number | null }

type ProposalRow = {
  mst_exam_id: number; exam_label: string; exam_date: string; time_slot: string
  room_id: number; room_number: string; faculty_id: number; faculty_name: string; reason: string
}

type UnfilledRow = {
  mst_exam_id: number; exam_label: string; exam_date: string; time_slot: string
  room_id: number; room_number: string; reason: string; blockers: string[]
}

type Proposal = {
  proposal: ProposalRow[]
  unfilled: UnfilledRow[]
  skipped_exams: { mst_exam_id: number; label: string; reason: string }[]
  stats: { exams: number; rooms_filled: number; rooms_unfilled: number }
}

export default function DutiesPage() {
  const [exams, setExams] = useState<Exam[]>([])
  const [selected, setSelected] = useState<number[]>([])
  const [result, setResult] = useState<Proposal | null>(null)
  const [busy, setBusy] = useState(false)
  const [applying, setApplying] = useState(false)
  const { toast } = useToast()

  useEffect(() => {
    fetch("/api/mst/exams").then((r) => r.ok ? r.json() : []).then(setExams).catch(() => {})
  }, [])

  const toggle = (id: number) =>
    setSelected((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id])

  const generate = async () => {
    if (selected.length === 0) {
      toast({ title: "Pick at least one exam", variant: "destructive" })
      return
    }
    setBusy(true)
    setResult(null)
    try {
      const res = await fetch("/api/mst/duties/auto-schedule", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mst_exam_ids: selected }),
      })
      if (!res.ok) throw new Error("scheduler failed")
      setResult(await res.json())
    } catch {
      toast({ title: "Could not generate proposal", variant: "destructive" })
    } finally {
      setBusy(false)
    }
  }

  const apply = async () => {
    if (!result || result.proposal.length === 0) return
    setApplying(true)
    try {
      const res = await fetch("/api/mst/duties/auto-schedule/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          assignments: result.proposal.map((p) => ({
            mst_exam_id: p.mst_exam_id, room_id: p.room_id, faculty_id: p.faculty_id,
          })),
        }),
      })
      if (!res.ok) throw new Error("apply failed")
      const data = await res.json()
      toast({ title: `Applied ${data.applied} duties`, description: "Review or tweak them in the MST Attendance Tracker." })
      setResult(null)
    } catch {
      toast({ title: "Could not apply proposal", variant: "destructive" })
    } finally {
      setApplying(false)
    }
  }

  const grouped = (result?.proposal ?? []).reduce<Record<string, ProposalRow[]>>((acc, p) => {
    const k = `${p.exam_label} · ${p.exam_date} · ${p.time_slot}`
    ;(acc[k] ||= []).push(p)
    return acc
  }, {})

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex justify-between items-end flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Duty Scheduler</h1>
          <p className="text-muted-foreground mt-2">
            Picks a free teacher for every exam room automatically. Review the proposal, then apply — nothing is saved until you say so.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={generate} disabled={busy}>
            {busy ? "Working…" : "Generate proposal"}
          </Button>
          {result && result.proposal.length > 0 && (
            <Button onClick={apply} disabled={applying}>
              {applying ? "Applying…" : `Apply ${result.proposal.length} duties`}
            </Button>
          )}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>1. Pick exams</CardTitle>
          <CardDescription>Only exams with a date and a time slot like 09:30-12:30 can be scheduled.</CardDescription>
        </CardHeader>
        <CardContent>
          {exams.length === 0 ? (
            <p className="text-sm text-muted-foreground">No exams yet. Create them in the MST Attendance Tracker first.</p>
          ) : (
            <div className="flex flex-col gap-2">
              <div className="flex gap-2 mb-1">
                <Button variant="outline" size="sm" onClick={() => setSelected(exams.map((e) => e.id))}>Select all</Button>
                <Button variant="ghost" size="sm" onClick={() => setSelected([])}>Clear</Button>
              </div>
              {exams.map((e) => (
                <label key={e.id} className="flex items-center gap-3 rounded-md border px-3 py-2 text-sm cursor-pointer hover:bg-muted/50">
                  <Input type="checkbox" className="h-4 w-4 accent-foreground" checked={selected.includes(e.id)} onChange={() => toggle(e.id)} />
                  <span className="font-medium font-mono">{e.label}</span>
                  <span className="text-muted-foreground">{e.exam_date || "no date"}{e.time_slot ? ` · ${e.time_slot}` : " · no slot"}</span>
                  {(!e.exam_date || !e.time_slot) && <Badge variant="secondary">cannot schedule</Badge>}
                </label>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {result && (
        <>
          <div className="grid gap-4 md:grid-cols-3">
            <Card><CardHeader className="pb-2"><CardDescription>Rooms filled</CardDescription><CardTitle className="text-3xl font-mono tabular-nums">{result.stats.rooms_filled}</CardTitle></CardHeader></Card>
            <Card><CardHeader className="pb-2"><CardDescription>Rooms unfilled</CardDescription><CardTitle className="text-3xl font-mono tabular-nums">{result.stats.rooms_unfilled}</CardTitle></CardHeader></Card>
            <Card><CardHeader className="pb-2"><CardDescription>Exams covered</CardDescription><CardTitle className="text-3xl font-mono tabular-nums">{result.stats.exams}</CardTitle></CardHeader></Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>2. Review the proposal</CardTitle>
              <CardDescription>Free = no regular class at that time, no overlapping duty, not exempt, under the daily limit. Ties go to the teacher with the fewest duties so far.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {Object.entries(grouped).map(([examKey, rows]) => (
                <div key={examKey}>
                  <h3 className="font-semibold mb-2 font-mono text-sm">{examKey}</h3>
                  <div className="rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Room</TableHead>
                          <TableHead>Proposed teacher</TableHead>
                          <TableHead>Why</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {rows.map((p) => (
                          <TableRow key={`${p.mst_exam_id}-${p.room_id}`}>
                            <TableCell className="font-medium font-mono">{p.room_number}</TableCell>
                            <TableCell>{p.faculty_name}</TableCell>
                            <TableCell className="text-muted-foreground text-sm">{p.reason}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              ))}
              {result.proposal.length === 0 && (
                <p className="text-sm text-muted-foreground">Nothing proposed — see unfilled rooms below.</p>
              )}
            </CardContent>
          </Card>

          {result.unfilled.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Unfilled rooms</CardTitle>
                <CardDescription>Assign these manually in the tracker — here is why each teacher was skipped.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {result.unfilled.map((u) => (
                  <div key={`${u.mst_exam_id}-${u.room_id}`} className="rounded-md border p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <Badge className="border border-foreground/30 bg-foreground/10 text-foreground">Unfilled</Badge>
                      <span className="font-mono text-sm font-medium">{u.room_number}</span>
                      <span className="text-xs text-muted-foreground">{u.exam_label} · {u.exam_date} · {u.time_slot}</span>
                    </div>
                    <ul className="text-xs text-muted-foreground space-y-1 list-disc pl-5">
                      {u.blockers.map((b, i) => <li key={i}>{b}</li>)}
                    </ul>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {result.skipped_exams.length > 0 && (
            <Card>
              <CardHeader><CardTitle>Skipped exams</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                {result.skipped_exams.map((s) => (
                  <p key={s.mst_exam_id} className="text-sm">
                    <span className="font-mono font-medium">{s.label}</span>
                    <span className="text-muted-foreground"> — {s.reason}</span>
                  </p>
                ))}
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
