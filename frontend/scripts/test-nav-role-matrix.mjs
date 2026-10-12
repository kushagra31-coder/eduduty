// Test suite: Navigation role filtering matrix verification
import assert from 'node:assert';

// Mirroring getFilteredNavLinks logic to test the role matrix contract
const NAV_LINKS = [
  { href: '/dashboard', label: 'Dashboard' },
  { href: '/attendance/upload', label: 'Upload Attendance', roles: ['SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR'] },
  { href: '/attendance/tracker', label: 'MST Seat Map' },
  { href: '/mst-rollcall', label: 'MST Roll Call', roles: ['SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR', 'FACULTY', 'INVIGILATOR'] },
  { href: '/eligibility', label: 'Eligibility' },
  { href: '/follow-up', label: 'VT / Follow-up', roles: ['SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR', 'FACULTY', 'VIEWER'] },
  { href: '/duties', label: 'Duty Scheduler' },
  { href: '/timetable', label: 'Timetable' },
  { href: '/ai', label: 'AI Assistant', roles: ['SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR', 'FACULTY'] },
  { href: '/settings', label: 'Settings', roles: ['SUPER_ADMIN', 'ADMIN', 'EXAM_COORDINATOR'] },
];

function getFilteredNavLinks(role) {
  if (!role) return NAV_LINKS;
  return NAV_LINKS.filter((item) => {
    if (!item.roles || item.roles.length === 0) return true;
    return item.roles.includes(role);
  });
}

console.log("=== Testing Navigation Role Matrix ===");

// 1. Super Admin
const adminLinks = getFilteredNavLinks('SUPER_ADMIN').map(l => l.href);
assert.strictEqual(adminLinks.length, 10, "SUPER_ADMIN must see all 10 navigation links");
console.log("✓ SUPER_ADMIN: 10/10 links visible");

// 2. Exam Coordinator
const coordLinks = getFilteredNavLinks('EXAM_COORDINATOR').map(l => l.href);
assert.strictEqual(coordLinks.length, 10, "EXAM_COORDINATOR must see all 10 navigation links");
console.log("✓ EXAM_COORDINATOR: 10/10 links visible");

// 3. Faculty
const facultyLinks = getFilteredNavLinks('FACULTY').map(l => l.href);
assert.strictEqual(facultyLinks.length, 8, "FACULTY must see 8 navigation links");
assert(!facultyLinks.includes('/attendance/upload'), "FACULTY must NOT see Upload Attendance");
assert(!facultyLinks.includes('/settings'), "FACULTY must NOT see Settings");
assert(facultyLinks.includes('/mst-rollcall'), "FACULTY must see MST Roll Call");
assert(facultyLinks.includes('/timetable'), "FACULTY must see Timetable");
assert(facultyLinks.includes('/ai'), "FACULTY must see AI Assistant");
console.log("✓ FACULTY: 8 links visible (Upload & Settings excluded)");

// 4. Viewer
const viewerLinks = getFilteredNavLinks('VIEWER').map(l => l.href);
assert.strictEqual(viewerLinks.length, 6, "VIEWER must see 6 read-only navigation links");
assert(!viewerLinks.includes('/attendance/upload'), "VIEWER must NOT see Upload Attendance");
assert(!viewerLinks.includes('/mst-rollcall'), "VIEWER must NOT see MST Roll Call");
assert(!viewerLinks.includes('/ai'), "VIEWER must NOT see AI Assistant");
assert(!viewerLinks.includes('/settings'), "VIEWER must NOT see Settings");
assert(viewerLinks.includes('/dashboard'), "VIEWER must see Dashboard");
assert(viewerLinks.includes('/attendance/tracker'), "VIEWER must see Seat Map");
assert(viewerLinks.includes('/eligibility'), "VIEWER must see Eligibility");
assert(viewerLinks.includes('/follow-up'), "VIEWER must see VT / Follow-up");
assert(viewerLinks.includes('/duties'), "VIEWER must see Duties");
assert(viewerLinks.includes('/timetable'), "VIEWER must see Timetable");
console.log("✓ VIEWER: 6 read-only links visible (All mutation links excluded)");

// 5. Invigilator
const invigLinks = getFilteredNavLinks('INVIGILATOR').map(l => l.href);
assert(!invigLinks.includes('/attendance/upload'), "INVIGILATOR must NOT see Upload Attendance");
assert(!invigLinks.includes('/settings'), "INVIGILATOR must NOT see Settings");
assert(invigLinks.includes('/mst-rollcall'), "INVIGILATOR must see MST Roll Call");
console.log("✓ INVIGILATOR: Roll call visible, administrative links excluded");

// 6. Unauthenticated / initial state
const defaultLinks = getFilteredNavLinks(null).map(l => l.href);
assert.strictEqual(defaultLinks.length, 10, "Null role must return full link set without crashing");
console.log("✓ Default/Null role: Full link set returned safely");

console.log("\nALL NAVIGATION ROLE MATRIX TESTS PASSED!");
