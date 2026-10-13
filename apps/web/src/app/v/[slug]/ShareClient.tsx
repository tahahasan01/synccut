"use client";

import { use, useEffect, useState } from "react";
import { api, API_URL, type Brand } from "@/lib/api";

type ShareData = { title: string; message: string; cta_label: string; video_path: string; brand: Brand };

export default function ShareClient({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const [data, setData] = useState<ShareData | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    api.getShare(slug).then(setData, () => setMissing(true));
  }, [slug]);

  if (missing) return <main className="flex min-h-screen items-center justify-center text-muted">This video isn&apos;t available.</main>;
  if (!data) return <main className="min-h-screen bg-paper" />;

  // Only http(s) links reach href/src: a javascript: URL here would run on this page.
  const web = (u: string | undefined) => (u && /^https?:\/\//i.test(u.trim()) ? u.trim() : "");
  const brand = {
    ...data.brand,
    avatar_url: web(data.brand.avatar_url),
    booking_url: web(data.brand.booking_url),
    profile_url: web(data.brand.profile_url),
    portfolio: data.brand.portfolio.map((i) => ({ ...i, url: web(i.url) })).filter((i) => i.url),
  };
  const accent = brand.accent || "#4F46E5";

  return (
    <main className="min-h-screen bg-paper">
      <header className="border-b border-rule bg-white">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-4 sm:px-6">
          {brand.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={brand.avatar_url} alt="" className="h-11 w-11 rounded-full object-cover" />
          ) : (
            <div className="flex h-11 w-11 items-center justify-center rounded-full text-lg font-semibold text-white" style={{ background: accent }}>
              {(brand.name || "?").slice(0, 1)}
            </div>
          )}
          <div className="min-w-0">
            <div className="font-semibold text-ink">{brand.name}</div>
            {brand.headline && <div className="truncate text-sm text-muted">{brand.headline}</div>}
          </div>
          {brand.rating_text && (
            <div className="ml-auto hidden rounded-full bg-ink/5 px-3 py-1 text-sm text-ink sm:block">{brand.rating_text}</div>
          )}
        </div>
      </header>

      <div className="mx-auto grid max-w-5xl gap-8 px-4 py-8 sm:px-6 lg:grid-cols-[1fr_340px]">
        <section className="space-y-5">
          <h1 className="text-2xl font-semibold text-ink">{data.title}</h1>
          <video src={`${API_URL}/media/${data.video_path}`} controls playsInline className="w-full rounded-xl bg-black shadow-lg" />
          {data.message && <p className="whitespace-pre-line text-ink">{data.message}</p>}
          {brand.portfolio.length > 0 && (
            <div>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">Recent work</h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {brand.portfolio.map((item) => (
                  <a key={item.url} href={item.url} target="_blank" rel="noopener noreferrer"
                    className="rounded-lg border border-rule bg-white p-4 text-sm font-medium text-ink hover:border-rule-strong hover:shadow-sm">
                    {item.title || item.url}
                  </a>
                ))}
              </div>
            </div>
          )}
        </section>

        <aside className="space-y-4">
          {brand.booking_url ? (
            <div className="overflow-hidden rounded-xl border border-rule bg-white">
              <div className="px-4 py-3 text-sm font-semibold" style={{ color: accent }}>{data.cta_label}</div>
              <iframe src={brand.booking_url} title="Booking calendar" className="h-[620px] w-full border-0"
                sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox" referrerPolicy="no-referrer" />
            </div>
          ) : null}
          {brand.profile_url && (
            <a href={brand.profile_url} target="_blank" rel="noopener noreferrer"
              className="block rounded-lg px-4 py-3 text-center text-sm font-semibold text-white" style={{ background: accent }}>
              View my profile
            </a>
          )}
        </aside>
      </div>
    </main>
  );
}
