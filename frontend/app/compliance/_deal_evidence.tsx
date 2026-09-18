"use client";

import { useEffect, useState } from "react";
import {
  CheckCircle2,
  Clipboard,
  ClipboardCheck,
  Loader2,
  Search,
  XCircle,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  getComplianceDealEvidence,
  getComplianceRecentDeals,
  type ComplianceCheckLine,
  type ComplianceDealEvidence,
  type ComplianceRecentDeal,
} from "@/lib/api";

/**
 * Deal evidence tab.
 *
 * Enter a deal id OR pick from a "recent deals" list -> assemble
 * proposer + approver + six-check evidence with values-vs-limits +
 * policy version + limit + full event history. Copy the whole thing
 * to the clipboard as a plain-text evidence pack.
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
  const [recent, setRecent] = useState<ComplianceRecentDeal[]>([]);

  useEffect(() => {
    getComplianceRecentDeals(20)
      .then(setRecent)
      .catch(() => {
        // recent list is a nice-to-have; a failure here shouldn't
        // block the tab.
      });
  }, []);

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

  useEffect(() => {
    if (initialDealId) load(initialDealId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialDealId]);

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-border bg-surface-2/40 p-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            load(dealId);
          }}
          className="flex flex-wrap items-end gap-2"
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
              list="recent-deal-ids"
            />
            {/* Native datalist gives typeahead + arrow-key select for free. */}
            <datalist id="recent-deal-ids">
              {recent.map((d) => (
                <option
                  key={d.deal_id}
                  value={d.deal_id}
                  label={`${d.counterparty_name} · ${d.currency} ${(
                    d.principal_pence / 100
                  ).toLocaleString()} · ${d.status}`}
                />
              ))}
            </datalist>
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

        {recent.length > 0 ? (
          <div className="mt-2 border-t border-border/60 pt-2">
            <div className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">
              Recent deals
            </div>
            <div className="flex flex-wrap gap-1">
              {recent.slice(0, 8).map((d) => (
                <button
                  key={d.deal_id}
                  type="button"
                  onClick={() => {
                    setDealId(d.deal_id);
                    load(d.deal_id);
                  }}
                  className="rounded border border-border bg-background px-2 py-0.5 text-[10.5px] hover:border-primary/40"
                  title={`${d.deal_id} · ${d.status}`}
                >
                  {d.counterparty_name}{" "}
                  <span className="text-muted-foreground">
                    ({d.currency} {(d.principal_pence / 100).toLocaleString()})
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      {error ? (
        <div className="rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      ) : null}

      {!data && !error && !loading ? (
        <div className="rounded border border-dashed border-border bg-surface-2/40 p-4 text-xs text-muted-foreground">
          Enter a deal id or pick one above to open its evidence file —
          six checks (with values vs limits), the policy version in force
          at booking, and the complete audit history.
        </div>
      ) : null}

      {data ? <EvidenceView data={data} /> : null}
    </div>
  );
}

function EvidenceView({ data }: { data: ComplianceDealEvidence }) {
  const passed = data.six_checks.filter((c) => c.passed).length;
  const failed = data.six_checks.length - passed;
  const [copied, setCopied] = useState(false);

  const copyPack = async () => {
    const text = renderEvidencePack(data);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      // Fall back to a hidden textarea if the modern API is blocked.
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        setCopied(true);
        setTimeout(() => setCopied(false), 2500);
      } finally {
        ta.remove();
      }
    }
  };

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
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={copyPack}
              title="Copy a plain-text evidence pack (all sections, one paste)"
            >
              {copied ? (
                <>
                  <ClipboardCheck className="mr-1 h-3 w-3 text-emerald-500" /> Copied
                </>
              ) : (
                <>
                  <Clipboard className="mr-1 h-3 w-3" /> Copy evidence pack
                </>
              )}
            </Button>
            <StatusBadge status={data.status} />
          </div>
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
          <ul className="space-y-1.5">
            {data.six_checks.map((c, i) => (
              <CheckLine key={i} check={c} currency={data.currency} />
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

function CheckLine({
  check,
  currency,
}: {
  check: ComplianceCheckLine;
  currency: string;
}) {
  const bar = extractBar(check, currency);
  return (
    <li
      className={
        "rounded border px-2 py-1.5 text-[11px] " +
        (check.passed
          ? "border-emerald-500/40 bg-emerald-500/5"
          : "border-destructive/40 bg-destructive/5")
      }
    >
      <div className="flex items-start gap-2">
        {check.passed ? (
          <CheckCircle2 className="h-3.5 w-3.5 mt-0.5 text-emerald-500 shrink-0" />
        ) : (
          <XCircle className="h-3.5 w-3.5 mt-0.5 text-destructive shrink-0" />
        )}
        <div className="flex-1">
          <div className="font-medium">{check.key}</div>
          {check.detail ? (
            <div className="text-[10.5px] text-muted-foreground">
              {check.detail}
            </div>
          ) : null}
          {bar ? <ValueLimitBar bar={bar} passed={check.passed} /> : null}
          {check.value && Object.keys(check.value).length > 0 && !bar ? (
            <dl className="mt-0.5 grid grid-cols-2 gap-x-3 text-[10px] text-muted-foreground sm:grid-cols-3">
              {Object.entries(check.value).map(([k, v]) => (
                <div key={k} className="flex gap-1.5">
                  <dt>{k}:</dt>
                  <dd className="font-mono">{formatValue(v)}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </div>
      </div>
    </li>
  );
}

type Bar = { value: number; limit: number; unit: string; label: string };

/** Pluck a value/limit pair out of the check_run payload if it names one. */
function extractBar(c: ComplianceCheckLine, currency: string): Bar | null {
  if (!c.value) return null;
  const v = c.value as Record<string, unknown>;

  // Common shapes the engine emits: {value, limit}, {measured, cap},
  // {actual, ceiling} — plus pence variants.
  const pairs: [string, string, string, string][] = [
    ["value_pence", "limit_pence", currency, "amount"],
    ["measured_pence", "cap_pence", currency, "amount"],
    ["actual_pence", "ceiling_pence", currency, "amount"],
    ["value", "limit", "", "value"],
    ["actual_pct", "cap_pct", "%", "percentage"],
    ["measured_pct", "limit_pct", "%", "percentage"],
  ];
  for (const [vk, lk, unit, label] of pairs) {
    if (typeof v[vk] === "number" && typeof v[lk] === "number") {
      const value = Number(v[vk]);
      const limit = Number(v[lk]);
      if (limit > 0)
        return {
          value: unit === currency ? value / 100 : value,
          limit: unit === currency ? limit / 100 : limit,
          unit,
          label,
        };
    }
  }
  return null;
}

function ValueLimitBar({ bar, passed }: { bar: Bar; passed: boolean }) {
  const pct = Math.min(150, Math.round((bar.value / bar.limit) * 100));
  const width = Math.min(100, pct);
  const cls = passed
    ? "bg-emerald-500/70"
    : pct >= 100
      ? "bg-destructive"
      : "bg-amber-500/80";
  const fmt = (n: number) =>
    bar.unit === "%"
      ? `${n.toFixed(1)}%`
      : bar.unit
        ? `${bar.unit} ${n.toLocaleString()}`
        : n.toLocaleString();
  return (
    <div className="mt-1">
      <div className="flex items-baseline justify-between text-[10px] text-muted-foreground">
        <span>
          Value <b className="text-foreground">{fmt(bar.value)}</b> · Limit{" "}
          <b className="text-foreground">{fmt(bar.limit)}</b>
        </span>
        <span className={pct >= 100 ? "text-destructive" : ""}>{pct}% of limit</span>
      </div>
      <div className="mt-0.5 h-1.5 w-full rounded bg-border/60">
        <div className={`h-1.5 rounded ${cls}`} style={{ width: `${width}%` }} />
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

function renderEvidencePack(d: ComplianceDealEvidence): string {
  const lines: string[] = [];
  const p = (s: string) => lines.push(s);
  p("Treasury Register — deal evidence pack");
  p(`Generated: ${new Date().toISOString()}`);
  p("");
  p("== Deal ==");
  p(`Id: ${d.deal_id}`);
  p(`Counterparty: ${d.counterparty_name} (${d.counterparty_rating ?? "—"})`);
  p(`Instrument: ${d.instrument}`);
  p(
    `Principal: ${d.currency} ${(d.principal_pence / 100).toLocaleString()}  · Rate: ${(d.rate_bp / 100).toFixed(2)}%  · Tenor: ${d.tenor_months}m`,
  );
  p(
    `Trade: ${d.trade_date}  Value: ${d.value_date}  Maturity: ${d.maturity_date ?? "—"}`,
  );
  p(`Entity: ${d.legal_entity_id ?? "—"}  · Status: ${d.status}`);
  p("");
  p("== Authority ==");
  p(`Proposed by: ${d.proposer_display ?? "—"}`);
  p(`Approved by: ${d.approver_display ?? "—"} (required: ${d.required_approver ?? "—"})`);
  if (d.override_reason) p(`Override reason: ${d.override_reason}`);
  p("");
  p("== Policy & limit at booking ==");
  p(`Policy version: ${d.policy_version_id ?? "—"} (effective ${d.policy_version_effective_from ?? "—"})`);
  p(`Limit id: ${d.limit_id ?? "—"}`);
  p(
    `Limit amount: ${d.limit_amount_pence !== null ? `${d.currency} ${(d.limit_amount_pence / 100).toLocaleString()}` : "—"}`,
  );
  p(`Note: ${d.policy_version_note}`);
  p("");
  p(
    `== Six checks (booking outcome ${d.booking_outcome ?? "n/a"}, check_run ${d.check_run_id ?? "—"}) ==`,
  );
  d.six_checks.forEach((c) => {
    p(`- [${c.passed ? "PASS" : "FAIL"}] ${c.key}: ${c.detail ?? ""}`);
    if (c.value) {
      for (const [k, v] of Object.entries(c.value)) {
        p(`      ${k}: ${formatValue(v)}`);
      }
    }
  });
  p("");
  p("== Event history ==");
  d.events.forEach((e) => {
    p(
      `- ${e.occurred_at}  ${e.action_label || e.action}  by ${e.actor_display ?? "—"}  · ${e.outcome ?? "—"}`,
    );
  });
  return lines.join("\n");
}
