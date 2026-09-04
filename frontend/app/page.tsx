"use client";

import { useCallback, useEffect, useState } from "react";
import { UserPlus } from "lucide-react";

import { Blotter } from "@/components/Blotter";
import { Book } from "@/components/Book";
import { CheckPanel } from "@/components/CheckPanel";
import { Header } from "@/components/Header";
import { PanelShell, EmptyState } from "@/components/PanelShell";
import { SignIn } from "@/components/SignIn";
import { Strip } from "@/components/Strip";
import { Ticket, EMPTY_TICKET, toFields, type TicketState } from "@/components/Ticket";
import { Verdict } from "@/components/Verdict";
import { AdvisoryCard } from "@/components/AdvisoryCard";
import { AdvisoryRunPanel } from "@/components/panels/AdvisoryRunPanel";
import { BreachesPanel } from "@/components/panels/BreachesPanel";
import { EvidencePanel } from "@/components/panels/EvidencePanel";
import { ExposurePanel } from "@/components/panels/ExposurePanel";
import { OnboardingPanel } from "@/components/panels/OnboardingPanel";
import { QueuePanel } from "@/components/panels/QueuePanel";
import { ConfirmationParseModal } from "@/components/panels/ConfirmationParseModal";
import { CreditSignalsPanel } from "@/components/panels/CreditSignalsPanel";
import { PlannerModal } from "@/components/panels/PlannerModal";
import { RatingsPanel } from "@/components/panels/RatingsPanel";
import { Button } from "@/components/ui/button";
import {
  approveDeal,
  getBreaches,
  getQueue,
  getState,
  recordDeal,
  whenSessionEnds,
  whoAmI,
} from "@/lib/api";
import { currentToken, endSession, type SignedInUser } from "@/lib/session";
import { approverLabel } from "@/lib/format";
import type { BreachView, CheckResult, QueueItem, StateResponse } from "@/lib/types";

/**
 * One panel at a time. Not a stack, so there is never a back button.
 *
 * The rule that opening one closes another is enforced by this being a
 * single value rather than a list. A second panel cannot be opened on top of
 * a first even by mistake.
 */
type Panel =
  | { kind: "none" }
  | { kind: "exposure" }
  | { kind: "queue" }
  | { kind: "breaches" }
  | { kind: "advisory"; runId: string | null }
  | { kind: "ratings" }
  | { kind: "onboarding" }
  | { kind: "evidence"; dealId: string };

/**
 * The surface.
 *
 * One surface carries all five models. The process design draws five because
 * they are five subjects, not five systems: they share one database and one
 * deal record, so they share one screen.
 *
 * The navigation budget from section 2 of document 3 is a limit rather than
 * a target. One surface. Zero page loads after the first. One click to
 * anything. One panel open at a time. Five items in the strip. A change that
 * breaks one of those is a change to argue about rather than absorb, which
 * is why there is no second navigation surface beside the strip.
 *
 * One state object from one call, replaced wholesale after every write. No
 * optimistic updates: the book, the blotter and the exposure panel must
 * agree, and refetching is the cheapest way to guarantee it.
 */
