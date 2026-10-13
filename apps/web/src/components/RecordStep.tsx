"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, fmtTime, mediaUrl, type Beat, type Project, type TakeMode } from "@/lib/api";
import { useExtension, type ExtMessage } from "@/lib/hooks";
import { TakeRecorder, type RecorderState } from "@/lib/recorder";
import { InPip, pipSupported, usePipWindow } from "./Teleprompter";
import { Badge, Button, Card, JobLine, Notice } from "./ui";

const MODES: { id: TakeMode; title: string; body: string }[] = [
  {
    id: "guided",
    title: "Guided",
    body: "The teleprompter shows each step. Press Next (or Alt+Shift+N) as you start it. Most reliable.",
  },
  {
    id: "play_along",
    title: "Play-along",
    body: "Your narration plays in your headphones while you browse along with it. Steps are marked automatically.",
  },
  {
    id: "freeform",
    title: "Free-form",
    body: "Just browse. Steps are matched to your clicks and page loads by timing, and flagged for review.",
  },
];

export function RecordStep({ project, onDone }: { project: Project; onDone: () => void }) {
  const [mode, setMode] = useState<TakeMode>("guided");
  const [startIdx, setStartIdx] = useState(0);
  const [rec, setRec] = useState<RecorderState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<TakeRecorder | null>(null);
  const pip = usePipWindow();

  const onExt = useCallback((msg: ExtMessage) => {
    if (msg.type === "event") recorder.current?.addEvent(msg.event);
    if (msg.type === "command" && msg.command === "next-beat") recorder.current?.markNext();
  }, []);
  const ext = useExtension(onExt);

  const recording = rec?.phase === "recording" || rec?.phase === "starting" || rec?.phase === "finishing";
  const beats = project.beats;

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (rec?.phase === "recording" && (e.key === "n" || e.key === "N" || e.code === "Space") && !(e.target instanceof HTMLInputElement)) {
        e.preventDefault();
        recorder.current?.markNext();
      }
    };
    const targets = [window, pip.win].filter(Boolean) as Window[];
    targets.forEach((t) => t.addEventListener("keydown", key));
    return () => targets.forEach((t) => t.removeEventListener("keydown", key));
  }, [rec?.phase, pip.win]);

  async function start() {
    setError(null);
    if (!navigator.mediaDevices?.getDisplayMedia) {
      setError("This browser can't record the screen. Use Chrome or Edge.");
      return;
    }
    const r = new TakeRecorder({
      projectId: project.id,
      mode,
      beats,
      startIdx,
      narrationUrl: mediaUrl(project.id, project.master!.path),
      onState: setRec,
    });
    recorder.current = r;
    try {
      await r.start();
      ext.send("recording-start");
    } catch (e) {
      recorder.current = null;
      if (!(e instanceof DOMException && e.name === "NotAllowedError")) setError(String(e));
    }
  }

  async function stop() {
    await recorder.current?.stop();
    ext.send("recording-stop");
    recorder.current = null;
    pip.close();
    onDone();
  }

  const current: Beat | undefined = beats[rec?.beatIdx ?? startIdx];
  const nextBeat: Beat | undefined = beats[(rec?.beatIdx ?? startIdx) + (mode === "guided" && (rec?.marked ?? 0) === 0 ? 0 : 1)];
  const waitingForFirst = mode === "guided" && rec?.phase === "recording" && (rec?.marked ?? 0) === 0;

  const prompter = (
    <div className="flex h-full flex-col gap-3 p-5">
      <div className="flex items-center justify-between text-xs uppercase tracking-wide text-muted">
        <span>
          {rec?.phase === "recording" ? <span className="text-signal">● REC {fmtTime(rec.elapsedMs)}</span> : "Teleprompter"}
        </span>
        <span>
          Step {(rec?.beatIdx ?? startIdx) + 1} / {beats.length}
        </span>
      </div>
      {waitingForFirst ? (
        <div className="text-lg font-semibold">Press Next when you start step {startIdx + 1}:</div>
      ) : null}
      <div className="text-2xl font-semibold leading-tight">{current?.label || current?.text}</div>
      {current?.label && <div className="text-sm text-muted">&ldquo;{current.text}&rdquo;</div>}
      {nextBeat && !waitingForFirst && (
        <div className="mt-auto text-sm text-muted">
          Next: <span className="text-white/70">{nextBeat.label || nextBeat.text}</span>
        </div>
      )}
      <div className="flex gap-2 pt-2">
        {mode === "guided" && rec?.phase === "recording" && (
          <button className="flex-1 rounded-lg bg-cue px-4 py-3 text-base font-bold text-ink hover:brightness-95" onClick={() => recorder.current?.markNext()}>
            {waitingForFirst ? "Start step" : "Next step"} ▸
          </button>
        )}
        {rec?.phase === "recording" && (
          <button className="rounded-lg bg-white/10 px-4 py-3 text-sm font-medium text-white hover:bg-white/20" onClick={stop}>
            Stop
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div className="space-y-5">
      <Card title="Record your browser">
        {!ext.connected && (
          <div className="mb-4">
            <Notice tone="warn">
              The SyncCut extension isn&apos;t connected. Recording still works, but without it you lose the
              Alt+Shift+N hotkey and click/tab events (needed for Free-form). Load <code>apps/extension</code> in{" "}
              <code>chrome://extensions</code> (Developer mode → Load unpacked), then reload this page.
            </Notice>
          </div>
        )}
        <div className="grid gap-3 md:grid-cols-3">
          {MODES.map((m) => (
            <button
              key={m.id}
              disabled={recording}
              onClick={() => setMode(m.id)}
              className={`rounded-xl border p-4 text-left transition ${mode === m.id ? "border-ink bg-cue-soft ring-2 ring-cue" : "border-rule hover:border-rule-strong"}`}
            >
              <div className="font-medium text-ink">{m.title}</div>
              <div className="mt-1 text-sm text-muted">{m.body}</div>
            </button>
          ))}
        </div>

        <div className="mt-5 flex flex-wrap items-end gap-4">
          <label className="text-sm">
            <span className="mb-1 block font-medium text-ink">Start at step</span>
            <select
              disabled={recording}
              value={startIdx}
              onChange={(e) => setStartIdx(Number(e.target.value))}
              className="rounded-lg border border-rule-strong bg-white px-3 py-2 text-sm"
            >
              {beats.map((b, i) => (
                <option key={b.id} value={i}>
                  {i + 1}. {(b.label || b.text).slice(0, 60)}
                </option>
              ))}
            </select>
          </label>
          {pipSupported() && !pip.win && (
            <Button variant="secondary" onClick={() => pip.open()}>Open floating teleprompter</Button>
          )}
          {!recording ? (
            <Button onClick={start}>● Start recording</Button>
          ) : (
            <Button variant="danger" onClick={stop} disabled={rec?.phase !== "recording"}>■ Stop recording</Button>
          )}
        </div>
        <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-muted">
          <li>When Chrome asks what to share, pick the <strong>window</strong> (or tab) you&apos;ll browse in, not this one.</li>
          <li>Open the floating teleprompter first. It stays on top and isn&apos;t recorded.</li>
          <li>Pick a later &ldquo;Start at step&rdquo; to redo just one step. The newest take wins for each step.</li>
        </ul>
        {error && <div className="mt-4"><Notice tone="bad">{error}</Notice></div>}
        {rec?.error && <div className="mt-4"><Notice tone="bad">{rec.error}</Notice></div>}
        {rec && rec.phase !== "idle" && (
          <div className="mt-4 text-xs text-muted">
            Uploaded {rec.uploadedChunks} parts{rec.pendingChunks ? `, ${rec.pendingChunks} pending` : ""}
            {rec.phase === "finishing" && " · finishing upload…"}
          </div>
        )}
      </Card>

      {(recording || pip.win) && (
        <InPip win={pip.win}>
          <div className={pip.win ? "h-full" : "overflow-hidden rounded-xl bg-monitor text-white"}>{prompter}</div>
        </InPip>
      )}

      <TakesList project={project} onChange={onDone} />
    </div>
  );
}

function TakesList({ project, onChange }: { project: Project; onChange: () => void }) {
  if (!project.takes.some((t) => t.mode !== "generated")) return null;
  const beatIndex = new Map(project.beats.map((b, i) => [b.id, i + 1]));
  return (
    <Card title="Takes">
      <div className="mb-3"><JobLine project={project} type="take" /></div>
      <ul className="divide-y divide-rule">
        {project.takes.filter((t) => t.mode !== "generated").reverse().map((t) => {
          const steps = t.markers.map((m) => beatIndex.get(m.beat_id)).filter(Boolean);
          return (
            <li key={t.id} className="flex flex-wrap items-center gap-3 py-3 text-sm">
              <Badge tone={t.status === "ready" ? "good" : t.status === "failed" ? "bad" : "info"}>{t.status}</Badge>
              <span className="font-medium text-ink">{t.mode.replace("_", "-")}</span>
              <span className="text-muted">{t.duration_ms ? fmtTime(t.duration_ms) : ""}</span>
              <span className="text-muted">
                {steps.length ? `steps ${steps[0]}–${steps[steps.length - 1]}` : t.mode === "freeform" ? "matched by timing" : "no step markers"}
              </span>
              {t.error && <span className="text-signal">{t.error}</span>}
              <span className="ml-auto">
                <Button
                  variant="ghost"
                  disabled={t.status === "processing" || t.status === "recording"}
                  onClick={async () => {
                    if (confirm("Delete this take? Steps using it will need a re-sync.")) {
                      await api.deleteTake(project.id, t.id);
                      onChange();
                    }
                  }}
                >
                  Delete
                </Button>
              </span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
