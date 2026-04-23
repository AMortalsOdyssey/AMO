"""
Lore Guard Service - 世界观守护者

功能:
1. validate_action - 校验玩家行为是否符合世界观规则
2. generate_narrative - 生成演绎叙述(约1000字，含对话)
3. generate_description - 生成演绎摘要(100-200字)
4. check_consequence_triggers - 检查代价触发条件
"""

import json
import re
import logging
from collections.abc import AsyncGenerator

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.tables import (
    Character,
    CharacterSnapshot,
    Event,
    LoreRule,
    StoryAnchor,
    WorldlineConsequence,
)

log = logging.getLogger(__name__)

# 快捷按钮类型到叙事偏置的映射(soft hint)
ACTION_TYPE_HINTS = {
    "cultivate": "本次叙事可适当偏向修炼主题，包括打坐运功、参悟功法、炼化丹药等；但若玩家输入明显是其他事情则以玩家输入为准",
    "explore": "本次叙事可适当偏向探索冒险主题，包括寻找机缘、勘察地形、发现宝物等；但若玩家输入明显是其他事情则以玩家输入为准",
    "combat": "本次叙事可适当偏向战斗主题，包括施法斗法、刀剑相交、生死搏杀等；但若玩家输入明显是其他事情则以玩家输入为准",
    "social": "本次叙事可适当偏向社交互动主题，包括结交朋友、拜见长辈、门派交流等；但若玩家输入明显是其他事情则以玩家输入为准",
    "trade": "本次叙事可适当偏向交易主题，包括灵石交易、物品交换、坊市买卖等；但若玩家输入明显是其他事情则以玩家输入为准",
    "custom": "",
}

# 角色互动行为约束规则
CHARACTER_INTERACTION_RULES = """## 角色互动规则
1. 在场角色应有合理反应，不能作为"透明人"存在
2. 对话时注意身份尊卑、辈分关系（例：晚辈对长辈需有敬称）
3. 战斗场景中角色行为需符合其性格特征
4. 社交场景中注意修仙世界的礼节规范
5. 角色之间的熟悉程度应影响交流方式
"""

# 角色知识边界规则
KNOWLEDGE_BOUNDARY_RULES = """## 角色知识边界规则
1. 角色只能知道其"知识截止章节"之前的信息
2. 角色不能有上帝视角，不能剧透未来会发生的事
3. 双方共同经历的事情可以互相知道
4. 对原著未明确提及的内容，可做合理推断/猜想，但不能幻觉式乱说
5. 若被问到不知道的事情，应如实表示不知道
"""


def _format_snapshot_abilities(snapshot: CharacterSnapshot | None) -> str:
    """
    格式化角色当前时间点的功法/装备/灵兽信息，用于 prompt 约束。
    这是防止时间线错误的关键 —— 明确告诉 LLM 当前时期角色拥有什么。
    """
    if not snapshot:
        return ""

    parts = []

    # 功法
    techniques = snapshot.techniques or []
    if techniques:
        tech_list = ", ".join(techniques[:15])  # 最多显示15个
        parts.append(f"已掌握功法：{tech_list}")
    else:
        parts.append("已掌握功法：无记录（按当前境界推断基础功法）")

    # 装备
    equipment = snapshot.equipment or {}
    if equipment:
        equip_items = []
        for k, v in list(equipment.items())[:10]:
            if isinstance(v, str):
                equip_items.append(f"{k}({v})")
            else:
                equip_items.append(k)
        parts.append(f"装备法宝：{', '.join(equip_items)}")

    # 灵兽
    spirit_beasts = snapshot.spirit_beasts or []
    if spirit_beasts:
        parts.append(f"灵兽：{', '.join(spirit_beasts[:5])}")

    return "\n".join(parts)


