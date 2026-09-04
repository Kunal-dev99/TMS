"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScenarioResultCard } from "@/components/panels/ScenarioResult";
import {
  NOT_ROLLED_STEPS,
  ThinkingTrace,
} from "@/components/panels/ThinkingTrace";
import { whatIfNotRolled, type ScenarioResult } from "@/lib/api";
import { shortDate } from "@/lib/format";
import type { DealDetail } from "@/lib/types";

/**
 * "What if this deal is not rolled at maturity?"
 *
 * A recurring treasury question, put where the answer belongs: alongside
 * the deal itself. The cash lands, the counterparty releases the headroom,
 * the daily income stops. All three are deterministic; the paragraph is
 * the model's reading of them.
 */
export function WhatIfNotRolled({ detail }: { detail: DealDetail }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [pending, setPending] = useState<ScenarioResult | null>(null);
  const [networkDone, setNetworkDone] = useState(false);

  const ask = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    setPending(null);
    setNetworkDone(false);
    try {
      const r = await whatIfNotRolled(detail.deal.id);
      setPending(r);
      setNetworkDone(true);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "That was refused.");
      setBusy(false);
    }
  };

  return (
    <section className="rounded-lg border border-border bg-surface-2/20 p-3">
      <div className="mb-1.5 flex items-center gap-1.5">
        <Sparkles className="h-3 w-3 text-primary" aria-hidden />
        <h3 className="text-[10px] font-medium uppercase tracking-wider text-primary">
          What if this deal is not rolled at maturity?
        </h3>
      </div>
      <p className="mb-2.5 text-[10px] text-muted-foreground">
        Matures {shortDate(detail.deal.maturity_date)}. Runs the arithmetic
        as if the cash lands in the operating account instead of being
        rolled. Nothing is written.
      </p>
      <Button
        type="button"
        size="sm"
        className="h-8 gap-1.5 text-xs"
        disabled={busy}
        onClick={ask}
      >
        <Sparkles className="h-3 w-3" aria-hidden />
        {busy ? "Thinking..." : "See what would happen"}
      </Button>
      {error ? (
        <p className="mt-2 rounded border border-destructive/40 bg-destructive/10 p-2 text-[10px] text-destructive">
          {error}
        </p>
      ) : null}
      {busy ? (
        <ThinkingTrace
          steps={NOT_ROLLED_STEPS}
          finished={networkDone}
          onFinished={() => {
            if (pending) setResult(pending);
            setBusy(false);
          }}
        />
      ) : null}
      {result ? <ScenarioResultCard result={result} /> : null}
    </section>
  );
}
