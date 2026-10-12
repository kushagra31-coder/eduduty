'use client'

import { useState, useCallback, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { UploadCloud, CheckCircle, AlertTriangle } from "lucide-react"
import { useToast } from "@/components/ui/use-toast"

interface ClassItem {
  id: number
  name: string
  branch: string
  year: number
  section?: string | null
}

export default function AttendanceUpload() {
  const [classes, setClasses] = useState<ClassItem[]>([])
  const [selectedClassId, setSelectedClassId] = useState<string>("")
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
  const { toast } = useToast()

  useEffect(() => {
    fetch('/api/classes')
      .then(res => res.ok ? res.json() : [])
      .then((data: ClassItem[]) => setClasses(data))
      .catch(() => {})
  }, [])

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
        toast({
          title: "Invalid file type",
          description: "Please upload an Excel (.xlsx or .xls) file.",
          variant: "destructive"
        })
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

    setIsUploading(true)
    const formData = new FormData()
    formData.append('file', file)
    if (selectedClassId) {
      formData.append('class_id', selectedClassId)
    }

    try {
      const res = await fetch('/api/upload-attendance/', {
        method: 'POST',
        body: formData,
      })

      const data = await res.json().catch(() => null)

      if (!res.ok) {
        const detail = data?.detail ?? `Server returned status ${res.status}`
        toast({
          title: "Upload Failed",
          description: detail,
          variant: "destructive"
        })
        return
      }

      setUploadResult(data)
      const skipped = (data.sheets ?? []).filter((s: { status: string }) => s.status !== 'imported')
      toast({
        title: "Upload Successful",
        description: `Imported ${data.rows_imported} records` +
          (data.subjects_imported ? ` across ${data.subjects_imported} subjects` : '') +
          ` from ${data.filename}` +
          (skipped.length ? ` (${skipped.length} sheet${skipped.length > 1 ? 's' : ''} skipped)` : ''),
      })
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

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Upload Attendance</h1>
        <p className="text-muted-foreground mt-2">
          Import Excel sheets to compute student eligibility automatically.
        </p>
      </div>

      <div className="max-w-2xl">
        <Card>
          <CardHeader>
            <CardTitle>Attendance Importer</CardTitle>
            <CardDescription>Drag and drop your Excel file here or click to browse.</CardDescription>
          </CardHeader>
          <CardContent>
            {!uploadResult ? (
              <div className="space-y-5">
                <div className="space-y-1.5">
                  <label htmlFor="class-select" className="text-sm font-medium">
                    Target Class <span className="text-muted-foreground font-normal text-xs">(required for flat rosters; pre-selected from filename)</span>
                  </label>
                  <div className="flex items-center gap-3">
                    <Select value={selectedClassId} onValueChange={(val) => setSelectedClassId(val || "")}>
                      <SelectTrigger id="class-select" className="w-full sm:w-80">
                        <SelectValue placeholder="Select class..." />
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
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => setSelectedClassId("")}
                        className="text-xs text-muted-foreground hover:text-foreground"
                      >
                        Clear
                      </Button>
                    )}
                  </div>
                </div>

                <div 
                  className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors cursor-pointer ${
                    isDragging ? 'border-primary bg-primary/5' : 'border-border hover:bg-accent hover:border-primary/50'
                  }`}
                  onDragEnter={handleDrag}
                  onDragLeave={handleDrag}
                  onDragOver={handleDrag}
                  onDrop={handleDrop}
                  onClick={() => document.getElementById('file-upload')?.click()}
                >
                  <input 
                    id="file-upload" 
                    type="file" 
                    className="hidden" 
                    accept=".xlsx, .xls"
                    onChange={handleFileChange}
                  />
                  <div className="flex flex-col items-center justify-center space-y-4">
                    <div className="p-4 bg-primary/10 rounded-full">
                      <UploadCloud className="h-8 w-8 text-primary" />
                    </div>
                    <div>
                      <p className="font-semibold text-lg">
                        {file ? file.name : "Click or drag file to this area to upload"}
                      </p>
                      <p className="text-sm text-muted-foreground mt-1">
                        Support for a single .xlsx or .xls file.
                      </p>
                    </div>
                  </div>
                </div>

                <div className="flex justify-end">
                  <Button 
                    onClick={handleUpload} 
                    disabled={!file || isUploading}
                    className="w-full sm:w-auto"
                  >
                    {isUploading ? "Uploading..." : "Upload File"}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="border rounded-lg p-8 text-center space-y-4 bg-muted/50">
                <div className="flex justify-center">
                  <CheckCircle className="h-12 w-12 text-foreground" />
                </div>
                <h3 className="text-xl font-semibold">Upload Complete</h3>
                <p className="text-muted-foreground">
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
                      <span>Class Mismatch Warnings ({uploadResult.class_conflicts.length} student{uploadResult.class_conflicts.length > 1 ? 's' : ''})</span>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      The following students already belong to a different class and were kept in their original class:
                    </p>
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
                      {uploadResult.sheets.filter(s => s.status !== 'imported').length} sheet(s) skipped — details
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
                <div className="pt-4">
                  <Button onClick={() => {
                    setFile(null)
                    setUploadResult(null)
                  }} variant="outline">
                    Upload Another File
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
