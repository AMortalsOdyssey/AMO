"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { apiFetch, type SiteConfig } from "@/lib/api";

const NAV = [
  { href: "/", label: "首页" },
  { href: "/graph-v3", label: "关系图谱" },
  { href: "/chat", label: "角色对话" },
  { href: "/storyplay", label: "演绎" },
  { href: "/timeline", label: "时间线" },
];

export default function Nav() {
  const pathname = usePathname();
  const [feedbackUrl, setFeedbackUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    apiFetch<SiteConfig>("/site-config")
      .then((config) => {
        if (!cancelled) {
          setFeedbackUrl(config.feedback_form_url || null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setFeedbackUrl(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <nav className="sticky top-0 z-40 border-b border-white/8 bg-black/18 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 md:gap-8">
        <Link href="/" className="min-w-0">
          <div className="text-[11px] uppercase tracking-[0.26em] text-white/38">AMO</div>
          <div className="truncate text-base font-semibold tracking-[0.16em] text-white/90 md:text-lg">
            A Mortal&apos;s Odyssey
          </div>
        </Link>
        <div className="ml-auto flex flex-wrap gap-1">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={`rounded-full border px-3 py-1.5 text-sm transition-colors ${
                pathname === n.href || (n.href !== "/" && pathname.startsWith(n.href))
                  ? "border-emerald-300/26 bg-emerald-300/18 text-white"
                  : "border-transparent text-white/56 hover:border-white/8 hover:bg-white/4 hover:text-white/90"
              }`}
            >
              {n.label}
            </Link>
          ))}
          {feedbackUrl ? (
            <a
              href={feedbackUrl}
              target="_blank"
              rel="noreferrer"
              className="rounded-full border border-transparent px-3 py-1.5 text-sm text-white/56 transition-colors hover:border-white/8 hover:bg-white/4 hover:text-white/90"
            >
              反馈
            </a>
          ) : null}
        </div>
      </div>
    </nav>
  );
}
