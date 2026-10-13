import type { Metadata } from "next";
import { Courier_Prime, Schibsted_Grotesk } from "next/font/google";
import { Suspense } from "react";
import { AppHeader } from "@/components/AppHeader";
import "./globals.css";

const ui = Schibsted_Grotesk({
  variable: "--font-ui",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
});

// Narration is shown as a script, so it is set the way scripts are: in Courier.
const courier = Courier_Prime({
  variable: "--font-courier",
  subsets: ["latin"],
  weight: ["400", "700"],
});

export const metadata: Metadata = {
  title: "SyncCut",
  description: "Record your narration once. SyncCut opens the sites you mention, when you mention them, and cuts one video with you in the corner.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${ui.variable} ${courier.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <Suspense fallback={null}>
          <AppHeader />
        </Suspense>
        {children}
      </body>
    </html>
  );
}
