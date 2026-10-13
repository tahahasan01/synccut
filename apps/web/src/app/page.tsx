"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { HeroDemo } from "@/components/demo/HeroDemo";
import { Badge, Button, Notice, inputClass } from "@/components/ui";
import { api, ApiError, fmtDuration, type ProjectSummary } from "@/lib/api";

const STEP_NAMES = ["Narration", "Browser actions", "Preview", "Export"];

function steps(p: ProjectSummary): boolean[] {
  const middle = p.mode === "generate" ? p.captured : p.synced;
  return [p.beats > 0, middle, middle, p.exported];
}

function describe(p: ProjectSummary): string {
  const parts = [p.duration_ms ? `${fmtDuration(p.duration_ms)} narration` : "No narration yet"];
  if (p.beats > 0) parts.push(`${p.beats} steps`);
  if (p.mode === "record") parts.push("recording mode");
  return parts.join(", ");
}

function relative(ts: number): string {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

export default function Home() {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    api.listProjects().then(setProjects, (e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  async function remove(p: ProjectSummary) {
    if (!window.confirm(`Delete "${p.name}"? Its video, takes and exports are removed for good.`)) return;
    try {
      await api.deleteProject(p.id);
      setProjects((ps) => ps?.filter((x) => x.id !== p.id) ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    try {
      const p = await api.createProject(name);
      router.push(`/projects/${p.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setCreating(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-6xl px-4 pb-16 pt-10 sm:px-6 lg:pt-14">
      <section className="grid items-center gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-14">
        <div>
          <h1 className="text-[40px] font-extrabold leading-[1.02] tracking-[-0.035em] text-ink sm:text-[52px]">
            Say it once.
            <br />
            The browser follows.
          </h1>
          <p className="mt-5 max-w-[46ch] text-[17px] leading-relaxed text-muted">
            Upload the video you already recorded. SyncCut reads your narration, opens the sites you mention the moment you
            mention them, and exports one MP4 with you in the corner.
          </p>
          <form onSubmit={create} className="mt-8 flex max-w-md flex-col gap-2 sm:flex-row">
            <label className="sr-only" htmlFor="video-name">Video name</label>
            <input
              id="video-name"
              className={`${inputClass} py-2.5`}
              placeholder="Name it, e.g. CRM automation for Sarah"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <Button type="submit" disabled={creating} className="shrink-0 py-2.5">{creating ? "Starting…" : "Start a video"}</Button>
          </form>
          {error && <div className="mt-4 max-w-md"><Notice tone="bad">{error}</Notice></div>}
        </div>
        <HeroDemo />
      </section>

      <section className="mt-16" aria-labelledby="videos">
        <div className="flex items-baseline justify-between border-b border-rule pb-3">
          <h2 id="videos" className="text-lg font-bold tracking-tight">Your videos</h2>
          {projects && projects.length > 0 && <span className="text-sm text-muted tabular">{projects.length}</span>}
        </div>
        {projects === null && !error && <p className="py-6 text-sm text-muted">Loading your videos…</p>}
        {projects?.length === 0 && (
          <p className="py-8 text-sm text-muted">No videos yet. Name one above, then upload the narration you recorded.</p>
        )}
        <ul>
          {projects?.map((p) => {
            const done = steps(p);
            const next = done.indexOf(false);
            return (
              <li key={p.id} className="flex items-center gap-3 border-b border-rule">
                <Link href={`/projects/${p.id}`} className="group grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-6 gap-y-2 py-4 sm:grid-cols-[minmax(0,1fr)_220px_110px]">
                  <span className="min-w-0">
                    <span className="block truncate font-bold text-ink group-hover:underline group-hover:decoration-cue group-hover:decoration-2 group-hover:underline-offset-4">{p.name}</span>
                    <span className="mt-0.5 block text-sm text-muted">{describe(p)}</span>
                  </span>
                  <span className="order-last col-span-2 sm:order-none sm:col-span-1">
                    <span className="flex gap-1" aria-hidden>
                      {done.map((d, i) => (
                        <span key={i} className={`h-1.5 flex-1 rounded-full ${d ? "bg-ink" : i === next ? "bg-cue" : "bg-rule"}`} />
                      ))}
                    </span>
                    <span className="mt-1.5 flex items-center gap-2 text-xs text-muted">
                      {next === -1 ? "Exported" : `Next: ${STEP_NAMES[next].toLowerCase()}`}
                      {p.share_slug && <Badge tone="good">Shared</Badge>}
                    </span>
                  </span>
                  <span className="text-right text-xs text-muted">{relative(p.updated_at)}</span>
                </Link>
                <button
                  onClick={() => remove(p)}
                  aria-label={`Delete ${p.name}`}
                  className="shrink-0 rounded-[var(--radius-control)] px-2 py-1 text-xs font-semibold text-muted hover:bg-signal/10 hover:text-signal focus-visible:text-signal"
                >
                  Delete
                </button>
              </li>
            );
          })}
        </ul>
      </section>
    </main>
  );
}
