"use client";

import { useState } from "react";
import { Layers } from "lucide-react";

import { EmptyState, PanelShell } from "@/components/PanelShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { resolveQueueItem } from "@/lib/api";
import { shortDate } from "@/lib/format";
import type { QueueItem } from "@/lib/types";

/**
 * The queue. One queue, two causes.
 *
 * A limit failure happens before the deal exists and is resolved by changing
 * the deal. A confirmation mismatch happens after it exists and is resolved
 * by agreeing what was actually traded. They share one strip entry, which is
 * what keeps the navigation budget at five.
 *
 * The two mismatch resolutions are not offered here, because the
 * confirmation cause arrives in phase three and an option that always
 * refuses is worse than an option that is not there.
 */
const RESOLUTIONS: { value: string; label: string; hint: string }[] = [
  {
    value: "RESIZED",
    label: "Resized",
    hint: "The client resubmits a smaller deal. This one is cancelled.",
  },
  {
    value: "REROUTED",
    label: "Rerouted",
    hint: "The client books with a different counterparty.",
  },
  {
    value: "OVERRIDDEN",
    label: "Override",
    hint: "Needs a reason. Only under a warning policy.",
  },
  { value: "CANCELLED", label: "Cancelled", hint: "The deal does not happen." },
];

export function QueuePanel({
  open,
  onClose,
  items,
  enforcement,
  onResolved,
}: {
  open: boolean;
  onClose: () => void;
  items: QueueItem[];
  enforcement: string;
  onResolved: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const resolve = async (itemId: string, resolution: string) => {
    setBusy(itemId);
    setError(null);
    try {
      await resolveQueueItem(itemId, resolution, reason || undefined);
      setReason("");
      onResolved();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "That was refused.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <PanelShell
      open={open}
      onClose={onClose}
      icon={Layers}
      title="Queue"
      description="One queue, two causes, told apart by a reason code"
    >
      {items.length === 0 ? (
        <EmptyState>
          Nothing open. A blocked deal or a confirmation mismatch lands here
          with a reason code.
        </EmptyState>
      ) : (
        <div className="space-y-4">
          {error ? (
            <p className="rounded border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
              {error}
            </p>
          ) : null}

          {items.map((item) => (
            <article
              key={item.id}
              className="rounded-lg border border-border bg-surface-2/20 p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{item.counterparty_name}</p>
                  <p className="mt-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                    {item.cause === "LIMIT_FAILURE"
                      ? "Limit failure"
                      : "Confirmation mismatch"}
                    {" · "}
                    {item.reason_code.replace(/_/g, " ").toLowerCase()}
                  </p>
                </div>
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  {shortDate(item.raised_at)}
                </span>
              </div>

              <p className="mt-2 text-xs text-muted-foreground">{item.detail}</p>

              {item.cause === "LIMIT_FAILURE" &&
              enforcement === "WARN_WITH_OVERRIDE" ? (
                <Input
                  className="mt-3 h-8 text-xs"
                  placeholder="Reason, required to override"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                />
              ) : null}

              <div className="mt-3 flex flex-wrap gap-2">
                {RESOLUTIONS.filter(
                  (option) =>
                    option.value !== "OVERRIDDEN" ||
                    enforcement === "WARN_WITH_OVERRIDE",
                ).map((option) => (
                  <Button
                    key={option.value}
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs"
                    title={option.hint}
                    disabled={busy === item.id}
                    onClick={() => resolve(item.id, option.value)}
                  >
                    {option.label}
                  </Button>
                ))}
              </div>
            </article>
          ))}
        </div>
      )}
    </PanelShell>
  );
}
