"use client";

import { BookOpen, Cog, Landmark, Settings2, ShieldCheck, type LucideIcon } from "lucide-react";

import { PanelShell } from "@/components/PanelShell";

/**
 * Control — the hub for LOVs and config the treasurer edits before
 * the trading day. Ratings & Policy remains its own strip entry
 * because it changes on its own cadence (rating actions, cap reviews).
 *
 * Each tile opens the matching drawer. Future LOV screens land here
 * without more work in the header.
 */
export function ControlPanel({
  open,
  onClose,
  onOpenPrinciples,
  onOpenAccountingEvents,
  onOpenSystemPolicy,
  onOpenReferenceSources,
}: {
  open: boolean;
  onClose: () => void;
  onOpenPrinciples: () => void;
  onOpenAccountingEvents: () => void;
  onOpenSystemPolicy: () => void;
  onOpenReferenceSources: () => void;
}) {
  return (
    <PanelShell
      open={open}
      onClose={onClose}
      icon={Cog}
      title="Control"
      description="Configurable LOVs and policy the treasurer edits before the day. Everything here is config, not hardcoded."
    >
      <div className="space-y-3">
        <ControlTile
          icon={Settings2}
          label="Investment principles"
          description="Allocation buckets by rating, risk floor, tenor cap, and per-name concentration. The planner reads this on every run."
          onClick={() => {
            onClose();
            onOpenPrinciples();
          }}
        />
        <ControlTile
          icon={Landmark}
          label="Accounting events"
          description="Which lifecycle stages fire an accounting event, and where the Treasury Register Connector posts them (Fusion AHCS, Fusion GL, Oracle EBS, custom REST)."
          onClick={() => {
            onClose();
            onOpenAccountingEvents();
          }}
        />
        <ControlTile
          icon={ShieldCheck}
          label="System policy"
          description="The numbers behind the six-check gate. Concentration cap, enforcement mode, rating bands (max limit + max tenor per rating), and the rate curve."
          onClick={() => {
            onClose();
            onOpenSystemPolicy();
          }}
        />
        <ControlTile
          icon={BookOpen}
          label="Reference & sources"
          description="Every field on the screen: where the value comes from, whether the treasurer can edit it, and where. The cheat sheet."
          onClick={() => {
            onClose();
            onOpenReferenceSources();
          }}
        />

        <div className="rounded-lg border border-dashed border-border bg-surface-2/30 p-3 text-center">
          <p className="text-[10.5px] text-muted-foreground">
            More LOVs land here as they are wired: currency LOVs,
            counterparty onboarding thresholds, calendar / holiday
            tables, banking-day rules.
          </p>
        </div>
      </div>
    </PanelShell>
  );
}

function ControlTile({
  icon: Icon,
  label,
  description,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left rounded-lg border border-border bg-surface-2/40 p-3 transition-colors hover:border-primary/40 hover:bg-primary/[.04]"
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/15 text-primary">
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <div className="text-xs font-semibold text-foreground">{label}</div>
          <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
            {description}
          </p>
        </div>
      </div>
    </button>
  );
}
