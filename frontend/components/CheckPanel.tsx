"use client";

import type { CheckResult } from "@/lib/types";
import { PageSection } from "@/components/common/PageSection";
import { ShieldCheck, CheckCircle2, XCircle, Circle, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

const CHECK_ORDER = [
  ["COUNTERPARTY_ACTIVE", "Counterparty approved and active"],
  ["INSTRUMENT_PERMITTED", "Instrument permitted"],
  ["ENTITY_LIMIT", "Entity limit"],
  ["GROUP_LIMIT", "Group limit"],
  ["TENOR_BAND", "Term inside the rating band"],
  ["CONCENTRATION", "Concentration cap"],
] as const;

/**
 * The gate. The one element on the page allowed to be visually strong.
 *
 * Six rows, always. The panel is never absent, so its position never shifts
 * and nothing below it moves as results arrive. While a request is in flight
 * the previous result stays, because clearing it produces a flicker on every
 * keystroke and tells the user nothing.
 *
 * There is no check logic here. Every row is rendered from what the server
 * returned, including the amount a failed row would pass at.
 */
export function CheckPanel({
  result,
  onResize,
}: {
  result: CheckResult | null;
  onResize?: (pence: number) => void;
}) {
  return (
    <PageSection
      icon={ShieldCheck}
      title="The Six Checks"
      description="Real-time compliance gate testing deals against policy"
      accent="primary"
    >
      <div className="space-y-3">
        {CHECK_ORDER.map(([key, fallbackName]) => {
          const outcome = result?.checks.find((c) => c.key === key);
          const isPassed = outcome?.passed;
          const isFailed = outcome && !outcome.passed;

          return (
            <div
              key={key}
              className="flex items-start gap-3 py-2.5 border-b border-border/40 last:border-0"
            >
              <div className="mt-0.5 shrink-0">
                {outcome === undefined ? (
                  <Circle className="h-4 w-4 text-muted-foreground/40" />
                ) : isPassed ? (
                  <CheckCircle2 className="h-4 w-4 text-success" />
                ) : (
                  <XCircle className="h-4 w-4 text-destructive" />
                )}
              </div>

              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-foreground">
                    {outcome?.name ?? fallbackName}
                  </span>
                  {outcome ? (
                    <span
                      className={`text-[10px] font-semibold uppercase tracking-wider ${
                        isPassed ? "text-success" : "text-destructive"
                      }`}
                    >
                      {isPassed ? "Pass" : "Breach"}
                    </span>
                  ) : null}
                </div>

                {outcome ? (
                  <>
                    <div className="text-[11px] text-muted-foreground mt-0.5">
                      {outcome.detail}
                    </div>

                    {outcome.workings.length > 0 ? (
                      <ul className="mt-1.5 space-y-0.5 text-[10px] text-muted-foreground/80 list-disc list-inside font-mono bg-surface-2/40 p-2 rounded">
                        {outcome.workings.map((line) => (
                          <li key={line} className="truncate">
                            {line}
                          </li>
                        ))}
                      </ul>
                    ) : null}

                    {outcome.resize_to_pence !== null ? (
                      <div className="mt-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="h-7 text-xs gap-1.5 border-primary/40 text-primary hover:bg-primary/10"
                          onClick={() => onResize?.(outcome.resize_to_pence!)}
                        >
                          Resize to the amount that fits
                          <ArrowRight className="h-3 w-3" />
                        </Button>
                      </div>
                    ) : null}
                  </>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </PageSection>
  );
}
