"use client";

/**
 * PersonaNav — a small role-gated top-nav that lets a signed-in user
 * jump between the treasurer view and the persona pages they have
 * permission to see.
 *
 * ADR-0009: each route keeps its own 'one surface, one panel' rule.
 * This nav is the only shared surface between them.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeftRight,
  Cog,
  ShieldCheck,
  PenLine,
  type LucideIcon,
} from "lucide-react";

import { hasRole } from "@/lib/session";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  requiresAnyRole?: string[];
};

const ITEMS: NavItem[] = [
  { href: "/", label: "Treasurer", icon: ArrowLeftRight },
  { href: "/admin", label: "Admin", icon: Cog, requiresAnyRole: ["ADMIN"] },
  {
    href: "/compliance",
    label: "Compliance",
    icon: ShieldCheck,
    requiresAnyRole: ["COMPLIANCE_OFFICER", "CFO", "ADMIN"],
  },
  { href: "/approvals", label: "Approvals", icon: PenLine },
];

export function PersonaNav() {
  const pathname = usePathname();

  const visible = ITEMS.filter(
    (item) => !item.requiresAnyRole || hasRole(...item.requiresAnyRole),
  );

  // If the user only has access to the treasurer view, don't render the
  // nav at all — no need to show a single-item bar.
  if (visible.length <= 1) return null;

  return (
    <nav className="border-b border-border bg-surface-2/60">
      <div className="mx-auto flex max-w-[1400px] items-center gap-1 px-4 py-1.5">
        {visible.map(({ href, label, icon: Icon }) => {
          const active =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
                active
                  ? "bg-primary/15 text-primary font-semibold"
                  : "text-muted-foreground hover:bg-surface-2 hover:text-foreground",
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              <span>{label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
