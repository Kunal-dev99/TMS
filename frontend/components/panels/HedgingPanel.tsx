"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeftRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileText,
  Info,
  Layers,
  ShieldCheck,
  Sparkles,
  TrendingUp,
} from "lucide-react";

import { PanelShell } from "@/components/PanelShell";
import { Button } from "@/components/ui/button";
import {
  getFxSummary,
  getFxByCurrency,
  listHedges,
  narrateFx,
  type FxBriefing,
  type FxCurrencySummary,
  type FxExposureView,
  type FxLiveHedge,
  type FxRecommendation,
  type FxSummaryView,
} from "@/lib/api";

/**
 * Hedging panel — the FX exposure & hedge dashboard from §14 of the spec.
 *
 * Top strip: one card per currency (gross, GBP equivalent, hedge %).
 * Middle: bucketed table for the selected currency with an
 *   "Initiate hedge" action per bucket.
 * Bottom: the sources footnote — where forecasts and rates come from,
 *   what is configurable in Control.
 */
export function HedgingPanel({
  open,
  onClose,
  onOpenInitiate,
  refreshKey = 0,
}: {
  open: boolean;
  onClose: () => void;
  onOpenInitiate: (args: {
    currency: string;
    exposureIds: string[];
    unhedgedMinor: number;
    label: string;
    prefillAmountMinor?: number;
    prefillTenorMonths?: number;
    prefillCounterpartyId?: string;
  }) => void;
  refreshKey?: number;
}) {
  const [summary, setSummary] = useState<FxSummaryView | null>(null);
  const [selected, setSelected] = useState<string>("EUR");
  const [detail, setDetail] = useState<FxExposureView | null>(null);
  const [activeTab, setActiveTab] = useState<"buckets" | "hedges" | "exposures">("buckets");
  const [hedges, setHedges] = useState<FxLiveHedge[] | null>(null);
  const [briefing, setBriefing] = useState<FxBriefing | null>(null);
  const [briefingLoading, setBriefingLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getFxSummary()
      .then((s) => {
        if (cancelled) return;
        setSummary(s);
        if (s.currencies.length > 0 && !s.currencies.some((c) => c.currency === selected)) {
          setSelected(s.currencies[0].currency);
        }
      })
      .catch((e) => !cancelled && setError(String(e.message ?? e)))
      .finally(() => !cancelled && setLoading(false));
    listHedges()
      .then((rows) => !cancelled && setHedges(rows))
      .catch(() => {
        /* non-fatal; hedges section stays hidden if this fails */
      });
    setBriefingLoading(true);
    narrateFx()
      .then((b) => !cancelled && setBriefing(b))
      .catch(() => {
        /* non-fatal; fall back to per-currency mechanical line */
      })
      .finally(() => !cancelled && setBriefingLoading(false));
    return () => {
      cancelled = true;
    };
  }, [open, refreshKey]);

  useEffect(() => {
    if (!open || !selected) return;
    let cancelled = false;
    getFxByCurrency(selected)
      .then((d) => !cancelled && setDetail(d))
      .catch((e) => !cancelled && setError(String(e.message ?? e)));
    return () => {
      cancelled = true;
    };
  }, [open, selected, refreshKey]);

  const currencies = summary?.currencies ?? [];

  return (
    <PanelShell
      open={open}
      onClose={onClose}
      icon={ArrowLeftRight}
      title="FX Exposure & Hedging"
      description="Foreign-currency receipts forecast from ERP/EPM. See what's hedged, what's exposed, and initiate an FX forward against the remaining balance."
    >
      {loading || !summary ? (
        <div className="py-8 text-center text-xs text-muted-foreground">Loading…</div>
      ) : error ? (
        <div className="rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      ) : (
        <div className="space-y-4">
          {/* Currency summary cards */}
          <section>
            <div className="mb-2 flex items-baseline justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Foreign currency exposure
              </h3>
              <span className="text-[10px] text-muted-foreground">
                as of {summary.as_of_date} · base {summary.base_currency}
              </span>
            </div>
            <p className="mb-1.5 text-[10px] text-muted-foreground">
              <span className="font-semibold">Sorted by policy-gap severity</span>{" "}
              — the currency with the biggest gap to its hedge target sits first
              (GBP-equivalent, currency-neutral). AI briefing ranks the same way.
            </p>
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
              {currencies.map((c, idx) => (
                <CurrencyCard
                  key={c.currency}
                  data={c}
                  rank={idx + 1}
                  active={c.currency === selected}
                  onClick={() => setSelected(c.currency)}
                />
              ))}
            </div>
          </section>

          {/* AI briefing — cross-currency, ranked by gap severity */}
          <AiBriefingBlock
            briefing={briefing}
            loading={briefingLoading}
            fallbackDetail={detail}
            selectedCurrency={selected}
            onUseRecommendation={async (rec) => {
              setSelected(rec.currency);
              const view =
                detail && detail.currency === rec.currency
                  ? detail
                  : await getFxByCurrency(rec.currency);
              const eligible = view.exposures
                .filter((e) => e.amount_minor > e.hedged_minor)
                .map((e) => e.id);
              onOpenInitiate({
                currency: rec.currency,
                exposureIds: eligible,
                unhedgedMinor: view.summary.unhedged_minor,
                label: `${rec.currency} · AI recommendation`,
                prefillAmountMinor: rec.amount_minor,
                prefillTenorMonths: rec.tenor_months,
                prefillCounterpartyId: rec.counterparty_id,
              });
            }}
          />

          {/* Watch callouts — maturity clustering, refinance walls */}
          {briefing && briefing.watch.length > 0 ? (
            <section className="space-y-1.5">
              {briefing.watch.map((w, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/[.08] p-3 text-[11px] leading-relaxed text-foreground"
                >
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
                  <span>{w}</span>
                </div>
              ))}
            </section>
          ) : null}

          {/* Segmented Perspective Tabs */}
          <div className="space-y-3">
            <div className="flex items-center justify-between border-b border-border pb-2">
              <div className="flex items-center gap-1 rounded border border-border bg-surface-2/40 p-0.5">
                <button
                  type="button"
                  onClick={() => setActiveTab("buckets")}
                  className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-[11px] font-medium transition-colors ${
                    activeTab === "buckets"
                      ? "bg-background text-foreground shadow-xs font-semibold"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Layers className="h-3 w-3" />
                  <span>Maturity Ladder ({detail?.buckets.length ?? 0})</span>
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("hedges")}
                  className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-[11px] font-medium transition-colors ${
                    activeTab === "hedges"
                      ? "bg-background text-foreground shadow-xs font-semibold"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <ShieldCheck className="h-3 w-3" />
                  <span>Active Hedges ({hedges?.length ?? 0})</span>
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("exposures")}
                  className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-[11px] font-medium transition-colors ${
                    activeTab === "exposures"
                      ? "bg-background text-foreground shadow-xs font-semibold"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <FileText className="h-3 w-3" />
                  <span>Invoices & Receivables ({detail?.exposures.length ?? 0})</span>
                </button>
              </div>
            </div>

            {/* Active Tab Content */}
            {activeTab === "buckets" && detail ? (
              <BucketTable
                detail={detail}
                onInitiate={(row) => {
                  if (row.unhedged_minor <= 0) return;
                  const eligible = detail.exposures
                    .filter((e) => e.amount_minor > e.hedged_minor)
                    .filter((e) => bucketOf(e.expected_date, summary.as_of_date) === row.bucket)
                    .map((e) => e.id);
                  onOpenInitiate({
                    currency: detail.currency,
                    exposureIds: eligible.length ? eligible : detail.exposures.map((e) => e.id),
                    unhedgedMinor: row.unhedged_minor,
                    label: `${detail.currency} ${row.label}`,
                  });
                }}
              />
            ) : null}

            {activeTab === "hedges" ? (
              hedges && hedges.length > 0 ? (
                <div className="overflow-x-auto rounded border border-border bg-card">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-border bg-surface-2/60 text-[10px] uppercase font-semibold text-muted-foreground">
                        <th className="py-2 px-3">Counterparty</th>
                        <th className="py-2 px-2 text-center">Ccy</th>
                        <th className="py-2 px-2.5 text-right">Sell Forward</th>
                        <th className="py-2 px-2.5 text-right">Buy GBP</th>
                        <th className="py-2 px-2 text-center">Tenor</th>
                        <th className="py-2 px-2.5">Traded</th>
                        <th className="py-2 px-2.5">Matures</th>
                        <th className="py-2 px-2 text-center">Covers</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/40">
                      {hedges
                        .slice()
                        .sort((a, b) => a.maturity_date.localeCompare(b.maturity_date))
                        .map((h) => (
                          <tr key={h.deal_id} className="hover:bg-muted/30 transition-colors">
                            <td className="py-1.5 px-3 font-medium">
                              {h.counterparty_name}
                            </td>
                            <td className="py-1.5 px-2 text-center">
                              <span className="rounded border border-border/60 bg-surface-2 px-1.5 py-0.5 text-[10px] font-semibold">
                                {h.currency}
                              </span>
                            </td>
                            <td className="py-1.5 px-2.5 text-right num font-semibold">
                              {formatMoney(h.covered_amount_minor, h.currency)}
                            </td>
                            <td className="py-1.5 px-2.5 text-right num text-muted-foreground">
                              {formatMoney(h.principal_pence, "GBP")}
                            </td>
                            <td className="py-1.5 px-2 text-center num text-muted-foreground">
                              {h.tenor_months}m
                            </td>
                            <td className="py-1.5 px-2.5 num text-muted-foreground">
                              {h.trade_date}
                            </td>
                            <td className="py-1.5 px-2.5 num font-medium">{h.maturity_date}</td>
                            <td className="py-1.5 px-2 text-center text-[10px] text-muted-foreground">
                              <span className="rounded bg-surface-2 px-1.5 py-0.5 font-medium">
                                {h.exposure_ids.length} exp
                              </span>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                  <p className="border-t border-border/40 bg-surface-2/40 px-3 py-1.5 text-[9.5px] text-muted-foreground">
                    Each row is an active <strong className="font-semibold text-foreground">FX_FORWARD</strong> Deal linked to one or more forecast exposures via HedgeLink.
                  </p>
                </div>
              ) : (
                <div className="rounded border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
                  No active FX forwards on book for this portfolio.
                </div>
              )
            ) : null}

            {activeTab === "exposures" && detail ? (
              <ExposureList data={detail} />
            ) : null}
          </div>

          {/* Sources — every figure on the panel is one of these three inputs.
              Kept explicit so the treasurer can see who owns each number. */}
          <div className="rounded border border-dashed border-border bg-surface-2/30 p-3 text-[10px] text-muted-foreground">
            <div className="mb-1.5 flex items-center gap-1.5 font-semibold text-foreground/80">
              <Info className="h-3 w-3" /> Where these numbers come from
            </div>
            <ul className="space-y-1">
              <li>
                <span className="font-semibold text-foreground/80">Forecast exposure</span>{" "}
                (e.g. €100m, $60m, CHF 12m) — from {summary.sources.forecast}, stored in
                the <code>currency_exposure</code> table. In production these arrive from
                Oracle EPM / OM / ERP or a file interface.
              </li>
              <li>
                <span className="font-semibold text-foreground/80">Policy target</span>{" "}
                (e.g. EUR 80%, USD 75%, CHF 60%) — from {summary.sources.policy} on the
                active investment policy version. Owned by CFO / treasurer, policy-versioned
                for audit. Not editable in the demo yet.
              </li>
              <li>
                <span className="font-semibold text-foreground/80">Hedged amount</span>{" "}
                — sum of live <code>hedge_link</code> rows against each exposure. Updates
                immediately whenever a hedge is initiated through the panel.
              </li>
              <li>
                <span className="font-semibold text-foreground/80">Gap to target</span>{" "}
                = forecast × target − hedged. Shown on each currency card and used by the
                AI briefing to rank priority.
              </li>
              <li>
                <span className="font-semibold text-foreground/80">Rates</span> — {summary.sources.rates}.
                Only used to show GBP equivalent and forward-rate quotes on the ticket.
              </li>
            </ul>
          </div>
        </div>
      )}
    </PanelShell>
  );
}

// ---------------------------------------------------------------- pieces

function CurrencyCard({
  data,
  rank,
  active,
  onClick,
}: {
  data: FxCurrencySummary;
  rank: number;
  active: boolean;
  onClick: () => void;
}) {
  const rankLabel =
    rank === 1
      ? "Biggest gap"
      : rank === 2
        ? "2nd priority"
        : "3rd priority";
  const ratioPct = Math.round(data.hedge_ratio_bp / 100);
  const targetPct = Math.round(data.target_cover_bp / 100);
  const isFullyCovered = data.unhedged_minor <= 0;
  const belowTarget = !isFullyCovered && data.target_cover_bp > 0 && data.hedge_ratio_bp < data.target_cover_bp;
  const symbol = CURRENCY_SYMBOL[data.currency] ?? "";

  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg border p-3 text-left transition-colors ${
        active
          ? "border-primary bg-primary/[.06] shadow-xs"
          : "border-border bg-surface-2/40 hover:border-primary/40 hover:bg-surface-2/60"
      }`}
    >
      <div className="mb-1 flex items-center justify-between">
        <span
          className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-px text-[9px] font-semibold uppercase tracking-wider ${
            rank === 1
              ? "border-warning/40 bg-warning/10 text-warning"
              : "border-border bg-surface-2/60 text-muted-foreground"
          }`}
        >
          #{rank} · {rankLabel}
        </span>
      </div>
      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-1.5">
          <span className="text-xs font-bold text-foreground tracking-tight">
            {data.currency}
          </span>
          <span className="text-[11px] text-muted-foreground font-medium">
            ({symbol.trim()})
          </span>
        </div>
        <span
          className={`rounded px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-wider ${
            isFullyCovered
              ? "bg-success/15 text-success border border-success/30"
              : belowTarget
              ? "bg-warning/15 text-warning border border-warning/30"
              : "bg-primary/15 text-primary border border-primary/30"
          }`}
        >
          {ratioPct}% hedged
        </span>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2 border-t border-border/40 pt-2 text-left">
        <div>
          <span className="text-[9px] uppercase font-semibold text-muted-foreground block">
            Forecast
          </span>
          <span className="num text-xs font-bold text-foreground">
            {formatMoney(data.gross_minor, data.currency)}
          </span>
          <span className="block text-[9.5px] text-muted-foreground truncate">
            ≈ {formatMoney(data.gross_gbp_pence, "GBP")}
          </span>
        </div>
        <div>
          <span className="text-[9px] uppercase font-semibold text-muted-foreground block">
            Unhedged Risk
          </span>
          <span className={`num text-xs font-bold ${data.unhedged_minor > 0 ? "text-warning" : "text-success"}`}>
            {formatMoney(data.unhedged_minor, data.currency)}
          </span>
          <span className="block text-[9.5px] text-muted-foreground">
            Target {targetPct}%
          </span>
        </div>
      </div>

      <div className="mt-2">
        <div className="flex justify-between text-[9px] text-muted-foreground mb-1">
          <span>Coverage</span>
          <span>{ratioPct}% / {targetPct}% target</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded bg-surface-2">
          <div
            className={`h-full ${isFullyCovered ? "bg-success" : belowTarget ? "bg-warning" : "bg-primary"}`}
            style={{ width: `${Math.min(100, ratioPct)}%` }}
          />
        </div>
      </div>

      {/* Derivation footer — makes the gap arithmetic visible.
          Forecast × target − hedged = unhedged risk relative to policy. */}
      {data.target_cover_bp > 0 ? (
        <div className="mt-2 border-t border-border/40 pt-1.5 text-[9.5px] font-mono text-muted-foreground leading-snug">
          {formatMoney(data.gross_minor, data.currency)} × {targetPct}%
          {" − "}
          {formatMoney(data.hedged_minor, data.currency)}
          {" = "}
          <span className={data.gap_to_target_minor > 0 ? "font-semibold text-warning" : "font-semibold text-success"}>
            {formatMoney(data.gap_to_target_minor, data.currency)} gap
          </span>
        </div>
      ) : null}
    </button>
  );
}

function AiBriefingBlock({
  briefing,
  loading,
  fallbackDetail,
  selectedCurrency,
  onUseRecommendation,
}: {
  briefing: FxBriefing | null;
  loading: boolean;
  fallbackDetail: FxExposureView | null;
  selectedCurrency: string;
  onUseRecommendation: (rec: FxRecommendation) => void;
}) {
  const currencyRec =
    briefing?.recommendations.find((r) => r.currency === selectedCurrency) ??
    briefing?.recommendations[0] ??
    null;
  const otherRecs =
    briefing?.recommendations.filter((r) => r !== currencyRec) ?? [];

  return (
    <div className="rounded-lg border border-primary/30 bg-primary/[.04] p-3 text-xs space-y-2.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          <h3 className="text-xs font-semibold uppercase tracking-wider text-primary">
            AI FX Executive Briefing
          </h3>
        </div>
        <span className="text-[10px] italic text-muted-foreground hidden sm:inline">
          Continuous policy gap & counterparty intelligence
        </span>
      </div>

      {loading && !briefing ? (
        <div className="flex items-center gap-2 text-muted-foreground py-1">
          <div className="h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <span>Analysing currency exposures and policy limits…</span>
        </div>
      ) : briefing?.briefing ? (
        <p className="leading-relaxed text-foreground font-normal whitespace-pre-line text-xs">
          {briefing.briefing}
        </p>
      ) : fallbackDetail ? (
        <p className="leading-relaxed text-foreground text-xs">
          <strong>{fallbackDetail.summary.currency}</strong> is currently{" "}
          <strong>{Math.round(fallbackDetail.summary.hedge_ratio_bp / 100)}%</strong> hedged,
          leaving <span className="text-warning font-semibold">{formatMoney(
            fallbackDetail.summary.unhedged_minor,
            fallbackDetail.currency,
          )}</span> unhedged across scheduled forecast receivables.
        </p>
      ) : null}

      {currencyRec ? (
        <div className="rounded border border-primary/40 bg-background p-2.5">
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[9.5px] font-bold uppercase tracking-wider text-primary">
                Recommendation · {currencyRec.currency}
              </span>
              <span className="text-[10px] text-muted-foreground font-medium hidden sm:inline">
                Pre-checked against counterparty limits
              </span>
            </div>
            <Button
              type="button"
              size="sm"
              className="h-6 gap-1 px-2.5 text-[11px] font-semibold"
              onClick={() => onUseRecommendation(currencyRec)}
            >
              <span>Use this</span>
              <ArrowLeftRight className="h-2.5 w-2.5" />
            </Button>
          </div>
          <p className="num text-xs font-bold text-foreground">
            Sell {formatMoney(currencyRec.amount_minor, currencyRec.currency)}{" "}
            {currencyRec.currency} forward · {currencyRec.tenor_months}m ·{" "}
            <span className="text-primary">{currencyRec.counterparty_name}</span>
          </p>
          <p className="mt-1 text-[10.5px] leading-relaxed text-muted-foreground">
            {currencyRec.reason}
          </p>
        </div>
      ) : null}

      {otherRecs.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5 pt-1 border-t border-border/40">
          <span className="text-[10px] font-medium text-muted-foreground">Also suggested:</span>
          {otherRecs.map((r) => (
            <button
              key={r.currency}
              type="button"
              onClick={() => onUseRecommendation(r)}
              className="inline-flex items-center gap-1 rounded border border-primary/40 bg-background px-2 py-0.5 text-[10px] font-medium text-primary hover:bg-primary/10 transition-colors"
            >
              <strong>{r.currency}</strong>: sell {formatMoney(r.amount_minor, r.currency)} · {r.tenor_months}m · {r.counterparty_name}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function BucketTable({
  detail,
  onInitiate,
}: {
  detail: FxExposureView;
  onInitiate: (row: FxExposureView["buckets"][number]) => void;
}) {
  const ccy = detail.currency;
  return (
    <div className="overflow-x-auto rounded border border-border bg-card">
      <table className="w-full text-left text-xs border-collapse">
        <thead>
          <tr className="border-b border-border bg-surface-2/60 text-[10px] uppercase font-semibold text-muted-foreground">
            <th className="py-2 px-3">Period</th>
            <th className="py-2 px-2 text-center w-20">Coverage</th>
            <th className="py-2 px-2.5 text-right">Forecast</th>
            <th className="py-2 px-2.5 text-right">Hedged</th>
            <th className="py-2 px-2.5 text-right">Unhedged</th>
            <th className="py-2 px-2.5 text-right">GBP Equiv</th>
            <th className="py-2 px-3 text-right">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/40">
          {detail.buckets.map((row) => {
            const dead = row.forecast_minor === 0;
            const pctCovered = row.forecast_minor > 0
              ? Math.min(100, Math.round((row.hedged_minor / row.forecast_minor) * 100))
              : 0;

            return (
              <tr key={row.bucket} className={`hover:bg-muted/30 transition-colors ${dead ? "text-muted-foreground/60" : ""}`}>
                <td className="py-2 px-3 font-semibold text-foreground">
                  {row.label}
                </td>
                <td className="py-2 px-2 text-center">
                  {!dead ? (
                    <div className="flex flex-col items-center gap-0.5">
                      <div className="h-1.5 w-14 overflow-hidden rounded bg-surface-2 border border-border/40">
                        <div
                          className={`h-full ${pctCovered >= 100 ? "bg-success" : pctCovered > 0 ? "bg-primary" : "bg-warning"}`}
                          style={{ width: `${pctCovered}%` }}
                        />
                      </div>
                      <span className="text-[9px] num text-muted-foreground font-medium">
                        {pctCovered}%
                      </span>
                    </div>
                  ) : (
                    <span className="text-[9.5px] text-muted-foreground">—</span>
                  )}
                </td>
                <td className="py-2 px-2.5 text-right num font-medium">
                  {formatMoney(row.forecast_minor, ccy)}
                </td>
                <td className="py-2 px-2.5 text-right num font-semibold text-success">
                  {formatMoney(row.hedged_minor, ccy)}
                </td>
                <td className="py-2 px-2.5 text-right num font-bold text-warning">
                  {formatMoney(row.unhedged_minor, ccy)}
                </td>
                <td className="py-2 px-2.5 text-right num text-muted-foreground">
                  {formatMoney(row.forecast_gbp_pence, "GBP")}
                </td>
                <td className="py-2 px-3 text-right">
                  {row.unhedged_minor > 0 ? (
                    <Button
                      type="button"
                      size="sm"
                      className="h-6 px-2.5 text-[10.5px] font-semibold"
                      onClick={() => onInitiate(row)}
                    >
                      Initiate hedge
                    </Button>
                  ) : dead ? null : (
                    <span className="inline-flex items-center gap-1 rounded bg-success/15 px-2 py-0.5 text-[9.5px] font-bold text-success border border-success/30">
                      <CheckCircle2 className="h-2.5 w-2.5" /> Covered
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ExposureList({ data }: { data: FxExposureView }) {
  return (
    <div className="mt-2 overflow-x-auto rounded border border-border/60">
      <table className="w-full text-left text-xs border-collapse">
        <thead>
          <tr className="border-b border-border bg-surface-2/60 text-[10px] uppercase font-semibold text-muted-foreground">
            <th className="py-2 px-3">Expected</th>
            <th className="py-2 px-2.5">Source</th>
            <th className="py-2 px-2.5">Reference</th>
            <th className="py-2 px-2.5 text-right">Amount</th>
            <th className="py-2 px-2.5 text-right">Hedged</th>
            <th className="py-2 px-2.5 text-center">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/40">
          {data.exposures.map((e) => (
            <tr key={e.id}>
              <td className="py-1.5 px-3 num">{e.expected_date}</td>
              <td className="py-1.5 px-2.5 text-[10.5px] text-muted-foreground">
                {e.source.replace(/_/g, " ").toLowerCase()}
              </td>
              <td className="py-1.5 px-2.5 text-[10.5px] text-muted-foreground">
                {e.source_reference ?? "—"}
              </td>
              <td className="py-1.5 px-2.5 text-right num">
                {formatMoney(e.amount_minor, data.currency)}
              </td>
              <td className="py-1.5 px-2.5 text-right num text-success">
                {formatMoney(e.hedged_minor, data.currency)}
              </td>
              <td className="py-1.5 px-2.5 text-center text-[10px] font-medium">
                {e.status.replace(/_/g, " ").toLowerCase()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- helpers

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

function bucketOf(expected: string, asOf: string): string {
  const d = (new Date(expected).getTime() - new Date(asOf).getTime()) / 86_400_000;
  if (d <= 92) return "0_3M";
  if (d <= 183) return "3_6M";
  if (d <= 365) return "6_12M";
  return "OVER_12M";
}
