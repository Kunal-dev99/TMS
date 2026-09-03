"use client";

import { UserCheck } from "lucide-react";

import { PageSection } from "@/components/common/PageSection";
import { sterling } from "@/lib/format";
import type { CheckResult } from "@/lib/types";

/**
 * The verdict.
 *
 * On a pass: the measured exposure, how it was measured, and who has to sign
 * — named before the user commits rather than after.
 *
 * On a failure: how many failed and what the policy allows.
 *
 * Every word of it is composed on the server. The client does not decide who
 * signs, and it does not work out a measurement basis.
 */
export function Verdict({ result }: { result: CheckResult | null }) {
  const passed = result?.outcome === "PASS";
  const overridden = result?.outcome === "OVERRIDDEN";

  return (
    <PageSection
      icon={UserCheck}
      title="Verdict"
      description="Who signs, and on what measured figure"
      accent={result === null ? "primary" : passed ? "success" : "danger"}
    >
      {result === null ? (
        <div className="p-4 rounded border border-dashed border-border bg-surface-2/30 text-center">
          <p className="text-xs text-muted-foreground">
            The verdict names who has to sign, before the deal is committed
            rather than after.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <p
            className={`text-sm font-medium ${
              passed
                ? "text-success"
                : overridden
                  ? "text-warning"
                  : "text-destructive"
            }`}
          >
            {result.verdict}
          </p>

          {result.measured_pence !== null ? (
            <div className="flex items-baseline justify-between gap-3 pt-2 border-t border-border/40">
              <span className="text-xs text-muted-foreground">Measured exposure</span>
              <span className="num text-sm font-semibold">
                {sterling(result.measured_pence)}
              </span>
            </div>
          ) : null}

          {result.measurement_basis ? (
            <p className="text-[10px] text-muted-foreground text-right -mt-1">
              {result.measurement_basis}
            </p>
          ) : null}

          <div className="flex items-center justify-between gap-3 pt-2 border-t border-border/40 text-xs">
            <span className="text-muted-foreground">Policy in force</span>
            <span>
              {result.enforcement === "HARD_BLOCK"
                ? "hard block"
                : "warn with an override"}
            </span>
          </div>
        </div>
      )}
    </PageSection>
  );
}
