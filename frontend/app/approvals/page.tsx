"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2, PenLine } from "lucide-react";

import { PageShell } from "@/components/PageShell";
import { Button } from "@/components/ui/button";
import {
  approveDeal,
  getApprovalQueue,
  whoAmI,
  type ApprovalQueueItem,
  type ApprovalQueueView,
} from "@/lib/api";
import { can, currentUser } from "@/lib/session";

/**
 * Approvals page — the signer's queue.
 *
 * Deals proposed but not yet approved. Signers see everything and act
 * on rows their role qualifies them to sign (and that they didn't
 * propose themselves). Segregation-of-duties is enforced by the
 * approve endpoint too — this page is just the surface.
 */
export default function ApprovalsPage() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [view, setView] = useState<ApprovalQueueView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setView(await getApprovalQueue());
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const me = currentUser() ?? (await whoAmI());
        if (!me) {
          router.replace("/");
          return;
        }
        if (!can("deal.approve", "admin.users")) {
          router.replace("/");
          return;
        }
        await load();
      } finally {
        setChecking(false);
      }
    })();
  }, [router, load]);

  const doApprove = async (item: ApprovalQueueItem) => {
    if (!item.required_approver) return;
    setBusy(item.deal_id);
    setError(null);
    try {
      await approveDeal(item.deal_id, item.required_approver);
      await load();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  if (checking) {
    return (
      <PageShell title="Approvals" icon={PenLine}>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> Checking access…
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell
      title="Approvals"
      description="Deals proposed and awaiting a signer. You can only sign rows your role qualifies you for and that you did not propose."
      icon={PenLine}
    >
      {error ? (
        <div className="mb-4 rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      ) : null}

      <div className="mb-3 flex items-baseline justify-between">
        <div className="text-[11px] text-muted-foreground">
          Signing as{" "}
          <b>{currentUser()?.display_name ?? "…"}</b> — roles{" "}
          <b>{view?.role_names_i_hold.join(", ") || "none"}</b>
        </div>
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs"
          onClick={load}
          disabled={loading}
        >
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
          Refresh
        </Button>
      </div>

      {view === null || loading && view.items.length === 0 ? (
        <div className="rounded border border-border bg-card p-3 text-xs text-muted-foreground">
          Loading…
        </div>
      ) : view.items.length === 0 ? (
        <div className="rounded border border-dashed border-border bg-surface-2/40 p-3 text-xs text-muted-foreground">
          Nothing awaiting a signer today.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-border bg-surface-2/60 text-[10px] uppercase font-semibold text-muted-foreground">
                <th className="py-2 px-3">Counterparty</th>
                <th className="py-2 px-3">Instrument</th>
                <th className="py-2 px-3 text-right">Principal</th>
                <th className="py-2 px-3 text-right">Tenor</th>
                <th className="py-2 px-3 text-right">Rate</th>
                <th className="py-2 px-3">Proposed by</th>
                <th className="py-2 px-3">Needs</th>
                <th className="py-2 px-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {view.items.map((r) => (
                <tr key={r.deal_id} className="hover:bg-muted/30">
                  <td className="py-2 px-3">
                    <div className="font-medium">{r.counterparty_name}</div>
                    <div className="text-[10px] text-muted-foreground">
                      {r.counterparty_rating}
                      {r.legal_entity_id ? ` · ${r.legal_entity_id}` : ""}
                    </div>
                  </td>
                  <td className="py-2 px-3">
                    <span className="rounded border border-border bg-surface-2/60 px-1.5 py-0.5 text-[10px] font-mono">
                      {r.instrument.replace(/_/g, " ").toLowerCase()}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-right num font-semibold">
                    {formatMoney(r.principal_pence, r.currency)}
                  </td>
                  <td className="py-2 px-3 text-right num text-muted-foreground">
                    {r.tenor_months}m
                  </td>
                  <td className="py-2 px-3 text-right num">
                    {(r.rate_bp / 100).toFixed(2)}%
                  </td>
                  <td className="py-2 px-3 text-[11px]">{r.proposed_by}</td>
                  <td className="py-2 px-3">
                    <span
                      className={`rounded-full border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                        r.can_approve
                          ? "border-primary/40 bg-primary/[.08] text-primary"
                          : "border-border bg-surface-2/60 text-muted-foreground"
                      }`}
                    >
                      {r.required_approver ?? "—"}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-right">
                    {r.can_approve ? (
                      <Button
                        size="sm"
                        className="h-6 gap-1 px-2 text-[10.5px]"
                        onClick={() => doApprove(r)}
                        disabled={busy === r.deal_id}
                      >
                        {busy === r.deal_id ? (
                          <Loader2 className="h-2.5 w-2.5 animate-spin" />
                        ) : (
                          <CheckCircle2 className="h-2.5 w-2.5" />
                        )}
                        Approve
                      </Button>
                    ) : (
                      <span className="text-[10px] italic text-muted-foreground">
                        Not eligible
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}

// ---------------------------------------------------------------- helpers

const CCY: Record<string, string> = { GBP: "£", EUR: "€", USD: "$", CHF: "CHF " };
function formatMoney(minor: number, currency: string): string {
  const symbol = CCY[currency] ?? "";
  const major = minor / 100;
  if (Math.abs(major) >= 1_000_000) return `${symbol}${(major / 1_000_000).toFixed(1)}m`;
  if (Math.abs(major) >= 1_000) return `${symbol}${(major / 1_000).toFixed(0)}k`;
  return `${symbol}${major.toFixed(0)}`;
}
