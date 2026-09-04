"use client";

import { useEffect, useState } from "react";
import { AlertOctagon, Eye, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { scanCreditSignals, type CreditSignal } from "@/lib/api";
import { perCent, sterling } from "@/lib/format";
import { ThinkingTrace } from "@/components/panels/ThinkingTrace";
import { TypedText } from "@/components/panels/TypedText";

/**
 * Credit signals — an AI reading of news for every counterparty on the
 * book, grounded in the current exposure. A treasurer cannot personally
 * read the FT for forty counterparties every morning; the scanner does
 * that first pass and surfaces what warrants attention.
 *
 * A card offers a suggested action but does not act. Clicking Put on
 * watch here would record the flag and reappear in the Ratings panel
 * for the person to review, so the AI proposes and the ordinary path
 * disposes.
 */

const SIGNAL_STEPS = [
  "Reading every counterparty's news file.",
  "Cross-referencing today's exposure to each name.",
  "Classifying each item as material or routine.",
  "Ranking counterparties by attention needed.",
  "Writing the card for each.",
];

const SEVERITY_ACCENT: Record<CreditSignal["severity"], string> = {
  MATERIAL: "border-destructive/50 bg-destructive/[.06]",
  WATCH: "border-warning/50 bg-warning/[.06]",
  QUIET: "border-border bg-surface-2/30",
};

const SEVERITY_LABEL: Record<CreditSignal["severity"], string> = {
  MATERIAL: "MATERIAL",
  WATCH: "WATCH",
  QUIET: "QUIET",
};

const MATERIALITY_TONE: Record<string, string> = {
  MATERIAL: "text-destructive",
  WATCH: "text-warning",
  IMMATERIAL: "text-muted-foreground",
};

const ACTION_LABEL: Record<CreditSignal["suggested_action"], string> = {
  PUT_ON_WATCH: "Put on watch",
  REDUCE: "Reduce",
  ROLL_OFF: "Roll off at maturity",
  MONITOR: "Monitor",
  IGNORE: "Ignore",
};


export function CreditSignalsPanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [signals, setSignals] = useState<CreditSignal[] | null>(null);
  const [pending, setPending] = useState<CreditSignal[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [networkDone, setNetworkDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setBusy(true);
    setError(null);
    setSignals(null);
    setPending(null);
    setNetworkDone(false);
    scanCreditSignals()
      .then((result) => {
        setPending(result.signals);
        setNetworkDone(true);
      })
      .catch((cause: unknown) => {
        setError(
          cause instanceof Error
            ? cause.message
            : "The scanner was refused.",
        );
        setBusy(false);
      });
  }, [open]);

  if (!open) return null;

  const material = (signals ?? []).filter((s) => s.severity === "MATERIAL").length;
  const watch = (signals ?? []).filter((s) => s.severity === "WATCH").length;
  const quiet = (signals ?? []).filter((s) => s.severity === "QUIET").length;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-6"
      role="dialog"
      aria-modal="true"
      aria-label="Credit signals"
    >
      <div className="relative w-full max-w-4xl rounded-lg border border-border bg-card shadow-2xl">
        <header className="flex items-start justify-between gap-4 border-b border-border p-5">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              <AlertOctagon className="h-4 w-4 text-primary" aria-hidden />
              Credit signals
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              What&apos;s in the news about every counterparty on your book,
              classified and ranked. The AI reads; you decide.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:bg-surface-2 hover:text-foreground"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="p-5">
          {error ? (
            <p className="rounded border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
              {error}
            </p>
          ) : null}

          {busy && !signals ? (
            <ThinkingTrace
              steps={SIGNAL_STEPS}
              finished={networkDone}
              intervalMs={320}
              onFinished={() => {
                if (pending) setSignals(pending);
                setBusy(false);
              }}
            />
          ) : null}

          {signals ? (
            <>
              <div className="mb-4 grid grid-cols-3 gap-3 rounded-lg border border-border bg-surface-2/30 p-3">
                <Stat
                  label="Material"
                  value={material}
                  tone={material > 0 ? "text-destructive" : "text-muted-foreground"}
                />
                <Stat
                  label="Watch"
                  value={watch}
                  tone={watch > 0 ? "text-warning" : "text-muted-foreground"}
                />
                <Stat label="Quiet" value={quiet} tone="text-muted-foreground" />
              </div>

              <div className="space-y-3">
                {signals.map((s) => (
                  <SignalCard key={s.counterparty_id} signal={s} />
                ))}
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}


function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div>
      <p className="text-[9px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className={`num mt-0.5 text-lg font-semibold ${tone}`}>{value}</p>
    </div>
  );
}


function SignalCard({ signal }: { signal: CreditSignal }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <article
      className={`rounded-lg border p-3 ${SEVERITY_ACCENT[signal.severity]}`}
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold">{signal.counterparty_name}</h3>
            <span className="text-[10px] text-muted-foreground">
              {signal.rating}
            </span>
            <span
              className={`rounded px-1.5 py-px text-[9px] font-medium uppercase tracking-wider ${
                signal.severity === "MATERIAL"
                  ? "bg-destructive/15 text-destructive"
                  : signal.severity === "WATCH"
                    ? "bg-warning/15 text-warning"
                    : "bg-surface-2 text-muted-foreground"
              }`}
            >
              {SEVERITY_LABEL[signal.severity]}
            </span>
          </div>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            {sterling(signal.used_pence)} of {sterling(signal.limit_pence)} used
            {" · "}
            {perCent(signal.utilisation_bp)} of the limit
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[9px] italic text-muted-foreground">
            read just now
          </span>
        </div>
      </div>

      <p className="text-xs leading-relaxed text-foreground">
        <TypedText text={signal.summary} charsPerSecond={90} />
      </p>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border/40 pt-2">
        <button
          type="button"
          className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground"
          onClick={() => setExpanded((e) => !e)}
        >
          <Eye className="h-3 w-3" />
          {expanded ? "Hide" : "Show"} the {signal.items.length} item(s) on file
        </button>

        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground">Suggested</span>
          <span
            className="rounded border border-primary/40 bg-primary/[.06] px-2 py-0.5 text-[10px] font-medium text-primary"
            title="A suggestion. Clicking here would record the action; nothing on the book moves without it."
          >
            {ACTION_LABEL[signal.suggested_action]}
          </span>
        </div>
      </div>

      {expanded ? (
        <ul className="mt-3 space-y-2 border-t border-border/40 pt-3">
          {signal.items.map((item) => (
            <li
              key={item.id}
              className="rounded border border-border/40 bg-card p-2"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[11px] font-medium">{item.headline}</p>
                  <p className="mt-0.5 text-[9.5px] text-muted-foreground">
                    {item.source} · {item.published_at}
                  </p>
                </div>
                <span
                  className={`shrink-0 rounded px-1.5 py-px text-[8.5px] font-medium uppercase tracking-wider ${
                    MATERIALITY_TONE[item.materiality]
                  }`}
                >
                  {item.materiality}
                </span>
              </div>
              {item.reasoning ? (
                <p className="mt-1.5 border-t border-border/30 pt-1.5 text-[9.5px] italic text-muted-foreground">
                  <Sparkles className="mr-1 inline h-2.5 w-2.5" aria-hidden />
                  {item.reasoning}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}
