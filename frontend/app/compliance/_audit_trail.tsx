"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Download,
  Loader2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  complianceActivityCsvUrl,
  listComplianceActivity,
  type ComplianceActivityRow,
  type ComplianceActivityView,
} from "@/lib/api";

/**
 * Compliance page — read-only view of the audit trail.
 *
 * Iteration 3 (2026-09-18):
 *   - All numeric/date rendering guarded — never shows NaN or
 *     "Invalid Date" even if the backend response is missing
 *     the extended fields.
 *   - Actor + record (subject_id) search inputs.
 *   - Saved-view chips: All / Deals / Access changes / Policy /
 *     Sign-ins — each fills the filter set behind the scenes.
 *   - Outcome column reads "Succeeded / Failed / Denied / …"
 *     with the raw code kept in the expanded detail.
 *   - Today preset explicit "midnight to now".
 *   - CSV export shows a truncated-slice warning when the match
 *     count exceeds the 10,000 cap.
 *
 * Gated by VIEW_AUDIT (COMPLIANCE_OFFICER, CFO, AUDITOR) or
 * MANAGE_USERS (ADMIN). Server enforces via require_permission.
 */

type Preset = "today" | "7d" | "30d" | "all" | "custom";

type SavedView =
  | { key: "all"; label: string }
  | { key: "deals"; label: string; action_prefix: "deal." }
  | { key: "hedges"; label: string; action_prefix: "hedge." }
  | { key: "access"; label: string; action_prefix: "access_change." }
  | { key: "policy"; label: string; action_prefix: "policy." }
  | { key: "signins"; label: string; action: "user.signed_in" };

const SAVED_VIEWS: SavedView[] = [
  { key: "all", label: "All activity" },
  { key: "deals", label: "Deal decisions", action_prefix: "deal." },
  { key: "hedges", label: "Hedges", action_prefix: "hedge." },
  { key: "access", label: "Access changes", action_prefix: "access_change." },
  { key: "policy", label: "Policy changes", action_prefix: "policy." },
  { key: "signins", label: "Sign-ins", action: "user.signed_in" },
];

const CSV_CAP = 10000;
const PAGE_SIZE = 50;

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function toLocalIso(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  d.setHours(0, 0, 0, 0);
  return toLocalIso(d);
}

function todayIso(): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return toLocalIso(d);
}

function safeDate(v: string | undefined | null): string {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isFinite(d.getTime()) ? d.toLocaleString() : "—";
}

// Domain outcome codes → plain English. Anything else falls back
// to the raw value or "Not recorded". Never infer success.
const OUTCOME_LABEL: Record<string, string> = {
  PASS: "Succeeded",
  FAIL: "Failed",
  OVERRIDDEN: "Overridden",
  BLOCKED: "Blocked",
  APPROVED: "Approved",
  BOOKED: "Booked",
  PROPOSED: "Proposed",
  INSTRUCTED: "Instructed",
  SETTLED: "Settled",
  ACTIVE: "Active",
  REJECTED: "Rejected",
  DENIED: "Denied",
  NO_GAP: "No gap",
  NO_CANDIDATES: "No candidates",
};

function prettyOutcome(o: string | undefined | null): {
  label: string;
  tone: "ok" | "bad" | "warn" | "muted";
} {
  if (!o) return { label: "Not recorded", tone: "muted" };
  const label = OUTCOME_LABEL[o] ?? o;
  if (["Succeeded", "Approved", "Booked", "Settled", "Active", "No gap"].includes(label)) {
    return { label, tone: "ok" };
  }
  if (["Failed", "Blocked", "Rejected", "Denied"].includes(label)) {
    return { label, tone: "bad" };
  }
  if (["Overridden"].includes(label)) {
    return { label, tone: "warn" };
  }
  return { label, tone: "muted" };
}

