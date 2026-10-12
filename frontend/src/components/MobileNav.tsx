"use client"

import React, { useEffect, useState, useRef } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { Menu, X, Sun, Moon, LogOut, User as UserIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { useTheme } from "next-themes"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/lib/auth/context"
import { getFilteredNavLinks } from "@/lib/nav"

export function MobileNav() {
  const [isOpen, setIsOpen] = useState(false)
  const pathname = usePathname()
  const { theme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)
  const { user, role, signOut } = useAuth()
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    setMounted(true)
  }, [])

  // Close mobile navigation on route change
  useEffect(() => {
    setIsOpen(false)
  }, [pathname])

  // Prevent background scrolling and handle Escape key while panel is open
  useEffect(() => {
    if (!isOpen) return

    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsOpen(false)
      }
    }

    window.addEventListener("keydown", handleKeyDown)
    // Focus the close button for accessibility
    closeButtonRef.current?.focus()

    return () => {
      document.body.style.overflow = originalOverflow
      window.removeEventListener("keydown", handleKeyDown)
    }
  }, [isOpen])

  if (pathname === "/login") {
    return null
  }

  const navLinks = getFilteredNavLinks(role)

  return (
    <>
      {/* ── Mobile Header Bar (Visible on viewports < md) ──────────────────── */}
      <header className="md:hidden sticky top-0 z-40 flex h-14 w-full items-center justify-between border-b bg-background/95 px-4 backdrop-blur supports-backdrop-filter:bg-background/60">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground text-sm font-bold shadow-xs">
            E
          </div>
          <div>
            <span className="font-bold tracking-tight text-sm">EduDuty</span>
            <span className="text-xs text-muted-foreground ml-1.5 hidden xs:inline">MST Operations</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {role && (
            <span className="hidden sm:inline-flex items-center rounded-full bg-secondary px-2.5 py-0.5 text-[11px] font-medium text-secondary-foreground">
              {role.replace("_", " ")}
            </span>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="h-9 w-9"
            onClick={() => setIsOpen(true)}
            aria-label="Open navigation menu"
            aria-expanded={isOpen}
            aria-controls="mobile-navigation-drawer"
          >
            <Menu className="h-5 w-5" />
          </Button>
        </div>
      </header>

      {/* ── Slide-Over Backdrop & Panel ────────────────────────────────────── */}
      {isOpen && (
        <div className="fixed inset-0 z-50 md:hidden flex" role="dialog" aria-modal="true" aria-label="Navigation Menu">
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black/60 backdrop-blur-xs transition-opacity animate-in fade-in duration-200"
            onClick={() => setIsOpen(false)}
            aria-hidden="true"
          />

          {/* Slide-over drawer */}
          <div
            id="mobile-navigation-drawer"
            className="relative z-50 flex h-full w-72 max-w-[85vw] flex-col bg-sidebar border-r shadow-2xl animate-in slide-in-from-left duration-250 ease-out"
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b px-4 py-3">
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground text-sm font-bold shadow-xs">
                  E
                </div>
                <div>
                  <h2 className="text-sm font-bold tracking-tight">EduDuty</h2>
                  <p className="text-[11px] text-muted-foreground">MST Operations</p>
                </div>
              </div>
              <Button
                ref={closeButtonRef}
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => setIsOpen(false)}
                aria-label="Close navigation menu"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>

            {/* Navigation links */}
            <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
              {navLinks.map(({ href, label, icon: Icon }) => {
                const active = pathname === href || pathname.startsWith(href + "/")
                return (
                  <Link
                    key={href}
                    href={href}
                    onClick={() => setIsOpen(false)}
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors min-h-[44px]",
                      active
                        ? "bg-primary text-primary-foreground shadow-xs font-semibold"
                        : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span>{label}</span>
                  </Link>
                )
              })}
            </nav>

            {/* User & Theme Footer */}
            <div className="border-t p-4 space-y-3 bg-sidebar/50">
              {user && (
                <div className="flex items-center gap-2.5 px-1 py-1 text-xs">
                  <div className="h-8 w-8 rounded-full bg-secondary flex items-center justify-center shrink-0">
                    <UserIcon className="h-4 w-4 text-secondary-foreground" />
                  </div>
                  <div className="overflow-hidden min-w-0">
                    <p className="font-medium text-foreground truncate text-xs">{user.email}</p>
                    <p className="text-[10px] text-muted-foreground capitalize font-mono">
                      {role ? role.replace("_", " ") : "User"}
                    </p>
                  </div>
                </div>
              )}

              <div className="grid grid-cols-2 gap-2 pt-1">
                {mounted && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full justify-center gap-1.5 text-xs h-9"
                    onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                  >
                    {theme === "dark" ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
                    Theme
                  </Button>
                )}
                {user && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full justify-center gap-1.5 text-xs h-9 text-destructive hover:bg-destructive/10 hover:text-destructive"
                    onClick={() => {
                      setIsOpen(false)
                      signOut()
                    }}
                  >
                    <LogOut className="h-3.5 w-3.5" />
                    Sign Out
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
