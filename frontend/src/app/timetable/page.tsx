"use client";
// frontend/src/app/timetable/page.tsx
// Grid-based timetable entry matching the real Acropolis sheet layout:
// days as rows, periods as columns, each cell can hold 1 entry (whole class)
// or 2 (split batch B1/B2, common during labs).

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/use-toast";

const DAYS = ["MON", "TUE", "WED", "THUR", "FRI"];

// Exact period times from the Acropolis timetable sheets (Images 1-5).
// LUNCH is rendered as a non-interactive divider column.
const PERIODS = [
  { label: "10:30-11:20", start: "10:30", end: "11:20" },
  { label: "11:20-12:10", start: "11:20", end: "12:10" },
  { label: "12:10-1:00",  start: "12:10", end: "13:00" },
  { label: "LUNCH",       start: null,    end: null     },
  { label: "1:50-2:40",   start: "13:50", end: "14:40" },
  { label: "2:40-3:30",   start: "14:40", end: "15:30" },
  { label: "3:30-4:15",   start: "15:30", end: "16:15" },
  { label: "4:15-5:00",   start: "16:15", end: "17:00" },
];

type Entry = {
  faculty_id: number;
  faculty_name?: string;
  subject_code: string;
  subject_name?: string;
  room: string;
  batch?: string;  // 'B1' | 'B2' | '' for whole class
};

