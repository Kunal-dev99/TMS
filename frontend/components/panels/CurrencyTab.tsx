"use client";

import { useCallback, useEffect, useState } from "react";
import { Link2, Unlink } from "lucide-react";

import { EmptyState } from "@/components/PanelShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  getCurrencyExposure,
  linkHedge,
  recordCurrencyExposure,
  unlinkHedge,
} from "@/lib/api";
import { minorUnits, perCent, shortDate } from "@/lib/format";
import type { CurrencyExposureView, DealSummary } from "@/lib/types";

/**
 * The second thing called exposure.
 *
 * A forward increases counterparty exposure and reduces currency exposure.
 * They are never netted, and the warning is at the top of this tab rather
 * than only in the documentation, because the interface is where somebody
 * would try it.
 *
 * Every figure here is minor units with its currency beside it. Nothing on
 * this tab is in pence, and there is no total that spans the two tabs,
 * because there is no endpoint that would return one.
 *
 * Each hedge is shown indented under the exposure it covers. Without that
 * link you own forwards and cannot say anything is covered.
 */
const UNLINK_REASONS = [
  { value: "ROLLED", label: "Rolled" },
  { value: "CLOSED_EARLY", label: "Closed early" },
  { value: "EXPOSURE_CANCELLED", label: "Exposure cancelled" },
  { value: "REALLOCATED", label: "Reallocated" },
];

const STATUS_TONE: Record<string, string> = {
  IDENTIFIED: "border-border text-muted-foreground",
  PARTIALLY_COVERED: "border-warning/40 text-warning",
  COVERED: "border-success/40 text-success",
  SETTLED: "border-border text-muted-foreground",
};

