"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ChevronDown,
  ChevronRight,
  Download,
  Loader2,
  ShieldCheck,
} from "lucide-react";

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
 * Iteration 2 (2026-09-18):
 *   - Defaults to "All activity, last 7 days" instead of a
 *     one-minute slice that returns no results.
 *   - Date presets (Today / 7d / 30d / All / Custom).
 *   - Pagination with real total-matching count.
 *   - Expandable rows: payload + subject reference.
 *   - Empty state offers Clear filters + Expand range.
 *   - CSV disclosure line makes the export scope explicit.
 *
 * Gated by VIEW_AUDIT (COMPLIANCE_OFFICER, CFO, AUDITOR) or
 * MANAGE_USERS (ADMIN). Server enforces via require_permission.
 */

type Preset = "today" | "7d" | "30d" | "all" | "custom";

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  d.setHours(0, 0, 0, 0);
  // Datetime-local format expects no trailing Z.
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T00:00`;
}

function todayIso(): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T00:00`;
}

const PAGE_SIZE = 50;

export default function CompliancePage() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [view, setView] = useState<ComplianceActivityView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [action, setAction] = useState("");
  const [subjectType, setSubjectType] = useState("");
  const [preset, setPreset] = useState<Preset>("7d");
  const [dateFrom, setDateFrom] = useState(isoDaysAgo(7));
  const [dateTo, setDateTo] = useState("");
  const [offset, setOffset] = useState(0);

  const fetch = useCallback(
    async (nextOffset: number = offset) => {
      setLoading(true);
      setError(null);
      try {
        const v = await listComplianceActivity({
          action: action || undefined,
          subject_type: subjectType || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          limit: PAGE_SIZE,
          offset: nextOffset,
        });
        setView(v);
      } catch (e) {
        setError(String((e as Error).message ?? e));
      } finally {
        setLoading(false);
      }
    },
    [action, subjectType, dateFrom, dateTo, offset],
  );

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
        await fetch(0);
      } finally {
        setChecking(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  const applyPreset = (p: Preset) => {
    setPreset(p);
    if (p === "today") {
      setDateFrom(todayIso());
      setDateTo("");
    } else if (p === "7d") {
      setDateFrom(isoDaysAgo(7));
      setDateTo("");
    } else if (p === "30d") {
      setDateFrom(isoDaysAgo(30));
      setDateTo("");
    } else if (p === "all") {
      setDateFrom("");
      setDateTo("");
    }
    setOffset(0);
    setTimeout(() => fetch(0), 0);
  };

  const onApply = () => {
    setOffset(0);
    setTimeout(() => fetch(0), 0);
  };

  const onReset = () => {
    setAction("");
    setSubjectType("");
    setPreset("7d");
    setDateFrom(isoDaysAgo(7));
    setDateTo("");
    setOffset(0);
    setTimeout(() => fetch(0), 0);
  };

  const onExpandRange = () => {
    setPreset("30d");
    setDateFrom(isoDaysAgo(30));
    setDateTo("");
    setOffset(0);
    setTimeout(() => fetch(0), 0);
  };

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
      description="Read-only view of the audit trail. Every mutation elsewhere in the app — sign-ins, admin actions, access-change reviews, deals, hedges — lands here."
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
        preset={preset}
        setPreset={applyPreset}
        dateFrom={dateFrom}
        setDateFrom={(v) => {
          setDateFrom(v);
          setPreset("custom");
        }}
        dateTo={dateTo}
        setDateTo={(v) => {
          setDateTo(v);
          setPreset("custom");
        }}
        onApply={onApply}
        onReset={onReset}
        actionsSeen={view?.actions_seen ?? []}
        subjectTypesSeen={view?.subject_types_seen ?? []}
        loading={loading}
        csvHref={csvHref}
        totalMatching={view?.total_matching ?? 0}
      />

      <ResultsHeader
        view={view}
        loading={loading}
      />

      <ActivityTable
        rows={view?.items ?? []}
        loading={loading}
        totalMatching={view?.total_matching ?? 0}
        totalAll={view?.total_all ?? 0}
        onClearFilters={onReset}
        onExpandRange={onExpandRange}
        hasFilters={
          !!action || !!subjectType || !!dateFrom || !!dateTo
        }
      />

      {view && view.total_matching > PAGE_SIZE ? (
        <Pagination
          offset={offset}
          pageSize={PAGE_SIZE}
          total={view.total_matching}
          onGo={(next) => {
            setOffset(next);
            setTimeout(() => fetch(next), 0);
          }}
          loading={loading}
        />
      ) : null}
    </PageShell>
  );
}

