"use client";

import { TrendingUp } from "lucide-react";

import { PanelShell } from "@/components/PanelShell";
import { PerformanceTab } from "@/components/panels/PerformanceTab";

/**
 * Performance — promoted from a tab inside Exposure to its own strip
 * entry. Renders the same content (headline stats, AI insights,
 * band/counterparty/monthly breakdowns) but lives on its own so a
 * treasurer can reach it in one click.
 */
export function PerformancePanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  return (
    <PanelShell
      open={open}
      onClose={onClose}
      icon={TrendingUp}
      title="Performance"
      description="What the book has generated to date, by counterparty, by rating band, and month by month — with AI insight on the biggest movers."
    >
      <PerformanceTab open={open} />
    </PanelShell>
  );
}
