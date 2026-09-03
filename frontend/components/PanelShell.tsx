"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The panel shell.
 *
 * 660px over the surface, or 92 per cent on a narrow screen. It owns the
 * scrim, escape, focus return, and the rule that opening one closes another.
 *
 * Panels never stack, so there is never a back button. That rule is enforced
 * by there being one `openPanel` value on the surface rather than a stack,
 * so a second panel cannot be opened on top of a first even by mistake.
 *
 * Focus moves into the panel on open and returns to whatever opened it on
 * close. Without the return, closing a panel drops focus onto the document
 * and the next tab starts from the top of the page.
 */
export function PanelShell({
  open,
  title,
  description,
  icon: Icon,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  description?: string;
  icon?: LucideIcon;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement;
    panel.current?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      // Focus returns to the control that opened the panel, so the next tab
      // continues from where the user was rather than from the top.
      if (opener.current instanceof HTMLElement) opener.current.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          "relative h-full w-[660px] max-w-[92vw] overflow-y-auto",
          "border-l border-border bg-card shadow-2xl outline-none",
        )}
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-border bg-card px-6 py-4">
          <div className="flex items-start gap-3 min-w-0">
            {Icon ? (
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
                <Icon className="h-[18px] w-[18px]" />
              </div>
            ) : null}
            <div className="min-w-0">
              <h2 className="text-section-title">{title}</h2>
              {description ? (
                <p className="text-helper mt-0.5">{description}</p>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close the panel"
            className="rounded-md p-1.5 text-muted-foreground hover:bg-surface-2 hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-6 py-5">{children}</div>
      </aside>
    </div>
  );
}

/** An empty view invites an action rather than reporting no records found. */
export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded border border-dashed border-border bg-surface-2/30 p-6 text-center">
      <p className="text-xs text-muted-foreground">{children}</p>
    </div>
  );
}
