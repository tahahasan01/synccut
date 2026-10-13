"use client";

import Link from "next/link";
import { use, useState } from "react";
import { ActionsStep } from "@/components/ActionsStep";
import { ExportStep } from "@/components/ExportStep";
import { NarrationStep } from "@/components/NarrationStep";
import { PreviewStep } from "@/components/PreviewStep";
import { RecordStep } from "@/components/RecordStep";
import { ReviewStep } from "@/components/ReviewStep";
import { Notice } from "@/components/ui";
import { fmtTime, type Project } from "@/lib/api";
import { useHealth, useProject } from "@/lib/hooks";

type Tab = "narration" | "actions" | "preview" | "record" | "review" | "export";

const exported = (p: Project) => p.renders.some((r) => r.preset === "final" && r.status === "ready");

function suggestedTab(p: Project): Tab {
  if (!p.beats.length) return "narration";
  if (p.mode === "generate") {
    if (!p.capture) return "actions";
    return exported(p) ? "export" : "preview";
  }
  if (!p.timeline) return "record";
  return exported(p) ? "export" : "review";
}

const running = (p: Project, type: string) => p.jobs.some((j) => j.type === type && (j.status === "queued" || j.status === "running"));

/** One line under each step saying where it stands. */
function stepStatus(p: Project): Record<Tab, string> {
  const flags = p.timeline?.segments.filter((s) => s.needs_review).length ?? 0;
  const recorded = p.takes.filter((t) => t.status === "ready" && t.mode !== "generated").length;
  return {
    narration: !p.master ? "Upload your video" : p.transcript ? `${fmtTime(p.master.probe?.duration_ms ?? 0)} · ${p.beats.length} steps` : running(p, "analyze") ? "Transcribing…" : "Needs a transcript",
    actions: running(p, "prepare") ? "Capturing pages…" : p.capture ? `${p.actions.length} actions · ${p.capture.pages} pages` : p.transcript ? "Not planned yet" : "After the narration",
    preview: p.capture ? "Plays in sync with you" : "After the actions",
    record: recorded ? `${recorded} take${recorded === 1 ? "" : "s"}` : "No takes yet",
    review: p.timeline ? (flags ? `${flags} to check` : "All steps look right") : "After a take",
    export: running(p, "render") ? "Rendering…" : exported(p) ? "Exported" : "Not exported yet",
  };
}

export default function ProjectClient({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { project, setProject, error, refresh } = useProject(id);

  if (error && !project) {
    return <main className="mx-auto max-w-5xl p-6"><Notice tone="bad">{error}</Notice></main>;
  }
  if (!project) return <main className="mx-auto max-w-5xl p-6 text-sm text-muted">Loading…</main>;
  return <ProjectView project={project} setProject={setProject} error={error} refresh={refresh} />;
}

function ProjectView({
  project, setProject, error, refresh,
}: {
  project: Project;
  setProject: (p: Project) => void;
  error: string | null;
  refresh: () => Promise<void>;
}) {
  const { health } = useHealth();
  const [chosen, setTab] = useState<Tab>(() => suggestedTab(project));
  const generated = project.mode === "generate";

  const tabs: { id: Tab; label: string; enabled: boolean; done: boolean }[] = generated
    ? [
        { id: "narration", label: "Narration", enabled: true, done: project.beats.length > 0 },
        { id: "actions", label: "Browser actions", enabled: Boolean(project.transcript), done: Boolean(project.capture) && project.actions.length > 0 },
        { id: "preview", label: "Preview", enabled: Boolean(project.capture), done: exported(project) },
        { id: "export", label: "Export & share", enabled: Boolean(project.capture), done: exported(project) },
      ]
    : [
        { id: "narration", label: "Narration", enabled: true, done: project.beats.length > 0 },
        { id: "record", label: "Record", enabled: project.beats.length > 0, done: project.takes.some((t) => t.status === "ready" && t.mode !== "generated") },
        { id: "review", label: "Review", enabled: project.beats.length > 0, done: Boolean(project.timeline) && !project.timeline!.segments.some((s) => s.needs_review) },
        { id: "export", label: "Export & share", enabled: Boolean(project.timeline), done: exported(project) },
      ];
  const tab = tabs.some((t) => t.id === chosen) ? chosen : suggestedTab(project);
  const status = stepStatus(project);

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-7 sm:px-6">
      <div>
        <Link href="/" className="text-sm font-medium text-muted hover:text-ink">Videos</Link>
        <h1 className="mt-1 text-[28px] font-extrabold leading-tight tracking-tight text-ink">{project.name}</h1>
      </div>

      {health && !health.whisper.ok && !project.transcript && (
        <Notice tone="bad">{health.whisper.error} Or import a subtitle file (.srt / .vtt) on the Narration tab.</Notice>
      )}
      {health && !health.ffmpeg && <Notice tone="bad">FFmpeg isn&apos;t available to the API. Install it and restart.</Notice>}
      {health && !health.claude.configured && (
        <Notice tone="info">No Anthropic API key found. Steps and browser actions come from phrase matching instead of Claude.</Notice>
      )}
      {error && <Notice tone="warn">{error}</Notice>}

      {/* The workflow really is a sequence, so the steps are numbered and joined. */}
      <nav aria-label="Steps" className="grid grid-cols-2 gap-x-2 gap-y-3 sm:grid-cols-4">
        {tabs.map((t, i) => {
          const current = tab === t.id;
          return (
            <button
              key={t.id}
              disabled={!t.enabled}
              aria-current={current ? "step" : undefined}
              onClick={() => setTab(t.id)}
              className="group text-left disabled:cursor-not-allowed"
            >
              <span className={`block h-[3px] rounded-full ${current ? "bg-cue" : t.done ? "bg-ink" : "bg-rule"}`} />
              <span className="mt-2.5 flex items-center gap-2">
                <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold tabular ${
                  t.done ? "bg-ink text-white" : current ? "bg-cue text-ink" : "bg-surface text-muted ring-1 ring-inset ring-rule-strong"
                }`}>
                  {t.done ? "✓" : i + 1}
                </span>
                <span className={`text-sm font-bold ${current ? "text-ink" : t.enabled ? "text-ink-soft group-hover:text-ink" : "text-rule-strong"}`}>{t.label}</span>
              </span>
              <span className={`mt-0.5 block pl-8 text-xs tabular ${t.enabled ? "text-muted" : "text-rule-strong"}`}>{status[t.id]}</span>
            </button>
          );
        })}
      </nav>

      {tab === "narration" && <NarrationStep project={project} onChange={setProject} />}
      {tab === "actions" && <ActionsStep project={project} onChange={setProject} />}
      {tab === "preview" && <PreviewStep project={project} onChange={setProject} />}
      {tab === "record" && <RecordStep project={project} onDone={refresh} />}
      {tab === "review" && <ReviewStep project={project} onChange={setProject} />}
      {tab === "export" && <ExportStep project={project} onChange={setProject} />}
    </main>
  );
}
