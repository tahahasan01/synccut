export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type Job = {
  id: string;
  type: "analyze" | "take" | "sync" | "render" | "prepare";
  label: string;
  status: JobStatus;
  progress: number;
  message: string;
  error: string | null;
  created_at: number;
};

export type Beat = {
  id: string;
  text: string;
  label?: string;
  intent?: string;
  site?: string;
  query?: string;
  start_ms: number;
  end_ms: number;
};

export type TakeMode = "guided" | "play_along" | "freeform" | "generated";
export type Take = {
  id: string;
  mode: TakeMode;
  start_beat_idx: number;
  status: "recording" | "processing" | "ready" | "failed";
  created_at: number;
  path: string | null;
  duration_ms: number;
  markers: { beat_id: string; t_ms: number }[];
  events: unknown[];
  error: string | null;
  width?: number;
  height?: number;
};

export type Piece = { in_ms: number; out_ms: number; speed: number };
export type SegmentKind = "face" | "browser" | "hold";
export type Segment = {
  id: string;
  beat_id: string | null;
  start_f: number;
  end_f: number;
  kind: SegmentKind;
  take_id: string | null;
  clip: { in_ms: number; out_ms: number } | null;
  pieces: Piece[];
  hold_ms: number;
  hold_at_ms?: number;
  flags: string[];
  confidence: number;
  needs_review: boolean;
  locked: boolean;
  origin: "auto" | "user";
};

export type Corner = "top-left" | "top-right" | "bottom-left" | "bottom-right";
export type Layout = { pip_corner: Corner; pip_width_pct: number; pip_visible: boolean; camera_zoom?: boolean };

export type ActionType = "navigate" | "search" | "scroll" | "click" | "new_tab" | "switch_tab" | "back";
export type Action = {
  id: string;
  type: ActionType;
  at_ms: number;
  url: string;
  query: string;
  target: string;
  tab: number;
  spoken: string;
  source?: string;
  confidence?: number;
};

export type ScenePage = { id: string; url: string; title: string; image: string | null; status: "ok" | "failed" | "blocked" | "start"; error?: string };
export type Scene = {
  duration_ms: number;
  pages: Record<string, ScenePage>;
  issues: { action_id: string; flags: string[]; late_ms: number }[];
  results: Record<string, { page: string | null; link_text: string | null }>;
  stale: boolean;
};
export type Timeline = {
  version: number;
  fps: number;
  total_frames: number;
  master_duration_ms: number;
  layout: Layout;
  segments: Segment[];
  origin: "auto" | "user";
};

export type Render = {
  id: string;
  poster_path?: string | null;
  preset: "draft" | "final";
  status: "rendering" | "ready" | "failed";
  path: string | null;
  timeline_version: number;
  created_at: number;
  error: string | null;
  seconds?: number;
};

export type Share = {
  slug: string;
  published: boolean;
  title: string;
  message: string;
  cta_label: string;
  render_id: string | null;
};

export type Project = {
  id: string;
  name: string;
  created_at: number;
  updated_at: number;
  master: {
    filename: string;
    path: string;
    probe: { duration_ms: number; width: number; height: number; fps: number } | null;
  } | null;
  transcript: { text: string; model: string; words: { w: string; start_ms: number; end_ms: number }[] } | null;
  beats: Beat[];
  beats_source: "claude" | "rules" | null;
  takes: Take[];
  timeline: Timeline | null;
  timeline_versions: unknown[];
  timeline_stale: boolean;
  renders: Render[];
  jobs: Job[];
  share: Share;
  mode: "generate" | "record";
  page_url?: string;
  actions: Action[];
  actions_source: "claude" | "rules" | "user" | null;
  capture: { run: string; captured_at: number; pages: number } | null;
  layout: Layout;
  browser_video: { scene_hash: string; take_id: string } | null;
};

export type ProjectSummary = {
  id: string;
  name: string;
  updated_at: number;
  has_master: boolean;
  beats: number;
  takes: number;
  exported: boolean;
  share_slug: string | null;
  mode: "generate" | "record";
  captured: boolean;
  synced: boolean;
  duration_ms: number | null;
};

export type Brand = {
  name: string;
  headline: string;
  avatar_url: string;
  accent: string;
  booking_url: string;
  profile_url: string;
  rating_text: string;
  portfolio: { title: string; url: string }[];
};

