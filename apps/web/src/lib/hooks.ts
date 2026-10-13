"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Health, type Project } from "./api";

function isBusy(p: Project | null): boolean {
  if (!p) return false;
  return (
    p.jobs.some((j) => j.status === "queued" || j.status === "running") ||
    p.takes.some((t) => t.status === "processing") ||
    p.renders.some((r) => r.status === "rendering")
  );
}

/** Loads a project and polls while any job is running. */
export function useProject(id: string) {
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setProject(await api.getProject(id));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [id]);

  useEffect(() => {
    let alive = true;
    api.getProject(id).then(
      (p) => alive && setProject(p),
      (e) => alive && setError(e instanceof ApiError ? e.message : String(e)),
    );
    return () => {
      alive = false;
    };
  }, [id]);

  const busy = isBusy(project);
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(refresh, 1200);
    return () => clearInterval(timer);
  }, [busy, refresh]);

  return { project, setProject, error, refresh, busy };
}

export function useHealth() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.health().then(setHealth, (e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);
  return { health, error };
}

export type ExtMessage =
  | { source: "synccut-ext"; type: "hello"; version: string }
  | { source: "synccut-ext"; type: "event"; event: Record<string, unknown> & { epoch_ms: number } }
  | { source: "synccut-ext"; type: "command"; command: string };

/** Bridge to the SyncCut Chrome extension (via its content script on this page). */
export function useExtension(onMessage?: (msg: ExtMessage) => void) {
  const [version, setVersion] = useState<string | null>(null);
  const handler = useRef(onMessage);
  useEffect(() => {
    handler.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    const listen = (e: MessageEvent) => {
      if (e.source !== window || e.data?.source !== "synccut-ext") return;
      const msg = e.data as ExtMessage;
      if (msg.type === "hello") setVersion(msg.version);
      handler.current?.(msg);
    };
    window.addEventListener("message", listen);
    window.postMessage({ source: "synccut-app", type: "ping" }, window.location.origin);
    return () => window.removeEventListener("message", listen);
  }, []);

  const send = useCallback((type: string, data: Record<string, unknown> = {}) => {
    window.postMessage({ source: "synccut-app", type, ...data }, window.location.origin);
  }, []);

  return { connected: version !== null, version, send };
}
