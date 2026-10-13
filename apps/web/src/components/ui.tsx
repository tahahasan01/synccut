"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Job, Project } from "@/lib/api";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-ink text-white hover:bg-ink-soft disabled:bg-rule-strong disabled:text-white",
  secondary: "bg-surface text-ink ring-1 ring-inset ring-rule-strong hover:ring-ink disabled:text-muted disabled:ring-rule",
  ghost: "text-muted hover:text-ink hover:bg-ink/5 disabled:text-rule-strong disabled:hover:bg-transparent",
  danger: "bg-surface text-signal ring-1 ring-inset ring-signal/40 hover:ring-signal disabled:opacity-50",
};

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-[var(--radius-control)] px-3.5 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}

/** A working surface. Titles are sentence case; actions sit to the right. */
export function Card({ title, actions, children, className = "" }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-[var(--radius-panel)] border border-rule bg-surface p-5 sm:p-6 ${className}`}>
      {(title || actions) && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          {title && <h2 className="text-lg font-bold tracking-tight text-ink">{title}</h2>}
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

const BADGE_TONES = {
  neutral: "bg-ink/[0.06] text-ink-soft",
  good: "bg-go-soft text-go",
  warn: "bg-cue-soft text-[#7a5a00]",
  bad: "bg-signal-soft text-signal",
  info: "bg-ink text-white",
};

export function Badge({ tone = "neutral", children }: { tone?: keyof typeof BADGE_TONES; children: ReactNode }) {
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${BADGE_TONES[tone]}`}>{children}</span>;
}

export function Progress({ value }: { value: number }) {
  return (
    <div className="h-1 w-full overflow-hidden rounded-full bg-rule" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full bg-ink transition-[width] duration-500" style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "bad"; children: ReactNode }) {
  const tones = {
    info: "border-l-ink bg-ink/[0.04] text-ink-soft",
    warn: "border-l-cue bg-cue-soft/60 text-ink",
    bad: "border-l-signal bg-signal-soft text-ink",
  };
  return <div role={tone === "bad" ? "alert" : undefined} className={`rounded-r-[var(--radius-control)] border-l-[3px] px-4 py-3 text-sm ${tones[tone]}`}>{children}</div>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-semibold text-ink">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted/70 outline-none focus:border-ink focus:ring-2 focus:ring-cue";

/** The latest job of a type: progress while running, the error if it failed. */
export function JobLine({ project, type }: { project: Project; type: Job["type"] }) {
  const job = project.jobs.find((j) => j.type === type);
  if (!job) return null;
  if (job.status === "queued" || job.status === "running") {
    return (
      <div className="space-y-1.5" aria-live="polite">
        <div className="flex justify-between text-xs text-muted">
          <span>{job.message || job.label}</span>
          <span className="tabular">{Math.round(job.progress * 100)}%</span>
        </div>
        <Progress value={job.progress} />
      </div>
    );
  }
  if (job.status === "failed") {
    return (
      <Notice tone="bad">
        <strong>{job.label} failed.</strong> {job.error}
      </Notice>
    );
  }
  return null;
}