export function AuditTrailTab() {
  const [view, setView] = useState<ComplianceActivityView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [savedView, setSavedView] = useState<SavedView["key"]>("all");
  const [action, setAction] = useState("");
  const [actionPrefix, setActionPrefix] = useState<string>("");
  const [subjectType, setSubjectType] = useState("");
  const [actor, setActor] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [preset, setPreset] = useState<Preset>("7d");
  const [dateFrom, setDateFrom] = useState(isoDaysAgo(7));
  const [dateTo, setDateTo] = useState("");
  const [offset, setOffset] = useState(0);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  const currentFilters = useMemo(
    () => ({
      action: action || undefined,
      action_prefix: actionPrefix || undefined,
      subject_type: subjectType || undefined,
      actor: actor.trim() || undefined,
      subject_id: subjectId.trim() || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    }),
    [action, actionPrefix, subjectType, actor, subjectId, dateFrom, dateTo],
  );

  const fetch = useCallback(
    async (nextOffset: number = offset) => {
      setLoading(true);
      setError(null);
      try {
        const v = await listComplianceActivity({
          ...currentFilters,
          limit: PAGE_SIZE,
          offset: nextOffset,
        });
        setView(v);
        setLastRefreshed(new Date());
      } catch (e) {
        setError(String((e as Error).message ?? e));
      } finally {
        setLoading(false);
      }
    },
    [currentFilters, offset],
  );

  useEffect(() => {
    fetch(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyPreset = (p: Preset) => {
    setPreset(p);
    if (p === "today") {
      setDateFrom(todayIso());
      setDateTo(toLocalIso(new Date()));
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

  const applySavedView = (v: SavedView) => {
    setSavedView(v.key);
    if ("action" in v) {
      setAction(v.action);
      setActionPrefix("");
    } else if ("action_prefix" in v) {
      setAction("");
      setActionPrefix(v.action_prefix);
    } else {
      setAction("");
      setActionPrefix("");
    }
    setOffset(0);
    setTimeout(() => fetch(0), 0);
  };

  const onApply = () => {
    setOffset(0);
    setTimeout(() => fetch(0), 0);
  };

  const onReset = () => {
    setSavedView("all");
    setAction("");
    setActionPrefix("");
    setSubjectType("");
    setActor("");
    setSubjectId("");
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
    () => complianceActivityCsvUrl(currentFilters as Record<string, string | undefined>),
    [currentFilters],
  );

  const totalMatching = view?.total_matching ?? 0;
  const totalAll = view?.total_all ?? 0;
  const items = view?.items ?? [];
  const viewOffset = view?.offset ?? 0;
  const csvTruncated = totalMatching > CSV_CAP;

  const rangeLabel = useMemo(() => {
    if (preset === "today") return "Today, midnight to now (local time)";
    if (preset === "7d") return "Last 7 days";
    if (preset === "30d") return "Last 30 days";
    if (preset === "all") return "All time";
    if (dateFrom && dateTo) return `${safeDate(dateFrom)} → ${safeDate(dateTo)}`;
    if (dateFrom) return `From ${safeDate(dateFrom)} (open-ended)`;
    if (dateTo) return `Up to ${safeDate(dateTo)} (open-ended start)`;
    return "Open-ended (no date restriction)";
  }, [preset, dateFrom, dateTo]);

  return (
    <div>
      {error ? (
        <div className="mb-4 rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      ) : null}

      <SavedViews current={savedView} onPick={applySavedView} />

      <FilterBar
        action={action}
        setAction={(v) => {
          setAction(v);
          setActionPrefix("");
          setSavedView("all");
        }}
        subjectType={subjectType}
        setSubjectType={setSubjectType}
        actor={actor}
        setActor={setActor}
        subjectId={subjectId}
        setSubjectId={setSubjectId}
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
        totalMatching={totalMatching}
        csvTruncated={csvTruncated}
        csvCap={CSV_CAP}
        rangeLabel={rangeLabel}
      />

      <ResultsHeader
        view={view}
        loading={loading}
        pageSize={PAGE_SIZE}
        lastRefreshedFallback={lastRefreshed}
      />

      <ActivityTable
        rows={items}
        loading={loading}
        totalMatching={totalMatching}
        totalAll={totalAll}
        onClearFilters={onReset}
        onExpandRange={onExpandRange}
        hasFilters={
          !!action || !!actionPrefix || !!subjectType || !!actor || !!subjectId || !!dateFrom || !!dateTo
        }
      />

      {totalMatching > PAGE_SIZE ? (
        <Pagination
          offset={viewOffset}
          pageSize={PAGE_SIZE}
          total={totalMatching}
          onGo={(next) => {
            setOffset(next);
            setTimeout(() => fetch(next), 0);
          }}
          loading={loading}
        />
      ) : null}
    </div>
  );
}

// ------------------------------------------------------ saved views

function SavedViews({
  current,
  onPick,
}: {
  current: SavedView["key"];
  onPick: (v: SavedView) => void;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-1.5">
      <span className="text-[10px] font-semibold uppercase text-muted-foreground mr-1">
        View
      </span>
      {SAVED_VIEWS.map((v) => (
        <button
          key={v.key}
          type="button"
          onClick={() => onPick(v)}
          className={
            "rounded border px-2 py-0.5 text-[10.5px] transition-colors " +
            (current === v.key
              ? "border-primary bg-primary/10 text-primary"
              : "border-border bg-background text-muted-foreground hover:border-primary/40")
          }
        >
          {v.label}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------ filter bar

function FilterBar({
  action,
  setAction,
  subjectType,
  setSubjectType,
  actor,
  setActor,
  subjectId,
  setSubjectId,
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
  csvTruncated,
  csvCap,
  rangeLabel,
}: {
  action: string;
  setAction: (v: string) => void;
  subjectType: string;
  setSubjectType: (v: string) => void;
  actor: string;
  setActor: (v: string) => void;
  subjectId: string;
  setSubjectId: (v: string) => void;
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
  csvTruncated: boolean;
  csvCap: number;
  rangeLabel: string;
}) {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
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
        <span className="ml-1 text-[10px] italic text-muted-foreground">
          {rangeLabel} · {tz}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-6">
        <div>
          <label className="text-[10px] font-semibold uppercase text-muted-foreground">
            Actor
          </label>
          <input
            type="text"
            value={actor}
            placeholder="name or user id"
            onChange={(e) => setActor(e.target.value)}
            className="mt-0.5 w-full rounded border border-border bg-background px-2 py-1 text-xs"
          />
        </div>
        <div>
          <label className="text-[10px] font-semibold uppercase text-muted-foreground">
            Record ID
          </label>
          <input
            type="text"
            value={subjectId}
            placeholder="deal_… / usr_…"
            onChange={(e) => setSubjectId(e.target.value)}
            className="mt-0.5 w-full rounded border border-border bg-background px-2 py-1 text-xs font-mono"
          />
        </div>
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
      </div>

      <div className="mt-2 flex items-center justify-end gap-1.5">
        <Button variant="outline" size="sm" className="h-7 text-xs" onClick={onReset}>
          Reset
        </Button>
        <Button size="sm" className="h-7 text-xs" onClick={onApply} disabled={loading}>
          {loading ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
          Apply
        </Button>
      </div>

      <div className="mt-2 border-t border-border/60 pt-2">
        {csvTruncated ? (
          <div className="mb-1.5 flex items-start gap-1.5 rounded border border-warning/50 bg-warning/10 px-2 py-1.5 text-[10.5px]">
            <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0 text-warning" />
            <div>
              <b>Incomplete export.</b> {totalMatching.toLocaleString()} rows match, but CSV export
              is capped at {csvCap.toLocaleString()}. Narrow the range or actor to get a complete
              slice.
            </div>
          </div>
        ) : null}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[10.5px] text-muted-foreground">
            CSV exports the rows matching the current filters (up to {csvCap.toLocaleString()}) —
            not just this page. The file includes a header block naming the filters, the row count
            and the export timestamp.
          </p>
          <a
            href={csvHref}
            target="_blank"
            rel="noopener"
            className="inline-flex h-7 items-center gap-1 rounded border border-border bg-background px-2 text-[10.5px] font-medium hover:border-primary/40"
            title={`Download CSV of the ${totalMatching.toLocaleString()} matching rows`}
          >
            <Download className="h-3 w-3" /> Export CSV
          </a>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------ results header

function ResultsHeader({
  view,
  loading,
  pageSize,
  lastRefreshedFallback,
}: {
  view: ComplianceActivityView | null;
  loading: boolean;
  pageSize: number;
  lastRefreshedFallback: Date | null;
}) {
  if (!view) return null;
  // A missing field must NOT render as 0 — a compliance officer
  // reading "0 matching" while the table shows rows would lose
  // trust in every count on the page.
  const totalRaw = view.total_matching as number | null | undefined;
  const totalAllRaw = view.total_all as number | null | undefined;
  const total = typeof totalRaw === "number" ? totalRaw : null;
  const totalAll = typeof totalAllRaw === "number" ? totalAllRaw : null;
  const off = typeof view.offset === "number" ? view.offset : 0;
  const shown = view.items.length;

  let rangeText: React.ReactNode;
  if (shown === 0 && (total === 0 || total === null)) {
    rangeText = "No events match these filters.";
  } else if (total === null) {
    // Backend didn't return a count. Show the rows we have, but
    // never fabricate a total.
    rangeText = (
      <>
        Showing <span className="text-foreground">{off + 1}–{off + shown}</span>{" "}
        <span title="Server did not return a total count. Restart the API to enable pagination totals.">
          · <b>count unavailable</b>
        </span>
      </>
    );
  } else {
    rangeText = (
      <>
        Showing{" "}
        <span className="text-foreground">
          {off + 1}–{off + shown}
        </span>{" "}
        of <span className="text-foreground">{total.toLocaleString()}</span>{" "}
        matching
        {totalAll !== null ? (
          <> (of {totalAll.toLocaleString()} total)</>
        ) : null}
        .
      </>
    );
  }

  const refreshedAt = view.generated_at
    ? safeDate(view.generated_at)
    : lastRefreshedFallback
      ? lastRefreshedFallback.toLocaleString()
      : "—";
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;

  return (
    <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[10.5px] text-muted-foreground">
      <div>
        {loading ? (
          <span className="inline-flex items-center gap-1">
            <Loader2 className="h-3 w-3 animate-spin" /> Loading…
          </span>
        ) : (
          <span>{rangeText}</span>
        )}
      </div>
      <div className="text-[10px]">
        Last refreshed {refreshedAt} · {tz}
        {pageSize ? ` · page size ${pageSize}` : ""}
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
            ? `An empty result is not evidence that no events occurred — the tenant holds ${totalAll.toLocaleString()} events overall.`
            : `The tenant holds ${totalAll.toLocaleString()} events overall; none fall in the current range.`}
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
  const outcome = prettyOutcome(row.outcome);
  const label = row.action_label || row.action;
  const outcomeCls =
    outcome.tone === "ok"
      ? "text-emerald-500"
      : outcome.tone === "bad"
        ? "text-destructive"
        : outcome.tone === "warn"
          ? "text-amber-500"
          : "text-muted-foreground";
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
          {safeDate(row.occurred_at)}
        </td>
        <td className="py-1.5 px-3 text-[11px]">{row.actor_display ?? "—"}</td>
        <td className="py-1.5 px-3">
          <div className="text-[11px] font-medium">{label}</div>
          {label !== row.action ? (
            <div className="font-mono text-[9.5px] text-muted-foreground">
              {row.action}
            </div>
          ) : (
            <div className="text-[9.5px] italic text-muted-foreground">
              (no human label — event code shown)
            </div>
          )}
        </td>
        <td className="py-1.5 px-3 text-[10.5px] text-muted-foreground">
          <div>{row.subject_type}</div>
          {row.subject_id ? (
            <div className="font-mono text-[9.5px]">{row.subject_id}</div>
          ) : null}
        </td>
        <td className={`py-1.5 px-3 text-[10.5px] font-medium ${outcomeCls}`}>
          <div className="flex items-center justify-between gap-2">
            <span>{outcome.label}</span>
            {hasDetail ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setOpen((v) => !v);
                }}
                className="rounded border border-border bg-background px-1.5 py-0.5 text-[9.5px] font-normal text-muted-foreground hover:border-primary/40 hover:text-foreground"
              >
                {open ? "Hide details" : "View details"}
              </button>
            ) : null}
          </div>
        </td>
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
  const before = (p as { before?: Record<string, unknown> }).before;
  const after = (p as { after?: Record<string, unknown> }).after;
  const restEntries = Object.entries(p).filter(
    ([k]) => k !== "before" && k !== "after",
  );

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-1 gap-x-3 gap-y-0.5 text-[10.5px] sm:grid-cols-2">
        <MetaLine k="Event id" v={row.id} mono />
        <MetaLine k="Timestamp" v={safeDate(row.occurred_at)} />
        <MetaLine k="Action code" v={row.action} mono />
        <MetaLine k="Raw outcome" v={row.outcome ?? "not recorded"} mono />
      </div>

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

function MetaLine({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex gap-2 border-b border-border/30 py-1">
      <dt className="text-[10px] font-medium text-muted-foreground min-w-[7rem]">{k}</dt>
      <dd className={"text-[10.5px] break-all " + (mono ? "font-mono" : "")}>{v}</dd>
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
