"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  getComplianceBreaches,
  type ComplianceBreachRegister,
  type ComplianceBreachRow,
} from "@/lib/api";

/**
 * Breaches & overrides register.
 *
 * Two feeds combined: exception_item (six-check failures) plus
 * audit_event with outcome=OVERRIDDEN (signers who forced a deal
 * through). Read-only; a signer clicks through to the operational
 * page to act.
 */
export function BreachesTab({
  onOpenDeal,
}: {
  onOpenDeal: (dealId: string) => void;
}) {
  const [data, setData] = useState<ComplianceBreachRegister | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");

  const load = (s: string = status) => {
    setLoading(true);
    setError(null);
    getComplianceBreaches({ status: s || undefined, limit: 500 })
      .then(setData)
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load(status);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

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

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2">
        <SummaryTile label="Open" value={data.total_open} tone="bad" />
        <SummaryTile label="Overridden" value={data.total_overridden_ytd} tone="warn" />
        <SummaryTile label="Resolved" value={data.total_resolved_ytd} tone="ok" />
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] font-semibold uppercase text-muted-foreground mr-1">
          Filter by status
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

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="border-b border-border bg-surface-2/60 text-[10px] uppercase font-semibold text-muted-foreground">
              <th className="py-2 px-3">Kind</th>
              <th className="py-2 px-3">When</th>
              <th className="py-2 px-3">Deal / counterparty</th>
              <th className="py-2 px-3">Rule</th>
              <th className="py-2 px-3">Reason</th>
              <th className="py-2 px-3">Status</th>
              <th className="py-2 px-3">Authoriser</th>
              <th className="py-2 px-3 text-right"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/40">
            {data.items.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-3 px-3 text-center text-muted-foreground">
                  No entries match that filter.
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
        {Intl.DateTimeFormat().resolvedOptions().timeZone}
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
  return (
    <tr className="align-top hover:bg-muted/30">
      <td className="py-1.5 px-3">
        <span className={`rounded border px-1.5 py-0.5 text-[9.5px] font-medium ${kindCls}`}>
          {row.kind}
        </span>
      </td>
      <td className="py-1.5 px-3 num text-[10.5px] text-muted-foreground whitespace-nowrap">
        {new Date(row.occurred_at).toLocaleString()}
      </td>
      <td className="py-1.5 px-3 text-[10.5px]">
        {row.counterparty_name ? (
          <div>{row.counterparty_name}</div>
        ) : null}
        {row.deal_id ? (
          <div className="font-mono text-[9.5px] text-muted-foreground">{row.deal_id}</div>
        ) : null}
      </td>
      <td className="py-1.5 px-3 text-[10.5px] font-mono">{row.rule}</td>
      <td className="py-1.5 px-3 text-[10.5px] text-muted-foreground max-w-[24rem]">
        {row.reason ?? "—"}
      </td>
      <td className={`py-1.5 px-3 text-[10.5px] font-medium ${statusCls}`}>
        {row.status}
      </td>
      <td className="py-1.5 px-3 text-[10.5px]">{row.authoriser_display ?? "—"}</td>
      <td className="py-1.5 px-3 text-right">
        {row.deal_id ? (
          <Button
            size="sm"
            variant="outline"
            className="h-6 text-[10px]"
            onClick={() => onOpenDeal(row.deal_id!)}
          >
            Evidence
          </Button>
        ) : null}
      </td>
    </tr>
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
