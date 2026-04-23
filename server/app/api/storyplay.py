"""
Storyplay API - 演绎系统

功能：
1. 启动演绎 - 创建世界线
2. 提交行动 - 校验、生成叙述、保存代价
3. 流式生成叙述 - SSE 实时输出
4. 检查代价触发 - 延迟代价触发机制
"""

import asyncio
import json
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connections import async_session, get_pg
from app.models.tables import (
    Character,
    CharacterSnapshot,
    PlayerAction,
    StoryAnchor,
    TimeWindow,
    WorldlineChapter,
    WorldlineConsequence,
)
from app.services.lore_guard import (
    check_consequence_triggers,
    generate_description,
    generate_narrative,
    generate_narrative_stream,
    mark_consequences_triggered,
    retrieve_related_events,
    validate_action,
)

router = APIRouter(prefix="/storyplay", tags=["storyplay"])
log = logging.getLogger(__name__)

WORLDLINE_PREFIX = "wl_"


class StartRequest(BaseModel):
    character_id: int
    time_window_id: int


class ActionRequest(BaseModel):
    worldline_id: str
    character_id: int
    action_type: str = "custom"
    action_detail: str
    chapter_context: int | None = None
    force: bool = False  # 强制继续（即使与锚点冲突）


class StreamActionRequest(BaseModel):
    worldline_id: str
    character_id: int
    action_type: str = "custom"
    action_detail: str
    chapter_context: int | None = None
    force: bool = False


# ── Helper Functions ──────────────────────────────────────────


async def _get_previous_descriptions(worldline_id: str, db: AsyncSession, limit: int = 50) -> list[str]:
    """获取最近的演绎摘要列表"""
    result = await db.execute(
        select(WorldlineChapter.description).where(
            WorldlineChapter.worldline_id == worldline_id,
            WorldlineChapter.description.isnot(None),
        ).order_by(WorldlineChapter.chapter_order.desc()).limit(limit)
    )
    descriptions = [row[0] for row in result.all() if row[0]]
    descriptions.reverse()  # 按时间顺序
    return descriptions


async def _get_last_present_characters(worldline_id: str, db: AsyncSession) -> list[str]:
    """获取上一次演绎的在场角色"""
    result = await db.execute(
        select(WorldlineChapter.present_characters).where(
            WorldlineChapter.worldline_id == worldline_id,
        ).order_by(WorldlineChapter.chapter_order.desc()).limit(1)
    )
    row = result.first()
    if row and row[0]:
        return row[0]
    return []


# ── Start Storyplay ────────────────────────────────────────────


@router.post("/start")
async def start_storyplay(req: StartRequest, db: AsyncSession = Depends(get_pg)):
    # Validate character
    char_result = await db.execute(
        select(Character).where(Character.id == req.character_id, Character.is_deleted.is_(False))
    )
    character = char_result.scalar_one_or_none()
    if not character:
        raise HTTPException(404, "Character not found")

    # Validate time window
    tw_result = await db.execute(
        select(TimeWindow).where(TimeWindow.id == req.time_window_id)
    )
    window = tw_result.scalar_one_or_none()
    if not window:
        raise HTTPException(404, "Time window not found")

    # Get snapshot at window start
    snap_result = await db.execute(
        select(CharacterSnapshot).where(
            CharacterSnapshot.character_id == req.character_id,
            CharacterSnapshot.worldline_id == "canon",
            CharacterSnapshot.chapter_start <= window.chapter_start,
        ).order_by(CharacterSnapshot.chapter_start.desc()).limit(1)
    )
    snapshot = snap_result.scalar_one_or_none()

    # Create worldline ID
    worldline_id = WORLDLINE_PREFIX + uuid.uuid4().hex[:12]

    return {
        "worldline_id": worldline_id,
        "character": {
            "id": character.id,
            "name": character.name,
            "realm_stage": snapshot.realm_stage if snapshot else "unknown",
            "knowledge_cutoff": snapshot.knowledge_cutoff if snapshot else window.chapter_start,
        },
        "time_window": {
            "id": window.id,
            "chapter_start": window.chapter_start,
            "chapter_end": window.chapter_end,
            "start_anchor": window.start_anchor.anchor_name if window.start_anchor else None,
            "end_anchor": window.end_anchor.anchor_name if window.end_anchor else None,
        },
        "chapter_context": window.chapter_start,
    }


