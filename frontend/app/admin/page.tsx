"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Building2,
  Cog,
  Copy,
  KeyRound,
  Loader2,
  Pencil,
  Plus,
  ShieldCheck,
  UserPlus,
  X,
} from "lucide-react";

import { PageShell } from "@/components/PageShell";
import { Button } from "@/components/ui/button";
import {
  approveAdminAccessChange,
  getAdminTenant,
  inviteAdminUser,
  listAdminAccessChanges,
  listAdminLegalEntities,
  listAdminRoles,
  listAdminUsers,
  rejectAdminAccessChange,
  resetAdminUserPassword,
  updateAdminUser,
  updateAdminUserScope,
  whoAmI,
  type AdminAccessChange,
  type AdminInviteResponse,
  type AdminLegalEntity,
  type AdminRoleRow,
  type AdminTenantView,
  type AdminUserRow,
} from "@/lib/api";
import { currentUser, hasRole } from "@/lib/session";

/**
 * Admin page — Track 1, Week 1-2.
 *
 * Users list + invite modal + edit-user panel + roles catalogue +
 * tenant settings. Every mutation writes an audit_event server-side.
 * Gated: only users with the ADMIN role see this route.
 */
export default function AdminPage() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [users, setUsers] = useState<AdminUserRow[] | null>(null);
  const [roles, setRoles] = useState<AdminRoleRow[]>([]);
  const [tenant, setTenant] = useState<AdminTenantView | null>(null);
  const [entities, setEntities] = useState<AdminLegalEntity[]>([]);
  const [accessChanges, setAccessChanges] = useState<AdminAccessChange[]>([]);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteResult, setInviteResult] = useState<AdminInviteResponse | null>(null);
  const [editing, setEditing] = useState<AdminUserRow | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [u, r, t, e, ac] = await Promise.all([
        listAdminUsers(),
        listAdminRoles(),
        getAdminTenant(),
        listAdminLegalEntities(),
        listAdminAccessChanges(),
      ]);
      setUsers(u);
      setRoles(r);
      setTenant(t);
      setEntities(e);
      setAccessChanges(ac);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }, []);

  // Sign-in gate + role gate.
  useEffect(() => {
    (async () => {
      try {
        const me = currentUser() ?? (await whoAmI());
        if (!me) {
          router.replace("/");
          return;
        }
        if (!hasRole("ADMIN")) {
          router.replace("/");
          return;
        }
        await load();
      } finally {
        setChecking(false);
      }
    })();
  }, [router, load]);

  if (checking) {
    return (
      <PageShell title="Admin" icon={Cog}>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> Checking access…
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell
      title="Admin"
      description="Users, roles, and tenant settings for this workspace. Every change is written to the audit trail."
      icon={Cog}
    >
      {error ? (
        <div className="mb-4 rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      ) : null}

      <div className="space-y-6">
        {tenant ? <TenantCard tenant={tenant} /> : null}

        {entities.length > 0 ? <LegalEntitiesCard entities={entities} /> : null}

        <AccessChangesCard
          items={accessChanges}
          currentDisplayName={currentUser()?.display_name ?? ""}
          onReviewed={load}
        />

        <section>
          <div className="mb-2 flex items-baseline justify-between">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Users
            </h2>
            <Button
              size="sm"
              className="h-7 gap-1.5 text-xs"
              onClick={() => {
                setInviteOpen(true);
                setInviteResult(null);
              }}
            >
              <UserPlus className="h-3 w-3" /> Invite user
            </Button>
          </div>
          <UsersTable
            users={users}
            entities={entities}
            onEdit={(u) => setEditing(u)}
          />
        </section>

        <RolesCard roles={roles} />
      </div>

      <InviteModal
        open={inviteOpen}
        roles={roles}
        result={inviteResult}
        onSubmitted={(res) => {
          setInviteResult(res);
          load();
        }}
        onClose={() => {
          setInviteOpen(false);
          setInviteResult(null);
        }}
      />

      <EditUserPanel
        user={editing}
        roles={roles}
        entities={entities}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          load();
        }}
      />
    </PageShell>
  );
}

