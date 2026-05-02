import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "KnowNet",
  description: "Markdown-first AI collaboration knowledge base",
  icons: {
    icon: "/icon.png",
    apple: "/icon.png"
  }
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
