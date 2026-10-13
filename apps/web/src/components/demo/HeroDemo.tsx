"use client";

/**
 * Home-page demo, built with the interactive-product-demo skill's beat engine,
 * activity gate and camera (see ./use-demo-*.ts).
 *
 * Brief (decided in-session, the user asked to proceed without a review round):
 *   Task    A freelancer's narration says "go to acme.dev" and the browser opens it,
 *           then "open the pricing page" and it clicks Pricing.
 *   Screen  SyncCut's script panel + the generated macOS-style browser it drives
 *   Camera  flat, whole frame (the slot is wide; the beacon directs the eye)
 *   Chrome  inside a browser frame (the browser IS the product's output)
 *   Frame   1200×700, matched by the stage's aspect-ratio
 *   Mobile  ships; carried by colour: the yellow line moves, the page changes
 */

import * as React from "react";
import "./hero-demo.css";

// Plain prefixed class names (scd-*): this build treats *.module.css as global CSS.
const styles = { stage: "scd-stage", demo: "scd-demo", camera: "scd-camera", cursor: "scd-cursor", line: "scd-line", cue: "scd-cue", page: "scd-page" } as const;
import { useDemoActive } from "./use-demo-active";
import { useDemoBeats, type DemoBeat } from "./use-demo-beats";
import { useDemoCamera } from "./use-demo-camera";
import { useTypedText } from "./use-typed-text";

const FRAME = { width: 1200, height: 700 };
const ADDRESS = "address";
const PRICING = "pricing";

const BEATS: readonly DemoBeat[] = [
  { hold: 1300, id: "establish", push: 0 },
  { hold: 1000, id: "say-open", push: 0 }, // line 2 is spoken; beacon on the address bar
  { hold: 420, id: "open", target: ADDRESS, travel: 900, push: 0 },
  { hold: 1500, id: "typed", push: 0 }, // types acme.dev, then the page loads
  { hold: 1100, id: "say-click", push: 0 }, // line 3 is spoken; beacon on Pricing
  { hold: 460, id: "click", target: PRICING, travel: 900, push: 0 },
  { hold: 2600, id: "result", push: 0 },
];
const AT = { open: 2, load: 3, click: 5 } as const;
const FIRST_ACTION = BEATS.findIndex((b) => b.target);
const LAST_ACTION = BEATS.map((b) => Boolean(b.target)).lastIndexOf(true);

const LINES = [
  { t: "0:00", text: "Hi Sarah, here's how I'd set up your reporting." },
  { t: "0:03", text: "First, let's go to acme.dev.", cue: "(open acme.dev)" },
  { t: "0:07", text: "Then open the pricing page.", cue: "(click “Pricing”)" },
];

