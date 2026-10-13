"use client";

import { useRef, useState } from "react";
import { api, ApiError, fmtTime, mediaUrl, type Beat, type Project } from "@/lib/api";
import { useHealth } from "@/lib/hooks";
import { Badge, Button, Card, JobLine, Notice, Progress, inputClass } from "./ui";

export function NarrationStep({ project, onChange }: { project: Project; onChange: (p: Project) => void }) {
  const [upload, setUpload] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const subsRef = useRef<HTMLInputElement>(null);
  const analyzing = project.jobs.some((j) => j.type === "analyze" && (j.status === "queued" || j.status === "running"));
  const { health } = useHealth();
  const noWhisper = health ? !health.whisper.ok : false;
  const lastAnalyze = project.jobs.find((j) => j.type === "analyze");

  async function onFile(file: File) {
    setError(null);
    setUpload(0);
    try {
      onChange(await api.uploadMaster(project.id, file, setUpload));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setUpload(null);
    }
  }

  return (
    <div className="space-y-5">
      <Card
        title="Your narration video"
        actions={
          project.master && (
            <Button variant="secondary" disabled={analyzing || upload !== null} onClick={() => fileRef.current?.click()}>
              Replace video
            </Button>
          )
        }
      >
        <input
          ref={fileRef}
          type="file"
          accept="video/*"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
        />
        {!project.master ? (
          <>
          <button
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const file = e.dataTransfer.files[0];
              if (file) onFile(file);
            }}
            className="flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed border-rule-strong px-6 py-12 text-center hover:border-ink hover:bg-cue-soft/40"
          >
            <span className="text-sm font-medium text-ink">Drop your recorded video here, or click to choose</span>
            <span className="text-xs text-muted">MP4, MOV or WebM with your face and voice. It is never modified.</span>
          </button>
          {noWhisper && (
            <p className="mt-3 text-xs text-muted">
              Automatic transcription isn&apos;t set up on this computer yet. After uploading, import the video&apos;s captions
              (.srt or .vtt) and SyncCut takes the timing from them.
            </p>
          )}
          </>
        ) : (
          <div className="grid gap-5 md:grid-cols-[280px_1fr]">
            <video src={mediaUrl(project.id, project.master.path)} controls className="w-full rounded-lg bg-black" />
            <div className="space-y-2 text-sm text-ink">
              <div className="font-medium text-ink">{project.master.filename}</div>
              {project.master.probe && (
                <div className="text-muted">
                  {fmtTime(project.master.probe.duration_ms)} · {project.master.probe.width}×{project.master.probe.height} ·{" "}
                  {project.master.probe.fps} fps
                </div>
              )}
              {project.transcript && (
                <p className="line-clamp-4 text-muted">&ldquo;{project.transcript.text}&rdquo;</p>
              )}
            </div>
          </div>
        )}
        <div className="mt-4 space-y-3">
          {upload !== null && (
            <div className="space-y-1.5">
              <div className="text-xs text-muted">Uploading… {Math.round(upload * 100)}%</div>
              <Progress value={upload} />
            </div>
          )}
          {error && <Notice tone="bad">{error}</Notice>}
          {/* Without Whisper the failed transcription is expected; the note below says what to do instead. */}
          {!project.transcript && !(noWhisper && lastAnalyze?.status === "failed") && <JobLine project={project} type="analyze" />}
          {project.master?.probe && !analyzing && !project.transcript && (
            <div className="flex flex-wrap items-center gap-2">
              {lastAnalyze?.status === "failed" && !noWhisper && (
                <Button variant="secondary" onClick={() => api.reanalyze(project.id).then(() => api.getProject(project.id)).then(onChange)}>
                  Try transcription again
                </Button>
              )}
              <Button variant={noWhisper ? "primary" : "secondary"} onClick={() => subsRef.current?.click()}>Import subtitles (.srt / .vtt)</Button>
              <span className="text-xs text-muted">
                {noWhisper
                  ? "Automatic transcription isn't set up on this computer, so the timing comes from your captions."
                  : "Use captions you already have instead of transcribing."}
              </span>
            </div>
          )}
          {project.transcript?.model?.startsWith("subtitles:") && (
            <p className="text-xs text-muted">Transcript from {project.transcript.model.slice(10)}.</p>
          )}
          <input
            ref={subsRef}
            type="file"
            accept=".srt,.vtt,text/vtt"
            className="hidden"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              setError(null);
              try {
                onChange(await api.importSubtitles(project.id, file));
              } catch (err) {
                setError(err instanceof ApiError ? err.message : String(err));
              }
            }}
          />
        </div>
      </Card>

      {project.mode === "generate" && <PageLink key={project.page_url ?? ""} project={project} onChange={onChange} />}

      {project.beats.length > 0 && <BeatsEditor key={JSON.stringify(project.beats)} project={project} onChange={onChange} />}
    </div>
  );
}

