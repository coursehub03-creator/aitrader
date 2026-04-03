import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "AITrader Terminal",
  description: "Incremental Next.js trading terminal scaffold",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