export function HeroDemo() {
  const viewportRef = React.useRef<HTMLDivElement>(null);
  const frameRef = React.useRef<HTMLDivElement>(null);
  const [reduced, setReduced] = React.useState(false);

  React.useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduced(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  const live = useDemoActive(viewportRef);
  const { index, phase, reset } = useDemoBeats(BEATS, live && !reduced);
  React.useEffect(() => {
    if (!live) reset();
  }, [live, reset]);

  const beat = BEATS[index]!;
  const done = phase === "done" ? index : index - 1;
  const loaded = reduced || done >= AT.load;
  const pricing = reduced || done >= AT.click;
  const focused = !reduced && done >= AT.open && index <= AT.load;
  const typed = useTypedText("acme.dev", { ms: 120, running: !reduced && index === AT.load });
  const address = loaded ? (pricing ? "acme.dev/pricing" : "acme.dev") : index === AT.load ? typed : "";
  const line = reduced ? 2 : index === 0 ? 0 : index < 4 ? 1 : 2;
  const onStage = !reduced && index >= FIRST_ACTION && index <= LAST_ACTION;
  const acting = !reduced && !!beat.target && !beat.quiet;

  const camera = useDemoCamera({
    fit: "contain",
    frameHeight: FRAME.height,
    frameRef,
    frameWidth: FRAME.width,
    key: `${loaded}:${pricing}`,
    pan: false,
    push: 0,
    target: reduced ? undefined : beat.target,
    viewportRef,
    zoom: 1,
  });

  return (
    <div className={styles.stage}>
      <div
        ref={viewportRef}
        className={styles.demo}
        data-beat={beat.id}
        data-live={live ? "" : undefined}
        data-phase={phase}
        role="img"
        aria-label="A freelancer's narration says “go to acme.dev”, and the generated browser opens it, then clicks Pricing when they say “open the pricing page”."
      >
        <div ref={frameRef} className={styles.camera} style={{ transform: `translate3d(${camera.x}px, ${camera.y}px, 0) scale(${camera.scale})` }}>
          <div className="absolute inset-0 bg-[#e9ecf1]" />
          <Script line={line} cues={[reduced || index >= 1, reduced || index >= 4]} />
          <Browser address={address} focused={focused} loaded={loaded} pricing={pricing} typing={index === AT.load && !loaded} />
        </div>
        <span
          className={styles.cursor}
          data-press={acting && phase !== "travel" ? "" : undefined}
          data-show={onStage ? "" : undefined}
          style={{ transform: `translate3d(${camera.cursorX}px, ${camera.cursorY}px, 0)` }}
          aria-hidden="true"
        >
          <i />
          <svg viewBox="0 0 24 24"><path d="M5.8 2.5v17.1l4.5-4.3 2.8 6 3-1.4-2.8-5.9 5.8-.4Z" /></svg>
        </span>
      </div>
    </div>
  );
}

function Script({ line, cues }: { line: number; cues: boolean[] }) {
  return (
    <div className="absolute left-7 top-7 h-[644px] w-[350px] rounded-[12px] border border-[#dde1e7] bg-white p-6">
      <div className="text-[15px] font-bold text-[#161a23]">Narration</div>
      <div className="mt-1 text-[12px] text-[#5e6675]">Recorded once · 0:12</div>
      <div className="mt-7 space-y-6">
        {LINES.map((l, i) => {
          const cueIndex = i - 1;
          return (
            <div key={l.t} className="grid grid-cols-[38px_1fr] gap-2">
              <span className="pt-1 text-[12px] font-semibold tabular text-[#5e6675]">{l.t}</span>
              <div>
                <p className={`${styles.line} rounded-[4px] px-1.5 py-0.5 font-script text-[17px] leading-[1.7] ${i === line ? "bg-[#fff4c7] text-[#161a23]" : "text-[#8a919d]"}`}>
                  {l.text}
                </p>
                {l.cue && (
                  <span
                    className={`${styles.cue} mt-2 inline-block rounded-[3px] bg-[#ffd338] px-1.5 py-0.5 font-script text-[15px] font-bold text-[#161a23]`}
                    style={{ opacity: cues[cueIndex] ? 1 : 0, transform: cues[cueIndex] ? "none" : "translateY(4px)" }}
                  >
                    {l.cue}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="absolute inset-x-6 bottom-6 flex items-center gap-3 rounded-[8px] bg-[#f6f7f9] p-3">
        <Face size={40} />
        <div className="text-[12px] leading-snug text-[#5e6675]">Your video plays in the corner. The browser follows what you say.</div>
      </div>
    </div>
  );
}

function Browser({ address, focused, loaded, pricing, typing }: { address: string; focused: boolean; loaded: boolean; pricing: boolean; typing: boolean }) {
  return (
    <div className="absolute left-[404px] top-7 h-[644px] w-[768px] overflow-hidden rounded-[12px] bg-white shadow-[0_30px_70px_-25px_rgba(16,19,26,0.5),0_0_0_0.5px_rgba(0,0,0,0.35)]">
      <div className="relative h-[46px] bg-[#f3f3f5]">
        <div className="absolute left-4 top-1/2 flex -translate-y-1/2 gap-[7px]">
          <i className="h-3 w-3 rounded-full bg-[#ff5f57]" /><i className="h-3 w-3 rounded-full bg-[#febc2e]" /><i className="h-3 w-3 rounded-full bg-[#28c840]" />
        </div>
        <div
          data-demo-target={ADDRESS}
          /* positioned by offset, not a transform: the camera measures targets with an offsetParent walk */
          className={`absolute left-[194px] top-[8px] flex h-[30px] w-[380px] items-center rounded-[8px] px-3 text-[13px] ${
            focused ? "justify-start bg-white ring-2 ring-[#0a84ff]/40" : "justify-center bg-[#e4e4e8]"
          }`}
        >
          {address ? <span className="text-[#1d1d1f]">{address}</span> : <span className="text-[#8e8e93]">Search or enter website name</span>}
          {typing && <span className="ml-px inline-block h-4 w-[1.5px] bg-[#0a84ff]" />}
        </div>
      </div>
      <div className="flex h-[32px] items-center border-y border-[#dcdce0] bg-[#e9e9ec] px-2">
        <div className="flex h-[24px] w-[200px] items-center gap-2 rounded-[6px] bg-white px-3 text-[12px] text-[#1d1d1f] shadow-[0_0.5px_2px_rgba(0,0,0,0.12)]">
          <span className={`h-3 w-3 rounded-[3px] ${loaded ? "bg-[#4f46e5]" : "bg-[#d1d1d6]"}`} />
          {loaded ? (pricing ? "Pricing · Acme" : "Acme Analytics") : "New Tab"}
        </div>
      </div>
      <div className="relative h-[566px]">
        <div className={`${styles.page} absolute inset-0 flex flex-col items-center justify-center gap-4 bg-[#f5f5f7]`} style={{ opacity: loaded ? 0 : 1 }}>
          <div className="text-[24px] font-bold text-[#3a3a3c]">New Tab</div>
          <div className="h-10 w-[360px] rounded-[10px] bg-white shadow-[0_0_0_1px_#e3e3e8]" />
        </div>
        <div className={`${styles.page} absolute inset-0 bg-white`} style={{ opacity: loaded ? 1 : 0 }}>
          <div className="flex items-center gap-6 border-b border-[#eef0f3] px-8 py-4 text-[13px] text-[#3f4654]">
            <span className="mr-auto text-[17px] font-extrabold tracking-tight text-[#4f46e5]">acme</span>
            <span>Product</span>
            <span data-demo-target={PRICING} className={`rounded-[6px] px-2 py-1 ${pricing ? "bg-[#eef0ff] font-semibold text-[#4f46e5]" : ""}`}>Pricing</span>
            <span>Docs</span>
            <span className="rounded-[7px] bg-[#4f46e5] px-3 py-1.5 font-semibold text-white">Start free</span>
          </div>
          {pricing ? <PricingPage /> : <HomePage />}
        </div>
        <div className="absolute bottom-4 left-4"><Face size={112} rect /></div>
      </div>
    </div>
  );
}

function HomePage() {
  return (
    <div className="px-10 pt-12">
      <div className="max-w-[420px] text-[34px] font-extrabold leading-[1.1] tracking-tight text-[#111827]">Know which leads will close.</div>
      <p className="mt-3 max-w-[380px] text-[14px] text-[#4b5563]">Acme scores every lead from your CRM and tells your team who to call first.</p>
      <div className="mt-8 ml-auto grid w-[300px] grid-cols-6 items-end gap-2">
        {[38, 62, 48, 80, 66, 92].map((h, i) => <div key={i} className="rounded-t-[4px] bg-[#c7d2fe]" style={{ height: h }} />)}
      </div>
    </div>
  );
}

function PricingPage() {
  const plans = [
    { name: "Starter", price: "$19" },
    { name: "Team", price: "$49", pick: true },
    { name: "Scale", price: "$99" },
  ];
  return (
    <div className="px-10 pt-10">
      <div className="text-[30px] font-extrabold tracking-tight text-[#111827]">Simple pricing</div>
      <div className="mt-6 grid grid-cols-3 gap-4 pl-[120px]">
        {plans.map((p) => (
          <div key={p.name} className={`rounded-[10px] p-4 ${p.pick ? "bg-[#4f46e5] text-white" : "bg-[#f3f4f6] text-[#111827]"}`}>
            <div className="text-[13px] font-semibold opacity-80">{p.name}</div>
            <div className="mt-2 text-[26px] font-extrabold">{p.price}<span className="text-[12px] font-medium opacity-70">/mo</span></div>
            <div className="mt-3 space-y-1.5">{[0, 1, 2].map((k) => <div key={k} className={`h-1.5 rounded-full ${p.pick ? "bg-white/40" : "bg-[#d1d5db]"}`} />)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Stand-in for the narrator's own video: a simple illustrated face, not a real person. */
function Face({ size, rect }: { size: number; rect?: boolean }) {
  return (
    <div
      className={`overflow-hidden bg-gradient-to-b from-[#5c6bd6] to-[#2c3a8f] ${rect ? "rounded-[10px] shadow-[0_8px_20px_rgba(0,0,0,0.3)]" : "rounded-full"}`}
      style={{ width: rect ? size * 1.5 : size, height: size }}
    >
      <svg viewBox="0 0 60 40" className="h-full w-full" aria-hidden>
        <circle cx="30" cy="17" r="8" fill="#f2c9a5" />
        <path d="M14 42c2-10 8-14 16-14s14 4 16 14z" fill="#ffd338" />
        <path d="M22 15c0-6 4-9 8-9s8 3 8 9c-2-3-5-4-8-4s-6 1-8 4z" fill="#3b2a20" />
      </svg>
    </div>
  );
}