export function CurrencyTab({
  deals,
  currency = "EUR",
}: {
  deals: DealSummary[];
  currency?: string;
}) {
  const [view, setView] = useState<CurrencyExposureView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [linkingTo, setLinkingTo] = useState<string | null>(null);

  const load = useCallback(
    (signal?: AbortSignal) => {
      getCurrencyExposure(currency, signal)
        .then(setView)
        .catch(() => undefined);
    },
    [currency],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  /** Only a forward can cover a currency obligation. */
  const forwards = deals.filter(
    (deal) => deal.instrument === "FX_FORWARD" && deal.status !== "CLOSED",
  );

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
      load();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "That was refused.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-warning/40 bg-warning/10 p-4">
        <p className="text-xs font-medium text-warning">
          {view?.warning ??
            "Counterparty exposure and currency exposure are separate figures moving in opposite directions. They are never netted."}
        </p>
        <p className="mt-1.5 text-[10px] text-muted-foreground">
          A forward increases the first and reduces the second. There is no
          endpoint that returns both, and no query joins them.
        </p>
      </div>

      {error ? (
        <p className="rounded border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
          {error}
        </p>
      ) : null}

      {view === null ? (
        <EmptyState>Reading the register.</EmptyState>
      ) : (
        <>
          <section>
            <h3 className="mb-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Net obligation by time bucket, against the cover target
            </h3>
            <div className="space-y-2.5">
              {view.buckets.map((bucket) => (
                <div key={bucket.bucket}>
                  <div className="flex items-baseline justify-between gap-3 text-xs">
                    <span>{bucket.bucket.replace(/_/g, " ").toLowerCase()}</span>
                    <span className="num">
                      {minorUnits(bucket.covered_minor, view.currency)} covered of{" "}
                      {minorUnits(bucket.net_minor, view.currency)}
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
                    <div
                      className={`h-full rounded-full ${
                        bucket.net_minor <= 0
                          ? "bg-border"
                          : bucket.covered_bp >= bucket.target_cover_bp
                            ? "bg-success"
                            : "bg-warning"
                      }`}
                      style={{
                        width: `${Math.min(100, bucket.covered_bp / 100)}%`,
                      }}
                    />
                  </div>
                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                    {bucket.net_minor <= 0
                      ? "Nothing owed in this bucket."
                      : `${perCent(bucket.covered_bp)} covered, against a target of ${perCent(bucket.target_cover_bp)}.` +
                        (bucket.covered_bp < bucket.target_cover_bp
                          ? ` ${minorUnits(
                              Math.round(
                                (bucket.net_minor * bucket.target_cover_bp) / 10000,
                              ) - bucket.covered_minor,
                              view.currency,
                            )} short.`
                          : "")}
                  </p>
                </div>
              ))}
            </div>
          </section>

          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                Obligations, and what covers each
              </h3>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-6 text-[10px]"
                onClick={() => setCapturing((open) => !open)}
              >
                {capturing ? "Cancel" : "Record an obligation"}
              </Button>
            </div>

            {capturing ? (
              <CaptureForm
                currency={view.currency}
                busy={busy}
                onSubmit={(body) =>
                  run(async () => {
                    await recordCurrencyExposure(body);
                    setCapturing(false);
                  })
                }
              />
            ) : null}

            {view.exposures.length === 0 ? (
              <EmptyState>
                No obligations recorded. An exposure exists before any hedge,
                and often outlives several of them.
              </EmptyState>
            ) : (
              <div className="space-y-3">
                {view.exposures.map((exposure) => (
                  <article
                    key={exposure.id}
                    className="rounded-lg border border-border bg-surface-2/20 p-3"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="num text-sm font-medium">
                          {minorUnits(exposure.amount_minor, exposure.currency)}{" "}
                          <span className="text-[10px] font-normal uppercase tracking-wider text-muted-foreground">
                            {exposure.direction.toLowerCase()}
                          </span>
                        </p>
                        <p className="text-[10px] text-muted-foreground">
                          {exposure.source.replace(/_/g, " ").toLowerCase()}
                          {exposure.source_reference
                            ? ` ${exposure.source_reference}`
                            : ""}
                          {" · due "}
                          {shortDate(exposure.expected_date)}
                        </p>
                      </div>
                      <span
                        className={`shrink-0 rounded-sm border px-1.5 py-0.5 text-[9px] uppercase tracking-wider ${
                          STATUS_TONE[exposure.status] ?? STATUS_TONE.IDENTIFIED
                        }`}
                      >
                        {exposure.status.replace(/_/g, " ").toLowerCase()}
                      </span>
                    </div>

                    {/* Indented under the exposure it covers. */}
                    {exposure.hedges.length > 0 ? (
                      <ul className="mt-2 space-y-1.5 border-l border-border pl-3">
                        {exposure.hedges.map((hedge) => (
                          <li
                            key={hedge.id}
                            className="flex items-center justify-between gap-2"
                          >
                            <span className="flex items-center gap-1.5 text-[11px]">
                              <Link2 className="h-3 w-3 text-muted-foreground" />
                              <span className="num">
                                {minorUnits(
                                  hedge.covered_amount_minor,
                                  hedge.currency,
                                )}
                              </span>
                              <span className="text-[10px] text-muted-foreground">
                                {/* Named, not an identifier. A treasurer
                                    reads counterparties, not primary keys. */}
                                forward with{" "}
                                {deals.find((deal) => deal.id === hedge.deal_id)
                                  ?.counterparty_name ?? "a counterparty"}
                              </span>
                            </span>
                            <select
                              className="h-6 rounded border border-input bg-transparent px-1 text-[10px]"
                              defaultValue=""
                              disabled={busy}
                              onChange={(event) => {
                                if (!event.target.value) return;
                                const reason = event.target.value;
                                event.target.value = "";
                                run(() => unlinkHedge(hedge.id, reason));
                              }}
                            >
                              <option value="">Unlink…</option>
                              {UNLINK_REASONS.map((reason) => (
                                <option key={reason.value} value={reason.value}>
                                  {reason.label}
                                </option>
                              ))}
                            </select>
                          </li>
                        ))}
                      </ul>
                    ) : null}

                    {exposure.status !== "COVERED" &&
                    exposure.status !== "SETTLED" ? (
                      linkingTo === exposure.id ? (
                        <LinkForm
                          forwards={forwards}
                          currency={exposure.currency}
                          busy={busy}
                          onCancel={() => setLinkingTo(null)}
                          onSubmit={(dealId, amount) =>
                            run(async () => {
                              await linkHedge(exposure.id, dealId, amount);
                              setLinkingTo(null);
                            })
                          }
                        />
                      ) : (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="mt-2 h-6 gap-1 text-[10px]"
                          disabled={forwards.length === 0}
                          onClick={() => setLinkingTo(exposure.id)}
                        >
                          <Link2 className="h-3 w-3" />
                          {forwards.length === 0
                            ? "No forward to link"
                            : "Link a forward"}
                        </Button>
                      )
                    ) : null}
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function CaptureForm({
  currency,
  busy,
  onSubmit,
}: {
  currency: string;
  busy: boolean;
  onSubmit: (body: {
    currency: string;
    amount_minor: number;
    direction: string;
    expected_date: string;
    source: string;
    source_reference: string | null;
  }) => void;
}) {
  const [amount, setAmount] = useState("");
  const [direction, setDirection] = useState("PAYABLE");
  const [date, setDate] = useState("");
  const [source, setSource] = useState("PURCHASE_ORDER");
  const [reference, setReference] = useState("");

  return (
    <div className="mb-3 space-y-2 rounded-lg border border-border bg-card p-3">
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label className="text-[10px]">Amount ({currency})</Label>
          <Input
            className="num h-8 text-xs"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            placeholder="4,000,000"
          />
        </div>
        <div className="space-y-1">
          <Label className="text-[10px]">Direction</Label>
          <select
            className="flex h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs"
            value={direction}
            onChange={(event) => setDirection(event.target.value)}
          >
            <option value="PAYABLE">Payable</option>
            <option value="RECEIVABLE">Receivable</option>
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label className="text-[10px]">Expected</Label>
          <input
            type="date"
            className="flex h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs"
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label className="text-[10px]">Source</Label>
          <select
            className="flex h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs"
            value={source}
            onChange={(event) => setSource(event.target.value)}
          >
            <option value="PURCHASE_ORDER">Purchase order</option>
            <option value="CONTRACT">Contract</option>
            <option value="INVOICE">Invoice</option>
            <option value="FORECAST">Forecast</option>
          </select>
        </div>
      </div>
      <div className="space-y-1">
        <Label className="text-[10px]">Reference</Label>
        <Input
          className="h-8 text-xs"
          value={reference}
          onChange={(event) => setReference(event.target.value)}
          placeholder="PO-2026-4471"
        />
      </div>
      <Button
        type="button"
        size="sm"
        className="h-7 w-full text-xs"
        disabled={busy || !amount.trim() || !date}
        onClick={() =>
          onSubmit({
            currency,
            amount_minor: Math.round(Number(amount.replace(/,/g, "")) * 100),
            direction,
            expected_date: date,
            source,
            source_reference: reference.trim() || null,
          })
        }
      >
        Record
      </Button>
    </div>
  );
}

function LinkForm({
  forwards,
  currency,
  busy,
  onCancel,
  onSubmit,
}: {
  forwards: DealSummary[];
  currency: string;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (dealId: string, coveredAmountMinor: number) => void;
}) {
  const [dealId, setDealId] = useState(forwards[0]?.id ?? "");
  const [amount, setAmount] = useState("");

  return (
    <div className="mt-2 space-y-2 rounded border border-border bg-card p-2">
      <select
        className="flex h-7 w-full rounded border border-input bg-transparent px-2 text-[11px]"
        value={dealId}
        onChange={(event) => setDealId(event.target.value)}
      >
        {forwards.map((deal) => (
          <option key={deal.id} value={deal.id}>
            {deal.counterparty_name}, {deal.tenor_months} months
          </option>
        ))}
      </select>
      <Input
        className="num h-7 text-[11px]"
        placeholder={`Amount covered (${currency})`}
        value={amount}
        onChange={(event) => setAmount(event.target.value)}
      />
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          className="h-6 flex-1 text-[10px]"
          disabled={busy || !dealId || !amount.trim()}
          onClick={() =>
            onSubmit(dealId, Math.round(Number(amount.replace(/,/g, "")) * 100))
          }
        >
          Link
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-6 text-[10px]"
          onClick={onCancel}
        >
          <Unlink className="mr-1 h-3 w-3" />
          Cancel
        </Button>
      </div>
    </div>
  );
}
