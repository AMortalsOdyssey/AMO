// 前端调用本地代理，代理层再调用后端
// 代理路径: /api/* -> amo-web Pod -> amo-server Pod
const API_BASE = "/api";

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) throw new Error(`API ${path}: ${res.status}`);
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
