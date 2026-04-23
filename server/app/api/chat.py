import json
import logging
from collections.abc import AsyncGenerator

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.db.connections import get_milvus, get_pg
from app.models.tables import Character, CharacterSnapshot
from app.schemas.responses import ChatRequest
from app.services.embeddings import get_embedding_vector

router = APIRouter(prefix="/chat", tags=["chat"])

WORLDLINE = "canon"
logger = logging.getLogger("amo.chat")

# 角色知识边界规则（与 lore_guard.py 保持一致）
KNOWLEDGE_BOUNDARY_RULES = """## 角色知识边界规则
1. 你只能知道"知识截止章节"之前的信息，任何此后发生的事情你都不知道
2. 你不能有上帝视角，不能剧透未来会发生的事
3. 双方共同经历的事情可以互相知道
4. 对原著未明确提及的内容，可做合理推断/猜想，但不能幻觉式乱说
5. 若被问到不知道的事情，应如实表示不知道或不清楚
"""


def _build_system_prompt(character_name: str, snapshot: CharacterSnapshot) -> str:
    persona = snapshot.persona_prompt or f"你是{character_name}。"
    traits = "、".join(_normalize_text_items(snapshot.personality_traits)) if snapshot.personality_traits else ""
    equipment_str = ""
    if snapshot.equipment:
        items = []
        for k, v in snapshot.equipment.items():
            if isinstance(v, list):
                items.extend(_normalize_text_items(v))
            elif isinstance(v, str):
                normalized = v.strip()
                if normalized:
                    items.append(normalized)
        if items:
            equipment_str = f"\n你当前拥有的法宝/物品：{'、'.join(items)}"

    techniques_str = ""
    if snapshot.techniques:
        technique_items = _normalize_text_items(snapshot.techniques)
        if technique_items:
            techniques_str = f"\n你修炼的功法/术法：{'、'.join(technique_items)}"

    return f"""你正在扮演《凡人修仙传》中的角色「{character_name}」。

## 角色设定
{persona}

## 当前境界
{snapshot.realm_stage}

{f"## 性格特征{chr(10)}{traits}" if traits else ""}
{equipment_str}
{techniques_str}

{KNOWLEDGE_BOUNDARY_RULES}

## 重要规则
1. 你只知道第 {snapshot.knowledge_cutoff} 章及之前的信息。任何此后发生的事情你都不知道。
2. 保持角色一致性，用符合角色身份和时代背景的方式说话。
3. 不要使用现代用语或破坏沉浸感的表达。
4. 如果被问到你不知道的事情（超出你的知识边界），如实回答你不知道。
5. 回答要简洁自然，像真人对话一样。不要过于正式或冗长。
6. 对于原著未明确提及的内容，你可以做合理推断，但不能凭空捏造。
"""


def _normalize_text_items(value) -> list[str]:
    items: list[str] = []

    def visit(node) -> None:
        if node is None:
            return
        if isinstance(node, str):
            text = node.strip()
            if text:
                items.append(text)
            return
        if isinstance(node, (list, tuple, set)):
            for child in node:
                visit(child)
            return
        if isinstance(node, dict):
            for child in node.values():
                visit(child)
            return
        text = str(node).strip()
        if text and text != "{}" and text != "[]":
            items.append(text)

    visit(value)
    return items


