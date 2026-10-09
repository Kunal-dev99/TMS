"use client";

/**
 * The thin title block that sits at the top of a page body inside
 * <AppShell>. Replaces what <PageShell> used to render around its
 * children — but as a standalone element the page controls, not a
 * wrapper.
 */

import type { LucideIcon } from "lucide-react";

export function PageHeader({
  title,
  description,
  icon: Icon,
  actions,
}: {
  title: string;
  description?: string;
  icon?: LucideIcon;
  /** Optional per-page action buttons rendered at the right. Keep
   *  the primary CTA in the Topbar; use this slot for secondary
   *  controls that read better next to the title. */
  actions?: React.ReactNode;
}) {
  return (
    <header className="border-b border-border bg-surface-1">
      <div className="mx-auto flex max-w-[1400px] items-start gap-3 px-4 py-4">
        {Icon ? (
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/15 text-primary">
            <Icon className="h-5 w-5" />
          </div>
        ) : null}
        <div className="min-w-0 flex-1">
          <h1 className="text-lg font-semibold text-foreground">{title}</h1>
          {description ? (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
        {actions ? (
          <div className="flex shrink-0 items-center gap-2">{actions}</div>
        ) : null}
      </div>
    </header>
  );
}

/** Routes that render WITHOUT the AppShell — pre-sign-in flows mostly.
 *  Documented here so a future page knows the carve-outs. Not enforced
 *  by code (each page decides its own wrapper); grep this list before
 *  wrapping a new pre-auth route. */
export const SHELL_EXEMPT_ROUTES = [
  "/activate",
  "/activate/*",
];
