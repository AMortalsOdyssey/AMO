from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connections import get_pg
from app.models.tables import (
    Faction,
    FactionMembership,
    ItemArtifact,
    Location,
    SpiritBeast,
    Technique,
)
from app.schemas.responses import (
    FactionBrief,
    FactionDetail,
    ItemOut,
    MembershipOut,
    SpiritBeastOut,
    TechniqueOut,
)

router = APIRouter(tags=["entities"])

WORLDLINE = "canon"


# ── Factions ────────────────────────────────────────────────

@router.get("/factions", response_model=list[FactionBrief])
async def list_factions(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = None,
    db: AsyncSession = Depends(get_pg),
):
    q = select(Faction).where(
        Faction.worldline_id == WORLDLINE,
        Faction.is_deleted.is_(False),
    )
    if search:
        q = q.where(Faction.name.ilike(f"%{search}%"))
    q = q.order_by(Faction.first_chapter.nulls_last(), Faction.id)
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    factions = result.scalars().all()

    # count members per faction
    faction_ids = [f.id for f in factions]
    counts = {}
    if faction_ids:
        cnt_q = (
            select(FactionMembership.faction_id, func.count())
            .where(
                FactionMembership.faction_id.in_(faction_ids),
                FactionMembership.worldline_id == WORLDLINE,
                FactionMembership.is_deleted.is_(False),
            )
            .group_by(FactionMembership.faction_id)
        )
        cnt_result = await db.execute(cnt_q)
        counts = dict(cnt_result.all())

    return [
        FactionBrief(
            id=f.id,
            name=f.name,
            faction_type=f.faction_type,
            power_level=f.power_level,
            first_chapter=f.first_chapter,
            member_count=counts.get(f.id, 0),
        )
        for f in factions
    ]


@router.get("/factions/{faction_id}", response_model=FactionDetail)
async def get_faction(faction_id: int, db: AsyncSession = Depends(get_pg)):
    result = await db.execute(
        select(Faction).where(Faction.id == faction_id, Faction.is_deleted.is_(False))
    )
    f = result.scalar_one_or_none()
    if not f:
        from fastapi import HTTPException
        raise HTTPException(404, "Faction not found")

    # members
    mem_q = select(FactionMembership).where(
        FactionMembership.faction_id == faction_id,
        FactionMembership.worldline_id == WORLDLINE,
        FactionMembership.is_deleted.is_(False),
    )
    mem_result = await db.execute(mem_q)
    mems = mem_result.scalars().all()

    from app.models.tables import Character
    char_ids = {m.character_id for m in mems}
    char_names = {}
    if char_ids:
        cn_result = await db.execute(
            select(Character.id, Character.name).where(Character.id.in_(char_ids))
        )
        char_names = dict(cn_result.all())

    return FactionDetail(
        id=f.id,
        name=f.name,
        faction_type=f.faction_type,
        parent_faction_id=f.parent_faction_id,
        first_chapter=f.first_chapter,
        location_id=f.location_id,
        power_level=f.power_level,
        description=f.description,
        members=[
            MembershipOut(
                id=m.id,
                faction_id=m.faction_id,
                faction_name=f.name,
                role=m.role,
                valid_from_chapter=m.valid_from_chapter,
                valid_until_chapter=m.valid_until_chapter,
            )
            for m in mems
        ],
    )


# ── Items ───────────────────────────────────────────────────

@router.get("/items", response_model=list[ItemOut])
async def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = None,
    item_type: str | None = None,
    db: AsyncSession = Depends(get_pg),
):
    q = select(ItemArtifact).where(
        ItemArtifact.worldline_id == WORLDLINE,
        ItemArtifact.is_deleted.is_(False),
    )
    if search:
        q = q.where(ItemArtifact.name.ilike(f"%{search}%"))
    if item_type:
        q = q.where(ItemArtifact.item_type == item_type)
    q = q.order_by(ItemArtifact.first_chapter.nulls_last(), ItemArtifact.id)
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return [ItemOut(**{col: getattr(i, col) for col in ItemOut.model_fields}) for i in result.scalars().all()]


# ── Techniques ──────────────────────────────────────────────

@router.get("/techniques", response_model=list[TechniqueOut])
async def list_techniques(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = None,
    db: AsyncSession = Depends(get_pg),
):
    q = select(Technique).where(
        Technique.worldline_id == WORLDLINE,
        Technique.is_deleted.is_(False),
    )
    if search:
        q = q.where(Technique.name.ilike(f"%{search}%"))
    q = q.order_by(Technique.first_chapter.nulls_last(), Technique.id)
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return [TechniqueOut(**{col: getattr(t, col) for col in TechniqueOut.model_fields}) for t in result.scalars().all()]


# ── Spirit Beasts ───────────────────────────────────────────

@router.get("/spirit-beasts", response_model=list[SpiritBeastOut])
async def list_spirit_beasts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_pg),
):
    q = select(SpiritBeast).where(
        SpiritBeast.worldline_id == WORLDLINE,
        SpiritBeast.is_deleted.is_(False),
    )
    q = q.order_by(SpiritBeast.first_chapter.nulls_last(), SpiritBeast.id)
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return [SpiritBeastOut(**{col: getattr(s, col) for col in SpiritBeastOut.model_fields}) for s in result.scalars().all()]


# ── Locations ───────────────────────────────────────────────

@router.get("/locations")
async def list_locations(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = None,
    db: AsyncSession = Depends(get_pg),
):
    q = select(Location).where(
        Location.worldline_id == WORLDLINE,
        Location.is_deleted.is_(False),
    )
    if search:
        q = q.where(Location.name.ilike(f"%{search}%"))
    q = q.order_by(Location.first_chapter.nulls_last(), Location.id)
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "location_type": r.location_type,
            "parent_location_id": r.parent_location_id,
            "first_chapter": r.first_chapter,
            "description": r.description,
        }
        for r in rows
    ]
