"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, fmtTime, mediaUrl, type Action, type ActionType, type Project, type Scene } from "@/lib/api";
import { Badge, Button, JobLine, Notice, inputClass } from "./ui";

const TYPES: { id: ActionType; label: string; field: "url" | "query" | "target" | "tab" | null; placeholder?: string }[] = [
  { id: "navigate", label: "Open a website", field: "url", placeholder: "hubspot.com" },
  { id: "search", label: "Search", field: "query", placeholder: "what to search for" },
  { id: "scroll", label: "Scroll", field: "target", placeholder: "down, up, bottom, top, or text on the page" },
  { id: "click", label: "Click", field: "target", placeholder: "link text, or “first result”" },
  { id: "new_tab", label: "Open a new tab", field: null },
  { id: "switch_tab", label: "Switch tab", field: "tab" },
  { id: "new_window", label: "Open a new window", field: null },
  { id: "switch_window", label: "Switch window", field: "tab" },
  { id: "back", label: "Go back", field: null },
];

const ISSUE_TEXT: Record<string, { text: string; tone: "warn" | "bad" | "neutral" }> = {
  page_unavailable: { text: "This page couldn't be captured", tone: "bad" },
  target_not_found: { text: "That link wasn't found on the page", tone: "bad" },
  not_a_link: { text: "That target isn't a link", tone: "warn" },
  scroll_text_not_found: { text: "Text not found, so it scrolls down instead", tone: "warn" },
  no_such_tab: { text: "There's no tab with that number in this window", tone: "bad" },
  no_such_window: { text: "There's no window with that number", tone: "bad" },
  too_many_windows: { text: "Up to 3 windows can be open", tone: "warn" },
  nothing_to_go_back_to: { text: "There's no earlier page to go back to", tone: "warn" },
  late: { text: "Starts late because the previous cue is still playing", tone: "warn" },
  not_captured: { text: "Not captured yet", tone: "warn" },
  rules_guess: { text: "Found by phrase matching", tone: "neutral" },
};

const bare = (url: string) => url.replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/$/, "");

/** How a cue reads inside the script: a short stage direction. */
function cueText(a: Action): string {
  switch (a.type) {
    case "navigate": return `open ${bare(a.url) || "a website"}`;
    case "search": return `search “${a.query}”`;
    case "scroll": return ["down", "up", "bottom", "top"].includes(a.target) ? `scroll ${a.target === "bottom" || a.target === "top" ? `to the ${a.target}` : a.target}` : `scroll to “${a.target}”`;
    case "click": return `click “${a.target}”`;
    case "new_tab": return "open a new tab";
    case "switch_tab": return a.tab < 0 ? "switch to the previous tab" : `switch to tab ${a.tab + 1}`;
    case "new_window": return "open a new window";
    case "switch_window": return a.tab < 0 ? "switch to the other window" : `switch to window ${a.tab + 1}`;
    case "back": return "go back";
  }
}

export function ActionsStep({ project, onChange }: { project: Project; onChange: (p: Project) => void }) {
  return <ScriptEditor key={JSON.stringify(project.actions)} project={project} onChange={onChange} />;
}

type Selection = { kind: "cue"; index: number } | { kind: "new"; at: number } | null;

