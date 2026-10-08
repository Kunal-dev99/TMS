"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Cpu, Loader2, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  listComplianceAiActivity,
  type ComplianceAiActivityView,
  type ComplianceAiRunRow,
} from "@/lib/api";

/**
 * AI Activity tab — Q-004 answer surface.
 *
 * Every LLM call the app made lands in ai_run. This tab is a filtered
 * view of it: endpoint filter, model filter, real-vs-fallback toggle,
 * date range, pagination. Each row expands to the prompt and response
 * previews the server returned (full text is available via the raw
 * row in a future 'open in detail' view; not shipped in Stage 3).
 */

const PAGE_SIZE = 50;

type FallbackFilter = "any" | "real" | "fallback";

export function AiActivityTab() {
  const [view, setView] = useState<ComplianceAiActivityView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [endpoint, setEndpoint] = useState("");
  const [model, setModel] = useState("");
  const [fallback, setFallback] = useState<FallbackFilter>("any");
  const [offset, setOffset] = useState(0);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  const params = useMemo(
    () => ({
      endpoint: endpoint || undefined,
      model: model.trim() || undefined,
      fallback:
        fallback === "real" ? false : fallback === "fallback" ? true : undefined,
      limit: PAGE_SIZE,
    }),
    [endpoint, model, fallback],
  );

  const load = (nextOffset: number = offset) => {
    setLoading(true);
    setError(null);
    listComplianceAiActivity({ ...params, offset: nextOffset })
      .then((v) => {
        setView(v);
        setLastRefreshed(new Date());
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load(0);
    setOffset(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint, model, fallback]);

  if (loading && !view) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" /> Loading AI activity…
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
  if (!view) return null;

  const total = view.total_matching;
  const totalAll = view.total_all;
  const items = view.items;
  const fallbackCount = items.filter((r) => r.fallback_used).length;
  const realCount = items.length - fallbackCount;

  return (
    <div className="space-y-3">
      <div className="rounded border border-border bg-surface-2/40 p-2.5 text-[10.5px] text-muted-foreground">
        <b>Every AI call is captured here.</b> Prompt + response text are
        stored on the row (previewed below). Fallback runs are non-AI
        decisions the deterministic engine made when the model was
        unavailable — the app never depends on the model to be up.
      </div>

      <div className="grid grid-cols-3 gap-2">
        <SummaryTile
          label="Runs (all time)"
          value={totalAll}
          tone="muted"
        />
        <SummaryTile
          label="Matching filters"
          value={total}
          tone="muted"
        />
        <SummaryTile
          label="Fallback on this page"
          value={fallbackCount}
          tone={fallbackCount > realCount ? "warn" : "muted"}
        />
      </div>

      <div className="rounded-lg border border-border bg-surface-2/40 p-3">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div>
            <label className="text-[10px] font-semibold uppercase text-muted-foreground">
              Endpoint
            </label>
            <select
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              className="mt-0.5 w-full rounded border border-border bg-background px-2 py-1 text-xs"
            >
              <option value="">All endpoints</option>
              {view.endpoints_seen.map((e) => (
                <option key={e} value={e}>
                  {e}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[10px] font-semibold uppercase text-muted-foreground">
              Model
            </label>
            <input
              type="text"
              value={model}
              placeholder="substring"
              onChange={(e) => setModel(e.target.value)}
              className="mt-0.5 w-full rounded border border-border bg-background px-2 py-1 text-xs"
            />
          </div>
          <div>
            <label className="text-[10px] font-semibold uppercase text-muted-foreground">
              Kind
            </label>
            <select
              value={fallback}
              onChange={(e) => setFallback(e.target.value as FallbackFilter)}
              className="mt-0.5 w-full rounded border border-border bg-background px-2 py-1 text-xs"
            >
              <option value="any">All</option>
              <option value="real">Real AI only</option>
              <option value="fallback">Fallback only</option>
            </select>
          </div>
          <div className="flex items-end justify-end">
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={() => {
                setEndpoint("");
                setModel("");
                setFallback("any");
              }}
            >
              Reset
            </Button>
          </div>
        </div>
      </div>

      <div className="text-[10.5px] text-muted-foreground">
        {items.length === 0 ? (
          "0 runs match these filters."
        ) : (
          <>
            Showing {view.offset + 1}–{view.offset + items.length} of{" "}
            <span className="text-foreground">{total.toLocaleString()}</span>{" "}
            (of {totalAll.toLocaleString()} total) · Last refreshed{" "}
            {lastRefreshed ? lastRefreshed.toLocaleString() : "—"}
          </>
        )}
      </div>

      {items.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-border bg-surface-2/60 text-[10px] uppercase font-semibold text-muted-foreground">
                <th className="py-2 px-3">When</th>
                <th className="py-2 px-3">Endpoint</th>
                <th className="py-2 px-3">Model</th>
                <th className="py-2 px-3 text-right">Tokens</th>
                <th className="py-2 px-3 text-right">Latency</th>
                <th className="py-2 px-3">Kind</th>
                <th className="py-2 px-3">Subject</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {items.map((r) => (
                <AiRow key={r.id} row={r} />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {total > PAGE_SIZE ? (
        <div className="mt-2 flex items-center justify-between text-[10.5px]">
          <div className="text-muted-foreground">
            Page {Math.floor(view.offset / PAGE_SIZE) + 1} of{" "}
            {Math.max(1, Math.ceil(total / PAGE_SIZE))}
          </div>
          <div className="flex gap-1.5">
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              disabled={view.offset === 0}
              onClick={() => {
                const next = Math.max(0, view.offset - PAGE_SIZE);
                setOffset(next);
                load(next);
              }}
            >
              Prev
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              disabled={view.offset + PAGE_SIZE >= total}
              onClick={() => {
                const next = view.offset + PAGE_SIZE;
                setOffset(next);
                load(next);
              }}
            >
              Next
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function AiRow({ row }: { row: ComplianceAiRunRow }) {
  const [open, setOpen] = useState(false);
  const hasDetail = !!(row.prompt_preview || row.response_preview);
  return (
    <>
      <tr
        className="align-top hover:bg-muted/30 cursor-pointer"
        onClick={() => hasDetail && setOpen((v) => !v)}
      >
        <td className="py-1.5 px-3 num text-[10.5px] text-muted-foreground whitespace-nowrap">
          {new Date(row.occurred_at).toLocaleString()}
        </td>
        <td className="py-1.5 px-3 font-mono text-[10.5px]">{row.endpoint}</td>
        <td className="py-1.5 px-3 text-[10.5px]">{row.model}</td>
        <td className="py-1.5 px-3 text-right text-[10.5px] num tabular-nums">
          {row.tokens_prompt}/{row.tokens_completion}
        </td>
        <td className="py-1.5 px-3 text-right text-[10.5px] num tabular-nums">
          {row.response_ms !== null ? `${row.response_ms} ms` : "—"}
        </td>
        <td className="py-1.5 px-3 text-[10.5px]">
          {row.fallback_used ? (
            <span className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-amber-600">
              <XCircle className="h-3 w-3" /> Fallback
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-emerald-500">
              <CheckCircle2 className="h-3 w-3" /> Real AI
            </span>
          )}
        </td>
        <td className="py-1.5 px-3 text-[10.5px] text-muted-foreground">
          {row.subject_type ? (
            <>
              <div>{row.subject_type}</div>
              {row.subject_id ? (
                <div className="font-mono text-[9.5px]">{row.subject_id}</div>
              ) : null}
            </>
          ) : (
            "—"
          )}
        </td>
      </tr>
      {open && hasDetail ? (
        <tr className="bg-surface-2/40">
          <td colSpan={7} className="py-2 px-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <PreviewBlock title="Prompt preview" body={row.prompt_preview} />
              <PreviewBlock title="Response preview" body={row.response_preview} />
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

function PreviewBlock({ title, body }: { title: string; body: string | null }) {
  return (
    <div className="rounded border border-border/60 bg-background p-2">
      <div className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">
        {title}
      </div>
      {body ? (
        <pre className="whitespace-pre-wrap break-words font-mono text-[10px] text-muted-foreground">
          {body}
        </pre>
      ) : (
        <div className="text-[10.5px] italic text-muted-foreground">—</div>
      )}
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
  tone: "ok" | "warn" | "muted";
}) {
  const toneCls =
    tone === "ok"
      ? "text-emerald-500"
      : tone === "warn"
        ? "text-amber-500"
        : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-surface-2/40 p-2.5">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase text-muted-foreground">
        <Cpu className="h-3 w-3" /> {label}
      </div>
      <div className={`num text-xl font-semibold ${toneCls}`}>
        {value.toLocaleString()}
      </div>
    </div>
  );
}