// ------------------------------------------------------ filter bar

function FilterBar({
  action,
  setAction,
  subjectType,
  setSubjectType,
  preset,
  setPreset,
  dateFrom,
  setDateFrom,
  dateTo,
  setDateTo,
  onApply,
  onReset,
  actionsSeen,
  subjectTypesSeen,
  loading,
  csvHref,
  totalMatching,
}: {
  action: string;
  setAction: (v: string) => void;
  subjectType: string;
  setSubjectType: (v: string) => void;
  preset: Preset;
  setPreset: (p: Preset) => void;
  dateFrom: string;
  setDateFrom: (v: string) => void;
  dateTo: string;
  setDateTo: (v: string) => void;
  onApply: () => void;
  onReset: () => void;
  actionsSeen: string[];
  subjectTypesSeen: string[];
  loading: boolean;
  csvHref: string;
  totalMatching: number;
}) {
  return (
    <div className="mb-3 rounded-lg border border-border bg-surface-2/40 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] font-semibold uppercase text-muted-foreground mr-1">
          Range
        </span>
        {(
          [
            ["today", "Today"],
            ["7d", "Last 7 days"],
            ["30d", "Last 30 days"],
            ["all", "All time"],
            ["custom", "Custom"],
          ] as [Preset, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setPreset(key)}
            className={
              "rounded border px-2 py-0.5 text-[10.5px] transition-colors " +
              (preset === key
                ? "border-primary bg-primary/10 text-primary"
                : "border-border bg-background text-muted-foreground hover:border-primary/40")
            }
          >
            {label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <div>
          <label className="text-[10px] font-semibold uppercase text-muted-foreground">
            Action
          </label>
          <select
            value={action}
            onChange={(e) => setAction(e.target.value)}
            className="mt-0.5 w-full rounded border border-border bg-background px-2 py-1 text-xs"
          >
            <option value="">All activity</option>
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
            <option value="">Any</option>
            {subjectTypesSeen.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-[10px] font-semibold uppercase text-muted-foreground">
            From ({Intl.DateTimeFormat().resolvedOptions().timeZone})
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
            To ({Intl.DateTimeFormat().resolvedOptions().timeZone})
          </label>
          <input
            type="datetime-local"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="mt-0.5 w-full rounded border border-border bg-background px-2 py-1 text-xs"
          />
        </div>
        <div className="flex items-end justify-end gap-1.5">
          <Button variant="outline" size="sm" className="h-7 text-xs" onClick={onReset}>
            Reset
          </Button>
          <Button size="sm" className="h-7 text-xs" onClick={onApply} disabled={loading}>
            {loading ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
            Apply
          </Button>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-2">
        <p className="text-[10.5px] text-muted-foreground">
          CSV exports all rows matching the current filters (max 10,000) — not
          just this page. The file includes a header block naming the
          filters, the row count and the export timestamp.
        </p>
        <a
          href={csvHref}
          target="_blank"
          rel="noopener"
          className="inline-flex h-7 items-center gap-1 rounded border border-border bg-background px-2 text-[10.5px] font-medium hover:border-primary/40"
          title={`Download CSV of the ${totalMatching} matching rows`}
        >
          <Download className="h-3 w-3" /> Export CSV
        </a>
      </div>
    </div>
  );
}

// ------------------------------------------------------ results header

function ResultsHeader({
  view,
  loading,
}: {
  view: ComplianceActivityView | null;
  loading: boolean;
}) {
  if (!view) return null;
  const showingFrom = view.offset + 1;
  const showingTo = view.offset + view.items.length;
  return (
    <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[10.5px] text-muted-foreground">
      <div>
        {loading ? (
          <span className="inline-flex items-center gap-1">
            <Loader2 className="h-3 w-3 animate-spin" /> Loading…
          </span>
        ) : view.items.length === 0 ? (
          <span>0 events match these filters.</span>
        ) : (
          <span>
            Showing <span className="text-foreground">{showingFrom}–{showingTo}</span>{" "}
            of <span className="text-foreground">{view.total_matching}</span>{" "}
            matching (of {view.total_all} total).
          </span>
        )}
      </div>
      <div className="text-[10px]">
        Generated {new Date(view.generated_at).toLocaleString()}
      </div>
    </div>
  );
}

// ------------------------------------------------------ table

function ActivityTable({
  rows,
  loading,
  totalMatching,
  totalAll,
  onClearFilters,
  onExpandRange,
  hasFilters,
}: {
  rows: ComplianceActivityRow[];
  loading: boolean;
  totalMatching: number;
  totalAll: number;
  onClearFilters: () => void;
  onExpandRange: () => void;
  hasFilters: boolean;
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
      <div className="rounded border border-dashed border-border bg-surface-2/40 p-4 text-xs">
        <p className="mb-1 font-medium text-foreground">
          No events match those filters.
        </p>
        <p className="mb-3 text-muted-foreground">
          {hasFilters
            ? `An empty result is not evidence that no events occurred — the tenant holds ${totalAll} events overall.`
            : `The tenant holds ${totalAll} events overall; none fall in the current range.`}
        </p>
        <div className="flex flex-wrap gap-1.5">
          {hasFilters ? (
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onClearFilters}>
              Clear filters
            </Button>
          ) : null}
          <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onExpandRange}>
            Expand to last 30 days
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-xs border-collapse">
        <thead>
          <tr className="border-b border-border bg-surface-2/60 text-[10px] uppercase font-semibold text-muted-foreground">
            <th className="py-2 px-2 w-6"></th>
            <th className="py-2 px-3">When</th>
            <th className="py-2 px-3">Actor</th>
            <th className="py-2 px-3">What happened</th>
            <th className="py-2 px-3">Subject</th>
            <th className="py-2 px-3">Outcome</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/40">
          {rows.map((r) => (
            <EventRow key={r.id} row={r} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EventRow({ row }: { row: ComplianceActivityRow }) {
  const [open, setOpen] = useState(false);
  const hasDetail = !!row.payload && Object.keys(row.payload).length > 0;
  return (
    <>
      <tr
        className="align-top hover:bg-muted/30 cursor-pointer"
        onClick={() => setOpen((v) => !v)}
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
        <td className="py-1.5 px-3 num text-[10.5px] text-muted-foreground whitespace-nowrap">
          {new Date(row.occurred_at).toLocaleString()}
        </td>
        <td className="py-1.5 px-3 text-[11px]">{row.actor_display ?? "—"}</td>
        <td className="py-1.5 px-3">
          <div className="text-[11px] font-medium">{row.action_label}</div>
          <div className="font-mono text-[9.5px] text-muted-foreground">
            {row.action}
          </div>
        </td>
        <td className="py-1.5 px-3 text-[10.5px] text-muted-foreground">
          <div>{row.subject_type}</div>
          {row.subject_id ? (
            <div className="font-mono text-[9.5px]">{row.subject_id}</div>
          ) : null}
        </td>
        <td className="py-1.5 px-3 text-[10.5px]">{row.outcome ?? "—"}</td>
      </tr>
      {open && hasDetail ? (
        <tr className="bg-surface-2/40">
          <td></td>
          <td colSpan={5} className="py-2 px-3">
            <PayloadDetail row={row} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function PayloadDetail({ row }: { row: ComplianceActivityRow }) {
  const p = row.payload ?? {};
  // Some payloads carry semantic before/after; render them as a
  // two-column diff when present, otherwise a plain key-value list.
  const before = (p as { before?: Record<string, unknown> }).before;
  const after = (p as { after?: Record<string, unknown> }).after;
  const restEntries = Object.entries(p).filter(
    ([k]) => k !== "before" && k !== "after",
  );

  return (
    <div className="space-y-2">
      {before || after ? (
        <div className="grid grid-cols-2 gap-2">
          <DiffCol title="Before" data={before ?? {}} />
          <DiffCol title="After" data={after ?? {}} />
        </div>
      ) : null}

      {restEntries.length > 0 ? (
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">
            Details
          </div>
          <dl className="grid grid-cols-1 gap-x-3 gap-y-0.5 sm:grid-cols-2">
            {restEntries.map(([k, v]) => (
              <div key={k} className="flex gap-2 border-b border-border/30 py-1">
                <dt className="text-[10px] font-medium text-muted-foreground min-w-[9rem]">
                  {k}
                </dt>
                <dd className="text-[10.5px] font-mono break-all">
                  {formatValue(v)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}

      {row.subject_id && row.subject_type === "deal" ? (
        <div className="text-[10.5px]">
          <span className="text-muted-foreground">Subject: </span>
          <a
            className="text-primary underline underline-offset-2"
            href={`/?deal=${encodeURIComponent(row.subject_id)}`}
          >
            Open deal {row.subject_id}
          </a>
        </div>
      ) : row.subject_id && row.subject_type === "user" ? (
        <div className="text-[10.5px]">
          <span className="text-muted-foreground">Subject: </span>
          <a
            className="text-primary underline underline-offset-2"
            href={`/admin?user=${encodeURIComponent(row.subject_id)}`}
          >
            Open user {row.subject_id}
          </a>
        </div>
      ) : null}
    </div>
  );
}

function DiffCol({
  title,
  data,
}: {
  title: string;
  data: Record<string, unknown>;
}) {
  const entries = Object.entries(data);
  return (
    <div className="rounded border border-border/60 bg-background p-2">
      <div className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">
        {title}
      </div>
      {entries.length === 0 ? (
        <div className="text-[10.5px] italic text-muted-foreground">—</div>
      ) : (
        <dl className="space-y-0.5">
          {entries.map(([k, v]) => (
            <div key={k} className="flex gap-2 text-[10.5px]">
              <dt className="min-w-[7rem] text-muted-foreground">{k}</dt>
              <dd className="font-mono break-all">{formatValue(v)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

// ------------------------------------------------------ pagination

function Pagination({
  offset,
  pageSize,
  total,
  onGo,
  loading,
}: {
  offset: number;
  pageSize: number;
  total: number;
  onGo: (next: number) => void;
  loading: boolean;
}) {
  const page = Math.floor(offset / pageSize) + 1;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const prev = Math.max(0, offset - pageSize);
  const next = Math.min((pages - 1) * pageSize, offset + pageSize);
  const atStart = offset === 0;
  const atEnd = offset + pageSize >= total;
  return (
    <div className="mt-3 flex items-center justify-between text-[10.5px]">
      <div className="text-muted-foreground">
        Page <span className="text-foreground">{page}</span> of{" "}
        <span className="text-foreground">{pages}</span>
      </div>
      <div className="flex gap-1.5">
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs"
          disabled={atStart || loading}
          onClick={() => onGo(0)}
        >
          First
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs"
          disabled={atStart || loading}
          onClick={() => onGo(prev)}
        >
          Prev
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs"
          disabled={atEnd || loading}
          onClick={() => onGo(next)}
        >
          Next
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs"
          disabled={atEnd || loading}
          onClick={() => onGo((pages - 1) * pageSize)}
        >
          Last
        </Button>
      </div>
    </div>
  );
}
