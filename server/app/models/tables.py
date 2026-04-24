from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    gender: Mapped[str | None] = mapped_column(String(10))
    first_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    first_year: Mapped[int | None] = mapped_column(Integer)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    is_major: Mapped[bool] = mapped_column(Boolean, default=False)
    worldline_id: Mapped[str] = mapped_column(String(36), default="canon")
    extraction_version: Mapped[int] = mapped_column(Integer, default=1)
    extraction_run: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    aliases: Mapped[list["CharacterAlias"]] = relationship(back_populates="character", lazy="selectin")
    snapshots: Mapped[list["CharacterSnapshot"]] = relationship(back_populates="character", lazy="selectin")


class CharacterAlias(Base):
    __tablename__ = "character_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), nullable=False)
    alias: Mapped[str] = mapped_column(String(100), nullable=False)
    alias_type: Mapped[str] = mapped_column(String(20), nullable=False)
    first_chapter: Mapped[int | None] = mapped_column(Integer)
    last_chapter: Mapped[int | None] = mapped_column(Integer)
    worldline_id: Mapped[str] = mapped_column(String(36), default="canon")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    character: Mapped["Character"] = relationship(back_populates="aliases")


class CharacterSnapshot(Base):
    __tablename__ = "character_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), nullable=False)
    realm_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    chapter_start: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_end: Mapped[int | None] = mapped_column(Integer)
    year_start: Mapped[int | None] = mapped_column(Integer)
    year_end: Mapped[int | None] = mapped_column(Integer)
    knowledge_cutoff: Mapped[int] = mapped_column(Integer, nullable=False)
    knowledge_cutoff_year: Mapped[int | None] = mapped_column(Integer)
    equipment: Mapped[dict] = mapped_column(JSONB, default=dict)
    techniques: Mapped[list] = mapped_column(JSONB, default=list)
    spirit_beasts: Mapped[list] = mapped_column(JSONB, default=list)
    faction_id: Mapped[int | None] = mapped_column(Integer)
    location_id: Mapped[int | None] = mapped_column(Integer)
    persona_prompt: Mapped[str | None] = mapped_column(Text)
    personality_traits: Mapped[list] = mapped_column(JSONB, default=list)
    worldline_id: Mapped[str] = mapped_column(String(36), default="canon")
    extraction_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    character: Mapped["Character"] = relationship(back_populates="snapshots")


