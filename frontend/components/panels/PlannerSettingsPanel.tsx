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
 * Section 2 — Allocation buckets. A % per rating band (AAA, AA, A, BBB).
 * Must sum to 100 for Save to enable. This IS the investment principle
 * the treasurer declares before deploying: not "which strategy to pick"
 * but "how to spread across risk bands."
 *
 * The planner then produces ONE blended plan that fits those buckets,
 * plus one or two alternatives with different concentration/yield
 * trade-offs.
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

  const bucketTotal = settings
    ? Object.values(settings.buckets).reduce((sum, v) => sum + (v || 0), 0)
    : 0;
  const bucketsValid = bucketTotal === 100;

  const save = async () => {
    if (!settings || !bucketsValid) return;
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
      description="What the treasurer declares before deploying: risk floor, allocation buckets, and concentration rules. Nothing here is hardcoded."
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
            valid={bucketsValid}
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
                disabled={saving || !bucketsValid}
                className="gap-1.5 text-xs"
                title={!bucketsValid ? `Buckets must sum to 100 (currently ${bucketTotal})` : undefined}
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
          Allocation buckets
        </h3>
        <span
          className={`font-mono text-xs ${
            valid ? "text-success" : "text-destructive"
          }`}
        >
          Total: {total}%
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
                <span className="text-xs text-muted-foreground">%</span>
              </div>
            </div>
          ))}
        </div>

        <p className="mt-4 text-[10px] text-muted-foreground">
          Set what share of idle cash goes in each rating band. Must sum
          to 100%. The planner then produces one blended plan that fits
          these buckets — plus a "higher yield" and "tighter
          concentration" variant for comparison.
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
