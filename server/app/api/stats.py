from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connections import get_pg
from app.models.tables import (
    Character,
    CharacterRelation,
    Event,
    Faction,
    ItemArtifact,
    Location,
    SpiritBeast,
    Technique,
)
from app.schemas.responses import StatsOut

router = APIRouter(prefix="/stats", tags=["stats"])

WORLDLINE = "canon"


@router.get("", response_model=StatsOut)
async def get_stats(db: AsyncSession = Depends(get_pg)):
    async def _count(model, extra_filter=None):
        q = select(func.count()).select_from(model)
        if hasattr(model, "worldline_id"):
            q = q.where(model.worldline_id == WORLDLINE)
        if hasattr(model, "is_deleted"):
            q = q.where(model.is_deleted.is_(False))
        if extra_filter is not None:
            q = q.where(extra_filter)
        r = await db.execute(q)
        return r.scalar_one()

    # chapters imported = distinct chapters in events table
    chap_q = select(func.count(func.distinct(Event.chapter))).where(
        Event.worldline_id == WORLDLINE,
        Event.is_deleted.is_(False),
    )
    chap_result = await db.execute(chap_q)
    chapters = chap_result.scalar_one()

    # max chapter number imported
    max_chap_q = select(func.max(Event.chapter)).where(
        Event.worldline_id == WORLDLINE,
        Event.is_deleted.is_(False),
    )
    max_chap_result = await db.execute(max_chap_q)
    max_chapter = max_chap_result.scalar_one() or 0

    return StatsOut(
        characters=await _count(Character),
        factions=await _count(Faction),
        locations=await _count(Location),
        items=await _count(ItemArtifact),
        techniques=await _count(Technique),
        spirit_beasts=await _count(SpiritBeast),
        events=await _count(Event),
        relations=await _count(CharacterRelation),
        chapters_imported=chapters,
        max_chapter=max_chapter,
    )