// ---------------------------------------------------------------- tenant

function TenantCard({ tenant }: { tenant: AdminTenantView }) {
  return (
    <section>
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Workspace
      </h2>
      <div className="grid grid-cols-1 gap-3 rounded-lg border border-border bg-card p-4 sm:grid-cols-4">
        <div className="flex items-start gap-2 sm:col-span-2">
          <div className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-md bg-primary/15 text-primary">
            <Building2 className="h-4 w-4" />
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Tenant name
            </p>
            <p className="text-sm font-semibold text-foreground">{tenant.name}</p>
            <p className="text-[10px] text-muted-foreground">{tenant.id}</p>
          </div>
        </div>
        <Field label="Base currency" value={tenant.base_currency} />
        <Field label="Book clock (as of)" value={tenant.as_of_date} />
      </div>
    </section>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="num text-sm font-semibold text-foreground">{value}</p>
    </div>
  );
}

// ---------------------------------------------------------------- users

function UsersTable({
  users,
  entities,
  onEdit,
}: {
  users: AdminUserRow[] | null;
  entities: AdminLegalEntity[];
  onEdit: (u: AdminUserRow) => void;
}) {
  if (users === null) {
    return (
      <div className="rounded border border-border bg-card p-3 text-xs text-muted-foreground">
        Loading…
      </div>
    );
  }
  if (users.length === 0) {
    return (
      <div className="rounded border border-dashed border-border bg-surface-2/40 p-3 text-xs text-muted-foreground">
        No users. Click <b>Invite user</b> to add one.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-xs border-collapse">
        <thead>
          <tr className="border-b border-border bg-surface-2/60 text-[10px] uppercase font-semibold text-muted-foreground">
            <th className="py-2 px-3">User</th>
            <th className="py-2 px-3">Roles</th>
            <th className="py-2 px-3">Company access</th>
            <th className="py-2 px-3">Status</th>
            <th className="py-2 px-3">Last signed in</th>
            <th className="py-2 px-3">Invited</th>
            <th className="py-2 px-3 text-right">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/40">
          {users.map((u) => (
            <tr key={u.id} className="hover:bg-muted/30">
              <td className="py-2 px-3">
                <div className="font-medium">{u.display_name}</div>
                <div className="text-[10.5px] text-muted-foreground">{u.email}</div>
              </td>
              <td className="py-2 px-3">
                <div className="flex flex-wrap gap-1">
                  {u.roles.length === 0 ? (
                    <span className="text-[10.5px] italic text-muted-foreground">
                      no roles
                    </span>
                  ) : (
                    u.roles.map((r) => (
                      <span
                        key={r}
                        className="rounded-full border border-border/60 bg-surface-2/60 px-1.5 py-0.5 text-[10px] font-medium"
                      >
                        {r.replace(/_/g, " ")}
                      </span>
                    ))
                  )}
                </div>
                {u.effective_access ? (
                  <EffectiveAccessSummary access={u.effective_access} />
                ) : null}
              </td>
              <td className="py-2 px-3">
                <ScopeCell scope={u.scope} entities={entities} />
              </td>
              <td className="py-2 px-3">
                <span
                  className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                    u.status === "ACTIVE"
                      ? "bg-success/15 text-success border border-success/30"
                      : "bg-muted text-muted-foreground border border-border/60"
                  }`}
                >
                  {u.status}
                </span>
                {u.pending_activation ? (
                  <span
                    className="ml-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider border border-warning/40 bg-warning/10 text-warning"
                    title="An activation link has been issued but not yet consumed."
                  >
                    Pending activation
                  </span>
                ) : null}
                {u.pending_role_grants && u.pending_role_grants.length > 0 ? (
                  <span
                    className="ml-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider border border-warning/40 bg-warning/10 text-warning"
                    title="Sensitive role grants awaiting a second admin's approval."
                  >
                    Pending: {u.pending_role_grants.join(", ")}
                  </span>
                ) : null}
              </td>
              <td className="py-2 px-3 num text-[10.5px] text-muted-foreground">
                {u.last_signed_in_at
                  ? new Date(u.last_signed_in_at).toLocaleString()
                  : "—"}
              </td>
              <td className="py-2 px-3 text-[10.5px] text-muted-foreground">
                {u.invited_by_display ? (
                  <>
                    by <b>{u.invited_by_display}</b>
                    <br />
                    <span className="text-[9.5px]">
                      {u.invited_at
                        ? new Date(u.invited_at).toLocaleDateString()
                        : ""}
                    </span>
                  </>
                ) : (
                  "—"
                )}
              </td>
              <td className="py-2 px-3 text-right">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-6 gap-1 px-2 text-[10.5px]"
                  onClick={() => onEdit(u)}
                >
                  <Pencil className="h-2.5 w-2.5" /> Edit
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- roles catalogue

function RolesCard({ roles }: { roles: AdminRoleRow[] }) {
  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Roles catalogue
        </h2>
        <span className="text-[10px] italic text-muted-foreground">
          each role holds an explicit set of permissions the backend enforces
        </span>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {roles.map((r) => (
          <div
            key={r.role}
            className="rounded-lg border border-border bg-surface-2/40 p-3"
          >
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-semibold">{r.label}</span>
              <span className="text-[9.5px] text-muted-foreground font-mono">
                {r.role}
              </span>
            </div>
            <p className="mt-1 text-[10.5px] leading-relaxed text-muted-foreground">
              {r.description}
            </p>
            {r.can && r.can.length > 0 ? (
              <ul className="mt-1.5 space-y-0.5">
                {r.can.map((phrase) => (
                  <li
                    key={phrase}
                    className="flex items-start gap-1.5 text-[10.5px] leading-snug text-foreground/80"
                  >
                    <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-success" />
                    <span>Can {phrase}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-[10.5px] italic text-muted-foreground">
                (no permissions granted)
              </p>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

// -------------------------------------------- effective access summary

function EffectiveAccessSummary({
  access,
}: {
  access: { can: string[]; cannot: string[] };
}) {
  const [expanded, setExpanded] = useState(false);
  const short = access.can.slice(0, 3);
  const rest = access.can.length - short.length;
  return (
    <div className="mt-1 text-[10px] text-muted-foreground leading-snug">
      {access.can.length === 0 ? (
        <span className="italic">No effective permissions.</span>
      ) : (
        <>
          <span className="text-foreground/80">Can </span>
          {(expanded ? access.can : short).join(" · ")}
          {!expanded && rest > 0 ? (
            <button
              type="button"
              onClick={() => setExpanded(true)}
              className="ml-1 font-medium text-primary hover:underline"
            >
              +{rest} more
            </button>
          ) : null}
          {expanded ? (
            <>
              <br />
              <span className="text-foreground/60">Cannot </span>
              {access.cannot.join(" · ")}
              <button
                type="button"
                onClick={() => setExpanded(false)}
                className="ml-1 font-medium text-primary hover:underline"
              >
                less
              </button>
            </>
          ) : null}
        </>
      )}
    </div>
  );
}

// -------------------------------------------- access-change queue

/**
 * Pending sensitive-access requests awaiting a second admin.
 *
 * Requester != reviewer is enforced server-side; here the UI just
 * hides Approve/Reject on rows the current admin requested and shows
 * a "you requested this" note instead. Rejection needs a reason,
 * approval doesn't (reason is optional context).
 */
function AccessChangesCard({
  items,
  currentDisplayName,
  onReviewed,
}: {
  items: AdminAccessChange[];
  currentDisplayName: string;
  onReviewed: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");

  const approve = async (id: string) => {
    setBusy(id);
    setError(null);
    try {
      await approveAdminAccessChange(id);
      onReviewed();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  const reject = async (id: string) => {
    if (!rejectReason.trim()) return;
    setBusy(id);
    setError(null);
    try {
      await rejectAdminAccessChange(id, rejectReason.trim());
      setRejecting(null);
      setRejectReason("");
      onReviewed();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Pending access changes
        </h2>
        <span className="text-[10px] italic text-muted-foreground">
          sensitive role grants — a different admin must approve (ADR-0015)
        </span>
      </div>

      {items.length === 0 ? (
        <div className="rounded border border-dashed border-border bg-surface-2/40 p-3 text-xs text-muted-foreground">
          No pending access changes.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-border bg-surface-2/60 text-[10px] uppercase font-semibold text-muted-foreground">
                <th className="py-2 px-3">Change</th>
                <th className="py-2 px-3">Subject</th>
                <th className="py-2 px-3">Requested by</th>
                <th className="py-2 px-3">When</th>
                <th className="py-2 px-3 text-right">Review</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {items.map((r) => {
                const isOwn = r.requested_by_display === currentDisplayName;
                const roleName =
                  r.change_type === "role.grant"
                    ? String(r.payload.role ?? "")
                    : r.change_type;
                return (
                  <tr key={r.id}>
                    <td className="py-2 px-3">
                      <span className="rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-warning">
                        Grant {roleName}
                      </span>
                    </td>
                    <td className="py-2 px-3">{r.subject_display}</td>
                    <td className="py-2 px-3">{r.requested_by_display}</td>
                    <td className="py-2 px-3 num text-[10.5px] text-muted-foreground">
                      {new Date(r.requested_at).toLocaleString()}
                    </td>
                    <td className="py-2 px-3 text-right">
                      {isOwn ? (
                        <span className="text-[10.5px] italic text-muted-foreground">
                          You requested this — another admin must review.
                        </span>
                      ) : rejecting === r.id ? (
                        <div className="flex items-center justify-end gap-1.5">
                          <input
                            type="text"
                            placeholder="Reason (required)"
                            value={rejectReason}
                            onChange={(e) => setRejectReason(e.target.value)}
                            className="w-40 rounded border border-border bg-background px-2 py-0.5 text-[11px]"
                            autoFocus
                          />
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-6 px-2 text-[10.5px]"
                            onClick={() => {
                              setRejecting(null);
                              setRejectReason("");
                            }}
                          >
                            Cancel
                          </Button>
                          <Button
                            size="sm"
                            className="h-6 px-2 text-[10.5px]"
                            disabled={!rejectReason.trim() || busy === r.id}
                            onClick={() => reject(r.id)}
                          >
                            {busy === r.id ? (
                              <Loader2 className="h-2.5 w-2.5 animate-spin" />
                            ) : null}
                            Confirm reject
                          </Button>
                        </div>
                      ) : (
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-6 px-2 text-[10.5px]"
                            onClick={() => setRejecting(r.id)}
                            disabled={busy === r.id}
                          >
                            Reject
                          </Button>
                          <Button
                            size="sm"
                            className="h-6 px-2 text-[10.5px]"
                            onClick={() => approve(r.id)}
                            disabled={busy === r.id}
                          >
                            {busy === r.id ? (
                              <Loader2 className="h-2.5 w-2.5 animate-spin" />
                            ) : null}
                            Approve
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {error ? (
        <div className="mt-2 rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      ) : null}
    </section>
  );
}

// -------------------------------------------- activation link card
//
// Rendered after invite + reset. The admin copies the link (or the
// full URL joined onto window.location.origin) and shares it out of
// band — the invitee visits /activate?token=... to set their own
// password. Neither the admin nor Treasury Register sees the password.

function ActivationLinkCard({
  email,
  activationUrl,
  expiresAt,
  note,
  variant = "invite",
}: {
  email: string;
  activationUrl: string;
  expiresAt: string;
  note: string;
  variant?: "invite" | "reset";
}) {
  const [copied, setCopied] = useState(false);
  const fullUrl = useMemo(() => {
    if (typeof window === "undefined") return activationUrl;
    return `${window.location.origin}${activationUrl}`;
  }, [activationUrl]);
  const label = variant === "reset" ? "Password reset" : `Invited ${email}`;
  const expires = new Date(expiresAt).toLocaleString();
  return (
    <div className="rounded border border-success/40 bg-success/10 p-3 text-xs">
      <p className="font-semibold text-success">{label}</p>
      <p className="mt-1 leading-relaxed text-foreground/80">{note}</p>
      <div className="mt-2 flex items-center gap-2 rounded border border-border bg-background px-2 py-1.5">
        <KeyRound className="h-3 w-3 shrink-0 text-muted-foreground" />
        <code className="flex-1 truncate font-mono text-[10.5px]">{fullUrl}</code>
        <button
          type="button"
          onClick={() => {
            navigator.clipboard.writeText(fullUrl);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1200);
          }}
          className="rounded p-1 text-muted-foreground hover:bg-surface-2 hover:text-foreground"
          title="Copy link"
        >
          <Copy className="h-3 w-3" />
        </button>
      </div>
      <p className="mt-1 text-[10px] text-muted-foreground">
        {copied ? "Copied ✓ " : ""}Expires {expires}. Single-use.
      </p>
    </div>
  );
}

// -------------------------------------------- scope cell + entities

function ScopeCell({
  scope,
  entities,
}: {
  scope: { group_wide: boolean; entity_ids: string[]; summary: string };
  entities: AdminLegalEntity[];
}) {
  if (scope.group_wide) {
    return (
      <span className="inline-block rounded-full border border-primary/30 bg-primary/[.08] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-primary">
        Group-wide
      </span>
    );
  }
  if (scope.entity_ids.length === 0) {
    return (
      <span className="text-[10.5px] italic text-destructive/80">
        No entity access
      </span>
    );
  }
  const codes = entities
    .filter((e) => scope.entity_ids.includes(e.id))
    .map((e) => e.code);
  return (
    <div className="flex flex-wrap gap-1">
      {codes.map((c) => (
        <span
          key={c}
          className="rounded border border-border bg-surface-2/60 px-1.5 py-0.5 text-[10px] font-mono font-medium"
        >
          {c}
        </span>
      ))}
      <span className="text-[10px] text-muted-foreground self-center">
        ({codes.length} of {entities.length})
      </span>
    </div>
  );
}

function LegalEntitiesCard({ entities }: { entities: AdminLegalEntity[] }) {
  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Legal entities
        </h2>
        <span className="text-[10px] italic text-muted-foreground">
          your own corporate subsidiaries — distinct from counterparties (banks) and from the tenant
        </span>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {entities.map((e) => (
          <div
            key={e.id}
            className="rounded-lg border border-border bg-surface-2/40 p-3"
          >
            <div className="flex items-baseline justify-between">
              <span className="text-xs font-semibold text-foreground">{e.name}</span>
              <span className="text-[9.5px] font-mono text-muted-foreground">
                {e.code}
              </span>
            </div>
            <p className="mt-1 text-[10.5px] text-muted-foreground">
              Base <b>{e.base_currency}</b>
              {e.country ? ` · ${e.country}` : ""} · {e.status.toLowerCase()}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

// -------------------------------------------- role change preview

function RoleChangePreview({
  roles,
  currentRoles,
  selectedRoles,
  currentAccess,
}: {
  roles: AdminRoleRow[];
  currentRoles: string[];
  selectedRoles: string[];
  currentAccess: { held: string[]; can: string[] };
}) {
  // Compute the effective can-list from the selected roles by unioning
  // the permission strings the /admin/roles endpoint gave us.
  const roleByName = useMemo(
    () => Object.fromEntries(roles.map((r) => [r.role, r])),
    [roles],
  );
  const projected = useMemo(() => {
    const heldNext = new Set<string>();
    const canNext = new Set<string>();
    for (const r of selectedRoles) {
      const meta = roleByName[r];
      if (!meta) continue;
      meta.permissions.forEach((p) => heldNext.add(p));
      meta.can.forEach((p) => canNext.add(p));
    }
    return { held: heldNext, can: canNext };
  }, [roleByName, selectedRoles]);

  const currentHeld = new Set(currentAccess.held);
  const currentCan = new Set(currentAccess.can);
  const rolesChanged =
    currentRoles.length !== selectedRoles.length ||
    currentRoles.some((r) => !selectedRoles.includes(r));

  if (!rolesChanged) return null;

  const gained = Array.from(projected.can).filter((c) => !currentCan.has(c)).sort();
  const lost = Array.from(currentCan).filter((c) => !projected.can.has(c)).sort();

  // Additions of sensitive roles will queue for four-eye review (ADR-0015),
  // not apply immediately. Tell the admin so before they hit Save.
  const SENSITIVE = new Set(["ADMIN", "CFO", "COMPLIANCE_OFFICER"]);
  const willQueue = selectedRoles.filter(
    (r) => !currentRoles.includes(r) && SENSITIVE.has(r),
  );

  return (
    <div className="mt-2 rounded border border-primary/25 bg-primary/[.04] p-2 text-[10.5px] leading-snug">
      <div className="mb-1 text-[9.5px] font-semibold uppercase tracking-wider text-primary">
        Preview of the change
      </div>
      {gained.length > 0 ? (
        <p>
          <span className="font-semibold text-success">Will gain:</span>{" "}
          {gained.join(" · ")}
        </p>
      ) : null}
      {lost.length > 0 ? (
        <p className="mt-0.5">
          <span className="font-semibold text-destructive">Will lose:</span>{" "}
          {lost.join(" · ")}
        </p>
      ) : null}
      {gained.length === 0 && lost.length === 0 ? (
        <p className="italic text-muted-foreground">
          Roles change but effective permissions are unchanged.
        </p>
      ) : null}
      {willQueue.length > 0 ? (
        <p className="mt-1 rounded border border-warning/40 bg-warning/10 px-1.5 py-1 text-warning">
          Four-eye review: <b>{willQueue.join(", ")}</b> will not apply until
          another admin approves it.
        </p>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- invite modal

function InviteModal({
  open,
  roles,
  result,
  onSubmitted,
  onClose,
}: {
  open: boolean;
  roles: AdminRoleRow[];
  result: AdminInviteResponse | null;
  onSubmitted: (r: AdminInviteResponse) => void;
  onClose: () => void;
}) {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setEmail("");
      setDisplayName("");
      setSelectedRoles([]);
      setSubmitting(false);
      setError(null);
    }
  }, [open]);

  if (!open) return null;

  const toggle = (r: string) =>
    setSelectedRoles((prev) =>
      prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r],
    );

  const canSubmit =
    email.trim().length > 0 && displayName.trim().length > 0 && !submitting;

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await inviteAdminUser({
        email: email.trim(),
        display_name: displayName.trim(),
        roles: selectedRoles,
      });
      onSubmitted(res);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-xl border border-border bg-surface-1 shadow-2xl">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <UserPlus className="h-4 w-4" /> Invite user
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:bg-surface-2 hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {result ? (
          <div className="p-4">
            <ActivationLinkCard
              email={result.user.email}
              activationUrl={result.activation_url}
              expiresAt={result.expires_at}
              note={result.note}
            />
            <div className="mt-3 flex justify-end">
              <Button size="sm" onClick={onClose}>
                Done
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3 p-4">
            <div>
              <label className="text-[10.5px] font-medium text-muted-foreground">
                Email
              </label>
              <input
                type="email"
                placeholder="jane.doe@northgate.example"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-xs"
              />
            </div>
            <div>
              <label className="text-[10.5px] font-medium text-muted-foreground">
                Display name
              </label>
              <input
                type="text"
                placeholder="Jane Doe"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-xs"
              />
            </div>
            <div>
              <label className="text-[10.5px] font-medium text-muted-foreground">
                Roles (grant now; can edit later)
              </label>
              <div className="mt-1 grid grid-cols-2 gap-1.5 rounded border border-border bg-surface-2/40 p-2">
                {roles.map((r) => (
                  <label
                    key={r.role}
                    className="flex cursor-pointer items-start gap-1.5 rounded p-1 text-[11px] hover:bg-surface-2"
                  >
                    <input
                      type="checkbox"
                      checked={selectedRoles.includes(r.role)}
                      onChange={() => toggle(r.role)}
                      className="mt-0.5"
                    />
                    <span>
                      <span className="font-medium">{r.label}</span>
                      <span className="block text-[9.5px] text-muted-foreground">
                        {r.description}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </div>

            {error ? (
              <div className="rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                {error}
              </div>
            ) : null}

            <div className="flex items-center justify-end gap-2 pt-1">
              <Button variant="outline" size="sm" onClick={onClose}>
                Cancel
              </Button>
              <Button size="sm" onClick={submit} disabled={!canSubmit}>
                {submitting ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                Invite
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- edit panel

function EditUserPanel({
  user,
  roles,
  entities,
  onClose,
  onSaved,
}: {
  user: AdminUserRow | null;
  roles: AdminRoleRow[];
  entities: AdminLegalEntity[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [displayName, setDisplayName] = useState("");
  const [status, setStatus] = useState<"ACTIVE" | "DISABLED">("ACTIVE");
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);
  const [groupWide, setGroupWide] = useState(false);
  const [selectedEntities, setSelectedEntities] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetLink, setResetLink] = useState<{ url: string; expires: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user) {
      setDisplayName(user.display_name);
      setStatus(user.status);
      setSelectedRoles(user.roles);
      setGroupWide(user.scope.group_wide);
      setSelectedEntities(user.scope.entity_ids);
      setError(null);
      setResetLink(null);
    }
  }, [user]);

  if (!user) return null;

  const toggle = (r: string) =>
    setSelectedRoles((prev) =>
      prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r],
    );

  const toggleEntity = (id: string) =>
    setSelectedEntities((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );

  /**
   * One Save that persists everything.
   *
   * Fires both PATCHes in parallel. Splitting into two buttons was a
   * bad reading of the "removals apply immediately" pattern from the
   * research — that means fast, not two-clicks. One button + fast
   * parallel writes gives the same speed without the footgun of
   * silently losing scope edits when the roles-only Save was clicked.
   */
  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await Promise.all([
        updateAdminUser(user.id, {
          display_name: displayName.trim(),
          status,
          roles: selectedRoles,
        }),
        updateAdminUserScope(user.id, {
          group_wide: groupWide,
          entity_ids: groupWide ? [] : selectedEntities,
        }),
      ]);
      onSaved();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSaving(false);
    }
  };

  const resetPassword = async () => {
    setResetting(true);
    setResetLink(null);
    try {
      const res = await resetAdminUserPassword(user.id);
      setResetLink({ url: res.activation_url, expires: res.expires_at });
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-xl border border-border bg-surface-1 shadow-2xl">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <Pencil className="h-4 w-4" /> Edit user
            </h2>
            <p className="text-[10.5px] text-muted-foreground">{user.email}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:bg-surface-2 hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 p-4">
          <div>
            <label className="text-[10.5px] font-medium text-muted-foreground">
              Display name
            </label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-xs"
            />
          </div>
          <div>
            <label className="text-[10.5px] font-medium text-muted-foreground">
              Status
            </label>
            <div className="mt-1 flex gap-2">
              {(["ACTIVE", "DISABLED"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setStatus(s)}
                  className={`flex-1 rounded border px-3 py-1.5 text-[11px] font-medium ${
                    status === s
                      ? "border-primary bg-primary/[.08] text-primary"
                      : "border-border bg-background text-foreground hover:border-primary/40"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-[10.5px] font-medium text-muted-foreground">
              Roles
            </label>
            <div className="mt-1 grid grid-cols-2 gap-1.5 rounded border border-border bg-surface-2/40 p-2">
              {roles.map((r) => (
                <label
                  key={r.role}
                  className="flex cursor-pointer items-start gap-1.5 rounded p-1 text-[11px] hover:bg-surface-2"
                >
                  <input
                    type="checkbox"
                    checked={selectedRoles.includes(r.role)}
                    onChange={() => toggle(r.role)}
                    className="mt-0.5"
                  />
                  <span>
                    <span className="font-medium">{r.label}</span>
                    <span className="block text-[9.5px] text-muted-foreground">
                      {r.description}
                    </span>
                  </span>
                </label>
              ))}
            </div>
            <RoleChangePreview
              roles={roles}
              currentRoles={user.roles}
              selectedRoles={selectedRoles}
              currentAccess={user.effective_access}
            />
          </div>

          {/* Company access (scope) — separate PATCH so revoke can
              apply immediately without waiting on role changes. */}
          <div>
            <label className="text-[10.5px] font-medium text-muted-foreground">
              Company access
            </label>
            <div className="mt-1 rounded border border-border bg-surface-2/40 p-2">
              <label className="flex cursor-pointer items-center gap-2 rounded p-1 text-[11px] hover:bg-surface-2">
                <input
                  type="checkbox"
                  checked={groupWide}
                  onChange={(e) => {
                    setGroupWide(e.target.checked);
                    if (e.target.checked) setSelectedEntities([]);
                  }}
                />
                <span className="font-semibold">
                  Group-wide — every subsidiary in the tenant
                </span>
              </label>
              {!groupWide ? (
                <div className="mt-1 grid grid-cols-2 gap-1.5 border-t border-border/40 pt-1.5">
                  {entities.map((e) => (
                    <label
                      key={e.id}
                      className="flex cursor-pointer items-start gap-1.5 rounded p-1 text-[11px] hover:bg-surface-2"
                    >
                      <input
                        type="checkbox"
                        checked={selectedEntities.includes(e.id)}
                        onChange={() => toggleEntity(e.id)}
                        className="mt-0.5"
                      />
                      <span>
                        <span className="font-mono font-medium">{e.code}</span>{" "}
                        <span className="text-muted-foreground">{e.name}</span>
                      </span>
                    </label>
                  ))}
                </div>
              ) : null}
              <p className="mt-2 border-t border-border/40 pt-2 text-[10px] text-muted-foreground">
                {groupWide
                  ? "Group-wide access to every subsidiary"
                  : `${selectedEntities.length} of ${entities.length} entities selected`}
              </p>
            </div>
          </div>

          {resetLink ? (
            <ActivationLinkCard
              email={user.email}
              activationUrl={resetLink.url}
              expiresAt={resetLink.expires}
              note="Password reset. The previous password no longer works. Share this activation link so the user can set a new one — link is single-use and expires in 24 hours."
              variant="reset"
            />
          ) : null}

          {error ? (
            <div className="rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error}
            </div>
          ) : null}

          <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
            <Button
              variant="outline"
              size="sm"
              onClick={resetPassword}
              disabled={resetting}
              className="gap-1.5 text-xs"
            >
              {resetting ? <Loader2 className="h-3 w-3 animate-spin" /> : <KeyRound className="h-3 w-3" />}
              Reset password
            </Button>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={onClose}>
                Cancel
              </Button>
              <Button size="sm" onClick={save} disabled={saving}>
                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                Save
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
