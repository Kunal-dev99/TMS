"use client";

/**
 * Compact top bar inside the AppShell.
 *
 * Carries: a breadcrumb derived from nav-config + the current path,
 * the user's name + role, a "⋯" action menu for operations that
 * don't belong in the sidebar (Nightly job / Reset / Paste a
 * confirmation — currently in Header.tsx; migrated per-page as the
 * old shells are replaced in Phase 4), and a Sign out.
 *
 * The old Header's "today" + "enforcement" + tenant chips live under
 * a <Topbar.ContextStrip> that pages opt into — Phase 4 wires it on
 * the treasurer home.
 */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ChevronRight, MoreHorizontal, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { signOut, whoAmI } from "@/lib/api";
import { currentUser, type SignedInUser } from "@/lib/session";
import { NAV, groupForPath } from "@/lib/nav-config";

export function Topbar({
  actions,
}: {
  /** Page-level actions injected by the current route. Rendered to
   *  the left of the user menu. Keep it short — 2 or 3 buttons max. */
  actions?: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<SignedInUser | null>(null);

  useEffect(() => {
    const existing = currentUser();
    if (existing) {
      setUser(existing);
      return;
    }
    void whoAmI()
      .then(setUser)
      .catch(() => setUser(null));
  }, [pathname]);

  const crumbs = buildCrumbs(pathname);

  return (
    <header className="flex h-11 shrink-0 items-center gap-3 border-b border-border bg-surface-1 px-4">
      <nav
        aria-label="Breadcrumb"
        className="flex min-w-0 flex-1 items-center gap-1 text-[12.5px] text-muted-foreground"
      >
        {crumbs.map((c, i) => (
          <span key={i} className="flex items-center gap-1">
            {i > 0 ? (
              <ChevronRight className="h-3 w-3 text-muted-foreground/60" />
            ) : null}
            {c.href ? (
              <Link
                href={c.href}
                className="rounded hover:bg-surface-2 hover:text-foreground"
              >
                {c.label}
              </Link>
            ) : (
              <span className="text-foreground">{c.label}</span>
            )}
          </span>
        ))}
      </nav>

      {actions ? (
        <div className="flex items-center gap-1">{actions}</div>
      ) : null}

      {user ? (
        <>
          <Link
            href="/profile/mfa"
            className="hidden md:inline-flex h-7 items-center gap-1 rounded-md px-2 text-[11px] font-medium text-muted-foreground hover:bg-surface-2 hover:text-foreground"
            title="Two-factor authentication"
          >
            <ShieldCheck className="h-3 w-3" />
            Security
          </Link>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label="More"
                className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-surface-2 hover:text-foreground"
              >
                <MoreHorizontal className="h-4 w-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <div className="px-2 py-1.5 text-[11px] text-muted-foreground">
                Signed in as{" "}
                <span className="font-medium text-foreground">
                  {user.display_name}
                </span>
              </div>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => router.push("/profile/mfa")}>
                Two-factor authentication
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={async () => {
                  await signOut();
                  router.push("/");
                }}
              >
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>
      ) : null}
    </header>
  );
}

interface Crumb {
  label: string;
  href?: string;
}

function buildCrumbs(pathname: string): Crumb[] {
  const entry = groupForPath(pathname);
  if (!entry) return [{ label: "Treasury Register" }];

  // Flat link: breadcrumb is just the entry label.
  if (entry.kind === "link") {
    return [{ label: entry.label }];
  }

  // Grouped entry: group label (linkable to first child) + the matched
  // child's label.
  const item =
    entry.children.find((c) => {
      const base = c.href.split("?")[0].split("#")[0];
      return base === pathname;
    }) ??
    entry.children.find((c) => {
      const base = c.href.split("?")[0].split("#")[0];
      return base !== "/" && pathname.startsWith(base);
    });

  const crumbs: Crumb[] = [
    { label: entry.label, href: entry.children[0]?.href },
  ];
  if (item) crumbs.push({ label: item.label });
  return crumbs;
}

/** Pages opt into the dense status chips (Prototype / tenant / today /
 *  enforcement) via <ContextStrip>. Lives inside the AppShell's
 *  content area at the top of the page. */
export function ContextStrip({ children }: { children: React.ReactNode }) {
  return (
    <div className="border-b border-border bg-surface-1 px-4 py-1.5 text-[11px] text-muted-foreground">
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </div>
  );
}

/** Convenience for shell-aware pages that want a per-page action
 *  button in the Topbar's `actions` slot. */
export function TopbarAction({
  children,
  onClick,
  variant = "ghost",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: "ghost" | "outline";
}) {
  return (
    <Button
      size="sm"
      variant={variant}
      type="button"
      onClick={onClick}
      className="h-7 px-2 text-[11px] text-muted-foreground"
    >
      {children}
    </Button>
  );
}
