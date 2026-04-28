"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, type SiteConfig } from "@/lib/api";
import { captureEvent } from "@/lib/analytics";
import { SITE_DOMAIN, SUPPORT_EMAIL, SUPPORT_EMAIL_HREF } from "@/lib/site";

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
          <p className="text-xs text-white/30">© {CURRENT_YEAR} {SITE_DOMAIN}. All rights reserved.</p>
          <a
            href={SUPPORT_EMAIL_HREF}
            onClick={() => {
              captureEvent("support_email_clicked", {
                source: "footer",
              });
            }}
            className="inline-flex text-xs text-white/46 transition-colors hover:text-emerald-100"
          >
            Support: {SUPPORT_EMAIL}
          </a>
        </div>

        <div className="flex flex-wrap gap-2 md:justify-end">
          <Link
            href="/contact"
            onClick={() => {
              captureEvent("contact_link_clicked", {
                href: "/contact",
                label: "联系方式",
                source: "footer",
              });
            }}
            className="rounded-full border border-white/8 px-3 py-1.5 text-white/56 transition-colors hover:border-white/14 hover:bg-white/4 hover:text-white/90"
          >
            联系方式
          </Link>
          <Link
            href="/terms"
            onClick={() => {
              captureEvent("legal_link_clicked", {
                href: "/terms",
                label: "用户协议",
                source: "footer",
              });
            }}
            className="rounded-full border border-white/8 px-3 py-1.5 text-white/56 transition-colors hover:border-white/14 hover:bg-white/4 hover:text-white/90"
          >
            用户协议
          </Link>
          <Link
            href="/privacy"
            onClick={() => {
              captureEvent("legal_link_clicked", {
                href: "/privacy",
                label: "隐私协议",
                source: "footer",
              });
            }}
            className="rounded-full border border-white/8 px-3 py-1.5 text-white/56 transition-colors hover:border-white/14 hover:bg-white/4 hover:text-white/90"
          >
            隐私协议
          </Link>
          {feedbackUrl ? (
            <a
              href={feedbackUrl}
              target="_blank"
              rel="noreferrer"
              onClick={() => {
                captureEvent("feedback_entry_clicked", {
                  source: "footer",
                });
              }}
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
