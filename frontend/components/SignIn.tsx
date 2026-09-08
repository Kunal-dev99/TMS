"use client";

import { useState } from "react";
import Image from "next/image";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { signIn } from "@/lib/api";
import type { SignedInUser } from "@/lib/session";

/**
 * Signing in.
 *
 * The surface itself does not change: this sits in front of it and nothing
 * behind it knows how the caller was identified.
 *
 * The demonstration accounts are listed on the screen, because this is a
 * prototype with a seeded book and hiding them would only mean somebody has
 * to be told them out loud. They go when Entra ID single sign on arrives,
 * along with the password field.
 */
const DEMO_ACCOUNTS = [
  {
    email: "a.whitfield@northgate.example",
    name: "A. Whitfield",
    role: "Analyst. Proposes deals",
  },
  {
    email: "m.doran@northgate.example",
    name: "M. Doran",
    role: "Head of Treasury. Signs up to the second threshold",
  },
  {
    email: "r.sethi@northgate.example",
    name: "R. Sethi",
    role: "CFO. Signs above it",
  },
];

export function SignIn({ onSignedIn }: { onSignedIn: (user: SignedInUser) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await signIn(email.trim(), password));
    } catch (cause: unknown) {
      setError(
        cause instanceof Error
          ? cause.message
          : "That email address and password do not match an account.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <Image
            src="/fusion-logo.png"
            alt="Fusion Practices"
            width={220}
            height={80}
            priority
            className="mx-auto mb-3 h-20 w-auto"
          />
          <h1 className="text-lg font-semibold">Treasury Register</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            Every action is recorded against the person who took it.
          </p>
        </div>

        <form
          onSubmit={submit}
          className="space-y-3 rounded-lg border border-border bg-card p-5"
        >
          <div className="space-y-1.5">
            <Label htmlFor="email" className="text-xs">
              Email address
            </Label>
            <Input
              id="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="password" className="text-xs">
              Password
            </Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </div>

          {error ? (
            <p className="rounded border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
              {error}
            </p>
          ) : null}

          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "Signing in" : "Sign in"}
          </Button>
        </form>

        <div className="mt-4 rounded-lg border border-dashed border-border bg-surface-2/30 p-3">
          <p className="mb-2 text-[10px] uppercase tracking-wider text-muted-foreground">
            Prototype accounts, password <code>treasury</code>
          </p>
          <ul className="space-y-1.5">
            {DEMO_ACCOUNTS.map((account) => (
              <li key={account.email}>
                <button
                  type="button"
                  className="w-full rounded px-2 py-1 text-left hover:bg-surface-2"
                  onClick={() => {
                    setEmail(account.email);
                    setPassword("treasury");
                  }}
                >
                  <span className="text-[11px] font-medium">{account.name}</span>
                  <span className="block text-[10px] text-muted-foreground">
                    {account.role}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[10px] text-muted-foreground">
            A deal cannot be signed by the person who proposed it, so seeing
            that control needs two of these.
          </p>
        </div>
      </div>
    </main>
  );
}