async def validate_action(
    action_detail: str,
    action_type: str,
    character_name: str,
    snapshot: CharacterSnapshot | None,
    chapter_context: int,
    time_window_end_chapter: int | None,
    db: AsyncSession,
    force: bool = False,
    present_characters: list[str] | None = None,
) -> dict:
    """
    Lore Guard: validate a player action against rules + anchors.
    Returns: {verdict, triggered_rules, narrative_hint, consequences, present_characters}

    新增参数:
    - force: 强制继续（即使与锚点冲突）
    - present_characters: 当前在场角色列表
    """
    # 1. Fetch relevant lore rules
    rules_result = await db.execute(
        select(LoreRule).where(LoreRule.worldline_id == "canon").limit(80)
    )
    rules = rules_result.scalars().all()
    rules_text = "\n".join(
        f"[{r.id}] [{r.category}/{r.severity}] {r.rule_name}: {r.description}"
        f" | 触发: {r.trigger_condition or '无'}"
        f" | 后果: {r.consequence_type or '无'} ({r.delay_type})"
        for r in rules
    )

    # 2. Fetch future anchors
    anchors_result = await db.execute(
        select(StoryAnchor).where(
            StoryAnchor.worldline_id == "canon",
            StoryAnchor.chapter > chapter_context,
        ).order_by(StoryAnchor.chapter).limit(10)
    )
    anchors = anchors_result.scalars().all()
    anchors_text = "\n".join(
        f"[第{a.chapter}章] {a.anchor_name}: {a.description}"
        for a in anchors
    )

    realm = snapshot.realm_stage if snapshot else "未知"
    persona = (snapshot.persona_prompt or "")[:200] if snapshot else ""

    # 角色当前时期的功法/装备/灵兽（时间线约束）
    abilities_text = _format_snapshot_abilities(snapshot)

    # 快捷按钮 soft hint
    action_hint = ACTION_TYPE_HINTS.get(action_type, "")
    hint_text = f"\n## 叙事偏置提示（软约束）\n{action_hint}" if action_hint else ""

    # 在场角色上下文
    present_text = ""
    if present_characters:
        present_text = f"\n## 当前在场角色\n{', '.join(present_characters)}"

    # 3. LLM validation
    prompt = f"""你是《凡人修仙传》世界观守护者（Lore Guard）。你的职责是评估玩家行为是否合理。

## 当前状态
- 角色: {character_name}
- 境界: {realm}
- 当前章节: 第{chapter_context}章
{f"- 时间窗口截止: 第{time_window_end_chapter}章" if time_window_end_chapter else ""}
{f"- 角色描述: {persona}" if persona else ""}
{f"- {abilities_text}" if abilities_text else ""}{present_text}

## 玩家行为
类型: {action_type}
描述: {action_detail}
{hint_text}

## 世界观规则库（部分）
{rules_text}

## 未来关键锚点（不可破坏，除非玩家明确要求强制偏离原著）
{anchors_text}

{CHARACTER_INTERACTION_RULES}

## 判断要求
1. 判断该行为是否合理
2. 如果触发规则，列出被触发的规则ID和代价
3. 如果与锚点冲突，建议替代方案
4. 分析该场景中应该有哪些角色在场
5. **功法检查**：如果行为涉及使用功法，检查是否在"已掌握功法"列表中

返回 JSON：
{{
  "verdict": "allow" | "allow_with_consequence" | "suggest_alternative",
  "explanation": "判断理由（50字以内）",
  "triggered_rules": [
    {{
      "rule_id": 规则ID,
      "rule_name": "规则名",
      "consequence_type": "代价类型",
      "severity": 1-10,
      "description": "具体代价描述",
      "delay_type": "immediate|years_later|realm_trigger",
      "trigger_condition": "触发条件描述，例如：下一次使用灵力时、X年后、与某人再次相遇时"
    }}
  ],
  "narrative_hint": "叙述建议（30字以内，如何在故事中体现这个行为）",
  "alternative": "替代方案建议（仅当verdict=suggest_alternative时）",
  "present_characters": ["角色1", "角色2"],
  "anchor_conflict": true/false
}}

只返回 JSON，不要其他内容。"""

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2048,
                "temperature": 0.2,
            },
        )

    if resp.status_code != 200:
        log.warning(f"Lore Guard LLM error: {resp.status_code}")
        return {
            "verdict": "allow",
            "explanation": "Lore Guard 暂不可用，默认放行",
            "triggered_rules": [],
            "narrative_hint": "",
            "present_characters": present_characters or [],
        }

    content = resp.json()["choices"][0]["message"]["content"]

    # Parse JSON from response
    match = re.search(r"\{[\s\S]*\}", content)
    if match:
        try:
            result = json.loads(match.group())
            # 如果强制继续且有锚点冲突，改为 allow_with_consequence
            if force and result.get("verdict") == "suggest_alternative":
                result["verdict"] = "allow_with_consequence"
                result["canon_divergence"] = True
                result["explanation"] = f"[强制偏离原著] {result.get('explanation', '')}"
            return result
        except json.JSONDecodeError:
            pass

    return {
        "verdict": "allow",
        "explanation": "解析失败，默认放行",
        "triggered_rules": [],
        "narrative_hint": "",
        "present_characters": present_characters or [],
    }


