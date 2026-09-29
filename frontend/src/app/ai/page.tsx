import { AIChat } from '@/components/AIChat'
import { Bot, Cpu, Lock } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'

export default function AIPage() {
  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <Bot className="h-8 w-8 text-primary" />
            AI Assistant
          </h1>
          <p className="text-muted-foreground mt-2">
            Ask questions about attendance, eligibility, or duty rosters in plain English. 
            Propose changes — all writes require your confirmation.
          </p>
        </div>
      </div>

      {/* Capability chips */}
      <div className="flex flex-wrap gap-2 text-xs">
        {[
          { icon: <Cpu className="h-3 w-3" />, label: 'Runs locally via Ollama' },
          { icon: <Lock className="h-3 w-3" />, label: 'Data never leaves your server' },
          { icon: <Lock className="h-3 w-3" />, label: 'Writes need human confirmation' },
        ].map(chip => (
          <div key={chip.label} className="flex items-center gap-1.5 rounded-full border bg-secondary/60 px-3 py-1 text-muted-foreground">
            {chip.icon}
            {chip.label}
          </div>
        ))}
      </div>

      {/* Example prompts */}
      <Card className="bg-muted/30 border-dashed">
        <CardContent className="pt-4 pb-3">
          <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">Example prompts</p>
          <div className="flex flex-wrap gap-2 text-xs">
            {[
              'How many CI-1 students are eligible for MST-1?',
              'List borderline students in CI-2',
              'Who are the VT candidates after MST-2?',
              'Override roll 2301 for MST-1, medical leave',
              'Mark roll 1042 as Absent for MST-2',
              'PDF for roll 2301',
            ].map(prompt => (
              <span key={prompt} className="rounded-md bg-background border px-2 py-1 text-muted-foreground hover:text-foreground hover:border-primary/50 cursor-pointer transition-colors">
                {prompt}
              </span>
            ))}
          </div>
        </CardContent>
      </Card>

      <AIChat />
    </div>
  )
}
