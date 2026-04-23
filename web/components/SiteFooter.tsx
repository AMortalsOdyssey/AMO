"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, type SiteConfig } from "@/lib/api";

const CURRENT_YEAR = new Date().getFullYear();

export default function SiteFooter() {
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
    <footer className="relative border-t border-white/8 bg-black/18 backdrop-blur-xl">
      <div className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-8 text-sm text-white/48 md:flex-row md:items-end md:justify-between">
        <div className="space-y-2">
          <div className="text-[11px] uppercase tracking-[0.28em] text-white/32">AMO Legal</div>
          <p className="max-w-2xl leading-6 text-white/42">
            AMO · A Mortal&apos;s Odyssey 为 `amo.8xd.io` 提供的世界观整理与交互体验站点。
            使用本网站即视为同意相关协议与隐私说明。
          </p>
          <p className="text-xs text-white/30">© {CURRENT_YEAR} amo.8xd.io. All rights reserved.</p>
        </div>

        <div className="flex flex-wrap gap-2 md:justify-end">
          <Link
            href="/terms"
            className="rounded-full border border-white/8 px-3 py-1.5 text-white/56 transition-colors hover:border-white/14 hover:bg-white/4 hover:text-white/90"
          >
            用户协议
          </Link>
          <Link
            href="/privacy"
            className="rounded-full border border-white/8 px-3 py-1.5 text-white/56 transition-colors hover:border-white/14 hover:bg-white/4 hover:text-white/90"
          >
            隐私协议
          </Link>
          {feedbackUrl ? (
            <a
              href={feedbackUrl}
              target="_blank"
              rel="noreferrer"
              className="rounded-full border border-white/8 px-3 py-1.5 text-white/56 transition-colors hover:border-white/14 hover:bg-white/4 hover:text-white/90"
            >
              反馈入口
            </a>
          ) : null}
        </div>
      </div>
    </footer>
  );
}
