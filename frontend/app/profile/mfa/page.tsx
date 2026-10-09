"use client";

/**
 * Profile → MFA.
 *
 * Three states:
 *   1. Not enrolled → "Set up" button → QR + secret + first-code input.
 *   2. First code accepted → recovery codes shown once behind an
 *      acknowledge gate.
 *   3. Already enrolled → status + "Re-issue recovery codes" button.
 *
 * MFA is opt-in today (per-tenant policy default = off). The page is
 * reachable from the Header "Security" link; nobody is forced here.
 *
 * Error surfaces:
 *   - 503 (no mfa_master_key in SecretsPort) → "unavailable in this
 *     environment, contact an administrator".
 *   - 400 wrong code → inline next to the input.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  Check,
  Download,
  KeyRound,
  Loader2,
  QrCode,
  RefreshCcw,
  ShieldCheck,
} from "lucide-react";

import { AppShell } from "@/components/shell/AppShell";
import { PageHeader } from "@/components/shell/PageHeader";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  RequestFailed,
  enrollMfa,
  getMfaStatus,
  reissueRecoveryCodes,
  verifyMfaCode,
  whoAmI,
  type MfaEnrollment,
  type MfaStatus,
} from "@/lib/api";
import { currentUser } from "@/lib/session";

type View =
  | { kind: "loading" }
  | { kind: "signed_out" }
  | { kind: "unavailable"; detail: string }
  | { kind: "status"; status: MfaStatus }
  | { kind: "enrolling"; enrollment: MfaEnrollment; codeError: string | null }
  | { kind: "codes_shown"; codes: string[]; source: "enroll" | "reissue" };

export default function ProfileMfaPage() {
  const router = useRouter();
  const [view, setView] = useState<View>({ kind: "loading" });
  const [busy, setBusy] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const status = await getMfaStatus();
      setView({ kind: "status", status });
    } catch (err) {
      if (err instanceof RequestFailed && err.status === 503) {
        setView({ kind: "unavailable", detail: err.message });
      } else if (err instanceof RequestFailed && err.status === 401) {
        setView({ kind: "signed_out" });
      } else {
        setView({
          kind: "unavailable",
          detail: err instanceof Error ? err.message : "Unknown error",
        });
      }
    }
  }, []);

  useEffect(() => {
    // currentUser() is in-memory only; it's empty after a fresh page
    // navigation even when a token is sitting in sessionStorage. Fall
    // back to whoAmI() which hits /auth/me — if the token is good,
    // this rehydrates the session.
    void (async () => {
      try {
        if (!currentUser()) await whoAmI();
      } catch {
        setView({ kind: "signed_out" });
        return;
      }
      void loadStatus();
    })();
  }, [loadStatus]);

  const startEnroll = async () => {
    setBusy(true);
    try {
      const enrollment = await enrollMfa();
      setView({ kind: "enrolling", enrollment, codeError: null });
    } catch (err) {
      if (err instanceof RequestFailed && err.status === 503) {
        setView({ kind: "unavailable", detail: err.message });
      } else {
        setView((prev) =>
          prev.kind === "enrolling"
            ? { ...prev, codeError: err instanceof Error ? err.message : "Failed to start" }
            : prev,
        );
      }
    } finally {
      setBusy(false);
    }
  };

  const submitFirstCode = async (code: string) => {
    if (view.kind !== "enrolling") return;
    setBusy(true);
    try {
      const result = await verifyMfaCode(code);
      if (!result.verified) {
        setView({ ...view, codeError: "That code didn't match. Try again." });
        return;
      }
      setView({
        kind: "codes_shown",
        codes: result.recovery_codes,
        source: "enroll",
      });
    } catch (err) {
      const msg =
        err instanceof RequestFailed
          ? err.message
          : err instanceof Error
            ? err.message
            : "Verification failed";
      setView({ ...view, codeError: msg });
    } finally {
      setBusy(false);
    }
  };

  const reissue = async () => {
    setBusy(true);
    try {
      const res = await reissueRecoveryCodes();
      setView({ kind: "codes_shown", codes: res.recovery_codes, source: "reissue" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <AppShell>
      <PageHeader
        title="Two-factor authentication"
        icon={ShieldCheck}
        description="Add a second step to sign-in using an authenticator app (Google Authenticator, 1Password, Authy)."
      />
      <div className="mx-auto max-w-[720px] px-4 py-6">
        {view.kind === "loading" ? (
          <LoadingBlock />
        ) : view.kind === "signed_out" ? (
          <SignedOutBlock onSignIn={() => router.push("/")} />
        ) : view.kind === "unavailable" ? (
          <UnavailableBlock detail={view.detail} />
        ) : view.kind === "status" && view.status.enrolled ? (
          <EnrolledBlock
            status={view.status}
            onReissue={reissue}
            busy={busy}
          />
        ) : view.kind === "status" ? (
          <NotEnrolledBlock onStart={startEnroll} busy={busy} />
        ) : view.kind === "enrolling" ? (
          <EnrollingBlock
            enrollment={view.enrollment}
            error={view.codeError}
            busy={busy}
            onSubmit={submitFirstCode}
            onCancel={() => void loadStatus()}
          />
        ) : (
          <RecoveryCodesModal
            codes={view.codes}
            source={view.source}
            onDone={() => void loadStatus()}
          />
        )}
      </div>
    </AppShell>
  );
}

// --- states ---------------------------------------------------------------

function LoadingBlock() {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />
      Loading…
    </div>
  );
}

function SignedOutBlock({ onSignIn }: { onSignIn: () => void }) {
  return (
    <Alert>
      <AlertCircle className="h-4 w-4" />
      <AlertTitle>Sign in first</AlertTitle>
      <AlertDescription className="mt-1 flex items-center justify-between gap-4">
        <span>You need to sign in before configuring MFA.</span>
        <Button size="sm" variant="outline" onClick={onSignIn}>
          Sign in
        </Button>
      </AlertDescription>
    </Alert>
  );
}

function UnavailableBlock({ detail }: { detail: string }) {
  return (
    <Alert variant="destructive">
      <AlertCircle className="h-4 w-4" />
      <AlertTitle>MFA isn&apos;t available in this environment</AlertTitle>
      <AlertDescription className="mt-1 text-xs">
        {detail || "Contact your administrator."}
      </AlertDescription>
    </Alert>
  );
}

function NotEnrolledBlock({
  onStart,
  busy,
}: {
  onStart: () => void;
  busy: boolean;
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-md border border-border bg-surface-1 p-5">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
            <KeyRound className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-medium text-foreground">
              You haven&apos;t set up MFA
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              When your organisation enables MFA for sensitive actions
              (approving a deal, granting a role), you&apos;ll be asked for
              a 6-digit code from your authenticator app. Set it up now
              so you&apos;re not blocked when the policy switches on.
            </p>
          </div>
        </div>
        <div className="mt-4 flex items-center justify-end">
          <Button onClick={onStart} disabled={busy} size="sm">
            {busy ? (
              <>
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                Setting up…
              </>
            ) : (
              "Set up two-factor authentication"
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}

function EnrolledBlock({
  status,
  onReissue,
  busy,
}: {
  status: MfaStatus;
  onReissue: () => void;
  busy: boolean;
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-md border border-border bg-surface-1 p-5">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-success/15 text-success">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-medium text-foreground">
              MFA is active on your account
            </h2>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <dt className="text-muted-foreground">Verified</dt>
              <dd className="text-foreground">{isoShort(status.verified_at)}</dd>
              <dt className="text-muted-foreground">Last used</dt>
              <dd className="text-foreground">
                {status.last_used_at ? isoShort(status.last_used_at) : "—"}
              </dd>
              <dt className="text-muted-foreground">Recovery codes</dt>
              <dd className="text-foreground">
                {status.has_recovery_codes ? "On file" : "None left"}
              </dd>
            </dl>
          </div>
        </div>
      </div>

      <div className="rounded-md border border-border bg-surface-1 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="text-sm font-medium text-foreground">
              Recovery codes
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Issuing a fresh set makes the old codes stop working.
              You&apos;ll see the new codes once; save them somewhere safe.
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={onReissue}
            disabled={busy}
          >
            {busy ? (
              <>
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                Working…
              </>
            ) : (
              <>
                <RefreshCcw className="mr-2 h-3.5 w-3.5" />
                Re-issue recovery codes
              </>
            )}
          </Button>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        To unenroll from MFA, ask an administrator — users can&apos;t drop
        their own MFA from here.
      </p>
    </div>
  );
}

function EnrollingBlock({
  enrollment,
  error,
  busy,
  onSubmit,
  onCancel,
}: {
  enrollment: MfaEnrollment;
  error: string | null;
  busy: boolean;
  onSubmit: (code: string) => void;
  onCancel: () => void;
}) {
  const [code, setCode] = useState("");

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (code.trim().length < 6) return;
    onSubmit(code.trim());
  };

  return (
    <div className="space-y-5">
      <div className="rounded-md border border-border bg-surface-1 p-5">
        <h2 className="text-sm font-medium text-foreground">
          Step 1 — scan this with your authenticator app
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Google Authenticator, 1Password, Authy — any TOTP app works.
        </p>
        <div className="mt-4 flex items-start gap-5">
          <div className="shrink-0">
            {enrollment.qr_data_url ? (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                src={enrollment.qr_data_url}
                alt="QR code — scan with authenticator app"
                width={200}
                height={200}
                className="rounded border border-border bg-white p-2"
              />
            ) : (
              <div className="flex h-[200px] w-[200px] flex-col items-center justify-center gap-2 rounded border border-dashed border-border bg-surface-2 p-3 text-center text-xs text-muted-foreground">
                <QrCode className="h-6 w-6" />
                QR unavailable on this backend.
                <br />
                Paste the key below instead.
              </div>
            )}
          </div>
          <div className="min-w-0 flex-1 space-y-3 text-xs">
            <div>
              <Label className="text-muted-foreground">
                Can&apos;t scan? Enter this key manually
              </Label>
              <code className="mt-1 block break-all rounded border border-border bg-surface-2 p-2 font-mono text-[11px]">
                {enrollment.secret}
              </code>
            </div>
            <p className="text-muted-foreground">
              Issuer:&nbsp;
              <span className="font-medium text-foreground">
                Treasury Register
              </span>
            </p>
          </div>
        </div>
      </div>

      <form
        className="rounded-md border border-border bg-surface-1 p-5"
        onSubmit={submit}
      >
        <h2 className="text-sm font-medium text-foreground">
          Step 2 — enter the 6-digit code
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Open the authenticator app and type the current code for
          &ldquo;Treasury Register&rdquo;.
        </p>
        <div className="mt-3 flex items-start gap-3">
          <Input
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            minLength={6}
            placeholder="123456"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            className="w-32 font-mono tracking-widest"
          />
          <Button type="submit" size="sm" disabled={busy || code.length < 6}>
            {busy ? (
              <>
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                Verifying…
              </>
            ) : (
              "Verify"
            )}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </Button>
        </div>
        {error ? (
          <p
            role="alert"
            className="mt-3 text-xs text-destructive"
          >
            {error}
          </p>
        ) : null}
      </form>
    </div>
  );
}

function RecoveryCodesModal({
  codes,
  source,
  onDone,
}: {
  codes: string[];
  source: "enroll" | "reissue";
  onDone: () => void;
}) {
  const [acknowledged, setAcknowledged] = useState(false);

  const downloadTxt = () => {
    const body =
      [
        "Treasury Register — MFA recovery codes",
        `Generated: ${new Date().toISOString()}`,
        "",
        "Each code works once. Keep them somewhere safe.",
        "",
        ...codes,
      ].join("\n");
    const blob = new Blob([body], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "treasury-register-recovery-codes.txt";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <Dialog open onOpenChange={() => undefined /* no close while unacked */}>
      <DialogContent className="max-w-[520px]">
        <DialogHeader>
          <DialogTitle>
            {source === "enroll"
              ? "MFA active — save these recovery codes"
              : "New recovery codes — the old ones no longer work"}
          </DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground">
          Use one of these codes to sign in if you lose access to your
          authenticator app. Each code works exactly once. We won&apos;t show
          them again.
        </p>
        <div className="mt-2 grid grid-cols-2 gap-2 rounded border border-border bg-surface-2 p-3 font-mono text-[13px]">
          {codes.map((c) => (
            <code key={c} className="select-all">
              {c}
            </code>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={downloadTxt}>
            <Download className="mr-2 h-3.5 w-3.5" />
            Download as .txt
          </Button>
        </div>
        <div className="mt-4 flex items-start gap-2 text-xs">
          <Checkbox
            id="ack-recovery"
            checked={acknowledged}
            onCheckedChange={(v) => setAcknowledged(v === true)}
            className="mt-0.5"
          />
          <Label htmlFor="ack-recovery" className="text-xs leading-snug">
            I have saved my recovery codes in a safe place.
          </Label>
        </div>
        <DialogFooter className="mt-4">
          <Button
            size="sm"
            onClick={onDone}
            disabled={!acknowledged}
          >
            <Check className="mr-2 h-3.5 w-3.5" />
            Continue
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// --- helpers --------------------------------------------------------------

function isoShort(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
