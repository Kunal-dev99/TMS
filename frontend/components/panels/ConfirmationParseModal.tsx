"use client";

import { useEffect, useState } from "react";
import { FileText, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ingestConfirmation,
  parseConfirmation,
  type ConfirmationIngestResult,
  type ParsedConfirmation,
} from "@/lib/api";
import type { BookRow } from "@/lib/types";
import { dealRate, perCent, sterling } from "@/lib/format";
import { ThinkingTrace } from "@/components/panels/ThinkingTrace";
import { TypedText } from "@/components/panels/TypedText";

/**
 * Read any confirmation, in any format.
 *
 * The person pastes what arrived — an email body, a SWIFT MT300, PDF
 * text, a broker note. AI extracts the structured fields. Every field
 * is editable before the person hits Ingest, so a bad parse is a fixable
 * one; the parser cannot land anything on the book on its own.
 *
 * The card carries the AI reasoning trace on the way in and the raw
 * message on the way out, so a reader can always audit what was read.
 */

const PARSE_STEPS = [
  "Reading the raw message.",
  "Identifying the format (SWIFT, email, PDF text).",
  "Matching the counterparty against the book.",
  "Extracting principal, rate, dates.",
  "Flagging anything that looks off.",
];

const SAMPLE_EMAIL = `From: settlements@meridianbank.example
To: treasury@northgate.example
Subject: Your deposit — reference MER-DEMO-4471

Dear Treasurer,

We confirm your placement with us:

  Amount:      GBP 4,000,000
  Rate:        4.18 percent per annum
  Value date:  14 August 2026
  Maturity:    14 November 2026
  Reference:   MER-DEMO-4471

Please contact us if anything above is not as agreed.

Meridian Bank plc, Settlements`;

const SAMPLE_SWIFT = `{1:F01HVBIGB2LAXXX0000000000}
{2:I300HVBIGB2LXXXXN}
{4:
:20:HAR-2026-4471
:22A:NEWT
:82A:HARBOUR AND VALE BANK
:87A:NORTHGATE GROUP TREASURY
:32B:GBP3,000,000,
:33B:EUR3,522,000,
:36:1.1740
:30T:20260804
:30V:20261104
-}`;


type EditableFields = {
  message_type: string;
  reference: string;
  counterparty_id: string;
  instrument: string;
  principal: string;
  rate: string;
  value_date: string;
  maturity_date: string;
};


