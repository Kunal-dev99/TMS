"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";

import { PageSection } from "@/components/common/PageSection";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { decideRecommendation } from "@/lib/api";
import { perCent, sterling } from "@/lib/format";
import type { AdvisoryCard as Card } from "@/lib/types";

/**
 * The recommendation, above the ticket fields.
 *
 * Inside the ticket column rather than a banner across the page, and not a
 * notification, because it is an input to the work rather than an
 * interruption of it.
 *
 * Accepting fills the five fields and triggers a check immediately. It books
 * nothing: the deal is recorded by the ordinary Record deal action and runs
 * the ordinary six checks, and the interface says so rather than asking to
 * be trusted about it.
 *
 * When validation failed, the reasoning is replaced by the rule based pick,
 * flagged as such. The recommendation survives; only the explanation is
 * lost.
 */
export function AdvisoryCard({
  card,
  onAccept,
  onDecided,
  onOpenRun,
}: {
  card: Card;
  onAccept: (ticket: NonNullable<Card["ticket"]>, recommendationId: string) => void;
  onDecided: () => void;
  onOpenRun: (runId: string) => void;
}) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const fallback = card.source === "RULE_FALLBACK";

  const accept = async () => {
    if (!card.ticket || !card.recommendation_id) return;
    setBusy(true);
    try {
      await decideRecommendation(card.recommendation_id, "ACCEPTED");
      onAccept(card.ticket, card.recommendation_id);
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    if (!card.recommendation_id || !reason.trim()) return;
    setBusy(true);
    try {
      await decideRecommendation(card.recommendation_id, "REJECTED", reason.trim());
      onDecided();
    } finally {
      setBusy(false);
    }
  };

  return (
    <PageSection
      icon={Sparkles}
      title="Advisory"
      description={`Overnight run, ${card.as_of}`}
      accent={fallback ? "warning" : "accent"}
    >
      <div className="space-y-3">
        <p className="text-sm font-medium">{card.headline}</p>

        {card.rationale ? (
          <p className="text-xs text-muted-foreground">{card.rationale}</p>
        ) : (
          <p className="rounded border border-warning/40 bg-warning/10 p-2 text-[11px] text-warning">
            Picked by the weighted score rather than the model, and flagged as
            such. The recommendation stands; only the explanation is lost.
          </p>
        )}

        {card.alternatives.length > 0 ? (
          <div>
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
              What was not picked
            </p>
            <ul className="mt-1 space-y-1">
              {card.alternatives.map((line) => (
                <li key={line} className="text-[10.5px] text-muted-foreground">
                  {line}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {card.ticket ? (
          <div className="rounded border border-border bg-surface-2/40 p-2.5 text-[11px]">
            <div className="flex items-baseline justify-between">
              <span className="text-muted-foreground">Would load</span>
              <span className="num font-medium">
                {sterling(card.ticket.principal_pence)} for{" "}
                {card.ticket.tenor_months} months at{" "}
                {perCent(card.ticket.rate_bp)}
              </span>
            </div>
            <p className="mt-1 text-[10px] text-muted-foreground">
              It then goes through the same six checks as anything a person
              typed.
            </p>
          </div>
        ) : null}

        {rejecting ? (
          <div className="space-y-2">
            <Input
              className="h-8 text-xs"
              placeholder="Say why. The next run learns from it."
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 flex-1 text-xs"
                disabled={busy || !reason.trim()}
                onClick={reject}
              >
                Reject
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 text-xs"
                onClick={() => setRejecting(false)}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              className="h-7 text-xs"
              disabled={busy || !card.ticket}
              onClick={accept}
            >
              Accept and load the ticket
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={() => onOpenRun(card.run_id)}
            >
              See the full run
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 text-xs"
              onClick={() => setRejecting(true)}
            >
              Reject
            </Button>
          </div>
        )}
      </div>
    </PageSection>
  );
}
