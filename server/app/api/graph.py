from fastapi import APIRouter, Query
import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.connections import get_neo4j
from app.models.tables import Character, CharacterRelation
from app.schemas.responses import GraphData, GraphEdge, GraphNode

router = APIRouter(prefix="/graph", tags=["graph"])

# 低价值角色名称过滤规则（与 characters.py 保持一致）
LOW_VALUE_NAME_PATTERNS = [
    r"^某",           # 以"某"开头
    r"^一[名位个]",   # 一名、一位、一个
    r"老者$",         # 以"老者"结尾
    r"修士$",         # 以"修士"结尾
    r"弟子$",         # 以"弟子"结尾
    r"^[某这那]人$",  # 某人、这人、那人
    r"^路人",         # 路人甲等
    r"^无名",         # 无名开头
    r"^那[名位个]",   # 那名、那位
    r"^这[名位个]",   # 这名、这位
    r"^陌生",         # 陌生人、陌生男子
    r"男子$",         # 以"男子"结尾
    r"女子$",         # 以"女子"结尾
    r"^中年[人男女]", # 中年人、中年男子、中年女子
    r"^青年$",        # 单独的"青年"
    r"^少年$",        # 单独的"少年"
    r"^老人$",        # 单独的"老人"
    r"^黑衣人$",      # 黑衣人
    r"^白衣人$",      # 白衣人
    r"妇人$",         # 以"妇人"结尾
    r"^[一二三四五六七八九十]哥$",  # 一哥、二哥等
    r"^[一二三四五六七八九十]姐$",  # 一姐、二姐等
    r"^[一二三四五六七八九十]弟$",  # 一弟、二弟等
    r"^[一二三四五六七八九十]妹$",  # 一妹、二妹等
    r"管事$",         # 以"管事"结尾
    r"丫鬟$",         # 以"丫鬟"结尾
    r"侍女$",         # 以"侍女"结尾
    r"侍卫$",         # 以"侍卫"结尾
    r"^兄台$",        # 兄台
    r"^侄孙$",        # 侄孙
]

FORCE_LOW_VALUE_NAME_PATTERNS = [
    r".*鬼影.*",
    r".*身影$",
    r".*影子$",
    r".*汉子$",
    r".*怪人$",
    r".*老妪$",
    r".*美妇$",
    r".*少妇$",
    r".*蒙面.*人.*",
    r".*衣人$",
    r".*男修$",
    r".*女修$",
    r".*道友$",
    r".*门主$",
    r".*副门主$",
    r".*大汉$",
    r".*元婴$",
    r".*父母$",
    r".*大哥$",
    r".*二哥$",
    r".*三哥$",
    r"^神秘人物$",
    r".*铁匠$",
    r"^大胡子$",
    r"^中年胖子$",
    r"^陈胖子$",
    r"^雷胖子$",
    r"^韩胖子$",
]

LOW_SIGNAL_RELATION_TYPES = {
    "旧识",
    "敌对",
    "同行/交谈",
    "disciple",
    "elder",
    "交易/雇佣",
    "同门/苦恋",
    "师伯",
    "师叔师侄",
    "师徒/敌对",
    "敌对/胁迫",
}

SYMMETRIC_RELATION_TYPES = {
    "同门",
    "血亲",
    "敌对",
    "盟友",
    "道侣",
    "旧识",
}

def _is_low_value_character(name: str, is_major: bool = False) -> bool:
    """判断是否为低价值角色（应过滤）"""
    if not name:
        return True
    for pattern in FORCE_LOW_VALUE_NAME_PATTERNS:
        if re.search(pattern, name):
            return True
    if is_major:
        return False
    if len(name) == 1:
        return True
    for pattern in LOW_VALUE_NAME_PATTERNS:
        if re.search(pattern, name):
            return True
    return False


def _is_low_signal_relation_type(relation_type: str | None) -> bool:
    return bool(relation_type) and relation_type in LOW_SIGNAL_RELATION_TYPES


