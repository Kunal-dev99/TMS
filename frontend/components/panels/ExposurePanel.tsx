"use client";

import { useEffect, useState } from "react";
import { BarChart3 } from "lucide-react";

import { EmptyState, PanelShell } from "@/components/PanelShell";
import { CurrencyTab } from "@/components/panels/CurrencyTab";
import { PerformanceTab } from "@/components/panels/PerformanceTab";
import { WhatIfCap } from "@/components/panels/WhatIfCap";
import { ExposureDial } from "@/components/panels/ExposureDial";
import { getExposure } from "@/lib/api";
import { perCent, sterling } from "@/lib/format";
import type {
  BookRow,
  DealSummary,
  ExposureView,
  UtilisationRow,
} from "@/lib/types";

/**
 * Exposure. Two tabs, and they can never be open at once.
 *
 * Counterparty exposure and currency exposure are separate figures moving in
 * opposite directions. A forward increases the first and reduces the second.
 * The tabs exist precisely so the two never appear in one view, because they
 * must never be netted, and the warning is in the interface rather than only
 * in the documentation, because the interface is where somebody would try
 * it.
 *
 * The currency tab stays visible while the register is empty. Hiding it
 * would hide the distinction it exists to make.
 */
export function ExposurePanel({
  open,
  onClose,
  book,
  capBp,
  deals,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  book: BookRow[];
  capBp: number;
  deals: DealSummary[];
  onPick: (counterpartyId: string) => void;
}) {
  const [tab, setTab] = useState<"counterparty" | "currency" | "performance">(
    "counterparty",
  );
  const [shape, setShape] = useState<"dial" | "table">("dial");
  const [view, setView] = useState<ExposureView | null>(null);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    getExposure(controller.signal)
      .then(setView)
      .catch(() => undefined);
    return () => controller.abort();
  }, [open]);

  return (
    <PanelShell
      open={open}
      onClose={onClose}
      icon={BarChart3}
      title="Exposure"
      description="Every counterparty's share of the book, and how close each is to its limit"
    >
      <div className="mb-5 flex gap-1 rounded-lg bg-surface-2/60 p-1">
        {(["counterparty", "currency", "performance"] as const).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              tab === key
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {key === "counterparty"
              ? "Counterparty"
              : key === "currency"
                ? "Currency"
                : "Performance"}
          </button>
        ))}
      </div>

      {tab === "counterparty" ? (
        view === null ? (
          <EmptyState>Reading the book.</EmptyState>
        ) : (
          <div className="space-y-6">
            <div className="rounded-lg border border-border bg-surface-2/30 p-4">
              <div className="flex items-baseline justify-between">
                <span className="text-xs text-muted-foreground">Portfolio total</span>
                <span className="num text-lg font-semibold">
                  {sterling(view.portfolio_total_pence)}
                </span>
              </div>
              <p className="mt-1 text-[10px] text-muted-foreground">
                Live deals at their measure, plus {sterling(view.uninvested_cash_pence)}{" "}
                uninvested. Cash counts: a concentration figure that ignores the
                operating account measures the wrong denominator.
              </p>
            </div>

            {/* The dial answers "who holds how much of this book". The
                table answers "by which cut". Two readings of one figure,
                and neither computes it. */}
            <div className="flex gap-1 rounded-lg bg-surface-2/60 p-1">
              {(["dial", "table"] as const).map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setShape(key)}
                  className={`flex-1 rounded-md px-3 py-1 text-[11px] font-medium transition-colors ${
                    shape === key
                      ? "bg-card text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {key === "dial" ? "Dial" : "Breakdown"}
                </button>
              ))}
            </div>

            {shape === "dial" ? (
              <ExposureDial
                view={view}
                book={book}
                capBp={capBp}
                onPick={(counterpartyId) => {
                  onPick(counterpartyId);
                  onClose();
                }}
              />
            ) : (
              <>
                <Utilisation title="By credit group" rows={view.by_group} />
                <Utilisation title="By rating band" rows={view.by_rating_band} />
                <Utilisation title="By maturity bucket" rows={view.by_maturity_bucket} />
              </>
            )}

            <WhatIfCap currentCapBp={capBp} />
          </div>
        )
      ) : tab === "currency" ? (
        <CurrencyTab deals={deals} />
      ) : (
        <PerformanceTab open={open && tab === "performance"} />
      )}
    </PanelShell>
  );
}

function Utilisation({ title, rows }: { title: string; rows: UtilisationRow[] }) {
  return (
    <section>
      <h3 className="mb-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {title}
      </h3>
      <div className="space-y-2.5">
        {rows.length === 0 ? (
          <p className="text-xs text-muted-foreground">Nothing held.</p>
        ) : (
          rows.map((row) => (
            <div key={row.key}>
              <div className="flex items-baseline justify-between gap-3 text-xs">
                <span className="truncate">{row.label}</span>
                <span className="num shrink-0 font-medium">
                  {sterling(row.used_pence)}
                  {row.limit_pence ? (
                    <span className="text-muted-foreground">
                      {" "}
                      of {sterling(row.limit_pence)}
                    </span>
                  ) : null}
                </span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
                <div
                  className={`h-full rounded-full ${
                    (row.utilisation_bp ?? 0) >= 10000
                      ? "bg-destructive"
                      : (row.utilisation_bp ?? 0) >= 8500
                        ? "bg-warning"
                        : "bg-primary"
                  }`}
                  style={{
                    width: `${Math.min(100, (row.utilisation_bp ?? 0) / 100)}%`,
                  }}
                />
              </div>
              {row.utilisation_bp !== null ? (
                <p className="mt-0.5 text-[10px] text-muted-foreground">
                  {perCent(row.utilisation_bp)}
                </p>
              ) : null}
            </div>
          ))
        )}
      </div>
    </section>
  );
}
