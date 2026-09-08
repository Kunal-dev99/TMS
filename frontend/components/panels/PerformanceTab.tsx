"use client";

import { useEffect, useState } from "react";
import { TrendingUp } from "lucide-react";

import { getPerformance, type PerformanceView } from "@/lib/api";
import { perCent, sterling } from "@/lib/format";

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
