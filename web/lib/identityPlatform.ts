"use client";

import { getApp, getApps, initializeApp, type FirebaseApp } from "firebase/app";
import { Auth, GoogleAuthProvider, getAuth } from "firebase/auth";

export interface IdentityPlatformConfig {
  enabled: boolean;
  apiKey: string;
  authDomain: string;
  projectId: string;
  appId: string | null;
  messagingSenderId: string | null;
}

let configPromise: Promise<IdentityPlatformConfig> | null = null;
let authPromise: Promise<Auth> | null = null;

async function loadIdentityPlatformConfig(): Promise<IdentityPlatformConfig> {
  const response = await fetch("/api/auth/config", {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error("Failed to load Identity Platform config.");
  }
  return response.json();
}

export async function getIdentityPlatformConfig() {
  if (!configPromise) {
    configPromise = loadIdentityPlatformConfig();
  }
  return configPromise;
}

function getOrCreateFirebaseApp(config: IdentityPlatformConfig): FirebaseApp {
  if (getApps().length > 0) {
    return getApp();
  }

  return initializeApp({
    apiKey: config.apiKey,
    authDomain: config.authDomain,
    projectId: config.projectId,
    appId: config.appId || undefined,
    messagingSenderId: config.messagingSenderId || undefined,
  });
}

export async function getIdentityPlatformAuth(): Promise<Auth> {
  if (!authPromise) {
    authPromise = (async () => {
      const config = await getIdentityPlatformConfig();
      if (!config.enabled) {
        throw new Error("Identity Platform is not configured for this deployment.");
      }

      const auth = getAuth(getOrCreateFirebaseApp(config));
      auth.languageCode = "zh-CN";
      return auth;
    })();
  }

  return authPromise;
}

export function createGoogleProvider() {
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  return provider;
}
