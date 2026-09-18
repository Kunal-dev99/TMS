"use client";

/**
 * PageShell — the wrapper for persona routes (`/admin`, `/compliance`,
 * `/approvals`).
 *
 * Renders the persona-nav across the top plus a titled page body. The
 * treasurer route (`/`) has its own shell (Header + Strip + Surface)
 * and does not use this — persona routes are simpler.
 */

import type { LucideIcon } from "lucide-react";

import { PersonaNav } from "@/components/PersonaNav";

export function PageShell({
  title,
  description,
  icon: Icon,
  children,
}: {
  title: string;
  description?: string;
  icon?: LucideIcon;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-background">
      <PersonaNav />
      <header className="border-b border-border bg-surface-1">
        <div className="mx-auto flex max-w-[1400px] items-start gap-3 px-4 py-4">
          {Icon ? (
            <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/15 text-primary">
              <Icon className="h-5 w-5" />
            </div>
          ) : null}
          <div>
            <h1 className="text-lg font-semibold text-foreground">{title}</h1>
            {description ? (
              <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
            ) : null}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1400px] px-4 py-6">{children}</main>
    </div>
  );
}
