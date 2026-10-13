import { Suspense } from "react";
import ProjectClient from "./ProjectClient";

export default function ProjectPage({ params }: PageProps<"/projects/[id]">) {
  return (
    <Suspense fallback={<main className="mx-auto max-w-5xl p-6 text-sm text-muted">Loading…</main>}>
      <ProjectClient params={params} />
    </Suspense>
  );
}
