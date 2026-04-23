from pydantic import BaseModel


# ── Characters ──────────────────────────────────────────────

class AliasOut(BaseModel):
    id: int
    alias: str
    alias_type: str
    first_chapter: int | None = None
    last_chapter: int | None = None


class SnapshotOut(BaseModel):
    id: int
    realm_stage: str
    chapter_start: int
    chapter_end: int | None = None
    year_start: int | None = None
    year_end: int | None = None
    knowledge_cutoff: int
    knowledge_cutoff_year: int | None = None
    equipment: dict = {}
    techniques: list = []
    spirit_beasts: list = []
    faction_id: int | None = None
    location_id: int | None = None
    persona_prompt: str | None = None
    personality_traits: list = []


class CharacterBrief(BaseModel):
    id: int
    name: str
    gender: str | None = None
    first_chapter: int
    is_major: bool
    aliases: list[str] = []
    realm_stages: list[str] = []


class CharacterDetail(BaseModel):
    id: int
    name: str
    gender: str | None = None
    first_chapter: int
    first_year: int | None = None
    is_major: bool
    aliases: list[AliasOut] = []
    snapshots: list[SnapshotOut] = []
    relations: list["RelationOut"] = []
    faction_memberships: list["MembershipOut"] = []
    item_ownerships: list["OwnershipOut"] = []
    realm_timeline: list["RealmTimelineOut"] = []


class RelationOut(BaseModel):
    id: int
    from_character_id: int
    from_character_name: str | None = None
    to_character_id: int
    to_character_name: str | None = None
    relation_type: str
    valid_from_chapter: int
    valid_until_chapter: int | None = None
    attributes: dict = {}


class MembershipOut(BaseModel):
    id: int
    faction_id: int
    faction_name: str | None = None
    role: str
    valid_from_chapter: int
    valid_until_chapter: int | None = None


class OwnershipOut(BaseModel):
    id: int
    item_id: int
    item_name: str | None = None
    item_type: str
    valid_from_chapter: int
    valid_until_chapter: int | None = None
    ownership_type: str


class RealmTimelineOut(BaseModel):
    id: int
    realm_stage: str
    start_chapter: int
    start_year: int | None = None
    end_chapter: int | None = None
    end_year: int | None = None
    confidence: str = "high"


# ── Factions ────────────────────────────────────────────────

class FactionBrief(BaseModel):
    id: int
    name: str
    faction_type: str | None = None
    power_level: str | None = None
    first_chapter: int | None = None
    member_count: int = 0


class FactionDetail(BaseModel):
    id: int
    name: str
    faction_type: str | None = None
    parent_faction_id: int | None = None
    first_chapter: int | None = None
    location_id: int | None = None
    power_level: str | None = None
    description: str | None = None
    members: list[MembershipOut] = []


# ── Items / Techniques / Spirit Beasts ──────────────────────

class ItemOut(BaseModel):
    id: int
    name: str
    item_type: str | None = None
    grade: str | None = None
    first_chapter: int | None = None
    description: str | None = None
    abilities: list = []


class TechniqueOut(BaseModel):
    id: int
    name: str
    technique_type: str | None = None
    grade: str | None = None
    first_chapter: int | None = None
    description: str | None = None
    effects: list = []


class SpiritBeastOut(BaseModel):
    id: int
    name: str
    species: str | None = None
    grade: str | None = None
    first_chapter: int | None = None
    description: str | None = None
    abilities: list = []


# ── Graph ───────────────────────────────────────────────────

class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    properties: dict = {}


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str
    properties: dict = {}


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# ── Timeline ────────────────────────────────────────────────

class TimelineEventOut(BaseModel):
    id: int
    world_year: int
    year_end: int | None = None
    chapter_start: int | None = None
    chapter_end: int | None = None
    event_type: str
    event_name: str
    event_detail: str | None = None
    primary_character_id: int | None = None
    affected_characters: list = []
    location_context: str | None = None
    faction_context: str | None = None


class EventOut(BaseModel):
    id: int
    event_name: str
    event_type: str
    chapter: int
    chapter_end: int | None = None
    world_year: int | None = None
    event_detail: str | None = None
    result: str | None = None
    primary_character_id: int | None = None
    participants: list = []


# ── Chat ────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    character_id: int
    chapter: int | None = None
    realm_stage: str | None = None
    message: str
    history: list[dict] = []


class ChatChunk(BaseModel):
    content: str
    done: bool = False


# ── Common ──────────────────────────────────────────────────

class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int


class StatsOut(BaseModel):
    characters: int
    factions: int
    locations: int
    items: int
    techniques: int
    spirit_beasts: int
    events: int
    relations: int
    chapters_imported: int
    max_chapter: int = 0


class SiteConfigOut(BaseModel):
    feedback_form_url: str | None = None
