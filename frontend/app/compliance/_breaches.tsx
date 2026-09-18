"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Download,
  Loader2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  complianceBreachesCsvUrl,
  getComplianceBreaches,
  type ComplianceBreachRegister,
  type ComplianceBreachRow,
} from "@/lib/api";

/**
 * Breaches & overrides register.
 *
 * Two feeds combined: exception_item (six-check failures) plus
 * audit_event with outcome=OVERRIDDEN. Filters cover status,
 * counterparty and a date range; rows expand for the full detail;
 * the whole slice exports to CSV with the same filters.
 */
export function BreachesTab({
  onOpenDeal,
}: {
  onOpenDeal: (dealId: string) => void;
}) {
  const [data, setData] = useState<ComplianceBreachRegister | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [status, setStatus] = useState("");
  const [counterparty, setCounterparty] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const filterParams = useMemo(
    () => ({
      status: status || undefined,
      counterparty: counterparty.trim() || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    }),
    [status, counterparty, dateFrom, dateTo],
  );

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getComplianceBreaches({ ...filterParams, limit: 500 })
      .then(setData)
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setLoading(false));
  }, [filterParams]);

  useEffect(() => {
    load();
  }, [load]);

  const csvHref = useMemo(
    () =>
      complianceBreachesCsvUrl(
        filterParams as Record<string, string | undefined>,
      ),
    [filterParams],
  );

  const clearFilters = () => {
    setStatus("");
    setCounterparty("");
    setDateFrom("");
    setDateTo("");
  };

  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" /> Loading register…
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

  const hasFilters =
    !!status || !!counterparty || !!dateFrom || !!dateTo;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2">
        <SummaryTile label="Open" value={data.total_open} tone="bad" />
        <SummaryTile
          label="Overridden"
          value={data.total_overridden_ytd}
          tone="warn"
        />
        <SummaryTile
          label="Resolved"
          value={data.total_resolved_ytd}
          tone="ok"
        />
      </div>

      <div className="rounded-lg border border-border bg-surface-2/40 p-3">
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-semibold uppercase text-muted-foreground mr-1">
            Status
          </span>
          {(
            [
              ["", "All"],
              ["OPEN", "Open"],
              ["OVERRIDDEN", "Overridden"],
              ["RESOLVED", "Resolved"],
              ["REJECTED", "Rejected"],
            ] as [string, string][]
          ).map(([key, label]) => (
            <button
              key={key || "all"}
              type="button"
              onClick={() => setStatus(key)}
              className={
                "rounded border px-2 py-0.5 text-[10.5px] transition-colors " +
                (status === key
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border bg-background text-muted-foreground hover:border-primary/40")
              }
            >
              {label}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div>
            <label className="text-[10px] font-semibold uppercase text-muted-foreground">
              Counterparty
            </label>
            <input
              type="text"
              value={counterparty}
              placeholder="name or id"
              onChange={(e) => setCounterparty(e.target.value)}
              className="mt-0.5 w-full rounded border border-border bg-background px-2 py-1 text-xs"
            />
          </div>
          <div>
            <label className="text-[10px] font-semibold uppercase text-muted-foreground">
              From
            </label>
            <input
              type="datetime-local"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="mt-0.5 w-full rounded border border-border bg-background px-2 py-1 text-xs"
            />
          </div>
          <div>
            <label className="text-[10px] font-semibold uppercase text-muted-foreground">
              To
            </label>
            <input
              type="datetime-local"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="mt-0.5 w-full rounded border border-border bg-background px-2 py-1 text-xs"
            />
          </div>
          <div className="flex items-end justify-end gap-1.5">
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={clearFilters}
              disabled={!hasFilters}
            >
              Reset
            </Button>
            <a
              href={csvHref}
              target="_blank"
              rel="noopener"
              className="inline-flex h-7 items-center gap-1 rounded border border-border bg-background px-2 text-[10.5px] font-medium hover:border-primary/40"
              title="Download CSV of the filtered register"
            >
              <Download className="h-3 w-3" /> CSV
            </a>
          </div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="border-b border-border bg-surface-2/60 text-[10px] uppercase font-semibold text-muted-foreground">
              <th className="py-2 px-2 w-6"></th>
              <th className="py-2 px-3">Kind</th>
              <th className="py-2 px-3">When</th>
              <th className="py-2 px-3">Deal / counterparty</th>
              <th className="py-2 px-3">Rule</th>
              <th className="py-2 px-3">Status</th>
              <th className="py-2 px-3">Authoriser</th>
              <th className="py-2 px-3 text-right"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/40">
            {data.items.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-3 px-3 text-center text-muted-foreground">
                  No entries match those filters.
                  {hasFilters ? (
                    <button
                      className="ml-2 text-primary underline"
                      onClick={clearFilters}
                    >
                      Clear filters
                    </button>
                  ) : null}
                </td>
              </tr>
            ) : (
              data.items.map((r, i) => (
                <BreachRow key={i} row={r} onOpenDeal={onOpenDeal} />
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="text-[10px] italic text-muted-foreground">
        Generated {new Date(data.generated_at).toLocaleString()} ·{" "}
        {Intl.DateTimeFormat().resolvedOptions().timeZone} ·{" "}
        {data.items.length} row{data.items.length === 1 ? "" : "s"} shown
      </div>
    </div>
  );
}

function BreachRow({
  row,
  onOpenDeal,
}: {
  row: ComplianceBreachRow;
  onOpenDeal: (dealId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const kindCls =
    row.kind === "override"
      ? "border-amber-500/40 bg-amber-500/10 text-amber-600"
      : "border-destructive/40 bg-destructive/10 text-destructive";
  const statusCls =
    row.status === "OPEN"
      ? "text-destructive"
      : row.status === "OVERRIDDEN"
        ? "text-amber-500"
        : row.status === "RESOLVED"
          ? "text-emerald-500"
          : "text-muted-foreground";
  const hasDetail =
    !!row.reason || !!row.resolution_reason || !!row.resolved_at;
  return (
    <>
      <tr
        className="align-top hover:bg-muted/30 cursor-pointer"
        onClick={() => hasDetail && setOpen((v) => !v)}
      >
        <td className="py-1.5 px-2 text-muted-foreground">
          {hasDetail ? (
            open ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )
          ) : null}
        </td>
        <td className="py-1.5 px-3">
          <span
            className={`rounded border px-1.5 py-0.5 text-[9.5px] font-medium ${kindCls}`}
          >
            {row.kind}
          </span>
        </td>
        <td className="py-1.5 px-3 num text-[10.5px] text-muted-foreground whitespace-nowrap">
          {new Date(row.occurred_at).toLocaleString()}
        </td>
        <td className="py-1.5 px-3 text-[10.5px]">
          {row.counterparty_name ? <div>{row.counterparty_name}</div> : null}
          {row.deal_id ? (
            <div className="font-mono text-[9.5px] text-muted-foreground">
              {row.deal_id}
            </div>
          ) : null}
        </td>
        <td className="py-1.5 px-3 text-[10.5px] font-mono">{row.rule}</td>
        <td className={`py-1.5 px-3 text-[10.5px] font-medium ${statusCls}`}>
          {row.status}
        </td>
        <td className="py-1.5 px-3 text-[10.5px]">
          {row.authoriser_display ?? "—"}
        </td>
        <td className="py-1.5 px-3 text-right">
          {row.deal_id ? (
            <Button
              size="sm"
              variant="outline"
              className="h-6 text-[10px]"
              onClick={(e) => {
                e.stopPropagation();
                onOpenDeal(row.deal_id!);
              }}
            >
              Evidence
            </Button>
          ) : null}
        </td>
      </tr>
      {open && hasDetail ? (
        <tr className="bg-surface-2/40">
          <td></td>
          <td colSpan={7} className="py-2 px-3">
            <BreachDetail row={row} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function BreachDetail({ row }: { row: ComplianceBreachRow }) {
  const failedChecks = row.rule.includes(",")
    ? row.rule.split(",").map((s) => s.trim())
    : [row.rule];
  return (
    <div className="space-y-2 text-[10.5px]">
      {row.kind === "override" && failedChecks.length > 0 ? (
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">
            Failed checks at booking
          </div>
          <ul className="ml-4 list-disc">
            {failedChecks.map((c) => (
              <li key={c} className="font-mono">
                {c}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {row.reason ? (
        <MetaLine
          label={row.kind === "override" ? "Override reason" : "Detail"}
          value={row.reason}
        />
      ) : null}
      {row.resolved_at ? (
        <MetaLine
          label="Resolved at"
          value={new Date(row.resolved_at).toLocaleString()}
        />
      ) : null}
      {row.resolution ? (
        <MetaLine label="Resolution" value={row.resolution} />
      ) : null}
      {row.resolution_reason ? (
        <MetaLine label="Resolution reason" value={row.resolution_reason} />
      ) : null}
    </div>
  );
}

function MetaLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2 border-b border-border/30 py-0.5">
      <dt className="text-[10px] font-medium text-muted-foreground min-w-[9rem]">
        {label}
      </dt>
      <dd className="text-[10.5px] break-words">{value}</dd>
    </div>
  );
}

function SummaryTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "ok" | "bad" | "warn";
}) {
  const toneCls =
    tone === "ok"
      ? "text-emerald-500"
      : tone === "bad"
        ? "text-destructive"
        : "text-amber-500";
  return (
    <div className="rounded-lg border border-border bg-surface-2/40 p-2.5">
      <div className="text-[10px] font-semibold uppercase text-muted-foreground">
        {label}
      </div>
      <div className={`num text-xl font-semibold ${toneCls}`}>
        {value.toLocaleString()}
      </div>
    </div>
  );
}
