"use client"

import Link from 'next/link';
import { Home, Upload, CheckSquare, Settings, Sun, Moon, Bot, CalendarDays } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTheme } from 'next-themes';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';

export function Sidebar({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <div className={cn("pb-12 border-r bg-background min-h-screen flex flex-col", className)}>
      <div className="space-y-4 py-4 flex-1">
        <div className="px-3 py-2">
          <h2 className="mb-2 px-4 text-lg font-semibold tracking-tight">
            MST Operations
          </h2>
          <div className="space-y-1">
            <Link href="/dashboard" className="w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground transition-colors">
              <Home className="h-4 w-4" />
              Dashboard
            </Link>
            <Link href="/attendance/upload" className="w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground transition-colors">
              <Upload className="h-4 w-4" />
              Upload Attendance
            </Link>
            <Link href="/eligibility" className="w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground transition-colors">
              <CheckSquare className="h-4 w-4" />
              Eligibility
            </Link>
            <Link href="/ai" className="w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground transition-colors">
              <Bot className="h-4 w-4" />
              AI Assistant
            </Link>
            <Link href="/timetable" className="w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground transition-colors">
              <CalendarDays className="h-4 w-4" />
              Timetable
            </Link>
            <Link href="/settings" className="w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground transition-colors">
              <Settings className="h-4 w-4" />
              Settings
            </Link>
          </div>
        </div>
      </div>
      
      <div className="p-4 border-t">
        {mounted && (
          <Button 
            variant="outline" 
            className="w-full justify-start gap-2" 
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          >
            {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            Toggle Theme
          </Button>
        )}
      </div>
    </div>
  );
}
