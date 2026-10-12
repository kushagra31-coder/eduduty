import {
  Home,
  Upload,
  Armchair,
  ClipboardCheck,
  CheckSquare,
  ClipboardList,
  Users,
  CalendarDays,
  Bot,
  Settings,
  type LucideIcon,
} from 'lucide-react'

export interface NavItem {
  href: string
  label: string
  icon: LucideIcon
  roles?: string[] // If undefined or empty, accessible to all authenticated users
  description?: string
}

export const NAV_LINKS: NavItem[] = [
  {
    href: '/dashboard',
    label: 'Dashboard',
    icon: Home,
    description: 'Role-specific overview and statistics',
  },
  {
    href: '/attendance/upload',
    label: 'Upload Attendance',
    icon: Upload,
    roles: ['SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR'],
    description: 'Import attendance spreadsheets',
  },
  {
    href: '/attendance/tracker',
    label: 'MST Seat Map',
    icon: Armchair,
    description: 'Examination room seating plan',
  },
  {
    href: '/mst-rollcall',
    label: 'MST Roll Call',
    icon: ClipboardCheck,
    roles: ['SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR', 'FACULTY', 'INVIGILATOR'],
    description: 'Real-time student attendance marking',
  },
  {
    href: '/eligibility',
    label: 'Eligibility',
    icon: CheckSquare,
    description: 'Student eligibility rosters and overrides',
  },
  {
    href: '/follow-up',
    label: 'VT / Follow-up',
    icon: ClipboardList,
    roles: ['SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR', 'FACULTY', 'VIEWER'],
    description: 'Dual-MST absence and VT tracking',
  },
  {
    href: '/duties',
    label: 'Duty Scheduler',
    icon: Users,
    description: 'Faculty invigilation duty management',
  },
  {
    href: '/timetable',
    label: 'Timetable',
    icon: CalendarDays,
    description: 'Academic class schedules and faculty commitments',
  },
  {
    href: '/ai',
    label: 'AI Assistant',
    icon: Bot,
    roles: ['SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR', 'FACULTY'],
    description: 'Conversational reporting and student lookup',
  },
  {
    href: '/settings',
    label: 'Settings',
    icon: Settings,
    roles: ['SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR'],
    description: 'Manage faculty, classes, rooms, and exams',
  },
]

/**
 * Filter navigation items based on current authenticated role.
 * If role is null (e.g. during initialization), returns all links.
 */
export function getFilteredNavLinks(role: string | null): NavItem[] {
  if (!role) {
    return NAV_LINKS
  }
  return NAV_LINKS.filter((item) => {
    if (!item.roles || item.roles.length === 0) {
      return true
    }
    return item.roles.includes(role)
  })
}