def _relation_type_from_edge(edge: GraphEdge) -> str | None:
    relation_type = edge.properties.get("relation_type") or edge.properties.get("type")
    return relation_type if isinstance(relation_type, str) and relation_type else None


def _merge_edge_properties(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)

    existing_id = merged.get("id")
    incoming_id = incoming.get("id")
    merged_ids = []
    for candidate in (existing_id, incoming_id):
        if candidate is not None and candidate not in merged_ids:
            merged_ids.append(candidate)
    if merged_ids:
        merged["merged_ids"] = merged_ids
        merged["id"] = merged_ids[0]

    for start_key in ("valid_from_chapter", "since_chapter"):
        existing_start = merged.get(start_key)
        incoming_start = incoming.get(start_key)
        if isinstance(existing_start, int) and isinstance(incoming_start, int):
            merged[start_key] = min(existing_start, incoming_start)
        elif existing_start is None and incoming_start is not None:
            merged[start_key] = incoming_start

    for end_key in ("valid_until_chapter", "until_chapter"):
        existing_end = merged.get(end_key)
        incoming_end = incoming.get(end_key)
        if existing_end is None or incoming_end is None:
            merged[end_key] = None
        elif isinstance(existing_end, int) and isinstance(incoming_end, int):
            merged[end_key] = max(existing_end, incoming_end)

    existing_attrs = merged.get("attributes")
    incoming_attrs = incoming.get("attributes")
    if isinstance(existing_attrs, dict) and isinstance(incoming_attrs, dict):
        merged_attrs = dict(existing_attrs)
        for key, incoming_value in incoming_attrs.items():
            existing_value = merged_attrs.get(key)
            if existing_value is None:
                merged_attrs[key] = incoming_value
            elif existing_value == incoming_value:
                continue
            elif isinstance(existing_value, list):
                if incoming_value not in existing_value:
                    merged_attrs[key] = [*existing_value, incoming_value]
            else:
                merged_attrs[key] = [existing_value, incoming_value]
        merged["attributes"] = merged_attrs
    elif existing_attrs is None and incoming_attrs is not None:
        merged["attributes"] = incoming_attrs

    return merged


def _edge_endpoint_sort_key(node_id: str) -> tuple[int, int, str]:
    return (0, int(node_id), node_id) if node_id.isdigit() else (1, 0, node_id)


def _fold_symmetric_relation_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
    folded: list[GraphEdge] = []
    symmetric_index: dict[tuple[str, str, str], int] = {}

    for edge in edges:
        relation_type = _relation_type_from_edge(edge)
        if edge.type != "RELATION" or relation_type not in SYMMETRIC_RELATION_TYPES:
            folded.append(edge)
            continue

        src, tgt = sorted((edge.source, edge.target), key=_edge_endpoint_sort_key)
        dedupe_key = (src, tgt, relation_type)
        existing_idx = symmetric_index.get(dedupe_key)

        if existing_idx is None:
            folded.append(GraphEdge(
                source=src,
                target=tgt,
                type=edge.type,
                properties=dict(edge.properties),
            ))
            symmetric_index[dedupe_key] = len(folded) - 1
            continue

        existing_edge = folded[existing_idx]
        existing_edge.properties = _merge_edge_properties(existing_edge.properties, edge.properties)

    return folded


@router.get("", response_model=GraphData)
async def get_graph(
    node_types: str = Query("Character", description="Comma-separated node types"),
    center_id: int | None = Query(None, description="Center node PG id for ego-graph"),
    depth: int = Query(2, ge=1, le=4, description="Traversal depth"),
    chapter_max: int | None = Query(None, description="Only show relations up to this chapter"),
    limit: int = Query(200, ge=1, le=1000),
    exclude_minor: bool = Query(True, description="过滤低价值角色(路人/无名)"),
    major_only: bool = Query(False, description="只显示主要角色(is_major=true)"),
    worldline: str = "canon",
):
    types = [t.strip() for t in node_types.split(",")]
    driver = get_neo4j()

    if center_id is not None:
        return await _ego_graph(driver, center_id, depth, chapter_max, limit, worldline, exclude_minor, major_only)

    return await _full_graph(driver, types, chapter_max, limit, worldline, exclude_minor, major_only)