# ── Submit Action (Non-Streaming) ─────────────────────────────


@router.post("/action")
async def submit_action(req: ActionRequest, db: AsyncSession = Depends(get_pg)):
    # Load character
    char_result = await db.execute(
        select(Character).where(Character.id == req.character_id, Character.is_deleted.is_(False))
    )
    character = char_result.scalar_one_or_none()
    if not character:
        raise HTTPException(404, "Character not found")

    # Find snapshot
    chapter = req.chapter_context or 1
    snap_result = await db.execute(
        select(CharacterSnapshot).where(
            CharacterSnapshot.character_id == req.character_id,
            CharacterSnapshot.worldline_id == "canon",
            CharacterSnapshot.chapter_start <= chapter,
        ).order_by(CharacterSnapshot.chapter_start.desc()).limit(1)
    )
    snapshot = snap_result.scalar_one_or_none()

    # Get time window end
    time_window_end = None
    if req.chapter_context:
        tw_result = await db.execute(
            select(TimeWindow).where(
                TimeWindow.chapter_start <= req.chapter_context,
                TimeWindow.chapter_end >= req.chapter_context,
            ).limit(1)
        )
        tw = tw_result.scalar_one_or_none()
        if tw:
            time_window_end = tw.chapter_end

    # 获取上下文信息
    previous_descriptions = await _get_previous_descriptions(req.worldline_id, db)
    last_present_chars = await _get_last_present_characters(req.worldline_id, db)

    # 1. 检查代价触发
    triggered_consequences = await check_consequence_triggers(
        worldline_id=req.worldline_id,
        chapter_context=chapter,
        world_year=None,  # TODO: 从时间映射获取
        character_name=character.name,
        action_detail=req.action_detail,
        present_characters=last_present_chars,
        db=db,
    )

    # 2. Lore Guard 校验
    lore_check = await validate_action(
        action_detail=req.action_detail,
        action_type=req.action_type,
        character_name=character.name,
        snapshot=snapshot,
        chapter_context=chapter,
        time_window_end_chapter=time_window_end,
        db=db,
        force=req.force,
        present_characters=last_present_chars,
    )

    # 3. 获取相关事件
    related_events = await retrieve_related_events(
        character_id=req.character_id,
        chapter_context=chapter,
        action_detail=req.action_detail,
        present_characters=lore_check.get("present_characters"),
        db=db,
    )

    # 4. Generate narrative (if allowed)
    narrative = ""
    description = ""
    if lore_check.get("verdict") in ("allow", "allow_with_consequence"):
        narrative = await generate_narrative(
            action_detail=req.action_detail,
            character_name=character.name,
            snapshot=snapshot,
            chapter_context=chapter,
            lore_check=lore_check,
            action_type=req.action_type,
            previous_descriptions=previous_descriptions,
            triggered_consequences=triggered_consequences,
            related_events=related_events,
        )
        # 生成摘要
        if narrative:
            description = await generate_description(narrative)

    # 5. Save player action
    action = PlayerAction(
        worldline_id=req.worldline_id,
        character_id=req.character_id,
        action_type=req.action_type,
        action_detail=req.action_detail,
        chapter_context=chapter,
        lore_check_result=lore_check,
        narrative=narrative,
    )
    db.add(action)
    await db.flush()

    # 6. Save consequences
    consequences_out = []
    for rule in lore_check.get("triggered_rules", []):
        consequence = WorldlineConsequence(
            worldline_id=req.worldline_id,
            action_id=action.id,
            lore_rule_id=rule.get("rule_id"),
            consequence_type=rule.get("consequence_type"),
            description=rule.get("description", ""),
            severity=rule.get("severity", 5),
            trigger_type=rule.get("delay_type", "immediate"),
            trigger_condition=rule.get("trigger_condition"),  # 新增：触发条件
            status="pending" if rule.get("delay_type") != "immediate" else "triggered",
        )
        db.add(consequence)
        consequences_out.append({
            "rule_name": rule.get("rule_name"),
            "consequence_type": rule.get("consequence_type"),
            "severity": rule.get("severity"),
            "description": rule.get("description"),
            "delay_type": rule.get("delay_type"),
            "trigger_condition": rule.get("trigger_condition"),
            "status": consequence.status,
        })

    # 7. 标记已触发的延迟代价
    if triggered_consequences:
        await mark_consequences_triggered(
            [c["id"] for c in triggered_consequences],
            db,
        )
        for tc in triggered_consequences:
            consequences_out.append({
                "rule_name": "延迟代价触发",
                "consequence_type": tc.get("consequence_type"),
                "severity": tc.get("severity"),
                "description": tc.get("description"),
                "delay_type": "triggered",
                "trigger_reason": tc.get("trigger_reason"),
                "status": "triggered",
            })

    # 8. Save chapter (if narrative generated)
    chapter_out = None
    if narrative:
        max_order_result = await db.execute(
            select(func.max(WorldlineChapter.chapter_order)).where(
                WorldlineChapter.worldline_id == req.worldline_id
            )
        )
        max_order = max_order_result.scalar() or 0

        present_characters = lore_check.get("present_characters", [])
        canon_divergence = lore_check.get("canon_divergence", False)

        wl_chapter = WorldlineChapter(
            worldline_id=req.worldline_id,
            chapter_order=max_order + 1,
            title=f"第{max_order + 1}章",
            content=narrative,
            description=description,
            action_id=action.id,
            canon_chapter=chapter,
            present_characters=present_characters,
            canon_divergence=canon_divergence,
        )
        db.add(wl_chapter)
        chapter_out = {
            "chapter_order": max_order + 1,
            "title": wl_chapter.title,
            "content": narrative,
            "description": description,
            "present_characters": present_characters,
            "canon_divergence": canon_divergence,
        }

    await db.commit()

    return {
        "action_id": action.id,
        "lore_check": {
            "verdict": lore_check.get("verdict"),
            "explanation": lore_check.get("explanation"),
            "alternative": lore_check.get("alternative"),
            "anchor_conflict": lore_check.get("anchor_conflict", False),
            "present_characters": lore_check.get("present_characters", []),
        },
        "consequences": consequences_out,
        "chapter": chapter_out,
        "triggered_consequences_count": len(triggered_consequences),
    }


