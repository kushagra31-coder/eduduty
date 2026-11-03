'use client'

import { useState, useCallback, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { UploadCloud, CheckCircle, AlertTriangle, Trash2, Database, RefreshCw, Tag } from "lucide-react"
import { useToast } from "@/components/ui/use-toast"

interface ClassItem {
  id: number
  name: string
  branch: string
  year: number
  section?: string | null
}

interface BatchItem {
  label: string
  record_count: number
  first_upload: string | null
  last_upload: string | null
  is_named: boolean
}

const SUGGESTED_LABELS = [
  "CI-1 MST-1", "CI-1 MST-2",
  "CI-2 MST-1", "CI-2 MST-2",
  "CY MST-1", "CY MST-2",
  "CI-1 Sem3", "CI-1 Sem5", "CI-2 Sem3", "CI-2 Sem5", "CY Sem3", "CY Sem5",
]

export default function AttendanceUpload() {
  const [classes, setClasses] = useState<ClassItem[]>([])
  const [selectedClassId, setSelectedClassId] = useState<string>("")
  const [batchLabel, setBatchLabel] = useState<string>("")
  const [isDragging, setIsDragging] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<{
    filename: string
    rows_imported: number
    subjects_imported?: number
    class?: string
    sheets?: { sheet: string; status: string; reason?: string; subject?: string; rows?: number }[]
    class_conflicts?: { roll_number: string; name: string; existing_class: string; imported_class: string }[]
  } | null>(null)

  // Batch management
  const [batches, setBatches] = useState<BatchItem[]>([])
  const [batchesLoading, setBatchesLoading] = useState(false)
  const [deletingBatch, setDeletingBatch] = useState<string | null>(null)

  const { toast } = useToast()

  useEffect(() => {
    fetch('/api/classes')
      .then(res => res.ok ? res.json() : [])
      .then((data: ClassItem[]) => setClasses(data))
      .catch(() => {})
    loadBatches()
  }, [])

  const loadBatches = async () => {
    setBatchesLoading(true)
    try {
      const res = await fetch('/api/import-batches')
      if (res.ok) {
        const data = await res.json()
        setBatches(data)
      }
    } catch {}
    finally { setBatchesLoading(false) }
  }

  const preselectClassFromFilename = useCallback((fileName: string, classList: ClassItem[]) => {
    const cleanFileName = fileName.toUpperCase().replace(/[_\-\s.]+/g, '')
    for (const c of classList) {
      const cleanClassName = c.name.toUpperCase().replace(/[_\-\s.]+/g, '')
      if (cleanClassName && cleanFileName.includes(cleanClassName)) {
        return String(c.id)
      }
    }
    return null
  }, [])

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === "dragenter" || e.type === "dragover") {
      setIsDragging(true)
    } else if (e.type === "dragleave") {
      setIsDragging(false)
    }
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const droppedFile = e.dataTransfer.files[0]
      if (droppedFile.name.endsWith('.xlsx') || droppedFile.name.endsWith('.xls')) {
        setFile(droppedFile)
        const matched = preselectClassFromFilename(droppedFile.name, classes)
        if (matched) setSelectedClassId(matched)
      } else {
        toast({ title: "Invalid file type", description: "Please upload an Excel (.xlsx or .xls) file.", variant: "destructive" })
      }
    }
  }, [classes, preselectClassFromFilename, toast])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selected = e.target.files[0]
      setFile(selected)
      const matched = preselectClassFromFilename(selected.name, classes)
      if (matched) setSelectedClassId(matched)
    }
  }

  const handleUpload = async () => {
    if (!file) return
    if (!batchLabel.trim()) {
      toast({ title: "Batch label required", description: "Please enter a batch label (e.g. 'CI-1 MST-1') to identify this dataset.", variant: "destructive" })
      return
    }

    setIsUploading(true)
    const formData = new FormData()
    formData.append('file', file)
    formData.append('batch_label', batchLabel.trim())
    if (selectedClassId) {
      formData.append('class_id', selectedClassId)
    }

    try {
      const res = await fetch('/api/upload-attendance', { method: 'POST', body: formData })
      const data = await res.json().catch(() => null)

      if (!res.ok) {
        toast({ title: "Upload Failed", description: data?.detail ?? `Server returned status ${res.status}`, variant: "destructive" })
        return
      }

      setUploadResult(data)
      const skipped = (data.sheets ?? []).filter((s: { status: string }) => s.status !== 'imported')
      toast({
        title: `Upload Successful — Batch: ${batchLabel}`,
        description: `Imported ${data.rows_imported} records` +
          (data.subjects_imported ? ` across ${data.subjects_imported} subjects` : '') +
          ` from ${data.filename}` +
          (skipped.length ? ` (${skipped.length} sheet${skipped.length > 1 ? 's' : ''} skipped)` : ''),
      })
      loadBatches()
    } catch (e) {
      toast({
        title: "Upload Failed",
        description: e instanceof TypeError
          ? "Could not reach the backend. Is the FastAPI server running on port 8000?"
          : (e instanceof Error ? e.message : "There was an error communicating with the server."),
        variant: "destructive"
      })
    } finally {
      setIsUploading(false)
    }
  }

  const handleDeleteBatch = async (label: string) => {
    if (!confirm(`Delete all attendance records for batch "${label}"? This will recompute eligibility.`)) return
    setDeletingBatch(label)
    try {
      const res = await fetch(`/api/import-batches/${encodeURIComponent(label)}`, { method: 'DELETE' })
      const data = await res.json().catch(() => null)
      if (!res.ok) {
        toast({ title: "Delete Failed", description: data?.detail ?? "Could not delete batch.", variant: "destructive" })
        return
      }
      toast({ title: `Batch "${label}" deleted`, description: `${data.deleted} records removed. Eligibility recomputed for ${data.affected_students} students.` })
      loadBatches()
    } catch {
      toast({ title: "Delete Failed", description: "Network error.", variant: "destructive" })
    } finally {
      setDeletingBatch(null)
    }
  }

  const [resetting, setResetting] = useState(false)

  const handleResetToFresh = async () => {
    if (!confirm("Reset database to clean fresh state? This will wipe legacy/dummy student data and keep clean CI-1, CI-2, CY (Cyber Security) classes ready for your upload.")) return
    setResetting(true)
    try {
      const res = await fetch('/api/data/reset', { method: 'POST' })
      const data = await res.json().catch(() => null)
      if (res.ok) {
        toast({
          title: "Clean Slate Initialized",
          description: "Classes CI-1, CI-2, CY (Cyber Security) are ready. All legacy cache has been removed.",
        })
        setUploadResult(null)
        setFile(null)
        loadBatches()
        fetch('/api/classes')
          .then(r => r.ok ? r.json() : [])
          .then(setClasses)
      } else {
        toast({ title: "Reset Failed", description: data?.detail ?? "Could not reset data.", variant: "destructive" })
      }
    } catch {
      toast({ title: "Reset Failed", description: "Network error.", variant: "destructive" })
    } finally {
      setResetting(false)
    }
  }

  return (
    <div className="space-y-6 animate-in pb-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Upload Attendance</h1>
        <p className="text-muted-foreground mt-2">
          Import Excel sheets to compute student eligibility. Tag each import with a <strong>Batch Label</strong> so datasets stay separate and can be cleared individually.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        {/* Upload Card */}
        <div className="lg:col-span-3">
          <Card>
            <CardHeader>
              <CardTitle>Attendance Importer</CardTitle>
              <CardDescription>Tag this import with a batch label, then drag &amp; drop your Excel file.</CardDescription>
            </CardHeader>
            <CardContent>
              {!uploadResult ? (
                <div className="space-y-5">
                  {/* Batch Label */}
                  <div className="space-y-2">
                    <label htmlFor="batch-label" className="text-sm font-semibold flex items-center gap-1.5">
                      <Tag className="h-3.5 w-3.5 text-primary" />
                      Batch Label <span className="text-destructive">*</span>
                    </label>
                    <Input
                      id="batch-label"
                      placeholder="e.g. CI-1 MST-1, CI-2 Sem5, CY MST-2 …"
                      value={batchLabel}
                      onChange={e => setBatchLabel(e.target.value)}
                      className="font-medium"
                    />
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {SUGGESTED_LABELS.map(lbl => (
                        <button
                          key={lbl}
                          type="button"
                          onClick={() => setBatchLabel(lbl)}
                          className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${
                            batchLabel === lbl
                              ? 'bg-primary text-primary-foreground border-primary'
                              : 'border-border text-muted-foreground hover:bg-accent hover:text-foreground'
                          }`}
                        >
                          {lbl}
                        </button>
                      ))}
                    </div>
                    <p className="text-[11px] text-muted-foreground">
                      This label identifies the dataset. Use the same label to overwrite it, or a new label to keep them separate.
                    </p>
                  </div>

                  {/* Class Select */}
                  <div className="space-y-1.5">
                    <label htmlFor="class-select" className="text-sm font-medium">
                      Target Class <span className="text-muted-foreground font-normal text-xs">(optional for multi-subject workbooks)</span>
                    </label>
                    <div className="flex items-center gap-3">
                      <Select value={selectedClassId} onValueChange={(val) => setSelectedClassId(val || "")}>
                        <SelectTrigger id="class-select" className="w-full sm:w-80">
                          <SelectValue placeholder="Select class…" />
                        </SelectTrigger>
                        <SelectContent>
                          {classes.map((c) => (
                            <SelectItem key={c.id} value={String(c.id)}>
                              {c.name} · Year {c.year} ({c.branch})
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {selectedClassId && (
                        <Button type="button" variant="ghost" size="sm"
                          onClick={() => setSelectedClassId("")}
                          className="text-xs text-muted-foreground">
                          Clear
                        </Button>
                      )}
                    </div>
                  </div>

                  {/* Drop zone */}
                  <div
                    className={`border-2 border-dashed rounded-xl p-10 text-center transition-all cursor-pointer ${
                      isDragging ? 'border-primary bg-primary/8 scale-[1.01]' : 'border-border hover:bg-accent hover:border-primary/50'
                    }`}
                    onDragEnter={handleDrag} onDragLeave={handleDrag}
                    onDragOver={handleDrag} onDrop={handleDrop}
                    onClick={() => document.getElementById('file-upload')?.click()}
                  >
                    <input id="file-upload" type="file" className="hidden" accept=".xlsx, .xls" onChange={handleFileChange} />
                    <div className="flex flex-col items-center space-y-3">
                      <div className="p-4 bg-primary/10 rounded-full">
                        <UploadCloud className="h-8 w-8 text-primary" />
                      </div>
                      <div>
                        <p className="font-semibold text-base">
                          {file ? file.name : "Click or drag Excel file here"}
                        </p>
                        <p className="text-xs text-muted-foreground mt-1">Supports .xlsx and .xls files</p>
                      </div>
                    </div>
                  </div>

                  <Button
                    onClick={handleUpload}
                    disabled={!file || isUploading}
                    className="w-full"
                  >
                    {isUploading ? "Uploading…" : `Upload as "${batchLabel || 'unnamed'}"` }
                  </Button>
                </div>
              ) : (
                <div className="border rounded-xl p-8 text-center space-y-4 bg-muted/50">
                  <CheckCircle className="h-12 w-12 text-emerald-500 mx-auto" />
                  <h3 className="text-xl font-semibold">Upload Complete</h3>
                  <p className="text-muted-foreground text-sm">
                    Successfully imported <span className="font-bold text-foreground">{uploadResult.rows_imported}</span> records
                    {uploadResult.subjects_imported != null && (
                      <> across <span className="font-bold text-foreground">{uploadResult.subjects_imported}</span> subjects</>
                    )}
                    {uploadResult.class && (
                      <> for class <span className="font-bold text-foreground">{uploadResult.class}</span></>
                    )}{' '}
                    from {uploadResult.filename}.
                  </p>

                  {uploadResult.class_conflicts && uploadResult.class_conflicts.length > 0 && (
                    <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-left space-y-2">
                      <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400 font-semibold text-sm">
                        <AlertTriangle className="h-4 w-4" />
                        <span>Class Mismatch Warnings ({uploadResult.class_conflicts.length})</span>
                      </div>
                      <ul className="text-xs space-y-1 max-h-36 overflow-y-auto">
                        {uploadResult.class_conflicts.map((c, idx) => (
                          <li key={idx} className="flex justify-between py-1 border-b border-border/50 last:border-0">
                            <span className="font-mono font-medium">{c.roll_number} ({c.name})</span>
                            <span className="text-muted-foreground">Original: {c.existing_class} · Sheet: {c.imported_class}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {uploadResult.sheets && uploadResult.sheets.some(s => s.status !== 'imported') && (
                    <details className="text-left text-sm mt-2">
                      <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                        {uploadResult.sheets.filter(s => s.status !== 'imported').length} sheet(s) skipped
                      </summary>
                      <ul className="mt-2 space-y-1">
                        {uploadResult.sheets.filter(s => s.status !== 'imported').map(s => (
                          <li key={s.sheet} className="text-muted-foreground">
                            <span className="font-medium text-foreground">{s.sheet}</span>: {s.reason ?? s.status}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}

                  <Button onClick={() => { setFile(null); setUploadResult(null) }} variant="outline">
                    Upload Another File
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Batch Manager */}
        <div className="lg:col-span-2">
          <Card className="h-full">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    <Database className="h-4 w-4 text-primary" />
                    Import Batches
                  </CardTitle>
                  <CardDescription className="text-xs mt-0.5">All uploaded datasets</CardDescription>
                </div>
                <Button variant="ghost" size="sm" onClick={loadBatches} disabled={batchesLoading} className="h-8 w-8 p-0">
                  <RefreshCw className={`h-3.5 w-3.5 ${batchesLoading ? 'animate-spin' : ''}`} />
                </Button>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {batches.length === 0 ? (
                <div className="px-5 py-10 text-center text-xs text-muted-foreground">
                  No import batches yet. Upload your first Excel file to get started.
                </div>
              ) : (
                <div className="divide-y divide-border/40">
                  {batches.map((b) => (
                    <div key={b.label} className="flex items-center justify-between px-5 py-3 hover:bg-muted/20 transition-colors">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold text-foreground truncate">{b.label}</span>
                          {b.is_named ? (
                            <Badge variant="outline" className="text-[10px] border-primary/30 text-primary px-1.5 py-0">Named</Badge>
                          ) : (
                            <Badge variant="outline" className="text-[10px] text-muted-foreground px-1.5 py-0">File</Badge>
                          )}
                        </div>
                        <p className="text-[11px] text-muted-foreground mt-0.5">
                          {b.record_count.toLocaleString()} records
                          {b.last_upload ? ` · ${new Date(b.last_upload).toLocaleDateString('en-IN')}` : ''}
                        </p>
                      </div>
                      {b.is_named && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive hover:bg-destructive/10 shrink-0"
                          onClick={() => handleDeleteBatch(b.label)}
                          disabled={deletingBatch === b.label}
                          title={`Delete batch "${b.label}"`}
                        >
                          {deletingBatch === b.label
                            ? <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                            : <Trash2 className="h-3.5 w-3.5" />}
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
            <div className="p-4 border-t bg-muted/10 space-y-2">
              <div className="text-[11px] text-muted-foreground flex items-center justify-between">
                <span>Start from scratch?</span>
                <span className="font-semibold text-primary">CI-1 · CI-2 · CY</span>
              </div>
              <Button
                variant="outline"
                size="sm"
                className="w-full text-xs gap-1.5 border-destructive/30 text-destructive hover:bg-destructive/10 hover:border-destructive"
                onClick={handleResetToFresh}
                disabled={resetting}
              >
                {resetting ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                Reset All &amp; Clean Slate
              </Button>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