class CharacterRealmTimeline(Base):
    __tablename__ = "character_realm_timeline"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), nullable=False)
    realm_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    start_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    start_year: Mapped[int | None] = mapped_column(Integer)
    end_chapter: Mapped[int | None] = mapped_column(Integer)
    end_year: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    worldline_id: Mapped[str] = mapped_column(String(36), default="canon")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Faction(Base):
    __tablename__ = "factions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    faction_type: Mapped[str | None] = mapped_column(String(50))
    parent_faction_id: Mapped[int | None] = mapped_column(ForeignKey("factions.id"))
    first_chapter: Mapped[int | None] = mapped_column(Integer)
    location_id: Mapped[int | None] = mapped_column(Integer)
    power_level: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(Text)
    worldline_id: Mapped[str] = mapped_column(String(36), default="canon")
    extraction_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    location_type: Mapped[str | None] = mapped_column(String(50))
    parent_location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    first_chapter: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    coordinates: Mapped[dict | None] = mapped_column(JSONB)
    worldline_id: Mapped[str] = mapped_column(String(36), default="canon")
    extraction_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class ItemArtifact(Base):
    __tablename__ = "items_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    item_type: Mapped[str | None] = mapped_column(String(50))
    grade: Mapped[str | None] = mapped_column(String(20))
    first_chapter: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    abilities: Mapped[list] = mapped_column(JSONB, default=list)
    materials: Mapped[list] = mapped_column(JSONB, default=list)
    worldline_id: Mapped[str] = mapped_column(String(36), default="canon")
    extraction_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Technique(Base):
    __tablename__ = "techniques"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    technique_type: Mapped[str | None] = mapped_column(String(50))
    grade: Mapped[str | None] = mapped_column(String(20))
    first_chapter: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[dict] = mapped_column(JSONB, default=dict)
    effects: Mapped[list] = mapped_column(JSONB, default=list)
    worldline_id: Mapped[str] = mapped_column(String(36), default="canon")
    extraction_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class SpiritBeast(Base):
    __tablename__ = "spirit_beasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    species: Mapped[str | None] = mapped_column(String(100))
    grade: Mapped[str | None] = mapped_column(String(20))
    first_chapter: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    abilities: Mapped[list] = mapped_column(JSONB, default=list)
    worldline_id: Mapped[str] = mapped_column(String(36), default="canon")
    extraction_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_name: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_end: Mapped[int | None] = mapped_column(Integer)
    world_year: Mapped[int | None] = mapped_column(Integer)
    year_end: Mapped[int | None] = mapped_column(Integer)
    event_detail: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)
    primary_character_id: Mapped[int | None] = mapped_column(ForeignKey("characters.id"))
    participants: Mapped[list] = mapped_column(JSONB, default=list)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    worldline_id: Mapped[str] = mapped_column(String(36), default="canon")
    extraction_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class CharacterRelation(Base):
    __tablename__ = "character_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), nullable=False)
    to_character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    valid_from_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_until_chapter: Mapped[int | None] = mapped_column(Integer)
    valid_from_year: Mapped[int | None] = mapped_column(Integer)
    valid_until_year: Mapped[int | None] = mapped_column(Integer)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    superseded_by: Mapped[int | None] = mapped_column(ForeignKey("character_relations.id"))
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    worldline_id: Mapped[str] = mapped_column(String(36), default="canon")
    extraction_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class FactionMembership(Base):
    __tablename__ = "faction_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), nullable=False)
    faction_id: Mapped[int] = mapped_column(ForeignKey("factions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    valid_from_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_until_chapter: Mapped[int | None] = mapped_column(Integer)
    valid_from_year: Mapped[int | None] = mapped_column(Integer)
    valid_until_year: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    worldline_id: Mapped[str] = mapped_column(String(36), default="canon")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class ItemOwnership(Base):
    __tablename__ = "item_ownerships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    valid_from_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_until_chapter: Mapped[int | None] = mapped_column(Integer)
    valid_from_year: Mapped[int | None] = mapped_column(Integer)
    valid_until_year: Mapped[int | None] = mapped_column(Integer)
    ownership_type: Mapped[str] = mapped_column(String(20), default="own")
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    worldline_id: Mapped[str] = mapped_column(String(36), default="canon")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MasterTimeline(Base):
    __tablename__ = "master_timeline"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    world_year: Mapped[int] = mapped_column(Integer, nullable=False)
    year_end: Mapped[int | None] = mapped_column(Integer)
    chapter_start: Mapped[int | None] = mapped_column(Integer)
    chapter_end: Mapped[int | None] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_name: Mapped[str] = mapped_column(String(200), nullable=False)
    event_detail: Mapped[str | None] = mapped_column(Text)
    primary_character_id: Mapped[int | None] = mapped_column(Integer)
    affected_characters: Mapped[list] = mapped_column(JSONB, default=list)
    realm_changes: Mapped[dict | None] = mapped_column(JSONB)
    location_context: Mapped[str | None] = mapped_column(String(200))
    faction_context: Mapped[str | None] = mapped_column(String(200))
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChapterYearMapping(Base):
    __tablename__ = "chapter_year_mapping"

    chapter_num: Mapped[int] = mapped_column(Integer, primary_key=True)
    world_year: Mapped[int] = mapped_column(Integer, nullable=False)
    year_end: Mapped[int | None] = mapped_column(Integer)
    arc: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceRef(Base):
    __tablename__ = "source_refs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_table: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_field: Mapped[str | None] = mapped_column(String(50))
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_chapter: Mapped[int | None] = mapped_column(Integer)
    source_char_start: Mapped[int | None] = mapped_column(Integer)
    source_char_end: Mapped[int | None] = mapped_column(Integer)
    source_quote: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    extraction_run: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoreRule(Base):
    __tablename__ = "lore_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    sub_category: Mapped[str | None] = mapped_column(String(50))
    rule_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_condition: Mapped[str | None] = mapped_column(Text)
    consequence_type: Mapped[str | None] = mapped_column(String(50))
    consequence_detail: Mapped[str | None] = mapped_column(Text)
    delay_type: Mapped[str] = mapped_column(String(20), default="immediate")
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    source_chapters: Mapped[list] = mapped_column(JSONB, default=list)
    source_quote: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    worldline_id: Mapped[str] = mapped_column(String(36), default="canon")
    extraction_run: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StoryAnchor(Base):
    __tablename__ = "story_anchors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"))
    anchor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    world_year: Mapped[int | None] = mapped_column(Integer)
    preconditions: Mapped[list] = mapped_column(JSONB, default=list)
    is_deletable: Mapped[bool] = mapped_column(Boolean, default=False)
    importance: Mapped[str] = mapped_column(String(20), default="high")
    description: Mapped[str | None] = mapped_column(Text)
    worldline_id: Mapped[str] = mapped_column(String(36), default="canon")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TimeWindow(Base):
    __tablename__ = "time_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_anchor_id: Mapped[int | None] = mapped_column(ForeignKey("story_anchors.id"))
    end_anchor_id: Mapped[int | None] = mapped_column(ForeignKey("story_anchors.id"))
    chapter_start: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_end: Mapped[int] = mapped_column(Integer, nullable=False)
    world_year_start: Mapped[int | None] = mapped_column(Integer)
    world_year_end: Mapped[int | None] = mapped_column(Integer)
    allowed_actions: Mapped[list] = mapped_column(JSONB, default=list)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    start_anchor: Mapped["StoryAnchor"] = relationship(foreign_keys=[start_anchor_id], lazy="selectin")
    end_anchor: Mapped["StoryAnchor"] = relationship(foreign_keys=[end_anchor_id], lazy="selectin")


