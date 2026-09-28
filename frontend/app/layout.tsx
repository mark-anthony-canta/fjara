import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "Fjara · Clarity for Icelandic accounting", description: "Ask about Icelandic tax and accounting, with official sources alongside every answer." };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
