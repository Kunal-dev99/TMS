"use client";

import { useMemo, useState } from "react";
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
 *
 * One deal can violate more than one rule at a time -- a downgrade often
 * blows past both the amount and the tenor limit on the same position. The
 * server records that as two breaches, because two rules were broken, but
 * for the treasurer it is one piece of work: same deal, same counterparty,
 * same set of responses. So the panel groups breaches by deal and renders
 * one card per position with the reasons stacked. A response applies to
 * every breach in the group in one click.
 */
const RESPONSES = [
  { value: "HOLD_TO_MATURITY", label: "Hold to maturity" },
  { value: "BREAK_EARLY", label: "Break early" },
  { value: "SEEK_RATIFICATION", label: "Seek ratification" },
  { value: "REDUCE_ON_ROLL", label: "Reduce on roll" },
];


type BreachGroup = {
  key: string;
  counterparty_name: string;
  deal_id: string | null;
  raised_at: string;
  breaches: BreachView[];
};


function groupByDeal(breaches: BreachView[]): BreachGroup[] {
  const groups = new Map<string, BreachGroup>();
  for (const breach of breaches) {
    // Breaches with a deal_id are grouped by the deal. Portfolio-level
    // breaches (concentration, say) have no deal_id and each stands on
    // its own -- grouping by "" would fold every one of them into the
    // same card, which is not the same problem.
    const key = breach.deal_id
      ? `deal:${breach.deal_id}`
      : `breach:${breach.id}`;
    const existing = groups.get(key);
    if (existing) {
      existing.breaches.push(breach);
      // Keep the earliest raised_at for the group timestamp.
      if (breach.raised_at < existing.raised_at) {
        existing.raised_at = breach.raised_at;
      }
    } else {
      groups.set(key, {
        key,
        counterparty_name: breach.counterparty_name,
        deal_id: breach.deal_id,
        raised_at: breach.raised_at,
        breaches: [breach],
      });
    }
  }
  return Array.from(groups.values());
}


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

  const groups = useMemo(() => groupByDeal(breaches), [breaches]);

  const respond = async (group: BreachGroup, response: string) => {
    setBusy(group.key);
    try {
      // A group is one problem for the treasurer, so one click responds
      // to every breach on the same deal. If any of the responses fail
      // the whole batch aborts and the state reloads so the reader sees
      // exactly what happened.
      const unresolved = group.breaches.filter((b) => !b.response);
      for (const breach of unresolved) {
        await respondToBreach(breach.id, response);
      }
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
      {groups.length === 0 ? (
        <EmptyState>
          Nothing flagged. A breach appears when a rating action makes an
          existing position fall outside a revised limit.
        </EmptyState>
      ) : (
        <div className="space-y-4">
          {groups.map((group) => {
            const alreadyResponded = group.breaches.every((b) => b.response);
            const lastResponse = group.breaches.find((b) => b.response)
              ?.response;
            return (
              <article
                key={group.key}
                className="rounded-lg border border-destructive/30 bg-destructive/5 p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium">
                      {group.counterparty_name}
                    </p>
                    <p className="mt-0.5 text-[10px] uppercase tracking-wider text-destructive">
                      {group.breaches.length === 1
                        ? `${group.breaches[0].type.toLowerCase()} breach`
                        : `${group.breaches.length} rules broken`}
                    </p>
                  </div>
                  <span className="shrink-0 text-[10px] text-muted-foreground">
                    {shortDate(group.raised_at)}
                  </span>
                </div>

                {/* Reasons stacked. Each one has its own type badge so the
                    reader sees at a glance which rules the position broke. */}
                <ul className="mt-3 space-y-2">
                  {group.breaches.map((b) => (
                    <li
                      key={b.id}
                      className="flex items-start gap-2 text-xs text-muted-foreground"
                    >
                      <span
                        className="mt-[3px] shrink-0 rounded bg-destructive/15 px-1.5 py-px text-[9px] font-medium uppercase tracking-wider text-destructive"
                      >
                        {b.type.toLowerCase()}
                      </span>
                      <span>{b.detail}</span>
                    </li>
                  ))}
                </ul>

                {alreadyResponded && lastResponse ? (
                  <p className="mt-3 rounded border border-border bg-card p-2 text-[10px] text-muted-foreground">
                    Recorded: {lastResponse.replace(/_/g, " ").toLowerCase()}.
                    The position is still outside policy.
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
                        disabled={busy === group.key}
                        onClick={() => respond(group, option.value)}
                      >
                        {option.label}
                      </Button>
                    ))}
                  </div>
                )}

                {group.deal_id ? (
                  <button
                    type="button"
                    onClick={() => onShowEvidence(group.deal_id!)}
                    className="mt-3 text-[11px] font-medium text-primary underline-offset-2 hover:underline"
                  >
                    Show the check it passed
                  </button>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </PanelShell>
  );
}