export function ConfirmationParseModal({
  open,
  onClose,
  book,
  onIngested,
}: {
  open: boolean;
  onClose: () => void;
  book: BookRow[];
  onIngested: (result: ConfirmationIngestResult) => void;
}) {
  const [rawText, setRawText] = useState("");
  const [busy, setBusy] = useState(false);
  const [networkDone, setNetworkDone] = useState(false);
  const [pending, setPending] = useState<ParsedConfirmation | null>(null);
  const [parsed, setParsed] = useState<ParsedConfirmation | null>(null);
  const [fields, setFields] = useState<EditableFields | null>(null);
  const [ingestBusy, setIngestBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ingestResult, setIngestResult] = useState<ConfirmationIngestResult | null>(null);

  // A close resets everything so the next open starts fresh.
  useEffect(() => {
    if (!open) {
      setRawText("");
      setBusy(false);
      setNetworkDone(false);
      setPending(null);
      setParsed(null);
      setFields(null);
      setIngestBusy(false);
      setError(null);
      setIngestResult(null);
    }
  }, [open]);

  const runParse = async () => {
    if (!rawText.trim()) return;
    setBusy(true);
    setNetworkDone(false);
    setParsed(null);
    setFields(null);
    setError(null);
    setIngestResult(null);
    try {
      const p = await parseConfirmation(rawText);
      setPending(p);
      setNetworkDone(true);
    } catch (cause: unknown) {
      setError(
        cause instanceof Error ? cause.message : "The parser was refused.",
      );
      setBusy(false);
    }
  };

  const revealResult = () => {
    if (!pending) return;
    setParsed(pending);
    setFields({
      message_type: pending.message_type ?? "DOCUMENT",
      reference: pending.reference ?? "",
      counterparty_id: pending.counterparty_id ?? "",
      instrument: pending.instrument ?? "DEPOSIT",
      principal:
        pending.principal_pence != null
          ? (pending.principal_pence / 100).toString()
          : "",
      rate:
        pending.rate_bp != null
          ? pending.instrument === "FX_FORWARD"
            ? (pending.rate_bp / 10000).toFixed(4)
            : (pending.rate_bp / 100).toFixed(2)
          : "",
      value_date: pending.value_date ?? "",
      maturity_date: pending.maturity_date ?? "",
    });
    setBusy(false);
  };

  const ingest = async () => {
    if (!fields || !parsed) return;
    setIngestBusy(true);
    setError(null);
    try {
      const rate =
        fields.instrument === "FX_FORWARD"
          ? Math.round(parseFloat(fields.rate) * 10000)
          : Math.round(parseFloat(fields.rate) * 100);
      const result = await ingestConfirmation({
        message_type: fields.message_type,
        reference: fields.reference,
        counterparty_id: fields.counterparty_id || null,
        instrument: fields.instrument,
        principal_pence: Math.round(parseFloat(fields.principal) * 100),
        rate_bp: rate,
        value_date: fields.value_date,
        maturity_date: fields.maturity_date || null,
        raw_payload: parsed.raw_payload,
      });
      setIngestResult(result);
      onIngested(result);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "That was refused.");
    } finally {
      setIngestBusy(false);
    }
  };

  if (!open) return null;

  const missingRequired =
    !fields ||
    !fields.counterparty_id ||
    !fields.instrument ||
    !fields.principal ||
    !fields.rate ||
    !fields.value_date;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-6"
      role="dialog"
      aria-modal="true"
      aria-label="Paste a confirmation"
    >
      <div className="relative w-full max-w-4xl rounded-lg border border-border bg-card shadow-2xl">
        <header className="flex items-start justify-between gap-4 border-b border-border p-5">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              <FileText className="h-4 w-4 text-primary" aria-hidden />
              Paste a confirmation
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Email, SWIFT MT300 or MT320, PDF text, broker note. The parser
              reads it; the six checks still gate the ingest.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:bg-surface-2 hover:text-foreground"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="space-y-4 p-5">
          {error ? (
            <p className="rounded border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
              {error}
            </p>
          ) : null}

          {/* Paste area, hidden after ingest */}
          {!ingestResult ? (
            <div className="space-y-2">
              <div className="flex items-baseline justify-between">
                <Label className="text-[10px]">
                  The raw message, in any format
                </Label>
                <div className="flex gap-2 text-[10px]">
                  <button
                    type="button"
                    className="text-primary hover:underline"
                    onClick={() => setRawText(SAMPLE_EMAIL)}
                    disabled={busy || !!parsed}
                  >
                    Try an email
                  </button>
                  <span className="text-muted-foreground">·</span>
                  <button
                    type="button"
                    className="text-primary hover:underline"
                    onClick={() => setRawText(SAMPLE_SWIFT)}
                    disabled={busy || !!parsed}
                  >
                    Try a SWIFT MT300
                  </button>
                </div>
              </div>
              <textarea
                className="h-40 w-full resize-y rounded-md border border-input bg-transparent p-2.5 font-mono text-[11px] leading-snug"
                placeholder="Paste the confirmation as it arrived."
                value={rawText}
                onChange={(event) => setRawText(event.target.value)}
                disabled={busy || !!parsed}
              />
              {!parsed ? (
                <Button
                  type="button"
                  className="gap-1.5"
                  disabled={busy || !rawText.trim()}
                  onClick={runParse}
                >
                  <Sparkles className="h-3 w-3" aria-hidden />
                  {busy ? "Reading..." : "Read this"}
                </Button>
              ) : null}
            </div>
          ) : null}

          {/* AI reasoning trace */}
          {busy ? (
            <ThinkingTrace
              steps={PARSE_STEPS}
              finished={networkDone}
              intervalMs={280}
              onFinished={revealResult}
            />
          ) : null}

          {/* Extracted fields, editable */}
          {parsed && fields && !ingestResult ? (
            <>
              <div className="rounded-lg border border-primary/30 bg-primary/[.04] p-3">
                <div className="mb-2 flex items-center gap-1.5">
                  <Sparkles className="h-3 w-3 text-primary" aria-hidden />
                  <span className="text-[9px] font-medium uppercase tracking-wider text-primary">
                    Extracted
                  </span>
                  <span className="ml-auto text-[9px] italic text-muted-foreground">
                    read just now · {parsed.fields_extracted.length} of{" "}
                    {parsed.fields_extracted.length +
                      parsed.fields_missing.length}{" "}
                    fields
                  </span>
                </div>
                <p className="text-[10.5px] italic leading-snug text-muted-foreground">
                  <TypedText
                    text={summarise(parsed, book)}
                    charsPerSecond={90}
                  />
                </p>

                {parsed.warnings.length > 0 ? (
                  <ul className="mt-2 space-y-0.5 border-t border-primary/20 pt-2">
                    {parsed.warnings.map((w, i) => (
                      <li
                        key={i}
                        className="text-[10px] text-warning"
                      >
                        ! {w}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>

              <div className="rounded-lg border border-border bg-surface-2/20 p-3">
                <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Review before ingesting
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <FieldSelect
                    label="Counterparty"
                    value={fields.counterparty_id}
                    onChange={(v) =>
                      setFields({ ...fields, counterparty_id: v })
                    }
                    options={[
                      { value: "", label: "Choose a counterparty" },
                      ...book.map((row) => ({
                        value: row.counterparty_id,
                        label: row.name,
                      })),
                    ]}
                  />
                  <FieldSelect
                    label="Message type"
                    value={fields.message_type}
                    onChange={(v) => setFields({ ...fields, message_type: v })}
                    options={[
                      { value: "MT300", label: "MT300 — FX" },
                      { value: "MT320", label: "MT320 — deposit" },
                      { value: "MT535", label: "MT535" },
                      { value: "MT536", label: "MT536" },
                      { value: "BROKER_NOTE", label: "Broker note" },
                      { value: "DOCUMENT", label: "Document / email" },
                    ]}
                  />
                  <FieldSelect
                    label="Instrument"
                    value={fields.instrument}
                    onChange={(v) => setFields({ ...fields, instrument: v })}
                    options={[
                      { value: "DEPOSIT", label: "Deposit" },
                      { value: "FX_FORWARD", label: "FX forward" },
                      { value: "MMF", label: "Money market fund" },
                      { value: "GILT", label: "Gilt" },
                    ]}
                  />
                  <FieldInput
                    label="Reference"
                    value={fields.reference}
                    onChange={(v) => setFields({ ...fields, reference: v })}
                    placeholder="MER-DEMO-4471"
                  />
                  <FieldInput
                    label="Principal (£)"
                    value={fields.principal}
                    onChange={(v) => setFields({ ...fields, principal: v })}
                    placeholder="4000000"
                    mono
                  />
                  <FieldInput
                    label={
                      fields.instrument === "FX_FORWARD"
                        ? "Forward rate"
                        : "Rate (%)"
                    }
                    value={fields.rate}
                    onChange={(v) => setFields({ ...fields, rate: v })}
                    placeholder={
                      fields.instrument === "FX_FORWARD" ? "1.1740" : "4.18"
                    }
                    mono
                  />
                  <FieldInput
                    label="Value date"
                    value={fields.value_date}
                    onChange={(v) => setFields({ ...fields, value_date: v })}
                    type="date"
                  />
                  <FieldInput
                    label="Maturity"
                    value={fields.maturity_date}
                    onChange={(v) =>
                      setFields({ ...fields, maturity_date: v })
                    }
                    type="date"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setParsed(null);
                    setFields(null);
                  }}
                >
                  Try another message
                </Button>
                <Button
                  type="button"
                  size="sm"
                  disabled={ingestBusy || missingRequired}
                  onClick={ingest}
                >
                  {ingestBusy ? "Ingesting..." : "Ingest confirmation"}
                </Button>
              </div>
            </>
          ) : null}

          {/* Ingest outcome */}
          {ingestResult ? <IngestOutcome result={ingestResult} onClose={onClose} /> : null}
        </div>
      </div>
    </div>
  );
}


function summarise(parsed: ParsedConfirmation, book: BookRow[]): string {
  const parts: string[] = [];
  const cp = book.find((r) => r.counterparty_id === parsed.counterparty_id);
  if (cp) parts.push(cp.name);
  if (parsed.instrument === "FX_FORWARD") parts.push("FX forward");
  else if (parsed.instrument) parts.push(parsed.instrument.toLowerCase());
  if (parsed.principal_pence != null) parts.push(sterling(parsed.principal_pence));
  if (parsed.rate_bp != null && parsed.instrument) {
    parts.push(
      "at " + dealRate(parsed.rate_bp, parsed.instrument),
    );
  } else if (parsed.rate_bp != null) {
    parts.push("at " + perCent(parsed.rate_bp));
  }
  if (parsed.value_date) parts.push("value " + parsed.value_date);
  if (parsed.maturity_date) parts.push("matures " + parsed.maturity_date);
  return parts.length
    ? "Read as " + parts.join(", ") + "."
    : "Nothing conclusive was extracted; key the fields manually.";
}


function FieldInput({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  mono,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  mono?: boolean;
}) {
  return (
    <div className="space-y-1">
      <Label className="text-[10px]">{label}</Label>
      <Input
        type={type}
        className={`h-8 text-xs${mono ? " num" : ""}`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}


function FieldSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="space-y-1">
      <Label className="text-[10px]">{label}</Label>
      <select
        className="flex h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}


function IngestOutcome({
  result,
  onClose,
}: {
  result: ConfirmationIngestResult;
  onClose: () => void;
}) {
  const tone =
    result.match_status === "MATCHED"
      ? "border-success/40 bg-success/10 text-success"
      : result.match_status === "MISMATCHED"
        ? "border-warning/40 bg-warning/10 text-warning"
        : "border-muted-foreground/40 bg-surface-2 text-muted-foreground";
  return (
    <div className="space-y-3">
      <div className={`rounded-lg border p-3 ${tone}`}>
        <p className="text-sm font-medium">{result.match_status}</p>
        <p className="mt-1 text-[11px]">
          {result.match_status === "MATCHED"
            ? "Every field agreed with the deal. Recorded."
            : result.match_status === "MISMATCHED"
              ? `Attached to a deal, ${result.differences.length} field(s) disagreed. See the Queue.`
              : "No matching deal on the book. The confirmation waits — the deal may not have been keyed yet."}
        </p>
      </div>
      {result.differences.length > 0 ? (
        <table className="w-full text-[10.5px]">
          <thead>
            <tr className="text-[9px] uppercase tracking-wider text-muted-foreground">
              <th className="pb-1 text-left font-medium">Field</th>
              <th className="pb-1 text-right font-medium">Keyed</th>
              <th className="pb-1 text-right font-medium">Confirmed</th>
            </tr>
          </thead>
          <tbody>
            {result.differences.map((d) => (
              <tr key={d.field_name} className="border-t border-border/40">
                <td className="py-1">
                  {d.field_name.replace(/_/g, " ").replace(" pence", "").replace(" bp", "")}
                </td>
                <td className="num py-1 text-right">{d.keyed_value}</td>
                <td className="num py-1 text-right text-warning">
                  {d.confirmed_value}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <div className="flex justify-end">
        <Button type="button" onClick={onClose}>
          Done
        </Button>
      </div>
    </div>
  );
}
