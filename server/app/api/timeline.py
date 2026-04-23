from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connections import get_pg
from app.models.tables import Event, MasterTimeline, ChapterYearMapping
from app.schemas.responses import EventOut, TimelineEventOut

router = APIRouter(prefix="/timeline", tags=["timeline"])

WORLDLINE = "canon"


@router.get("", response_model=list[TimelineEventOut])
async def get_master_timeline(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    event_type: str | None = None,
    chapter_min: int | None = None,
    chapter_max: int | None = None,
    db: AsyncSession = Depends(get_pg),
):
    q = select(MasterTimeline).order_by(MasterTimeline.chapter_start, MasterTimeline.id)

    if event_type:
        q = q.where(MasterTimeline.event_type == event_type)
    if chapter_min is not None:
        q = q.where(MasterTimeline.chapter_start >= chapter_min)
    if chapter_max is not None:
        q = q.where(MasterTimeline.chapter_start <= chapter_max)

    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    rows = result.scalars().all()
    return [TimelineEventOut(**{col: getattr(r, col) for col in TimelineEventOut.model_fields}) for r in rows]


@router.get("/count")
async def get_master_timeline_count(
    event_type: str | None = None,
    chapter_min: int | None = None,
    chapter_max: int | None = None,
    db: AsyncSession = Depends(get_pg),
):
    """返回时间线事件总数，用于分页"""
    q = select(func.count()).select_from(MasterTimeline)
    if event_type:
        q = q.where(MasterTimeline.event_type == event_type)
    if chapter_min is not None:
        q = q.where(MasterTimeline.chapter_start >= chapter_min)
    if chapter_max is not None:
        q = q.where(MasterTimeline.chapter_start <= chapter_max)
    result = await db.execute(q)
    total = result.scalar() or 0
    return {"total": total}


@router.get("/events", response_model=list[EventOut])
async def get_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    character_id: int | None = None,
    event_type: str | None = None,
    chapter_min: int | None = None,
    chapter_max: int | None = None,
    db: AsyncSession = Depends(get_pg),
):
    q = select(Event).where(
        Event.worldline_id == WORLDLINE,
        Event.is_deleted.is_(False),
    )
    if character_id is not None:
        q = q.where(Event.primary_character_id == character_id)
    if event_type:
        q = q.where(Event.event_type == event_type)
    if chapter_min is not None:
        q = q.where(Event.chapter >= chapter_min)
    if chapter_max is not None:
        q = q.where(Event.chapter <= chapter_max)

    q = q.order_by(Event.chapter, Event.id)
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    rows = result.scalars().all()
    return [EventOut(**{col: getattr(r, col) for col in EventOut.model_fields}) for r in rows]


@router.get("/chapter-mapping")
async def get_chapter_year_mapping(
    chapter_min: int = Query(1),
    chapter_max: int = Query(None),
    db: AsyncSession = Depends(get_pg),
):
    q = select(ChapterYearMapping).where(
        ChapterYearMapping.chapter_num >= chapter_min,
        ChapterYearMapping.chapter_num <= chapter_max,
    ).order_by(ChapterYearMapping.chapter_num)
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        {
            "chapter_num": r.chapter_num,
            "world_year": r.world_year,
            "year_end": r.year_end,
            "arc": r.arc,
        }
        for r in rows
    ]
