"use client";

import { useEffect, useState } from "react";
import { BookOpen } from "lucide-react";

import { PanelShell } from "@/components/PanelShell";
import { getSystemPolicy, type SystemPolicySource } from "@/lib/api";

/**
 * Reference & sources - the cheat sheet.
 *
 * Every visible field in the app catalogued: where the value comes
 * from, whether the treasurer can edit it (and if so, where). Read-only
 * from this panel; navigate to Control's other tiles for edits.
 */
export function ReferenceSourcesPanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [sources, setSources] = useState<SystemPolicySource[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    getSystemPolicy()
      .then((v) => { if (!cancelled) setSources(v.sources); })
      .catch(() => undefined)
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open]);

  return (
    <PanelShell
      open={open}
      onClose={onClose}
      icon={BookOpen}
      title="Reference & sources"
      description="Every field on the screen, where it comes from, and where it's edited. The cheat sheet."
    >
      {loading ? (
        <div className="py-8 text-center text-xs text-muted-foreground">Loading…</div>
      ) : (
        <div className="space-y-3">
          {sources.map((s) => (
            <div key={s.field} className="rounded border border-border bg-surface-2/40 p-3">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs font-semibold text-foreground">{s.field}</span>
                <span className={`text-[9px] uppercase tracking-wider font-medium ${
                  s.editable.startsWith("yes")
                    ? "text-primary"
                    : "text-muted-foreground"
                }`}>
                  {s.editable}
                </span>
              </div>
              <div className="mt-1 grid grid-cols-[80px_1fr] gap-x-2 gap-y-0.5 text-[11px]">
                <span className="text-muted-foreground">Source</span>
                <span>{s.source}</span>
                <span className="text-muted-foreground">Shown on</span>
                <span className="italic text-muted-foreground">{s.shown_on}</span>
              </div>
            </div>
          ))}
          <p className="pt-2 text-[10px] italic text-muted-foreground">
            Nothing on the screen is random. Every value either comes from an
            external feed (with the provider named) or from an editable screen
            in Control (with the location named). This panel is the map.
          </p>
        </div>
      )}
    </PanelShell>
  );
}
