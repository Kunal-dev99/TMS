"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeftRight,
  ArrowRight,
  Check,
  CheckCircle2,
  Loader2,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  adviseHedge,
  checkHedge,
  getFxCounterparties,
  getFxForwardRate,
  initiateHedge,
  type FxCounterparty,
  type FxRateQuote,
} from "@/lib/api";
import type { CheckResult } from "@/lib/types";

/**
 * Initiate FX forward hedge — modal launched from the Hedging panel.
 *
 * Two columns. Left: exposure context (read-only). Right: hedge inputs.
 * Guardrails: cannot hedge more than the available unhedged balance;
 * the amount is capped and % chips clamp too. The forward rate is
 * fetched from the mock rate service and is labelled indicative.
 */
export function InitiateHedgeModal({
  open,
  onClose,
  onDone,
  currency,
  exposureIds,
  unhedgedMinor,
  label,
  prefillAmountMinor,
  prefillTenorMonths,
  prefillCounterpartyId,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
  currency: string;
  exposureIds: string[];
  unhedgedMinor: number;
  label: string;
  prefillAmountMinor?: number;
  prefillTenorMonths?: number;
  prefillCounterpartyId?: string;
}) {
  const [counterparties, setCounterparties] = useState<FxCounterparty[]>([]);
  const [rate, setRate] = useState<FxRateQuote | null>(null);
  const [amountMinor, setAmountMinor] = useState(0);
  const [tenor, setTenor] = useState(6);
  const [counterpartyId, setCounterpartyId] = useState<string>("");
  const [reference, setReference] = useState("");
  const [comments, setComments] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [check, setCheck] = useState<CheckResult | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  const checkAbort = useRef<AbortController | null>(null);
  const [advice, setAdvice] = useState<string[] | null>(null);
  const [adviceLoading, setAdviceLoading] = useState(false);
  const adviceAbort = useRef<AbortController | null>(null);

  const pair = `${currency}_GBP`;

  useEffect(() => {
    if (!open) return;
    setAmountMinor(
      prefillAmountMinor && prefillAmountMinor > 0
        ? Math.min(prefillAmountMinor, unhedgedMinor)
        : Math.round(unhedgedMinor * 0.5),
    );
    setTenor(prefillTenorMonths ?? 6);
    setReference("");
    setComments("");
    setError(null);
    getFxCounterparties()
      .then((rows) => {
        setCounterparties(rows);
        if (
          prefillCounterpartyId &&
          rows.some((r) => r.id === prefillCounterpartyId)
        ) {
          setCounterpartyId(prefillCounterpartyId);
        } else if (rows.length > 0) {
          setCounterpartyId(rows[0].id);
        }
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, [open, unhedgedMinor, prefillAmountMinor, prefillTenorMonths, prefillCounterpartyId]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    getFxForwardRate(pair, tenor)
      .then((q) => !cancelled && setRate(q))
      .catch((e) => !cancelled && setError(String(e.message ?? e)));
    return () => {
      cancelled = true;
    };
  }, [open, pair, tenor]);

  // AI advisor — concentration, headroom, ladder, policy gap. Governance
  // narration only; the module never comments on FX rate direction.
  useEffect(() => {
    if (!open || !counterpartyId || amountMinor <= 0) {
      setAdvice(null);
      return;
    }
    adviceAbort.current?.abort();
    const controller = new AbortController();
    adviceAbort.current = controller;
    setAdviceLoading(true);
    const handle = setTimeout(() => {
      adviseHedge(
        {
          currency,
          sell_amount_minor: amountMinor,
          tenor_months: tenor,
          counterparty_id: counterpartyId,
        },
        controller.signal,
      )
        .then((r) => {
          if (!controller.signal.aborted) setAdvice(r.observations);
        })
        .catch(() => {
          /* aborted or transient */
        })
        .finally(() => {
          if (!controller.signal.aborted) setAdviceLoading(false);
        });
    }, 350);
    return () => {
      clearTimeout(handle);
      controller.abort();
    };
  }, [open, counterpartyId, amountMinor, tenor, currency]);

  // Live six-check pre-flight. Fires whenever inputs settle. Same
  // pattern the deposit ticket uses — the treasurer sees the verdict
  // before Initiate is clicked.
  useEffect(() => {
    if (!open || !counterpartyId || amountMinor <= 0) {
      setCheck(null);
      return;
    }
    checkAbort.current?.abort();
    const controller = new AbortController();
    checkAbort.current = controller;
    const handle = setTimeout(() => {
      checkHedge(
        {
          currency,
          sell_amount_minor: amountMinor,
          tenor_months: tenor,
          counterparty_id: counterpartyId,
        },
        controller.signal,
      )
        .then((r) => {
          if (!controller.signal.aborted) setCheck(r);
        })
        .catch(() => {
          /* aborted or transient; the button stays gated on the last known result */
        });
    }, 250);
    return () => {
      clearTimeout(handle);
      controller.abort();
    };
  }, [open, counterpartyId, amountMinor, tenor, currency]);

  const gbpValue = useMemo(() => {
    if (!rate) return 0;
    return Math.round(amountMinor * rate.forward);
  }, [amountMinor, rate]);

  const overHedge = amountMinor > unhedgedMinor;
  const invalidAmount = amountMinor <= 0;

  const setPct = (pct: number) =>
    setAmountMinor(Math.round((unhedgedMinor * pct) / 100));

  const failedChecks = check !== null && check.outcome === "FAIL";
  const softOverrideAvailable = failedChecks && check?.enforcement !== "HARD_BLOCK";
  const overrideBlocked = failedChecks && !softOverrideAvailable;
  const overrideMissingReason =
    softOverrideAvailable && overrideReason.trim().length === 0;

  const submit = async () => {
    if (overHedge || invalidAmount || !counterpartyId || submitting) return;
    if (overrideBlocked) return;
    if (overrideMissingReason) return;
    setSubmitting(true);
    setError(null);
    try {
      await initiateHedge({
        currency,
        sell_amount_minor: amountMinor,
        tenor_months: tenor,
        counterparty_id: counterpartyId,
        exposure_ids: exposureIds,
        reference: reference || undefined,
        comments: comments || undefined,
        override_reason: failedChecks ? overrideReason : undefined,
      });
      onDone();
      onClose();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSubmitting(false);
    }
  };

  const selectedCp = counterparties.find((cp) => cp.id === counterpartyId) ?? null;

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-3 sm:p-4 overflow-y-auto">
      <div className="w-full max-w-2xl rounded-xl border border-border bg-surface-1 shadow-2xl overflow-hidden my-auto max-h-[92vh] flex flex-col">
        {/* Institutional Header */}
        <div className="flex items-center justify-between border-b border-border bg-surface-2/40 px-5 py-3.5 shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/15 text-primary">
              <ArrowLeftRight className="h-4 w-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold text-foreground">Initiate FX Forward Hedge</h2>
                <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[9.5px] font-bold uppercase tracking-wider text-primary">
                  FX_FORWARD
                </span>
                <span className="rounded border border-border/80 bg-surface-2 px-1.5 py-0.5 text-[9.5px] font-semibold text-muted-foreground">
                  Sell {currency} / Buy GBP
                </span>
              </div>
              <p className="text-[10.5px] text-muted-foreground">
                {label} · Allocated pro-rata across {exposureIds.length} forecast receivables
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1.5 text-muted-foreground hover:bg-surface-2 hover:text-foreground transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Scrollable Modal Body */}
        <div className="overflow-y-auto flex-1 p-5 space-y-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {/* Left: Exposure Profile & Context */}
            <div className="space-y-3 rounded-lg border border-border bg-surface-2/40 p-3.5">
              <div className="flex items-center justify-between">
                <h3 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                  Exposure Profile
                </h3>
                <span className="rounded border border-primary/20 bg-primary/10 px-1.5 py-0.5 text-[9.5px] font-bold text-primary">
                  {currency} / GBP
                </span>
              </div>

              <div className="rounded-md border border-border/60 bg-background p-3">
                <span className="text-[10px] uppercase font-semibold text-muted-foreground block">
                  Available Unhedged
                </span>
                <span className="num text-xl font-extrabold text-warning block">
                  {formatMoney(unhedgedMinor, currency)}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  From scheduled ERP/EPM receivables
                </span>
              </div>

              <div className="space-y-2 text-xs">
                <div className="flex justify-between py-1 border-b border-border/40">
                  <span className="text-muted-foreground">Hedge Direction</span>
                  <span className="font-semibold text-foreground">Sell {currency} / Buy GBP</span>
                </div>
                <div className="flex justify-between py-1 border-b border-border/40">
                  <span className="text-muted-foreground">Linked Receivables</span>
                  <span className="num font-semibold text-foreground">{exposureIds.length} invoices</span>
                </div>
                <div className="flex justify-between py-1 border-b border-border/40">
                  <span className="text-muted-foreground">Post-Hedge Unhedged</span>
                  <span className={`num font-semibold ${amountMinor >= unhedgedMinor ? "text-success" : "text-muted-foreground"}`}>
                    {formatMoney(Math.max(0, unhedgedMinor - amountMinor), currency)}
                  </span>
                </div>
              </div>

              <div className="rounded-lg bg-surface-2/60 p-2.5 text-[10.5px] leading-relaxed text-muted-foreground border border-border/40">
                <p>
                  The forward will be pro-rated across the underlying receivables in this bucket. Booked as an <strong className="text-foreground">FX_FORWARD</strong> Deal linked via HedgeLink.
                </p>
              </div>
            </div>

            {/* Right: Hedge Inputs & Sizing */}
            <div className="space-y-3.5">
              <div>
                <div className="flex items-baseline justify-between">
                  <label className="text-[10.5px] font-semibold text-foreground">
                    Hedge Amount ({currency})
                  </label>
                  <span className="text-[10px] text-muted-foreground">
                    Max: {formatMoney(unhedgedMinor, currency)}
                  </span>
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <div className="relative flex-1">
                    <input
                      type="number"
                      min={0}
                      max={unhedgedMinor / 100}
                      step={1000}
                      value={Math.round(amountMinor / 100)}
                      onChange={(e) =>
                        setAmountMinor(Math.max(0, Math.round(Number(e.target.value) * 100)))
                      }
                      className={`w-full rounded-md border bg-background px-3 py-1.5 text-right num text-xs font-semibold focus:ring-1 focus:ring-primary outline-none ${
                        overHedge ? "border-destructive text-destructive" : "border-border"
                      }`}
                    />
                  </div>
                  <span className="rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-[11px] font-bold text-foreground">
                    {currency}
                  </span>
                </div>

                {/* Quick % chips */}
                <div className="mt-1.5 grid grid-cols-4 gap-1.5">
                  {[
                    { label: "25%", val: 25 },
                    { label: "50%", val: 50 },
                    { label: "75%", val: 75 },
                    { label: "100%", val: 100 },
                  ].map((p) => {
                    const targetAmount = Math.round((unhedgedMinor * p.val) / 100);
                    const isSelected = Math.abs(amountMinor - targetAmount) < 100;
                    return (
                      <button
                        key={p.val}
                        type="button"
                        onClick={() => setPct(p.val)}
                        className={`rounded-md border py-1 text-[10.5px] font-semibold transition-all ${
                          isSelected
                            ? "border-primary bg-primary text-primary-foreground shadow-xs"
                            : "border-border bg-surface-2/60 text-muted-foreground hover:border-primary/60 hover:text-foreground"
                        }`}
                      >
                        {p.label}
                      </button>
                    );
                  })}
                </div>
                {overHedge ? (
                  <p className="mt-1 text-[10px] text-destructive flex items-center gap-1 font-medium">
                    <AlertTriangle className="h-3 w-3 shrink-0" />
                    <span>Cannot exceed available unhedged of {formatMoney(unhedgedMinor, currency)}.</span>
                  </p>
                ) : null}
              </div>

              {/* Tenor & Quick Market Tenor Chips */}
              <div>
                <div className="flex items-baseline justify-between">
                  <label className="text-[10.5px] font-semibold text-foreground">
                    Tenor & Maturity
                  </label>
                  <span className="num text-xs font-bold text-primary">
                    {tenor} Month{tenor > 1 ? "s" : ""}
                  </span>
                </div>

                <div className="mt-1.5 grid grid-cols-5 gap-1">
                  {[1, 3, 6, 9, 12].map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setTenor(m)}
                      className={`rounded-md border py-1 text-[10px] font-semibold transition-all ${
                        tenor === m
                          ? "border-primary bg-primary text-primary-foreground shadow-xs"
                          : "border-border bg-surface-2/60 text-muted-foreground hover:border-primary/60 hover:text-foreground"
                      }`}
                    >
                      {m}M
                    </button>
                  ))}
                </div>

                <input
                  type="range"
                  min={1}
                  max={12}
                  value={tenor}
                  onChange={(e) => setTenor(Number(e.target.value))}
                  className="mt-2 w-full accent-[hsl(var(--primary))]"
                />
              </div>

              {/* Counterparty selector */}
              <div>
                <label className="text-[10.5px] font-semibold text-foreground">
                  Approved Counterparty
                </label>
                <select
                  value={counterpartyId}
                  onChange={(e) => setCounterpartyId(e.target.value)}
                  className="mt-1 w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs font-medium focus:ring-1 focus:ring-primary outline-none"
                >
                  {counterparties.map((cp) => (
                    <option key={cp.id} value={cp.id}>
                      {cp.name} ({cp.rating}) · Free CP: {formatMoney(cp.entity_headroom_pence, "GBP")}{cp.near_cap ? " [NEAR CAP]" : ""}
                    </option>
                  ))}
                </select>

                {selectedCp ? (
                  <div className="mt-1.5 grid grid-cols-2 gap-2 rounded-lg border border-border/70 bg-surface-2/40 p-2 text-[10px]">
                    <div>
                      <div className="flex justify-between text-muted-foreground mb-0.5">
                        <span>Entity Headroom</span>
                        <span className="font-bold text-foreground">
                          {formatMoney(selectedCp.entity_headroom_pence, "GBP")}
                        </span>
                      </div>
                      <div className="h-1 w-full overflow-hidden rounded bg-surface-2">
                        <div
                          className="h-full bg-primary"
                          style={{
                            width: `${Math.max(
                              5,
                              Math.min(
                                100,
                                selectedCp.entity_limit_pence > 0
                                  ? ((selectedCp.entity_limit_pence - selectedCp.entity_headroom_pence) / selectedCp.entity_limit_pence) * 100
                                  : 0
                              )
                            )}%`,
                          }}
                        />
                      </div>
                    </div>
                    <div>
                      <div className="flex justify-between text-muted-foreground mb-0.5">
                        <span>Group Headroom</span>
                        <span className="font-bold text-foreground">
                          {formatMoney(selectedCp.group_headroom_pence, "GBP")}
                        </span>
                      </div>
                      <div className="h-1 w-full overflow-hidden rounded bg-surface-2">
                        <div
                          className="h-full bg-primary"
                          style={{
                            width: `${Math.max(
                              5,
                              Math.min(
                                100,
                                selectedCp.group_limit_pence > 0
                                  ? ((selectedCp.group_limit_pence - selectedCp.group_headroom_pence) / selectedCp.group_limit_pence) * 100
                                  : 0
                              )
                            )}%`,
                          }}
                        />
                      </div>
                    </div>
                    {selectedCp.near_cap ? (
                      <div className="col-span-2 text-[9.5px] font-semibold text-warning flex items-center gap-1">
                        <AlertTriangle className="h-3 w-3" />
                        <span>Bank is near single-name concentration capacity (&lt;20% remaining).</span>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>

              {/* FX Pricing & Economics Card */}
              {rate ? (
                <div className="rounded-lg border border-border bg-surface-2/40 p-3 text-xs space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                      FX Pricing Economics
                    </span>
                    <span className="text-[9.5px] italic text-muted-foreground">
                      {rate.source} · {rate.quality}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-[11px]">
                    <div>
                      <span className="text-muted-foreground block text-[10px]">Spot Rate ({rate.pair})</span>
                      <span className="num font-semibold text-foreground">{rate.spot.toFixed(4)}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground block text-[10px]">Forward Rate ({rate.tenor_months}m)</span>
                      <span className="num font-bold text-foreground">
                        {rate.forward.toFixed(4)}{" "}
                        <span className="text-muted-foreground font-normal text-[10px]">
                          ({rate.forward_points_bp > 0 ? "+" : ""}{rate.forward_points_bp}bp)
                        </span>
                      </span>
                    </div>
                  </div>
                  <div className="border-t border-border/40 pt-2 flex items-center justify-between">
                    <span className="text-[11px] font-medium text-muted-foreground">
                      Protected GBP Value:
                    </span>
                    <span className="num text-sm font-extrabold text-primary flex items-center gap-1">
                      <ArrowRight className="h-3 w-3" />
                      £{(gbpValue / 100).toLocaleString("en-GB", { maximumFractionDigits: 0 })}
                    </span>
                  </div>
                </div>
              ) : null}

              <div>
                <label className="text-[10.5px] font-medium text-muted-foreground">
                  Reference / Comments
                </label>
                <input
                  type="text"
                  placeholder="e.g. Q1 EPM forecast hedge"
                  value={reference}
                  onChange={(e) => setReference(e.target.value)}
                  className="mt-1 w-full rounded-md border border-border bg-background px-2.5 py-1 text-xs outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
            </div>
          </div>

          {/* Six-Checks Pre-flight Card */}
          {check ? (
            <div className="rounded-lg border border-border bg-surface-2/40 p-3.5">
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider">
                  <ShieldCheck className="h-3.5 w-3.5 text-primary" />
                  <span>Six-Check Policy Pre-Flight</span>
                </div>
                <span
                  className={`rounded px-1.5 py-0.5 text-[9.5px] font-bold uppercase tracking-wider ${
                    check.outcome === "PASS"
                      ? "bg-success/15 text-success border border-success/30"
                      : "bg-destructive/15 text-destructive border border-destructive/30"
                  }`}
                >
                  {check.outcome === "PASS"
                    ? "✓ All 6 Checks Pass"
                    : `${check.failed_count} of 6 Checks Failed`}
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {check.checks.map((c) => (
                  <span
                    key={c.key}
                    title={c.detail}
                    className={`rounded border px-1.5 py-0.5 text-[10px] font-medium transition-all ${
                      c.passed
                        ? "border-success/30 bg-success/10 text-success"
                        : "border-destructive/30 bg-destructive/10 text-destructive"
                    }`}
                  >
                    {c.passed ? <Check className="mr-1 inline h-2.5 w-2.5" /> : null}
                    {c.name}
                  </span>
                ))}
              </div>
              <p className="mt-2 text-[10.5px] leading-relaxed text-muted-foreground">
                {check.verdict}
              </p>
              {softOverrideAvailable ? (
                <div className="mt-2.5 rounded border border-warning/40 bg-warning/[.08] p-2.5">
                  <label className="text-[10px] font-bold uppercase tracking-wider text-warning block mb-1">
                    Override Justification (Soft policy warning in force)
                  </label>
                  <input
                    type="text"
                    value={overrideReason}
                    onChange={(e) => setOverrideReason(e.target.value)}
                    placeholder="e.g. Covered by intra-day funding, CFO sign-off on record"
                    className="w-full rounded border border-warning/40 bg-background px-2.5 py-1 text-xs outline-none focus:ring-1 focus:ring-warning"
                  />
                </div>
              ) : null}
            </div>
          ) : null}

          {/* AI Advisor Observations Card */}
          {advice && advice.length > 0 ? (
            <div className="rounded-lg border border-primary/30 bg-primary/[.04] p-3">
              <div className="mb-1 flex items-center gap-1.5 text-[10.5px] font-bold uppercase tracking-wider text-primary">
                <Sparkles className="h-3 w-3" />
                <span>AI Governance Observations</span>
                {adviceLoading ? (
                  <Loader2 className="h-2.5 w-2.5 animate-spin text-muted-foreground" />
                ) : null}
              </div>
              <p className="mb-1.5 text-[9.5px] italic text-muted-foreground">
                Concentration, headroom, ladder and policy movement — not a market view.
              </p>
              <ul className="space-y-1 text-[11px] leading-relaxed text-foreground/90">
                {advice.map((line, i) => (
                  <li key={i} className="flex items-start gap-1.5">
                    <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-primary" />
                    <span>{line}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {error ? (
            <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error}
            </div>
          ) : null}
        </div>

        {/* Modal Action Footer */}
        <div className="flex items-center justify-between border-t border-border bg-surface-2/40 px-5 py-3.5 shrink-0">
          <div className="text-[10.5px] text-muted-foreground hidden sm:block">
            {selectedCp && amountMinor > 0 ? (
              <span>
                Booking forward: Sell <strong className="text-foreground">{formatMoney(amountMinor, currency)}</strong> to buy <strong className="text-foreground">£{(gbpValue / 100).toLocaleString("en-GB", { maximumFractionDigits: 0 })}</strong> with <strong className="text-foreground">{selectedCp.name}</strong>
              </span>
            ) : (
              <span>Draft ticket · Live check pre-flight before booking</span>
            )}
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onClose}
              disabled={submitting}
              className="text-xs"
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={submit}
              disabled={
                submitting ||
                overHedge ||
                invalidAmount ||
                !counterpartyId ||
                overrideBlocked ||
                overrideMissingReason
              }
              className="gap-1.5 text-xs font-semibold shadow-xs"
              title={
                overrideBlocked
                  ? "The policy in force is a hard block; resize or reroute the hedge."
                  : overrideMissingReason
                    ? "Override reason required."
                    : undefined
              }
            >
              {submitting ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
              {failedChecks ? "Initiate with override" : "Initiate FX Forward"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- helpers

function Field({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`num text-xs ${highlight ? "font-semibold text-warning" : "text-foreground"}`}>
        {value}
      </p>
    </div>
  );
}

const CURRENCY_SYMBOL: Record<string, string> = {
  GBP: "£",
  EUR: "€",
  USD: "$",
  CHF: "CHF ",
};

function formatMoney(minorUnits: number, currency: string): string {
  const symbol = CURRENCY_SYMBOL[currency] ?? "";
  const major = minorUnits / 100;
  if (Math.abs(major) >= 1_000_000) {
    return `${symbol}${(major / 1_000_000).toFixed(1)}m`;
  }
  if (Math.abs(major) >= 1_000) {
    return `${symbol}${(major / 1_000).toFixed(0)}k`;
  }
  return `${symbol}${major.toFixed(0)}`;
}