function ScriptEditor({ project, onChange }: { project: Project; onChange: (p: Project) => void }) {
  const [actions, setActions] = useState<Action[]>(project.actions);
  const [scene, setScene] = useState<Scene | null>(null);
  const [selected, setSelected] = useState<Selection>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const editorRef = useRef<HTMLDivElement>(null);
  const preparing = project.jobs.some((j) => j.type === "prepare" && (j.status === "queued" || j.status === "running"));
  const dirty = JSON.stringify(actions) !== JSON.stringify(project.actions);
  const duration = project.master?.probe?.duration_ms ?? 0;

  useEffect(() => {
    if (!project.capture || preparing) return;
    let alive = true;
    api.getScene(project.id).then((s) => alive && setScene(s), () => alive && setScene(null));
    return () => {
      alive = false;
    };
  }, [project.id, project.capture, preparing, project.actions]);

  const issues = useMemo(() => new Map((scene?.issues ?? []).map((i) => [i.action_id, i.flags])), [scene]);
  const order = useMemo(() => actions.map((a, i) => ({ a, i })).sort((x, y) => x.a.at_ms - y.a.at_ms), [actions]);

  function select(next: Selection) {
    setSelected(next);
    if (next && window.matchMedia("(max-width: 1023px)").matches) {
      requestAnimationFrame(() => editorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    }
  }

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      onChange(await api.getProject(project.id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  async function save() {
    setSaving(true);
    await run(async () => {
      await api.putActions(project.id, actions);
      await api.prepare(project.id, false); // re-captures only if something other than timing changed
    });
    setSaving(false);
  }

  const update = (i: number, patch: Partial<Action>) => setActions((as) => as.map((a, j) => (j === i ? { ...a, ...patch } : a)));

  function addAt(at: number, type: ActionType, value: string) {
    const action: Action = { id: "", type, at_ms: at, url: "", query: "", target: "", tab: 0, spoken: "", source: "user" };
    const field = TYPES.find((t) => t.id === type)!.field;
    if (field === "url") action.url = value;
    else if (field === "query") action.query = value;
    else if (field === "target") action.target = value || (type === "scroll" ? "down" : "");
    const next = [...actions, action];
    setActions(next);
    select({ kind: "cue", index: next.length - 1 });
  }

  const flagged = order.filter(({ a }) => (issues.get(a.id) ?? []).some((f) => ISSUE_TEXT[f]?.tone === "bad")).length;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h2 className="text-lg font-bold tracking-tight">Browser actions</h2>
          <p className="mt-1 text-sm text-muted">
            Your narration, set as a script. Each yellow cue is something the browser does, at the word where it sits. Click a
            cue to change it, or click any word to add a cue there.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {project.actions_source && (
            <Badge tone={project.actions_source === "claude" ? "info" : "neutral"}>
              {project.actions_source === "claude" ? "Planned by Claude" : project.actions_source === "rules" ? "Found by phrase matching" : "Edited by you"}
            </Badge>
          )}
          <Button variant="ghost" disabled={preparing || !project.transcript}
            onClick={() => confirm("Replace all cues with a fresh plan from the narration?") && run(() => api.prepare(project.id, true))}>
            Re-plan from narration
          </Button>
          {dirty && <Button variant="secondary" onClick={() => { setActions(project.actions); setSelected(null); }}>Discard changes</Button>}
          <Button disabled={(!dirty && !scene?.stale) || saving || preparing} onClick={save}>{saving ? "Saving…" : "Save and capture pages"}</Button>
        </div>
      </div>

      <div className="space-y-3">
        <JobLine project={project} type="prepare" />
        {error && <Notice tone="bad">{error}</Notice>}
        {scene?.stale && !preparing && !dirty && (
          <Notice tone="warn">The captured pages are out of date because the cues or the browser layout changed. Save and capture pages to update them.</Notice>
        )}
        {!project.transcript && <Notice>Add the narration first. The script is made from its transcript.</Notice>}
      </div>

      {project.transcript && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
          <Script
            project={project}
            order={order}
            issues={issues}
            selected={selected}
            onSelectCue={(index) => select({ kind: "cue", index })}
            onPickWord={(at) => select({ kind: "new", at })}
          />
          <div ref={editorRef} className="lg:sticky lg:top-4 lg:self-start">
            {selected?.kind === "cue" && actions[selected.index] ? (
              <CueEditor
                key={selected.index}
                project={project}
                action={actions[selected.index]}
                flags={issues.get(actions[selected.index].id) ?? []}
                scene={scene}
                duration={duration}
                onChange={(patch) => update(selected.index, patch)}
                onRemove={() => { setActions(actions.filter((_, j) => j !== selected.index)); setSelected(null); }}
                onStep={(dir) => {
                  const pos = order.findIndex((o) => o.i === selected.index) + dir;
                  if (order[pos]) select({ kind: "cue", index: order[pos].i });
                }}
              />
            ) : selected?.kind === "new" ? (
              <NewCue at={selected.at} onAdd={addAt} onCancel={() => setSelected(null)} />
            ) : (
              <Summary count={actions.length} pages={project.capture?.pages ?? 0} flagged={flagged} dirty={dirty} />
            )}
          </div>
        </div>
      )}

      <p className="text-sm text-muted">
        Prefer to show your own browser?{" "}
        <button className="font-semibold text-ink underline decoration-cue decoration-2 underline-offset-4" onClick={() => run(() => api.setMode(project.id, "record"))}>
          Switch to recording mode
        </button>
      </p>
    </div>
  );
}

/* ── The script ─────────────────────────────────────────────────────────── */

function Script({
  project, order, issues, selected, onSelectCue, onPickWord,
}: {
  project: Project;
  order: { a: Action; i: number }[];
  issues: Map<string, string[]>;
  selected: Selection;
  onSelectCue: (index: number) => void;
  onPickWord: (at: number) => void;
}) {
  const words = project.transcript!.words;
  const beats = project.beats.length ? project.beats : [{ id: "all", text: "", start_ms: 0, end_ms: Infinity }];

  // Each cue sits just before the first word spoken at or after its time.
  const cuesBefore = new Map<number, { a: Action; i: number }[]>();
  const trailing: { a: Action; i: number }[] = [];
  for (const cue of order) {
    const w = words.findIndex((x) => x.start_ms >= cue.a.at_ms - 1);
    if (w < 0) trailing.push(cue);
    else cuesBefore.set(w, [...(cuesBefore.get(w) ?? []), cue]);
  }

  const renderCue = ({ a, i }: { a: Action; i: number }) => {
    const flags = issues.get(a.id) ?? [];
    const bad = flags.some((f) => ISSUE_TEXT[f]?.tone === "bad");
    const isSel = selected?.kind === "cue" && selected.index === i;
    return (
      <button
        key={`cue-${i}`}
        onClick={() => onSelectCue(i)}
        aria-pressed={isSel}
        title={`${fmtTime(a.at_ms)}: ${cueText(a)}`}
        className={`mx-0.5 inline rounded-[3px] px-1.5 py-0.5 font-script text-[15px] font-bold not-italic leading-loose ${
          isSel ? "bg-cue text-ink ring-2 ring-ink" : bad ? "bg-signal-soft text-signal ring-1 ring-signal/40" : "bg-cue-soft text-ink hover:bg-cue"
        }`}
      >
        ({cueText(a)})
      </button>
    );
  };

  const pending = selected?.kind === "new" ? selected.at : null;

  return (
    <article aria-label="Narration script" className="rounded-[var(--radius-panel)] border border-rule bg-surface px-4 py-5 sm:px-8 sm:py-7">
      <div className="space-y-5">
        {beats.map((beat, b) => {
          const end = beats[b + 1]?.start_ms ?? Infinity;
          const idx = words.map((w, k) => ({ w, k })).filter(({ w }) => w.start_ms >= beat.start_ms - 1 && w.start_ms < end - 1);
          if (!idx.length) return null;
          return (
            <div key={beat.id} className="grid grid-cols-[3.75rem_minmax(0,1fr)] gap-3">
              <span className="pt-1 text-xs font-semibold text-muted tabular">{fmtTime(beat.start_ms)}</span>
              <p className="max-w-[68ch] font-script text-[17px] leading-[2] text-ink">
                {idx.map(({ w, k }) => (
                  <Fragment key={k}>
                    {(cuesBefore.get(k) ?? []).map(renderCue)}
                    <span
                      onClick={() => onPickWord(w.start_ms)}
                      className={`cursor-pointer rounded-[2px] hover:bg-cue-soft ${pending === w.start_ms ? "bg-cue" : ""}`}
                    >
                      {w.w}
                    </span>{" "}
                  </Fragment>
                ))}
              </p>
            </div>
          );
        })}
        {trailing.length > 0 && (
          <div className="grid grid-cols-[3.75rem_minmax(0,1fr)] gap-3">
            <span />
            <p className="font-script text-[17px] leading-[2]">{trailing.map(renderCue)}</p>
          </div>
        )}
      </div>
    </article>
  );
}

/* ── Side panel ─────────────────────────────────────────────────────────── */

const panel = "rounded-[var(--radius-panel)] border border-rule bg-surface p-5";

function Summary({ count, pages, flagged, dirty }: { count: number; pages: number; flagged: number; dirty: boolean }) {
  return (
    <div className={panel}>
      <div className="flex gap-6">
        <div><div className="text-2xl font-extrabold tabular">{count}</div><div className="text-xs text-muted">cues</div></div>
        <div><div className="text-2xl font-extrabold tabular">{pages}</div><div className="text-xs text-muted">pages captured</div></div>
        <div><div className={`text-2xl font-extrabold tabular ${flagged ? "text-signal" : ""}`}>{flagged}</div><div className="text-xs text-muted">need a look</div></div>
      </div>
      <p className="mt-4 text-sm text-muted">
        {dirty ? "You have unsaved changes. Save to capture the pages again." : "Select a cue to see the page it shows and change what it does."}
      </p>
    </div>
  );
}

function NewCue({ at, onAdd, onCancel }: { at: number; onAdd: (at: number, type: ActionType, value: string) => void; onCancel: () => void }) {
  const [type, setType] = useState<ActionType>("navigate");
  const [value, setValue] = useState("");
  const spec = TYPES.find((t) => t.id === type)!;
  return (
    <form className={panel} onSubmit={(e) => { e.preventDefault(); onAdd(at, type, value); }}>
      <h3 className="font-bold">New cue at <span className="tabular">{fmtTime(at)}</span></h3>
      <div className="mt-4 grid grid-cols-2 gap-2" role="radiogroup" aria-label="What the browser does">
        {TYPES.map((t) => (
          <button key={t.id} type="button" role="radio" aria-checked={type === t.id} onClick={() => setType(t.id)}
            className={`rounded-[var(--radius-control)] px-2.5 py-2 text-left text-sm font-semibold ring-1 ring-inset ${type === t.id ? "bg-cue ring-ink" : "ring-rule-strong hover:ring-ink"}`}>
            {t.label}
          </button>
        ))}
      </div>
      {spec.field && spec.field !== "tab" && (
        <input autoFocus className={`${inputClass} mt-3`} placeholder={spec.placeholder} value={value} onChange={(e) => setValue(e.target.value)} />
      )}
      <div className="mt-4 flex gap-2">
        <Button type="submit">Add cue</Button>
        <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}

function CueEditor({
  project, action, flags, scene, duration, onChange, onRemove, onStep,
}: {
  project: Project;
  action: Action;
  flags: string[];
  scene: Scene | null;
  duration: number;
  onChange: (patch: Partial<Action>) => void;
  onRemove: () => void;
  onStep: (dir: -1 | 1) => void;
}) {
  const spec = TYPES.find((t) => t.id === action.type)!;
  const result = scene?.results?.[action.id];
  const page = result?.page ? scene?.pages[result.page] : null;
  const nudge = (ms: number) => onChange({ at_ms: Math.min(Math.max(0, action.at_ms + ms), Math.max(duration - 500, 0)) });

  return (
    <div className={panel}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold text-muted tabular">{fmtTime(action.at_ms)}</div>
          <h3 className="mt-0.5 font-script text-lg font-bold leading-snug">({cueText(action)})</h3>
        </div>
        <div className="flex shrink-0 gap-1">
          <Button variant="ghost" className="px-2" aria-label="Previous cue" onClick={() => onStep(-1)}>‹</Button>
          <Button variant="ghost" className="px-2" aria-label="Next cue" onClick={() => onStep(1)}>›</Button>
        </div>
      </div>

      {page?.image && project.capture && (
        <figure className="mt-4">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={mediaUrl(project.id, `capture/${project.capture.run}/${page.image}`)} alt={`Captured page: ${page.title}`}
            className="aspect-[16/10] w-full rounded-[var(--radius-control)] border border-rule object-cover object-top" />
          <figcaption className="mt-1.5 truncate text-xs text-muted">{page.title} · {bare(page.url)}</figcaption>
        </figure>
      )}
      {result?.link_text && <p className="mt-2 text-xs text-muted">Clicks the link “{result.link_text}”.</p>}
      {page && page.status !== "ok" && page.error && <div className="mt-3"><Notice tone="bad">{page.error}</Notice></div>}
      {flags.filter((f) => ISSUE_TEXT[f] && f !== "rules_guess").map((f) => (
        <div key={f} className="mt-3"><Notice tone={ISSUE_TEXT[f].tone === "bad" ? "bad" : "warn"}>{ISSUE_TEXT[f].text}.</Notice></div>
      ))}

      <div className="mt-5 space-y-3">
        <label className="block">
          <span className="mb-1.5 block text-sm font-semibold">When</span>
          <div className="flex items-center gap-2">
            <Button type="button" variant="secondary" className="px-2.5" onClick={() => nudge(-200)} aria-label="0.2 seconds earlier">−0.2s</Button>
            <input type="number" step={0.1} min={0} max={duration / 1000} className={`${inputClass} text-center tabular`}
              value={(action.at_ms / 1000).toFixed(1)} onChange={(e) => onChange({ at_ms: Math.max(0, Number(e.target.value) * 1000) })} />
            <Button type="button" variant="secondary" className="px-2.5" onClick={() => nudge(200)} aria-label="0.2 seconds later">+0.2s</Button>
          </div>
        </label>
        <label className="block">
          <span className="mb-1.5 block text-sm font-semibold">What the browser does</span>
          <select className={inputClass} value={action.type} onChange={(e) => onChange({ type: e.target.value as ActionType })}>
            {TYPES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
        </label>
        {spec.field === "tab" ? (
          <label className="block">
            <span className="mb-1.5 block text-sm font-semibold">{action.type === "switch_window" ? "Which window" : "Which tab"}</span>
            <select className={inputClass} value={action.tab} onChange={(e) => onChange({ tab: Number(e.target.value) })}>
              {action.type === "switch_window" ? (
                <>
                  <option value={-1}>The other window</option>
                  {[0, 1, 2].map((n) => <option key={n} value={n}>Window {n + 1}</option>)}
                </>
              ) : (
                <>
                  <option value={-1}>The previous tab</option>
                  {[0, 1, 2, 3].map((n) => <option key={n} value={n}>Tab {n + 1}</option>)}
                </>
              )}
            </select>
          </label>
        ) : spec.field ? (
          <label className="block">
            <span className="mb-1.5 block text-sm font-semibold">{spec.field === "url" ? "Website" : spec.field === "query" ? "Search for" : action.type === "click" ? "Link to click" : "Scroll to"}</span>
            <input className={inputClass} placeholder={spec.placeholder} value={action[spec.field] as string}
              onChange={(e) => onChange({ [spec.field as "url"]: e.target.value })} />
          </label>
        ) : null}
        {action.spoken && <p className="text-xs text-muted">Placed at “{action.spoken}”.</p>}
      </div>

      <div className="mt-5 border-t border-rule pt-4">
        <Button variant="danger" onClick={onRemove}>Remove cue</Button>
      </div>
    </div>
  );
}
