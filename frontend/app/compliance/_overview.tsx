"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  TrendingDown,
  TrendingUp,
  Minus,
} from "lucide-react";

import {
  getComplianceOverview,
  type ComplianceOverview,
  type ComplianceTopEntry,
} from "@/lib/api";

/**
 * Overview tab — compact strip of counts + 7d-vs-prior-7d trend +
 * "who / what" leader boards a compliance officer scans first thing
 * in the morning.
 */
export function OverviewTab({
  onGoToBreaches,
  onGoToAudit,
}: {
  onGoToBreaches: () => void;
  onGoToAudit: () => void;
}) {
  const [data, setData] = useState<ComplianceOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getComplianceOverview()
      .then(setData)
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" /> Loading overview…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
        {error}
      </div>
    );
  }
  if (!data) return null;

  const missingEvidence = data.deals_missing_evidence;
  const needsAttention = data.open_breaches + missingEvidence;
  const eventsTrend = trendDelta(data.events_last_7d, data.events_prior_7d);
  const breachTrend = trendDelta(
    data.open_breaches,
    data.open_breaches_prior_period,
    /* invert */ true, // fewer breaches is good
  );

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Kpi
          label="Open breaches"
          value={data.open_breaches}
          tone={data.open_breaches > 0 ? "bad" : "ok"}
          trend={breachTrend}
          onClick={onGoToBreaches}
          hint="Six-check failures still open"
        />
        <Kpi
          label="Overrides (YTD)"
          value={data.overrides_ytd}
          tone={data.overrides_ytd > 0 ? "warn" : "muted"}
          onClick={onGoToBreaches}
          hint="Signers who forced deals through"
        />
        <Kpi
          label="Resolved (YTD)"
          value={data.resolved_ytd}
          tone="ok"
          onClick={onGoToBreaches}
          hint="Breaches closed with a written resolution"
        />
        <Kpi
          label="Events (last 7d)"
          value={data.events_last_7d}
          tone="muted"
          trend={eventsTrend}
          onClick={onGoToAudit}
          hint={`Prior 7 days: ${data.events_prior_7d.toLocaleString()}`}
        />
        <Kpi
          label="Deals missing evidence"
          value={missingEvidence}
          tone={missingEvidence > 0 ? "bad" : "ok"}
          hint="Should always be zero on this codebase"
        />
      </div>

      {needsAttention > 0 ? (
        <div className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs">
          <div className="mb-1 flex items-center gap-1.5 font-medium text-amber-600">
            <AlertTriangle className="h-3.5 w-3.5" /> {needsAttention} item(s) need attention
          </div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            {data.open_breaches > 0 ? (
              <li>
                {data.open_breaches} open breach{data.open_breaches === 1 ? "" : "es"} — see the
                Breaches &amp; overrides tab.
              </li>
            ) : null}
            {missingEvidence > 0 ? (
              <li>
                {missingEvidence} deal{missingEvidence === 1 ? "" : "s"} with no six-check
                evidence — this is a data-integrity issue, escalate to engineering.
              </li>
            ) : null}
          </ul>
        </div>
      ) : (
        <div className="rounded border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-xs">
          <div className="flex items-center gap-1.5 text-emerald-500">
            <CheckCircle2 className="h-3.5 w-3.5" /> No open items. The register is clean today.
          </div>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <LeaderCard
          title="Top actors — last 7 days"
          empty="No one has been active in the last 7 days."
          items={data.top_actors_7d}
          onItemClick={onGoToAudit}
        />
        <LeaderCard
          title="Top actions — last 7 days"
          empty="No activity in the last 7 days."
          items={data.top_actions_7d}
          onItemClick={onGoToAudit}
        />
      </div>

      <div className="text-[10px] italic text-muted-foreground">
        Generated {new Date(data.generated_at).toLocaleString()} ·{" "}
        {Intl.DateTimeFormat().resolvedOptions().timeZone}
      </div>
    </div>
  );
}

type Trend = { delta: number; direction: "up" | "down" | "flat"; good: boolean };

function trendDelta(current: number, prior: number, invert = false): Trend {
  const delta = current - prior;
  const direction: Trend["direction"] =
    delta === 0 ? "flat" : delta > 0 ? "up" : "down";
  const raw = direction === "up";
  const good = invert ? !raw : raw;
  return { delta, direction, good };
}

function TrendChip({ trend }: { trend: Trend }) {
  if (trend.direction === "flat") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded border border-border bg-background px-1 py-0 text-[9.5px] text-muted-foreground">
        <Minus className="h-2.5 w-2.5" /> 0
      </span>
    );
  }
  const Icon = trend.direction === "up" ? TrendingUp : TrendingDown;
  const cls = trend.good ? "text-emerald-500" : "text-destructive";
  const sign = trend.delta > 0 ? "+" : "";
  return (
    <span
      className={`inline-flex items-center gap-0.5 rounded border border-border bg-background px-1 py-0 text-[9.5px] ${cls}`}
      title="Vs prior 7 days"
    >
      <Icon className="h-2.5 w-2.5" /> {sign}
      {trend.delta.toLocaleString()}
    </span>
  );
}

function Kpi({
  label,
  value,
  tone,
  trend,
  onClick,
  hint,
}: {
  label: string;
  value: number;
  tone: "ok" | "bad" | "warn" | "muted";
  trend?: Trend;
  onClick?: () => void;
  hint?: string;
}) {
  const toneCls =
    tone === "ok"
      ? "text-emerald-500"
      : tone === "bad"
        ? "text-destructive"
        : tone === "warn"
          ? "text-amber-500"
          : "text-foreground";
  const clickable = !!onClick;
  return (
    <div
      role={clickable ? "button" : undefined}
      onClick={onClick}
      className={
        "rounded-lg border border-border bg-surface-2/40 p-3 " +
        (clickable ? "cursor-pointer hover:border-primary/40" : "")
      }
      title={hint}
    >
      <div className="flex items-center justify-between">
        <div className="text-[10px] font-semibold uppercase text-muted-foreground">
          {label}
        </div>
        {trend ? <TrendChip trend={trend} /> : null}
      </div>
      <div className={`mt-1 num text-2xl font-semibold ${toneCls}`}>
        {value.toLocaleString()}
      </div>
      {hint ? (
        <div className="mt-0.5 text-[10px] text-muted-foreground">{hint}</div>
      ) : null}
    </div>
  );
}

function LeaderCard({
  title,
  empty,
  items,
  onItemClick,
}: {
  title: string;
  empty: string;
  items: ComplianceTopEntry[];
  onItemClick?: () => void;
}) {
  const max = items.reduce((m, i) => Math.max(m, i.count), 0) || 1;
  return (
    <div className="rounded-lg border border-border bg-surface-2/40 p-3">
      <div className="mb-2 text-[10px] font-semibold uppercase text-muted-foreground">
        {title}
      </div>
      {items.length === 0 ? (
        <div className="text-[10.5px] italic text-muted-foreground">{empty}</div>
      ) : (
        <ul className="space-y-1">
          {items.map((it) => {
            const pct = Math.max(4, Math.round((it.count / max) * 100));
            return (
              <li
                key={it.key}
                className={
                  "grid grid-cols-[1fr_auto] items-center gap-2 " +
                  (onItemClick ? "cursor-pointer" : "")
                }
                onClick={onItemClick}
              >
                <div>
                  <div className="text-[11px]">{it.label}</div>
                  <div className="mt-0.5 h-1 w-full rounded bg-border/60">
                    <div
                      className="h-1 rounded bg-primary/70"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
                <div className="num text-[11px] font-medium tabular-nums">
                  {it.count.toLocaleString()}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
