"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Reveals text one character at a time, so a paragraph reads as the
 * model writing rather than a caption dropped in whole.
 *
 * The response has already arrived; the pacing is client-side. That
 * keeps the effect independent of network jitter, which was the point
 * of the trace-then-reveal flow above it: the reader sees the reasoning
 * play out at a readable speed regardless of when the model returned.
 *
 * Speeds up as the paragraph gets longer, so a two-sentence line and a
 * five-sentence one both feel like the same voice writing. A blinking
 * caret follows the write head until the last character lands.
 */
export function TypedText({
  text,
  charsPerSecond = 65,
  onDone,
  className,
}: {
  text: string;
  charsPerSecond?: number;
  onDone?: () => void;
  className?: string;
}) {
  const [shown, setShown] = useState(0);
  const startedFor = useRef<string | null>(null);

  // A new string resets the writer. Same string, no-op.
  useEffect(() => {
    if (startedFor.current !== text) {
      startedFor.current = text;
      setShown(0);
    }
  }, [text]);

  // Type. The interval scales with length so a very long paragraph
  // doesn't feel like a minute; a short one still gets the rhythm.
  useEffect(() => {
    if (shown >= text.length) {
      if (shown > 0) onDone?.();
      return;
    }
    // Base cadence, tuned in ms.
    const baseMs = 1000 / charsPerSecond;
    // Faster after the first sentence, on the argument that a reader has
    // caught the rhythm and long paragraphs would otherwise stall.
    const boost = shown > 80 ? 0.75 : 1;
    const wait = Math.max(6, baseMs * boost);
    const id = window.setTimeout(() => setShown(shown + 1), wait);
    return () => window.clearTimeout(id);
  }, [shown, text, charsPerSecond, onDone]);

  const done = shown >= text.length;
  return (
    <span className={className}>
      {text.slice(0, shown)}
      {done ? null : (
        <span
          className="inline-block h-[0.9em] w-[0.4em] translate-y-[0.12em] animate-pulse bg-primary/70"
          aria-hidden
        />
      )}
    </span>
  );
}
