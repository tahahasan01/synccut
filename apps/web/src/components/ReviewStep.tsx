"use client";

import { useState } from "react";
import { api, ApiError, fmtTime, frameMs, mediaUrl, type Corner, type Project, type Segment, type SegmentKind } from "@/lib/api";
import { Badge, Button, Card, JobLine, Notice } from "./ui";

const FLAG_TEXT: Record<string, { text: string; tone: "warn" | "bad" | "neutral" }> = {
  missing_footage: { text: "No footage for this step", tone: "bad" },
  heavy_retime: { text: "Clip was cut to fit", tone: "warn" },
  auto_guess: { text: "Matched by timing only", tone: "warn" },
  long_hold: { text: "Long freeze at the end", tone: "warn" },
  idle_trimmed: { text: "Idle time removed", tone: "neutral" },
};

const KIND_TEXT: Record<SegmentKind, string> = {
  browser: "Browser clip",
  hold: "Freeze frame",
  face: "Face full-screen",
};

export function ReviewStep({ project, onChange }: { project: Project; onChange: (p: Project) => void }) {
  const [error, setError] = useState<string | null>(null);
  const timeline = project.timeline;
  const syncing = project.jobs.some((j) => (j.type === "sync" || j.type === "take") && (j.status === "queued" || j.status === "running"));
  const rendering = project.renders.some((r) => r.status === "rendering");
  const draft = project.renders.find((r) => r.preset === "draft" && r.status === "ready");

  async function run<T>(fn: () => Promise<T>) {
    setError(null);
    try {
      const out = await fn();
      if (out && typeof out === "object" && "timeline" in out) onChange(out as unknown as Project);
      else onChange(await api.getProject(project.id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  if (!timeline) {
    return (
      <Card title="Review">
        <p className="mb-4 text-sm text-muted">
          Record a browser take first. It syncs automatically when the recording finishes.
        </p>
        <JobLine project={project} type="take" />
        <JobLine project={project} type="sync" />
        {project.takes.some((t) => t.status === "ready") && (
          <Button disabled={syncing} onClick={() => run(() => api.sync(project.id))}>Sync now</Button>
        )}
        {error && <div className="mt-3"><Notice tone="bad">{error}</Notice></div>}
      </Card>
    );
  }

  const review = timeline.segments.filter((s) => s.needs_review).length;
  const fps = timeline.fps;
  const takes = project.takes.filter((t) => t.status === "ready");

  return (
    <div className="space-y-5">
      <Card
        title={
          <span className="flex items-center gap-2">
            Review <Badge tone={review ? "warn" : "good"}>{review ? `${review} to check` : "all steps look good"}</Badge>
          </span>
        }
        actions={
          <>
            <Button variant="ghost" disabled={!project.timeline_versions.length} onClick={() => run(() => api.undoTimeline(project.id))}>
              Undo
            </Button>
            <Button variant="secondary" disabled={syncing} onClick={() => run(() => api.sync(project.id))}>
              Re-sync
            </Button>
            <Button disabled={rendering} onClick={() => run(() => api.render(project.id, "draft"))}>
              {rendering ? "Rendering…" : "Preview (draft render)"}
            </Button>
          </>
        }
      >
        {project.timeline_stale && (
          <div className="mb-4"><Notice tone="warn">Steps or takes changed since the last sync. Re-sync to update. Steps you confirmed are kept.</Notice></div>
        )}
        {error && <div className="mb-4"><Notice tone="bad">{error}</Notice></div>}
        <div className="space-y-3">
          <JobLine project={project} type="sync" />
          <JobLine project={project} type="render" />
        </div>

        <div className="mt-2 grid gap-5 lg:grid-cols-[1fr_320px]">
          <div>
            {draft ? (
              <video key={draft.id} src={mediaUrl(project.id, draft.path!)} controls className="w-full rounded-lg bg-black" />
            ) : (
              <div className="flex aspect-video items-center justify-center rounded-lg bg-ink/5 text-sm text-muted">
                Click &ldquo;Preview&rdquo; to render a quick 540p draft
              </div>
            )}
            {draft && draft.timeline_version !== timeline.version && (
              <p className="mt-2 text-xs text-[#7a5a00]">This preview is from an older version of the timeline. Render again to see your changes.</p>
            )}
          </div>
          <LayoutControls project={project} onRun={run} />
        </div>
      </Card>

      <Card title="Timeline">
        <ol className="space-y-2">
          {timeline.segments.map((seg) => (
            <SegmentRow key={`${seg.id}-${timeline.version}`} project={project} seg={seg} fps={fps} takes={takes} onRun={run} />
          ))}
        </ol>
      </Card>
    </div>
  );
}

function LayoutControls({ project, onRun }: { project: Project; onRun: (fn: () => Promise<unknown>) => void }) {
  const layout = project.timeline!.layout;
  const [width, setWidth] = useState(layout.pip_width_pct);
  const corners: Corner[] = ["top-left", "top-right", "bottom-left", "bottom-right"];
  return (
    <div className="space-y-4 rounded-lg border border-rule p-4">
      <div className="text-sm font-medium text-ink">Picture-in-picture</div>
      <label className="flex items-center gap-2 text-sm text-ink">
        <input
          type="checkbox"
          checked={layout.pip_visible}
          onChange={(e) => onRun(() => api.patchLayout(project.id, { pip_visible: e.target.checked }))}
        />
        Show my video over the browser
      </label>
      <div className="grid grid-cols-2 gap-2">
        {corners.map((c) => (
          <button
            key={c}
            onClick={() => onRun(() => api.patchLayout(project.id, { pip_corner: c }))}
            className={`rounded-md border px-2 py-1.5 text-xs capitalize ${layout.pip_corner === c ? "border-ink bg-cue-soft text-ink" : "border-rule text-muted"}`}
          >
            {c.replace("-", " ")}
          </button>
        ))}
      </div>
      <label className="block text-sm text-ink">
        Size: {Math.round(width * 100)}% of width
        <input
          type="range"
          min={0.1}
          max={0.45}
          step={0.01}
          value={width}
          onChange={(e) => setWidth(Number(e.target.value))}
          onPointerUp={() => onRun(() => api.patchLayout(project.id, { pip_width_pct: width }))}
          onKeyUp={() => onRun(() => api.patchLayout(project.id, { pip_width_pct: width }))}
          className="mt-1 w-full"
        />
      </label>
      <p className="text-xs text-muted">The narration&apos;s audio is always kept. Browser audio isn&apos;t recorded.</p>
    </div>
  );
}

function SegmentRow({
  project, seg, fps, takes, onRun,
}: {
  project: Project;
  seg: Segment;
  fps: number;
  takes: Project["takes"];
  onRun: (fn: () => Promise<unknown>) => void;
}) {
  const beatIdx = project.beats.findIndex((b) => b.id === seg.beat_id);
  const beat = project.beats[beatIdx];
  const take = takes.find((t) => t.id === seg.take_id);
  const [clipIn, setClipIn] = useState(((seg.clip?.in_ms ?? 0) / 1000).toFixed(1));
  const [clipOut, setClipOut] = useState(((seg.clip?.out_ms ?? 0) / 1000).toFixed(1));
  const [holdAt, setHoldAt] = useState(((seg.hold_at_ms ?? 0) / 1000).toFixed(1));
  const speed = seg.pieces.length ? Math.max(...seg.pieces.map((p) => p.speed)) : 1;
  const patch = (p: Parameters<typeof api.patchSegment>[2]) => onRun(() => api.patchSegment(project.id, seg.id, p));

  const applyClip = () => {
    const a = Number(clipIn) * 1000, b = Number(clipOut) * 1000;
    if (seg.clip && Number.isFinite(a) && Number.isFinite(b) && b > a && (a !== seg.clip.in_ms || b !== seg.clip.out_ms)) {
      patch({ clip: { in_ms: a, out_ms: b } });
    }
  };

  return (
    <li className={`rounded-lg border p-3 ${seg.needs_review ? "border-cue bg-cue-soft/40" : "border-rule"}`}>
      <div className="flex flex-wrap items-start gap-4">
        <div className="w-28 shrink-0 font-mono text-xs text-muted">
          {fmtTime(frameMs(seg.start_f, fps))}
          <br />
          {fmtTime(frameMs(seg.end_f, fps))}
        </div>
        {seg.kind === "browser" && take?.path && seg.clip && (
          <video
            src={`${mediaUrl(project.id, take.path)}#t=${(seg.clip.in_ms / 1000).toFixed(2)},${(seg.clip.out_ms / 1000).toFixed(2)}`}
            preload="metadata"
            muted
            controls
            className="w-44 shrink-0 rounded bg-black"
          />
        )}
        <div className="min-w-0 flex-1 space-y-2">
          <div className="text-sm font-medium text-ink">
            {beat ? `${beatIdx + 1}. ${beat.label || beat.text}` : "Intro (before the first step)"}
          </div>
          {beat?.label && <div className="line-clamp-2 text-xs text-muted">&ldquo;{beat.text}&rdquo;</div>}
          <div className="flex flex-wrap gap-1.5">
            {seg.flags.map((f) => (
              <Badge key={f} tone={FLAG_TEXT[f]?.tone ?? "neutral"}>{FLAG_TEXT[f]?.text ?? f}</Badge>
            ))}
            {seg.kind === "browser" && speed > 1.01 && <Badge>{speed.toFixed(2)}× speed</Badge>}
            {seg.kind === "browser" && seg.hold_ms > 300 && <Badge>holds {(seg.hold_ms / 1000).toFixed(1)}s</Badge>}
            {seg.locked && <Badge tone="good">confirmed</Badge>}
          </div>
        </div>
        <div className="flex shrink-0 flex-col gap-2 text-sm">
          <div className="flex gap-2">
            <select
              value={seg.kind}
              onChange={(e) => patch({ kind: e.target.value as SegmentKind })}
              className="rounded-md border border-rule-strong bg-white px-2 py-1.5 text-sm"
              disabled={!takes.length && seg.kind === "face"}
            >
              {(Object.keys(KIND_TEXT) as SegmentKind[]).map((k) => (
                <option key={k} value={k} disabled={k !== "face" && !takes.length}>{KIND_TEXT[k]}</option>
              ))}
            </select>
            {seg.kind !== "face" && takes.length > 1 && (
              <select
                value={seg.take_id ?? ""}
                onChange={(e) => patch({ take_id: e.target.value })}
                className="rounded-md border border-rule-strong bg-white px-2 py-1.5 text-sm"
              >
                {takes.map((t, i) => (
                  <option key={t.id} value={t.id}>Take {i + 1}</option>
                ))}
              </select>
            )}
          </div>
          {seg.kind === "browser" && seg.clip && (
            <div className="flex items-center gap-1 text-xs text-muted">
              clip
              <input className="w-16 rounded border border-rule-strong px-1.5 py-1" value={clipIn} onChange={(e) => setClipIn(e.target.value)} onBlur={applyClip} onKeyDown={(e) => e.key === "Enter" && applyClip()} />
              –
              <input className="w-16 rounded border border-rule-strong px-1.5 py-1" value={clipOut} onChange={(e) => setClipOut(e.target.value)} onBlur={applyClip} onKeyDown={(e) => e.key === "Enter" && applyClip()} />
              s
            </div>
          )}
          {seg.kind === "hold" && (
            <div className="flex items-center gap-1 text-xs text-muted">
              frame at
              <input
                className="w-16 rounded border border-rule-strong px-1.5 py-1"
                value={holdAt}
                onChange={(e) => setHoldAt(e.target.value)}
                onBlur={() => Number(holdAt) * 1000 !== seg.hold_at_ms && patch({ hold_at_ms: Number(holdAt) * 1000 })}
              />
              s
            </div>
          )}
          <Button variant={seg.locked ? "ghost" : "secondary"} onClick={() => patch({ locked: !seg.locked })}>
            {seg.locked ? "Unconfirm" : "Looks good"}
          </Button>
        </div>
      </div>
    </li>
  );
}
