"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, KeyRound, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  consumeActivationToken,
  resolveActivationToken,
  type ActivationResolve,
} from "@/lib/api";
import { startSession } from "@/lib/session";

/**
 * Activation page — public, unauthenticated.
 *
 * The invitee lands here via a link the admin shared out of band.
 * On mount we resolve the token to show "Welcome, Jane Doe — set your
 * password". On submit we consume the token, set the password, and
 * (courtesy of the backend returning a bearer token) sign the user in
 * immediately.
 *
 * ADR-0014 covers the shape.
 */
export default function ActivatePage() {
  return (
    <Suspense
      fallback={
        <ActivateShell>
          <p className="text-xs text-muted-foreground">Loading…</p>
        </ActivateShell>
      }
    >
      <ActivateInner />
    </Suspense>
  );
}

function ActivateInner() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token") ?? "";
  const [resolved, setResolved] = useState<ActivationResolve | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!token) {
      setError("No activation token supplied.");
      return;
    }
    resolveActivationToken(token)
      .then((r) => setResolved(r))
      .catch((e) => setError(String((e as Error).message ?? e)));
  }, [token]);

  const canSubmit =
    !submitting &&
    password.length >= 8 &&
    password === confirm &&
    resolved !== null;

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await consumeActivationToken(token, password);
      startSession(result.token, result.user);
      setDone(true);
      window.setTimeout(() => router.replace("/"), 900);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSubmitting(false);
    }
  };

  if (error && !resolved) {
    return (
      <ActivateShell>
        <div className="rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
        <p className="mt-3 text-[11px] text-muted-foreground">
          Ask an administrator for a fresh activation link.
        </p>
      </ActivateShell>
    );
  }

  if (done) {
    return (
      <ActivateShell>
        <div className="flex items-center gap-2 text-sm text-success">
          <CheckCircle2 className="h-4 w-4" />
          Password set. Signing you in…
        </div>
      </ActivateShell>
    );
  }

  if (!resolved) {
    return (
      <ActivateShell>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> Checking the link…
        </div>
      </ActivateShell>
    );
  }

  const heading =
    resolved.purpose === "RESET"
      ? "Reset your password"
      : "Welcome — set your password";
  const mismatch = confirm.length > 0 && password !== confirm;
  return (
    <ActivateShell>
      <p className="mb-1 text-xs text-muted-foreground">
        For <b>{resolved.email}</b> ({resolved.display_name})
      </p>
      <h1 className="mb-4 text-lg font-semibold">{heading}</h1>

      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div>
          <label className="text-[10.5px] font-medium text-muted-foreground">
            New password (min 8 characters)
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-xs"
            autoFocus
          />
        </div>
        <div>
          <label className="text-[10.5px] font-medium text-muted-foreground">
            Confirm password
          </label>
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className={`mt-1 w-full rounded border bg-background px-2 py-1.5 text-xs ${
              mismatch ? "border-destructive" : "border-border"
            }`}
          />
          {mismatch ? (
            <p className="mt-1 text-[10px] text-destructive">
              Passwords don't match.
            </p>
          ) : null}
        </div>

        {error ? (
          <div className="rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        ) : null}

        <Button
          type="submit"
          size="sm"
          disabled={!canSubmit}
          className="w-full gap-1.5"
        >
          {submitting ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <KeyRound className="h-3 w-3" />
          )}
          {resolved.purpose === "RESET" ? "Reset password" : "Set password and sign in"}
        </Button>

        <p className="text-[10px] text-muted-foreground">
          Link expires {new Date(resolved.expires_at).toLocaleString()}.
          Single-use — after you set your password, the link is retired.
        </p>
      </form>
    </ActivateShell>
  );
}

function ActivateShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-sm rounded-xl border border-border bg-surface-1 p-6 shadow-xl">
        <div className="mb-4 flex items-center gap-2 border-b border-border pb-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/15 text-primary">
            <KeyRound className="h-4 w-4" />
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Treasury Register
            </p>
            <p className="text-xs font-semibold">Account activation</p>
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}
