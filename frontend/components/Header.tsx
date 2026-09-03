"use client";

import type { StateResponse } from "@/lib/types";
import { shortDate } from "@/lib/format";
import { Header as RedwoodHeader } from "@/components/layout/header";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { Button } from "@/components/ui/button";
import { resetBook, signOut } from "@/lib/api";
import type { SignedInUser } from "@/lib/session";

/**
 * Enterprise Header integrating the Redwood Professional layout header
 * with TMS specific controls (prototype badge, tenant, enforcement, date, reset).
 */
export function Header({
  state,
  user,
  onReset,
  onSignedOut,
}: {
  state: StateResponse | null;
  user?: SignedInUser | null;
  onReset?: () => void;
  onSignedOut?: () => void;
}) {
  return (
    <RedwoodHeader
      title="Treasury Register"
      logoSrc="/brand/logo.png"
      logoAlt="Fusion Practices"
      actions={
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold border status-testing">
            Prototype
          </span>

          {state?.tenant_name ? (
            <span className="hidden sm:inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium border border-border bg-surface-2 text-foreground">
              {state.tenant_name}
            </span>
          ) : null}

          <div className="hidden lg:flex items-center gap-3 text-xs text-muted-foreground pl-2 border-l border-border">
            <span>Today <strong className="text-foreground font-medium">{shortDate(state?.as_of_date)}</strong></span>
            <span>
              Enforcement:{" "}
              <strong className="text-foreground font-medium">
                {state?.enforcement === "WARN_WITH_OVERRIDE"
                  ? "warn with override"
                  : "hard block"}
              </strong>
            </span>
          </div>

          {/* Drop every row and reload the seed. The one place in the
              system where anything is deleted: nothing a user does inside
              the system deletes anything. */}
          <Button
            variant="outline"
            size="sm"
            type="button"
            onClick={() => resetBook().then(() => onReset?.())}
            className="h-7 text-xs px-2.5 text-muted-foreground"
          >
            Reset
          </Button>

          {/* Who is acting. Every write is recorded against this person,
              and a deal they proposed cannot be signed by them. */}
          {user ? (
            <div className="hidden md:flex items-center gap-2 pl-2 border-l border-border">
              <div className="text-right leading-tight">
                <div className="text-[11px] font-medium text-foreground">
                  {user.display_name}
                </div>
                <div className="text-[10px] text-muted-foreground">
                  {user.roles
                    .map((role) => role.replace(/_/g, " ").toLowerCase())
                    .join(", ") || "no role held"}
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                type="button"
                onClick={() => signOut().then(() => onSignedOut?.())}
                className="h-7 text-xs px-2 text-muted-foreground"
              >
                Sign out
              </Button>
            </div>
          ) : null}

          <div className="pl-1 border-l border-border">
            <ThemeToggle />
          </div>
        </div>
      }
    />
  );
}
