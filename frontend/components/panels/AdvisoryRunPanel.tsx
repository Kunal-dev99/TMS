"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Sparkles, XCircle } from "lucide-react";

import { EmptyState, PanelShell } from "@/components/PanelShell";
import { getAdvisoryRun } from "@/lib/api";
import { perCent, sterling } from "@/lib/format";
import type { AdvisoryRunView } from "@/lib/types";

/**
 * The advisory run in full.
 *
 * Six stages, one of which calls a model, and the four failures it
 * structurally cannot produce.
 *
 * The candidate list is shown priced and complete, including the ones
 * excluded before ranking and the reason, because the exclusion is the
 * guardrail rather than the ranking. A reader who only sees the winner
 * cannot tell whether anything was ever refused.
 */
const STAGES = [
  { key: 1, title: "Assemble context", kind: "Deterministic", detail: "The book, the forecast, the policy and the clock. Nothing is retrieved, so there is no retrieval quality problem." },
  { key: 2, title: "Detect the gap", kind: "Deterministic", detail: "Arithmetic against the investment policy. With no gap the model is never called at all." },
  { key: 3, title: "Build candidates", kind: "Deterministic", detail: "The main guardrail. Anything that would fail the six checks is excluded before the list exists." },
  { key: 4, title: "Rank and explain", kind: "The model", detail: "Output constrained to a candidate identifier and prose. It never generates a number." },
  { key: 5, title: "Validate", kind: "Deterministic", detail: "Three tests. The identifier is real, the checks rerun clean, and every figure matches one computed at stage 3." },
  { key: 6, title: "Accept or edit", kind: "Human", detail: "Records a decision and returns a ticket. Books nothing." },
];

export function AdvisoryRunPanel({
  runId,
  onClose,
}: {
  runId: string | null;
  onClose: () => void;
}) {
  const [run, setRun] = useState<AdvisoryRunView | null>(null);

  useEffect(() => {
    if (!runId) {
      setRun(null);
      return;
    }
    const controller = new AbortController();
    setRun(null);
    getAdvisoryRun(runId, controller.signal)
      .then(setRun)
      .catch(() => undefined);
    return () => controller.abort();
  }, [runId]);

  return (
    <PanelShell
      open={runId !== null}
      onClose={onClose}
      icon={Sparkles}
      title="Advisory run"
      description="Six stages, one of which calls a model"
    >
      {run === null ? (
        <EmptyState>Reading the run.</EmptyState>
      ) : (
        <div className="space-y-6">
          <section className="rounded-lg border border-border bg-surface-2/30 p-4">
            <p className="text-sm font-medium">{run.card.headline}</p>
            <p className="mt-1 text-[10px] text-muted-foreground">
              {run.outcome.replace(/_/g, " ").toLowerCase()}
              {run.model_enabled
                ? ` · model ${run.model_name ?? "enabled"}`
                : " · model switched off in the investment policy"}
            </p>
          </section>

          <section>
            <h3 className="mb-3 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              The six stages
            </h3>
            <ol className="space-y-2.5">
              {STAGES.map((stage) => (
                <li key={stage.key} className="flex gap-3">
                  <span
                    className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                      stage.kind === "The model"
                        ? "bg-accent/20 text-accent"
                        : "bg-surface-2 text-muted-foreground"
                    }`}
                  >
                    {stage.key}
                  </span>
                  <div className="min-w-0">
                    <p className="text-[11.5px] font-medium">
                      {stage.title}
                      <span
                        className={`ml-1.5 rounded-sm border px-1 py-px text-[9px] font-normal uppercase tracking-wider ${
                          stage.kind === "The model"
                            ? "border-accent/40 text-accent"
                            : "border-border text-muted-foreground"
                        }`}
                      >
                        {stage.kind}
                      </span>
                    </p>
                    <p className="text-[10px] text-muted-foreground">
                      {stage.detail}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </section>

          <section>
            <h3 className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Candidates, priced
            </h3>
            <p className="mb-3 text-[10px] text-muted-foreground">
              Every option the rules produced, including the ones excluded
              before ranking. The exclusion is the guardrail.
            </p>
            <div className="space-y-2">
              {run.candidates.map((candidate) => (
                <div
                  key={candidate.id}
                  className={`rounded border p-2.5 ${
                    candidate.excluded
                      ? "border-border bg-surface-2/20 opacity-70"
                      : "border-primary/30 bg-primary/5"
                  }`}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-[11.5px] font-medium">
                      {candidate.rank ? `${candidate.rank}. ` : ""}
                      {candidate.counterparty_name}
                    </span>
                    <span className="num text-[11px]">
                      {sterling(candidate.amount_pence)} at{" "}
                      {perCent(candidate.indicative_rate_bp)}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                    {candidate.excluded
                      ? candidate.exclusion_reason
                      : `${candidate.tenor_months} months, score ${candidate.score_bp}.`}
                  </p>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h3 className="mb-3 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Validation
            </h3>
            <div className="space-y-2">
              {run.validation.map((result) => (
                <div key={result.test} className="flex items-start gap-2">
                  {result.passed ? (
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
                  ) : (
                    <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />
                  )}
                  <div className="min-w-0">
                    <p className="text-[11px] font-medium">
                      {result.test.replace(/_/g, " ").toLowerCase()}
                    </p>
                    <p className="text-[10px] text-muted-foreground">
                      {result.detail}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-lg border border-border bg-surface-2/30 p-3">
            <p className="text-[10px] text-muted-foreground">
              Nothing is recorded because a model suggested it. The only path
              from a recommendation into the book runs through a person and
              then through the same six checks as a deal somebody typed.
            </p>
          </section>
        </div>
      )}
    </PanelShell>
  );
}
