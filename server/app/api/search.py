from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connections import get_pg
from app.models.tables import Character, CharacterAlias, Faction, ItemArtifact, Location, Technique

router = APIRouter(prefix="/search", tags=["search"])

WORLDLINE = "canon"


@router.get("")
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
    types: str = Query("all", description="Comma-separated: character,faction,item,technique,location,all"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_pg),
):
    search_types = [t.strip() for t in types.split(",")]
    search_all = "all" in search_types
    results = []
    pattern = f"%{q}%"

    if search_all or "character" in search_types:
        # search by name
        char_q = select(Character).where(
            Character.worldline_id == WORLDLINE,
            Character.is_deleted.is_(False),
            Character.name.ilike(pattern),
        ).limit(limit)
        chars = (await db.execute(char_q)).scalars().all()

        # also search by alias
        alias_q = select(CharacterAlias.character_id).where(
            CharacterAlias.alias.ilike(pattern),
        ).limit(limit)
        alias_ids = [row for row in (await db.execute(alias_q)).scalars().all()]
        if alias_ids:
            extra_q = select(Character).where(
                Character.id.in_(alias_ids),
                Character.is_deleted.is_(False),
            )
            extra = (await db.execute(extra_q)).scalars().all()
            seen = {c.id for c in chars}
            chars.extend(c for c in extra if c.id not in seen)

        for c in chars[:limit]:
            results.append({
                "type": "character",
                "id": c.id,
                "name": c.name,
                "detail": f"首次出场: 第{c.first_chapter}章",
            })

    if search_all or "faction" in search_types:
        fq = select(Faction).where(
            Faction.worldline_id == WORLDLINE,
            Faction.is_deleted.is_(False),
            Faction.name.ilike(pattern),
        ).limit(limit)
        for f in (await db.execute(fq)).scalars().all():
            results.append({
                "type": "faction",
                "id": f.id,
                "name": f.name,
                "detail": f.faction_type or "",
            })

    if search_all or "item" in search_types:
        iq = select(ItemArtifact).where(
            ItemArtifact.worldline_id == WORLDLINE,
            ItemArtifact.is_deleted.is_(False),
            ItemArtifact.name.ilike(pattern),
        ).limit(limit)
        for i in (await db.execute(iq)).scalars().all():
            results.append({
                "type": "item",
                "id": i.id,
                "name": i.name,
                "detail": f"{i.item_type or ''} {i.grade or ''}".strip(),
            })

    if search_all or "technique" in search_types:
        tq = select(Technique).where(
            Technique.worldline_id == WORLDLINE,
            Technique.is_deleted.is_(False),
            Technique.name.ilike(pattern),
        ).limit(limit)
        for t in (await db.execute(tq)).scalars().all():
            results.append({
                "type": "technique",
                "id": t.id,
                "name": t.name,
                "detail": f"{t.technique_type or ''} {t.grade or ''}".strip(),
            })

    if search_all or "location" in search_types:
        lq = select(Location).where(
            Location.worldline_id == WORLDLINE,
            Location.is_deleted.is_(False),
            Location.name.ilike(pattern),
        ).limit(limit)
        for loc in (await db.execute(lq)).scalars().all():
            results.append({
                "type": "location",
                "id": loc.id,
                "name": loc.name,
                "detail": loc.location_type or "",
            })

    return {"query": q, "total": len(results), "results": results[:limit]}