export default function Surface() {
  const [user, setUser] = useState<SignedInUser | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [state, setState] = useState<StateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel>({ kind: "none" });
  const [plannerOpen, setPlannerOpen] = useState(false);
  const [parseOpen, setParseOpen] = useState(false);
  const [signalsOpen, setSignalsOpen] = useState(false);

  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [breaches, setBreaches] = useState<BreachView[]>([]);

  const [ticket, setTicket] = useState<TicketState>(EMPTY_TICKET);
  const [result, setResult] = useState<CheckResult | null>(null);
  const [recording, setRecording] = useState(false);
  /** Set when the ticket was filled from a recommendation, so the deal
   *  can be written back to it once it has passed the six checks. */
  const [acceptedFrom, setAcceptedFrom] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const [next, openItems, raised] = await Promise.all([
        getState(signal),
        getQueue(),
        getBreaches(),
      ]);
      setState(next);
      setQueue(openItems);
      setBreaches(raised);
      setError(null);
    } catch (cause: unknown) {
      if (signal?.aborted) return;
      setError(cause instanceof Error ? cause.message : "The state call failed.");
    }
  }, []);

  /**
   * A token in sessionStorage survives a reload, so the surface asks the
   * server who it belongs to rather than trusting what it has cached.
   */
  useEffect(() => {
    whenSessionEnds(() => {
      setUser(null);
      setState(null);
    });

    if (!currentToken()) {
      setCheckingSession(false);
      return;
    }
    whoAmI()
      .then(setUser)
      .catch(() => endSession())
      .finally(() => setCheckingSession(false));
  }, []);

  useEffect(() => {
    if (!user) return;
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [user, load]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 2600);
    return () => clearTimeout(timer);
  }, [toast]);

  /**
   * Record, then sign, then refetch the whole state.
   *
   * Two calls in one interaction, because recording and approving are two
   * decisions even when one person makes both.
   */
  const record = useCallback(
    async (overrideReason?: string) => {
      const fields = toFields(ticket);
      if (!fields) return;
      setRecording(true);
      try {
        const booked = await recordDeal(fields, overrideReason, acceptedFrom);
        if (booked.deal.status === "BLOCKED") {
          // The ticket keeps its values, because the user will usually
          // resize rather than start again.
          setToast("Blocked. The deal went to the queue.");
        } else {
          const role =
            booked.run.required_approver ?? booked.deal.required_approver ?? "ANALYST";
          try {
            await approveDeal(booked.deal.id, role);
            setToast(`Recorded, and signed as ${approverLabel(role)}.`);
          } catch {
            // Since phase 1.5 the proposer cannot sign their own deal, and
            // a signer must hold the role the amount requires. Both are
            // refusals rather than failures, so the deal stays proposed and
            // the surface says who has to pick it up.
            setToast(
              `Recorded. Awaiting a signature from ${approverLabel(role)}.`,
            );
          }
          setTicket(EMPTY_TICKET);
          setResult(null);
          setAcceptedFrom(null);
        }
        await load();
      } catch (cause: unknown) {
        setToast(cause instanceof Error ? cause.message : "That write was refused.");
      } finally {
        setRecording(false);
      }
    },
    [ticket, load, acceptedFrom],
  );

  if (checkingSession) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <p className="text-xs text-muted-foreground">Checking the session.</p>
      </div>
    );
  }

  if (!user) {
    return <SignIn onSignedIn={setUser} />;
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <Header
        state={state}
        user={user}
        onReset={() => load()}
        onSignedOut={() => {
          setUser(null);
          setState(null);
        }}
        onParseConfirmation={() => setParseOpen(true)}
      />

      {state === null ? (
        /* One quiet skeleton, not eleven spinners. */
        <div className="flex flex-1 items-center justify-center">
          <p className="text-xs text-muted-foreground">
            {error ?? "Reading the book."}
          </p>
        </div>
      ) : (
        /* The book at 58 per cent, the ticket at 42. */
        <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[58fr_42fr]">
          <section className="min-w-0 space-y-5 overflow-y-auto px-6 py-5">
            <Book
              rows={state.book}
              portfolioTotalPence={state.portfolio_total_pence}
              uninvestedCashPence={state.uninvested_cash_pence}
              onSelect={(counterpartyId) =>
                setTicket((current) => ({ ...current, counterpartyId }))
              }
              action={
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 gap-1.5 text-xs"
                  onClick={() => setPanel({ kind: "onboarding" })}
                >
                  <UserPlus className="h-3.5 w-3.5" />
                  Add
                </Button>
              }
            />
            <Blotter
              deals={state.deals}
              onSelect={(dealId) => setPanel({ kind: "evidence", dealId })}
            />
          </section>

          <section className="min-w-0 space-y-5 overflow-y-auto border-l border-border px-6 py-5">
            {/* AI actions on today's book — the two features that read
                the whole book rather than one deal. Grouped visually so
                a reader sees both at once. */}
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {state.uninvested_cash_pence > 0 ? (
                <button
                  type="button"
                  className="group flex flex-col items-start rounded-lg border border-primary/40 bg-primary/[.06] p-3 text-left transition hover:bg-primary/10"
                  onClick={() => setPlannerOpen(true)}
                >
                  <span className="text-[9px] font-medium uppercase tracking-wider text-primary">
                    ✨ Deploy the idle cash
                  </span>
                  <p className="mt-0.5 text-[11px] text-foreground">
                    Four ways to place £
                    {(state.uninvested_cash_pence / 100).toLocaleString(
                      "en-GB",
                      { maximumFractionDigits: 0 },
                    )}
                    , ranked.
                  </p>
                </button>
              ) : null}
              <button
                type="button"
                className="group flex flex-col items-start rounded-lg border border-primary/40 bg-primary/[.06] p-3 text-left transition hover:bg-primary/10"
                onClick={() => setSignalsOpen(true)}
              >
                <span className="text-[9px] font-medium uppercase tracking-wider text-primary">
                  ✨ Scan credit signals
                </span>
                <p className="mt-0.5 text-[11px] text-foreground">
                  What&apos;s in the news about every counterparty on your
                  book.
                </p>
              </button>
            </div>

            {/* Above the ticket fields, inside the ticket column. An input
                to the work rather than an interruption of it. */}
            {state.advisory ? (
              <AdvisoryCard
                card={state.advisory}
                onAccept={(accepted, recommendationId) => {
                  setTicket({
                    counterpartyId: accepted.counterparty_id,
                    instrument: accepted.instrument,
                    principal: String(Math.round(accepted.principal_pence / 100)),
                    tenor: String(accepted.tenor_months),
                    rate: (accepted.rate_bp / 100).toFixed(2),
                  });
                  setAcceptedFrom(recommendationId);
                  setToast("Loaded. It runs the same six checks as anything typed.");
                  load();
                }}
                onDecided={() => {
                  setToast("Recorded. The next run learns from it.");
                  load();
                }}
                onOpenRun={(runId) => setPanel({ kind: "advisory", runId })}
              />
            ) : null}

            <Ticket
              ticket={ticket}
              onChange={setTicket}
              book={state.book}
              onResult={setResult}
              onRecord={record}
              recording={recording}
              result={result}
              enforcement={state.enforcement}
            />

            <CheckPanel
              result={result}
              onResize={(pence) =>
                setTicket((current) => ({
                  ...current,
                  principal: String(Math.round(pence / 100)),
                }))
              }
            />

            <Verdict result={result} />
          </section>
        </main>
      )}

      {/* Bottom centre, 2.6 seconds. Confirmations and errors that do not
          belong to a field. */}
      {toast ? (
        <div className="fixed bottom-16 left-1/2 z-40 -translate-x-1/2 rounded-md border border-border bg-card px-4 py-2 text-xs shadow-lg">
          {toast}
        </div>
      ) : null}

      <Strip
        queueCount={state?.queue_counts.total ?? 0}
        breachCount={state?.breach_count ?? 0}
        advisoryCount={state?.advisory ? 1 : 0}
        onOpen={(item) => {
          if (item === "Exposure") setPanel({ kind: "exposure" });
          if (item === "Queue") setPanel({ kind: "queue" });
          if (item === "Breaches") setPanel({ kind: "breaches" });
          if (item === "Advisory")
            setPanel({
              kind: "advisory",
              runId: state?.advisory?.run_id ?? state?.advisory_run_id ?? null,
            });
          if (item === "Ratings and policy") setPanel({ kind: "ratings" });
        }}
      />

      {state !== null ? (
        <>
          <ExposurePanel
            open={panel.kind === "exposure"}
            onClose={() => setPanel({ kind: "none" })}
            book={state.book}
            capBp={state.policy.concentration_cap_bp}
            deals={state.deals}
            onPick={(counterpartyId) =>
              setTicket((current) => ({ ...current, counterpartyId }))
            }
          />
          <QueuePanel
            open={panel.kind === "queue"}
            onClose={() => setPanel({ kind: "none" })}
            items={queue}
            enforcement={state.enforcement}
            onResolved={() => {
              setToast("Resolved.");
              load();
            }}
          />
          <BreachesPanel
            open={panel.kind === "breaches"}
            onClose={() => setPanel({ kind: "none" })}
            breaches={breaches}
            onResponded={() => {
              setToast("Recorded. The position is still outside policy.");
              load();
            }}
            onShowEvidence={(dealId) => setPanel({ kind: "evidence", dealId })}
          />
          <RatingsPanel
            open={panel.kind === "ratings"}
            onClose={() => setPanel({ kind: "none" })}
            state={state}
            onApplied={async (breachesRaised) => {
              await load();
              // The one place the interface navigates on the user's behalf,
              // because the result is the reason they pressed it.
              if (breachesRaised > 0) setPanel({ kind: "breaches" });
            }}
          />
          <OnboardingPanel
            open={panel.kind === "onboarding"}
            onClose={() => setPanel({ kind: "none" })}
            bands={state.rating_bands}
            onFinished={() => {
              setToast("Active. The name is in the book and in the ticket.");
              load();
            }}
          />
          <EvidencePanel
            dealId={panel.kind === "evidence" ? panel.dealId : null}
            onClose={() => setPanel({ kind: "none" })}
            onSigned={() => {
              setToast("Signed. On the book.");
              load();
            }}
          />

          {panel.kind === "advisory" && panel.runId === null ? (
            <PanelShell
              open
              onClose={() => setPanel({ kind: "none" })}
              title="Advisory run"
              description="Six stages, one of which calls a model"
            >
              <EmptyState>
                No run has produced an outstanding recommendation. The nightly
                job runs accrual first and then the advisory layer, and the
                layer refuses to run without an investment policy.
              </EmptyState>
            </PanelShell>
          ) : (
            <AdvisoryRunPanel
              runId={panel.kind === "advisory" ? panel.runId : null}
              onClose={() => setPanel({ kind: "none" })}
            />
          )}
        </>
      ) : null}

      <ConfirmationParseModal
        open={parseOpen}
        onClose={() => setParseOpen(false)}
        book={state?.book ?? []}
        onIngested={() => {
          load();
        }}
      />

      <CreditSignalsPanel
        open={signalsOpen}
        onClose={() => setSignalsOpen(false)}
      />

      <PlannerModal
        open={plannerOpen}
        onClose={() => setPlannerOpen(false)}
        onPick={(a) => {
          setTicket({
            counterpartyId: a.counterparty_id,
            instrument: "DEPOSIT",
            principal: String(Math.round(a.principal_pence / 100)),
            tenor: String(a.tenor_months),
            rate: (a.rate_bp / 100).toFixed(2),
          });
          setPlannerOpen(false);
          setToast(
            "Loaded. Runs the same six checks as anything typed by hand.",
          );
        }}
      />
    </div>
  );
}
