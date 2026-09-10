"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowLeftRight, RotateCcw, Save } from "lucide-react";

import { PanelShell } from "@/components/PanelShell";
import { Button } from "@/components/ui/button";
import { getFxPolicy, putFxPolicy, type FxPolicyTarget } from "@/lib/api";

/**
 * FX policy panel — the CurrencyCoverTarget editor from Anil's ask.
 *
 * Per currency: one slider for target hedge ratio (%). The panel reads
 * the current investment policy version, lets the treasurer tweak the
 * targets, and PUTs them back — the Hedging dashboard's gap arithmetic
 * updates immediately on the next open.
 *
 * Prototype note: writes in place rather than superseding the policy
 * version. Enough for a demo of "raise USD from 75% to 90%, watch the
 * gap grow." Production would create a new policy version.
 */
export function FxPolicyPanel({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const [targets, setTargets] = useState<FxPolicyTarget[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDirty(false);
    getFxPolicy()
      .then((p) => {
        if (cancelled) return;
        // Ensure the three demo currencies are always present as rows
        // (even at 0%) so the treasurer can add a new target with the
        // slider rather than through a separate "add" flow.
        const known = new Set(p.targets.map((t) => t.currency.toUpperCase()));
        const merged = [...p.targets];
        for (const ccy of ["EUR", "USD", "CHF"]) {
          if (!known.has(ccy)) {
            merged.push({ currency: ccy, target_cover_bp: 0, horizon_days: 180 });
          }
        }
        merged.sort((a, b) => a.currency.localeCompare(b.currency));
        setTargets(merged);
      })
      .catch((e) => !cancelled && setError(String(e.message ?? e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [open]);

  const setTargetPct = (currency: string, pct: number) => {
    if (!targets) return;
    setDirty(true);
    setTargets(
      targets.map((t) =>
        t.currency === currency
          ? { ...t, target_cover_bp: Math.max(0, Math.min(100, pct)) * 100 }
          : t,
      ),
    );
  };

  const setHorizon = (currency: string, days: number) => {
    if (!targets) return;
    setDirty(true);
    setTargets(
      targets.map((t) =>
        t.currency === currency
          ? { ...t, horizon_days: Math.max(30, Math.min(365, days)) }
          : t,
      ),
    );
  };

  const save = async () => {
    if (!targets) return;
    setSaving(true);
    setError(null);
    try {
      await putFxPolicy(targets);
      onSaved?.();
      onClose();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    setSaving(true);
    setError(null);
    try {
      const p = await putFxPolicy([
        { currency: "EUR", target_cover_bp: 8000, horizon_days: 180 },
        { currency: "USD", target_cover_bp: 7500, horizon_days: 180 },
        { currency: "CHF", target_cover_bp: 6000, horizon_days: 180 },
      ]);
      setTargets(p.targets);
      setDirty(false);
      onSaved?.();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <PanelShell
      open={open}
      onClose={onClose}
      icon={ArrowLeftRight}
      title="FX hedge policy"
      description="How much of each foreign-currency exposure the treasury policy requires to be hedged. The Hedging panel reads these targets to compute the gap it shows."
    >
      {loading || !targets ? (
        <div className="py-8 text-center text-xs text-muted-foreground">Loading…</div>
      ) : (
        <div className="space-y-5">
          {error ? (
            <div className="rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error}
            </div>
          ) : null}

          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Per-currency target hedge ratio
            </h3>
            <div className="space-y-4 rounded border border-border bg-surface-2/40 p-4">
              {targets.map((t) => (
                <TargetRow
                  key={t.currency}
                  target={t}
                  onPct={(pct) => setTargetPct(t.currency, pct)}
                  onDays={(d) => setHorizon(t.currency, d)}
                />
              ))}
            </div>
            <p className="mt-3 text-[10px] leading-relaxed text-muted-foreground">
              The panel shows <b>gap = forecast × target − hedged</b>. Set a
              target to 0% to remove policy pressure on that currency. Horizon
              controls how far out the target applies (default 180 days).
            </p>
          </section>

          <div className="flex items-center justify-between border-t border-border pt-4">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={reset}
              disabled={saving}
              className="gap-1.5 text-xs text-muted-foreground"
            >
              <RotateCcw className="h-3 w-3" />
              Reset to defaults
            </Button>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={onClose}
                disabled={saving}
                className="text-xs"
              >
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={save}
                disabled={saving || !dirty}
                className="gap-1.5 text-xs"
              >
                <Save className="h-3 w-3" />
                {saving ? "Saving…" : "Save policy"}
              </Button>
            </div>
          </div>

          <p className="text-[10px] text-muted-foreground">
            Prototype: writes in place on the active policy version.
            Production would supersede the policy so historic gap figures
            re-derive against the target that was in force at the time.
          </p>
        </div>
      )}
    </PanelShell>
  );
}

// ------------------------------------------------------------- row

function TargetRow({
  target,
  onPct,
  onDays,
}: {
  target: FxPolicyTarget;
  onPct: (pct: number) => void;
  onDays: (days: number) => void;
}) {
  const pct = Math.round(target.target_cover_bp / 100);
  return (
    <div className="grid grid-cols-[60px_1fr_70px_90px] items-center gap-3">
      <span className="text-xs font-semibold">{target.currency}</span>
      <input
        type="range"
        min={0}
        max={100}
        step={5}
        value={pct}
        onChange={(e) => onPct(Number(e.target.value))}
        className="w-full accent-[hsl(var(--primary))]"
      />
      <div className="flex items-center gap-1">
        <input
          type="number"
          min={0}
          max={100}
          step={5}
          value={pct}
          onChange={(e) => onPct(Number(e.target.value) || 0)}
          className="w-12 rounded border border-border bg-background px-1 py-0.5 text-right font-mono text-xs"
        />
        <span className="text-xs text-muted-foreground">%</span>
      </div>
      <div className="flex items-center gap-1">
        <input
          type="number"
          min={30}
          max={365}
          step={30}
          value={target.horizon_days}
          onChange={(e) => onDays(Number(e.target.value) || 180)}
          className="w-14 rounded border border-border bg-background px-1 py-0.5 text-right font-mono text-xs"
        />
        <span className="text-xs text-muted-foreground">d</span>
      </div>
    </div>
  );
}
