"use client";

import { useEffect, useState } from "react";
import { ArrowRight, Loader2, ShieldCheck } from "lucide-react";

import {
  getCompliancePolicyHistory,
  type CompliancePolicyHistory,
  type CompliancePolicyVersion,
} from "@/lib/api";

/**
 * Policy history tab.
 *
 * Newest version first, current one flagged, each row expandable to
 * show what changed from the previous version, who wrote it, who
 * authorised it, and the free-text note.
 *
 * Reads /compliance/policy/history which returns the per-version
 * diff pre-computed server-side. Read-only.
 */
export function PolicyHistoryTab() {
  const [data, setData] = useState<CompliancePolicyHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getCompliancePolicyHistory()
      .then(setData)
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" /> Loading policy history…
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

  if (data.versions.length === 0) {
    return (
      <div className="rounded border border-dashed border-border bg-surface-2/40 p-4 text-xs text-muted-foreground">
        No policy versions found for this tenant.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="rounded border border-border bg-surface-2/40 p-2.5 text-[10.5px] text-muted-foreground">
        Newest first. The current version is the one with no{" "}
        <b>superseded at</b>. Each row lists what changed from the
        previous version, who wrote it and who authorised it. Older
        versions may show "not recorded" for the authoriser — the
        four-eye control (ADR-0015) only applies to versions written
        after the policy_version change-metadata migration.
      </div>

      <ol className="space-y-2">
        {data.versions.map((v, i) => (
          <VersionCard
            key={v.id}
            v={v}
            index={data.versions.length - i}
          />
        ))}
      </ol>

      <div className="text-[10px] italic text-muted-foreground">
        Generated {new Date(data.generated_at).toLocaleString()} ·{" "}
        {Intl.DateTimeFormat().resolvedOptions().timeZone}
      </div>
    </div>
  );
}

function VersionCard({
  v,
  index,
}: {
  v: CompliancePolicyVersion;
  index: number;
}) {
  const changed = Object.keys(v.changes);
  return (
    <li className="rounded-lg border border-border bg-surface-2/40 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-3.5 w-3.5 text-muted-foreground" />
            <div className="font-medium">Policy v{index}</div>
            {v.is_current ? (
              <span className="rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[9.5px] font-medium text-emerald-500">
                Current
              </span>
            ) : (
              <span className="rounded border border-border bg-background px-1.5 py-0.5 text-[9.5px] text-muted-foreground">
                Superseded
              </span>
            )}
          </div>
          <div className="font-mono text-[10px] text-muted-foreground">
            {v.id}
          </div>
        </div>
        <div className="text-right text-[10px] text-muted-foreground">
          <div>
            Effective from{" "}
            <b className="text-foreground">{v.effective_from}</b>
          </div>
          {v.superseded_at ? (
            <div>
              Superseded {new Date(v.superseded_at).toLocaleString()}
            </div>
          ) : null}
        </div>
      </div>

      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[10.5px] sm:grid-cols-4">
        <Field
          label="Concentration cap"
          value={`${(v.concentration_cap_bp / 100).toFixed(2)}%`}
        />
        <Field
          label="Analyst threshold"
          value={`GBP ${(v.threshold_analyst_pence / 100).toLocaleString()}`}
        />
        <Field
          label="Head-of-treasury threshold"
          value={`GBP ${(v.threshold_hot_pence / 100).toLocaleString()}`}
        />
        <Field label="Enforcement" value={v.enforcement} />
        <Field label="FX add-on" value={`${(v.fx_add_on_bp / 100).toFixed(2)}%`} />
        <Field
          label="Approved by"
          value={v.approved_by || "—"}
        />
        <Field
          label="Changed by"
          value={v.changed_by_display ?? "not recorded"}
        />
        <Field
          label="Authorised by"
          value={v.authorised_by_display ?? "not recorded"}
        />
      </dl>

      {v.note ? (
        <div className="mt-2 rounded border border-border/60 bg-background p-2 text-[10.5px]">
          <div className="mb-0.5 text-[9.5px] font-semibold uppercase text-muted-foreground">
            Note
          </div>
          {v.note}
        </div>
      ) : null}

      <div className="mt-2 border-t border-border/40 pt-2">
        <div className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">
          Changes from previous version
        </div>
        {changed.length === 0 ? (
          <div className="text-[10.5px] italic text-muted-foreground">
            {v.superseded_at || index !== 1
              ? "No prior version — this is the earliest recorded policy."
              : "No policy fields differ from the previous version."}
          </div>
        ) : (
          <ul className="space-y-1">
            {changed.map((field) => (
              <li
                key={field}
                className="flex flex-wrap items-baseline gap-1.5 text-[10.5px]"
              >
                <span className="font-mono text-[10px] text-muted-foreground min-w-[12rem]">
                  {field}
                </span>
                <span className="rounded border border-destructive/40 bg-destructive/5 px-1.5 py-0.5 font-mono text-[10px] text-destructive line-through">
                  {formatValue(v.changes[field].from)}
                </span>
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <span className="rounded border border-emerald-500/40 bg-emerald-500/5 px-1.5 py-0.5 font-mono text-[10px] text-emerald-500">
                  {formatValue(v.changes[field].to)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[9.5px] uppercase text-muted-foreground">{label}</dt>
      <dd className="text-[11px]">{value}</dd>
    </div>
  );
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}
