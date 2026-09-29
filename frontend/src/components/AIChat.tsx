'use client'

import { useState, useRef, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Send, Bot, User, Loader2, FileText, AlertTriangle, ExternalLink } from 'lucide-react'
import { useToast } from '@/components/ui/use-toast'

type MessageRole = 'user' | 'assistant' | 'error'

interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  type?: 'answer' | 'write_proposal' | 'pdf_link' | 'error'
  opJson?: Record<string, string>
  pdfLink?: string
}

const WRITE_OP_LABELS: Record<string, string> = {
  override_eligibility:  'Override Eligibility',
  mark_attempt_status:   'Mark Exam Attempt',
  assign_duty:           'Assign Invigilation Duty',
}

function WriteProposalCard({ opJson, onConfirm, onDismiss }: {
  opJson: Record<string, string>
  onConfirm: () => void
  onDismiss: () => void
}) {
  const label = WRITE_OP_LABELS[opJson.operation] ?? opJson.operation
  return (
    <div className="rounded-xl border-2 border-foreground bg-muted/40 p-4 space-y-3 max-w-sm">
      <div className="flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-foreground flex-shrink-0" />
        <span className="font-semibold text-sm text-foreground">Proposed Write: {label}</span>
      </div>
      <div className="text-xs space-y-1 text-muted-foreground">
        {Object.entries(opJson)
          .filter(([k]) => k !== 'operation')
          .map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <span className="font-medium capitalize w-28 shrink-0">{k.replace(/_/g, ' ')}:</span>
              <span>{v}</span>
            </div>
          ))}
      </div>
      <p className="text-xs text-muted-foreground">
        This change will be logged in the audit trail.
      </p>
      <div className="flex gap-2 pt-1">
        <Button size="sm" onClick={onConfirm}>
          Confirm
        </Button>
        <Button size="sm" variant="outline" onClick={onDismiss}>
          Dismiss
        </Button>
      </div>
    </div>
  )
}

function PDFLinkCard({ link, message }: { link: string; message: string }) {
  const fullUrl = `/api${link}`
  return (
    <div className="rounded-xl border border-foreground/30 bg-muted/30 p-4 space-y-2 max-w-sm">
      <div className="flex items-center gap-2">
        <FileText className="h-4 w-4 text-foreground" />
        <span className="font-semibold text-sm text-foreground">PDF Ready</span>
      </div>
      <p className="text-xs text-muted-foreground">{message}</p>
      <a href={fullUrl} target="_blank" rel="noreferrer">
        <Button size="sm" variant="outline" className="gap-2 mt-1">
          <ExternalLink className="h-3 w-3" />
          Open PDF
        </Button>
      </a>
    </div>
  )
}

