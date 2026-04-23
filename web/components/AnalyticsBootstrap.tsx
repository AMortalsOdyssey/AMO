"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { apiFetch, type SiteConfig } from "@/lib/api";
import { capturePageview, initAnalytics, isAnalyticsReady } from "@/lib/analytics";

export default function AnalyticsBootstrap() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [siteConfig, setSiteConfig] = useState<SiteConfig | null>(null);

  const currentUrl = useMemo(() => {
    const search = searchParams.toString();
    return search ? `${pathname}?${search}` : pathname;
  }, [pathname, searchParams]);

  useEffect(() => {
    let cancelled = false;

    apiFetch<SiteConfig>("/site-config")
      .then((config) => {
        if (!cancelled) {
          setSiteConfig(config);
          initAnalytics(config);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSiteConfig({
            feedback_form_url: null,
            posthog_public_key: null,
            posthog_host: null,
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!siteConfig?.posthog_public_key || !isAnalyticsReady()) return;
    capturePageview(currentUrl);
  }, [currentUrl, siteConfig]);

  return null;
}
