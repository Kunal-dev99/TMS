"use client";

import { useEffect, useState } from "react";
import { RotateCcw, Save, ShieldCheck } from "lucide-react";

import { PanelShell } from "@/components/PanelShell";
import { Button } from "@/components/ui/button";
import {
  getSystemPolicy,
  resetRateCurve,
  updateSystemPolicy,
  type SystemPolicyBand,
  type SystemPolicyView,
} from "@/lib/api";
import { sterling } from "@/lib/format";

/**
 * System policy - the treasurer edits the numbers behind the six-check
 * gate. Concentration cap, enforcement mode, rating bands (max limit +
 * max tenor per band), and the rate curve.
 */
export function SystemPolicyPanel({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const [view, setView] = useState<SystemPolicyView | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true); setError(null);
    getSystemPolicy()
      .then((v) => { if (!cancelled) setView(v); })
      .catch((e) => { if (!cancelled) setError(String(e.message ?? e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open]);

  const patchPolicy = (delta: Partial<SystemPolicyView["policy"]>) => {
    if (!view) return;
    setView({ ...view, policy: { ...view.policy, ...delta } });
  };

  const patchBand = (rating: string, delta: Partial<SystemPolicyBand>) => {
    if (!view) return;
    setView({
      ...view,
      rating_bands: view.rating_bands.map((b) =>
        b.rating === rating ? { ...b, ...delta } : b,
      ),
    });
  };

  const patchRate = (rating: string, tenor: number, bp: number) => {
    if (!view) return;
    const curve = { ...view.rate_curve };
    const row = { ...(curve[rating] ?? {}) };
    row[String(tenor)] = bp;
    curve[rating] = row;
    setView({ ...view, rate_curve: curve });
  };

  const save = async () => {
    if (!view) return;
    setSaving(true); setError(null);
    try {
      const saved = await updateSystemPolicy({
        policy: view.policy,
        rating_bands: view.rating_bands.map((b) => ({
          rating: b.rating,
          max_limit_pence: b.max_limit_pence,
          max_tenor_months: b.max_tenor_months,
        })),
        rate_curve: view.rate_curve,
      });
      setView(saved);
      onSaved?.();
      onClose();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally { setSaving(false); }
  };

  const doResetCurve = async () => {
    setSaving(true); setError(null);
    try {
      const saved = await resetRateCurve();
      setView(saved);
      onSaved?.();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally { setSaving(false); }
  };

  return (
    <PanelShell
      open={open}
      onClose={onClose}
      icon={ShieldCheck}
      title="System policy"
      description="The numbers behind the six-check gate. Concentration cap, enforcement, rating bands, rate curve. All editable."
    >
      {loading || !view ? (
        <div className="py-8 text-center text-xs text-muted-foreground">Loading…</div>
      ) : (
        <div className="space-y-6">
          {error ? (
            <div className="rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error}
            </div>
          ) : null}

          {/* Section 1 - Concentration cap + enforcement */}
          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Policy
            </h3>
            <div className="space-y-4 rounded border border-border bg-surface-2/40 p-4">
              <div>
                <div className="mb-1 flex items-baseline justify-between">
                  <label className="text-xs font-medium">Concentration cap</label>
                  <span className="font-mono text-xs text-primary">
                    {(view.policy.concentration_cap_bp / 100).toFixed(0)}% of portfolio
                  </span>
                </div>
                <input
                  type="range"
                  min={500}
                  max={10000}
                  step={100}
                  value={view.policy.concentration_cap_bp}
                  onChange={(e) => patchPolicy({ concentration_cap_bp: Number(e.target.value) })}
                  className="w-full accent-[hsl(var(--primary))]"
                />
                <p className="mt-1 text-[10px] text-muted-foreground">
                  Any placement that would tip the top-N group over this cap is refused. Source: <code>policy_versions</code>.
                </p>
              </div>

              <div>
                <div className="mb-1 flex items-baseline justify-between">
                  <label className="text-xs font-medium">Enforcement mode</label>
                </div>
                <select
                  value={view.policy.enforcement}
                  onChange={(e) => patchPolicy({ enforcement: e.target.value as "HARD_BLOCK" | "WARN_WITH_OVERRIDE" })}
                  className="w-full rounded border border-border bg-background px-2.5 py-1.5 text-xs"
                >
                  <option value="WARN_WITH_OVERRIDE">Warn with override (proceed with a reason)</option>
                  <option value="HARD_BLOCK">Hard block (refuse the deal)</option>
                </select>
                <p className="mt-1 text-[10px] text-muted-foreground">
                  How the six-check gate behaves when a check fails.
                </p>
              </div>
            </div>
          </section>

          {/* Section 2 - Rating bands */}
          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Rating bands
            </h3>
            <div className="rounded border border-border bg-surface-2/40 p-3">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    <th className="pb-2 text-left">Rating</th>
                    <th className="pb-2 text-right">Max limit per name</th>
                    <th className="pb-2 text-right">Max tenor (months)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {view.rating_bands.map((b) => (
                    <tr key={b.rating}>
                      <td className="py-1.5 font-mono font-semibold">{b.rating}</td>
                      <td className="py-1.5 text-right">
                        <div className="inline-flex items-center gap-1">
                          <span className="text-muted-foreground">£</span>
                          <input
                            type="number"
                            min={0}
                            step={500000}
                            value={Math.round(b.max_limit_pence / 100)}
                            onChange={(e) => patchBand(b.rating, {
                              max_limit_pence: Math.max(0, Number(e.target.value)) * 100,
                            })}
                            className="w-28 rounded border border-border bg-background px-1.5 py-0.5 text-right font-mono text-xs"
                          />
                        </div>
                      </td>
                      <td className="py-1.5 text-right">
                        <input
                          type="number"
                          min={0}
                          max={60}
                          step={1}
                          value={b.max_tenor_months}
                          onChange={(e) => patchBand(b.rating, {
                            max_tenor_months: Math.max(0, Math.min(60, Number(e.target.value))),
                          })}
                          className="w-16 rounded border border-border bg-background px-1.5 py-0.5 text-right font-mono text-xs"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-[10px] text-muted-foreground">
                A tighter band cuts every deal against a counterparty at that rating. Source: <code>rating_band</code> table.
              </p>
            </div>
          </section>

          {/* Section 3 - Rate curve */}
          <section>
            <h3 className="mb-3 flex items-baseline justify-between text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <span>Rate curve</span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={doResetCurve}
                disabled={saving}
                className="h-6 gap-1 text-[10px] text-muted-foreground normal-case"
              >
                <RotateCcw className="h-2.5 w-2.5" />
                Reset curve
              </Button>
            </h3>
            <div className="rounded border border-border bg-surface-2/40 p-3">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    <th className="pb-2 text-left">Rating</th>
                    {view.curve_tenors.map((t) => (
                      <th key={t} className="pb-2 text-right">{t}m (bp)</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {view.rating_ladder.slice().reverse().map((r) => (
                    <tr key={r}>
                      <td className="py-1.5 font-mono font-semibold">{r}</td>
                      {view.curve_tenors.map((t) => (
                        <td key={t} className="py-1.5 text-right">
                          <input
                            type="number"
                            min={0}
                            max={2000}
                            step={5}
                            value={view.rate_curve[r]?.[String(t)] ?? 0}
                            onChange={(e) => patchRate(r, t, Math.max(0, Math.min(2000, Number(e.target.value))))}
                            className="w-16 rounded border border-border bg-background px-1.5 py-0.5 text-right font-mono text-xs"
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-[10px] text-muted-foreground">
                Rates in basis points. 100 bp = 1%. Source: Bloomberg BGN in production; internal curve for the prototype.
              </p>
            </div>
          </section>

          {/* Save row */}
          <div className="flex items-center justify-between border-t border-border pt-4">
            <p className="text-[10px] italic text-muted-foreground">
              Prototype: updates in place. Production would supersede the current policy version.
            </p>
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
                disabled={saving}
                className="gap-1.5 text-xs"
              >
                <Save className="h-3 w-3" />
                {saving ? "Saving…" : "Save policy"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </PanelShell>
  );
}
