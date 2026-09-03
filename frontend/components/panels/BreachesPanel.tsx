"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import { EmptyState, PanelShell } from "@/components/PanelShell";
import { Button } from "@/components/ui/button";
import { respondToBreach } from "@/lib/api";
import { shortDate } from "@/lib/format";
import type { BreachView } from "@/lib/types";

/**
 * Breaches.
 *
 * A breach is a position that was compliant when it was booked and is not
 * compliant now. Nobody made a mistake. The world moved.
 *
 * Responding records a decision. It does not clear the breach, it does not
 * change the deal, and the count in the strip does not fall, because the
 * position is still outside policy. The panel says so in those words rather
 * than leaving the user to notice.
 */
const RESPONSES = [
  { value: "HOLD_TO_MATURITY", label: "Hold to maturity" },
  { value: "BREAK_EARLY", label: "Break early" },
  { value: "SEEK_RATIFICATION", label: "Seek ratification" },
  { value: "REDUCE_ON_ROLL", label: "Reduce on roll" },
];

export function BreachesPanel({
  open,
  onClose,
  breaches,
  onResponded,
  onShowEvidence,
}: {
  open: boolean;
  onClose: () => void;
  breaches: BreachView[];
  onResponded: () => void;
  onShowEvidence: (dealId: string) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);

  const respond = async (breachId: string, response: string) => {
    setBusy(breachId);
    try {
      await respondToBreach(breachId, response);
      onResponded();
    } finally {
      setBusy(null);
    }
  };

  return (
    <PanelShell
      open={open}
      onClose={onClose}
      icon={AlertTriangle}
      title="Breaches"
      description="Compliant when booked. Not compliant now"
    >
      {breaches.length === 0 ? (
        <EmptyState>
          Nothing flagged. A breach appears when a rating action makes an
          existing position fall outside a revised limit.
        </EmptyState>
      ) : (
        <div className="space-y-4">
          {breaches.map((breach) => (
            <article
              key={breach.id}
              className="rounded-lg border border-destructive/30 bg-destructive/5 p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{breach.counterparty_name}</p>
                  <p className="mt-0.5 text-[10px] uppercase tracking-wider text-destructive">
                    {breach.type.toLowerCase()} breach
                  </p>
                </div>
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  {shortDate(breach.raised_at)}
                </span>
              </div>

              <p className="mt-2 text-xs text-muted-foreground">{breach.detail}</p>

              {breach.response ? (
                <p className="mt-3 rounded border border-border bg-card p-2 text-[10px] text-muted-foreground">
                  Recorded: {breach.response.replace(/_/g, " ").toLowerCase()}. The
                  position is still outside policy.
                </p>
              ) : (
                <div className="mt-3 flex flex-wrap gap-2">
                  {RESPONSES.map((option) => (
                    <Button
                      key={option.value}
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs"
                      disabled={busy === breach.id}
                      onClick={() => respond(breach.id, option.value)}
                    >
                      {option.label}
                    </Button>
                  ))}
                </div>
              )}

              {breach.deal_id ? (
                <button
                  type="button"
                  onClick={() => onShowEvidence(breach.deal_id!)}
                  className="mt-3 text-[11px] font-medium text-primary underline-offset-2 hover:underline"
                >
                  Show the check it passed
                </button>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </PanelShell>
  );
}
