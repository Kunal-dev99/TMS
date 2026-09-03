/**
 * The formatting module.
 *
 * Pence to pounds, minor units with a currency, basis points to per cent,
 * dates, and the stage label. Nothing formats inline anywhere else, because
 * a second place that turns pence into pounds is a second place that can
 * round differently.
 *
 * Nothing here decides anything. There is no arithmetic in this file beyond
 * changing the units of a figure the server already computed.
 */

const CURRENCY_SYMBOLS: Record<string, string> = {
  GBP: "£",
  EUR: "€",
  USD: "$",
};

/** 1811983562 becomes £18,119,836. Rounded to the pound, as displayed. */
export function sterling(pence: number | null | undefined): string {
  if (pence === null || pence === undefined) return "—";
  return `£${Math.round(pence / 100).toLocaleString("en-GB")}`;
}

/** Foreign currency. Never appears without its currency. */
export function minorUnits(amount: number, currency: string): string {
  const symbol = CURRENCY_SYMBOLS[currency] ?? "";
  const places = currency === "JPY" ? 0 : 2;
  const value = Math.round(amount / 10 ** places).toLocaleString("en-GB");
  return symbol ? `${symbol}${value}` : `${value} ${currency}`;
}

/** 420 becomes 4.20 per cent. */
export function perCent(basisPoints: number | null | undefined): string {
  if (basisPoints === null || basisPoints === undefined) return "—";
  return `${(basisPoints / 100).toFixed(2)}%`;
}

/**
 * The rate column, which holds two different things.
 *
 * Document 1 gives deal.rate_bp as the contracted rate or the forward rate,
 * in one column. A deposit at 420 is 4.20 per cent. A forward at 11740 is a
 * rate of 1.1740, and showing it as 117.40 per cent reads as nonsense.
 *
 * The instrument decides which it is. That is a display decision, so it
 * lives here rather than in a component.
 */
export function dealRate(basisPoints: number, instrument: string): string {
  if (instrument === "FX_FORWARD") {
    return (basisPoints / 10000).toFixed(4);
  }
  return perCent(basisPoints);
}

/** 2026-09-03 becomes 3 Sep 2026. */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return date.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function months(count: number): string {
  return count === 1 ? "1 month" : `${count} months`;
}

/**
 * The approver role, as a person would say it.
 *
 * Which role is required is decided by ApprovalRouter against the thresholds
 * in the policy version in force. This turns the answer into a phrase and
 * does not work it out.
 */
export function approverLabel(role: string | null | undefined): string {
  switch (role) {
    case "ANALYST":
      return "an analyst";
    case "HEAD_OF_TREASURY":
      return "the Head of Treasury";
    case "CFO":
      return "the CFO";
    default:
      return "—";
  }
}

/**
 * The headroom bar's band.
 *
 * Navy below 85 per cent, amber from 85, red at 100. This is a colour rule
 * from section 10, applied to a utilisation the server computed. The client
 * does not work out headroom.
 */
export function headroomBand(utilisationBp: number | null | undefined): string {
  if (utilisationBp === null || utilisationBp === undefined) return "";
  if (utilisationBp >= 10000) return "full";
  if (utilisationBp >= 8500) return "warm";
  return "";
}

export function utilisationWidth(utilisationBp: number | null | undefined): string {
  if (!utilisationBp || utilisationBp < 0) return "0%";
  return `${Math.min(100, utilisationBp / 100)}%`;
}
