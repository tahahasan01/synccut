import { Suspense } from "react";
import ShareClient from "./ShareClient";

export default function SharePage({ params }: PageProps<"/v/[slug]">) {
  return (
    <Suspense fallback={<main className="min-h-screen bg-paper" />}>
      <ShareClient params={params} />
    </Suspense>
  );
}
