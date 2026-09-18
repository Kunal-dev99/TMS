"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Download, Loader2, ShieldCheck } from "lucide-react";

import { PageShell } from "@/components/PageShell";
import { Button } from "@/components/ui/button";
import {
  complianceActivityCsvUrl,
  listComplianceActivity,
  whoAmI,
  type ComplianceActivityRow,
  type ComplianceActivityView,
} from "@/lib/api";
import { can, currentUser } from "@/lib/session";

/**
 * Compliance page — read-only view of the audit trail.
 *
 * Filter bar (action / subject-type / date range) + table + CSV
 * export. The feed is populated by audit_service across the entire
 * app: sign-ins, admin actions, access-change approvals, hedge
 * initiations, deal state changes.
 *
 * Gated by VIEW_AUDIT (COMPLIANCE_OFFICER, CFO, AUDITOR) or
 * MANAGE_USERS (ADMIN). Server enforces the same via require_permission.
 */
export default function CompliancePage() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [view, setView] = useState<ComplianceActivityView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [action, setAction] = useState("");
  const [subjectType, setSubjectType] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [limit, setLimit] = useState(200);

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const v = await listComplianceActivity({
        action: action || undefined,
        subject_type: subjectType || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        limit,
      });
      setView(v);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }, [action, subjectType, dateFrom, dateTo, limit]);

  useEffect(() => {
    (async () => {
      try {
        const me = currentUser() ?? (await whoAmI());
        if (!me) {
          router.replace("/");
          return;
        }
        if (!can("view.audit", "admin.users")) {
          router.replace("/");
          return;
        }
        await fetch();
      } finally {
        setChecking(false);
      }
    })();
  }, [router, fetch]);

  const csvHref = useMemo(
    () =>
      complianceActivityCsvUrl({
        action: action || undefined,
        subject_type: subjectType || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      }),
    [action, subjectType, dateFrom, dateTo],
  );

  if (checking) {
    return (
      <PageShell title="Compliance" icon={ShieldCheck}>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> Checking access…
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell
      title="Compliance"
      description="Read-only view of the audit trail. Every mutation elsewhere in the app — sign-ins, admin actions, access-change reviews, hedge initiations — lands here."
      icon={ShieldCheck}
    >
      {error ? (
        <div className="mb-4 rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      ) : null}

      <FilterBar
        action={action}
        setAction={setAction}
        subjectType={subjectType}
        setSubjectType={setSubjectType}
        dateFrom={dateFrom}
        setDateFrom={setDateFrom}
        dateTo={dateTo}
        setDateTo={setDateTo}
        limit={limit}
        setLimit={setLimit}
        onApply={fetch}
        onReset={() => {
          setAction("");
          setSubjectType("");
          setDateFrom("");
          setDateTo("");
          setLimit(200);
          setTimeout(fetch, 0);
        }}
        actionsSeen={view?.actions_seen ?? []}
        subjectTypesSeen={view?.subject_types_seen ?? []}
        loading={loading}
        csvHref={csvHref}
      />

      <ActivityTable rows={view?.items ?? []} loading={loading} />
    </PageShell>
  );
}

// ------------------------------------------------------ filter bar

function FilterBar({
  action,
  setAction,
  subjectType,
  setSubjectType,
  dateFrom,
  setDateFrom,
  dateTo,
  setDateTo,
  limit,
  setLimit,
  onApply,
  onReset,
  actionsSeen,
  subjectTypesSeen,
  loading,
  csvHref,
}: {
  action: string;
  setAction: (v: string) => void;
  subjectType: string;
  setSubjectType: (v: string) => void;
  dateFrom: string;
  setDateFrom: (v: string) => void;
  dateTo: string;
  setDateTo: (v: string) => void;
  limit: number;
  setLimit: (v: number) => void;
  onApply: () => void;
  onReset: () => void;
  actionsSeen: string[];
  subjectTypesSeen: string[];
  loading: boolean;
  csvHref: string;
}) {
  return (
    <div className="mb-4 grid grid-cols-2 gap-2 rounded-lg border border-border bg-surface-2/40 p-3 sm:grid-cols-6">
      <div>
        <label className="text-[10px] font-semibold uppercase text-muted-foreground">
          Action
        </label>
        <select
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className="mt-0.5 w-full rounded border border-border bg-background px-2 py-1 text-xs"
        >
          <option value="">any</option>
          {actionsSeen.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="text-[10px] font-semibold uppercase text-muted-foreground">
          Subject type
        </label>
        <select
          value={subjectType}
          onChange={(e) => setSubjectType(e.target.value)}
          className="mt-0.5 w-full rounded border border-border bg-background px-2 py-1 text-xs"
        >
          <option value="">any</option>
          {subjectTypesSeen.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
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
      <div>
        <label className="text-[10px] font-semibold uppercase text-muted-foreground">
          Limit
        </label>
        <input
          type="number"
          min={10}
          max={2000}
          step={50}
          value={limit}
          onChange={(e) => setLimit(Math.min(2000, Math.max(10, Number(e.target.value) || 200)))}
          className="mt-0.5 w-full rounded border border-border bg-background px-2 py-1 text-xs num"
        />
      </div>
      <div className="flex items-end justify-end gap-1.5">
        <Button variant="outline" size="sm" className="h-7 text-xs" onClick={onReset}>
          Reset
        </Button>
        <Button size="sm" className="h-7 text-xs" onClick={onApply} disabled={loading}>
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
          Apply
        </Button>
        <a
          href={csvHref}
          target="_blank"
          rel="noopener"
          className="inline-flex h-7 items-center gap-1 rounded border border-border bg-background px-2 text-[10.5px] font-medium hover:border-primary/40"
        >
          <Download className="h-3 w-3" /> CSV
        </a>
      </div>
    </div>
  );
}

// ------------------------------------------------------ table

function ActivityTable({
  rows,
  loading,
}: {
  rows: ComplianceActivityRow[];
  loading: boolean;
}) {
  if (loading && rows.length === 0) {
    return (
      <div className="rounded border border-border bg-card p-3 text-xs text-muted-foreground">
        Loading…
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div className="rounded border border-dashed border-border bg-surface-2/40 p-3 text-xs text-muted-foreground">
        No events match those filters.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-xs border-collapse">
        <thead>
          <tr className="border-b border-border bg-surface-2/60 text-[10px] uppercase font-semibold text-muted-foreground">
            <th className="py-2 px-3">When</th>
            <th className="py-2 px-3">Actor</th>
            <th className="py-2 px-3">Action</th>
            <th className="py-2 px-3">Subject</th>
            <th className="py-2 px-3">Outcome</th>
            <th className="py-2 px-3">Payload</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/40">
          {rows.map((r) => (
            <tr key={r.id} className="align-top hover:bg-muted/30">
              <td className="py-1.5 px-3 num text-[10.5px] text-muted-foreground whitespace-nowrap">
                {new Date(r.occurred_at).toLocaleString()}
              </td>
              <td className="py-1.5 px-3 text-[11px]">{r.actor_display ?? "—"}</td>
              <td className="py-1.5 px-3">
                <span className="rounded border border-border bg-surface-2/60 px-1.5 py-0.5 text-[10px] font-mono">
                  {r.action}
                </span>
              </td>
              <td className="py-1.5 px-3 text-[10.5px] text-muted-foreground">
                <div>{r.subject_type}</div>
                {r.subject_id ? (
                  <div className="font-mono text-[9.5px]">{r.subject_id}</div>
                ) : null}
              </td>
              <td className="py-1.5 px-3 text-[10.5px]">{r.outcome ?? "—"}</td>
              <td className="py-1.5 px-3">
                {r.payload ? (
                  <pre className="whitespace-pre-wrap break-all font-mono text-[10px] text-muted-foreground">
                    {JSON.stringify(r.payload, null, 2)}
                  </pre>
                ) : (
                  <span className="text-[10.5px] italic text-muted-foreground">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
