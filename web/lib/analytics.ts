"use client";

import posthog from "posthog-js";

type AnalyticsConfig = {
  posthog_public_key?: string | null;
  posthog_host?: string | null;
};

let initialized = false;

export function initAnalytics(config: AnalyticsConfig) {
  const apiKey = config.posthog_public_key?.trim();
  if (!apiKey || initialized) return false;

  posthog.init(apiKey, {
    api_host: config.posthog_host?.trim() || "https://us.i.posthog.com",
    autocapture: true,
    capture_pageview: false,
    capture_pageleave: true,
    session_recording: {
      maskAllInputs: true,
      maskInputOptions: {
        password: true,
      },
    },
  });

  initialized = true;
  return true;
}

export function isAnalyticsReady() {
  return initialized;
}

export function capturePageview(url: string) {
  if (!initialized) return;
  posthog.capture("$pageview", { $current_url: url });
}

export function captureEvent(event: string, properties?: Record<string, unknown>) {
  if (!initialized) return;
  posthog.capture(event, properties);
}