export function AIChat() {
  const [messages, setMessages]     = useState<ChatMessage[]>([
    {
      id: '0',
      role: 'assistant',
      type: 'answer',
      content: "Hi! I'm your MST assistant. Ask me anything — eligibility counts, VT candidates, attendance breakdowns — or say things like \"override roll 2301 for MST-1, medical leave\" or \"PDF for roll 2301\".",
    },
  ])
  const [input, setInput]           = useState('')
  const [loading, setLoading]       = useState(false)
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false)
  const [pendingOp, setPendingOp]   = useState<{ msgId: string; opJson: Record<string, string> } | null>(null)
  const bottomRef                   = useRef<HTMLDivElement>(null)
  const { toast }                   = useToast()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = async () => {
    const text = input.trim()
    if (!text || loading) return

    const userMsg: ChatMessage = { id: Date.now().toString(), role: 'user', content: text }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const res = await fetch('/api/ai/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      })
      const data = await res.json().catch(() => null)

      if (!res.ok) {
        // HTTP error from the backend — surface its detail, don't pretend it's a network failure.
        setMessages(prev => [...prev, {
          id: (Date.now() + 1).toString(),
          role: 'error',
          type: 'error',
          content: `Request failed (HTTP ${res.status}): ${data?.detail ?? 'the AI backend returned an error.'}`,
        }])
        return
      }

      if (data.type === 'write_proposal') {
        const msgId = (Date.now() + 1).toString()
        const botMsg: ChatMessage = {
          id: msgId,
          role: 'assistant',
          type: 'write_proposal',
          content: 'I can make this change for you. Please review and confirm:',
          opJson: data.content,
        }
        setMessages(prev => [...prev, botMsg])
      } else if (data.type === 'pdf_link') {
        const botMsg: ChatMessage = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          type: 'pdf_link',
          content: data.message ?? 'Here is the PDF link.',
          pdfLink: data.content,
        }
        setMessages(prev => [...prev, botMsg])
      } else if (data.type === 'error') {
        const botMsg: ChatMessage = {
          id: (Date.now() + 1).toString(),
          role: 'error',
          type: 'error',
          content: data.content,
        }
        setMessages(prev => [...prev, botMsg])
      } else {
        const botMsg: ChatMessage = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          type: 'answer',
          content: data.content,
        }
        setMessages(prev => [...prev, botMsg])
      }
    } catch (e) {
      // fetch() threw — network failure, not an HTTP error from the backend.
      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        role: 'error',
        content: e instanceof TypeError
          ? 'Could not reach the backend. Is the FastAPI server running on port 8000?'
          : `Request failed: ${e instanceof Error ? e.message : String(e)}`,
      }])
    } finally {
      setLoading(false)
    }
  }

  const handleConfirmWrite = (msgId: string, opJson: Record<string, string>) => {
    setPendingOp({ msgId, opJson })
    setConfirmDialogOpen(true)
  }

  const executeConfirmedWrite = async () => {
    if (!pendingOp) return
    setConfirmDialogOpen(false)
    setLoading(true)
    try {
      const res = await fetch('/api/ai/confirm-write', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ op_json: pendingOp.opJson }),
      })
      const data = await res.json().catch(() => null)
      if (!res.ok) {
        throw new Error(data?.detail ?? `Server returned status ${res.status}`)
      }
      if (data.success) {
        toast({ title: 'Change applied', description: `${data.changed?.changed ?? 'Operation'} completed successfully.` })
        setMessages(prev => [...prev, {
          id: Date.now().toString(),
          role: 'assistant',
          type: 'answer',
          content: `Done — the change has been applied and logged to the audit trail.`,
        }])
      } else {
        throw new Error(data.detail ?? 'Unknown error')
      }
    } catch (e) {
      toast({ title: 'Write failed', description: e instanceof Error ? e.message : String(e), variant: 'destructive' })
    } finally {
      setLoading(false)
      setPendingOp(null)
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)] max-h-[800px]">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-2 pb-4">
        {messages.map(msg => (
          <div
            key={msg.id}
            className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {msg.role !== 'user' && (
              <div className="shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center mt-1">
                <Bot className="h-4 w-4 text-primary" />
              </div>
            )}

            <div className={`max-w-[80%] space-y-2`}>
              {msg.content && (
                <div className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                  msg.role === 'user'
                    ? 'bg-primary text-primary-foreground rounded-tr-sm'
                    : msg.role === 'error'
                    ? 'bg-destructive/10 text-destructive rounded-tl-sm border border-destructive/20'
                    : 'bg-muted rounded-tl-sm'
                }`}>
                  {msg.content}
                </div>
              )}

              {msg.type === 'write_proposal' && msg.opJson && (
                <WriteProposalCard
                  opJson={msg.opJson}
                  onConfirm={() => handleConfirmWrite(msg.id, msg.opJson!)}
                  onDismiss={() => toast({ title: 'Dismissed', description: 'No changes were made.' })}
                />
              )}

              {msg.type === 'pdf_link' && msg.pdfLink && (
                <PDFLinkCard link={msg.pdfLink} message={msg.content} />
              )}
            </div>

            {msg.role === 'user' && (
              <div className="shrink-0 w-8 h-8 rounded-full bg-secondary flex items-center justify-center mt-1">
                <User className="h-4 w-4 text-secondary-foreground" />
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="flex gap-3 justify-start">
            <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
              <Bot className="h-4 w-4 text-primary" />
            </div>
            <div className="bg-muted rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
              <span className="text-sm text-muted-foreground">Thinking…</span>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="border-t pt-4">
        <div className="flex gap-2">
          <Input
            id="ai-chat-input"
            placeholder="Ask a question or give an instruction…"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() } }}
            disabled={loading}
            className="flex-1"
          />
          <Button onClick={sendMessage} disabled={loading || !input.trim()} size="icon">
            <Send className="h-4 w-4" />
          </Button>
        </div>
        <p className="text-xs text-muted-foreground mt-2">
          All AI-proposed writes require your confirmation before being applied.
        </p>
      </div>

      {/* Confirm write dialog */}
      <Dialog open={confirmDialogOpen} onOpenChange={setConfirmDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-foreground" />
              Confirm Database Change
            </DialogTitle>
            <DialogDescription>
              This action will be permanently logged in the audit trail with your identity.
            </DialogDescription>
          </DialogHeader>
          {pendingOp && (
            <div className="space-y-2 py-2 text-sm">
              <p className="font-medium">Operation: <Badge variant="secondary">{WRITE_OP_LABELS[pendingOp.opJson.operation] ?? pendingOp.opJson.operation}</Badge></p>
              {Object.entries(pendingOp.opJson)
                .filter(([k]) => k !== 'operation')
                .map(([k, v]) => (
                  <div key={k} className="flex gap-2">
                    <span className="text-muted-foreground capitalize w-32">{k.replace(/_/g, ' ')}:</span>
                    <span className="font-medium">{v}</span>
                  </div>
                ))}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDialogOpen(false)}>Cancel</Button>
            <Button onClick={executeConfirmedWrite}>
              Apply Change
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