class PlayerAction(Base):
    __tablename__ = "player_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    worldline_id: Mapped[str] = mapped_column(String(36), nullable=False)
    character_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    action_detail: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_context: Mapped[int | None] = mapped_column(Integer)
    world_year: Mapped[int | None] = mapped_column(Integer)
    time_window_id: Mapped[int | None] = mapped_column(Integer)
    lore_check_result: Mapped[dict | None] = mapped_column(JSONB)
    narrative: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorldlineConsequence(Base):
    __tablename__ = "worldline_consequences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    worldline_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action_id: Mapped[int | None] = mapped_column(ForeignKey("player_actions.id"))
    lore_rule_id: Mapped[int | None] = mapped_column(ForeignKey("lore_rules.id"))
    consequence_type: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[int] = mapped_column(Integer, default=5)
    trigger_type: Mapped[str] = mapped_column(String(20), default="immediate")
    trigger_condition: Mapped[str | None] = mapped_column(Text)  # 触发条件描述
    trigger_at_year: Mapped[int | None] = mapped_column(Integer)
    trigger_at_realm: Mapped[str | None] = mapped_column(String(50))
    trigger_on_character: Mapped[str | None] = mapped_column(String(100))  # 与某角色相遇触发
    trigger_on_keyword: Mapped[list | None] = mapped_column(JSONB, default=list)  # 关键词触发
    status: Mapped[str] = mapped_column(String(20), default="pending")
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    triggered_reason: Mapped[str | None] = mapped_column(String(200))  # 触发原因
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorldlineChapter(Base):
    __tablename__ = "worldline_chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    worldline_id: Mapped[str] = mapped_column(String(36), nullable=False)
    chapter_order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)  # 演绎摘要(100-200字)
    action_id: Mapped[int | None] = mapped_column(ForeignKey("player_actions.id"))
    canon_chapter: Mapped[int | None] = mapped_column(Integer)
    canon_contrast: Mapped[str | None] = mapped_column(Text)
    canon_divergence: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否偏离原著
    present_characters: Mapped[list] = mapped_column(JSONB, default=list)  # 在场角色
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BillingCustomer(Base):
    __tablename__ = "billing_customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_token: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    creem_customer_id: Mapped[str | None] = mapped_column(String(100), index=True)
    credit_balance: Mapped[int] = mapped_column(Integer, default=0)
    free_credits_granted: Mapped[int] = mapped_column(Integer, default=0)
    paid_credits_granted: Mapped[int] = mapped_column(Integer, default=0)
    total_used_credits: Mapped[int] = mapped_column(Integer, default=0)
    free_credit_granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class BillingProduct(Base):
    __tablename__ = "billing_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    billing_type: Mapped[str] = mapped_column(String(30), default="one_time")
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(12), nullable=False, default="USD")
    credits_per_unit: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    creem_product_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class BillingCheckout(Base):
    __tablename__ = "billing_checkouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("billing_customers.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("billing_products.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), default="creem")
    mode: Mapped[str] = mapped_column(String(30), default="local_mock")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    checkout_url: Mapped[str | None] = mapped_column(Text)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(12), nullable=False, default="USD")
    credits_to_grant: Mapped[int] = mapped_column(Integer, nullable=False)
    creem_checkout_id: Mapped[str | None] = mapped_column(String(100), index=True)
    creem_order_id: Mapped[str | None] = mapped_column(String(100), index=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class CreditLedgerEntry(Base):
    __tablename__ = "credit_ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("billing_customers.id"), nullable=False, index=True)
    checkout_id: Mapped[int | None] = mapped_column(ForeignKey("billing_checkouts.id"), index=True)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BillingWebhookEvent(Base):
    __tablename__ = "billing_webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(30), default="creem")
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="received", index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    primary_email: Mapped[str] = mapped_column(String(255), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    photo_url: Mapped[str | None] = mapped_column(String(1024))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthIdentity(Base):
    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_auth_identities_provider_uid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String(64))
    session_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserApp(Base):
    __tablename__ = "user_apps"
    __table_args__ = (
        UniqueConstraint("user_id", "app_code", name="uq_user_apps_user_app"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    app_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
