import type { Metadata } from "next";
import { Suspense } from "react";
import { Geist } from "next/font/google";
import "./globals.css";
import AnalyticsBootstrap from "@/components/AnalyticsBootstrap";
import { AuthProvider } from "@/components/AuthProvider";
import Nav from "@/components/Nav";
import SiteFooter from "@/components/SiteFooter";

const geist = Geist({ variable: "--font-geist", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "AMO · A Mortal's Odyssey",
  description: "东方修真叙事资料索引 · 关系图谱 · 角色对话 · 交互演绎 · 时间线",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" className={`${geist.variable} h-full antialiased dark`}>
      <body className="min-h-full flex flex-col text-foreground">
        <AuthProvider>
          <Suspense fallback={null}>
            <AnalyticsBootstrap />
          </Suspense>
          <Nav />
          <main className="relative flex-1">{children}</main>
          <SiteFooter />
        </AuthProvider>
      </body>
    </html>
  );
}
