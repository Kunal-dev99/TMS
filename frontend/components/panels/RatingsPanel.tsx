"use client";

import { useState } from "react";
import { SlidersHorizontal } from "lucide-react";

import { PanelShell } from "@/components/PanelShell";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  applyRatingAction,
  setClock,
  setEnforcement,
  whatIfRatingChange,
  type ScenarioResult,
} from "@/lib/api";
import { ScenarioResultCard } from "@/components/panels/ScenarioResult";
import {
  RATING_CHANGE_STEPS,
  ThinkingTrace,
} from "@/components/panels/ThinkingTrace";
import { Sparkles } from "lucide-react";
import { sterling } from "@/lib/format";
import type { BookRow, RatingBandView, StateResponse } from "@/lib/types";

/**
 * Ratings and policy.
 *
 * Kept behind the strip rather than on the surface, because a prominent
 * downgrade control makes a demonstration look staged. Nobody inside the
 * organisation triggers a rating action; it is the world moving, and the
 * interface should not suggest otherwise.
 *
 * Applying one closes the panel, reloads the state and opens the breaches
 * panel when the re-test raised any. That is the one place the interface
 * navigates on the user's behalf, because the result is the reason they
 * pressed it.
 */
export function RatingsPanel({
  open,
  onClose,
  state,
  onApplied,
}: {
  open: boolean;
  onClose: () => void;
  state: StateResponse;
  onApplied: (breachesRaised: number) => void;
}) {
  const [counterpartyId, setCounterpartyId] = useState("");
  const [rating, setRating] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [scenario, setScenario] = useState<ScenarioResult | null>(null);
  const [scenarioBusy, setScenarioBusy] = useState(false);
  // Held until the thinking trace has shown every step. The result is
  // already in memory; the trace controls the reveal.
  const [scenarioPending, setScenarioPending] = useState<ScenarioResult | null>(null);
  const [networkDone, setNetworkDone] = useState(false);

  const selected: BookRow | undefined = state.book.find(
    (row) => row.counterparty_id === counterpartyId,
  );
  const band: RatingBandView | undefined = state.rating_bands.find(
    (b) => b.rating === rating,
  );

  const apply = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await applyRatingAction(counterpartyId, rating);
      setOutcome(
        `${result.action.toLowerCase()}. ${result.positions_tested} position${
          result.positions_tested === 1 ? "" : "s"
        } re-tested, ${result.breaches_raised} breach${
          result.breaches_raised === 1 ? "" : "es"
        } raised.`,
      );
      onApplied(result.breaches_raised);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "That was refused.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelShell
      open={open}
      onClose={onClose}
      icon={SlidersHorizontal}
      title="Ratings and policy"
      description="The world moving, and the two settings that are still open"
    >
      <div className="space-y-6">
        <section className="space-y-3">
          <h3 className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Record a rating action
          </h3>

          <div className="space-y-1.5">
            <Label htmlFor="rating-cp" className="text-xs">
              Counterparty
            </Label>
            <select
              id="rating-cp"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
              value={counterpartyId}
              onChange={(event) => {
                setCounterpartyId(event.target.value);
                setOutcome(null);
              }}
            >
              <option value="">Choose a counterparty</option>
              {state.book.map((row) => (
                <option key={row.counterparty_id} value={row.counterparty_id}>
                  {row.name} — {row.rating}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="rating-new" className="text-xs">
              New rating
            </Label>
            <select
              id="rating-new"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
              value={rating}
              onChange={(event) => setRating(event.target.value)}
            >
              <option value="">Choose a rating</option>
              {state.rating_bands.map((b) => (
                <option key={b.rating} value={b.rating}>
                  {b.rating}
                </option>
              ))}
            </select>
          </div>

          {selected && band ? (
            <p className="rounded border border-border bg-surface-2/30 p-2 text-[10px] text-muted-foreground">
              {selected.name} holds {sterling(selected.used_pence)} against{" "}
              {sterling(selected.limit_pence)}. At {band.rating} the limit becomes{" "}
              {sterling(band.max_limit_pence)} to {band.max_tenor_months} months,
              and every live position is re-tested against it.
            </p>
          ) : null}

          {error ? (
            <p className="rounded border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
              {error}
            </p>
          ) : null}

          {outcome ? (
            <p className="rounded border border-warning/40 bg-warning/10 p-2 text-xs text-warning">
              {outcome}
            </p>
          ) : null}

          <div className="flex flex-col gap-2 sm:flex-row">
            {/* Preview first, then act. The gate a treasurer wants before
                changing anything: a paragraph and a list of what would
                move. Deterministic figures; the paragraph is the model's
                reading of them. */}
            <Button
              type="button"
              variant="outline"
              className="w-full gap-1.5 sm:w-auto"
              disabled={
                scenarioBusy || busy || !counterpartyId || !rating
              }
              onClick={async () => {
                setScenarioBusy(true);
                setScenario(null);
                setScenarioPending(null);
                setNetworkDone(false);
                try {
                  const result = await whatIfRatingChange({
                    counterparty_id: counterpartyId,
                    new_rating: rating,
                  });
                  setScenarioPending(result);
                  setNetworkDone(true);
                } catch (cause: unknown) {
                  setError(
                    cause instanceof Error
                      ? cause.message
                      : "That was refused.",
                  );
                  setScenarioBusy(false);
                }
              }}
            >
              <Sparkles className="h-3 w-3" aria-hidden />
              {scenarioBusy ? "Thinking..." : "What would this do?"}
            </Button>
            <Button
              type="button"
              className="w-full sm:flex-1"
              disabled={busy || !counterpartyId || !rating}
              onClick={apply}
            >
              Apply, and re-test the book
            </Button>
          </div>

          {scenarioBusy ? (
            <ThinkingTrace
              steps={RATING_CHANGE_STEPS}
              finished={networkDone}
              onFinished={() => {
                if (scenarioPending) setScenario(scenarioPending);
                setScenarioBusy(false);
              }}
            />
          ) : null}
          {scenario ? <ScenarioResultCard result={scenario} /> : null}
        </section>

        <section className="space-y-3 border-t border-border pt-5">
          <h3 className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Enforcement
          </h3>
          <p className="text-[10px] text-muted-foreground">
            Both are built as a policy setting, which takes the decision off
            the critical path. Settle it by flipping it on a failing deal in
            the room rather than in a slide. Changing it writes a new policy
            version, so runs recorded under the old one stay reproducible.
          </p>
          <div className="flex gap-2">
            {[
              { value: "HARD_BLOCK", label: "Hard block" },
              { value: "WARN_WITH_OVERRIDE", label: "Warn with an override" },
            ].map((option) => (
              <Button
                key={option.value}
                type="button"
                size="sm"
                variant={
                  state.enforcement === option.value ? "default" : "outline"
                }
                className="h-8 flex-1 text-xs"
                onClick={() =>
                  setEnforcement(option.value).then(() => onApplied(0))
                }
              >
                {option.label}
              </Button>
            ))}
          </div>
        </section>

        <section className="space-y-3 border-t border-border pt-5">
          <h3 className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            The clock
          </h3>
          <p className="text-[10px] text-muted-foreground">
            Everything derives from it. Moving it forward accrues interest on
            every deposit, which moves every measured exposure with it.
          </p>
          <div className="flex gap-2">
            <input
              type="date"
              defaultValue={state.as_of_date}
              className="flex h-8 flex-1 rounded-md border border-input bg-transparent px-3 text-xs"
              onChange={(event) => {
                if (event.target.value) {
                  setClock(event.target.value).then(() => onApplied(0));
                }
              }}
            />
          </div>
        </section>
      </div>
    </PanelShell>
  );
}
