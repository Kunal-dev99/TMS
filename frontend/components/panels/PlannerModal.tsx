"use client";

import { useEffect, useState } from "react";
import { Check, ChevronDown, ChevronUp, Sparkles, TrendingUp, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { deployCash, type DeploymentPlan, type PlannerCandidate } from "@/lib/api";
import { perCent, sterling } from "@/lib/format";
import {
  ThinkingTrace,
} from "@/components/panels/ThinkingTrace";
import { TypedText } from "@/components/panels/TypedText";
import {
  TipNote,
  TipRow,
  TipTitle,
  useFloatingTooltip,
} from "@/components/common/FloatingTooltip";

/**
 * The cash deployment planner.
 *
 * One blended plan for today's idle cash. The treasurer sets caps
 * per rating band (up to 80% AAA, up to 10% AA…) and the planner
 * greedily picks the highest-yielding spread that fits inside those
 * ceilings. Every allocation is gated by the same CheckEngine as any
 * typed deal. Two alternatives — Higher yield (loosens A/BBB caps by
 * 15 pts each) and Tighter concentration (halves the per-name cap) —
 * sit alongside for comparison. The model labels; the numbers are ours.
 *
 * The modal draws its own SVG charts inline: an allocation bar per
 * candidate showing who gets what, a yield-vs-concentration scatter
 * placing all candidates side by side, and a running total.
 */

const PLANNER_STEPS = [
  "Reading the operating account balance.",
  "Enumerating counterparties with headroom.",
  "Pricing each placement against the rating curve.",
  "Building four candidate plans.",
  "Running the six checks on every allocation.",
  "Asking the model to rank the four.",
];

const BUILTIN_ACCENT: Record<string, string> = {
  BLENDED: "hsl(var(--primary))",
  HIGHER_YIELD: "hsl(var(--warning))",
  TIGHTER_CONCENTRATION: "hsl(var(--success))",
  // Legacy kinds — still rendered in a valid palette if a custom
  // strategy points at one of them.
  MAX_YIELD: "hsl(var(--warning))",
  DIVERSIFIED: "hsl(var(--primary))",
  PRESERVE_HEADROOM: "hsl(var(--success))",
  CONSERVATIVE: "hsl(var(--muted-foreground))",
};
// Custom strategies fall back to a neutral accent.
const ACCENT = new Proxy(BUILTIN_ACCENT, {
  get: (t, k: string) => t[k] ?? "hsl(var(--muted-foreground))",
}) as Record<string, string>;

export function PlannerModal({
  open,
  onClose,
  onPick,
  onPickBatch,
}: {
  open: boolean;
  onClose: () => void;
  /** Load a chosen allocation into the ticket. Fires once per click. */
  onPick: (allocation: {
    counterparty_id: string;
    principal_pence: number;
    tenor_months: number;
    rate_bp: number;
  }) => void;
  /**
   * Fire every allocation on a whole candidate through the six checks
   * in sequence — same shape as clicking Initiate on each row one by
   * one, but without the click count. Passes the candidate's label so
   * the toast can name which plan is being placed.
   */
  onPickBatch?: (
    allocations: {
      counterparty_id: string;
      counterparty_name: string;
      principal_pence: number;
      tenor_months: number;
      rate_bp: number;
    }[],
    label: string,
  ) => Promise<void> | void;
}) {
  const [plan, setPlan] = useState<DeploymentPlan | null>(null);
  const [pending, setPending] = useState<DeploymentPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [networkDone, setNetworkDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setBusy(true);
    setError(null);
    setPlan(null);
    setPending(null);
    setNetworkDone(false);
    deployCash()
      .then((result) => {
        setPending(result);
        setNetworkDone(true);
      })
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : "That was refused.");
        setBusy(false);
      });
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-6"
      role="dialog"
      aria-modal="true"
      aria-label="Cash deployment planner"
    >
      <div className="relative w-full max-w-5xl rounded-lg border border-border bg-card shadow-2xl">
        <header className="flex items-start justify-between gap-4 border-b border-border p-5">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              <TrendingUp className="h-4 w-4 text-primary" aria-hidden />
              Deploy the idle cash
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              The highest-yielding spread inside the rating caps you set.
              Two variants for comparison. Every allocation is pre-checked
              against the six-check gate.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:bg-surface-2 hover:text-foreground"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="p-5">
          {error ? (
            <div className="rounded border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          ) : null}

          {busy && !plan ? (
            <ThinkingTrace
              steps={PLANNER_STEPS}
              finished={networkDone}
              intervalMs={350}
              onFinished={() => {
                if (pending) setPlan(pending);
                setBusy(false);
              }}
            />
          ) : null}

          {plan ? <PlanBody plan={plan} onPick={onPick} onPickBatch={onPickBatch} /> : null}
        </div>
      </div>
    </div>
  );
}


