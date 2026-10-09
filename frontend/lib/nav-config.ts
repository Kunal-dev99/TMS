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

/** A single top-level nav item with its own href. Renders as a plain
 *  link (no chevron, no expand/collapse). Use when the destination
 *  is one page. */
export interface NavLink {
  kind: "link";
  id: string;
  label: string;
  icon: string;
  href: string;
  requiresAnyRole?: string[];
}

/** A grouped nav entry with children. Renders with a chevron that
 *  expands to reveal its children. Use when there are 2+ real routes
 *  under the same umbrella. */
export interface NavGroupExpandable {
  kind: "group";
  id: string;
  label: string;
  icon: string;
  requiresAnyRole?: string[];
  children: NavItem[];
}

export type NavEntry = NavLink | NavGroupExpandable;

/** Back-compat alias so callers that typed against NavGroup still
 *  type-check. New code should prefer NavEntry. */
export type NavGroup = NavEntry;

export const NAV: NavEntry[] = [
  {
    kind: "link",
    id: "treasurer",
    label: "Treasurer",
    icon: "arrows-left-right",
    href: "/",
  },
  {
    kind: "link",
    id: "approvals",
    label: "Approvals",
    icon: "pen-line",
    href: "/approvals",
  },
  {
    kind: "group",
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
    kind: "link",
    id: "admin",
    label: "Admin",
    icon: "settings",
    requiresAnyRole: ["ADMIN"],
    href: "/admin",
  },
  {
    kind: "link",
    id: "profile",
    label: "Two-factor authentication",
    icon: "shield-lock",
    href: "/profile/mfa",
  },
];

/** The sidebar entry that owns `pathname`, or null. For a link, that's
 *  the link itself; for a group, it's the group whose child matches.
 *  Used by Topbar's breadcrumb + Sidebar's auto-expansion. */
export function groupForPath(pathname: string): NavEntry | null {
  for (const entry of NAV) {
    if (entry.kind === "link") {
      const base = entry.href.split("?")[0].split("#")[0];
      if (base === pathname) return entry;
      if (base !== "/" && pathname.startsWith(base)) return entry;
    } else {
      for (const item of entry.children) {
        const base = item.href.split("?")[0].split("#")[0];
        if (base === pathname) return entry;
        if (base !== "/" && pathname.startsWith(base)) return entry;
      }
    }
  }
  return null;
}

/** For a given NavEntry, return its primary href (the link's own href,
 *  or the first child's href for a group). */
export function primaryHref(entry: NavEntry): string {
  return entry.kind === "link" ? entry.href : entry.children[0]?.href ?? "/";
}
