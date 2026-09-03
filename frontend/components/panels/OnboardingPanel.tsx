"use client";

import { useState } from "react";
import { UserPlus } from "lucide-react";

import { PanelShell } from "@/components/PanelShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  activateCounterparty,
  createCounterparty,
  setCounterpartyLimit,
  verifyCounterparty,
} from "@/lib/api";
import { sterling } from "@/lib/format";
import type { RatingBandView } from "@/lib/types";

/**
 * Add a counterparty. Four steps, each separately refusable.
 *
 * Draft, verified, approved, active. Nothing shortens it, because the point
 * of the slow loop is that somebody looked at each step. The status moves
 * visibly, so the panel shows the loop rather than describing it.
 *
 * Step three proposes the band's figures rather than starting from a blank
 * field, and refuses a limit nobody signed.
 */
export function OnboardingPanel({
  open,
  onClose,
  bands,
  onFinished,
}: {
  open: boolean;
  onClose: () => void;
  bands: RatingBandView[];
  onFinished: () => void;
}) {
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [counterpartyId, setCounterpartyId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [lei, setLei] = useState("");
  const [parent, setParent] = useState("");
  const [rating, setRating] = useState("A");
  const [proposed, setProposed] = useState<{
    amount_pence: number;
    max_tenor_months: number;
  } | null>(null);
  const [amount, setAmount] = useState("");
  const [tenor, setTenor] = useState("");
  const [approver, setApprover] = useState("");
  const [reason, setReason] = useState("");

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "That step was refused.");
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setStep(1);
    setCounterpartyId(null);
    setName("");
    setLei("");
    setParent("");
    setRating("A");
    setProposed(null);
    setAmount("");
    setTenor("");
    setApprover("");
    setReason("");
    setError(null);
  };

  const aboveBand =
    proposed !== null && Number(amount.replace(/,/g, "")) * 100 > proposed.amount_pence;

  return (
    <PanelShell
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      icon={UserPlus}
      title="Add a counterparty"
      description="Four steps, each separately refusable"
    >
      <ol className="mb-5 flex gap-1">
        {["Draft", "Verify", "Limit", "Activate"].map((label, index) => (
          <li
            key={label}
            className={`flex-1 rounded-md px-2 py-1.5 text-center text-[10px] font-medium ${
              step > index + 1
                ? "bg-success/15 text-success"
                : step === index + 1
                  ? "bg-primary/15 text-primary"
                  : "bg-surface-2/60 text-muted-foreground"
            }`}
          >
            {index + 1}. {label}
          </li>
        ))}
      </ol>

      {error ? (
        <p className="mb-4 rounded border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
          {error}
        </p>
      ) : null}

      {step === 1 ? (
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="cp-name" className="text-xs">
              Legal name
            </Label>
            <Input
              id="cp-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Sterling Union Bank"
            />
          </div>
          <Button
            type="button"
            className="w-full"
            disabled={busy || !name.trim()}
            onClick={() =>
              run(async () => {
                const created = await createCounterparty(name.trim());
                setCounterpartyId(created.counterparty_id);
                setStep(2);
              })
            }
          >
            Create draft
          </Button>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="space-y-3">
          <p className="text-[10px] text-muted-foreground">
            The group parent is the field the whole group check rests on, and
            it comes from a public register rather than from the counterparty.
          </p>
          <div className="space-y-1.5">
            <Label htmlFor="cp-lei" className="text-xs">
              Legal entity identifier
            </Label>
            <Input
              id="cp-lei"
              value={lei}
              onChange={(event) => setLei(event.target.value)}
              placeholder="213800..."
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cp-parent" className="text-xs">
              Group parent
            </Label>
            <Input
              id="cp-parent"
              value={parent}
              onChange={(event) => setParent(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cp-rating" className="text-xs">
              Rating
            </Label>
            <select
              id="cp-rating"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
              value={rating}
              onChange={(event) => setRating(event.target.value)}
            >
              {bands.map((band) => (
                <option key={band.rating} value={band.rating}>
                  {band.rating} — up to {sterling(band.max_limit_pence)},{" "}
                  {band.max_tenor_months} months
                </option>
              ))}
            </select>
          </div>
          <Button
            type="button"
            className="w-full"
            disabled={busy || !lei.trim() || !parent.trim()}
            onClick={() =>
              run(async () => {
                const verified = await verifyCounterparty(counterpartyId!, {
                  legal_entity_identifier: lei.trim(),
                  group_parent_name: parent.trim(),
                  rating,
                  country: "GB",
                  instruments: ["DEPOSIT"],
                });
                setProposed({
                  amount_pence: verified.proposed_limit_pence,
                  max_tenor_months: verified.proposed_max_tenor_months,
                });
                setAmount(String(Math.round(verified.proposed_limit_pence / 100)));
                setTenor(String(verified.proposed_max_tenor_months));
                setStep(3);
              })
            }
          >
            Verify
          </Button>
        </div>
      ) : null}

      {step === 3 && proposed ? (
        <div className="space-y-3">
          <p className="text-[10px] text-muted-foreground">
            Proposed from the {rating} band: {sterling(proposed.amount_pence)} to{" "}
            {proposed.max_tenor_months} months. A limit nobody signed is not a
            control.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="cp-amount" className="text-xs">
                Limit (£)
              </Label>
              <Input
                id="cp-amount"
                className="num"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cp-tenor" className="text-xs">
                Term (months)
              </Label>
              <Input
                id="cp-tenor"
                className="num"
                value={tenor}
                onChange={(event) => setTenor(event.target.value)}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cp-approver" className="text-xs">
              Approved by
            </Label>
            <Input
              id="cp-approver"
              value={approver}
              onChange={(event) => setApprover(event.target.value)}
              placeholder="Required"
            />
          </div>
          {aboveBand ? (
            <div className="space-y-1.5">
              <Label htmlFor="cp-reason" className="text-xs text-warning">
                Reason, required above the band
              </Label>
              <Input
                id="cp-reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </div>
          ) : null}
          <Button
            type="button"
            className="w-full"
            disabled={busy || !approver.trim()}
            onClick={() =>
              run(async () => {
                await setCounterpartyLimit(counterpartyId!, {
                  amount_pence: Math.round(Number(amount.replace(/,/g, "")) * 100),
                  max_tenor_months: Math.round(Number(tenor)),
                  approved_by: approver.trim(),
                  reason: reason || undefined,
                });
                setStep(4);
              })
            }
          >
            Set the limit and approve
          </Button>
        </div>
      ) : null}

      {step === 4 ? (
        <div className="space-y-3">
          <p className="text-[10px] text-muted-foreground">
            Activating is the boundary between the slow onboarding loop and the
            fast per deal loop. It is the only thing that puts a name in front
            of a dealer.
          </p>
          <Button
            type="button"
            className="w-full"
            disabled={busy}
            onClick={() =>
              run(async () => {
                await activateCounterparty(counterpartyId!);
                reset();
                onFinished();
                onClose();
              })
            }
          >
            Activate
          </Button>
        </div>
      ) : null}
    </PanelShell>
  );
}