async def _retrieve_context(
    character_id: int,
    knowledge_cutoff: int,
    query: str,
    top_k: int = 5,
) -> str:
    """Retrieve relevant context from Zilliz within knowledge_cutoff."""
    milvus = get_milvus()
    if milvus is None:
        logger.warning(
            "milvus client unavailable, skipping vector retrieval",
            extra={"character_id": character_id, "knowledge_cutoff": knowledge_cutoff},
        )
        return ""

    # Search event embeddings
    try:
        results = milvus.search(
            collection_name=settings.zilliz_event_collection,
            data=[await get_embedding_vector(query, task_type="RETRIEVAL_QUERY")],
            limit=top_k,
            filter=f'worldline_id == "canon" and source_chapter <= {knowledge_cutoff}',
            output_fields=["content", "source_chapter", "event_type"],
        )
        contexts = []
        if results and results[0]:
            for hit in results[0]:
                entity = hit.get("entity", {})
                content = entity.get("content", "")
                chapter = entity.get("source_chapter", "?")
                if content:
                    contexts.append(f"[第{chapter}章] {content}")
        if contexts:
            return "\n\n".join(contexts)
    except Exception:
        logger.warning(
            "vector retrieval failed",
            extra={
                "collection": settings.zilliz_event_collection,
                "character_id": character_id,
                "knowledge_cutoff": knowledge_cutoff,
            },
            exc_info=True,
        )

    return ""


async def _stream_llm(
    system_prompt: str,
    context: str,
    user_message: str,
    history: list[dict],
) -> AsyncGenerator[str, None]:
    messages = [{"role": "system", "content": system_prompt}]

    if context:
        messages.append({
            "role": "system",
            "content": f"以下是与对话相关的背景信息（来自原著）：\n\n{context}",
        })

    for msg in history[-100:]:  # keep last 100 messages
        messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    messages.append({"role": "user", "content": user_message})

    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            f"{settings.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": messages,
                "stream": True,
                "temperature": 0.8,
                "max_tokens": 1024,
            },
        ) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


@router.post("")
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_pg)):
    logger.info(
        "chat request received",
        extra={
            "character_id": req.character_id,
            "chapter": req.chapter,
            "realm_stage": req.realm_stage,
            "history_len": len(req.history),
        },
    )
    # 1. Load character
    char_result = await db.execute(
        select(Character).where(Character.id == req.character_id, Character.is_deleted.is_(False))
    )
    character = char_result.scalar_one_or_none()
    if not character:
        raise HTTPException(404, "Character not found")

    # 2. Find appropriate snapshot
    snap_q = select(CharacterSnapshot).where(
        CharacterSnapshot.character_id == req.character_id,
        CharacterSnapshot.worldline_id == WORLDLINE,
    )
    if req.realm_stage:
        snap_q = snap_q.where(CharacterSnapshot.realm_stage == req.realm_stage)
    elif req.chapter:
        snap_q = snap_q.where(CharacterSnapshot.chapter_start <= req.chapter)
        snap_q = snap_q.order_by(CharacterSnapshot.chapter_start.desc())
    else:
        snap_q = snap_q.order_by(CharacterSnapshot.chapter_start.desc())
    snap_q = snap_q.limit(1)

    snap_result = await db.execute(snap_q)
    snapshot = snap_result.scalar_one_or_none()

    # 3. Build system prompt
    if snapshot:
        try:
            system_prompt = _build_system_prompt(character.name, snapshot)
        except Exception:
            logger.exception(
                "failed to build system prompt",
                extra={
                    "character_id": req.character_id,
                    "character_name": character.name,
                    "snapshot_id": snapshot.id,
                },
            )
            raise
        knowledge_cutoff = snapshot.knowledge_cutoff
    else:
        # Fallback for characters without snapshots
        system_prompt = f"""你正在扮演《凡人修仙传》中的角色「{character.name}」。

## 重要规则
1. 保持角色一致性，用符合角色身份和时代背景的方式说话。
2. 不要使用现代用语或破坏沉浸感的表达。
3. 回答要简洁自然，像真人对话一样。
"""
        knowledge_cutoff = 150  # default to max imported

    # 4. RAG retrieval (within knowledge_cutoff)
    context = await _retrieve_context(
        req.character_id,
        knowledge_cutoff,
        req.message,
    )

    # 5. Stream response
    async def event_generator():
        async for chunk in _stream_llm(system_prompt, context, req.message, req.history):
            yield {"data": json.dumps({"content": chunk, "done": False}, ensure_ascii=False)}
        yield {"data": json.dumps({"content": "", "done": True}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())