def _character_to_graph_node(character: Character) -> GraphNode | None:
    if _is_low_value_character(character.name, character.is_major):
        return None
    return GraphNode(
        id=str(character.id),
        label=character.name,
        type="Character",
        properties={
            "id": character.id,
            "name": character.name,
            "gender": character.gender,
            "first_chapter": character.first_chapter,
            "is_major": character.is_major,
        },
    )


def _character_relation_to_edge(relation: CharacterRelation) -> GraphEdge:
    return GraphEdge(
        source=str(relation.from_character_id),
        target=str(relation.to_character_id),
        type="RELATION",
        properties={
            "id": relation.id,
            "type": relation.relation_type,
            "relation_type": relation.relation_type,
            "valid_from_chapter": relation.valid_from_chapter,
            "valid_until_chapter": relation.valid_until_chapter,
            "attributes": relation.attributes or {},
            "confidence": relation.confidence,
        },
    )


def _apply_character_relation_filters(query, from_char, to_char, chapter_max: int | None, worldline: str, major_only: bool):
    query = query.where(
        CharacterRelation.worldline_id == worldline,
        CharacterRelation.is_deleted.is_(False),
        from_char.worldline_id == worldline,
        from_char.is_deleted.is_(False),
        to_char.worldline_id == worldline,
        to_char.is_deleted.is_(False),
    )
    if chapter_max is not None:
        query = query.where(
            CharacterRelation.valid_from_chapter <= chapter_max,
            or_(
                CharacterRelation.valid_until_chapter.is_(None),
                CharacterRelation.valid_until_chapter >= chapter_max,
            ),
        )
    if major_only:
        query = query.where(from_char.is_major.is_(True), to_char.is_major.is_(True))
    return query


async def _full_character_graph_pg(
    db: AsyncSession,
    chapter_max: int | None,
    limit: int,
    worldline: str,
    exclude_minor: bool = True,
    major_only: bool = False,
) -> GraphData:
    from_char = aliased(Character)
    to_char = aliased(Character)

    query = (
        select(CharacterRelation, from_char, to_char)
        .join(from_char, CharacterRelation.from_character_id == from_char.id)
        .join(to_char, CharacterRelation.to_character_id == to_char.id)
        .order_by(CharacterRelation.valid_from_chapter.desc(), CharacterRelation.id.desc())
        .limit(limit)
    )
    query = _apply_character_relation_filters(query, from_char, to_char, chapter_max, worldline, major_only)

    result = await db.execute(query)
    rows = result.all()

    nodes_map: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    for relation, src_char, tgt_char in rows:
        if _is_low_signal_relation_type(relation.relation_type):
            continue
        src_node = _character_to_graph_node(src_char)
        tgt_node = _character_to_graph_node(tgt_char)
        if exclude_minor and (src_node is None or tgt_node is None):
            continue
        if src_node:
            nodes_map[src_node.id] = src_node
        if tgt_node:
            nodes_map[tgt_node.id] = tgt_node
        if src_node and tgt_node:
            edges.append(_character_relation_to_edge(relation))

    return GraphData(nodes=list(nodes_map.values()), edges=_fold_symmetric_relation_edges(edges))


