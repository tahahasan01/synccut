"use client";

import Link from "next/link";
import { useState } from "react";
import { api, ApiError, mediaUrl, type Project } from "@/lib/api";
import { Badge, Button, Card, Field, JobLine, Notice, inputClass } from "./ui";

export function ExportStep({ project, onChange }: { project: Project; onChange: (p: Project) => void }) {
  const [error, setError] = useState<string | null>(null);
  const timeline = project.timeline;
  const rendering = project.renders.some((r) => r.status === "rendering");
  const final = project.renders.find((r) => r.preset === "final" && r.status === "ready");
  const review = timeline?.segments.filter((s) => s.needs_review).length ?? 0;
  const generated = project.mode === "generate";
  const canExport = generated ? Boolean(project.capture) : Boolean(timeline);

  async function exportFinal() {
    setError(null);
    if (review && !confirm(`${review} step(s) still need checking. Export anyway?`)) return;
    try {
      await api.render(project.id, "final");
      onChange(await api.getProject(project.id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <div className="space-y-5">
      <Card
        title="Export"
        actions={
          <Button disabled={!canExport || rendering} onClick={exportFinal}>
            {rendering ? "Rendering…" : final ? "Export again" : "Export 1080p MP4"}
          </Button>
        }
      >
        {!canExport && (
          <p className="text-sm text-muted">
            {generated ? "Plan the browser actions and capture their pages first." : "Record and sync a take first."}
          </p>
        )}
        {generated && canExport && !final && (
          <p className="mb-3 text-sm text-muted">
            Exporting draws the browser frame by frame in sync with your narration, then adds your video and audio. It takes
            a few times the video&apos;s length.
          </p>
        )}
        {error && <div className="mb-3"><Notice tone="bad">{error}</Notice></div>}
        <JobLine project={project} type="render" />
        {final && (
          <div className="mt-4 space-y-3">
            <video key={final.id} src={mediaUrl(project.id, final.path!)} poster={final.poster_path ? mediaUrl(project.id, final.poster_path) : undefined} controls className="w-full rounded-lg bg-black" />
            <div className="flex flex-wrap items-center gap-3 text-sm text-muted">
              <a href={mediaUrl(project.id, final.path!)} download={`${project.name}.mp4`} className="font-medium text-ink hover:underline">
                Download MP4
              </a>
              <span>Rendered in {final.seconds}s</span>
              {timeline && final.timeline_version !== timeline.version && (
                <Badge tone="warn">older than your latest edits</Badge>
              )}
            </div>
          </div>
        )}
      </Card>
      <ShareSettings key={JSON.stringify(project.share)} project={project} onChange={onChange} canPublish={Boolean(final)} />
    </div>
  );
}

function ShareSettings({ project, onChange, canPublish }: { project: Project; onChange: (p: Project) => void; canPublish: boolean }) {
  const [share, setShare] = useState(project.share);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const link = typeof window === "undefined" ? "" : `${window.location.origin}/v/${share.slug}`;

  async function save(published = share.published) {
    setError(null);
    try {
      const final = project.renders.find((r) => r.preset === "final" && r.status === "ready");
      const { title, message, cta_label } = share;
      onChange(await api.putShare(project.id, { title, message, cta_label, published, render_id: final?.id ?? null }));
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          Share page {project.share.published ? <Badge tone="good">published</Badge> : <Badge>private</Badge>}
        </span>
      }
      actions={
        <>
          <Button variant="secondary" onClick={() => save()}>{saved ? "Saved" : "Save"}</Button>
          <Button disabled={!canPublish} onClick={() => save(!project.share.published)}>
            {project.share.published ? "Unpublish" : "Publish"}
          </Button>
        </>
      }
    >
      <p className="mb-4 text-sm text-muted">
        A page under your own brand with this video, your proof (rating, profile, portfolio) and your booking calendar.
        Edit your name, booking link and portfolio in <Link href="/brand" className="text-ink hover:underline">Brand settings</Link>.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Headline" hint="e.g. Hi Sarah, here's how I'd automate your lead intake">
          <input className={inputClass} value={share.title} onChange={(e) => setShare({ ...share, title: e.target.value })} />
        </Field>
        <Field label="Button label">
          <input className={inputClass} value={share.cta_label} onChange={(e) => setShare({ ...share, cta_label: e.target.value })} />
        </Field>
        <div className="md:col-span-2">
          <Field label="Message under the video">
            <textarea rows={3} className={inputClass} value={share.message} onChange={(e) => setShare({ ...share, message: e.target.value })} />
          </Field>
        </div>
      </div>
      {error && <div className="mt-3"><Notice tone="bad">{error}</Notice></div>}
      {!canPublish && <p className="mt-3 text-xs text-muted">Export the final video to publish.</p>}
      {project.share.published && (
        <div className="mt-4 flex flex-wrap items-center gap-2 rounded-lg bg-paper p-3 text-sm">
          <a href={link} target="_blank" rel="noreferrer" className="font-mono text-ink hover:underline">{link}</a>
          <Button variant="ghost" onClick={() => navigator.clipboard.writeText(link)}>Copy</Button>
        </div>
      )}
      <p className="mt-4 text-xs text-muted">
        Running locally, this link only works on your machine. Deploy the app to share it with clients. Check your
        marketplace&apos;s rules (e.g. Upwork) on off-platform contact before adding links.
      </p>
    </Card>
  );
}
