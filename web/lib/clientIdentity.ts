const STORAGE_KEY = "amo_client_token";

function buildFallbackToken() {
  return `amo_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

export function getOrCreateClientToken() {
  if (typeof window === "undefined") {
    return null;
  }

  const existing = window.localStorage.getItem(STORAGE_KEY);
  if (existing) {
    return existing;
  }

  const token = typeof window.crypto?.randomUUID === "function"
    ? `amo_${window.crypto.randomUUID()}`
    : buildFallbackToken();

  window.localStorage.setItem(STORAGE_KEY, token);
  return token;
}
