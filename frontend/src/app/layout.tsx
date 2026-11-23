import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { SidebarNav } from "@/components/SidebarNav";
import { HeaderTopBar } from "@/components/HeaderTopBar";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "ARCHON CRM",
  description: "Agentic Operating System Control Center v2.0",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex">
        <SidebarNav />
        <div className="flex min-h-full min-w-0 flex-1 flex-col">
          <HeaderTopBar />
          {children}
        </div>
      </body>
    </html>
  );
}
