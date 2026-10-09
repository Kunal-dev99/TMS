"use client";

/**
 * The outer frame every signed-in page sits inside after Phase 3.
 *
 * Composition:
 *   <AppShell actions={<RunNightly/>, <Reset/>}>
 *     <YourPage />
 *   </AppShell>
 *
 * The shell owns:
 *   - the sidebar (collapsible, config-driven),
 *   - the top bar (breadcrumb + actions slot + user menu),
 *   - nothing inside the page body — that's yours.
 *
 * Pre-sign-in flows (/activate, future /auth/*) do NOT wrap in
 * AppShell — see SHELL_EXEMPT_ROUTES in Phase 3.
 */

import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export function AppShell({
  children,
  actions,
}: {
  children: React.ReactNode;
  /** Optional per-page actions rendered in the Topbar. */
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen w-full bg-background">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar actions={actions} />
        <main className="min-w-0 flex-1 overflow-x-auto">{children}</main>
      </div>
    </div>
  );
}
