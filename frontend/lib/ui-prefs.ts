/**
 * Per-user UI preferences, stored in localStorage.
 *
 * Scope today (MVP): sidebar collapse state + which groups are
 * expanded. One key per preference under `treasury.ui.*` so a future
 * preference lands without migrating. Guards every read/write — a
 * private window / blocked storage returns the default rather than
 * crashing the surface.
 *
 * localStorage (not sessionStorage) deliberately — these are UI
 * preferences, not credentials; the user wants their sidebar to
 * look the same across tabs and sessions.
 */

const KEY_SIDEBAR_COLLAPSED = "treasury.ui.sidebarCollapsed";
const KEY_EXPANDED_GROUPS = "treasury.ui.expandedGroups";

export function readSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(KEY_SIDEBAR_COLLAPSED) === "1";
  } catch {
    return false;
  }
}

export function writeSidebarCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(KEY_SIDEBAR_COLLAPSED, collapsed ? "1" : "0");
  } catch {
    /* no-op */
  }
}

export function readExpandedGroups(): string[] {
  try {
    const raw = localStorage.getItem(KEY_EXPANDED_GROUPS);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed.filter((v) => typeof v === "string");
    return [];
  } catch {
    return [];
  }
}

export function writeExpandedGroups(groupIds: string[]): void {
  try {
    localStorage.setItem(KEY_EXPANDED_GROUPS, JSON.stringify(groupIds));
  } catch {
    /* no-op */
  }
}
