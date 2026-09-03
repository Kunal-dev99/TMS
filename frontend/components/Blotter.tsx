"use client";

import type { DealSummary } from "@/lib/types";
import { dealRate, sterling } from "@/lib/format";
import { PageSection } from "@/components/common/PageSection";
import { FileText, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * The blotter. Model 2, at a glance.
 *
 * The measured column carries the measurement basis underneath it, so a
 * forward is never read as its notional. The flag is a pill only when
 * something needs attention, so a pill on a row always means something.
 *
 * Clicking a row opens the deal lifecycle panel.
 */
export function Blotter({
  deals,
  onSelect,
}: {
  deals: DealSummary[];
  onSelect?: (dealId: string) => void;
}) {
  return (
    <PageSection
      icon={FileText}
      title="Deal Blotter"
      description="Live positions and active deals across the book"
      accent="primary"
    >
      {deals.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground">
          Nothing on the book yet.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left border-collapse">
            <thead>
              <tr className="border-b border-border text-[10px] uppercase font-semibold text-muted-foreground tracking-wider">
                <th className="py-2.5 px-3">Counterparty</th>
                <th className="py-2.5 px-3">Instrument</th>
                <th className="py-2.5 px-3 text-right num">Principal</th>
                <th className="py-2.5 px-3 text-right num">Measured</th>
                <th className="py-2.5 px-3">Stage</th>
                <th className="py-2.5 px-3">Flag</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {deals.map((deal) => (
                <tr
                  key={deal.id}
                  onClick={() => onSelect?.(deal.id)}
                  className="hover:bg-surface-2/60 transition-colors cursor-pointer group"
                >
                  <td className="py-3 px-3">
                    <div className="font-semibold text-foreground group-hover:text-primary transition-colors">
                      {deal.counterparty_name}
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-0.5">
                      {dealRate(deal.rate_bp, deal.instrument)} • {deal.tenor_months} months
                    </div>
                  </td>
                  <td className="py-3 px-3 capitalize text-muted-foreground font-medium">
                    {deal.instrument.replace("_", " ").toLowerCase()}
                  </td>
                  <td className="py-3 px-3 text-right num">
                    <div className="font-medium text-foreground">{sterling(deal.principal_pence)}</div>
                    {deal.currency !== "GBP" ? (
                      <div className="text-[10px] text-muted-foreground">notional {deal.currency}</div>
                    ) : null}
                  </td>
                  <td className="py-3 px-3 text-right num">
                    <div className="font-medium text-foreground">{sterling(deal.measured_pence)}</div>
                    <div className="text-[10px] text-muted-foreground">{deal.measurement_basis}</div>
                  </td>
                  <td className="py-3 px-3">
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium border border-border bg-surface-2 text-foreground">
                      {deal.stage}
                    </span>
                  </td>
                  <td className="py-3 px-3">
                    {deal.flag ? (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold border status-failed">
                        {deal.flag}
                      </span>
                    ) : (
                      <span className="text-muted-foreground/40">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageSection>
  );
}