export type Health = {
  ok: boolean;
  ffmpeg: boolean;
  whisper: { ok: boolean; model?: string; error?: string };
  claude: { configured: boolean; model: string };
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(0, `Can't reach the SyncCut API at ${API_URL}. Is it running?`);
  }
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  health: () => request<Health>("/api/health"),
  listProjects: () => request<ProjectSummary[]>("/api/projects"),
  createProject: (name: string) => request<Project>("/api/projects", json("POST", { name })),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  renameProject: (id: string, name: string) => request<Project>(`/api/projects/${id}`, json("PATCH", { name })),
  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),

  uploadMaster: (id: string, file: File, onProgress?: (fraction: number) => void) =>
    new Promise<Project>((resolve, reject) => {
      const form = new FormData();
      form.append("file", file);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_URL}/api/projects/${id}/master`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) return resolve(JSON.parse(xhr.responseText));
        let message = xhr.statusText;
        try {
          message = JSON.parse(xhr.responseText).detail ?? message;
        } catch {
          /* keep status text */
        }
        reject(new ApiError(xhr.status, message));
      };
      xhr.onerror = () => reject(new ApiError(0, "Upload failed: network error."));
      xhr.send(form);
    }),
  reanalyze: (id: string) => request<Job>(`/api/projects/${id}/analyze`, { method: "POST" }),
  putBeats: (id: string, beats: Beat[]) => request<Project>(`/api/projects/${id}/beats`, json("PUT", { beats })),

  createTake: (id: string, mode: TakeMode, startBeatIdx: number) =>
    request<Take>(`/api/projects/${id}/takes`, json("POST", { mode, start_beat_idx: startBeatIdx })),
  uploadChunk: (id: string, tid: string, seq: number, blob: Blob) =>
    request<void>(`/api/projects/${id}/takes/${tid}/chunks/${seq}`, {
      method: "PUT",
      body: blob,
      headers: { "Content-Type": "application/octet-stream" },
    }),
  completeTake: (
    id: string,
    tid: string,
    body: { rec_start_epoch_ms: number; markers: { beat_id: string; epoch_ms: number }[]; events: unknown[] },
  ) => request<Job>(`/api/projects/${id}/takes/${tid}/complete`, json("POST", body)),
  deleteTake: (id: string, tid: string) => request<void>(`/api/projects/${id}/takes/${tid}`, { method: "DELETE" }),

  sync: (id: string) => request<Job>(`/api/projects/${id}/sync`, { method: "POST" }),
  patchSegment: (
    id: string,
    sid: string,
    patch: Partial<{ kind: SegmentKind; take_id: string; clip: { in_ms: number; out_ms: number }; hold_at_ms: number; locked: boolean }>,
  ) => request<Project>(`/api/projects/${id}/timeline/segments/${sid}`, json("PATCH", patch)),
  patchLayout: (id: string, patch: Partial<Layout>) =>
    request<Project>(`/api/projects/${id}/timeline/layout`, json("PATCH", patch)),
  undoTimeline: (id: string) => request<Project>(`/api/projects/${id}/timeline/undo`, { method: "POST" }),

  render: (id: string, preset: "draft" | "final") =>
    request<Render>(`/api/projects/${id}/renders`, json("POST", { preset })),
  putShare: (id: string, share: Omit<Share, "slug">) => request<Project>(`/api/projects/${id}/share`, json("PUT", share)),
  getShare: (slug: string) =>
    request<{ title: string; message: string; cta_label: string; video_path: string; brand: Brand }>(`/api/share/${slug}`),

  importSubtitles: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Project>(`/api/projects/${id}/subtitles`, { method: "POST", body: form });
  },
  setPage: (id: string, url: string) => request<Project>(`/api/projects/${id}/page`, json("PUT", { url })),
  setMode: (id: string, mode: Project["mode"]) => request<Project>(`/api/projects/${id}/mode`, json("PUT", { mode })),
  prepare: (id: string, replan: boolean) => request<Job>(`/api/projects/${id}/prepare`, json("POST", { replan })),
  putActions: (id: string, actions: Action[]) => request<Project>(`/api/projects/${id}/actions`, json("PUT", { actions })),
  getScene: (id: string) => request<Scene>(`/api/projects/${id}/scene`),

  getBrand: () => request<Brand>("/api/brand"),
  putBrand: (brand: Brand) => request<Brand>("/api/brand", json("PUT", brand)),
};

export const mediaUrl = (projectId: string, path: string) => `${API_URL}/media/${projectId}/${path}`;

/** The generated-browser stage in preview mode; `nonce` forces a reload after edits. */
export const stageUrl = (p: Project, nonce: string) =>
  `${API_URL}/stage/index.html?mode=preview&scene=${encodeURIComponent(`${API_URL}/api/projects/${p.id}/scene?v=${nonce}`)}` +
  `&assets=${encodeURIComponent(`${API_URL}/media/${p.id}/capture/${p.capture?.run}/`)}`;

export function fmtTime(ms: number): string {
  const total = Math.max(0, ms) / 1000;
  const m = Math.floor(total / 60);
  const s = total - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

/** A length for prose ("2:05", "45s"), unlike fmtTime's editing precision. */
export function fmtDuration(ms: number): string {
  const total = Math.round(Math.max(0, ms) / 1000);
  if (total < 60) return `${total}s`;
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export const frameMs = (frame: number, fps: number) => (frame * 1000) / fps;
