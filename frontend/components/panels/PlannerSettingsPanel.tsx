"use client";

import { useEffect, useState } from "react";
import { RotateCcw, Save, Settings2 } from "lucide-react";

import { PanelShell } from "@/components/PanelShell";
import { Button } from "@/components/ui/button";
import {
  getPlannerSettings,
  resetPlannerSettings,
  updatePlannerSettings,
  type PlannerSettings,
} from "@/lib/api";

/**
 * The Investment Principles panel — Anil's Sep-8 "everything config-driven"
 * ask made visible.
 *
 * Section 1 — Parameters. Sliders for min rating, tenor ceiling, per-name
 * cap, and group concentration cap.
 *
 * Section 2 — Rating caps. A MAX % per rating band (AAA, AA, A, BBB).
 * Anil's Sep-9 feedback: "pick a limit of each bucket ie 80% AAA and
 * 10% AA and then have the AI calculate the best spread to get maximum
 * income." Caps are upper limits, not targets - they don't need to sum
 * to 100. The planner picks the highest-yielding spread that fits
 * inside them.
 */
export function PlannerSettingsPanel({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [settings, setSettings] = useState<PlannerSettings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getPlannerSettings()
      .then((s) => { if (!cancelled) setSettings(s); })
      .catch((e) => { if (!cancelled) setError(String(e.message ?? e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open]);

  const patch = (delta: Partial<PlannerSettings>) => {
    setSettings((prev) => (prev ? { ...prev, ...delta } : prev));
  };

  const setBucket = (band: string, pct: number) => {
    if (!settings) return;
    patch({ buckets: { ...settings.buckets, [band]: pct } });
  };

  // Caps do not need to sum to 100 — that was the old "target" model.
  // Now buckets are ceilings and any non-negative sum is valid.
  const bucketTotal = settings
    ? Object.values(settings.buckets).reduce((sum, v) => sum + (v || 0), 0)
    : 0;
  const anyCapSet = bucketTotal > 0;

  const save = async () => {
    if (!settings || !anyCapSet) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await updatePlannerSettings({
        min_rating: settings.min_rating,
        max_tenor_months: settings.max_tenor_months,
        per_name_cap_pct: settings.per_name_cap_pct,
        group_concentration_cap_pct: settings.group_concentration_cap_pct,
        buckets: settings.buckets,
      });
      setSettings(saved);
      onSaved?.();
      onClose();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSaving(false);
    }
  };

  const resetDefaults = async () => {
    setSaving(true);
    setError(null);
    try {
      const s = await resetPlannerSettings();
      setSettings(s);
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
      icon={Settings2}
      title="Investment principles"
      description="Set the risk floor, rating caps (upper limits per band), and concentration rules. The planner picks the best spread inside them to maximise income."
    >
      {loading || !settings ? (
        <div className="py-8 text-center text-xs text-muted-foreground">Loading…</div>
      ) : (
        <div className="space-y-6">
          {error ? (
            <div className="rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error}
            </div>
          ) : null}

          <Parameters
            settings={settings}
            onChange={(delta) => patch(delta)}
          />

          <Buckets
            settings={settings}
            total={bucketTotal}
            valid={anyCapSet}
            onChange={setBucket}
          />

          <div className="flex items-center justify-between border-t border-border pt-4">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={resetDefaults}
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
                disabled={saving || !anyCapSet}
                className="gap-1.5 text-xs"
                title={!anyCapSet ? "Set at least one rating cap above 0%" : undefined}
              >
                <Save className="h-3 w-3" />
                {saving ? "Saving…" : "Save principles"}
              </Button>
            </div>
          </div>

          <p className="text-[10px] text-muted-foreground">
            Prototype: principles live in memory for the session. Production
            would persist to <code>policy_versions</code> with an approval
            flow and a periodic review cycle (quarterly, per Anil's spec).
          </p>
        </div>
      )}
    </PanelShell>
  );
}

// ---------------------------------------------------------------- sections

function Parameters({
  settings,
  onChange,
}: {
  settings: PlannerSettings;
  onChange: (delta: Partial<PlannerSettings>) => void;
}) {
  return (
    <section>
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Parameters
      </h3>
      <div className="space-y-4 rounded border border-border bg-surface-2/40 p-4">
        <RatingSelect
          value={settings.min_rating}
          ladder={settings.rating_ladder}
          onChange={(v) => onChange({ min_rating: v })}
        />
        <Slider
          label="Max tenor"
          value={settings.max_tenor_months}
          min={3}
          max={24}
          step={1}
          suffix=" months"
          onChange={(v) => onChange({ max_tenor_months: v })}
        />
        <Slider
          label="Per-name cap"
          value={settings.per_name_cap_pct}
          min={10}
          max={100}
          step={5}
          suffix="% of idle cash"
          onChange={(v) => onChange({ per_name_cap_pct: v })}
        />
        <Slider
          label="Group concentration cap"
          value={settings.group_concentration_cap_pct}
          min={5}
          max={100}
          step={5}
          suffix="% of portfolio"
          onChange={(v) => onChange({ group_concentration_cap_pct: v })}
        />
      </div>
    </section>
  );
}

function Buckets({
  settings,
  total,
  valid,
  onChange,
}: {
  settings: PlannerSettings;
  total: number;
  valid: boolean;
  onChange: (band: string, pct: number) => void;
}) {
  const bandColor: Record<string, string> = {
    AAA: "hsl(var(--success))",
    AA:  "hsl(var(--primary))",
    A:   "hsl(var(--warning))",
    BBB: "hsl(var(--muted-foreground))",
  };
  return (
    <section>
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Rating caps
        </h3>
        <span
          className={`font-mono text-xs ${
            total >= 100
              ? "text-success"
              : total > 0
                ? "text-warning"
                : "text-destructive"
          }`}
          title={
            total < 100
              ? `Combined ceiling is ${total}%; up to ${100 - total}% of cash may stay uninvested.`
              : `Combined ceiling covers the full ${total}%.`
          }
        >
          Combined ceiling: {total}%
        </span>
      </div>
      <div className="rounded border border-border bg-surface-2/40 p-4">
        {/* Stacked bar preview */}
        <div className="mb-4 flex h-2 w-full overflow-hidden rounded-full bg-surface-2">
          {settings.rating_bands.map((band) => {
            const pct = settings.buckets[band] || 0;
            if (pct <= 0) return null;
            return (
              <div
                key={band}
                style={{
                  width: `${pct}%`,
                  background: bandColor[band] ?? "hsl(var(--muted-foreground))",
                }}
                title={`${band}: ${pct}%`}
              />
            );
          })}
        </div>

        <div className="space-y-3">
          {settings.rating_bands.map((band) => (
            <div key={band} className="grid grid-cols-[60px_1fr_70px] items-center gap-3">
              <span className="flex items-center gap-2 text-xs font-medium">
                <span
                  className="h-2 w-2 rounded-full shrink-0"
                  style={{ background: bandColor[band] ?? "hsl(var(--muted-foreground))" }}
                />
                {band}
              </span>
              <input
                type="range"
                min={0}
                max={100}
                step={5}
                value={settings.buckets[band] || 0}
                onChange={(e) => onChange(band, Number(e.target.value))}
                className="w-full accent-[hsl(var(--primary))]"
              />
              <div className="flex items-center gap-1">
                <input
                  type="number"
                  min={0}
                  max={100}
                  step={5}
                  value={settings.buckets[band] || 0}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    onChange(band, Number.isFinite(v) ? Math.max(0, Math.min(100, v)) : 0);
                  }}
                  className="w-12 rounded border border-border bg-background px-1 py-0.5 text-right font-mono text-xs"
                />
                <span className="text-xs text-muted-foreground">% max</span>
              </div>
            </div>
          ))}
        </div>

        <p className="mt-4 text-[10px] text-muted-foreground">
          Each number is a <b>ceiling</b>, not a target. The planner
          picks the highest-yielding spread it can find inside these
          caps. Set 80% AAA + 10% AA and the planner will use up to
          those - but never more. If your caps sum to less than 100%,
          any leftover cash stays uninvested until the caps rise.
        </p>
      </div>
    </section>
  );
}

function RatingSelect({
  value,
  ladder,
  onChange,
}: {
  value: string;
  ladder: string[];
  onChange: (v: string) => void;
}) {
  const idx = Math.max(0, ladder.indexOf(value));
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <label className="text-xs font-medium">Min rating</label>
        <span className="font-mono text-xs text-primary">{ladder[idx] ?? value}</span>
      </div>
      <input
        type="range"
        min={0}
        max={ladder.length - 1}
        step={1}
        value={idx}
        onChange={(e) => onChange(ladder[Number(e.target.value)])}
        className="w-full accent-[hsl(var(--primary))]"
      />
      <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
        <span>{ladder[0]}</span>
        <span>{ladder[ladder.length - 1]}</span>
      </div>
    </div>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  suffix,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix: string;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <label className="text-xs font-medium">{label}</label>
        <span className="font-mono text-xs text-primary">
          {value}
          {suffix}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-[hsl(var(--primary))]"
      />
      <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
        <span>
          {min}
          {suffix}
        </span>
        <span>
          {max}
          {suffix}
        </span>
      </div>
    </div>
  );
}
