"use client";

import { Sparkles } from "lucide-react";

import type { ScenarioResult } from "@/lib/api";
import { TypedText } from "@/components/panels/TypedText";

/**
 * Renders a what-if result: the model's paragraph on top, the deterministic
 * change list underneath.
 *
 * The layout says which part is which. The paragraph is one voice; the list
 * is what that voice is reading. A treasurer who wants to check the model's
 * work reads the list; one who wants the summary reads the paragraph. Both
 * are on the same card.
 */
export function ScenarioResultCard({ result }: { result: ScenarioResult }) {
  return (
    <div className="mt-3 rounded-lg border border-primary/30 bg-primary/5 p-3">
      <div className="mb-2 flex items-center gap-1.5">
        <Sparkles className="h-3 w-3 text-primary" aria-hidden />
        <span className="text-[9px] font-medium uppercase tracking-wider text-primary">
          What would happen
        </span>
        <span className="ml-auto text-[9px] italic text-muted-foreground">
          drafted just now
        </span>
      </div>

      {result.narrative ? (
        <p className="text-xs leading-relaxed text-foreground">
          <TypedText text={result.narrative} />
        </p>
      ) : null}

      {result.changes.length > 0 ? (
        <div className="mt-3 border-t border-primary/20 pt-2">
          <p className="mb-1 text-[9px] font-medium uppercase tracking-wider text-muted-foreground">
            The deterministic figures the paragraph reads
          </p>
          <ul className="space-y-0.5">
            {result.changes.map((line, index) => (
              <li
                key={index}
                className="text-[10.5px] leading-snug text-muted-foreground"
              >
                {"• "}
                {line}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