/** The page the video is about: the user's site, or the job posting they're replying to. */
function PageLink({ project, onChange }: { project: Project; onChange: (p: Project) => void }) {
  const [url, setUrl] = useState(project.page_url ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const saved = project.page_url ?? "";
  const dirty = url.trim() !== saved;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      onChange(await api.setPage(project.id, url.trim()));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="The page you're talking about">
      <form onSubmit={save} className="space-y-3">
        <p className="max-w-prose text-sm text-muted">
          Paste the job posting you&apos;re replying to, or your own website. When you mention it (&ldquo;your job post&rdquo;,
          &ldquo;my site&rdquo;), the browser opens this page, and the video starts on it if you never name another site first.
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <label className="sr-only" htmlFor="page-url">Link</label>
          <input
            id="page-url"
            type="url"
            inputMode="url"
            placeholder="https://www.upwork.com/jobs/… or yoursite.com"
            className={`${inputClass} sm:flex-1`}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <Button type="submit" disabled={!dirty || saving}>{saving ? "Saving…" : saved && !url.trim() ? "Remove link" : "Save link"}</Button>
        </div>
        {saved && !dirty && project.transcript && (
          <p className="text-xs text-muted">Saved. Browser actions were planned again with this page.</p>
        )}
        {error && <Notice tone="bad">{error}</Notice>}
      </form>
    </Card>
  );
}

function BeatsEditor({ project, onChange }: { project: Project; onChange: (p: Project) => void }) {
  const [beats, setBeats] = useState<Beat[]>(project.beats);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = JSON.stringify(beats) !== JSON.stringify(project.beats);

  const merge = (i: number) =>
    setBeats((bs) => {
      const a = bs[i], b = bs[i + 1];
      const merged: Beat = {
        ...a,
        text: `${a.text} ${b.text}`.trim(),
        label: [a.label, b.label].filter(Boolean).join(", then ") || undefined,
        end_ms: b.end_ms,
      };
      return [...bs.slice(0, i), merged, ...bs.slice(i + 2)];
    });

  async function save() {
    setSaving(true);
    setError(null);
    try {
      onChange(await api.putBeats(project.id, beats));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          Steps <Badge tone={project.beats_source === "claude" ? "info" : "neutral"}>
            {project.beats_source === "claude" ? "grouped by Claude" : "split by sentence"}
          </Badge>
        </span>
      }
      actions={
        <>
          {dirty && <Button variant="ghost" onClick={() => setBeats(project.beats)}>Discard</Button>}
          <Button disabled={!dirty || saving} onClick={save}>{saving ? "Saving…" : "Save steps"}</Button>
        </>
      }
    >
      <p className="mb-4 text-sm text-muted">
        Each step is one thing you&apos;ll do in the browser while that part of the narration plays. The label is what the
        teleprompter shows you. Merge steps that are one action.
      </p>
      {error && <div className="mb-3"><Notice tone="bad">{error}</Notice></div>}
      <ol className="divide-y divide-rule">
        {beats.map((beat, i) => (
          <li key={beat.id} className="grid gap-3 py-3 md:grid-cols-[3rem_7rem_1fr_auto] md:items-start">
            <span className="text-sm font-semibold text-muted">{i + 1}</span>
            <span className="font-mono text-xs text-muted">
              {fmtTime(beat.start_ms)}–{fmtTime(beat.end_ms)}
            </span>
            <div className="space-y-1.5">
              <input
                className={inputClass}
                value={beat.label ?? ""}
                placeholder="Teleprompter label, e.g. Open the client's job post"
                onChange={(e) => setBeats((bs) => bs.map((b, j) => (j === i ? { ...b, label: e.target.value } : b)))}
              />
              <p className="font-script text-[15px] leading-relaxed text-ink-soft">{beat.text}</p>
            </div>
            <div className="flex gap-1">
              {i < beats.length - 1 && (
                <Button variant="ghost" title="Merge with the next step" onClick={() => merge(i)}>Merge ↓</Button>
              )}
            </div>
          </li>
        ))}
      </ol>
    </Card>
  );
}
