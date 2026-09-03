"use client";

import type { BookRow } from "@/lib/types";
import {
  headroomBand,
  months,
  sterling,
  utilisationWidth,
} from "@/lib/format";
import { PageSection } from "@/components/common/PageSection";
import { Building2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * The book. Model 1, the state of the world.
 *
 * Each row carries its group name and group utilisation underneath the
 * counterparty name, so a name that looks free at entity level is still
 * visibly constrained by its group. Nothing else on the screen connects two
 * legal entities in the same credit.
 *
 * Every figure here came from the state call. The client does not work out
 * headroom, utilisation or a group total.
 */
export function Book({
  rows,
  portfolioTotalPence,
  uninvestedCashPence,
  onSelect,
  action,
}: {
  rows: BookRow[];
  portfolioTotalPence: number;
  uninvestedCashPence: number;
  onSelect?: (counterpartyId: string) => void;
  /** The Add control. Onboarding opens from the book it will appear in. */
  action?: React.ReactNode;
}) {
  return (
    <PageSection
      icon={Building2}
      title="Approved Counterparties"
      description="Active credits, limits, ratings and headroom in force"
      accent="primary"
      actions={action}
    >
      <div className="overflow-x-auto">
        <table className="w-full text-xs text-left border-collapse">
          <thead>
            <tr className="border-b border-border text-[10px] uppercase font-semibold text-muted-foreground tracking-wider">
              <th className="py-2.5 px-3">Counterparty</th>
              <th className="py-2.5 px-2">Rating</th>
              <th className="py-2.5 px-3 text-right num">Limit</th>
              <th className="py-2.5 px-3 text-right num">Used</th>
              <th className="py-2.5 px-3 w-44">Headroom</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/50">
            {rows.map((row) => {
              const band = headroomBand(row.utilisation_bp);
              const barColor =
                band === "full"
                  ? "bg-destructive"
                  : band === "warm"
                    ? "bg-warning"
                    : "bg-primary";

              return (
                <tr
                  key={row.counterparty_id}
                  className={cn(
                    "hover:bg-surface-2/60 transition-colors cursor-pointer group",
                    row.has_open_breach && "bg-destructive/5 dark:bg-destructive/10"
                  )}
                  onClick={() => onSelect?.(row.counterparty_id)}
                >
                  <td className="py-3 px-3">
                    <div className="font-semibold text-foreground group-hover:text-primary transition-colors">
                      {row.name}
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-0.5">
                      {row.group_name} • group at {sterling(row.group_used_pence)} of{" "}
                      {sterling(row.group_limit_pence)}
                    </div>
                  </td>
                  <td className="py-3 px-2 whitespace-nowrap">
                    {row.rating_status === "WATCH" ? (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold border status-testing">
                        {row.rating} watch
                      </span>
                    ) : (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border border-border bg-surface-2 text-foreground">
                        {row.rating}
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-3 text-right num">
                    <div className="font-medium text-foreground">{sterling(row.limit_pence)}</div>
                    <div className="text-[10px] text-muted-foreground">
                      {row.max_tenor_months
                        ? `to ${months(row.max_tenor_months)}`
                        : "no limit"}
                    </div>
                  </td>
                  <td className="py-3 px-3 text-right num font-medium text-foreground">
                    {sterling(row.used_pence)}
                  </td>
                  <td className="py-3 px-3">
                    <div className="w-full bg-surface-2 rounded-full h-1.5 overflow-hidden">
                      <div
                        className={cn("h-full rounded-full transition-all duration-300", barColor)}
                        style={{ width: utilisationWidth(row.utilisation_bp) }}
                      />
                    </div>
                    <div className="text-[10px] text-muted-foreground mt-1 flex justify-between">
                      <span>
                        {row.limit_pence === null
                          ? "no limit"
                          : row.group_utilisation_bp >= 10000
                            ? "group full"
                            : `${sterling(row.headroom_pence)} free`}
                      </span>
                      <span className="num opacity-75">
                        {row.utilisation_bp ? `${(row.utilisation_bp / 100).toFixed(0)}%` : "0%"}
                      </span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-4 pt-3 border-t border-border/40 text-[11px] text-muted-foreground flex flex-wrap justify-between items-center gap-2">
        <span>Every figure computed from the deals behind it, none typed.</span>
        <span className="font-medium text-foreground num">
          Portfolio {sterling(portfolioTotalPence)} • {sterling(uninvestedCashPence)} uninvested cash
        </span>
      </div>
    </PageSection>
  );
}