async def _ego_character_graph_pg(
    db: AsyncSession,
    center_id: int,
    depth: int,
    chapter_max: int | None,
    limit: int,
    worldline: str,
    exclude_minor: bool = True,
    major_only: bool = False,
) -> GraphData:
    center = await db.get(Character, center_id)
    if center is None or center.worldline_id != worldline or center.is_deleted:
        return GraphData(nodes=[], edges=[])

    nodes_map: dict[str, GraphNode] = {}
    center_node = _character_to_graph_node(center)
    if center_node:
        nodes_map[center_node.id] = center_node

    collected_edges: dict[int, GraphEdge] = {}
    frontier = {center_id}
    visited = {center_id}

    for _ in range(depth):
        if not frontier or len(collected_edges) >= limit:
            break

        from_char = aliased(Character)
        to_char = aliased(Character)
        query = (
            select(CharacterRelation, from_char, to_char)
            .join(from_char, CharacterRelation.from_character_id == from_char.id)
            .join(to_char, CharacterRelation.to_character_id == to_char.id)
            .where(
                or_(
                    CharacterRelation.from_character_id.in_(frontier),
                    CharacterRelation.to_character_id.in_(frontier),
                )
            )
            .order_by(CharacterRelation.valid_from_chapter.desc(), CharacterRelation.id.desc())
            .limit(limit)
        )
        query = _apply_character_relation_filters(query, from_char, to_char, chapter_max, worldline, major_only)

        result = await db.execute(query)
        next_frontier: set[int] = set()

        for relation, src_char, tgt_char in result.all():
            if _is_low_signal_relation_type(relation.relation_type):
                continue
            src_node = _character_to_graph_node(src_char)
            tgt_node = _character_to_graph_node(tgt_char)
            if exclude_minor:
                keep_src = src_node is not None or src_char.id == center_id
                keep_tgt = tgt_node is not None or tgt_char.id == center_id
                if not keep_src or not keep_tgt:
                    continue
            if src_node:
                nodes_map[src_node.id] = src_node
            if tgt_node:
                nodes_map[tgt_node.id] = tgt_node

            collected_edges.setdefault(relation.id, _character_relation_to_edge(relation))

            if src_char.id not in visited:
                next_frontier.add(src_char.id)
            if tgt_char.id not in visited:
                next_frontier.add(tgt_char.id)

            if len(collected_edges) >= limit:
                break

        frontier = next_frontier - visited
        visited.update(next_frontier)

    return GraphData(
        nodes=list(nodes_map.values()),
        edges=_fold_symmetric_relation_edges(list(collected_edges.values())),
    )


async def _full_graph(driver, types: list[str], chapter_max: int | None, limit: int, worldline: str, exclude_minor: bool = True, major_only: bool = False) -> GraphData:
    type_filter_n = " OR ".join(f"n:{t}" for t in types)
    type_filter_m = " OR ".join(f"m:{t}" for t in types)
    chapter_filter = ""
    if chapter_max is not None:
        chapter_filter = """
      AND (
        coalesce(r.valid_from_chapter, r.since_chapter) IS NULL
        OR coalesce(r.valid_from_chapter, r.since_chapter) <= $ch_max
      )
      AND (
        coalesce(r.valid_until_chapter, r.until_chapter) IS NULL
        OR coalesce(r.valid_until_chapter, r.until_chapter) >= $ch_max
      )
"""

    # 只显示主要角色
    major_filter = ""
    if major_only:
        major_filter = "AND (n.is_major = true OR NOT n:Character) AND (m.is_major = true OR NOT m:Character)"

    query = f"""
    MATCH (n)-[r]-(m)
    WHERE ({type_filter_n}) AND ({type_filter_m})
      AND (r.worldline IS NULL OR r.worldline = $wl)
      AND (r.deleted IS NULL OR r.deleted = false)
      {chapter_filter}
      {major_filter}
    RETURN n, r, m
    LIMIT $limit
    """
    params: dict = {"wl": worldline, "limit": limit}
    if chapter_max is not None:
        params["ch_max"] = chapter_max

    nodes_map: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    async with driver.session() as session:
        result = await session.run(query, **params)
        async for record in result:
            n = record["n"]
            m = record["m"]
            r = record["r"]
            props = dict(r)
            relation_type = props.get("type") or props.get("relation_type")
            if r.type == "RELATION" and _is_low_signal_relation_type(relation_type):
                continue

            for node in (n, m):
                nid = str(node.get("id", node.element_id))
                if nid not in nodes_map:
                    labels = list(node.labels)
                    node_name = node.get("name", nid)
                    node_type = labels[0] if labels else "Unknown"
                    is_major = node.get("is_major", False)

                    # 过滤低价值角色（仅 Character 类型）
                    if exclude_minor and node_type == "Character" and _is_low_value_character(node_name, is_major):
                        continue

                    nodes_map[nid] = GraphNode(
                        id=nid,
                        label=node_name,
                        type=node_type,
                        properties=dict(node),
                    )

            src = str(n.get("id", n.element_id))
            tgt = str(m.get("id", m.element_id))
            # 只添加两端节点都存在的边
            if src in nodes_map and tgt in nodes_map:
                edges.append(GraphEdge(
                    source=src,
                    target=tgt,
                    type=r.type,
                    properties=props,
                ))

    return GraphData(nodes=list(nodes_map.values()), edges=_fold_symmetric_relation_edges(edges))


