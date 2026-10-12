"use client"

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Sun, Moon, LogOut, User as UserIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTheme } from 'next-themes';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/lib/auth/context';
import { getFilteredNavLinks } from '@/lib/nav';


export function Sidebar({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);
  const { user, role, signOut } = useAuth();

  useEffect(() => {
    setMounted(true);
  }, []);

  if (pathname === '/login') {
    return null;
  }

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
            {getFilteredNavLinks(role).map(({ href, label, icon: Icon }) => {
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
      
      <div className="p-4 border-t space-y-2">
        {user && (
          <div className="px-2 py-1.5 flex items-center gap-2 text-xs text-muted-foreground border-b pb-2 mb-2">
            <UserIcon className="h-4 w-4 shrink-0" />
            <div className="overflow-hidden text-ellipsis whitespace-nowrap">
              <p className="font-medium text-foreground text-xs">{user.email}</p>
              <p className="text-[10px] text-muted-foreground capitalize">{role ? role.replace('_', ' ') : 'User'}</p>
            </div>
          </div>
        )}
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
        {user && (
          <Button 
            variant="ghost" 
            className="w-full justify-start gap-2 text-destructive hover:text-destructive hover:bg-destructive/10" 
            onClick={() => signOut()}
          >
            <LogOut className="h-4 w-4" />
            Sign Out
          </Button>
        )}
      </div>
    </div>
  );
}

