"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { PlusCircle } from "lucide-react";

import { PageSection } from "@/components/common/PageSection";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { checkDeal } from "@/lib/api";
import { perCent } from "@/lib/format";
import type { BookRow, CheckResult, Instrument, TicketFields } from "@/lib/types";

/** A pause in typing produces one call. */
const DEBOUNCE_MS = 150;

const INSTRUMENTS: Instrument[] = ["DEPOSIT", "FX_FORWARD", "MMF", "GILT"];

export interface TicketState {
  counterpartyId: string;
  instrument: Instrument;
  /** Held as the string the user typed, so a half typed number is not a zero. */
  principal: string;
  tenor: string;
  rate: string;
}

export const EMPTY_TICKET: TicketState = {
  counterpartyId: "",
  instrument: "DEPOSIT",
  principal: "",
  tenor: "6",
  rate: "4.25",
};

export function toFields(ticket: TicketState): TicketFields | null {
  const principal = Number(ticket.principal.replace(/,/g, ""));
  const tenor = Number(ticket.tenor);
  const rate = Number(ticket.rate);
  if (!ticket.counterpartyId) return null;
  if (!Number.isFinite(principal) || principal <= 0) return null;
  if (!Number.isFinite(tenor) || tenor < 1) return null;
  if (!Number.isFinite(rate) || rate < 0) return null;
  return {
    counterparty_id: ticket.counterpartyId,
    instrument: ticket.instrument,
    principal_pence: Math.round(principal * 100),
    tenor_months: Math.round(tenor),
    rate_bp: Math.round(rate * 100),
  };
}

/**
 * Propose a deal. Five fields.
 *
 * Counterparty, instrument, principal, term, rate. Nothing else is needed to
 * test a deal, and a sixth field would be a sixth thing to get wrong in a
 * demonstration.
 *
 * Every change triggers a check, debounced at 150 milliseconds, with the
 * previous request cancelled. While a request is in flight the previous
 * result stays on screen: clearing it produces a flicker on every keystroke
 * and tells the user nothing.
 *
 * Enter does not submit. Recording a deal is deliberate, and the check panel
 * is changing under the user as they type.
 */
export function Ticket({
  ticket,
  onChange,
  book,
  onResult,
  onRecord,
  recording,
  result,
  enforcement,
}: {
  ticket: TicketState;
  onChange: (next: TicketState) => void;
  book: BookRow[];
  onResult: (result: CheckResult | null) => void;
  onRecord: (overrideReason?: string) => void;
  recording: boolean;
  result: CheckResult | null;
  enforcement: string;
}) {
  const [overrideReason, setOverrideReason] = useState("");
  const inFlight = useRef<AbortController | null>(null);
  const fields = toFields(ticket);
  const serialised = fields ? JSON.stringify(fields) : null;

  const runCheck = useCallback(
    (payload: TicketFields) => {
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;

      checkDeal(payload, controller.signal)
        .then(onResult)
        .catch((cause: unknown) => {
          // An abort is the newer keystroke doing its job, not a failure.
          if (controller.signal.aborted) return;
          if (cause instanceof DOMException && cause.name === "AbortError") return;
          onResult(null);
        });
    },
    [onResult],
  );

  useEffect(() => {
    if (!serialised) {
      inFlight.current?.abort();
      onResult(null);
      return;
    }
    const timer = setTimeout(() => runCheck(JSON.parse(serialised) as TicketFields), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [serialised, runCheck, onResult]);

  useEffect(() => () => inFlight.current?.abort(), []);

  const blocked = result?.outcome === "FAIL";
  const canOverride = blocked && enforcement === "WARN_WITH_OVERRIDE";
  const active = book.filter((row) => row.status === "ACTIVE");

  return (
    <PageSection
      icon={PlusCircle}
      title="Propose a Deal"
      description="Five fields. The checks run as you type and persist nothing."
      accent="primary"
    >
      <form
        className="space-y-3"
        onSubmit={(event) => {
          // Enter does not submit. The panel is changing under the user.
          event.preventDefault();
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="counterparty" className="text-xs">
            Counterparty
          </Label>
          <select
            id="counterparty"
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            value={ticket.counterpartyId}
            onChange={(event) =>
              onChange({ ...ticket, counterpartyId: event.target.value })
            }
          >
            <option value="">Choose a counterparty</option>
            {active.map((row) => (
              <option key={row.counterparty_id} value={row.counterparty_id}>
                {row.name} — {row.rating}
              </option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="instrument" className="text-xs">
              Instrument
            </Label>
            <select
              id="instrument"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              value={ticket.instrument}
              onChange={(event) =>
                onChange({ ...ticket, instrument: event.target.value as Instrument })
              }
            >
              {INSTRUMENTS.map((instrument) => (
                <option key={instrument} value={instrument}>
                  {instrument.replace("_", " ").toLowerCase()}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="principal" className="text-xs">
              Principal (£)
            </Label>
            <Input
              id="principal"
              inputMode="decimal"
              placeholder="10,000,000"
              value={ticket.principal}
              onChange={(event) =>
                onChange({ ...ticket, principal: event.target.value })
              }
              className="num"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="tenor" className="text-xs">
              Term (months)
            </Label>
            <Input
              id="tenor"
              inputMode="numeric"
              value={ticket.tenor}
              onChange={(event) => onChange({ ...ticket, tenor: event.target.value })}
              className="num"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="rate" className="text-xs">
              Rate (%)
            </Label>
            <Input
              id="rate"
              inputMode="decimal"
              value={ticket.rate}
              onChange={(event) => onChange({ ...ticket, rate: event.target.value })}
              className="num"
            />
            {fields ? (
              <p className="text-[10px] text-muted-foreground">
                {perCent(fields.rate_bp)} as basis points
              </p>
            ) : null}
          </div>
        </div>

        {/* The override reason appears inline, never in a dialog. */}
        {canOverride ? (
          <div className="space-y-1.5">
            <Label htmlFor="override" className="text-xs text-warning">
              Reason for the override
            </Label>
            <Input
              id="override"
              placeholder="Required. This puts the book outside policy."
              value={overrideReason}
              onChange={(event) => setOverrideReason(event.target.value)}
            />
          </div>
        ) : null}

        <div className="pt-1">
          <Button
            type="button"
            className="w-full"
            disabled={!fields || recording || (canOverride && !overrideReason.trim())}
            variant={blocked && !canOverride ? "outline" : "default"}
            onClick={() => onRecord(canOverride ? overrideReason : undefined)}
          >
            {recording
              ? "Recording"
              : canOverride
                ? "Override and record"
                : blocked
                  ? "Record deal, and go to the queue"
                  : "Record deal"}
          </Button>
        </div>
      </form>
    </PageSection>
  );
}
