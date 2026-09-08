"use client";

import { useEffect, useState } from "react";
import { Landmark, RotateCcw, Save } from "lucide-react";

import { PanelShell } from "@/components/PanelShell";
import { Button } from "@/components/ui/button";
import {
  getAccountingEvents,
  resetAccountingEvents,
  updateAccountingEvents,
  type AccountingEventRule,
  type AccountingEventSettings,
} from "@/lib/api";

/**
 * Accounting events — Anil's Sep-8 ask.
 *
 * The prototype does not post journals from here (Oracle does that);
 * this screen makes the trigger points visible and toggle-able so the
 * demo can answer "which lifecycle stages are accounting events?" with
 * a configured screen instead of code.
 *
 * Every "posts to" and "integration" caption is named against the deep-
 * research report on Fusion Accounting Hub, so a consultant reading
 * the screen hears the correct integration surface.
 */
export function AccountingEventsPanel({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const [settings, setSettings] = useState<AccountingEventSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getAccountingEvents()
      .then((s) => { if (!cancelled) setSettings(s); })
      .catch((e) => { if (!cancelled) setError(String(e.message ?? e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open]);

  const toggle = (stage: string) => {
    if (!settings) return;
    setSettings({
      ...settings,
      rules: settings.rules.map((r) =>
        r.stage === stage ? { ...r, is_event: !r.is_event } : r,
      ),
    });
  };

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await updateAccountingEvents({
        rules: settings.rules,
        target_gl: settings.target_gl,
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
      const s = await resetAccountingEvents();
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
      icon={Landmark}
      title="Accounting events"
      description="Which lifecycle stages fire an accounting event, and where they post. Configurable — not hardcoded."
    >
      {loading || !settings ? (
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
              Destination
            </h3>
            <div className="rounded-lg border border-border bg-surface-2/40 p-4 space-y-3">
              <div>
                <label className="mb-1 block text-[11px] font-medium text-muted-foreground">
                  Post accounting events to
                </label>
                <select
                  value={settings.target_gl}
                  onChange={(e) => setSettings({ ...settings, target_gl: e.target.value })}
                  className="w-full rounded border border-border bg-background px-2.5 py-1.5 text-xs"
                >
                  {settings.supported_targets.map((t) => (
                    <option key={t.key} value={t.key}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-baseline justify-between text-[11px]">
                <span className="text-muted-foreground">Integration</span>
                <span className="font-medium text-foreground">
                  {settings.connector_name}{" "}
                  <span className="text-[9px] uppercase tracking-wider text-primary">first-party</span>
                </span>
              </div>
              <p className="text-[10px] text-muted-foreground">
                The Connector is built into the Treasury Register — no
                Oracle Integration Cloud, no separate middleware SKU. Change
                the destination once here and every enabled event routes
                there.
              </p>
            </div>
          </section>

          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Deal lifecycle
            </h3>
            <div className="space-y-2">
              {settings.rules.map((rule) => (
                <EventRow key={rule.stage} rule={rule} onToggle={() => toggle(rule.stage)} />
              ))}
            </div>
          </section>

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
                {saving ? "Saving…" : "Save catalogue"}
              </Button>
            </div>
          </div>

          <p className="text-[10px] text-muted-foreground">
            Prototype: no journals are actually posted from the Register.
            In production the toggled-on events flow through the
            <span className="font-medium text-foreground"> Treasury Register Connector</span> —
            our first-party integration layer, not Oracle Integration
            Cloud — into whichever destination is selected above (Fusion
            AHCS, Fusion GL, Oracle EBS, or a custom endpoint),
            preserving drill-back to the deal.
          </p>
        </div>
      )}
    </PanelShell>
  );
}

function EventRow({
  rule,
  onToggle,
}: {
  rule: AccountingEventRule;
  onToggle: () => void;
}) {
  return (
    <div
      className={`rounded-lg border p-3 transition-colors ${
        rule.is_event
          ? "border-primary/30 bg-primary/5"
          : "border-border bg-surface-2/30"
      }`}
    >
      <div className="flex items-start gap-3">
        <label className="mt-0.5 flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={rule.is_event}
            onChange={onToggle}
            className="h-4 w-4 accent-[hsl(var(--primary))]"
            aria-label={`Toggle ${rule.stage} as accounting event`}
          />
        </label>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-xs font-semibold uppercase tracking-wider">
              {rule.stage.toLowerCase()}
            </span>
            {rule.is_event ? (
              <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider text-primary">
                accounting event
              </span>
            ) : (
              <span className="text-[10px] text-muted-foreground">
                no journal
              </span>
            )}
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
            {rule.note}
          </p>
          {rule.is_event ? (
            <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
              <div>
                <span className="text-muted-foreground">Event class:</span>{" "}
                <span className="font-medium text-foreground">{rule.event_class}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Event type:</span>{" "}
                <span className="font-medium text-foreground">{rule.event_type}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Cadence:</span>{" "}
                <span className="font-medium text-foreground">{rule.cadence}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Posts to:</span>{" "}
                <span className="font-medium text-foreground">{rule.posts_to}</span>
              </div>
              <div className="col-span-2">
                <span className="text-muted-foreground">Integration:</span>{" "}
                <span className="font-medium text-foreground">{rule.integration}</span>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
