"use client";

import { useEffect, useState } from "react";
import { Button, Card, Field, Notice, inputClass } from "@/components/ui";
import { api, ApiError, type Brand } from "@/lib/api";

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
    <main className="mx-auto w-full max-w-3xl space-y-5 px-4 py-8 sm:px-6">
      <h1 className="text-xl font-semibold text-ink">Brand settings</h1>
      <p className="text-sm text-muted">Shown on every share page. Use your own name and brand.</p>
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
              <div key={i} className="flex gap-2">
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
    </main>
  );
}