export default function TimetablePage() {
  const [classes, setClasses]   = useState<any[]>([]);
  const [faculty, setFaculty]   = useState<any[]>([]);
  const [classId, setClassId]   = useState<number | null>(null);
  const [semester, setSemester] = useState("III");
  const [session, setSession]   = useState("Jul-Dec 2026");
  // grid keys: `${day}-${periodIdx}`, value: array of entries (1 = whole class, 2 = B1+B2 split)
  const [grid, setGrid]         = useState<Record<string, Entry[]>>({});
  const [editing, setEditing]   = useState<{ day: string; periodIdx: number } | null>(null);
  const [draft, setDraft]       = useState<Entry>({ faculty_id: 0, subject_code: "", room: "", batch: "" });

  const { toast } = useToast();

  useEffect(() => {
    fetch("/api/classes").then(r => r.json()).then(setClasses).catch(() => {});
    fetch("/api/faculty").then(r => r.json()).then(setFaculty).catch(() => {});
  }, []);

  const cellKey = (day: string, i: number) => `${day}-${i}`;

  function openCell(day: string, periodIdx: number) {
    if (PERIODS[periodIdx].label === "LUNCH") return;
    setEditing({ day, periodIdx });
    setDraft({ faculty_id: 0, subject_code: "", room: "", batch: "" });
  }

  function addEntryToCell() {
    if (!editing || !draft.faculty_id || !draft.subject_code) {
      toast({ title: "Missing fields", description: "Pick a faculty and enter a subject code.", variant: "destructive" });
      return;
    }
    const fac = faculty.find(f => f.id === draft.faculty_id);
    const entryWithName: Entry = { ...draft, faculty_name: fac?.name };
    const k = cellKey(editing.day, editing.periodIdx);
    setGrid(prev => ({ ...prev, [k]: [...(prev[k] || []), entryWithName] }));
    setEditing(null);
  }

  function removeEntry(day: string, periodIdx: number, idx: number) {
    const k = cellKey(day, periodIdx);
    setGrid(prev => ({ ...prev, [k]: prev[k].filter((_, i) => i !== idx) }));
  }

  async function saveAll() {
    if (!classId) {
      toast({ title: "No class selected", description: "Select a class before saving.", variant: "destructive" });
      return;
    }
    const cls = classes.find(c => c.id === classId);

    // Step 1 — create/refresh a timetable version (old data preserved, not overwritten)
    const versionRes = await fetch("/api/timetable/version", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ class_id: classId, semester, session }),
    });
    if (!versionRes.ok) {
      toast({ title: "Version creation failed", description: "Could not create timetable version.", variant: "destructive" });
      return;
    }
    const version = await versionRes.json();

    // Step 2 — flatten grid into bulk entry payload
    const entries: any[] = [];
    for (const day of DAYS) {
      PERIODS.forEach((p, idx) => {
        if (p.label === "LUNCH") return;
        const k = cellKey(day, idx);
        (grid[k] || []).forEach(e => {
          entries.push({
            faculty_id:          e.faculty_id,
            day_of_week:         day,
            period_start:        p.start,
            period_end:          p.end,
            subject_code:        e.subject_code,
            subject_name:        e.subject_name || null,
            room:                e.room || null,
            batch:               e.batch || null,
            class_id:            classId,
            year:                cls?.year,
            semester,
            timetable_version_id: version.id,
          });
        });
      });
    }
    if (entries.length === 0) {
      toast({ title: "Nothing to save", description: "Add some entries to the grid first." });
      return;
    }

    const res = await fetch("/api/timetable/entries/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(entries),
    });
    if (res.ok) {
      toast({ title: "Timetable saved", description: `${entries.length} entries saved successfully.` });
    } else {
      toast({ title: "Save failed", description: "Check the backend log for details.", variant: "destructive" });
    }
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-xl font-semibold">Timetable Input</h1>
      <p className="text-sm text-muted-foreground">
        Enter every class this branch/year has — including years that don&apos;t sit the MST.
        The duty scheduler needs the full picture to block faculty correctly across all
        classes (e.g. a faculty in both CI-1 and CI-2 sheets is blocked in both).
      </p>

      {/* Controls */}
      <div className="flex flex-wrap gap-3 items-center">
        <Select onValueChange={v => setClassId(Number(v))}>
          <SelectTrigger className="w-48">
            <SelectValue placeholder="Select class" />
          </SelectTrigger>
          <SelectContent>
            {classes.map(c => (
              <SelectItem key={c.id} value={String(c.id)}>
                {c.name} (Yr {c.year})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Input
          className="w-24"
          value={semester}
          onChange={e => setSemester(e.target.value)}
          placeholder="Semester"
          title="Semester (e.g. III, V)"
        />
        <Input
          className="w-48"
          value={session}
          onChange={e => setSession(e.target.value)}
          placeholder="Session (e.g. Jul-Dec 2026)"
        />
        <Button onClick={saveAll}>Save timetable</Button>
      </div>

      {/* Timetable grid */}
      <div className="overflow-x-auto border rounded-md">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr>
              <th className="border p-2 bg-muted">Day</th>
              {PERIODS.map(p => (
                <th
                  key={p.label}
                  className={`border p-2 whitespace-nowrap ${
                    p.label === "LUNCH" ? "bg-muted/40 text-muted-foreground" : "bg-muted"
                  }`}
                >
                  {p.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DAYS.map(day => (
              <tr key={day}>
                <td className="border p-2 font-medium bg-muted/50">{day}</td>
                {PERIODS.map((p, idx) => {
                  if (p.label === "LUNCH") {
                    return (
                      <td key={idx} className="border p-2 text-center text-muted-foreground bg-muted/20">
                        —
                      </td>
                    );
                  }
                  const k = cellKey(day, idx);
                  const cellEntries = grid[k] || [];
                  return (
                    <td
                      key={idx}
                      className="border p-1 align-top cursor-pointer hover:bg-accent/40 min-w-[7rem]"
                      onClick={() => openCell(day, idx)}
                    >
                      {cellEntries.length === 0 && (
                        <span className="text-muted-foreground text-base leading-none">+</span>
                      )}
                      {cellEntries.map((e, i) => (
                        <div key={i} className="text-[11px] leading-tight mb-1 flex justify-between gap-1">
                          <span className="truncate">
                            {e.subject_code}
                            {e.batch ? `/${e.batch}` : ""} · {e.faculty_name || `#${e.faculty_id}`} · {e.room}
                          </span>
                          <button
                            onClick={ev => { ev.stopPropagation(); removeEntry(day, idx, i); }}
                            className="text-red-500 shrink-0"
                            title="Remove entry"
                          >
                            ×
                          </button>
                        </div>
                      ))}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Add-entry dialog */}
      <Dialog open={!!editing} onOpenChange={() => setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Add class entry
              {editing && (
                <span className="ml-2 text-sm font-normal text-muted-foreground">
                  {editing.day} · {PERIODS[editing.periodIdx].label}
                </span>
              )}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Select onValueChange={v => setDraft(d => ({ ...d, faculty_id: Number(v) }))}>
              <SelectTrigger><SelectValue placeholder="Faculty" /></SelectTrigger>
              <SelectContent>
                {faculty.map(f => (
                  <SelectItem key={f.id} value={String(f.id)}>
                    {f.name}{f.abbreviation ? ` (${f.abbreviation})` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Input
              placeholder="Subject code (e.g. CSIT-303)"
              value={draft.subject_code}
              onChange={e => setDraft(d => ({ ...d, subject_code: e.target.value }))}
            />
            <Input
              placeholder="Subject name (optional)"
              value={draft.subject_name ?? ""}
              onChange={e => setDraft(d => ({ ...d, subject_name: e.target.value }))}
            />
            <Input
              placeholder="Room / lab (e.g. LR-349)"
              value={draft.room}
              onChange={e => setDraft(d => ({ ...d, room: e.target.value }))}
            />
            <Input
              placeholder="Batch — leave blank for whole class; use B1 or B2 for lab splits"
              value={draft.batch}
              onChange={e => setDraft(d => ({ ...d, batch: e.target.value }))}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
            <Button onClick={addEntryToCell}>Add to cell</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
