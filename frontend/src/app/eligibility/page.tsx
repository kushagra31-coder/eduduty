'use client'

import { useState, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"
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
import { useToast } from "@/components/ui/use-toast"

type Exam = { id: number; label: string }

type EligibilityRecord = {
  id: number
  student_id: number
  roll_number: string
  name: string
  mst_exam_id: number
  overall_pct: number
  lowest_subject_pct: number
  status: string
  override: boolean
  override_reason: string | null
}

export default function EligibilityPage() {
  const [exams, setExams] = useState<Exam[]>([])
  const [examId, setExamId] = useState<number>(1)
  const [records, setRecords] = useState<EligibilityRecord[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [overrideModalOpen, setOverrideModalOpen] = useState(false)
  const [selectedRecord, setSelectedRecord] = useState<EligibilityRecord | null>(null)
  const [overrideReason, setOverrideReason] = useState("")
  const { toast } = useToast()

  // Load exams on mount
  useEffect(() => {
    fetch('/api/mst/exams')
      .then(r => r.ok ? r.json() : [])
      .then((data: Exam[]) => {
        setExams(data)
        if (data.length > 0) setExamId(data[data.length - 1].id) // pick the latest
      })
      .catch(() => {})
  }, [])

  const fetchRecords = async () => {
    setIsLoading(true)
    try {
      const res = await fetch(`/api/eligibility/${examId}`)
      if (res.ok) {
        const data = await res.json()
        setRecords(data)
      }
    } catch (err) {
      console.error("Failed to fetch records", err)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchRecords()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [examId])

  const handleOverrideClick = (record: EligibilityRecord) => {
    setSelectedRecord(record)
    setOverrideReason(record.override_reason || "")
    setOverrideModalOpen(true)
  }

  const submitOverride = async () => {
    if (!selectedRecord || !overrideReason) {
      toast({
        title: "Reason required",
        description: "You must provide a reason for the override.",
        variant: "destructive"
      })
      return
    }

    try {
      const res = await fetch(`/api/eligibility/override/${selectedRecord.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          override: !selectedRecord.override,
          reason: overrideReason
        })
      })

      if (res.ok) {
        toast({ title: "Override updated successfully" })
        setOverrideModalOpen(false)
        fetchRecords()
      } else {
        throw new Error("Failed to update override")
      }
    } catch {
      toast({
        title: "Error",
        description: "Could not update the override status.",
        variant: "destructive"
      })
    }
  }

  const getStatusBadge = (status: string, override: boolean) => {
    if (override) return <Badge className="border-2 border-primary bg-transparent text-primary hover:bg-primary/10">Overridden</Badge>
    if (status === "Eligible") return <Badge className="bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/25">Eligible</Badge>
    if (status === "Borderline") return <Badge className="bg-amber-500/20 text-amber-700 dark:text-amber-400 border-amber-500/30 hover:bg-amber-500/25">Borderline</Badge>
    if (status === "Not eligible") return <Badge className="bg-red-500/20 text-red-700 dark:text-red-400 border-red-500/30 hover:bg-red-500/25">Not Eligible</Badge>
    return <Badge variant="secondary">Missing</Badge>
  }

  const selectedExam = exams.find(e => e.id === examId)

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex justify-between items-end flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">MST Eligibility</h1>
          <p className="text-muted-foreground mt-2">
            Review eligibility status and manage HOD overrides.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {exams.length > 0 && (
            <Select value={String(examId)} onValueChange={v => setExamId(Number(v))}>
              <SelectTrigger className="w-40">
                <SelectValue placeholder="Select exam" />
              </SelectTrigger>
              <SelectContent>
                {exams.map(e => (
                  <SelectItem key={e.id} value={String(e.id)}>{e.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <Button variant="outline" onClick={fetchRecords}>Refresh</Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Eligibility Roster{selectedExam ? ` — ${selectedExam.label}` : ''}</CardTitle>
          <CardDescription>Based on 50% overall attendance threshold. Borderline: 45–49%.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Roll Number</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead className="text-right">Overall %</TableHead>
                  <TableHead className="text-right">Lowest Subject %</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  <TableRow>
                    <TableCell colSpan={6} className="h-24 text-center">Loading...</TableCell>
                  </TableRow>
                ) : records.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="h-24 text-center">No records found. Upload attendance first.</TableCell>
                  </TableRow>
                ) : (
                  records.map((record) => (
                    <TableRow key={record.id} className={record.override ? "bg-muted/60" : ""}>
                      <TableCell className="font-medium font-mono">{record.roll_number}</TableCell>
                      <TableCell>{record.name}</TableCell>
                      <TableCell className="text-right font-mono tabular-nums">{record.overall_pct}%</TableCell>
                      <TableCell className="text-right text-muted-foreground font-mono tabular-nums">{record.lowest_subject_pct}%</TableCell>
                      <TableCell>{getStatusBadge(record.status, record.override)}</TableCell>
                      <TableCell className="text-right">
                        <Button 
                          variant="ghost" 
                          size="sm"
                          onClick={() => handleOverrideClick(record)}
                        >
                          {record.override ? "Edit Override" : "Override"}
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

      <Dialog open={overrideModalOpen} onOpenChange={setOverrideModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {selectedRecord?.override ? "Remove or Edit Override" : "Override Eligibility"}
            </DialogTitle>
            <DialogDescription>
              Action for student: {selectedRecord?.name} ({selectedRecord?.roll_number})
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="reason">Reason for override</Label>
              <Input 
                id="reason" 
                value={overrideReason} 
                onChange={(e) => setOverrideReason(e.target.value)} 
                placeholder="e.g. Medical leave approved by HOD" 
              />
              <p className="text-xs text-muted-foreground">
                This reason will be logged in the audit trail.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOverrideModalOpen(false)}>Cancel</Button>
            <Button onClick={submitOverride}>Save changes</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
