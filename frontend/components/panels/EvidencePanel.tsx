"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Circle, FileText, PenLine, XCircle } from "lucide-react";

import { EmptyState, PanelShell } from "@/components/PanelShell";
import { Button } from "@/components/ui/button";
import {
  AmendmentSection,
  ConfirmationSection,
  SettlementSection,
} from "@/components/panels/DealLifecycle";
import { approveDeal, getDeal } from "@/lib/api";
import { approverLabel, perCent, shortDate, sterling } from "@/lib/format";
import type { DealDetail } from "@/lib/types";

/**
 * The deal lifecycle, and the evidence behind the booking.
 *
 * Reached by clicking any blotter row. The whole of model 2 is one click
 * from there and nowhere else.
 *
 * The check evidence is read back from what was written on the day, never
 * recomputed. That is what turns "compliant when booked" from a claim into a
 * fact: the six checks as they stood, the limit in force then, and the name
 * that signed.
 *
 * The closing line is the point. Until a deal closes, the counterparty holds
 * the headroom and the next deal may be blocked for no reason.
 */
const SOURCE_LABEL: Record<string, string> = {
  OUTSIDE: "outside",
  ORACLE: "Oracle",
  PLATFORM: "",
};

export function EvidencePanel({
  dealId,
  onClose,
  onSigned,
}: {
  dealId: string | null;
  onClose: () => void;
  onSigned?: () => void;
}) {
  const [detail, setDetail] = useState<DealDetail | null>(null);
  const [signing, setSigning] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  const reload = useCallback(
    (signal?: AbortSignal) => {
      if (!dealId) return;
      getDeal(dealId, signal)
        .then(setDetail)
        .catch(() => undefined);
    },
    [dealId],
  );

  useEffect(() => {
    if (!dealId) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    setDetail(null);
    setRefusal(null);
    reload(controller.signal);
    return () => controller.abort();
  }, [dealId, reload]);

  /**
   * Sign a deal somebody else proposed.
   *
   * The button is offered to everybody, because whether this caller may sign
   * is the server's decision and not the client's. Hiding it would be a
   * guess at a rule, and a guess that disagreed with the server would be
   * worse than a refusal the user can read.
   */
  const sign = async () => {
    if (!detail?.deal.required_approver || !dealId) return;
    setSigning(true);
    setRefusal(null);
    try {
      await approveDeal(dealId, detail.deal.required_approver);
      reload();
      onSigned?.();
    } catch (cause: unknown) {
      setRefusal(cause instanceof Error ? cause.message : "That signature was refused.");
    } finally {
      setSigning(false);
    }
  };

  return (
    <PanelShell
      open={dealId !== null}
      onClose={onClose}
      icon={FileText}
      title={detail ? detail.deal.counterparty_name : "Deal"}
      description="The lifecycle, and the checks it passed"
    >
      {detail === null ? (
        <EmptyState>Reading the deal.</EmptyState>
      ) : (
        <div className="space-y-6">
          {detail.deal.status === "PROPOSED" ? (
            <section className="rounded-lg border border-warning/40 bg-warning/10 p-4">
              <div className="flex items-start gap-3">
                <PenLine className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-warning">
                    Awaiting a signature from{" "}
                    {approverLabel(detail.deal.required_approver)}.
                  </p>
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    Proposed by {detail.deal.approved_by ?? "somebody"}
                    {". "}
                    A deal cannot be signed by the person who proposed it, and
                    the signer has to hold the role the amount requires. The
                    checks run again on signing, because this is the moment it
                    goes on the book.
                  </p>

                  {refusal ? (
                    <p className="mt-2 rounded border border-destructive/40 bg-destructive/10 p-2 text-[10px] text-destructive">
                      {refusal}
                    </p>
                  ) : null}

                  <Button
                    type="button"
                    size="sm"
                    className="mt-3 h-7 text-xs"
                    disabled={signing}
                    onClick={sign}
                  >
                    {signing
                      ? "Signing"
                      : `Sign as ${approverLabel(detail.deal.required_approver)}`}
                  </Button>
                </div>
              </div>
            </section>
          ) : null}

          <section className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-surface-2/30 p-4 text-xs">
            <Figure label="Principal" value={sterling(detail.deal.principal_pence)} />
            <Figure
              label="Measured"
              value={sterling(detail.deal.measured_pence)}
              hint={detail.deal.measurement_basis}
            />
            <Figure label="Rate" value={perCent(detail.deal.rate_bp)} />
            <Figure label="Term" value={`${detail.deal.tenor_months} months`} />
            <Figure label="Stage" value={detail.deal.stage} />
            <Figure
              label="Matures"
              value={shortDate(detail.deal.maturity_date)}
            />
          </section>

          <section>
            <h3 className="mb-3 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Lifecycle
            </h3>
            <ol className="space-y-3">
              {detail.timeline.map((event) => (
                <li key={event.key} className="flex gap-3">
                  <span
                    className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                      event.state === "DONE"
                        ? "bg-success"
                        : event.state === "WARN"
                          ? "bg-warning"
                          : "bg-border"
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <span
                        className={`text-[11.5px] font-medium ${
                          event.state === "FUTURE" ? "text-muted-foreground" : ""
                        }`}
                      >
                        {event.title}
                        {SOURCE_LABEL[event.source] ? (
                          <span className="ml-1.5 rounded-sm border border-border px-1 py-px text-[9px] font-normal uppercase tracking-wider text-muted-foreground">
                            {SOURCE_LABEL[event.source]}
                          </span>
                        ) : null}
                      </span>
                      <span className="shrink-0 text-[10px] text-muted-foreground">
                        {event.occurred_at ? shortDate(event.occurred_at) : "—"}
                      </span>
                    </div>
                    <p className="text-[10.5px] text-muted-foreground">
                      {event.detail}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </section>

          {detail.run ? (
            <section>
              <h3 className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                The checks it passed
              </h3>
              <p className="mb-3 text-[10px] text-muted-foreground">
                Read back from what was written on the day, never recomputed.
                {detail.limit
                  ? ` Limit in force then: ${sterling(detail.limit.amount_pence)} to ${detail.limit.max_tenor_months} months, approved by ${detail.limit.approved_by}.`
                  : ""}
              </p>
              <div className="space-y-2">
                {detail.run.checks.map((check) => (
                  <div
                    key={check.key}
                    className="flex items-start gap-2 border-b border-border/40 py-2 last:border-0"
                  >
                    {check.passed ? (
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
                    ) : (
                      <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />
                    )}
                    <div className="min-w-0">
                      <p className="text-[11px] font-medium">{check.name}</p>
                      <p className="text-[10px] text-muted-foreground">
                        {check.detail}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ) : (
            <section>
              <h3 className="mb-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                The checks it passed
              </h3>
              <EmptyState>
                This position predates the gate. Seeded deals carry no check
                run, which is why the seed is illustrative rather than
                evidence.
              </EmptyState>
            </section>
          )}

          <ConfirmationSection detail={detail} />

          <AmendmentSection
            detail={detail}
            onChanged={() => {
              reload();
              onSigned?.();
            }}
          />

          <SettlementSection
            detail={detail}
            onChanged={() => {
              reload();
              onSigned?.();
            }}
          />

          {detail.accruals.length > 0 ? (
            <section>
              <h3 className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                Recognised, per day
              </h3>
              <p className="mb-2 text-[10px] text-muted-foreground">
                Stored rather than recomputed, because what was recognised on
                a day is a fact and a later recalculation would quietly
                rewrite it.
              </p>
              <div className="flex items-baseline justify-between rounded border border-border bg-surface-2/30 p-2.5 text-xs">
                <span className="text-muted-foreground">
                  {detail.accruals.filter((row) => !row.reversal_of).length}{" "}
                  days
                  {detail.accruals.some((row) => row.reversal_of)
                    ? `, ${detail.accruals.filter((row) => row.reversal_of).length} reversed`
                    : ""}
                </span>
                <span className="num font-medium">
                  {sterling(
                    detail.accruals.reduce(
                      (total, row) => total + row.amount_pence,
                      0,
                    ),
                  )}
                </span>
              </div>
              {detail.journals.length > 0 ? (
                <ul className="mt-2 space-y-1">
                  {detail.journals.map((journal) => (
                    <li
                      key={`${journal.period}-${journal.status}`}
                      className="flex items-baseline justify-between text-[10px]"
                    >
                      <span className="text-muted-foreground">
                        {journal.period}, {journal.count} entries,{" "}
                        {journal.status.toLowerCase()}
                        {journal.oracle_reference
                          ? ` · ${journal.oracle_reference}`
                          : ""}
                      </span>
                      <span className="num">
                        {sterling(journal.amount_pence)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>
          ) : null}

          {detail.breaches.length > 0 ? (
            <section>
              <h3 className="mb-2 text-[10px] font-medium uppercase tracking-wider text-destructive">
                Outside policy
              </h3>
              {detail.breaches.map((breach) => (
                <p key={breach.id} className="text-xs text-muted-foreground">
                  {breach.detail}
                </p>
              ))}
            </section>
          ) : null}

          <section className="flex items-start gap-2 rounded-lg border border-border bg-surface-2/30 p-3">
            <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <p className="text-[10px] text-muted-foreground">
              The whole of the deal lifecycle, in one view. Execution and
              confirmation are labelled outside, payment and journals as
              Oracle, so the boundary is visible without a separate
              integration screen.
            </p>
          </section>
        </div>
      )}
    </PanelShell>
  );
}

function Figure({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="num text-sm font-medium">{value}</p>
      {hint ? <p className="text-[10px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}
