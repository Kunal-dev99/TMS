"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { perCent, sterling } from "@/lib/format";
import type { BookRow, ExposureView } from "@/lib/types";

/**
 * The exposure dial.
 *
 * A rotating disc whose sections are proportionate to what is actually held,
 * and which drills from a credit group into the counterparties inside it.
 *
 * Two rules it has to keep.
 *
 * Every figure comes from the server. The wedge angles are the only
 * arithmetic here, and an angle is a drawing instruction rather than a
 * number a treasurer reads. The moment this file works out a headroom or a
 * utilisation, it has become a second implementation of the limit
 * arithmetic.
 *
 * Nothing depends on motion to be understood. The disc rotates the selected
 * section to the pointer, but the selection is also stated in the centre, in
 * the legend, and in the accessible name of every wedge. Under reduced
 * motion the rotation is instant and nothing is lost.
 *
 * Colour means distance from a limit, not identity. Section 10 of document 3
 * gives the palette its meanings and a categorical colour per group would
 * take one of them away, so groups are told apart by size and label, and the
 * hue only changes as a group approaches the concentration cap.
 */

const SIZE = 280;
const CENTRE = SIZE / 2;
const OUTER = 128;
const INNER = 92;
const SUB_OUTER = 86;
const SUB_INNER = 58;

/** Below this a wedge is too thin to be a click target worth offering. */
const MIN_DEGREES = 1.2;

type Wedge = {
  key: string;
  label: string;
  amountPence: number;
  /** Share of the portfolio, in basis points. Computed by the server. */
  shareBp: number;
  /** Utilisation against this section's own limit, when it has one. */
  utilisationBp: number | null;
  limitPence: number | null;
  start: number;
  end: number;
  cash?: boolean;
};

function polar(cx: number, cy: number, radius: number, degrees: number) {
  const radians = ((degrees - 90) * Math.PI) / 180;
  return { x: cx + radius * Math.cos(radians), y: cy + radius * Math.sin(radians) };
}

