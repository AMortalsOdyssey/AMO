from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connections import get_pg
from app.models.tables import LoreRule, StoryAnchor

router = APIRouter(prefix="/lore", tags=["lore"])

WORLDLINE = "canon"


@router.get("/rules")
async def list_lore_rules(
    category: str | None = None,
    severity: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_pg),
):
    q = select(LoreRule).where(LoreRule.worldline_id == WORLDLINE)
    if category:
        q = q.where(LoreRule.category == category)
    if severity:
        q = q.where(LoreRule.severity == severity)
    if search:
        q = q.where(
            LoreRule.rule_name.ilike(f"%{search}%")
            | LoreRule.description.ilike(f"%{search}%")
        )
    q = q.order_by(LoreRule.category, LoreRule.id)
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    rules = result.scalars().all()
    return [
        {
            "id": r.id,
            "category": r.category,
            "sub_category": r.sub_category,
            "rule_name": r.rule_name,
            "description": r.description,
            "trigger_condition": r.trigger_condition,
            "consequence_type": r.consequence_type,
            "consequence_detail": r.consequence_detail,
            "delay_type": r.delay_type,
            "severity": r.severity,
            "source_chapters": r.source_chapters,
            "source_quote": r.source_quote,
        }
        for r in rules
    ]


@router.get("/rules/stats")
async def lore_rules_stats(db: AsyncSession = Depends(get_pg)):
    q = (
        select(LoreRule.category, func.count())
        .where(LoreRule.worldline_id == WORLDLINE)
        .group_by(LoreRule.category)
    )
    result = await db.execute(q)
    cats = dict(result.all())
    total = sum(cats.values())
    return {"total": total, "categories": cats}


@router.get("/rules/{rule_id}")
async def get_lore_rule(rule_id: int, db: AsyncSession = Depends(get_pg)):
    result = await db.execute(select(LoreRule).where(LoreRule.id == rule_id))
    r = result.scalar_one_or_none()
    if not r:
        from fastapi import HTTPException
        raise HTTPException(404, "Rule not found")
    return {
        "id": r.id,
        "category": r.category,
        "sub_category": r.sub_category,
        "rule_name": r.rule_name,
        "description": r.description,
        "trigger_condition": r.trigger_condition,
        "consequence_type": r.consequence_type,
        "consequence_detail": r.consequence_detail,
        "delay_type": r.delay_type,
        "severity": r.severity,
        "source_chapters": r.source_chapters,
        "source_quote": r.source_quote,
    }


@router.get("/anchors")
async def list_story_anchors(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_pg),
):
    q = select(StoryAnchor).where(
        StoryAnchor.worldline_id == WORLDLINE
    ).order_by(StoryAnchor.chapter)
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    anchors = result.scalars().all()
    return [
        {
            "id": a.id,
            "anchor_name": a.anchor_name,
            "chapter": a.chapter,
            "world_year": a.world_year,
            "importance": a.importance,
            "description": a.description,
            "is_deletable": a.is_deletable,
        }
        for a in anchors
    ]