async def generate_narrative(
    action_detail: str,
    character_name: str,
    snapshot: CharacterSnapshot | None,
    chapter_context: int,
    lore_check: dict,
    action_type: str = "custom",
    previous_descriptions: list[str] | None = None,
    triggered_consequences: list[dict] | None = None,
    related_events: list[dict] | None = None,
) -> str:
    """
    Generate narrative text for the player's action.

    新增参数:
    - action_type: 快捷按钮类型(soft hint)
    - previous_descriptions: 最近50条演绎摘要
    - triggered_consequences: 本次触发的代价列表
    - related_events: 相关人物/事件检索结果
    """
    realm = snapshot.realm_stage if snapshot else "未知"
    knowledge_cutoff = snapshot.knowledge_cutoff if snapshot else chapter_context

    # 代价文本
    consequences_text = ""
    if lore_check.get("triggered_rules"):
        consequences_text = "\n".join(
            f"- {r['rule_name']}: {r['description']}"
            for r in lore_check["triggered_rules"]
        )

    # 触发的延迟代价
    triggered_cons_text = ""
    if triggered_consequences:
        triggered_cons_text = "## 本次触发的延迟代价（必须在叙述中体现！）\n" + "\n".join(
            f"- {c.get('rule_name', '未知')}: {c.get('description', '')}"
            for c in triggered_consequences
        )

    # 在场角色
    present_characters = lore_check.get("present_characters", [])
    present_text = f"当前在场角色：{', '.join(present_characters)}" if present_characters else ""

    # 近期演绎摘要（上下文）
    context_text = ""
    if previous_descriptions:
        recent = previous_descriptions[-50:]  # 最近50条
        context_text = "## 近期演绎摘要（上下文连贯性参考）\n" + "\n".join(
            f"- {desc}" for desc in recent[-10:]  # 显示最近10条完整内容
        )
        if len(recent) > 10:
            context_text = f"（共{len(recent)}条历史摘要，显示最近10条）\n" + context_text

    # 相关事件检索
    events_text = ""
    if related_events:
        events_text = "## 相关历史事件（可参考引用）\n" + "\n".join(
            f"- 第{e.get('chapter', '?')}章: {e.get('event_name', '')}: {e.get('event_detail', '')[:100]}"
            for e in related_events[:5]
        )

    # 快捷按钮 soft hint
    action_hint = ACTION_TYPE_HINTS.get(action_type, "")
    hint_text = f"\n## 叙事偏置提示（软约束，若玩家输入明显是别的事则以玩家输入为准）\n{action_hint}" if action_hint else ""

    # 偏离原著警告
    divergence_text = ""
    if lore_check.get("canon_divergence"):
        divergence_text = "\n## ⚠️ 世界线已偏离原著\n本次行为违背了原著剧情走向，叙述中可以暗示世界线的分歧。"

    # 角色当前时期的功法/装备/灵兽（时间线约束）
    abilities_text = _format_snapshot_abilities(snapshot)
    abilities_block = f"\n{abilities_text}" if abilities_text else ""

    prompt = f"""你是《凡人修仙传》的叙述者。请根据以下信息生成一段故事叙述。

## 角色
{character_name}，{realm}
知识边界：只知道第{knowledge_cutoff}章及之前的事情{abilities_block}
{present_text}

## 玩家行动
{action_detail}
{hint_text}

## 代价（如有，必须在叙述中体现）
{consequences_text or "无"}
{triggered_cons_text}
{divergence_text}

## 叙述建议
{lore_check.get("narrative_hint", "")}

{context_text}

{events_text}

{CHARACTER_INTERACTION_RULES}

{KNOWLEDGE_BOUNDARY_RULES}

## 要求
1. **严格控制在900-1100字**（目标1000字，绝对不超过1100字）
2. 文风贴近《凡人修仙传》原著：冷静、克制、描写细腻
3. 第三人称视角
4. **必须包含角色间的对话**，对话占比约30-40%
5. 在场角色都应有合理的反应和互动，不能作为透明人
6. 如有代价，必须自然融入叙述
7. 不要出现现代用语
8. 保持与近期摘要的连贯性
9. 遵守角色知识边界规则
10. **功法约束**：角色只能使用"已掌握功法"列表中的功法，不能凭空使用未来才学会的功法（如大庚剑阵、噬灵术等高阶功法）

**再次强调：总字数必须控制在900-1100字之间，超过1100字视为不合格。写到1000字左右就要开始收尾。**

请直接输出叙述文本，不要其他内容。"""

    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            f"{settings.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2048,
                "temperature": 0.8,
            },
        )

    if resp.status_code == 200:
        return resp.json()["choices"][0]["message"]["content"].strip()
    log.error(f"Narrative generation failed: {resp.status_code}")
    return "叙述生成失败。"


