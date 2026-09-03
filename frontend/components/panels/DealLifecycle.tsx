"use client";

import { useEffect, useState } from "react";
import { FileWarning, PenLine, Scale } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  applyAmendment,
  getStatements,
  raiseAmendment,
  recordStatementLine,
  settleDeal,
} from "@/lib/api";
import { perCent, shortDate, sterling } from "@/lib/format";
import type { AmendmentPreview, DealDetail, StatementLine } from "@/lib/types";

/**
 * The three phase-three sections of the deal panel.
 *
 * Kept in one file because they are one story: what the counterparty says
 * was traded, what was changed afterwards, and whether the money arrived.
 */

// --------------------------------------------------------------------------
// The confirmation
// --------------------------------------------------------------------------

export function ConfirmationSection({ detail }: { detail: DealDetail }) {
  const confirmation = detail.confirmation;

  return (
    <section>
      <h3 className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        The counterparty&apos;s record
      </h3>
      <p className="mb-3 text-[10px] text-muted-foreground">
        It arrives on its own route, which is the only reason matching is a
        control. Fold it into the deal feed and there is nothing to match
        against.
      </p>

      {confirmation === null ? (
        <div className="rounded border border-dashed border-border bg-surface-2/30 p-3">
          <p className="text-xs text-muted-foreground">
            No confirmation has arrived. The position is on the book and only
            our own record says what was traded.
          </p>
        </div>
      ) : (
        <div
          className={`rounded-lg border p-3 ${
            confirmation.match_status === "MATCHED"
              ? "border-success/30 bg-success/5"
              : "border-warning/40 bg-warning/10"
          }`}
        >
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[11.5px] font-medium">
              {confirmation.message_type} {confirmation.reference}
            </span>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
              {confirmation.match_status.toLowerCase()}
            </span>
          </div>

          {confirmation.differences.length === 0 ? (
            <p className="mt-1 text-[10.5px] text-muted-foreground">
              Every field agreed.
            </p>
          ) : (
            <table className="mt-2 w-full text-[10.5px]">
              <thead>
                <tr className="text-[9px] uppercase tracking-wider text-muted-foreground">
                  <th className="pb-1 text-left font-medium">Field</th>
                  <th className="pb-1 text-right font-medium">Keyed</th>
                  <th className="pb-1 text-right font-medium">Confirmed</th>
                </tr>
              </thead>
              <tbody>
                {confirmation.differences.map((difference) => (
                  <tr
                    key={difference.field_name}
                    className="border-t border-border/40"
                  >
                    <td className="py-1">
                      {difference.field_name
                        .replace(/_/g, " ")
                        .replace(" pence", "")
                        .replace(" bp", "")}
                    </td>
                    <td className="num py-1 text-right">
                      {difference.keyed_value}
                    </td>
                    <td className="num py-1 text-right text-warning">
                      {difference.confirmed_value}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------
// Amendments
// --------------------------------------------------------------------------

const TYPES = [
  { value: "CORRECTION", label: "Correction" },
  { value: "ROLL", label: "Roll" },
  { value: "PARTIAL_DRAWDOWN", label: "Partial drawdown" },
  { value: "BREAK", label: "Break" },
];

export function AmendmentSection({
  detail,
  onChanged,
}: {
  detail: DealDetail;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [type, setType] = useState("CORRECTION");
  const [effective, setEffective] = useState("");
  const [rate, setRate] = useState("");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<AmendmentPreview | null>(null);
  const [amendmentId, setAmendmentId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const amendable =
    detail.deal.status === "ACTIVE" || detail.deal.status === "MATURED";

  const raise = async () => {
    setBusy(true);
    setError(null);
    try {
      const raised = await raiseAmendment(detail.deal.id, {
        type,
        effective_date: effective,
        reason: reason.trim(),
        new_rate_bp: rate.trim() ? Math.round(Number(rate) * 100) : null,
      });
      setAmendmentId(raised.amendment_id);
      setPreview(raised.preview);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "That was refused.");
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!amendmentId) return;
    setBusy(true);
    setError(null);
    try {
      await applyAmendment(amendmentId);
      setOpen(false);
      setPreview(null);
      setAmendmentId(null);
      setReason("");
      setRate("");
      onChanged();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "That was refused.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Amendments
        </h3>
        {amendable ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-6 gap-1 text-[10px]"
            onClick={() => setOpen((was) => !was)}
          >
            <PenLine className="h-3 w-3" />
            {open ? "Cancel" : "Raise one"}
          </Button>
        ) : null}
      </div>

      {detail.amendments.length === 0 && !open ? (
        <p className="text-[10.5px] text-muted-foreground">
          Nothing amended. A correction is an entry rather than an edit: the
          original accrual rows stay and reversals are written against them.
        </p>
      ) : null}

      {detail.amendments.map((amendment) => (
        <div
          key={amendment.id}
          className="mb-2 rounded border border-warning/40 bg-warning/10 p-2.5"
        >
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[11.5px] font-medium">
              {amendment.type.replace(/_/g, " ").toLowerCase()},{" "}
              {amendment.status.toLowerCase()}
            </span>
            <span className="text-[10px] text-muted-foreground">
              from {shortDate(amendment.effective_date)}
            </span>
          </div>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            {amendment.reason}
            {amendment.new_rate_bp
              ? ` New rate ${perCent(amendment.new_rate_bp)}.`
              : ""}
          </p>
        </div>
      ))}

      {open ? (
        <div className="space-y-2 rounded-lg border border-border bg-card p-3">
          <p className="text-[10px] text-muted-foreground">
            Raising records what is proposed and what it would change. Nothing
            is reversed until you apply it.
          </p>

          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label className="text-[10px]">Type</Label>
              <select
                className="flex h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs"
                value={type}
                onChange={(event) => setType(event.target.value)}
              >
                {TYPES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label className="text-[10px]">Effective from</Label>
              <input
                type="date"
                className="flex h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs"
                value={effective}
                onChange={(event) => setEffective(event.target.value)}
              />
            </div>
          </div>

          <div className="space-y-1">
            <Label className="text-[10px]">New rate (%), if it changed</Label>
            <Input
              className="num h-8 text-xs"
              value={rate}
              onChange={(event) => setRate(event.target.value)}
              placeholder={perCent(detail.deal.rate_bp)}
            />
          </div>

          <div className="space-y-1">
            <Label className="text-[10px]">Reason</Label>
            <Input
              className="h-8 text-xs"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="An amendment that reverses posted journals needs one."
            />
          </div>

          {error ? (
            <p className="rounded border border-destructive/40 bg-destructive/10 p-2 text-[10px] text-destructive">
              {error}
            </p>
          ) : null}

          {preview ? (
            <div
              className={`rounded border p-2.5 text-[10px] ${
                preview.any_period_closed
                  ? "border-destructive/40 bg-destructive/10"
                  : "border-border bg-surface-2/40"
              }`}
            >
              <p className="font-medium">
                {preview.accruals_affected} day(s) would be reversed,{" "}
                {sterling(preview.amount_to_reverse_pence)} in total.
              </p>
              <p className="mt-1 text-muted-foreground">
                Periods touched: {preview.periods_affected.join(", ") || "none"}.
                {preview.any_period_closed
                  ? " One of them has posted journals in it, so applying will be refused: whether a closed period can be reopened is an accounting policy decision rather than a technical one."
                  : ""}
              </p>
            </div>
          ) : null}

          <div className="flex gap-2">
            {preview === null ? (
              <Button
                type="button"
                size="sm"
                className="h-7 flex-1 text-xs"
                disabled={busy || !effective || !reason.trim()}
                onClick={raise}
              >
                Raise, and show what it would change
              </Button>
            ) : (
              <Button
                type="button"
                size="sm"
                className="h-7 flex-1 text-xs"
                disabled={busy}
                onClick={apply}
              >
                Apply. Reverse and repost.
              </Button>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}

// --------------------------------------------------------------------------
// Settlement
// --------------------------------------------------------------------------

export function SettlementSection({
  detail,
  onChanged,
}: {
  detail: DealDetail;
  onChanged: () => void;
}) {
  const [lines, setLines] = useState<StatementLine[]>([]);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    getStatements()
      .then((rows) => {
        setLines(rows);
        setSelected(rows[0]?.id ?? "");
      })
      .catch(() => undefined);
  }, [open]);

  const settlement = detail.settlement;
  const settleable =
    detail.deal.status === "ACTIVE" || detail.deal.status === "MATURED";

  const settle = async () => {
    setBusy(true);
    setError(null);
    try {
      await settleDeal(detail.deal.id, selected);
      onChanged();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "That was refused.");
    } finally {
      setBusy(false);
    }
  };

  const recordAndSettle = async () => {
    setBusy(true);
    setError(null);
    try {
      // The stored accrual, not the measured exposure.
      //
      // These are two different figures and they are meant to be: exposure is
      // recomputed at current terms, an accrual is what was recognised on the
      // day and stays recognised. A mid-life amendment separates them, because
      // the days before the effective date keep the old rate. Settlement
      // compares against the stored accrual, so a line built from the measured
      // figure arrives short and reports a break that nothing caused.
      const accrued = detail.accruals.reduce(
        (total, row) => total + row.amount_pence,
        0,
      );
      const line = await recordStatementLine({
        account_name: "Group operating account",
        amount_pence: detail.deal.principal_pence + accrued,
        value_date: detail.deal.maturity_date ?? detail.deal.value_date,
        reference: detail.deal.id,
      });
      await settleDeal(detail.deal.id, line.statement_line_id);
      onChanged();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "That was refused.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Settlement
        </h3>
        {settleable ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-6 gap-1 text-[10px]"
            onClick={() => setOpen((was) => !was)}
          >
            <Scale className="h-3 w-3" />
            {open ? "Cancel" : "Match three sources"}
          </Button>
        ) : null}
      </div>

      <p className="mb-2 text-[10px] text-muted-foreground">
        The deal record, the counterparty&apos;s confirmation and the bank
        statement. Two of three agreeing is not enough: if the record and the
        confirmation agree but the statement differs, the money did not arrive
        as promised.
      </p>

      {settlement ? (
        <div
          className={`rounded-lg border p-3 ${
            settlement.match_status === "AGREED"
              ? "border-success/30 bg-success/5"
              : "border-destructive/40 bg-destructive/10"
          }`}
        >
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[11.5px] font-medium">
              {settlement.match_status === "AGREED"
                ? "All three agree"
                : settlement.match_status === "BREAK"
                  ? "Break"
                  : "Waiting on a third source"}
            </span>
            {settlement.closed_at ? (
              <span className="text-[10px] text-muted-foreground">
                closed {shortDate(settlement.closed_at)}
              </span>
            ) : null}
          </div>
          {settlement.break_detail ? (
            <p className="mt-1 flex items-start gap-1.5 text-[10.5px] text-muted-foreground">
              <FileWarning className="mt-0.5 h-3 w-3 shrink-0" />
              {settlement.break_detail}
            </p>
          ) : null}
          <dl className="mt-2 grid grid-cols-3 gap-2 border-t border-border/40 pt-2 text-[10px]">
            <div>
              <dt className="text-muted-foreground">Record</dt>
              <dd className="num">
                {sterling(
                  settlement.expected_principal_pence +
                    settlement.expected_interest_pence,
                )}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Confirmation</dt>
              <dd className="num">
                {settlement.confirmed_amount_pence === null
                  ? "—"
                  : sterling(settlement.confirmed_amount_pence)}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Statement</dt>
              <dd className="num">
                {settlement.statement_amount_pence === null
                  ? "—"
                  : sterling(settlement.statement_amount_pence)}
              </dd>
            </div>
          </dl>
        </div>
      ) : (
        <p className="text-[10.5px] text-muted-foreground">
          Not settled. Until this deal closes the counterparty still holds the
          headroom, and the next deal may be blocked for no reason.
        </p>
      )}

      {open ? (
        <div className="mt-3 space-y-2 rounded-lg border border-border bg-card p-3">
          {error ? (
            <p className="rounded border border-destructive/40 bg-destructive/10 p-2 text-[10px] text-destructive">
              {error}
            </p>
          ) : null}

          {lines.length > 0 ? (
            <>
              <Label className="text-[10px]">Bank statement line</Label>
              <select
                className="flex h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs"
                value={selected}
                onChange={(event) => setSelected(event.target.value)}
              >
                {lines.map((line) => (
                  <option key={line.id} value={line.id}>
                    {sterling(Math.abs(line.amount_pence))} on{" "}
                    {line.value_date}
                    {line.reference ? ` — ${line.reference}` : ""}
                  </option>
                ))}
              </select>
              <Button
                type="button"
                size="sm"
                className="h-7 w-full text-xs"
                disabled={busy || !selected}
                onClick={settle}
              >
                Match against this line
              </Button>
            </>
          ) : (
            <p className="text-[10px] text-muted-foreground">
              No statement lines have been ingested. The statement is the third
              source and it comes from Oracle, prior day.
            </p>
          )}

          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 w-full text-xs"
            disabled={busy}
            onClick={recordAndSettle}
          >
            Record a matching line and settle
          </Button>
          <p className="text-[10px] text-muted-foreground">
            The second control stands in for the statement feed, which is not
            built. It records a line for exactly what the deal expects, on the
            same basis settlement uses, so the three way match is a real
            comparison rather than a simulated one.
          </p>
        </div>
      ) : null}
    </section>
  );
}
