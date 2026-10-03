"use client"

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Home, Upload, CheckSquare, Settings, Sun, Moon, Bot, CalendarDays, Armchair, ClipboardList, Users, ClipboardCheck } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTheme } from 'next-themes';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';

const NAV_LINKS = [
  { href: "/dashboard",          label: "Dashboard",          icon: Home },
  { href: "/attendance/upload",  label: "Upload Attendance",  icon: Upload },
  { href: "/attendance/tracker", label: "MST Seat Map",       icon: Armchair },
  { href: "/mst-rollcall",       label: "MST Roll Call",      icon: ClipboardCheck },
  { href: "/eligibility",        label: "Eligibility",        icon: CheckSquare },
  { href: "/follow-up",          label: "VT / Follow-up",     icon: ClipboardList },
  { href: "/duties",             label: "Duty Scheduler",     icon: Users },
  { href: "/timetable",          label: "Timetable",          icon: CalendarDays },
  { href: "/ai",                 label: "AI Assistant",       icon: Bot },
  { href: "/settings",           label: "Settings",           icon: Settings },
];


export function Sidebar({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <div className={cn("pb-12 border-r bg-sidebar min-h-screen flex flex-col", className)}>
      <div className="space-y-4 py-4 flex-1">
        <div className="px-3 py-2">
          <div className="mb-6 px-4 flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground text-lg font-bold shadow-sm">
              E
            </div>
            <div>
              <h2 className="text-base font-bold tracking-tight leading-none">
                EduDuty
              </h2>
              <p className="text-xs text-muted-foreground mt-1">MST Operations</p>
            </div>
          </div>
          <div className="space-y-1">
            {NAV_LINKS.map(({ href, label, icon: Icon }) => {
              const active = pathname === href || pathname.startsWith(href + "/");
              return (
                <Link
                  key={href}
                  href={href}
                  className={cn(
                    "w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150",
                    active
                      ? "bg-primary text-primary-foreground shadow-sm"
                      : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </Link>
              );
            })}
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
