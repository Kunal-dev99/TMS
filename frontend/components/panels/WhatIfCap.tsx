"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScenarioResultCard } from "@/components/panels/ScenarioResult";
import {
  CAP_CHANGE_STEPS,
  ThinkingTrace,
} from "@/components/panels/ThinkingTrace";
import { whatIfCapChange, type ScenarioResult } from "@/lib/api";
import { perCent } from "@/lib/format";

/**
 * "What if the concentration cap moved?"
 *
 * The cap is not something a treasurer moves casually, so the section is
 * closed by default and asks for a number rather than offering a slider.
 * Every figure that comes back is a re-run of the concentration check,
 * done in memory; nothing is written.
 */
export function WhatIfCap({ currentCapBp }: { currentCapBp: number }) {
  const [percent, setPercent] = useState(
    ((currentCapBp - 500) / 100).toFixed(0),
  );
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
      const bp = Math.round(Number(percent) * 100);
      const r = await whatIfCapChange(bp);
      setPending(r);
      setNetworkDone(true);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "That was refused.");
      setBusy(false);
    }
  };

  return (
    <section className="mt-4 rounded-lg border border-border bg-surface-2/20 p-3">
      <div className="mb-2 flex items-center gap-1.5">
        <Sparkles className="h-3 w-3 text-primary" aria-hidden />
        <h4 className="text-[10px] font-medium uppercase tracking-wider text-primary">
          What if the concentration cap moved?
        </h4>
      </div>
      <p className="mb-2.5 text-[10px] text-muted-foreground">
        Runs the concentration check against a different cap. The current cap
        is {perCent(currentCapBp)}. Nothing is written; the book stays as it
        is.
      </p>
      <div className="flex items-end gap-2">
        <div className="flex-1 space-y-1">
          <Label className="text-[10px]">New cap (%)</Label>
          <Input
            className="num h-8 text-xs"
            value={percent}
            onChange={(event) => setPercent(event.target.value)}
            placeholder={(currentCapBp / 100).toFixed(0)}
          />
        </div>
        <Button
          type="button"
          size="sm"
          className="h-8 gap-1.5 text-xs"
          disabled={busy || !percent.trim()}
          onClick={ask}
        >
          <Sparkles className="h-3 w-3" aria-hidden />
          {busy ? "Thinking..." : "See what would happen"}
        </Button>
      </div>
      {error ? (
        <p className="mt-2 rounded border border-destructive/40 bg-destructive/10 p-2 text-[10px] text-destructive">
          {error}
        </p>
      ) : null}
      {busy ? (
        <ThinkingTrace
          steps={CAP_CHANGE_STEPS}
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
