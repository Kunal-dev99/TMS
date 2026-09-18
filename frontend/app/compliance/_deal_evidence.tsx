"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Search, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  getComplianceDealEvidence,
  type ComplianceDealEvidence,
} from "@/lib/api";

/**
 * Deal evidence tab.
 *
 * Enter a deal id -> assemble the complete picture:
 *   * terms
 *   * proposer + approver
 *   * six-check evidence with values-vs-limits
 *   * policy version + counterparty limit in force AT BOOKING
 *   * complete audit-event history
 *
 * All read-only; the operational deal panel remains the only place
 * to act on the deal.
 */
export function DealEvidenceTab({
  initialDealId,
}: {
  initialDealId?: string | null;
}) {
  const [dealId, setDealId] = useState(initialDealId ?? "");
  const [data, setData] = useState<ComplianceDealEvidence | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (id: string) => {
    const trimmed = id.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    setData(null);
    try {
      const v = await getComplianceDealEvidence(trimmed);
      setData(v);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  };

  // Auto-load if a deep-link supplied a deal id.
  useEffect(() => {
    if (initialDealId) load(initialDealId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialDealId]);

  return (
    <div className="space-y-3">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          load(dealId);
        }}
        className="flex flex-wrap items-end gap-2 rounded-lg border border-border bg-surface-2/40 p-3"
      >
        <div className="flex-1 min-w-[16rem]">
          <label className="text-[10px] font-semibold uppercase text-muted-foreground">
            Deal ID
          </label>
          <input
            type="text"
            value={dealId}
            onChange={(e) => setDealId(e.target.value)}
            placeholder="deal_…"
            className="mt-0.5 w-full rounded border border-border bg-background px-2 py-1 text-xs font-mono"
          />
        </div>
        <Button size="sm" className="h-7 text-xs" type="submit" disabled={loading}>
          {loading ? (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          ) : (
            <Search className="mr-1 h-3 w-3" />
          )}
          Open evidence
        </Button>
      </form>

      {error ? (
        <div className="rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      ) : null}

      {!data && !error && !loading ? (
        <div className="rounded border border-dashed border-border bg-surface-2/40 p-4 text-xs text-muted-foreground">
          Enter a deal id to open its evidence file — the six checks, the
          policy version in force at booking, and the complete audit history.
          Deal ids appear in the audit trail (subject) and in the breaches
          register.
        </div>
      ) : null}

      {data ? <EvidenceView data={data} /> : null}
    </div>
  );
}

function EvidenceView({ data }: { data: ComplianceDealEvidence }) {
  const passed = data.six_checks.filter((c) => c.passed).length;
  const failed = data.six_checks.length - passed;
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-border bg-surface-2/40 p-3">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <div className="text-[10px] font-semibold uppercase text-muted-foreground">
              Deal
            </div>
            <div className="text-base font-semibold">
              {data.counterparty_name}{" "}
              <span className="text-muted-foreground text-xs">
                ({data.counterparty_rating ?? "—"})
              </span>
            </div>
            <div className="font-mono text-[10px] text-muted-foreground">
              {data.deal_id}
            </div>
          </div>
          <StatusBadge status={data.status} />
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] sm:grid-cols-4">
          <Field label="Instrument" value={data.instrument} />
          <Field
            label="Principal"
            value={`${data.currency} ${(data.principal_pence / 100).toLocaleString()}`}
          />
          <Field label="Rate" value={`${(data.rate_bp / 100).toFixed(2)}%`} />
          <Field label="Tenor" value={`${data.tenor_months}m`} />
          <Field label="Trade date" value={data.trade_date} />
          <Field label="Value date" value={data.value_date} />
          <Field label="Maturity" value={data.maturity_date ?? "—"} />
          <Field label="Entity" value={data.legal_entity_id ?? "—"} />
        </dl>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-border bg-surface-2/40 p-3">
          <div className="mb-2 text-[10px] font-semibold uppercase text-muted-foreground">
            Authority
          </div>
          <dl className="space-y-1 text-[11px]">
            <Line label="Proposed by" value={data.proposer_display ?? "—"} />
            <Line label="Approved by" value={data.approver_display ?? "—"} />
            <Line label="Required role" value={data.required_approver ?? "—"} />
            {data.override_reason ? (
              <div className="mt-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[10.5px] text-amber-600">
                <b>Override:</b> {data.override_reason}
              </div>
            ) : null}
          </dl>
        </div>

        <div className="rounded-lg border border-border bg-surface-2/40 p-3">
          <div className="mb-2 text-[10px] font-semibold uppercase text-muted-foreground">
            Policy &amp; limit at booking
          </div>
          <dl className="space-y-1 text-[11px]">
            <Line
              label="Policy version"
              value={data.policy_version_id ?? "—"}
              mono
            />
            <Line
              label="Effective from"
              value={data.policy_version_effective_from ?? "—"}
            />
            <Line label="Limit id" value={data.limit_id ?? "—"} mono />
            <Line
              label="Limit amount"
              value={
                data.limit_amount_pence !== null
                  ? `${data.currency} ${(data.limit_amount_pence / 100).toLocaleString()}`
                  : "—"
              }
            />
          </dl>
          <div className="mt-1.5 text-[9.5px] italic text-muted-foreground">
            {data.policy_version_note}
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-surface-2/40 p-3">
        <div className="mb-2 flex items-baseline justify-between">
          <div className="text-[10px] font-semibold uppercase text-muted-foreground">
            Six checks
          </div>
          <div className="text-[10px] text-muted-foreground">
            {data.booking_outcome ? (
              <>
                Booking outcome:{" "}
                <span className="font-medium text-foreground">
                  {data.booking_outcome}
                </span>{" "}
                · {passed} passed, {failed} failed
              </>
            ) : (
              <>No booking check_run recorded</>
            )}
          </div>
        </div>
        {data.six_checks.length === 0 ? (
          <div className="text-[10.5px] italic text-muted-foreground">
            No individual check results were captured on this deal.
          </div>
        ) : (
          <ul className="space-y-1">
            {data.six_checks.map((c, i) => (
              <li
                key={i}
                className={
                  "flex items-start gap-2 rounded border px-2 py-1.5 text-[11px] " +
                  (c.passed
                    ? "border-emerald-500/40 bg-emerald-500/5"
                    : "border-destructive/40 bg-destructive/5")
                }
              >
                {c.passed ? (
                  <CheckCircle2 className="h-3.5 w-3.5 mt-0.5 text-emerald-500 shrink-0" />
                ) : (
                  <XCircle className="h-3.5 w-3.5 mt-0.5 text-destructive shrink-0" />
                )}
                <div className="flex-1">
                  <div className="font-medium">{c.key}</div>
                  {c.detail ? (
                    <div className="text-[10.5px] text-muted-foreground">
                      {c.detail}
                    </div>
                  ) : null}
                  {c.value && Object.keys(c.value).length > 0 ? (
                    <dl className="mt-0.5 grid grid-cols-2 gap-x-3 text-[10px] text-muted-foreground sm:grid-cols-3">
                      {Object.entries(c.value).map(([k, v]) => (
                        <div key={k} className="flex gap-1.5">
                          <dt>{k}:</dt>
                          <dd className="font-mono">{formatValue(v)}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="rounded-lg border border-border bg-surface-2/40 p-3">
        <div className="mb-2 text-[10px] font-semibold uppercase text-muted-foreground">
          Event history
        </div>
        {data.events.length === 0 ? (
          <div className="text-[10.5px] italic text-muted-foreground">
            No events recorded against this deal.
          </div>
        ) : (
          <ol className="space-y-1">
            {data.events.map((e) => (
              <li
                key={e.id}
                className="flex items-start gap-2 border-b border-border/40 pb-1 text-[10.5px]"
              >
                <div className="min-w-[10rem] font-mono text-[10px] text-muted-foreground whitespace-nowrap">
                  {new Date(e.occurred_at).toLocaleString()}
                </div>
                <div className="flex-1">
                  <div>
                    <b>{e.action_label || e.action}</b>{" "}
                    {e.actor_display ? (
                      <span className="text-muted-foreground">
                        by {e.actor_display}
                      </span>
                    ) : null}
                    {e.outcome ? (
                      <span className="ml-1 text-muted-foreground">
                        · {e.outcome}
                      </span>
                    ) : null}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-[9.5px] uppercase text-muted-foreground">{label}</dt>
      <dd className="text-[11px]">{value}</dd>
    </div>
  );
}

function Line({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex gap-2 border-b border-border/30 py-0.5">
      <dt className="text-[10px] font-medium text-muted-foreground min-w-[7rem]">
        {label}
      </dt>
      <dd className={"text-[10.5px] break-all " + (mono ? "font-mono" : "")}>
        {value}
      </dd>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "BOOKED" || status === "APPROVED" || status === "SETTLED"
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-500"
      : status === "BLOCKED" || status === "REJECTED"
        ? "border-destructive/40 bg-destructive/10 text-destructive"
        : "border-amber-500/40 bg-amber-500/10 text-amber-500";
  return (
    <span className={`rounded border px-2 py-0.5 text-[10px] font-medium ${tone}`}>
      {status}
    </span>
  );
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}
