'use client'

import { useState, useCallback } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { UploadCloud, CheckCircle } from "lucide-react"
import { useToast } from "@/components/ui/use-toast"

export default function AttendanceUpload() {
  const [isDragging, setIsDragging] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<{
    filename: string
    rows_imported: number
    subjects_imported?: number
    class?: string
    sheets?: { sheet: string; status: string; reason?: string; subject?: string; rows?: number }[]
  } | null>(null)
  const { toast } = useToast()

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
      } else {
        toast({
          title: "Invalid file type",
          description: "Please upload an Excel (.xlsx or .xls) file.",
          variant: "destructive"
        })
      }
    }
  }, [toast])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0])
    }
  }

  const handleUpload = async () => {
    if (!file) return

    setIsUploading(true)
    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch('/api/upload-attendance/', {
        method: 'POST',
        body: formData,
      })

      const data = await res.json().catch(() => null)

      if (!res.ok) {
        // HTTP error from the backend (e.g. 400 "no subject sheets recognized") —
        // show FastAPI's actual detail instead of a generic message.
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
        description: `Imported ${data.rows_imported} records across ${data.subjects_imported} subjects from ${data.filename}` +
          (skipped.length ? ` (${skipped.length} sheet${skipped.length > 1 ? 's' : ''} skipped)` : ''),
      })
    } catch (e) {
      // fetch() itself threw — network failure, backend unreachable.
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
              <div className="space-y-4">
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
