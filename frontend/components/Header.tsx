"use client";

import type { StateResponse } from "@/lib/types";
import { shortDate } from "@/lib/format";
import { Header as RedwoodHeader } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { resetBook, runNightly, signOut } from "@/lib/api";
import { useState } from "react";
import { Check, FileText, Landmark, Loader2, Play, RotateCcw, Settings2 } from "lucide-react";
import type { SignedInUser } from "@/lib/session";

/**
 * Enterprise Header integrating the Redwood Professional layout header
 * with TMS specific controls (prototype badge, tenant, enforcement, date, reset).
 */
export function Header({
  state,
  user,
  onReset,
  onSignedOut,
  onParseConfirmation,
  onOpenPlannerSettings,
  onOpenAccountingEvents,
}: {
  state: StateResponse | null;
  user?: SignedInUser | null;
  onReset?: () => void;
  onSignedOut?: () => void;
  onParseConfirmation?: () => void;
  onOpenPlannerSettings?: () => void;
  onOpenAccountingEvents?: () => void;
}) {
  const [nightlyBusy, setNightlyBusy] = useState(false);
  const [nightlyResult, setNightlyResult] = useState<string | null>(null);
  const [resetBusy, setResetBusy] = useState(false);
  const [resetDone, setResetDone] = useState(false);

  const doReset = async () => {
    // Idempotent: nothing bad happens if double-clicked, but the button
    // is disabled during the call and shows the running state so the
    // reader is not left wondering whether the click landed.
    if (resetBusy) return;
    setResetBusy(true);
    setResetDone(false);
    try {
      await resetBook();
      onReset?.();
      setResetDone(true);
      // Fade the tick out after a moment so the button returns to its
      // idle appearance rather than staying green forever.
      window.setTimeout(() => setResetDone(false), 1200);
    } finally {
      setResetBusy(false);
    }
  };

  const runTheNight = async () => {
    setNightlyBusy(true);
    setNightlyResult(null);
    try {
      // Runs the same endpoint the scheduler will call. In production the
      // scheduler is the only caller and there is no button, because the
      // job runs on its own. Here it lives beside Reset so a demonstration
      // does not need a terminal, and both controls sit under the
      // "Prototype" badge that says so.
      const outcome = (await runNightly()) as {
        accrual_rows_written?: number;
        journals_built?: number;
        advisory_outcome?: string;
      };
      const rows = outcome.accrual_rows_written ?? 0;
      const journals = outcome.journals_built ?? 0;
      const advisory =
        outcome.advisory_outcome === "MODEL_ACCEPTED"
          ? " · advisory ran"
          : outcome.advisory_outcome === "MODEL_REJECTED_FALLBACK"
            ? " · advisory fell back"
            : outcome.advisory_outcome === "RULE_ONLY"
              ? " · advisory off"
              : "";
      setNightlyResult(
        `${rows} accruals, ${journals} journals${advisory}`,
      );
      onReset?.();
    } catch (cause: unknown) {
      setNightlyResult(
        cause instanceof Error ? cause.message : "That was refused.",
      );
    } finally {
      setNightlyBusy(false);
    }
  };

  return (
    <RedwoodHeader
      title="Treasury Register"
      logoSrc="/fusion-logo.png"
      logoAlt="Fusion Practices"
      actions={
        <div className="flex flex-wrap items-center justify-end gap-2 [&_button]:whitespace-nowrap">
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold border status-testing">
            Prototype
          </span>

          {state?.tenant_name ? (
            <span className="hidden sm:inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium border border-border bg-surface-2 text-foreground">
              {state.tenant_name}
            </span>
          ) : null}

          <div className="hidden lg:flex items-center gap-3 text-xs text-muted-foreground pl-2 border-l border-border">
            <span>Today <strong className="text-foreground font-medium">{shortDate(state?.as_of_date)}</strong></span>
            <span>
              Enforcement:{" "}
              <strong className="text-foreground font-medium">
                {state?.enforcement === "WARN_WITH_OVERRIDE"
                  ? "warn with override"
                  : "hard block"}
              </strong>
            </span>
          </div>

          {/* Drop every row and reload the seed. The one place in the
              system where anything is deleted: nothing a user does inside
              the system deletes anything. */}
          {/* A demonstration control, in the same row as Reset and behind
              the Prototype badge, because it is one. In production the
              nightly job runs on a schedule and there is no button. Here
              a treasurer needs to see accruals and journals appear
              without switching to a terminal, and the readout to the
              right of it says what happened so the audience knows the
              click did something. */}
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              type="button"
              disabled={nightlyBusy}
              onClick={runTheNight}
              className="h-7 gap-1.5 px-2.5 text-xs text-muted-foreground"
              title="Runs the same endpoint the scheduler will call in production."
            >
              <Play className="h-3 w-3" />
              {nightlyBusy ? "Running..." : "Run the nightly job"}
            </Button>
            {nightlyResult ? (
              <span
                className="hidden xl:inline whitespace-nowrap text-[10px] text-muted-foreground max-w-[220px] truncate"
                title={nightlyResult}
              >
                {nightlyResult}
              </span>
            ) : null}
          </div>

          {/* The AI parser. Any format arrives, the model reads it,
              the person reviews, the six checks gate the ingest. */}
          {onParseConfirmation ? (
            <Button
              variant="outline"
              size="sm"
              type="button"
              className="h-7 gap-1.5 px-2.5 text-xs text-muted-foreground"
              onClick={onParseConfirmation}
              title="Paste an email, SWIFT message or PDF text. AI extracts the fields."
            >
              <FileText className="h-3 w-3" />
              Paste a confirmation
            </Button>
          ) : null}

          <Button
            variant="outline"
            size="sm"
            type="button"
            disabled={resetBusy}
            onClick={doReset}
            className={`h-7 gap-1.5 px-2.5 text-xs ${
              resetDone
                ? "border-success/50 text-success"
                : "text-muted-foreground"
            }`}
            title="Restore the seeded book. About one second."
          >
            {resetBusy ? (
              <>
                <Loader2 className="h-3 w-3 animate-spin" />
                Resetting…
              </>
            ) : resetDone ? (
              <>
                <Check className="h-3 w-3" />
                Reset
              </>
            ) : (
              <>
                <RotateCcw className="h-3 w-3" />
                Reset
              </>
            )}
          </Button>

          {/* Investment principles — Anil's Sep-8 "everything
              config-driven" ask. Sliders for risk floor, tenor cap,
              concentration, and an allocation-bucket table. The
              planner reads these on every run. */}
          {onOpenPlannerSettings ? (
            <Button
              variant="outline"
              size="sm"
              type="button"
              onClick={onOpenPlannerSettings}
              className="h-7 w-7 p-0 text-muted-foreground"
              title="Investment principles — buckets, risk floor, concentration"
              aria-label="Investment principles"
            >
              <Settings2 className="h-3.5 w-3.5" />
            </Button>
          ) : null}

          {/* Anil's "everything config-driven" catalogue: which
              lifecycle stages fire an accounting event, and where
              they post. */}
          {onOpenAccountingEvents ? (
            <Button
              variant="outline"
              size="sm"
              type="button"
              onClick={onOpenAccountingEvents}
              className="h-7 w-7 p-0 text-muted-foreground"
              title="Accounting events — configurable triggers into Oracle GL"
              aria-label="Accounting events"
            >
              <Landmark className="h-3.5 w-3.5" />
            </Button>
          ) : null}

          {/* Who is acting. Every write is recorded against this person,
              and a deal they proposed cannot be signed by them. */}
          {user ? (
            <div className="hidden md:flex items-center gap-2 pl-2 border-l border-border">
              <div className="text-right leading-tight">
                <div className="text-[11px] font-medium text-foreground">
                  {user.display_name}
                </div>
                <div className="text-[10px] text-muted-foreground">
                  {user.roles
                    .map((role) => role.replace(/_/g, " ").toLowerCase())
                    .join(", ") || "no role held"}
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                type="button"
                onClick={() => signOut().then(() => onSignedOut?.())}
                className="h-7 text-xs px-2 text-muted-foreground"
              >
                Sign out
              </Button>
            </div>
          ) : null}
        </div>
      }
    />
  );
}
