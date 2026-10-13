"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/** Wordmark: a cue mark (the yellow tick an editor drops on a timeline) and the name. */
export function Wordmark() {
  return (
    <span className="flex items-center gap-2 text-[17px] font-extrabold tracking-tight text-ink">
      <span aria-hidden className="relative block h-5 w-3">
        <span className="absolute inset-y-0 left-0 w-[3px] rounded-full bg-ink" />
        <span className="absolute left-[5px] top-0 h-3 w-[7px] rounded-[2px] bg-cue" />
      </span>
      SyncCut
    </span>
  );
}

export function AppHeader() {
  const pathname = usePathname();
  if (pathname.startsWith("/v/")) return null; // share pages show only the user's brand
  const link = (href: string, label: string) => {
    const active = href === "/" ? pathname === "/" || pathname.startsWith("/projects") : pathname.startsWith(href);
    return (
      <Link
        href={href}
        aria-current={active ? "page" : undefined}
        className={`rounded-[var(--radius-control)] px-3 py-1.5 text-sm font-medium ${active ? "text-ink" : "text-muted hover:text-ink"}`}
      >
        {label}
        {active && <span aria-hidden className="mt-0.5 block h-[2px] rounded-full bg-cue" />}
      </Link>
    );
  };
  return (
    <header className="border-b border-rule bg-surface">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3 sm:px-6">
        <Link href="/" aria-label="SyncCut home">
          <Wordmark />
        </Link>
        <nav className="ml-auto flex gap-1">
          {link("/", "Videos")}
          {link("/brand", "Brand")}
        </nav>
      </div>
    </header>
  );
}
