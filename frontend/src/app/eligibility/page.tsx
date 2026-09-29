'use client'

import { useState, useEffect } from 'react'
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
import { useToast } from "@/components/ui/use-toast"

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
  const [records, setRecords] = useState<EligibilityRecord[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [overrideModalOpen, setOverrideModalOpen] = useState(false)
  const [selectedRecord, setSelectedRecord] = useState<EligibilityRecord | null>(null)
  const [overrideReason, setOverrideReason] = useState("")
  const { toast } = useToast()

  const fetchRecords = async () => {
    setIsLoading(true)
    try {
      // Hardcoded MST-1 for phase 1 demo
      const res = await fetch('/api/eligibility/1')
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
  }, [])

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
        fetchRecords() // refresh data
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
    if (override) return <Badge className="border-2 border-foreground bg-transparent text-foreground hover:bg-muted">Overridden</Badge>
    if (status === "Eligible") return <Badge className="bg-foreground text-background hover:bg-foreground/85">Eligible</Badge>
    if (status === "Borderline") return <Badge className="border border-dashed border-foreground/60 bg-transparent text-foreground hover:bg-muted">Borderline</Badge>
    if (status === "Not eligible") return <Badge className="border border-foreground/30 bg-foreground/10 text-foreground hover:bg-foreground/15">Not Eligible</Badge>
    return <Badge variant="secondary">Missing</Badge>
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">MST Eligibility</h1>
          <p className="text-muted-foreground mt-2">
            Review eligibility status and manage HOD overrides.
          </p>
        </div>
        <Button variant="outline" onClick={fetchRecords}>Refresh Data</Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Eligibility Roster - MST-1</CardTitle>
          <CardDescription>Based on 50% attendance threshold.</CardDescription>
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
