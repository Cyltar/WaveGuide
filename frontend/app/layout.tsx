import type { Metadata } from "next";
import "./globals.css";


export const metadata: Metadata = {
  title: "WaveGuide",
  description:
    "AI-powered League of Legends coaching assistant",
};


export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        {children}
      </body>
    </html>
  );
}