"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

/**
 * A floating tooltip that follows the cursor over an area.
 *
 * The tooltip is one element per host, positioned absolutely inside the
 * host's own bounding box. That means it never leaks out of the panel,
 * never fires against a wrong SVG element under a mouse move, and never
 * needs a portal.
 *
 * Usage:
 *   const tip = useFloatingTooltip();
 *   <div ref={tip.hostRef} className="relative">
 *     <svg
 *       onPointerMove={(e) => tip.move(e)}
 *       onPointerLeave={() => tip.hide()}
 *     >
 *       <path
 *         onPointerEnter={(e) => tip.show(e, <YourContent />)}
 *         onPointerLeave={() => tip.hide()}
 *       />
 *     </svg>
 *     {tip.render()}
 *   </div>
 *
 * The content is a React node so a caller can render numbers, tables,
 * badges, whatever they like -- the tooltip does not care about shape.
 */
export function useFloatingTooltip() {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState(false);
  const [content, setContent] = useState<ReactNode>(null);
  const [pos, setPos] = useState({ x: 0, y: 0 });

  const localPoint = useCallback((clientX: number, clientY: number) => {
    const host = hostRef.current;
    if (!host) return { x: 0, y: 0 };
    const rect = host.getBoundingClientRect();
    return { x: clientX - rect.left, y: clientY - rect.top };
  }, []);

  const show = useCallback(
    (event: { clientX: number; clientY: number }, node: ReactNode) => {
      setContent(node);
      setPos(localPoint(event.clientX, event.clientY));
      setVisible(true);
    },
    [localPoint],
  );

  const move = useCallback(
    (event: { clientX: number; clientY: number }) => {
      setPos(localPoint(event.clientX, event.clientY));
    },
    [localPoint],
  );

  const hide = useCallback(() => setVisible(false), []);

  // Hide when the user scrolls or navigates away, so a stale tooltip
  // never lingers over a re-rendered chart.
  useEffect(() => {
    if (!visible) return;
    const off = () => setVisible(false);
    window.addEventListener("scroll", off, true);
    return () => window.removeEventListener("scroll", off, true);
  }, [visible]);

  const render = useCallback(() => {
    if (!visible || !content) return null;
    const host = hostRef.current;
    const width = host?.clientWidth ?? 640;
    const height = host?.clientHeight ?? 400;
    // Anchor top-left of the tooltip 12 px away from the cursor. If the
    // tooltip would fall off the right or bottom edge of the host, flip
    // it to the other side. Estimated size 240 x 130.
    const tw = 240;
    const th = 130;
    let left = pos.x + 12;
    let top = pos.y + 12;
    if (left + tw > width) left = pos.x - tw - 12;
    if (top + th > height) top = pos.y - th - 12;
    if (left < 4) left = 4;
    if (top < 4) top = 4;
    return (
      <div
        role="tooltip"
        aria-live="polite"
        className="pointer-events-none absolute z-40 max-w-[260px] rounded-md border border-border bg-card px-2.5 py-2 text-[10.5px] leading-tight shadow-lg"
        style={{ left, top }}
      >
        {content}
      </div>
    );
  }, [visible, content, pos]);

  return { hostRef, show, move, hide, render };
}


/** Small helpers so hover content reads consistently across charts. */

export function TipTitle({ children }: { children: ReactNode }) {
  return (
    <p className="mb-1 text-[11px] font-semibold text-foreground">{children}</p>
  );
}


export function TipRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: ReactNode;
  tone?: "muted" | "warn" | "success" | "danger";
}) {
  const colour =
    tone === "warn"
      ? "text-warning"
      : tone === "success"
        ? "text-success"
        : tone === "danger"
          ? "text-destructive"
          : "text-foreground";
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-[9.5px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span className={`num text-[10.5px] font-medium ${colour}`}>{value}</span>
    </div>
  );
}


export function TipNote({ children }: { children: ReactNode }) {
  return (
    <p className="mt-1.5 border-t border-border/40 pt-1 text-[9.5px] italic text-muted-foreground">
      {children}
    </p>
  );
}
