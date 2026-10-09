/**
 * The sidebar nav tree.
 *
 * One array drives every entry in `components/shell/Sidebar`. Adding a
 * page = one new NavItem under the right group. Hiding something per
 * role = `requiresAnyRole`. No layout code change needed either way.
 *
 * Group ordering is intentional: Treasurer first (daily workspace),
 * Approvals + Compliance (control surfaces), Admin (configuration),
 * Profile (self-service) last.
 *
 * `icon` is a Tabler icon name (we already use `lucide-react` for
 * icons elsewhere; the sidebar passes the name through to lucide via
 * the SidebarGroup component — see components/shell/Sidebar.tsx for
 * the name→component map).
 */

export interface NavItem {
  href: string;
  label: string;
  /** Optional pill badge next to the label — "3", "new", etc. The
   *  value can be a static string or a function keyed by state we
   *  haven't wired yet; keep static for Phase 1. */
  badge?: string;
}

export interface NavGroup {
  id: string;
  label: string;
  /** Icon name — resolved to a lucide component in Sidebar.tsx. */
  icon: string;
  /** Role gate — the group only renders if the signed-in user holds
   *  ANY of these roles. Omit to show to everyone. */
  requiresAnyRole?: string[];
  /** Optional role gate per item inside the group; otherwise inherits
   *  from the group. */
  children: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    id: "treasurer",
    label: "Treasurer",
    icon: "arrows-left-right",
    children: [
      { href: "/", label: "Deals and book" },
      { href: "/#planner", label: "Planner" },
      { href: "/#hedging", label: "Hedging" },
      { href: "/#exposure", label: "Exposure" },
    ],
  },
  {
    id: "approvals",
    label: "Approvals",
    icon: "pen-line",
    children: [{ href: "/approvals", label: "Queue" }],
  },
  {
    id: "compliance",
    label: "Compliance",
    icon: "shield-check",
    requiresAnyRole: ["COMPLIANCE_OFFICER", "CFO", "ADMIN"],
    children: [
      { href: "/compliance", label: "Overview" },
      { href: "/compliance?tab=audit", label: "Audit trail" },
      { href: "/compliance?tab=evidence", label: "Deal evidence" },
      { href: "/compliance?tab=breaches", label: "Breaches" },
      { href: "/compliance?tab=policy", label: "Policy history" },
      { href: "/compliance?tab=ai", label: "AI activity" },
    ],
  },
  {
    id: "admin",
    label: "Admin",
    icon: "settings",
    requiresAnyRole: ["ADMIN"],
    children: [
      { href: "/admin", label: "Overview" },
      { href: "/admin/users", label: "Users and roles" },
      { href: "/admin/system-policy", label: "Policy and bands" },
    ],
  },
  {
    id: "profile",
    label: "Profile",
    icon: "user",
    children: [
      { href: "/profile/mfa", label: "Two-factor authentication" },
    ],
  },
];

/** The sidebar group whose children contain `pathname`, or null. Used
 *  by SidebarGroup to auto-expand the group the user is currently in. */
export function groupForPath(pathname: string): NavGroup | null {
  for (const group of NAV) {
    for (const item of group.children) {
      const base = item.href.split("?")[0].split("#")[0];
      if (base === pathname) return group;
      if (base !== "/" && pathname.startsWith(base)) return group;
    }
  }
  return null;
}
