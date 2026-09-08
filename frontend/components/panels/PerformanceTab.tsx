"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Sparkles, TrendingDown, TrendingUp } from "lucide-react";

import {
  getPerformance,
  type PerformanceInsight,
  type PerformanceLens,
  type PerformanceView,
} from "@/lib/api";
import { perCent, sterling } from "@/lib/format";
import { TypedText } from "@/components/panels/TypedText";

/**
 * Performance — Anil's Sep-8 ask: "where you have the exposure, you
 * need another tab for performance. How much income you have generated
 * overall."
 *
 * Three shapes over the accrual table: a total-earned stat, a table by
 * counterparty, and a monthly cumulative-interest sparkline. Every
 * figure is what was recognised, never a forecast — forecasts live in
 * EPM / Cash Positioning, not here.
 */
const BAND_COLOR: Record<string, string> = {
  AAA: "hsl(var(--success))",
  AA:  "hsl(var(--primary))",
  A:   "hsl(var(--warning))",
  BBB: "hsl(var(--muted-foreground))",
};

export function PerformanceTab({ open }: { open: boolean }) {
  const [view, setView] = useState<PerformanceView | null>(null);
  const [loading, setLoading] = useState(false);
  const [lens, setLens] = useState<PerformanceLens>("yield");
  const [redrafts, setRedrafts] = useState(0);
  const [projMonths, setProjMonths] = useState<3 | 6 | 12>(12);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    const controller = new AbortController();
    getPerformance(controller.signal)
      .then((v) => { if (!cancelled) setView(v); })
      .catch(() => undefined)
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [open]);

  if (loading && !view) {
    return (
      <p className="py-6 text-center text-xs text-muted-foreground">
        Reading the accruals…
      </p>
    );
  }

  if (!view || view.total_interest_pence === 0) {
    return (
      <div className="rounded border border-dashed border-border bg-surface-2/30 p-6 text-center">
        <p className="text-xs text-muted-foreground">
          No interest recognised yet. Run the nightly job to accrue today's
          interest, or wait for the scheduler.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Headline stats */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard
          label="Income to date"
          value={sterling(view.total_interest_pence)}
          highlight
        />
        <StatCard
          label="Weighted rate"
          value={perCent(view.weighted_rate_bp)}
        />
        <StatCard
          label="Days recognised"
          value={String(view.days_recognised)}
        />
      </div>

      {/* Insights — AI-styled cards with a lens toggle. Change lens
          or click Re-draft and the cards type in again. */}
      {view.insights_by_lens ? (
        <section>
          <div className="mb-2 flex items-center gap-1.5 flex-wrap">
            <Sparkles className="h-3 w-3 text-primary" aria-hidden />
            <h3 className="text-xs font-semibold uppercase tracking-wider text-primary">
              Insights
            </h3>
            <span className="text-[10px] text-muted-foreground">
              switch lens · re-draft
            </span>
            <div className="ml-auto flex items-center gap-1">
              <LensButton
                label="Yield"
                active={lens === "yield"}
                onClick={() => { setLens("yield"); setRedrafts((n) => n + 1); }}
              />
              <LensButton
                label="Diversification"
                active={lens === "diversification"}
                onClick={() => { setLens("diversification"); setRedrafts((n) => n + 1); }}
              />
              <LensButton
                label="Safety"
                active={lens === "safety"}
                onClick={() => { setLens("safety"); setRedrafts((n) => n + 1); }}
              />
              <button
                type="button"
                onClick={() => setRedrafts((n) => n + 1)}
                title="Re-draft with the same lens"
                className="ml-1 rounded border border-border bg-surface-2/40 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-muted-foreground hover:text-primary hover:border-primary/40"
              >
                Re-draft
              </button>
            </div>
          </div>
          <div className="space-y-2">
            {(view.insights_by_lens[lens] ?? []).map((ins, i) => (
              <InsightCard
                key={`${lens}-${redrafts}-${i}`}
                insight={ins}
                typing
              />
            ))}
          </div>
        </section>
      ) : null}

      {/* Projection — extrapolate the last month's run rate. */}
      {view.projection ? (
        <section>
          <div className="mb-2 flex items-center gap-1.5">
            <TrendingUp className="h-3 w-3 text-primary" aria-hidden />
            <h3 className="text-xs font-semibold uppercase tracking-wider text-primary">
              Projection
            </h3>
            <span className="text-[10px] text-muted-foreground">
              if {view.projection.based_on_month}'s pace holds
            </span>
          </div>
          <div className="rounded-lg border border-primary/30 bg-primary/5 p-3">
            <div className="mb-3 flex items-center gap-1">
              {([3, 6, 12] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setProjMonths(m)}
                  className={`rounded px-2 py-0.5 text-[10px] font-medium transition-colors ${
                    projMonths === m
                      ? "bg-primary text-primary-foreground"
                      : "bg-surface-2/60 text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {m} months
                </button>
              ))}
            </div>
            <div className="flex items-baseline gap-2">
              <span className="num text-2xl font-semibold text-primary">
                {sterling(
                  projMonths === 3
                    ? view.projection.three_month_pence
                    : projMonths === 6
                      ? view.projection.six_month_pence
                      : view.projection.twelve_month_pence,
                )}
              </span>
              <span className="text-[10.5px] text-muted-foreground">
                projected over the next {projMonths} months, based on{" "}
                {view.projection.based_on_month} run rate of{" "}
                <span className="font-medium text-foreground">
                  {sterling(view.projection.monthly_run_rate_pence)}/mo
                </span>
              </span>
            </div>
          </div>
        </section>
      ) : null}

      {/* By-band bar */}
      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Income by rating band
        </h3>
        <div className="rounded border border-border bg-surface-2/40 p-3">
          <div className="mb-3 flex h-2 w-full overflow-hidden rounded-full bg-surface-2">
            {view.by_band.map((b) => {
              if (b.share_bp <= 0) return null;
              return (
                <div
                  key={b.band}
                  style={{
                    width: `${b.share_bp / 100}%`,
                    background: BAND_COLOR[b.band] ?? "hsl(var(--muted-foreground))",
                  }}
                  title={`${b.band}: ${perCent(b.share_bp)}`}
                />
              );
            })}
          </div>
          <div className="grid grid-cols-4 gap-2">
            {view.by_band.map((b) => (
              <div key={b.band} className="text-center">
                <div className="flex items-center justify-center gap-1.5">
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ background: BAND_COLOR[b.band] ?? "hsl(var(--muted-foreground))" }}
                  />
                  <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                    {b.band}
                  </span>
                </div>
                <div className="mt-1 text-xs font-medium">
                  {sterling(b.interest_pence)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* By counterparty */}
      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Income by counterparty
        </h3>
        <div className="overflow-hidden rounded border border-border">
          <table className="w-full text-xs">
            <thead className="bg-surface-2/60 text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">Counterparty</th>
                <th className="px-3 py-2 text-right">Deals</th>
                <th className="px-3 py-2 text-right">Interest</th>
                <th className="px-3 py-2 text-right">Share</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {view.by_counterparty.map((c) => (
                <tr key={c.counterparty_id} className="hover:bg-surface-2/40">
                  <td className="px-3 py-2">
                    <div className="font-medium text-foreground">{c.name}</div>
                    <div className="text-[10px] text-muted-foreground">
                      {c.rating} · band {c.band}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right num">{c.deal_count}</td>
                  <td className="px-3 py-2 text-right num font-medium">
                    {sterling(c.interest_pence)}
                  </td>
                  <td className="px-3 py-2 text-right num text-muted-foreground">
                    {perCent(c.share_bp)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Monthly cumulative */}
      {view.by_month.length ? (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Running total by month
          </h3>
          <div className="rounded border border-border bg-surface-2/40 p-3">
            <MonthlyChart data={view.by_month} />
          </div>
        </section>
      ) : null}

      <p className="text-[10px] italic text-muted-foreground">
        <TrendingUp className="mb-0.5 mr-1 inline h-2.5 w-2.5" />
        What was recognised, not projected. Forecasts live in Cash
        Positioning (Oracle EPM); the Register reports realised income.
      </p>
    </div>
  );
}

function LensButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded px-2 py-0.5 text-[10px] font-medium transition-colors ${
        active
          ? "bg-primary text-primary-foreground"
          : "bg-surface-2/60 text-muted-foreground hover:text-foreground"
      }`}
    >
      {label}
    </button>
  );
}

function InsightCard({
  insight,
  typing = false,
}: {
  insight: PerformanceInsight;
  typing?: boolean;
}) {
  const palette =
    insight.kind === "watch"
      ? {
          border: "border-warning/40",
          bg: "bg-warning/5",
          text: "text-warning",
          Icon: AlertTriangle,
        }
      : insight.kind === "positive"
        ? {
            border: "border-success/40",
            bg: "bg-success/5",
            text: "text-success",
            Icon: TrendingUp,
          }
        : {
            border: "border-primary/30",
            bg: "bg-primary/5",
            text: "text-primary",
            Icon: TrendingDown,
          };
  const { Icon } = palette;
  return (
    <div className={`rounded-lg border p-3 ${palette.border} ${palette.bg}`}>
      <div className="flex items-start gap-2">
        <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${palette.text}`} />
        <div className="min-w-0">
          <div className={`text-[11px] font-semibold ${palette.text}`}>
            {insight.title}
          </div>
          <p className="mt-0.5 text-[11px] leading-relaxed text-foreground">
            {typing ? (
              <TypedText text={insight.body} charsPerSecond={120} />
            ) : (
              insight.body
            )}
          </p>
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-3 ${
        highlight
          ? "border-primary/40 bg-primary/5"
          : "border-border bg-surface-2/40"
      }`}
    >
      <p className="text-[9px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p
        className={`num mt-0.5 text-lg font-semibold ${
          highlight ? "text-primary" : "text-foreground"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function MonthlyChart({
  data,
}: {
  data: { month: string; interest_pence: number; cumulative_pence: number }[];
}) {
  if (data.length === 0) return null;
  const W = 560;
  const H = 120;
  const P = 18;
  const maxCum = Math.max(...data.map((d) => d.cumulative_pence));
  const xStep = (W - 2 * P) / Math.max(1, data.length - 1);
  const pts = data.map((d, i) => {
    const x = P + i * xStep;
    const y = H - P - ((d.cumulative_pence / (maxCum || 1)) * (H - 2 * P));
    return { x, y, d };
  });
  const path = pts
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(" ");
  const fillPath = `${path} L ${pts[pts.length - 1].x.toFixed(1)} ${H - P} L ${pts[0].x.toFixed(1)} ${H - P} Z`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-32 w-full">
      <path d={fillPath} fill="hsl(var(--primary) / 0.12)" />
      <path d={path} fill="none" stroke="hsl(var(--primary))" strokeWidth={1.5} />
      {pts.map((p, i) => (
        <g key={i}>
          <circle cx={p.x} cy={p.y} r={2.5} fill="hsl(var(--primary))" />
          <text
            x={p.x}
            y={H - 4}
            textAnchor="middle"
            className="fill-current text-[8px] text-muted-foreground"
          >
            {p.d.month.slice(5)}/{p.d.month.slice(2, 4)}
          </text>
          {i === pts.length - 1 ? (
            <text
              x={p.x}
              y={p.y - 6}
              textAnchor="end"
              className="fill-current text-[9px] font-medium text-foreground"
            >
              {sterling(p.d.cumulative_pence)}
            </text>
          ) : null}
        </g>
      ))}
    </svg>
  );
}
