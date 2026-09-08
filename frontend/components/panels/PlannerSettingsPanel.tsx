"use client";

import { useEffect, useState } from "react";
import { Plus, RotateCcw, Save, Settings2, Trash2 } from "lucide-react";

import { PanelShell } from "@/components/PanelShell";
import { Button } from "@/components/ui/button";
import {
  getPlannerSettings,
  resetPlannerSettings,
  updatePlannerSettings,
  type CustomStrategy,
  type PlannerSettings,
} from "@/lib/api";

/**
 * The Planner Policy panel — Anil's "everything config-driven, nothing
 * hardwired" ask made visible.
 *
 * Sliders drive the rating floor, tenor ceiling, per-name cap, and group
 * concentration cap. A checkbox per built-in strategy toggles it. A form
 * at the bottom adds custom strategies (each is a named variant of one
 * of the four archetypes with rating/tenor overrides). Save PUTs the
 * whole thing; the next planner run reads it.
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

  const toggleStrategy = (kind: string) => {
    if (!settings) return;
    const next = settings.enabled_strategies.includes(kind)
      ? settings.enabled_strategies.filter((k) => k !== kind)
      : [...settings.enabled_strategies, kind];
    patch({ enabled_strategies: next });
  };

  const addCustom = (custom: CustomStrategy) => {
    if (!settings) return;
    patch({ custom_strategies: [...settings.custom_strategies, custom] });
  };

  const removeCustom = (kind: string) => {
    if (!settings) return;
    patch({
      custom_strategies: settings.custom_strategies.filter((c) => c.kind !== kind),
    });
  };

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await updatePlannerSettings({
        min_rating: settings.min_rating,
        max_tenor_months: settings.max_tenor_months,
        per_name_cap_pct: settings.per_name_cap_pct,
        group_concentration_cap_pct: settings.group_concentration_cap_pct,
        enabled_strategies: settings.enabled_strategies,
        custom_strategies: settings.custom_strategies,
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
      title="Planner policy"
      description="Sliders and strategies drive the cash-deployment planner. Nothing here is hardcoded."
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

          <Strategies
            settings={settings}
            onToggle={toggleStrategy}
          />

          <CustomStrategies
            settings={settings}
            onAdd={addCustom}
            onRemove={removeCustom}
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
                disabled={saving}
                className="gap-1.5 text-xs"
              >
                <Save className="h-3 w-3" />
                {saving ? "Saving…" : "Save policy"}
              </Button>
            </div>
          </div>

          <p className="text-[10px] text-muted-foreground">
            Prototype: settings live in memory for the session. Production
            would persist to <code>policy_versions</code> with an approval
            flow.
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

function Strategies({
  settings,
  onToggle,
}: {
  settings: PlannerSettings;
  onToggle: (kind: string) => void;
}) {
  return (
    <section>
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Strategies to show
      </h3>
      <div className="divide-y divide-border rounded border border-border bg-surface-2/40">
        {settings.builtin_strategies.map((s) => {
          const enabled = settings.enabled_strategies.includes(s.kind);
          return (
            <label
              key={s.kind}
              className="flex items-center gap-3 p-3 cursor-pointer hover:bg-surface-2/70"
            >
              <input
                type="checkbox"
                checked={enabled}
                onChange={() => onToggle(s.kind)}
                className="h-4 w-4 accent-[hsl(var(--primary))]"
              />
              <div className="min-w-0 flex-1">
                <div className="text-xs font-medium">{s.label}</div>
                <div className="text-[11px] text-muted-foreground truncate">
                  {s.tagline}
                </div>
              </div>
              <span className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
                {s.kind.toLowerCase().replaceAll("_", "-")}
              </span>
            </label>
          );
        })}
      </div>
      <p className="mt-2 text-[10px] text-muted-foreground">
        Tick more than one — the planner shows every enabled strategy
        side-by-side, so the treasurer can compare them on one screen.
      </p>
    </section>
  );
}

function CustomStrategies({
  settings,
  onAdd,
  onRemove,
}: {
  settings: PlannerSettings;
  onAdd: (custom: CustomStrategy) => void;
  onRemove: (kind: string) => void;
}) {
  const [showForm, setShowForm] = useState(false);
  const [label, setLabel] = useState("");
  const [basedOn, setBasedOn] = useState(settings.builtin_strategies[0]?.kind ?? "MAX_YIELD");
  const [minRating, setMinRating] = useState("");
  const [maxTenor, setMaxTenor] = useState<string>("");

  const submit = () => {
    if (!label.trim()) return;
    const kind = "CUSTOM_" + label.trim().toUpperCase().replace(/[^A-Z0-9]+/g, "_");
    onAdd({
      kind,
      label: label.trim(),
      tagline: "",
      based_on: basedOn,
      min_rating: minRating,
      max_tenor_months: maxTenor ? Number(maxTenor) : 0,
    });
    setLabel("");
    setMinRating("");
    setMaxTenor("");
    setShowForm(false);
  };

  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Custom strategies
        </h3>
        {!showForm ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setShowForm(true)}
            className="gap-1 text-xs text-primary"
          >
            <Plus className="h-3 w-3" />
            Add strategy
          </Button>
        ) : null}
      </div>

      {settings.custom_strategies.length === 0 && !showForm ? (
        <div className="rounded border border-dashed border-border bg-surface-2/30 p-4 text-center text-[11px] text-muted-foreground">
          None yet. Add a named variant of an existing strategy.
        </div>
      ) : null}

      {settings.custom_strategies.length > 0 ? (
        <div className="mb-3 divide-y divide-border rounded border border-border bg-surface-2/40">
          {settings.custom_strategies.map((c) => (
            <div key={c.kind} className="flex items-center gap-3 p-3">
              <div className="min-w-0 flex-1">
                <div className="text-xs font-medium">{c.label}</div>
                <div className="text-[11px] text-muted-foreground truncate">
                  Based on {c.based_on.toLowerCase().replaceAll("_", " ")}
                  {c.min_rating ? ` · ≥ ${c.min_rating}` : ""}
                  {c.max_tenor_months ? ` · ≤ ${c.max_tenor_months}m` : ""}
                </div>
              </div>
              <button
                type="button"
                onClick={() => onRemove(c.kind)}
                aria-label={`Remove ${c.label}`}
                className="rounded p-1 text-muted-foreground hover:bg-surface-2 hover:text-destructive"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      ) : null}

      {showForm ? (
        <div className="space-y-3 rounded border border-primary/30 bg-primary/5 p-4">
          <div>
            <label className="mb-1 block text-[11px] font-medium text-muted-foreground">
              Name
            </label>
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. UK banks only"
              className="w-full rounded border border-border bg-background px-2.5 py-1.5 text-xs"
            />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="mb-1 block text-[11px] font-medium text-muted-foreground">
                Based on
              </label>
              <select
                value={basedOn}
                onChange={(e) => setBasedOn(e.target.value)}
                className="w-full rounded border border-border bg-background px-2 py-1.5 text-xs"
              >
                {settings.builtin_strategies.map((s) => (
                  <option key={s.kind} value={s.kind}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-muted-foreground">
                Min rating
              </label>
              <select
                value={minRating}
                onChange={(e) => setMinRating(e.target.value)}
                className="w-full rounded border border-border bg-background px-2 py-1.5 text-xs"
              >
                <option value="">(any)</option>
                {settings.rating_ladder.slice().reverse().map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-muted-foreground">
                Max tenor
              </label>
              <select
                value={maxTenor}
                onChange={(e) => setMaxTenor(e.target.value)}
                className="w-full rounded border border-border bg-background px-2 py-1.5 text-xs"
              >
                <option value="">(any)</option>
                {[3, 6, 9, 12, 18, 24].map((m) => (
                  <option key={m} value={m}>{m} months</option>
                ))}
              </select>
            </div>
          </div>
          <div className="flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => { setShowForm(false); setLabel(""); }}
              className="text-xs"
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={submit}
              disabled={!label.trim()}
              className="text-xs"
            >
              Add
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
