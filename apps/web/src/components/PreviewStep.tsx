"use client";

import { useEffect, useRef, useState } from "react";
import { api, API_URL, ApiError, fmtTime, mediaUrl, stageUrl, type Corner, type Project } from "@/lib/api";
import { Card, JobLine, Notice } from "./ui";

const CORNERS: Corner[] = ["top-left", "top-right", "bottom-left", "bottom-right"];

/**
 * Live preview: the generated browser (stage iframe) follows the narration
 * video's clock, so what you see here is what the export renders.
 */
export function PreviewStep({ project, onChange }: { project: Project; onChange: (p: Project) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const frame = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const layout = project.layout;
  const [width, setWidth] = useState(layout.pip_width_pct);
  const duration = project.master?.probe?.duration_ms ?? 0;
  const nonce = `${project.capture?.run}-${project.updated_at}`;
  const preparing = project.jobs.some((j) => j.type === "prepare" && (j.status === "queued" || j.status === "running"));

  // drive the stage from the narration clock
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const v = video.current;
      if (v && frame.current?.contentWindow) {
        const t = v.currentTime * 1000;
        frame.current.contentWindow.postMessage({ source: "synccut-editor", type: "seek", t }, API_URL);
        setTime(t);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  useEffect(() => {
    const onMsg = (e: MessageEvent) => {
      if (e.origin === API_URL && e.data?.source === "synccut-stage" && e.data.type === "ready") setReady(true);
    };
    addEventListener("message", onMsg);
    return () => removeEventListener("message", onMsg);
  }, []);

  async function patch(p: Parameters<typeof api.patchLayout>[1]) {
    setError(null);
    try {
      onChange(await api.patchLayout(project.id, p));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  if (!project.capture) {
    return (
      <Card title="Preview">
        <JobLine project={project} type="prepare" />
        <p className="mt-2 text-sm text-muted">The preview appears once the browser actions are planned and their pages captured.</p>
      </Card>
    );
  }

  const circle = (layout.pip_shape ?? "circle") === "circle";
  const pos: Record<Corner, string> = {
    "top-left": "left-[1.7%] top-[3%]", "top-right": "right-[1.7%] top-[3%]",
    "bottom-left": "left-[1.7%] bottom-[3%]", "bottom-right": "right-[1.7%] bottom-[3%]",
  };

  const seekTo = (ms: number) => {
    if (video.current) video.current.currentTime = Math.min(Math.max(ms, 0), duration) / 1000;
  };
  const cues = [...project.actions].sort((a, b) => a.at_ms - b.at_ms);
  const currentCue = cues.filter((c) => c.at_ms <= time).pop();

  return (
    <div className="space-y-5">
      <div className="max-w-2xl">
        <h2 className="text-lg font-bold tracking-tight">Preview</h2>
        <p className="mt-1 text-sm text-muted">This is what the export will look like: the browser follows your narration, with you in the corner.</p>
      </div>
      {preparing && <JobLine project={project} type="prepare" />}
      {error && <Notice tone="bad">{error}</Notice>}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
        {/* The monitor: the one dark surface in the app, so the picture reads as the output. */}
        <div className="rounded-[var(--radius-panel)] bg-monitor p-3 shadow-[0_24px_60px_-20px_rgba(16,19,26,0.55)] sm:p-4">
          <div className="relative aspect-video w-full overflow-hidden rounded-[6px] bg-black">
            <iframe
              key={nonce}
              ref={frame}
              src={stageUrl(project, nonce)}
              title="Generated browser preview"
              className="absolute inset-0 h-full w-full border-0"
            />
            <video
              ref={video}
              src={mediaUrl(project.id, project.master!.path)}
              playsInline
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              className={`absolute object-cover shadow-lg ${circle ? "aspect-square rounded-full" : "aspect-video rounded-[8px]"} ${pos[layout.pip_corner]} ${layout.pip_visible ? "" : "opacity-0"}`}
              style={{ width: `${width * (circle ? 65 : 100)}%` }}
            />
            {!ready && <div className="absolute inset-0 flex items-center justify-center text-sm text-white/70">Loading the preview…</div>}
          </div>

          <div className="mt-3 flex items-center gap-3 text-white">
            <button
              onClick={() => (playing ? video.current?.pause() : video.current?.play())}
              aria-label={playing ? "Pause" : "Play"}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-cue text-ink hover:brightness-95"
            >
              {playing ? (
                <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden><rect x="2" y="1" width="3.5" height="12" rx="1" fill="currentColor" /><rect x="8.5" y="1" width="3.5" height="12" rx="1" fill="currentColor" /></svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden><path d="M3 1.5v11l9.5-5.5z" fill="currentColor" /></svg>
              )}
            </button>
            <div className="relative h-9 min-w-0 flex-1">
              {/* cue ticks: where the browser does something */}
              <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-white/15">
                <div className="h-full rounded-full bg-white/60" style={{ width: `${duration ? (time / duration) * 100 : 0}%` }} />
              </div>
              {cues.map((c) => (
                <button
                  key={c.id}
                  onClick={() => seekTo(c.at_ms - 400)}
                  title={`${fmtTime(c.at_ms)} · ${c.type.replace("_", " ")}`}
                  aria-label={`Jump to cue at ${fmtTime(c.at_ms)}`}
                  className="absolute top-1/2 z-10 h-4 w-[5px] -translate-x-1/2 -translate-y-1/2 rounded-[2px] bg-cue hover:h-5"
                  style={{ left: `${(c.at_ms / duration) * 100}%` }}
                />
              ))}
              <input
                type="range" min={0} max={duration} step={33} value={time} aria-label="Position"
                className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                onChange={(e) => seekTo(Number(e.target.value))}
              />
            </div>
            <span className="w-28 shrink-0 text-right text-xs text-white/70 tabular">{fmtTime(time)} / {fmtTime(duration)}</span>
          </div>
          <p className="mt-2 min-h-5 truncate text-xs text-white/60">
            {currentCue ? <>Last cue: <span className="font-script font-bold text-cue">({currentCue.type.replace("_", " ")} {currentCue.url.replace(/^https?:\/\/(www\.)?/, "") || currentCue.query || currentCue.target})</span></> : "Before the first cue"}
          </p>
        </div>

        <div className="space-y-4 self-start rounded-[var(--radius-panel)] border border-rule bg-surface p-5">
          <div className="text-sm font-bold text-ink">Layout</div>
            <label className="flex items-center gap-2 text-sm text-ink">
              <input type="checkbox" checked={layout.pip_visible} onChange={(e) => patch({ pip_visible: e.target.checked })} />
              Show my video (picture-in-picture)
            </label>
            <div className="grid grid-cols-2 gap-2">
              {(["circle", "rect"] as const).map((shape) => (
                <button key={shape} onClick={() => patch({ pip_shape: shape })}
                  className={`rounded-md border px-2 py-1.5 text-xs ${(layout.pip_shape ?? "circle") === shape ? "border-ink bg-cue-soft text-ink" : "border-rule text-muted"}`}>
                  {shape === "circle" ? "Round avatar" : "Rectangle"}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-2">
              {CORNERS.map((c) => (
                <button key={c} onClick={() => patch({ pip_corner: c })}
                  className={`rounded-md border px-2 py-1.5 text-xs capitalize ${layout.pip_corner === c ? "border-ink bg-cue-soft text-ink" : "border-rule text-muted"}`}>
                  {c.replace("-", " ")}
                </button>
              ))}
            </div>
            <label className="block text-sm text-ink">
              Size: {Math.round(width * 100)}% of width
              <input type="range" min={0.1} max={0.45} step={0.01} value={width} className="mt-1 w-full"
                onChange={(e) => setWidth(Number(e.target.value))}
                onPointerUp={() => patch({ pip_width_pct: width })} onKeyUp={() => patch({ pip_width_pct: width })} />
            </label>
            <label className="flex items-start gap-2 text-sm text-ink">
              <input type="checkbox" className="mt-1" checked={layout.show_dock !== false} onChange={(e) => patch({ show_dock: e.target.checked })} />
              <span>Show the Dock<span className="block text-xs text-muted">The app bar at the bottom of the Mac. Off looks like an auto-hidden Dock.</span></span>
            </label>
            <label className="flex items-start gap-2 text-sm text-ink">
              <input type="checkbox" className="mt-1" checked={layout.camera_zoom === true} onChange={(e) => patch({ camera_zoom: e.target.checked })} />
              <span>Zoom in on each action<span className="block text-xs text-muted">Pushes in on the address bar or link being used. Leave it off for a plain screen recording.</span></span>
            </label>
            <p className="text-xs text-muted">Timing is set on the Browser actions tab. The export uses your original audio.</p>
        </div>
      </div>
    </div>
  );
}
