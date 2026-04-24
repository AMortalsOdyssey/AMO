// 前端调用本地代理，代理层再调用后端
// 代理路径: /api/* -> amo-web Pod -> amo-server Pod
import { getOrCreateClientToken } from "@/lib/clientIdentity";

const API_BASE = "/api";

export function buildApiHeaders(init?: HeadersInit, options?: { json?: boolean }) {
  const headers = new Headers(init);
  const wantsJson = options?.json ?? true;
  if (wantsJson && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const clientToken = getOrCreateClientToken();
  if (clientToken && !headers.has("X-AMO-Client-Token")) {
    headers.set("X-AMO-Client-Token", clientToken);
  }

  return headers;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const wantsJson = !(typeof FormData !== "undefined" && init?.body instanceof FormData);
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: buildApiHeaders(init?.headers, { json: wantsJson }),
  });
  if (!res.ok) {
    const contentType = res.headers.get("Content-Type") || "";
    let detail = res.statusText || "Request failed";
    if (contentType.includes("application/json")) {
      const payload = await res.json();
      detail = payload?.detail?.message || payload?.error || JSON.stringify(payload);
    } else {
      detail = await res.text();
    }
    throw new Error(`API ${path}: ${res.status} ${detail}`);
  }
  return res.json();
}

export interface CharacterBrief {
  id: number;
  name: string;
  gender: string | null;
  first_chapter: number;
  is_major: boolean;
  aliases: string[];
  realm_stages: string[];
}

export interface Snapshot {
  id: number;
  realm_stage: string;
  chapter_start: number;
  chapter_end: number | null;
  knowledge_cutoff: number;
  persona_prompt: string | null;
  personality_traits: string[];
  equipment: Record<string, unknown>;
  techniques: string[];
  spirit_beasts: string[];
}

export interface Relation {
  id: number;
  from_character_id: number;
  from_character_name: string | null;
  to_character_id: number;
  to_character_name: string | null;
  relation_type: string;
  valid_from_chapter: number;
  valid_until_chapter: number | null;
  attributes: Record<string, unknown>;
}

export interface Membership {
  id: number;
  faction_id: number;
  faction_name: string | null;
  role: string;
  valid_from_chapter: number;
}

export interface RealmTimeline {
  id: number;
  realm_stage: string;
  start_chapter: number;
  start_year: number | null;
  end_chapter: number | null;
  end_year: number | null;
}

export interface CharacterDetail {
  id: number;
  name: string;
  gender: string | null;
  first_chapter: number;
  first_year: number | null;
  is_major: boolean;
  aliases: { id: number; alias: string; alias_type: string }[];
  snapshots: Snapshot[];
  relations: Relation[];
  faction_memberships: Membership[];
  realm_timeline: RealmTimeline[];
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  properties: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  properties: Record<string, unknown>;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface TimelineEvent {
  id: number;
  world_year: number;
  chapter_start: number | null;
  event_type: string;
  event_name: string;
  event_detail: string | null;
  primary_character_id: number | null;
}

export interface Stats {
  characters: number;
  factions: number;
  locations: number;
  items: number;
  techniques: number;
  spirit_beasts: number;
  events: number;
  relations: number;
  chapters_imported: number;
  max_chapter: number;
}

export interface SearchResult {
  type: string;
  id: number;
  name: string;
  detail: string;
}

export interface SiteConfig {
  feedback_form_url: string | null;
  posthog_public_key?: string | null;
  posthog_host?: string | null;
}

export interface AuthUser {
  id: string;
  email: string;
  email_verified: boolean;
  display_name: string | null;
  photo_url: string | null;
  providers: string[];
}

export interface AuthSession {
  authenticated: boolean;
  user: AuthUser | null;
  session_expires_at: string | null;
}

export interface BillingSummary {
  client_token: string;
  remaining_credits: number;
  free_credits_granted: number;
  paid_credits_granted: number;
  used_credits: number;
  free_credits_remaining: number;
  paid_credits_remaining: number;
}

export interface BillingProduct {
  product_key: string;
  display_name: string;
  description: string | null;
  price_cents: number;
  currency: string;
  credits_per_unit: number;
  is_active: boolean;
  billing_type: string;
  creem_product_id_configured: boolean;
  mode: string;
}

export interface BillingCatalog {
  provider: string;
  mode: string;
  support_email: string | null;
  free_allowance_credits: number;
  pack: BillingProduct;
  summary: BillingSummary;
}

export interface BillingCheckout {
  request_id: string;
  provider: string;
  mode: string;
  status: string;
  checkout_url: string | null;
  amount_cents: number;
  currency: string;
  credits_to_grant: number;
  completed_at: string | null;
}

export interface BillingCheckoutDetail {
  checkout: BillingCheckout;
  summary: BillingSummary;
}