async def generate_narrative_stream(
    action_detail: str,
    character_name: str,
    snapshot: CharacterSnapshot | None,
    chapter_context: int,
    lore_check: dict,
    action_type: str = "custom",
    previous_descriptions: list[str] | None = None,
    triggered_consequences: list[dict] | None = None,
    related_events: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """
    流式生成演绎叙述（SSE）
    """
    realm = snapshot.realm_stage if snapshot else "未知"
    knowledge_cutoff = snapshot.knowledge_cutoff if snapshot else chapter_context

    # 代价文本
    consequences_text = ""
    if lore_check.get("triggered_rules"):
        consequences_text = "\n".join(
            f"- {r['rule_name']}: {r['description']}"
            for r in lore_check["triggered_rules"]
        )

    # 触发的延迟代价
    triggered_cons_text = ""
    if triggered_consequences:
        triggered_cons_text = "## 本次触发的延迟代价（必须在叙述中体现！）\n" + "\n".join(
            f"- {c.get('rule_name', '未知')}: {c.get('description', '')}"
            for c in triggered_consequences
        )

    # 在场角色
    present_characters = lore_check.get("present_characters", [])
    present_text = f"当前在场角色：{', '.join(present_characters)}" if present_characters else ""

    # 近期演绎摘要
    context_text = ""
    if previous_descriptions:
        recent = previous_descriptions[-50:]
        context_text = "## 近期演绎摘要（上下文连贯性参考）\n" + "\n".join(
            f"- {desc}" for desc in recent[-10:]
        )

    # 相关事件
    events_text = ""
    if related_events:
        events_text = "## 相关历史事件（可参考引用）\n" + "\n".join(
            f"- 第{e.get('chapter', '?')}章: {e.get('event_name', '')}: {e.get('event_detail', '')[:100]}"
            for e in related_events[:5]
        )

    # 快捷按钮 soft hint
    action_hint = ACTION_TYPE_HINTS.get(action_type, "")
    hint_text = f"\n## 叙事偏置提示（软约束）\n{action_hint}" if action_hint else ""

    # 偏离原著警告
    divergence_text = ""
    if lore_check.get("canon_divergence"):
        divergence_text = "\n## ⚠️ 世界线已偏离原著\n本次行为违背了原著剧情走向。"

    # 角色当前时期的功法/装备/灵兽（时间线约束）
    abilities_text = _format_snapshot_abilities(snapshot)
    abilities_block = f"\n{abilities_text}" if abilities_text else ""

    prompt = f"""你是《凡人修仙传》的叙述者。请根据以下信息生成一段故事叙述。

## 角色
{character_name}，{realm}
知识边界：只知道第{knowledge_cutoff}章及之前的事情{abilities_block}
{present_text}

## 玩家行动
{action_detail}
{hint_text}

## 代价（如有，必须在叙述中体现）
{consequences_text or "无"}
{triggered_cons_text}
{divergence_text}

## 叙述建议
{lore_check.get("narrative_hint", "")}

{context_text}

{events_text}

{CHARACTER_INTERACTION_RULES}

{KNOWLEDGE_BOUNDARY_RULES}

## 要求
1. **严格控制在900-1100字**（目标1000字，绝对不超过1100字）
2. 文风贴近《凡人修仙传》原著：冷静、克制、描写细腻
3. 第三人称视角
4. **必须包含角色间的对话**，对话占比约30-40%
5. 在场角色都应有合理的反应和互动
6. 如有代价，必须自然融入叙述
7. 不要出现现代用语
8. 保持与近期摘要的连贯性
9. 遵守角色知识边界规则
10. **功法约束**：角色只能使用"已掌握功法"列表中的功法，不能凭空使用未来才学会的功法（如大庚剑阵、噬灵术等高阶功法）

**再次强调：总字数必须控制在900-1100字之间，超过1100字视为不合格。写到1000字左右就要开始收尾。**

请直接输出叙述文本，不要其他内容。"""

    timeout = httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            f"{settings.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
                "max_tokens": 2048,
                "temperature": 0.8,
            },
        ) as resp:
            if resp.status_code != 200:
                error_text = await resp.aread()
                raise RuntimeError(f"LLM stream failed: {resp.status_code} {error_text.decode(errors='ignore')[:300]}")

            saw_done = False
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    saw_done = True
                    break
                try:
                    chunk = json.loads(payload)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

            if not saw_done:
                raise RuntimeError("LLM stream ended unexpectedly before [DONE]")


