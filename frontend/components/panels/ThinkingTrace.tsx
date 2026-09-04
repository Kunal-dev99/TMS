"use client";

import { useEffect, useState } from "react";
import { Check, Loader2, Sparkles } from "lucide-react";

/**
 * Steps a treasury scenario actually goes through, shown to the reader.
 *
 * The point is not the animation. The point is that the reader learns what
 * the system is doing on their behalf, in the vocabulary of their own work.
 * The steps below are the real order of the server-side call; if it stops
 * being the real order, this component is the lie. Match the two.
 *
 * Timing: one step at a time, each one settling before the next fades in.
 * When the response arrives, any remaining steps flash through quickly so
 * the reader sees they were done rather than skipped.
 */
export function ThinkingTrace({
  steps,
  finished,
  intervalMs = 200,
  onFinished,
}: {
  steps: string[];
  /** True when the network call has returned; the trace may then race
      through the remaining steps but never skips them. */
  finished: boolean;
  intervalMs?: number;
  /** Called once every step has been shown AND the network is back. The
      parent uses this to hold the result until the reader has seen the
      reasoning. */
  onFinished?: () => void;
}) {
  const [shown, setShown] = useState(1);

  // Advance one step at a time. Every step gets a full interval even when
  // the response is already back, because the point of the trace is that
  // the reader sees the reasoning; racing past it defeats the exercise.
  useEffect(() => {
    if (shown >= steps.length) return;
    const id = window.setTimeout(() => setShown(shown + 1), intervalMs);
    return () => window.clearTimeout(id);
  }, [shown, steps.length, intervalMs]);

  // A new run resets the trace.
  useEffect(() => {
    setShown(1);
  }, [steps]);

  // Signal the parent when the reader has seen every step and the network
  // has come back. Either condition alone is not enough.
  useEffect(() => {
    if (finished && shown >= steps.length && onFinished) {
      onFinished();
    }
  }, [finished, shown, steps.length, onFinished]);

  return (
    <div
      className="mt-3 rounded-lg border border-primary/20 bg-primary/[.03] p-3"
      role="status"
      aria-live="polite"
    >
      <div className="mb-2 flex items-center gap-1.5">
        <Sparkles className="h-3 w-3 text-primary" aria-hidden />
        <span className="text-[9px] font-medium uppercase tracking-wider text-primary">
          Reasoning
        </span>
      </div>
      <ol className="space-y-1.5">
        {steps.slice(0, shown).map((step, index) => {
          const isCurrent = index === shown - 1 && !finished;
          const isDone = index < shown - 1 || finished;
          return (
            <li
              key={index}
              className={`flex items-start gap-2 text-[11px] leading-snug transition-opacity duration-200 ${
                isCurrent ? "text-foreground" : "text-muted-foreground"
              }`}
              style={{ opacity: 1 }}
            >
              <span className="mt-0.5 flex h-3 w-3 shrink-0 items-center justify-center">
                {isDone ? (
                  <Check className="h-3 w-3 text-primary" aria-hidden />
                ) : (
                  <Loader2
                    className="h-3 w-3 animate-spin text-primary"
                    aria-hidden
                  />
                )}
              </span>
              <span>{step}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}


/** The steps a rating-change scenario really goes through. */
export const RATING_CHANGE_STEPS = [
  "Taking a snapshot of the current book.",
  "Applying the rating action to a scratch copy.",
  "Tightening the limit to the new band's ceiling.",
  "Re-testing every position that names this counterparty.",
  "Rolling the scratch copy back so nothing is written.",
  "Reading the before-and-after into a paragraph.",
];


/** The steps a cap-change scenario really goes through. */
export const CAP_CHANGE_STEPS = [
  "Reading each credit group's share of the portfolio.",
  "Recomputing the concentration check at the new cap.",
  "Naming the groups that would cross the line.",
  "Reading the before-and-after into a paragraph.",
];


/** The steps a not-rolled scenario really goes through. */
export const NOT_ROLLED_STEPS = [
  "Reading the deal's stored accrual, day by day.",
  "Modelling the cash arrival on the maturity date.",
  "Recomputing the counterparty and group headroom.",
  "Estimating the daily interest that would stop.",
  "Reading the before-and-after into a paragraph.",
];