# ── Submit Action (Streaming) ─────────────────────────────────


@router.post("/action/stream")
async def submit_action_stream(req: StreamActionRequest, db: AsyncSession = Depends(get_pg)):
    """流式生成演绎叙述"""
    log = logging.getLogger("storyplay.stream")

    # Load character
    char_result = await db.execute(
        select(Character).where(Character.id == req.character_id, Character.is_deleted.is_(False))
    )
    character = char_result.scalar_one_or_none()
    if not character:
        raise HTTPException(404, "Character not found")

    # Find snapshot
    chapter = req.chapter_context or 1
    snap_result = await db.execute(
        select(CharacterSnapshot).where(
            CharacterSnapshot.character_id == req.character_id,
            CharacterSnapshot.worldline_id == "canon",
            CharacterSnapshot.chapter_start <= chapter,
        ).order_by(CharacterSnapshot.chapter_start.desc()).limit(1)
    )
    snapshot = snap_result.scalar_one_or_none()

    # Get time window end
    time_window_end = None
    try:
        tw_result = await db.execute(
            select(TimeWindow).where(
                TimeWindow.chapter_start <= chapter,
                TimeWindow.chapter_end >= chapter,
            ).limit(1)
        )
        tw = tw_result.scalar_one_or_none()
        if tw:
            time_window_end = tw.chapter_end
    except Exception as e:
        log.error(f"TimeWindow query failed: {e}", exc_info=True)
        await db.rollback()

    # 获取上下文
    try:
        previous_descriptions = await _get_previous_descriptions(req.worldline_id, db)
    except Exception as e:
        log.error(f"_get_previous_descriptions failed: {e}", exc_info=True)
        await db.rollback()
        previous_descriptions = []
    try:
        last_present_chars = await _get_last_present_characters(req.worldline_id, db)
    except Exception as e:
        log.error(f"_get_last_present_characters failed: {e}", exc_info=True)
        await db.rollback()
        last_present_chars = []

    # 1. 检查代价触发
    try:
        triggered_consequences = await check_consequence_triggers(
            worldline_id=req.worldline_id,
            chapter_context=chapter,
            world_year=None,
            character_name=character.name,
            action_detail=req.action_detail,
            present_characters=last_present_chars,
            db=db,
        )
    except Exception as e:
        log.error(f"check_consequence_triggers failed: {e}", exc_info=True)
        await db.rollback()
        triggered_consequences = []

    # 2. Lore Guard 校验
    try:
        lore_check = await validate_action(
            action_detail=req.action_detail,
            action_type=req.action_type,
            character_name=character.name,
            snapshot=snapshot,
            chapter_context=chapter,
            time_window_end_chapter=time_window_end,
            db=db,
            force=req.force,
            present_characters=last_present_chars,
        )
    except Exception as e:
        log.error(f"validate_action failed: {e}", exc_info=True)
        await db.rollback()
        lore_check = {"verdict": "allow", "explanation": "Lore Guard 暂时不可用，允许通过", "present_characters": last_present_chars or []}

    # 3. 获取相关事件
    try:
        related_events = await retrieve_related_events(
            character_id=req.character_id,
            chapter_context=chapter,
            action_detail=req.action_detail,
            present_characters=lore_check.get("present_characters"),
            db=db,
        )
    except Exception as e:
        log.error(f"retrieve_related_events failed: {e}", exc_info=True)
        await db.rollback()
        related_events = []

    # 在 generator 外提前提取 ORM 对象的属性，避免 lazy load 在 streaming 中触发
    character_name = character.name
    # 创建一个简单的 snapshot 副本（避免 lazy load）
    snapshot_copy = None
    if snapshot:
        from types import SimpleNamespace
        snapshot_copy = SimpleNamespace(
            realm_stage=snapshot.realm_stage,
            knowledge_cutoff=snapshot.knowledge_cutoff,
            persona_prompt=snapshot.persona_prompt,
            personality_traits=list(snapshot.personality_traits) if snapshot.personality_traits else [],
            equipment=dict(snapshot.equipment) if snapshot.equipment else {},
            techniques=list(snapshot.techniques) if snapshot.techniques else [],
            spirit_beasts=list(snapshot.spirit_beasts) if snapshot.spirit_beasts else [],
        )

    def emit_event(event_type: str, **payload: object) -> dict[str, str]:
        return {"data": json.dumps({"type": event_type, **payload}, ensure_ascii=False)}

    def log_background_failure(task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except Exception as exc:
            log.error(
                "storyplay background task failed for worldline=%s character_id=%s: %s",
                req.worldline_id,
                req.character_id,
                exc,
                exc_info=True,
            )

    async def run_storyplay_generation(stream_queue: asyncio.Queue[dict[str, str] | None]) -> None:
        # 流式生成叙述
        narrative_chunks = []
        try:
            async for chunk in generate_narrative_stream(
                action_detail=req.action_detail,
                character_name=character_name,
                snapshot=snapshot_copy,
                chapter_context=chapter,
                lore_check=lore_check,
                action_type=req.action_type,
                previous_descriptions=previous_descriptions,
                triggered_consequences=triggered_consequences,
                related_events=related_events,
            ):
                narrative_chunks.append(chunk)
                stream_queue.put_nowait(emit_event("narrative", content=chunk))

            full_narrative = "".join(narrative_chunks)
        except Exception as e:
            log.error(f"generate_narrative_stream failed: {e}", exc_info=True)
            try:
                full_narrative = await generate_narrative(
                    action_detail=req.action_detail,
                    character_name=character_name,
                    snapshot=snapshot_copy,
                    chapter_context=chapter,
                    lore_check=lore_check,
                    action_type=req.action_type,
                    previous_descriptions=previous_descriptions,
                    triggered_consequences=triggered_consequences,
                    related_events=related_events,
                )
                if not narrative_chunks and full_narrative:
                    stream_queue.put_nowait(emit_event("narrative", content=full_narrative, recovered=True))
            except Exception as fallback_error:
                log.error(f"generate_narrative fallback failed: {fallback_error}", exc_info=True)
                stream_queue.put_nowait(emit_event("error", message=f"叙述生成失败: {fallback_error}"))
                stream_queue.put_nowait(emit_event("done"))
                stream_queue.put_nowait(None)
                return

        # 生成摘要
        try:
            description = await generate_description(full_narrative)
        except Exception as e:
            log.error(f"generate_description failed: {e}", exc_info=True)
            description = full_narrative[:200] if full_narrative else ""

        # 保存到数据库（使用独立 session，避免 request scope 结束后 session 失效）
        try:
            async with async_session() as save_db:
                action = PlayerAction(
                    worldline_id=req.worldline_id,
                    character_id=req.character_id,
                    action_type=req.action_type,
                    action_detail=req.action_detail,
                    chapter_context=chapter,
                    lore_check_result=lore_check,
                    narrative=full_narrative,
                )
                save_db.add(action)
                await save_db.flush()

                # Save consequences
                consequences_out = []
                for rule in lore_check.get("triggered_rules", []):
                    consequence = WorldlineConsequence(
                        worldline_id=req.worldline_id,
                        action_id=action.id,
                        lore_rule_id=rule.get("rule_id"),
                        consequence_type=rule.get("consequence_type"),
                        description=rule.get("description", ""),
                        severity=rule.get("severity", 5),
                        trigger_type=rule.get("delay_type", "immediate"),
                        trigger_condition=rule.get("trigger_condition"),
                        status="pending" if rule.get("delay_type") != "immediate" else "triggered",
                    )
                    save_db.add(consequence)
                    consequences_out.append({
                        "rule_name": rule.get("rule_name"),
                        "consequence_type": rule.get("consequence_type"),
                        "severity": rule.get("severity"),
                        "description": rule.get("description"),
                        "status": consequence.status,
                    })

                # 标记已触发的延迟代价
                if triggered_consequences:
                    await mark_consequences_triggered([c["id"] for c in triggered_consequences], save_db)

                # Save chapter
                max_order_result = await save_db.execute(
                    select(func.max(WorldlineChapter.chapter_order)).where(
                        WorldlineChapter.worldline_id == req.worldline_id
                    )
                )
                max_order = max_order_result.scalar() or 0

                present_characters = lore_check.get("present_characters", [])
                canon_divergence = lore_check.get("canon_divergence", False)

                wl_chapter = WorldlineChapter(
                    worldline_id=req.worldline_id,
                    chapter_order=max_order + 1,
                    title=f"第{max_order + 1}章",
                    content=full_narrative,
                    description=description,
                    action_id=action.id,
                    canon_chapter=chapter,
                    present_characters=present_characters,
                    canon_divergence=canon_divergence,
                )
                save_db.add(wl_chapter)
                await save_db.commit()

                # 发送完成信息
                stream_queue.put_nowait(
                    emit_event(
                        "chapter",
                        data={
                            "chapter_order": max_order + 1,
                            "title": wl_chapter.title,
                            "description": description,
                            "content": full_narrative,
                            "present_characters": present_characters,
                            "canon_divergence": canon_divergence,
                        },
                    )
                )
                stream_queue.put_nowait(emit_event("consequences", data=consequences_out))
        except Exception as e:
            log.error(f"DB save failed: {e}", exc_info=True)
            stream_queue.put_nowait(emit_event("error", message=f"保存失败: {e}"))

        stream_queue.put_nowait(emit_event("done"))
        stream_queue.put_nowait(None)

    async def event_generator():
        # 发送初始信息
        yield emit_event("lore_check", data=lore_check)

        if lore_check.get("verdict") not in ("allow", "allow_with_consequence"):
            yield emit_event("done", verdict=lore_check.get("verdict"))
            return

        stream_queue: asyncio.Queue[dict[str, str] | None] = asyncio.Queue()
        background_task = asyncio.create_task(run_storyplay_generation(stream_queue))
        background_task.add_done_callback(log_background_failure)

        try:
            while True:
                event = await stream_queue.get()
                if event is None:
                    break
                yield event
        except asyncio.CancelledError:
            log.warning(
                "storyplay SSE client disconnected while background generation continues: worldline=%s character_id=%s chapter=%s",
                req.worldline_id,
                req.character_id,
                chapter,
            )
            raise

    return EventSourceResponse(
        event_generator(),
        ping=3,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Get Time Windows ───────────────────────────────────────────


@router.get("/time-windows")
async def list_time_windows(db: AsyncSession = Depends(get_pg)):
    result = await db.execute(
        select(TimeWindow).order_by(TimeWindow.chapter_start)
    )
    windows = result.scalars().all()
    return [
        {
            "id": w.id,
            "chapter_start": w.chapter_start,
            "chapter_end": w.chapter_end,
            "start_anchor": w.start_anchor.anchor_name if w.start_anchor else None,
            "end_anchor": w.end_anchor.anchor_name if w.end_anchor else None,
            "description": w.description,
        }
        for w in windows
    ]


# ── Get Worldline Data ─────────────────────────────────────────


@router.get("/worldline/{worldline_id}")
async def get_worldline(worldline_id: str, db: AsyncSession = Depends(get_pg)):
    # Chapters
    chapters_result = await db.execute(
        select(WorldlineChapter).where(
            WorldlineChapter.worldline_id == worldline_id
        ).order_by(WorldlineChapter.chapter_order)
    )
    chapters = chapters_result.scalars().all()

    # Consequences
    cons_result = await db.execute(
        select(WorldlineConsequence).where(
            WorldlineConsequence.worldline_id == worldline_id
        ).order_by(WorldlineConsequence.created_at)
    )
    consequences = cons_result.scalars().all()

    # Actions
    actions_result = await db.execute(
        select(PlayerAction).where(
            PlayerAction.worldline_id == worldline_id
        ).order_by(PlayerAction.created_at)
    )
    actions = actions_result.scalars().all()

    # 获取最近50条演绎摘要
    descriptions = [c.description for c in chapters if c.description][-50:]

    return {
        "worldline_id": worldline_id,
        "chapters": [
            {
                "chapter_order": c.chapter_order,
                "title": c.title,
                "content": c.content,
                "description": c.description,
                "canon_chapter": c.canon_chapter,
                "present_characters": c.present_characters if hasattr(c, 'present_characters') else [],
                "canon_divergence": c.canon_divergence if hasattr(c, 'canon_divergence') else False,
            }
            for c in chapters
        ],
        "consequences": [
            {
                "id": c.id,
                "consequence_type": c.consequence_type,
                "description": c.description,
                "severity": c.severity,
                "trigger_type": c.trigger_type,
                "trigger_condition": c.trigger_condition if hasattr(c, 'trigger_condition') else None,
                "status": c.status,
                "triggered_at": c.triggered_at.isoformat() if c.triggered_at else None,
            }
            for c in consequences
        ],
        "action_count": len(actions),
        "chapter_count": len(chapters),
        "recent_descriptions": descriptions,  # 供前端做上下文展示
    }


# ── Get Consequences ───────────────────────────────────────────


@router.get("/worldline/{worldline_id}/consequences")
async def get_consequences(
    worldline_id: str,
    status: str | None = Query(None, description="Filter by status: pending/triggered"),
    db: AsyncSession = Depends(get_pg),
):
    """获取世界线的代价列表"""
    q = select(WorldlineConsequence).where(
        WorldlineConsequence.worldline_id == worldline_id
    )
    if status:
        q = q.where(WorldlineConsequence.status == status)
    q = q.order_by(WorldlineConsequence.created_at.desc())

    result = await db.execute(q)
    consequences = result.scalars().all()

    return [
        {
            "id": c.id,
            "consequence_type": c.consequence_type,
            "description": c.description,
            "severity": c.severity,
            "trigger_type": c.trigger_type,
            "trigger_condition": c.trigger_condition if hasattr(c, 'trigger_condition') else None,
            "status": c.status,
            "triggered_at": c.triggered_at.isoformat() if c.triggered_at else None,
            "triggered_reason": c.triggered_reason if hasattr(c, 'triggered_reason') else None,
        }
        for c in consequences
    ]