async def generate_description(narrative: str) -> str:
    """
    生成演绎摘要（100-200字），用于后续上下文传递。
    """
    prompt = f"""请为以下故事叙述生成一个简洁摘要，概述这段叙述中发生的主要事件。

## 叙述内容
{narrative}

## 要求
1. 100-200字
2. 包含：主要人物、发生了什么事、结果如何
3. 客观简洁，不带感情色彩
4. 只输出摘要文本，不要其他内容

请直接输出摘要："""

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{settings.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
                "temperature": 0.3,
            },
        )

    if resp.status_code == 200:
        return resp.json()["choices"][0]["message"]["content"].strip()
    log.error(f"Description generation failed: {resp.status_code}")
    return ""


async def check_consequence_triggers(
    worldline_id: str,
    chapter_context: int,
    world_year: int | None,
    character_name: str,
    action_detail: str,
    present_characters: list[str] | None,
    db: AsyncSession,
) -> list[dict]:
    """
    检查是否有代价应该被触发。

    触发条件类型:
    - immediate: 立即触发（创建时就触发）
    - years_later: 指定年份后触发
    - realm_trigger: 境界变化时触发
    - conditional: 条件触发（基于关键词/角色/事件匹配）

    返回应该触发的代价列表。
    """
    # 获取该世界线的所有待触发代价
    result = await db.execute(
        select(WorldlineConsequence).where(
            WorldlineConsequence.worldline_id == worldline_id,
            WorldlineConsequence.status == "pending",
        )
    )
    pending_consequences = result.scalars().all()

    triggered = []

    for cons in pending_consequences:
        should_trigger = False
        trigger_reason = ""

        # 1. 立即触发类型（应该在创建时就触发了）
        if cons.trigger_type == "immediate":
            should_trigger = True
            trigger_reason = "立即触发"

        # 2. 年份触发
        elif cons.trigger_type == "years_later" and world_year:
            if cons.trigger_at_year and world_year >= cons.trigger_at_year:
                should_trigger = True
                trigger_reason = f"到达指定年份 {cons.trigger_at_year}"

        # 3. 境界触发
        elif cons.trigger_type == "realm_trigger":
            # 这需要单独检查境界变化，暂时跳过
            pass

        # 4. 条件触发（关键词/角色匹配）
        elif cons.trigger_type == "conditional":
            # 检查描述中的触发条件
            trigger_condition = cons.description or ""

            # 检查是否提到了在场角色
            if present_characters:
                for char in present_characters:
                    if char in trigger_condition:
                        should_trigger = True
                        trigger_reason = f"与{char}再次相遇"
                        break

            # 检查行动描述中的关键词匹配
            if not should_trigger:
                keywords = ["灵力", "法术", "修炼", "突破", "战斗", "使用"]
                for kw in keywords:
                    if kw in trigger_condition and kw in action_detail:
                        should_trigger = True
                        trigger_reason = f"触发条件：{kw}"
                        break

        if should_trigger:
            triggered.append({
                "id": cons.id,
                "lore_rule_id": cons.lore_rule_id,
                "consequence_type": cons.consequence_type,
                "description": cons.description,
                "severity": cons.severity,
                "trigger_reason": trigger_reason,
            })

    return triggered


async def mark_consequences_triggered(
    consequence_ids: list[int],
    db: AsyncSession,
) -> None:
    """将指定代价标记为已触发"""
    from datetime import datetime
    for cons_id in consequence_ids:
        result = await db.execute(
            select(WorldlineConsequence).where(WorldlineConsequence.id == cons_id)
        )
        cons = result.scalar_one_or_none()
        if cons:
            cons.status = "triggered"
            cons.triggered_at = datetime.now()


async def retrieve_related_events(
    character_id: int,
    chapter_context: int,
    action_detail: str,
    present_characters: list[str] | None,
    db: AsyncSession,
    limit: int = 5,
) -> list[dict]:
    """
    检索与当前演绎相关的历史事件，用于上下文增强。
    """
    # 从 events 表检索与角色相关的事件
    events_result = await db.execute(
        select(Event).where(
            Event.worldline_id == "canon",
            Event.is_deleted.is_(False),
            Event.chapter <= chapter_context,
            Event.primary_character_id == character_id,
        ).order_by(Event.chapter.desc()).limit(limit)
    )
    events = events_result.scalars().all()

    result = []
    for e in events:
        result.append({
            "id": e.id,
            "event_name": e.event_name,
            "event_type": e.event_type,
            "chapter": e.chapter,
            "event_detail": e.event_detail,
            "result": e.result,
        })

    return result
