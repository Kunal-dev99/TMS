"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ClipboardCheck,
  FileSearch,
  Loader2,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";

import { PageShell } from "@/components/PageShell";
import { whoAmI } from "@/lib/api";
import { can, currentUser } from "@/lib/session";

import { AuditTrailTab } from "./_audit_trail";
import { BreachesTab } from "./_breaches";
import { DealEvidenceTab } from "./_deal_evidence";
import { OverviewTab } from "./_overview";
import { PolicyHistoryTab } from "./_policy_history";

/**
 * Compliance shell — a compact summary strip and five tabs.
 *
 *   Overview · Audit trail · Deal evidence · Breaches & overrides · Policy history
 *
 * "Overview" and "Breaches & overrides" derive from tables already
 * in place (audit_event, exception_item, check_run, deal). "Deal
 * evidence" reads the six-check run captured at booking time. "Policy
 * history" is stubbed until the policy_version table grows the
 * changed_by / authorised_by / superseded_by columns.
 *
 * The whole page stays read-only. Buttons that would act (approve,
 * override, resolve) link out to the operational page instead.
 */

type TabKey = "overview" | "audit" | "evidence" | "breaches" | "policy";

const TABS: { key: TabKey; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { key: "overview", label: "Overview", icon: ShieldCheck },
  { key: "audit", label: "Audit trail", icon: ClipboardCheck },
  { key: "evidence", label: "Deal evidence", icon: FileSearch },
  { key: "breaches", label: "Breaches & overrides", icon: ShieldAlert },
  { key: "policy", label: "Policy history", icon: ShieldCheck },
];

export default function CompliancePage() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [tab, setTab] = useState<TabKey>("overview");
  const [pinnedDealId, setPinnedDealId] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const me = currentUser() ?? (await whoAmI());
        if (!me) {
          router.replace("/");
          return;
        }
        if (!can("view.audit", "admin.users")) {
          router.replace("/");
          return;
        }
      } finally {
        setChecking(false);
      }
    })();
  }, [router]);

  if (checking) {
    return (
      <PageShell title="Compliance" icon={ShieldCheck}>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> Checking access…
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell
      title="Compliance"
      description="Read-only view. Overview, the audit trail, per-deal evidence, the breach and override register, and policy history — all sourced from tables the rest of the app already writes to."
      icon={ShieldCheck}
    >
      <div className="mb-4 flex flex-wrap gap-1 border-b border-border">
        {TABS.map((t) => {
          const active = tab === t.key;
          const Icon = t.icon;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={
                "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-xs transition-colors " +
                (active
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground")
              }
            >
              <Icon className="h-3.5 w-3.5" /> {t.label}
            </button>
          );
        })}
      </div>

      {tab === "overview" ? (
        <OverviewTab
          onGoToBreaches={() => setTab("breaches")}
          onGoToAudit={() => setTab("audit")}
        />
      ) : null}
      {tab === "audit" ? <AuditTrailTab /> : null}
      {tab === "evidence" ? (
        <DealEvidenceTab initialDealId={pinnedDealId} />
      ) : null}
      {tab === "breaches" ? (
        <BreachesTab
          onOpenDeal={(dealId) => {
            setPinnedDealId(dealId);
            setTab("evidence");
          }}
        />
      ) : null}
      {tab === "policy" ? <PolicyHistoryTab /> : null}
    </PageShell>
  );
}
