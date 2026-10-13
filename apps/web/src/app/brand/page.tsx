"use client";

import { useEffect, useRef, useState } from "react";
import { Button, Card, Field, Notice, inputClass } from "@/components/ui";
import { api, API_URL, ApiError, type Brand, type Skin } from "@/lib/api";

export default function BrandPage() {
  const [brand, setBrand] = useState<Brand | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.getBrand().then(setBrand, (e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!brand) return;
    setError(null);
    try {
      setBrand(await api.putBrand(brand));
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  if (!brand) return <main className="mx-auto max-w-3xl p-6 text-sm text-muted">{error ?? "Loading…"}</main>;
  const set = (patch: Partial<Brand>) => setBrand({ ...brand, ...patch });

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <h1 className="text-[28px] font-extrabold leading-tight tracking-tight text-ink">Brand</h1>
      <p className="mt-1 text-sm text-muted">Shown on every share page. Use your own name and brand.</p>
      <div className="mt-6 grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_340px]">
      <form onSubmit={save} className="space-y-5">
        <Card title="You">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Name"><input className={inputClass} value={brand.name} onChange={(e) => set({ name: e.target.value })} /></Field>
            <Field label="Headline" hint="e.g. Automation engineer · Make, n8n, Python">
              <input className={inputClass} value={brand.headline} onChange={(e) => set({ headline: e.target.value })} />
            </Field>
            <Field label="Photo URL"><input className={inputClass} value={brand.avatar_url} onChange={(e) => set({ avatar_url: e.target.value })} /></Field>
            <Field label="Accent colour">
              <input type="color" className="h-10 w-20 rounded border border-rule-strong" value={brand.accent} onChange={(e) => set({ accent: e.target.value })} />
            </Field>
          </div>
        </Card>
        <Card title="Proof and call to action">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Rating or track record" hint="e.g. Top Rated · 100% Job Success · 40 projects">
              <input className={inputClass} value={brand.rating_text} onChange={(e) => set({ rating_text: e.target.value })} />
            </Field>
            <Field label="Profile link" hint="e.g. your Upwork profile URL">
              <input className={inputClass} value={brand.profile_url} onChange={(e) => set({ profile_url: e.target.value })} />
            </Field>
            <div className="md:col-span-2">
              <Field label="Booking calendar link" hint="Calendly or Cal.com link. It's embedded on the share page.">
                <input className={inputClass} value={brand.booking_url} onChange={(e) => set({ booking_url: e.target.value })} />
              </Field>
            </div>
          </div>
        </Card>
        <Card
          title="Portfolio"
          actions={<Button type="button" variant="secondary" onClick={() => set({ portfolio: [...brand.portfolio, { title: "", url: "" }] })}>Add item</Button>}
        >
          {brand.portfolio.length === 0 && <p className="text-sm text-muted">Links to past work, case studies or demos.</p>}
          <div className="space-y-2">
            {brand.portfolio.map((item, i) => (
              <div key={i} className="flex flex-col gap-2 sm:flex-row">
                <input className={inputClass} placeholder="Title" value={item.title}
                  onChange={(e) => set({ portfolio: brand.portfolio.map((p, j) => (j === i ? { ...p, title: e.target.value } : p)) })} />
                <input className={inputClass} placeholder="https://…" value={item.url}
                  onChange={(e) => set({ portfolio: brand.portfolio.map((p, j) => (j === i ? { ...p, url: e.target.value } : p)) })} />
                <Button type="button" variant="ghost" onClick={() => set({ portfolio: brand.portfolio.filter((_, j) => j !== i) })}>Remove</Button>
              </div>
            ))}
          </div>
        </Card>
        {error && <Notice tone="bad">{error}</Notice>}
        <Button type="submit">{saved ? "Saved" : "Save brand"}</Button>
      </form>
      <div className="space-y-6">
        <SharePreview brand={brand} />
        <ScreenLook />
      </div>
      </div>
    </main>
  );
}

const web = (u: string) => (/^https?:\/\//i.test(u.trim()) ? u.trim() : "");

/** What a client sees at the top of a share page, updated as you type. */
function SharePreview({ brand }: { brand: Brand }) {
  const accent = brand.accent || "#4F46E5";
  const avatar = web(brand.avatar_url);
  return (
    <aside aria-label="Share page preview" className="lg:sticky lg:top-6">
      <h2 className="mb-2 text-sm font-semibold text-muted">How clients see it</h2>
      <div className="overflow-hidden rounded-xl border border-rule bg-paper shadow-sm">
        <div className="flex items-center gap-3 border-b border-rule bg-white px-4 py-3">
          {avatar ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={avatar} alt="" className="h-9 w-9 rounded-full object-cover" />
          ) : (
            <div className="flex h-9 w-9 items-center justify-center rounded-full font-semibold text-white" style={{ background: accent }}>
              {(brand.name || "?").slice(0, 1)}
            </div>
          )}
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-ink">{brand.name || "Your name"}</div>
            <div className="truncate text-xs text-muted">{brand.headline || "Your headline"}</div>
          </div>
        </div>
        <div className="space-y-3 p-4">
          {brand.rating_text && <div className="inline-block rounded-full bg-ink/5 px-2.5 py-0.5 text-xs text-ink">{brand.rating_text}</div>}
          <div className="flex aspect-video items-center justify-center rounded-lg bg-ink text-xs text-white/60">Your video</div>
          {web(brand.booking_url) && (
            <div className="rounded-lg border border-rule bg-white px-3 py-2 text-xs font-semibold" style={{ color: accent }}>Your booking calendar</div>
          )}
          {web(brand.profile_url) && (
            <div className="rounded-lg px-3 py-2 text-center text-xs font-semibold text-white" style={{ background: accent }}>View my profile</div>
          )}
          {brand.portfolio.filter((i) => web(i.url)).length > 0 && (
            <ul className="space-y-1">
              {brand.portfolio.filter((i) => web(i.url)).map((i, n) => (
                <li key={n} className="truncate rounded border border-rule bg-white px-3 py-1.5 text-xs text-ink">{i.title || i.url}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </aside>
  );
}

/** The generated browser can look exactly like the user's own Mac: desktop, Dock, menu bar, Chrome toolbar. */
function ScreenLook() {
  const [skin, setSkin] = useState<Skin | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.getSkin().then(setSkin, () => setSkin({ active: false, version: null, url: null }));
  }, []);

  async function run(fn: () => Promise<Skin>) {
    setBusy(true);
    setError(null);
    try {
      setSkin(await fn());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="screen-look">
      <h2 id="screen-look" className="mb-2 text-sm font-semibold text-muted">Your screen</h2>
      <div className="space-y-3 rounded-xl border border-rule bg-surface p-4">
        {skin?.active && skin.url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={`${API_URL}${skin.url}desktop.png?v=${skin.version}`} alt="Your screen, as videos will show it"
            className="w-full rounded-md border border-rule" />
        )}
        <p className="text-sm text-muted">
          {skin?.active
            ? "Videos use your own desktop, Dock, menu bar and Chrome toolbar. Re-export a video to apply a new screenshot."
            : "Make videos look like your Mac. Open Chrome on a New Tab page (not full screen) and take a full-screen screenshot with \u2318\u21e73."}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant={skin?.active ? "secondary" : "primary"} disabled={busy} onClick={() => ref.current?.click()}>
            {busy ? "Uploading…" : skin?.active ? "Replace screenshot" : "Upload a screenshot"}
          </Button>
          {skin?.active && <Button type="button" variant="ghost" disabled={busy} onClick={() => run(api.deleteSkin)}>Use the default look</Button>}
        </div>
        {error && <Notice tone="bad">{error}</Notice>}
        <input ref={ref} type="file" accept="image/png,image/jpeg,image/webp" className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) run(() => api.uploadSkin(file));
          }} />
      </div>
    </section>
  );
}
