"use client";

import { api, type Beat, type TakeMode } from "./api";

export const epochNow = () => performance.timeOrigin + performance.now();

const MIME_CANDIDATES = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];

export type RecordingResult = { takeId: string };

type Options = {
  projectId: string;
  mode: TakeMode;
  beats: Beat[];
  startIdx: number;
  narrationUrl: string;
  onState: (s: RecorderState) => void;
};

export type RecorderState = {
  phase: "idle" | "starting" | "recording" | "finishing" | "done" | "error";
  beatIdx: number; // beat currently being performed
  marked: number; // beats marked so far (guided)
  elapsedMs: number;
  uploadedChunks: number;
  pendingChunks: number;
  error?: string;
};

/**
 * Records the chosen window/tab with getDisplayMedia, uploads 2 s chunks as it
 * goes, and collects beat markers + extension events with one epoch clock.
 */
export class TakeRecorder {
  private stream?: MediaStream;
  private recorder?: MediaRecorder;
  private audio?: HTMLAudioElement;
  private takeId?: string;
  private seq = 0;
  private uploads: Promise<void> = Promise.resolve();
  private uploaded = 0;
  private pending = 0;
  private recStart = 0;
  private audioStart = 0;
  private markers: { beat_id: string; epoch_ms: number }[] = [];
  private events: Record<string, unknown>[] = [];
  private tick?: ReturnType<typeof setInterval>;
  private stopped?: Promise<void>;
  private state: RecorderState = { phase: "idle", beatIdx: 0, marked: 0, elapsedMs: 0, uploadedChunks: 0, pendingChunks: 0 };

  constructor(private opts: Options) {
    this.state.beatIdx = opts.startIdx;
  }

  private emit(patch: Partial<RecorderState>) {
    this.state = { ...this.state, ...patch, uploadedChunks: this.uploaded, pendingChunks: this.pending };
    this.opts.onState(this.state);
  }

  async start(): Promise<void> {
    this.emit({ phase: "starting" });
    const constraints = {
      video: { frameRate: { ideal: 30, max: 30 }, width: { ideal: 1920 }, height: { ideal: 1080 } },
      audio: false,
      selfBrowserSurface: "exclude",
      surfaceSwitching: "include",
      monitorTypeSurfaces: "include",
    } as DisplayMediaStreamOptions;
    try {
      this.stream = await navigator.mediaDevices.getDisplayMedia(constraints);
    } catch (e) {
      this.emit({ phase: "idle", error: e instanceof Error && e.name === "NotAllowedError" ? "Screen sharing was cancelled." : String(e) });
      throw e;
    }
    const take = await api.createTake(this.opts.projectId, this.opts.mode, this.opts.startIdx);
    this.takeId = take.id;

    const mimeType = MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m)) ?? "";
    this.recorder = new MediaRecorder(this.stream, { mimeType, videoBitsPerSecond: 8_000_000 });
    this.recorder.ondataavailable = (e) => e.data.size > 0 && this.queueChunk(e.data);
    this.stopped = new Promise((resolve) => this.recorder!.addEventListener("stop", () => resolve(), { once: true }));
    this.stream.getVideoTracks()[0].addEventListener("ended", () => void this.stop());

    this.recorder.addEventListener(
      "start",
      () => {
        this.recStart = epochNow();
        if (this.opts.mode === "play_along") this.startNarration();
        this.tick = setInterval(() => this.onTick(), 200);
        this.emit({ phase: "recording" });
      },
      { once: true },
    );
    this.recorder.start(2000);
  }

  private startNarration() {
    const beat = this.opts.beats[this.opts.startIdx];
    const offset = beat?.start_ms ?? 0;
    const audio = new Audio(this.opts.narrationUrl);
    audio.preload = "auto";
    audio.addEventListener("playing", () => {
      if (!this.audioStart) this.audioStart = epochNow() - (audio.currentTime * 1000 - offset);
    }, { once: true });
    audio.addEventListener("ended", () => void this.stop());
    audio.addEventListener("loadedmetadata", () => {
      audio.currentTime = offset / 1000;
      audio.play().catch((e) => this.emit({ error: `Couldn't play narration: ${e}` }));
    }, { once: true });
    this.audio = audio;
  }

  private onTick() {
    const elapsed = epochNow() - this.recStart;
    let beatIdx = this.state.beatIdx;
    if (this.opts.mode === "play_along" && this.audio) {
      const t = this.audio.currentTime * 1000;
      const idx = this.opts.beats.findLastIndex((b) => b.start_ms <= t + 50);
      if (idx >= 0) beatIdx = idx;
    }
    this.emit({ elapsedMs: elapsed, beatIdx });
  }

  /** Guided mode: the user is starting the current beat now. */
  markNext() {
    if (this.state.phase !== "recording" || this.opts.mode !== "guided") return;
    const idx = this.opts.startIdx + this.markers.length;
    const beat = this.opts.beats[idx];
    if (!beat) return;
    this.markers.push({ beat_id: beat.id, epoch_ms: epochNow() });
    this.emit({ marked: this.markers.length, beatIdx: idx });
  }

  addEvent(event: Record<string, unknown>) {
    if (this.state.phase === "recording") this.events.push(event);
  }

  private queueChunk(blob: Blob) {
    const seq = this.seq++;
    this.pending++;
    this.emit({});
    this.uploads = this.uploads.then(async () => {
      for (let attempt = 0; ; attempt++) {
        try {
          await api.uploadChunk(this.opts.projectId, this.takeId!, seq, blob);
          break;
        } catch (e) {
          if (attempt >= 4) {
            this.emit({ error: `Upload of part ${seq} failed: ${e}` });
            throw e;
          }
          await new Promise((r) => setTimeout(r, 500 * 2 ** attempt));
        }
      }
      this.pending--;
      this.uploaded++;
      this.emit({});
    });
  }

  private playAlongMarkers() {
    if (!this.audioStart) return [];
    const stopEpoch = epochNow();
    const offset = this.opts.beats[this.opts.startIdx]?.start_ms ?? 0;
    return this.opts.beats
      .slice(this.opts.startIdx)
      .map((b) => ({ beat_id: b.id, epoch_ms: this.audioStart + (b.start_ms - offset) }))
      .filter((m) => m.epoch_ms < stopEpoch);
  }

  async stop(): Promise<RecordingResult | undefined> {
    if (!this.recorder || this.state.phase !== "recording") return;
    this.emit({ phase: "finishing" });
    clearInterval(this.tick);
    this.audio?.pause();
    if (this.recorder.state !== "inactive") this.recorder.stop();
    await this.stopped;
    this.stream?.getTracks().forEach((t) => t.stop());
    try {
      await this.uploads;
      const markers = this.opts.mode === "play_along" ? this.playAlongMarkers() : this.markers;
      await api.completeTake(this.opts.projectId, this.takeId!, {
        rec_start_epoch_ms: this.recStart,
        markers,
        events: this.events,
      });
      this.emit({ phase: "done" });
      return { takeId: this.takeId! };
    } catch (e) {
      this.emit({ phase: "error", error: e instanceof Error ? e.message : String(e) });
    }
  }
}
