"use client";

import { AlertTriangle, BarChart3, Cog, Layers, SlidersHorizontal, Sparkles, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * The strip. Six entries, capped.
 *
 * Adding a seventh means merging two. Ratings & Policy stays as-is
 * (rating bands, cap, tenor caps) — Control gathers the LOV / config
 * screens the treasurer edits before the day (investment principles,
 * accounting-event catalogue, future settings).
 */
const ITEMS = [
  { key: "Exposure", label: "Exposure", icon: BarChart3 },
  { key: "Performance", label: "Performance", icon: TrendingUp },
  { key: "Queue", label: "Queue", icon: Layers },
  { key: "Breaches", label: "Breaches", icon: AlertTriangle },
  { key: "Advisory", label: "Advisory", icon: Sparkles },
  { key: "Ratings and policy", label: "Ratings & Policy", icon: SlidersHorizontal },
  { key: "Control", label: "Control", icon: Cog },
] as const;

export function Strip({
  queueCount,
  breachCount,
  advisoryCount,
  onOpen,
}: {
  queueCount: number;
  breachCount: number;
  advisoryCount: number;
  onOpen?: (item: string) => void;
}) {
  const counts: Record<string, number | null> = {
    Exposure: null,
    Performance: null,
    Queue: queueCount,
    Breaches: breachCount,
    Advisory: advisoryCount,
    "Ratings and policy": null,
    Control: null,
  };

  return (
    <nav className="h-11 border-t border-border bg-surface-1 flex items-center divide-x divide-border select-none z-20">
      {ITEMS.map(({ key, label, icon: Icon }) => {
        const count = counts[key];
        const hasAlert = count !== null && count > 0;
        const isBreach = key === "Breaches" && hasAlert;

        return (
          <button
            key={key}
            type="button"
            onClick={() => onOpen?.(key)}
            className="flex-1 h-full px-3 flex items-center justify-center gap-2 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-surface-2/60 transition-colors"
          >
            <Icon className="h-3.5 w-3.5 shrink-0" />
            <span>{label}</span>
            {count !== null ? (
              <span
                className={cn(
                  "min-w-[18px] px-1.5 py-0.2 rounded-full text-[10px] font-semibold flex items-center justify-center",
                  isBreach
                    ? "status-failed font-bold"
                    : hasAlert
                      ? "status-testing"
                      : "bg-surface-2 text-muted-foreground"
                )}
              >
                {count}
              </span>
            ) : null}
          </button>
        );
      })}
    </nav>
  );
}