function donutSegment(
  radiusOuter: number,
  radiusInner: number,
  start: number,
  end: number,
) {
  // A full circle cannot be drawn as one arc, so a lone section is nudged
  // just short of 360 degrees. The gap is invisible and the alternative is
  // a wedge that vanishes.
  const sweep = Math.min(end - start, 359.99);
  const finish = start + sweep;
  const largeArc = sweep > 180 ? 1 : 0;

  const outerStart = polar(CENTRE, CENTRE, radiusOuter, start);
  const outerEnd = polar(CENTRE, CENTRE, radiusOuter, finish);
  const innerEnd = polar(CENTRE, CENTRE, radiusInner, finish);
  const innerStart = polar(CENTRE, CENTRE, radiusInner, start);

  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${radiusOuter} ${radiusOuter} 0 ${largeArc} 1 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerEnd.x} ${innerEnd.y}`,
    `A ${radiusInner} ${radiusInner} 0 ${largeArc} 0 ${innerStart.x} ${innerStart.y}`,
    "Z",
  ].join(" ");
}

/**
 * Distance from the cap, as a class.
 *
 * The same three bands as the headroom bar in section 10: quiet below 85 per
 * cent of the ceiling, amber from 85, red at or over it. A group at 44 per
 * cent of a 50 per cent cap is at 88 per cent of its ceiling and should look
 * like it.
 */
function pressure(utilisationBp: number | null): "quiet" | "warm" | "full" {
  if (utilisationBp === null) return "quiet";
  if (utilisationBp >= 10000) return "full";
  if (utilisationBp >= 8500) return "warm";
  return "quiet";
}

const FILL: Record<string, string> = {
  quiet: "var(--dial-quiet)",
  warm: "var(--dial-warm)",
  full: "var(--dial-full)",
};

export function ExposureDial({
  view,
  book,
  capBp,
  onPick,
}: {
  view: ExposureView;
  book: BookRow[];
  /** The concentration cap from the policy version in force. */
  capBp: number;
  onPick: (counterpartyId: string) => void;
}) {
  const [groupKey, setGroupKey] = useState<string | null>(null);
  const [focused, setFocused] = useState(0);
  const [reducedMotion, setReducedMotion] = useState(false);
  const disc = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(query.matches);
    const listen = (event: MediaQueryListEvent) => setReducedMotion(event.matches);
    query.addEventListener("change", listen);
    return () => query.removeEventListener("change", listen);
  }, []);

  const total = view.portfolio_total_pence;

  /** The outer ring: every credit group, plus the cash nobody has invested. */
  const groups = useMemo<Wedge[]>(() => {
    const rows = view.by_group
      .filter((row) => row.used_pence > 0)
      .map((row) => ({
        key: row.key,
        label: row.label,
        amountPence: row.used_pence,
        shareBp: total ? Math.round((row.used_pence * 10000) / total) : 0,
        utilisationBp: row.utilisation_bp,
        limitPence: row.limit_pence,
      }));

    if (view.uninvested_cash_pence > 0) {
      rows.push({
        key: "__cash",
        label: "Uninvested cash",
        amountPence: view.uninvested_cash_pence,
        shareBp: total
          ? Math.round((view.uninvested_cash_pence * 10000) / total)
          : 0,
        utilisationBp: null,
        limitPence: null,
        cash: true,
      } as Wedge);
    }

    rows.sort((a, b) => b.amountPence - a.amountPence);

    let cursor = 0;
    return rows.map((row) => {
      const degrees = total ? (row.amountPence / total) * 360 : 0;
      const wedge = { ...row, start: cursor, end: cursor + degrees } as Wedge;
      cursor += degrees;
      return wedge;
    });
  }, [view, total]);

  /**
   * The subsections: the counterparties inside the selected group.
   *
   * They are laid out across their parent's arc, so a name occupies the same
   * share of the group that the group occupies of the portfolio. The two
   * rings are then reading the same units at two depths.
   */
  const subsections = useMemo<Wedge[]>(() => {
    const parent = groups.find((wedge) => wedge.key === groupKey);
    if (!parent || parent.cash) return [];

    const members = book
      .filter((row) => row.group_id === groupKey && row.used_pence > 0)
      .sort((a, b) => b.used_pence - a.used_pence);

    const held = members.reduce((sum, row) => sum + row.used_pence, 0) || 1;
    const span = parent.end - parent.start;
    let cursor = parent.start;

    return members.map((row) => {
      const degrees = (row.used_pence / held) * span;
      const wedge: Wedge = {
        key: row.counterparty_id,
        label: row.name,
        amountPence: row.used_pence,
        shareBp: total ? Math.round((row.used_pence * 10000) / total) : 0,
        utilisationBp: row.utilisation_bp,
        limitPence: row.limit_pence,
        start: cursor,
        end: cursor + degrees,
      };
      cursor += degrees;
      return wedge;
    });
  }, [groups, groupKey, book, total]);

  const ring = groupKey ? subsections : groups;
  const selected = ring[Math.min(focused, Math.max(0, ring.length - 1))];

  /** Rotate so the focused section sits under the pointer at the top. */
  const rotation = selected ? -((selected.start + selected.end) / 2) : 0;

  const parent = groups.find((wedge) => wedge.key === groupKey) ?? null;

  const step = (delta: number) => {
    if (ring.length === 0) return;
    setFocused((current) => (current + delta + ring.length) % ring.length);
  };

  const drillIn = () => {
    if (!selected) return;
    if (groupKey) {
      onPick(selected.key);
      return;
    }
    if (selected.cash) return;
    setGroupKey(selected.key);
    setFocused(0);
  };

  const drillOut = () => {
    if (!groupKey) return;
    const index = groups.findIndex((wedge) => wedge.key === groupKey);
    setGroupKey(null);
    setFocused(index < 0 ? 0 : index);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    // Escape belongs to the panel shell, which closes the whole panel. The
    // dial takes Backspace for stepping back out, so the two do not fight.
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      step(1);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      step(-1);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      drillIn();
    } else if (event.key === "Backspace") {
      event.preventDefault();
      drillOut();
    }
  };

  const transition = reducedMotion ? "none" : "transform 480ms cubic-bezier(.22,.61,.36,1)";

  return (
    <div className="space-y-4">
      <style>{`
        :root {
          --dial-quiet: color-mix(in srgb, hsl(var(--primary)) 78%, transparent);
          --dial-warm: color-mix(in srgb, hsl(var(--warning)) 82%, transparent);
          --dial-full: color-mix(in srgb, hsl(var(--destructive)) 82%, transparent);
        }
      `}</style>

      <div className="flex flex-col items-center">
        <svg
          ref={disc}
          width={SIZE}
          height={SIZE}
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          tabIndex={0}
          role="listbox"
          aria-label={
            groupKey
              ? `Counterparties in ${parent?.label ?? "the group"}`
              : "Credit groups by share of the portfolio"
          }
          onKeyDown={onKeyDown}
          className="rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {/* The pointer. Fixed at the top, so the disc turns and the
              reference does not. */}
          <path
            d={`M ${CENTRE} 6 l 6 11 l -12 0 Z`}
            fill="hsl(var(--foreground))"
            opacity="0.55"
          />

          <g
            style={{
              transform: `rotate(${rotation}deg)`,
              transformOrigin: `${CENTRE}px ${CENTRE}px`,
              transition,
            }}
          >
            {/* The outer band is always every credit group. Drilling in
                dims it rather than replacing it: a ring drawn across one
                group's arc alone reads as a broken circle, and the whole
                point of a proportionate disc is that the proportions stay
                on screen. */}
            {groups.map((wedge, index) => {
              const isSelected = !groupKey && selected?.key === wedge.key;
              const isParent = groupKey === wedge.key;
              const tooThin = wedge.end - wedge.start < MIN_DEGREES;
              return (
                <path
                  key={wedge.key}
                  d={donutSegment(
                    isSelected || isParent ? OUTER + 6 : OUTER,
                    INNER,
                    wedge.start,
                    wedge.end,
                  )}
                  fill={FILL[pressure(wedge.utilisationBp)]}
                  opacity={isSelected ? 1 : isParent ? 0.75 : groupKey ? 0.18 : 0.45}
                  stroke="hsl(var(--card))"
                  strokeWidth="1.5"
                  role={groupKey ? undefined : "option"}
                  aria-selected={groupKey ? undefined : isSelected}
                  aria-label={
                    groupKey
                      ? undefined
                      : `${wedge.label}, ${sterling(wedge.amountPence)}, ${perCent(wedge.shareBp)} of the portfolio`
                  }
                  aria-hidden={groupKey ? true : undefined}
                  style={{
                    cursor: tooThin ? "default" : "pointer",
                    transition: reducedMotion ? "none" : "opacity 200ms",
                  }}
                  onClick={() => {
                    if (groupKey) {
                      // Clicking another group from inside one moves across
                      // rather than stacking a second level.
                      if (wedge.key !== groupKey && !wedge.cash) {
                        setGroupKey(wedge.key);
                        setFocused(0);
                      }
                      return;
                    }
                    setFocused(index);
                    if (selected?.key === wedge.key) drillIn();
                  }}
                />
              );
            })}

            {/* The subsections sit inside their parent's arc, so a name
                holds the same share of the group that the group holds of
                the portfolio. Two rings, one unit, two depths. */}
            {groupKey
              ? subsections.map((wedge, index) => {
                  const isSelected = selected?.key === wedge.key;
                  return (
                    <path
                      key={`sub-${wedge.key}`}
                      d={donutSegment(
                        isSelected ? SUB_OUTER + 4 : SUB_OUTER,
                        SUB_INNER,
                        wedge.start,
                        wedge.end,
                      )}
                      fill={FILL[pressure(wedge.utilisationBp)]}
                      opacity={isSelected ? 1 : 0.45}
                      stroke="hsl(var(--card))"
                      strokeWidth="1.5"
                      role="option"
                      aria-selected={isSelected}
                      aria-label={`${wedge.label}, ${sterling(wedge.amountPence)}, ${perCent(wedge.shareBp)} of the portfolio`}
                      style={{
                        cursor: "pointer",
                        transition: reducedMotion ? "none" : "opacity 200ms",
                      }}
                      onClick={() => {
                        setFocused(index);
                        if (isSelected) onPick(wedge.key);
                      }}
                    />
                  );
                })
              : null}
          </g>

          {/* The centre states the selection, so nothing depends on having
              watched the disc turn. */}
          <foreignObject
            x={CENTRE - 54}
            y={CENTRE - 40}
            width="108"
            height="80"
            style={{ pointerEvents: "none" }}
          >
            <div className="flex h-full flex-col items-center justify-center text-center">
              <p className="text-[9px] uppercase leading-tight tracking-wider text-muted-foreground">
                {selected ? selected.label : "Portfolio"}
              </p>
              <p className="num mt-0.5 text-sm font-semibold leading-none">
                {sterling(selected ? selected.amountPence : total)}
              </p>
              <p className="mt-1 text-[9px] leading-tight text-muted-foreground">
                {selected
                  ? `${perCent(selected.shareBp)} of the book`
                  : `cap ${perCent(capBp)}`}
              </p>
            </div>
          </foreignObject>
        </svg>

        <p className="mt-2 text-[10px] text-muted-foreground">
          Arrow keys turn the dial. Enter opens a section. Backspace steps back.
        </p>
      </div>

      {/* Where the selection is stated in words. A wedge is a proportion; the
          figures a treasurer acts on are here. */}
      <div className="rounded-lg border border-border bg-surface-2/30 p-3">
        <div className="flex items-center gap-2">
          {groupKey ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-6 gap-1 px-1.5 text-[10px]"
              onClick={drillOut}
            >
              <ChevronLeft className="h-3 w-3" />
              {parent?.label}
            </Button>
          ) : (
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Credit groups
            </span>
          )}
        </div>

        {selected ? (
          <div className="mt-2 space-y-1.5">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-sm font-medium">{selected.label}</span>
              <span className="num text-sm">{sterling(selected.amountPence)}</span>
            </div>

            {selected.limitPence !== null ? (
              <p className="text-[10px] text-muted-foreground">
                {perCent(selected.utilisationBp)} of a{" "}
                {sterling(selected.limitPence)} limit.
              </p>
            ) : selected.cash ? (
              <p className="text-[10px] text-muted-foreground">
                Sitting in the operating account. It counts towards the
                portfolio, because a concentration figure that ignores it
                measures the wrong denominator.
              </p>
            ) : null}

            {!selected.cash ? (
              <p className="text-[10px] text-muted-foreground">
                {perCent(selected.shareBp)} of the portfolio, against a
                concentration cap of {perCent(capBp)}.
              </p>
            ) : null}

            <div className="pt-1">
              {groupKey ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs"
                  onClick={() => onPick(selected.key)}
                >
                  Load into the ticket
                </Button>
              ) : selected.cash ? null : (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs"
                  onClick={drillIn}
                >
                  Open {selected.label}
                </Button>
              )}
            </div>
          </div>
        ) : (
          <p className="mt-2 text-xs text-muted-foreground">Nothing held.</p>
        )}
      </div>
    </div>
  );
}
