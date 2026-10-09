"use client";

/**
 * Collapsible left sidebar. Config-driven by lib/nav-config.
 *
 * Two collapse axes:
 *   - the sidebar itself: full (220px) or icons-only (56px). Persisted
 *     per user via lib/ui-prefs. Keyboard shortcut Ctrl/Cmd+\.
 *   - per-group expand/collapse. Persisted per user. The group
 *     containing the current route auto-expands on first mount if
 *     the user has never touched that group.
 *
 * Role gating: an entry's requiresAnyRole hides the group entirely
 * for users without the role. The gate reads the same hasRole() the
 * old PersonaNav used; nothing new on the backend.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeftRight,
  ChevronRight,
  Cog,
  PenLine,
  Settings,
  ShieldCheck,
  User,
  type LucideIcon,
} from "lucide-react";

import { whoAmI } from "@/lib/api";
import { currentUser, type SignedInUser } from "@/lib/session";
import { NAV, groupForPath, type NavGroup } from "@/lib/nav-config";
import {
  readExpandedGroups,
  readSidebarCollapsed,
  writeExpandedGroups,
  writeSidebarCollapsed,
} from "@/lib/ui-prefs";
import { cn } from "@/lib/utils";

const ICONS: Record<string, LucideIcon> = {
  "arrows-left-right": ArrowLeftRight,
  "pen-line": PenLine,
  "shield-check": ShieldCheck,
  settings: Settings,
  cog: Cog,
  user: User,
};

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState<boolean>(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  // Hydration gate — localStorage is only read on the client. Before
  // the first effect runs we render with defaults, then swap in the
  // persisted state. Keeps SSR output stable.
  const [hydrated, setHydrated] = useState(false);
  // The signed-in user. Needed so role-gated groups show up as soon
  // as the session rehydrates — not after a reload.
  const [user, setUser] = useState<SignedInUser | null>(null);

  useEffect(() => {
    setCollapsed(readSidebarCollapsed());
    const persisted = readExpandedGroups();
    const seed = new Set(persisted);
    // First visit: auto-expand the group containing the current route.
    if (persisted.length === 0) {
      const g = groupForPath(pathname);
      if (g) seed.add(g.id);
    }
    setExpanded(seed);
    setHydrated(true);

    const existing = currentUser();
    if (existing) {
      setUser(existing);
    } else {
      void whoAmI()
        .then(setUser)
        .catch(() => setUser(null));
    }
  }, [pathname]);

  const toggleSidebar = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      writeSidebarCollapsed(next);
      return next;
    });
  }, []);

  const toggleGroup = useCallback((groupId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      writeExpandedGroups([...next]);
      return next;
    });
  }, []);

  // Keyboard shortcut: Ctrl/Cmd + \ toggles sidebar.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "\\") {
        e.preventDefault();
        toggleSidebar();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggleSidebar]);

  const visibleGroups = useMemo(() => {
    // Read roles from state, not from the module-level hasRole() —
    // after a hard navigate the module-level user is null until a
    // sign-in writes to it, but the state here is updated by the
    // whoAmI() effect above.
    const roles = user?.roles ?? [];
    return NAV.filter(
      (g) => !g.requiresAnyRole || g.requiresAnyRole.some((r) => roles.includes(r)),
    );
  }, [user, hydrated]);

  return (
    <aside
      aria-label="Primary navigation"
      className={cn(
        "flex shrink-0 flex-col border-r border-border bg-surface-1 transition-[width] duration-150",
        collapsed ? "w-14" : "w-[220px]",
      )}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border px-2 py-2">
        {!collapsed ? (
          <span className="pl-2 text-[12px] font-medium text-foreground">
            Treasury Register
          </span>
        ) : null}
        <button
          type="button"
          onClick={toggleSidebar}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar (Ctrl+\\)" : "Collapse sidebar (Ctrl+\\)"}
          className="ml-auto flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-surface-2 hover:text-foreground"
        >
          <ChevronRight
            className={cn(
              "h-3.5 w-3.5 transition-transform",
              collapsed ? "" : "rotate-180",
            )}
          />
        </button>
      </div>

      <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-2 py-2 text-[13px]">
        {visibleGroups.map((group) => (
          <SidebarGroup
            key={group.id}
            group={group}
            collapsed={collapsed}
            expanded={expanded.has(group.id)}
            onToggle={() => toggleGroup(group.id)}
            activePath={pathname}
          />
        ))}
      </nav>
    </aside>
  );
}

function SidebarGroup({
  group,
  collapsed,
  expanded,
  onToggle,
  activePath,
}: {
  group: NavGroup;
  collapsed: boolean;
  expanded: boolean;
  onToggle: () => void;
  activePath: string;
}) {
  const Icon = ICONS[group.icon] ?? ArrowLeftRight;

  // Collapsed sidebar: show icon only; clicking jumps to the group's
  // first child. No expansion possible since there's no room for
  // children in a 56px rail.
  if (collapsed) {
    const first = group.children[0];
    return (
      <Link
        href={first?.href ?? "/"}
        title={group.label}
        aria-label={group.label}
        className={cn(
          "flex h-9 items-center justify-center rounded-md text-muted-foreground hover:bg-surface-2 hover:text-foreground",
          activePath.startsWith(first?.href.split("?")[0] ?? "") && first?.href !== "/"
            ? "bg-primary/10 text-primary"
            : "",
        )}
      >
        <Icon className="h-4 w-4" />
      </Link>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-muted-foreground hover:bg-surface-2 hover:text-foreground"
      >
        <ChevronRight
          className={cn(
            "h-3 w-3 transition-transform",
            expanded ? "rotate-90" : "",
          )}
        />
        <Icon className="h-3.5 w-3.5" />
        <span className="font-medium text-foreground">{group.label}</span>
      </button>
      <div
        className="grid overflow-hidden transition-[grid-template-rows] duration-150 ease-out"
        style={{ gridTemplateRows: expanded ? "1fr" : "0fr" }}
        aria-hidden={!expanded}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="mt-0.5 flex flex-col gap-0.5 pl-[26px] pr-1">
          {group.children.map((item) => {
            const base = item.href.split("?")[0].split("#")[0];
            const active =
              base === "/"
                ? activePath === "/" && !item.href.includes("#")
                : activePath === base;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-2 rounded-md px-2 py-1 text-[12.5px]",
                  active
                    ? "bg-primary/15 text-primary font-medium"
                    : "text-muted-foreground hover:bg-surface-2 hover:text-foreground",
                )}
              >
                <span className="truncate">{item.label}</span>
                {item.badge ? (
                  <span className="ml-auto rounded-full border border-border bg-surface-2 px-1.5 text-[10px] text-muted-foreground">
                    {item.badge}
                  </span>
                ) : null}
              </Link>
            );
          })}
          </div>
        </div>
      </div>
    </div>
  );
}
