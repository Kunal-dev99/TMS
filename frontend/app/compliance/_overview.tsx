"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";

import {
  getComplianceOverview,
  type ComplianceOverview,
} from "@/lib/api";

/**
 * Overview tab — compact strip of counts a compliance officer scans
 * first thing in the morning. Everything is derivable from tables
 * we already have: audit_event, exception_item, check_run, deal.
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

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Kpi
          label="Open breaches"
          value={data.open_breaches}
          tone={data.open_breaches > 0 ? "bad" : "ok"}
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
          onClick={onGoToAudit}
          hint="Anything the audit trail recorded"
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

      <div className="text-[10px] italic text-muted-foreground">
        Generated {new Date(data.generated_at).toLocaleString()} ·{" "}
        {Intl.DateTimeFormat().resolvedOptions().timeZone}
      </div>
    </div>
  );
}

function Kpi({
  label,
  value,
  tone,
  onClick,
  hint,
}: {
  label: string;
  value: number;
  tone: "ok" | "bad" | "warn" | "muted";
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
      <div className="text-[10px] font-semibold uppercase text-muted-foreground">
        {label}
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