async def _ego_graph(driver, center_id: int, depth: int, chapter_max: int | None, limit: int, worldline: str, exclude_minor: bool = True, major_only: bool = False) -> GraphData:
    chapter_filter = ""
    if chapter_max is not None:
        chapter_filter = """
      AND ALL(
        r IN relationships(path)
        WHERE (
          coalesce(r.valid_from_chapter, r.since_chapter) IS NULL
          OR coalesce(r.valid_from_chapter, r.since_chapter) <= $ch_max
        )
        AND (
          coalesce(r.valid_until_chapter, r.until_chapter) IS NULL
          OR coalesce(r.valid_until_chapter, r.until_chapter) >= $ch_max
        )
      )
"""

    query = f"""
    MATCH path = (center)-[*1..{depth}]-(neighbor)
    WHERE center.id = $center_id
      {chapter_filter}
    RETURN path
    LIMIT $limit
    """
    params: dict = {"center_id": center_id, "limit": limit}
    if chapter_max is not None:
        params["ch_max"] = chapter_max

    nodes_map: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    async with driver.session() as session:
        result = await session.run(query, **params)
        async for record in result:
            path = record["path"]
            kept_relationships: list[tuple[Any, dict, str, str]] = []
            kept_node_ids = {str(center_id)}
            for rel in path.relationships:
                props = dict(rel)
                relation_type = props.get("type") or props.get("relation_type")
                if rel.type == "RELATION" and _is_low_signal_relation_type(relation_type):
                    continue
                src = str(rel.start_node.get("id", rel.start_node.element_id))
                tgt = str(rel.end_node.get("id", rel.end_node.element_id))
                kept_relationships.append((rel, props, src, tgt))
                kept_node_ids.add(src)
                kept_node_ids.add(tgt)

            for node in path.nodes:
                nid = str(node.get("id", node.element_id))
                if nid not in kept_node_ids:
                    continue
                if nid not in nodes_map:
                    labels = list(node.labels)
                    node_name = node.get("name", nid)
                    node_type = labels[0] if labels else "Unknown"
                    is_major = node.get("is_major", False)

                    # 过滤低价值角色（仅 Character 类型）
                    if exclude_minor and node_type == "Character" and _is_low_value_character(node_name, is_major):
                        continue

                    nodes_map[nid] = GraphNode(
                        id=nid,
                        label=node_name,
                        type=node_type,
                        properties=dict(node),
                    )
            for rel, props, src, tgt in kept_relationships:
                # 只添加两端节点都存在的边
                if src in nodes_map and tgt in nodes_map:
                    edges.append(GraphEdge(
                        source=src,
                        target=tgt,
                        type=rel.type,
                        properties=dict(rel),
                    ))

    return GraphData(nodes=list(nodes_map.values()), edges=_fold_symmetric_relation_edges(edges))