function PlanBody({
  plan,
  onPick,
  onPickBatch,
}: {
  plan: DeploymentPlan;
  onPick: (a: {
    counterparty_id: string;
    principal_pence: number;
    tenor_months: number;
    rate_bp: number;
  }) => void;
  onPickBatch?: (
    allocations: {
      counterparty_id: string;
      counterparty_name: string;
      principal_pence: number;
      tenor_months: number;
      rate_bp: number;
    }[],
    label: string,
  ) => Promise<void> | void;
}) {
  const [selectedKind, setSelectedKind] = useState<string>(
    plan.recommendation_kind || plan.candidates[0]?.kind || "BLENDED",
  );
  const [showChart, setShowChart] = useState<boolean>(false);

  const selectedCandidate =
    plan.candidates.find((c) => c.kind === selectedKind) ||
    plan.candidates[0];

  const baseCandidate =
    plan.candidates.find((c) => c.kind === "BLENDED") || plan.candidates[0];

  return (
    <div className="space-y-4">
      {/* Header stats */}
      <div className="grid grid-cols-3 gap-3 rounded-lg border border-border bg-surface-2/30 p-2.5">
        <Stat label="Idle cash to deploy" value={sterling(plan.idle_cash_pence)} />
        <Stat label="Total portfolio" value={sterling(plan.portfolio_total_pence)} />
        <Stat
          label="Concentration cap"
          value={perCent(plan.concentration_cap_bp)}
        />
      </div>

      {/* AI Quick Summary */}
      {plan.recommendation_kind ? (
        <div className="rounded-lg border border-primary/30 bg-primary/5 p-3.5">
          <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary shrink-0" aria-hidden />
              <span className="text-xs font-bold uppercase tracking-wider text-primary">
                AI Quick Summary
              </span>
              <span
                className="rounded px-2 py-0.5 text-[9.5px] font-bold uppercase tracking-wider text-primary"
                style={{
                  background: `color-mix(in srgb, ${
                    ACCENT[plan.recommendation_kind] ||
                    "hsl(var(--primary))"
                  } 18%, transparent)`,
                }}
              >
                Recommended: {plan.candidates.find((c) => c.kind === plan.recommendation_kind)
                  ?.label ?? plan.recommendation_kind}
              </span>
            </div>
            <span className="text-[10px] italic text-muted-foreground hidden sm:inline">
              Point-by-point executive briefing · all trade-offs in one place
            </span>
          </div>
          <p className="text-xs leading-relaxed text-foreground font-normal whitespace-pre-line">
            <TypedText text={plan.recommendation_reason} />
          </p>
        </div>
      ) : null}

      {/* 3-Strategy Side-by-Side Comparison */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-foreground">
              Compare {plan.candidates.length} Placement Strategies
            </h3>
            <span className="text-[11px] text-muted-foreground hidden sm:inline">
              Select any strategy card to inspect its allocations below
            </span>
          </div>
          {plan.candidates.length ? (
            <button
              type="button"
              onClick={() => setShowChart((prev) => !prev)}
              className="flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
            >
              {showChart ? (
                <>
                  <ChevronUp className="h-3 w-3" /> Hide Trade-Off Scatter Chart
                </>
              ) : (
                <>
                  <ChevronDown className="h-3 w-3" /> Show Trade-Off Scatter Chart
                </>
              )}
            </button>
          ) : null}
        </div>

        {showChart && plan.candidates.length ? (
          <YieldConcentrationChart plan={plan} />
        ) : null}

        {/* 3-Column Comparative Cards */}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {plan.candidates.map((c) => {
            const isSelected = c.kind === selectedCandidate?.kind;
            const isRec = c.kind === plan.recommendation_kind;
            const accentColor = ACCENT[c.kind] || "hsl(var(--primary))";
            const yieldDelta =
              c.expected_annual_interest_pence -
              baseCandidate.expected_annual_interest_pence;
            const total = c.deployed_pence || 1;

            return (
              <div
                key={c.kind}
                onClick={() => setSelectedKind(c.kind)}
                className={`relative flex flex-col justify-between rounded-lg border p-3.5 transition-all cursor-pointer ${
                  isSelected
                    ? "border-primary bg-primary/[0.04] ring-2 ring-primary/25 shadow-sm"
                    : "border-border bg-card hover:border-muted-foreground/40 hover:bg-surface-2/20"
                }`}
              >
                <div>
                  {/* Card Title + Model Pick Badge */}
                  <div className="mb-1.5 flex items-center justify-between gap-1">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span
                        className="inline-block h-2.5 w-2.5 rounded-full shrink-0"
                        style={{ background: accentColor }}
                        aria-hidden
                      />
                      <span className="truncate text-xs font-semibold text-foreground">
                        {c.label}
                      </span>
                    </div>
                    {isRec ? (
                      <span className="inline-flex items-center gap-0.5 rounded bg-primary/15 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-primary shrink-0">
                        <Sparkles className="h-2.5 w-2.5" /> Model Pick
                      </span>
                    ) : null}
                  </div>

                  {/* Summary / Tagline */}
                  <p className="mb-2.5 text-[10.5px] leading-snug text-muted-foreground line-clamp-2 min-h-[28px]">
                    {plan.per_candidate_labels[c.kind] || c.tagline}
                  </p>

                  {/* High-level metrics container */}
                  <div className="mb-2 rounded border border-border/50 bg-surface-2/40 p-2 text-left">
                    <div className="flex items-baseline justify-between">
                      <span className="num text-sm font-bold text-foreground">
                        {sterling(c.expected_annual_interest_pence)}
                      </span>
                      {yieldDelta !== 0 && c.kind !== baseCandidate.kind ? (
                        <span
                          className={`num text-[10.5px] font-semibold ${
                            yieldDelta > 0
                              ? "text-emerald-600 dark:text-emerald-400"
                              : "text-amber-600 dark:text-amber-400"
                          }`}
                        >
                          {yieldDelta > 0 ? `+${sterling(yieldDelta)}` : sterling(yieldDelta)} / yr
                        </span>
                      ) : (
                        <span className="text-[9.5px] font-medium uppercase text-muted-foreground">
                          annual interest
                        </span>
                      )}
                    </div>

                    <div className="mt-1.5 grid grid-cols-3 gap-1 border-t border-border/40 pt-1.5 text-center text-[10px]">
                      <div>
                        <p className="text-[8.5px] uppercase text-muted-foreground">Rate</p>
                        <p className="num font-semibold text-foreground">
                          {perCent(c.weighted_rate_bp)}
                        </p>
                      </div>
                      <div>
                        <p className="text-[8.5px] uppercase text-muted-foreground">Concentration</p>
                        <p className="num font-semibold text-foreground">
                          +{perCent(c.concentration_change_bp)}
                        </p>
                      </div>
                      <div>
                        <p className="text-[8.5px] uppercase text-muted-foreground">Deals</p>
                        <p className="num font-semibold text-foreground">
                          {c.allocations.length}
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Proportional Mini Bar */}
                  <div className="mb-2">
                    <div className="flex h-2 overflow-hidden rounded-full border border-border/40 bg-muted/40">
                      {c.allocations.map((a, idx) => {
                        const pct = (a.principal_pence / total) * 100;
                        return (
                          <div
                            key={a.counterparty_id + idx}
                            style={{
                              width: `${pct}%`,
                              background: accentColor,
                              opacity: 0.45 + 0.55 * (a.principal_pence / total),
                            }}
                            title={`${a.counterparty_name}: ${pct.toFixed(0)}%`}
                          />
                        );
                      })}
                    </div>
                  </div>
                </div>

                {/* Card footer CTA */}
                <div className="pt-1">
                  {isSelected ? (
                    <div className="flex items-center justify-between text-[10.5px] font-semibold text-primary py-0.5">
                      <span className="flex items-center gap-1">
                        <Check className="h-3 w-3" /> Active View
                      </span>
                      <span className="text-[9.5px] font-normal text-muted-foreground">
                        Inspecting below
                      </span>
                    </div>
                  ) : (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-6 w-full text-[10.5px]"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedKind(c.kind);
                      }}
                    >
                      Inspect Strategy
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Selected Strategy Allocation Table (Clean Executive Drilldown) */}
      {selectedCandidate ? (
        <div className="rounded-lg border border-border bg-card p-3.5 space-y-2.5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border pb-2.5">
            <div>
              <div className="flex items-center gap-2">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ background: ACCENT[selectedCandidate.kind] }}
                  aria-hidden
                />
                <h4 className="text-xs font-semibold text-foreground">
                  {selectedCandidate.label} Placements Breakdown
                </h4>
                <span className="text-[11px] text-muted-foreground">
                  ({selectedCandidate.allocations.length} counterparties ·{" "}
                  {sterling(selectedCandidate.deployed_pence)} deployed)
                </span>
              </div>
              <p className="mt-0.5 text-[10.5px] text-muted-foreground">
                {selectedCandidate.tagline}
              </p>
            </div>

            {onPickBatch && selectedCandidate.allocations.length > 0 ? (
              <Button
                type="button"
                size="sm"
                className="h-7 gap-1.5 text-xs font-semibold shrink-0"
                onClick={() =>
                  onPickBatch(
                    selectedCandidate.allocations.map((a) => ({
                      counterparty_id: a.counterparty_id,
                      counterparty_name: a.counterparty_name,
                      principal_pence: a.principal_pence,
                      tenor_months: a.tenor_months,
                      rate_bp: a.rate_bp,
                    })),
                    selectedCandidate.label,
                  )
                }
              >
                Initiate all {selectedCandidate.allocations.length} at once
              </Button>
            ) : null}
          </div>

          {/* Table */}
          <div className="overflow-x-auto rounded border border-border/60">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-border bg-surface-2/60 text-[10px] uppercase font-semibold text-muted-foreground">
                  <th className="py-2 px-3">Counterparty</th>
                  <th className="py-2 px-2.5 text-center">Rating</th>
                  <th className="py-2 px-2 text-center">Tenor</th>
                  <th className="py-2 px-2.5 text-right">Indicative Rate</th>
                  <th className="py-2 px-3 text-right">Utilisation</th>
                  <th className="py-2 px-3 text-right">Allocated Amount</th>
                  <th className="py-2 px-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {selectedCandidate.allocations.map((a) => (
                  <tr
                    key={a.counterparty_id + "_" + a.tenor_months}
                    className="hover:bg-muted/30 transition-colors"
                  >
                    <td className="py-2 px-3 font-medium">
                      {a.counterparty_name}
                      <span className="block text-[9.5px] text-muted-foreground font-normal">
                        Group: {a.group_name}
                      </span>
                    </td>
                    <td className="py-2 px-2.5 text-center">
                      <span className="inline-block rounded bg-surface-2 px-1.5 py-0.5 text-[10px] font-semibold border border-border/60">
                        {a.counterparty_rating}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-center num text-muted-foreground">
                      {a.tenor_months}m
                    </td>
                    <td className="py-2 px-2.5 text-right num font-medium text-foreground">
                      {perCent(a.rate_bp)}
                    </td>
                    <td className="py-2 px-3 text-right num text-muted-foreground">
                      {perCent(a.resulting_utilisation_bp)}
                    </td>
                    <td className="py-2 px-3 text-right num font-semibold text-foreground">
                      {sterling(a.principal_pence)}
                    </td>
                    <td className="py-2 px-3 text-center">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-6 px-2.5 text-[10.5px]"
                        onClick={() =>
                          onPick({
                            counterparty_id: a.counterparty_id,
                            principal_pence: a.principal_pence,
                            tenor_months: a.tenor_months,
                            rate_bp: a.rate_bp,
                          })
                        }
                      >
                        Initiate
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Consolidated disclaimer footnote */}
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between text-[9.5px] text-muted-foreground/80 italic pt-0.5 gap-1">
            <span>
              * Indicative rate from Bloomberg BGN composite. Click &ldquo;Initiate&rdquo; to load into dealing ticket.
            </span>
            <span>Every allocation is pre-checked and passes the six controls.</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}


function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[9px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="num mt-0.5 text-sm font-semibold">{value}</p>
    </div>
  );
}


/**
 * Yield-vs-concentration scatter. X: weighted rate. Y: how much
 * concentration the plan adds. Recommended point is haloed.
 *
 * Names live on the cards below, not on the chart, because names on the
 * chart collide when three of the four cluster. Each dot carries a
 * numbered pill (1-4) and the card matching that number carries the same
 * pill. Compact labels next to each dot are stacked with a light
 * collision-avoidance pass, so a reader always sees the rate and the
 * concentration cost for every point.
 */
function YieldConcentrationChart({ plan }: { plan: DeploymentPlan }) {
  // A choreographed draw-in: axes first, then gridlines, then one dot at
  // a time. The eye reads a chart that assembles itself as something a
  // system is deciding on the reader's behalf, not a canned image.
  const [phase, setPhase] = useState<number>(0);
  useEffect(() => {
    setPhase(0);
    const ids: number[] = [];
    // Frame budget: axes @ 0, grid @ 300, dot 1 @ 600, dot 2 @ 780,
    // dot 3 @ 960, dot 4 @ 1140, labels & halo @ 1500.
    ids.push(window.setTimeout(() => setPhase(1), 300));
    ids.push(window.setTimeout(() => setPhase(2), 600));
    for (let i = 0; i < plan.candidates.length; i++) {
      ids.push(window.setTimeout(() => setPhase(3 + i), 780 + i * 180));
    }
    ids.push(
      window.setTimeout(
        () => setPhase(3 + plan.candidates.length + 1),
        780 + plan.candidates.length * 180 + 220,
      ),
    );
    return () => ids.forEach(window.clearTimeout);
  }, [plan.candidates.length]);

  const axesIn = phase >= 1;
  const gridIn = phase >= 2;
  const dotsVisible = Math.max(0, phase - 2);
  const labelsIn = phase >= 3 + plan.candidates.length + 1;

  // Hover tooltip for the dots. Each candidate has its own content.
  const tip = useFloatingTooltip();

  const dotTooltip = (c: PlannerCandidate) => {
    const isRec = c.kind === plan.recommendation_kind;
    return (
      <>
        <TipTitle>
          {c.label}
          {isRec ? " · model pick" : ""}
        </TipTitle>
        <TipRow label="Weighted rate" value={perCent(c.weighted_rate_bp)} />
        <TipRow
          label="Annual interest"
          value={sterling(c.expected_annual_interest_pence)}
          tone="success"
        />
        <TipRow label="Deployed" value={sterling(c.deployed_pence)} />
        <TipRow
          label="Concentration added"
          value={"+" + perCent(c.concentration_change_bp)}
          tone={c.concentration_change_bp >= 1500 ? "warn" : "muted"}
        />
        <TipRow
          label="Allocations"
          value={
            c.allocations.length +
            (c.allocations.length === 1 ? " counterparty" : " counterparties")
          }
        />
        <TipNote>{c.tagline}</TipNote>
      </>
    );
  };

  const w = 640;
  const h = 240;
  const pad = { l: 44, r: 20, t: 24, b: 44 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;

  const xs = plan.candidates.map((c) => c.weighted_rate_bp);
  const ys = plan.candidates.map((c) => c.concentration_change_bp);
  const xSpan = Math.max(...xs) - Math.min(...xs);
  const xMin = Math.min(...xs) - Math.max(15, xSpan * 0.3);
  const xMax = Math.max(...xs) + Math.max(15, xSpan * 0.3);
  const yMin = 0;
  const yMax = Math.max(...ys, plan.concentration_cap_bp / 4) * 1.15;

  const px = (v: number) => pad.l + ((v - xMin) / (xMax - xMin)) * plotW;
  const py = (v: number) => pad.t + plotH - ((v - yMin) / (yMax - yMin)) * plotH;

  // Gridline values: 4 evenly-spaced ticks on each axis.
  const xTicks = 4;
  const yTicks = 4;
  const xTickValues = Array.from({ length: xTicks + 1 }, (_, i) =>
    xMin + ((xMax - xMin) * i) / xTicks,
  );
  const yTickValues = Array.from({ length: yTicks + 1 }, (_, i) =>
    yMin + ((yMax - yMin) * i) / yTicks,
  );

  // Position the compact label near each dot. Default to the upper-right
  // of the dot; if that puts it within 18 vertical pixels of another
  // dot's label, push it below instead.
  type Placed = {
    kind: string;
    cx: number;
    cy: number;
    lx: number;
    ly: number;
    anchor: "start" | "end";
  };
  const placements: Placed[] = plan.candidates.map((c) => {
    const cx = px(c.weighted_rate_bp);
    const cy = py(c.concentration_change_bp);
    // Anchor away from the right edge.
    const rightEdge = w - pad.r;
    const anchor: "start" | "end" = cx > rightEdge - 90 ? "end" : "start";
    return {
      kind: c.kind,
      cx,
      cy,
      lx: anchor === "start" ? cx + 12 : cx - 12,
      ly: cy - 6,
      anchor,
    };
  });
  // Second pass: if two label boxes overlap (roughly 90 x 26 pixels), the
  // later one drops below the point.
  for (let i = 0; i < placements.length; i++) {
    for (let j = 0; j < i; j++) {
      const a = placements[i];
      const b = placements[j];
      if (Math.abs(a.cx - b.cx) < 90 && Math.abs(a.ly - b.ly) < 26) {
        a.ly = a.cy + 20;
      }
    }
  }

  return (
    <div
      ref={tip.hostRef}
      className="relative rounded-lg border border-border bg-surface-2/20 p-3"
    >
      <div className="mb-2 flex items-baseline justify-between">
        <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Yield vs. concentration cost
        </p>
        <p className="text-[9px] italic text-muted-foreground">
          Bottom-right is the sweet spot. Hover a dot for the numbers.
        </p>
      </div>

      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="w-full"
        role="img"
        aria-label="Each candidate placed on yield and concentration axes"
        onPointerMove={tip.move}
        onPointerLeave={tip.hide}
      >
        {/* Grid — fade in after axes are drawn. */}
        <g
          style={{
            opacity: gridIn ? 1 : 0,
            transition: "opacity 400ms ease-out",
          }}
        >
          {yTickValues.map((v, i) => (
            <g key={"gy" + i}>
              <line
                x1={pad.l}
                y1={py(v)}
                x2={w - pad.r}
                y2={py(v)}
                stroke="hsl(var(--border))"
                strokeWidth={0.6}
                strokeDasharray={i === 0 ? "" : "2 3"}
                opacity={i === 0 ? 1 : 0.5}
              />
              <text
                x={pad.l - 6}
                y={py(v) + 3}
                textAnchor="end"
                fontSize="8.5"
                fill="hsl(var(--muted-foreground))"
              >
                +{(v / 100).toFixed(1)}%
              </text>
            </g>
          ))}
          {xTickValues.map((v, i) => (
            <g key={"gx" + i}>
              <line
                x1={px(v)}
                y1={pad.t}
                x2={px(v)}
                y2={h - pad.b}
                stroke="hsl(var(--border))"
                strokeWidth={0.6}
                strokeDasharray={i === 0 ? "" : "2 3"}
                opacity={i === 0 ? 1 : 0.5}
              />
              <text
                x={px(v)}
                y={h - pad.b + 14}
                textAnchor="middle"
                fontSize="8.5"
                fill="hsl(var(--muted-foreground))"
              >
                {(v / 100).toFixed(2)}%
              </text>
            </g>
          ))}
        </g>

        {/* Axis titles — fade in with the axes. */}
        <g
          style={{
            opacity: axesIn ? 1 : 0,
            transition: "opacity 300ms ease-out",
          }}
        >
          <text
            x={pad.l + plotW / 2}
            y={h - 6}
            textAnchor="middle"
            fontSize="9"
            fill="hsl(var(--muted-foreground))"
            fontWeight={500}
          >
            Weighted rate
          </text>
          <text
            transform={`translate(12 ${pad.t + plotH / 2}) rotate(-90)`}
            textAnchor="middle"
            fontSize="9"
            fill="hsl(var(--muted-foreground))"
            fontWeight={500}
          >
            Concentration added
          </text>
        </g>

        {/* Candidate points — each one pops in on its own beat. */}
        {plan.candidates.map((c, i) => {
          const p = placements[i];
          const isRec = c.kind === plan.recommendation_kind;
          const colour = ACCENT[c.kind];
          const visible = i < dotsVisible;
          return (
            <g
              key={c.kind}
              onPointerEnter={(e) => tip.show(e, dotTooltip(c))}
              onPointerLeave={tip.hide}
              style={{
                opacity: visible ? 1 : 0,
                transform: visible ? "scale(1)" : "scale(0.5)",
                transformOrigin: `${p.cx}px ${p.cy}px`,
                transformBox: "fill-box",
                cursor: "pointer",
                transition:
                  "opacity 220ms ease-out, transform 260ms cubic-bezier(.34, 1.56, .64, 1)",
              }}
            >
              {isRec ? (
                <circle
                  cx={p.cx}
                  cy={p.cy}
                  r={13}
                  fill="none"
                  stroke={colour}
                  strokeWidth={1.5}
                  opacity={0.45}
                />
              ) : null}
              {/* A generous invisible hit target, so the hover works
                  without pixel-perfect aim. `pointer-events="all"` is
                  the SVG trick for invisible interactive elements: a
                  transparent fill is treated as no-paint and receives
                  no events by default. */}
              <circle
                cx={p.cx}
                cy={p.cy}
                r={18}
                fill="transparent"
                pointerEvents="all"
              />
              <circle
                cx={p.cx}
                cy={p.cy}
                r={6}
                fill={colour}
                stroke="hsl(var(--card))"
                strokeWidth={1.5}
              />
              <text
                x={p.cx}
                y={p.cy + 3}
                textAnchor="middle"
                fontSize="8"
                fontWeight={700}
                fill="hsl(var(--card))"
              >
                {i + 1}
              </text>
              {/* Compact rate / concentration label — fades in only
                  after every dot has landed, so the eye tracks the dots
                  first and the numbers second. */}
              <g
                style={{
                  opacity: labelsIn ? 1 : 0,
                  transition: `opacity 300ms ease-out ${i * 60}ms`,
                }}
              >
                <text
                  x={p.lx}
                  y={p.ly}
                  textAnchor={p.anchor}
                  fontSize="9.5"
                  fontWeight={600}
                  fill="hsl(var(--foreground))"
                >
                  {perCent(c.weighted_rate_bp)}
                </text>
                <text
                  x={p.lx}
                  y={p.ly + 11}
                  textAnchor={p.anchor}
                  fontSize="8.5"
                  fill="hsl(var(--muted-foreground))"
                >
                  +{perCent(c.concentration_change_bp)}
                </text>
              </g>
            </g>
          );
        })}
      </svg>

      {tip.render()}

      {/* Numbered legend under the chart. Same order the dots use. */}
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {plan.candidates.map((c, i) => (
          <div key={c.kind} className="flex items-center gap-1.5">
            <span
              className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-full text-[8px] font-bold text-white"
              style={{ background: ACCENT[c.kind] }}
              aria-hidden
            >
              {i + 1}
            </span>
            <span className="text-[10px] text-muted-foreground">{c.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

