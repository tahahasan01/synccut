"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

type DocumentPiP = { requestWindow: (opts: { width: number; height: number }) => Promise<Window> };

export const pipSupported = () => typeof window !== "undefined" && "documentPictureInPicture" in window;

/** An always-on-top Document Picture-in-Picture window that stays out of the screen capture. */
export function usePipWindow() {
  const [win, setWin] = useState<Window | null>(null);

  const open = useCallback(async () => {
    const dpip = (window as unknown as { documentPictureInPicture?: DocumentPiP }).documentPictureInPicture;
    if (!dpip) return null;
    const w = await dpip.requestWindow({ width: 460, height: 340 });
    for (const sheet of Array.from(document.styleSheets)) {
      try {
        const style = w.document.createElement("style");
        style.textContent = Array.from(sheet.cssRules).map((r) => r.cssText).join("\n");
        w.document.head.appendChild(style);
      } catch {
        if (sheet.href) {
          const link = w.document.createElement("link");
          link.rel = "stylesheet";
          link.href = sheet.href;
          w.document.head.appendChild(link);
        }
      }
    }
    w.document.documentElement.className = document.documentElement.className;
    w.document.title = "SyncCut teleprompter";
    w.addEventListener("pagehide", () => setWin(null), { once: true });
    setWin(w);
    return w;
  }, []);

  const close = useCallback(() => win?.close(), [win]);
  useEffect(() => () => win?.close(), [win]);

  return { win, open, close };
}

export function InPip({ win, children }: { win: Window | null; children: ReactNode }) {
  if (!win) return <>{children}</>;
  return createPortal(<div className="h-full bg-monitor text-white">{children}</div>, win.document.body);
}
