from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connections import get_pg
from app.models.tables import (
    Character,
    CharacterAlias,
    CharacterRelation,
    CharacterRealmTimeline,
    CharacterSnapshot,
    Faction,
    FactionMembership,
    ItemArtifact,
    ItemOwnership,
)
from app.schemas.responses import (
    AliasOut,
    CharacterBrief,
    CharacterDetail,
    MembershipOut,
    OwnershipOut,
    RealmTimelineOut,
    RelationOut,
    SnapshotOut,
)

router = APIRouter(prefix="/characters", tags=["characters"])

WORLDLINE = "canon"


# 低价值角色名称过滤规则
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
    # 师兄/师姐/师弟/师妹/师叔/师伯等称谓
    r"^[大二三四五六七八九十]?师[兄姐弟妹叔伯]$",  # 师兄、大师兄、三师兄、师姐等
    r"^小师[兄姐弟妹]$",  # 小师兄、小师姐等
    r"^老师[兄姐弟妹]$",  # 老师兄等
    r"师祖$",         # 以"师祖"结尾
    r"长老$",         # 以"长老"结尾（非特定人物）
    r"掌门$",         # 以"掌门"结尾（非特定人物）
    r"真人$",         # 以"真人"结尾（非特定人物）
    r"^[大二三四五六七八九十]长老$",  # 大长老、二长老等
    r"前辈$",         # 以"前辈"结尾
    r"道友$",         # 以"道友"结尾
    r"仙子$",         # 以"仙子"结尾（非特定人物）
    r"^那少年$",      # 那少年
    r"^那老者$",      # 那老者
    r"^那男子$",      # 那男子
    r"^那女子$",      # 那女子
]

def _is_low_value_character(name: str, is_major: bool) -> bool:
    """判断是否为低价值角色（应过滤）"""
    import re
    if not name:
        return True
    # 主要角色不过滤
    if is_major:
        return False
    # 单字名（只有姓）
    if len(name) == 1:
        return True
    # 匹配低价值名称模式
    for pattern in LOW_VALUE_NAME_PATTERNS:
        if re.search(pattern, name):
            return True
    return False


@router.get("", response_model=list[CharacterBrief])
async def list_characters(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str | None = None,
    faction_id: int | None = None,
    is_major: bool | None = None,
    exclude_minor: bool = Query(True, description="过滤低价值角色(路人/无名)"),
    db: AsyncSession = Depends(get_pg),
):
    q = select(Character).where(
        Character.worldline_id == WORLDLINE,
        Character.is_deleted.is_(False),
    )

    # 在 DB 层面过滤低价值角色名（仅过滤非 is_major 角色）
    if exclude_minor:
        import re as _re
        from sqlalchemy import and_, not_, or_
        # 单字名
        minor_conditions = [
            and_(not_(Character.is_major), func.length(Character.name) <= 1),
        ]
        # 正则模式匹配的低价值角色 — 用 LIKE/类似模式在 SQL 实现
        like_patterns = [
            ("某%", True),      # 以"某"开头
            ("%老者", False),   # 以"老者"结尾
            ("%修士", False),   # 以"修士"结尾
            ("%弟子", False),   # 以"弟子"结尾
            ("路人%", True),    # 路人甲等
            ("无名%", True),    # 无名开头
            ("陌生%", True),    # 陌生人、陌生男子
            ("%男子", False),   # 以"男子"结尾
            ("%女子", False),   # 以"女子"结尾
            ("%妇人", False),   # 以"妇人"结尾
            ("%管事", False),   # 以"管事"结尾
            ("%丫鬟", False),   # 以"丫鬟"结尾
            ("%侍女", False),   # 以"侍女"结尾
            ("%侍卫", False),   # 以"侍卫"结尾
            # 新增：师门称谓、门派职位
            ("%师祖", False),   # 以"师祖"结尾
            ("%长老", False),   # 以"长老"结尾
            ("%掌门", False),   # 以"掌门"结尾
            ("%真人", False),   # 以"真人"结尾
            ("%前辈", False),   # 以"前辈"结尾
            ("%道友", False),   # 以"道友"结尾
            ("%仙子", False),   # 以"仙子"结尾
            ("那少年", True),   # 那少年
            ("那老者", True),   # 那老者
        ]
        for pattern, _is_prefix in like_patterns:
            minor_conditions.append(
                and_(not_(Character.is_major), Character.name.like(pattern))
            )
        # 精确匹配
        exact_minor = [
            "某人", "这人", "那人", "青年", "少年", "老人",
            "黑衣人", "白衣人", "兄台", "侄孙",
            "中年人", "中年男子", "中年女子",
            # 师门称谓
            "师兄", "师姐", "师弟", "师妹", "师叔", "师伯",
            "大师兄", "二师兄", "三师兄", "四师兄", "五师兄",
            "大师姐", "二师姐", "三师姐", "四师姐", "五师姐",
            "大师弟", "二师弟", "三师弟", "四师弟", "五师弟",
            "大师妹", "二师妹", "三师妹", "四师妹", "五师妹",
            "小师兄", "小师姐", "小师弟", "小师妹",
            "老师兄", "老师姐",
            # 门派职位
            "大长老", "二长老", "三长老", "四长老", "五长老",
            "六长老", "七长老", "八长老", "九长老", "十长老",
        ]
        minor_conditions.append(
            and_(not_(Character.is_major), Character.name.in_(exact_minor))
        )
        q = q.where(not_(or_(*minor_conditions)))

    if search:
        # search by name or alias
        alias_ids = select(CharacterAlias.character_id).where(
            CharacterAlias.alias.ilike(f"%{search}%")
        )
        q = q.where(Character.name.ilike(f"%{search}%") | Character.id.in_(alias_ids))
    if is_major is not None:
        q = q.where(Character.is_major == is_major)
    if faction_id is not None:
        member_ids = select(FactionMembership.character_id).where(
            FactionMembership.faction_id == faction_id,
            FactionMembership.is_deleted.is_(False),
        )
        q = q.where(Character.id.in_(member_ids))

    q = q.order_by(Character.first_chapter, Character.id)
    q = q.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(q)
    characters = result.scalars().all()

    out = []
    for c in characters:
        out.append(
            CharacterBrief(
                id=c.id,
                name=c.name,
                gender=c.gender,
                first_chapter=c.first_chapter,
                is_major=c.is_major,
                aliases=[a.alias for a in c.aliases],
                realm_stages=[s.realm_stage for s in c.snapshots],
            )
        )
    return out


@router.get("/count")
async def count_characters(db: AsyncSession = Depends(get_pg)):
    result = await db.execute(
        select(func.count()).select_from(Character).where(
            Character.worldline_id == WORLDLINE,
            Character.is_deleted.is_(False),
        )
    )
    return {"count": result.scalar_one()}


@router.get("/for-chat", response_model=list[CharacterBrief])
async def list_characters_for_chat(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    search: str | None = None,
    db: AsyncSession = Depends(get_pg),
):
    """
    获取可用于对话/演绎的核心角色列表。

    核心角色定义：
    1. is_major = true 的角色
    2. 有 character_snapshots 的角色（有详细设定）
    3. 有 character_relations 的角色（有故事关联）

    排除：低价值角色（路人、称谓类）
    """
    from sqlalchemy import and_, distinct, not_, or_, union_all

    # 子查询：有 snapshot 的角色
    has_snapshot = select(distinct(CharacterSnapshot.character_id)).where(
        CharacterSnapshot.worldline_id == WORLDLINE
    )

    # 子查询：有关系的角色（from 或 to）
    has_relation_from = select(distinct(CharacterRelation.from_character_id)).where(
        CharacterRelation.worldline_id == WORLDLINE,
        CharacterRelation.is_deleted.is_(False),
    )
    has_relation_to = select(distinct(CharacterRelation.to_character_id)).where(
        CharacterRelation.worldline_id == WORLDLINE,
        CharacterRelation.is_deleted.is_(False),
    )

    # 主查询：核心角色
    q = select(Character).where(
        Character.worldline_id == WORLDLINE,
        Character.is_deleted.is_(False),
        or_(
            Character.is_major == True,
            Character.id.in_(has_snapshot),
            Character.id.in_(has_relation_from),
            Character.id.in_(has_relation_to),
        ),
    )

    # 排除低价值角色
    # 对于泛称类（如"神秘男子"），无论 is_major 都过滤
    # 对于其他模式（如"%修士"），只过滤非 is_major
    like_patterns = [
        ("某%", True),
        ("%老者", False),
        ("%修士", False),
        ("路人%", True),
        ("无名%", True),
        ("陌生%", True),
        ("%妇人", False),
        ("%管事", False),
        ("%丫鬟", False),
        ("%侍女", False),
        ("%侍卫", False),
        ("%道友", False),
        ("那少年", True),
        ("那老者", True),
    ]
    minor_conditions = [
        func.length(Character.name) <= 1,  # 单字名一律过滤
    ]
    for pattern, _is_prefix in like_patterns:
        minor_conditions.append(
            and_(not_(Character.is_major), Character.name.like(pattern))
        )

    # 泛称类：无论 is_major 都过滤
    generic_patterns = [
        "%男子",   # 青年男子、神秘男子等
        "%女子",   # 青年女子、神秘女子等
        "%长老",   # 大长老、二长老等
        "%掌门",
        "%真人",
        "%仙子",
        "%衣人",   # 蓝衣人、黄衣人、灰衣人等
        "%袍人",   # 黑袍人等
        "%师祖",   # 李师祖、掩月宗师祖等
        "%女弟子", # 灵兽山女弟子等
        "%弟子",
        "%道士",
        "%公子",
        "%少女",
        "%前辈",
        "%老祖",   # 燕家老祖等
        "%少主",   # 鬼灵门少主等
        "%掌柜",   # 田掌柜等
        "%青年",   # 矮粗青年等
        "%总管",   # 馨王府的总管等
        "%小姐",   # 表小姐等
        "%老道",   # 老道等
        "%老二",   # 蒙山五友老二等
        "%老大",
        "%老三",
        "%老四",
        "%老五",
        "%仙师",   # 吴仙师等
        "%大夫",   # 华大夫等（墨大夫是特例，保留）
        # 称谓类
        "%师叔",
        "%师伯",
        "%师兄",
        "%师姐",
        "%师弟",
        "%师妹",
        "%兄弟",   # 李氏兄弟、慕容兄弟等
        "%姓老者", # 萧姓老者等
        "%大汉",   # 光头大汉等
        "%四友",   # 蒙山四友等
        "%五友",   # 蒙山五友等
        "%大人",   # 血侍大人等
        "%教主",   # 黑煞教教主等
        "%姑娘",   # 邢姑娘等
        "%老者",   # 儒生老者、白衣老者、冷脸老者、白衫老者、黄袍老者等
        "%师叔祖", # 师叔祖、红拂师叔祖等
        "%声音",   # 浑厚的男子声音等
        "%之父",   # 林师兄之父等
        "%忠仆",   # 掌柜忠仆等
    ]
    for pattern in generic_patterns:
        minor_conditions.append(Character.name.like(pattern))

    # 精确匹配：无论 is_major 都过滤的泛称
    always_exclude = [
        "神秘男子", "神秘女子", "神秘老者", "神秘人",
        "青年男子", "青年女子", "巨汉", "儒生",
        "灰衣人", "灰衣男子", "灰衣老者",
        "黑袍人", "黑袍男子", "黑袍老者",
        "白袍人", "白袍男子", "白袍老者",
        "蓝袍人", "蓝袍男子", "蓝袍老者",
        "红袍人", "红袍男子", "红袍老者",
        "老妪", "老妇", "老翁", "老头",
        "美妇", "美妇人", "美貌女子", "丽人",
        "少女", "少妇", "童子", "小童",
        "大汉", "壮汉", "瘦子",
        "使者", "来人", "此人",
        "某人", "这人", "那人", "青年", "少年", "老人",
        "黑衣人", "白衣人", "兄台", "侄孙",
        "中年人", "中年男子", "中年女子",
        # 魁梧相关
        "魁梧汉子", "魁梧身影", "魁梧老者", "魁梧男子",
        # 其他身影/人影
        "黑影", "人影", "身影",
        # 姓+老/姓+老者 类
        "许老", "张老", "李老", "王老", "陈老", "刘老",
        "许姓老者", "张姓老者", "李姓老者", "王姓老者",
        # X兄弟类
        "慕容兄弟",
        # 数字+称谓
        "6师兄", "六师兄",
        # 单字泛称
        "道士", "和尚", "僧人", "书生",
        # 衣衫类
        "黄衫女", "青衫女", "白衫女", "红衫女",
        # 描述性泛称
        "矮粗青年", "田掌柜", "破嗓子",
        # 门派+老祖类
        "燕家老祖", "鬼灵门少主",
    ]
    minor_conditions.append(Character.name.in_(always_exclude))

    # 非 is_major 才过滤的精确名称
    non_major_exclude = [
        "师兄", "师姐", "师弟", "师妹", "师叔", "师伯",
        "大师兄", "二师兄", "三师兄", "四师兄", "五师兄",
        "大师姐", "二师姐", "三师姐", "四师姐", "五师姐",
        "大师弟", "二师弟", "三师弟", "四师弟", "五师弟",
        "大师妹", "二师妹", "三师妹", "四师妹", "五师妹",
        "小师兄", "小师姐", "小师弟", "小师妹",
        "老师兄", "老师姐",
        "大长老", "二长老", "三长老", "四长老", "五长老",
        "六长老", "七长老", "八长老", "九长老", "十长老",
    ]
    minor_conditions.append(
        and_(not_(Character.is_major), Character.name.in_(non_major_exclude))
    )

    # 白名单：这些角色即使匹配泛称规则也保留
    whitelist = ["墨大夫", "张仙师"]
    q = q.where(or_(not_(or_(*minor_conditions)), Character.name.in_(whitelist)))

    # 搜索
    if search:
        alias_ids = select(CharacterAlias.character_id).where(
            CharacterAlias.alias.ilike(f"%{search}%")
        )
        q = q.where(Character.name.ilike(f"%{search}%") | Character.id.in_(alias_ids))

    # 排序：is_major 优先，然后按 first_chapter
    q = q.order_by(Character.is_major.desc(), Character.first_chapter, Character.id)
    q = q.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(q)
    characters = result.scalars().all()

    out = []
    for c in characters:
        out.append(
            CharacterBrief(
                id=c.id,
                name=c.name,
                gender=c.gender,
                first_chapter=c.first_chapter,
                is_major=c.is_major,
                aliases=[a.alias for a in c.aliases],
                realm_stages=[s.realm_stage for s in c.snapshots],
            )
        )
    return out


@router.get("/for-chat/count")
async def count_characters_for_chat(db: AsyncSession = Depends(get_pg)):
    """获取核心角色总数"""
    from sqlalchemy import distinct, or_

    has_snapshot = select(distinct(CharacterSnapshot.character_id)).where(
        CharacterSnapshot.worldline_id == WORLDLINE
    )
    has_relation_from = select(distinct(CharacterRelation.from_character_id)).where(
        CharacterRelation.worldline_id == WORLDLINE,
        CharacterRelation.is_deleted.is_(False),
    )
    has_relation_to = select(distinct(CharacterRelation.to_character_id)).where(
        CharacterRelation.worldline_id == WORLDLINE,
        CharacterRelation.is_deleted.is_(False),
    )

    result = await db.execute(
        select(func.count()).select_from(Character).where(
            Character.worldline_id == WORLDLINE,
            Character.is_deleted.is_(False),
            or_(
                Character.is_major == True,
                Character.id.in_(has_snapshot),
                Character.id.in_(has_relation_from),
                Character.id.in_(has_relation_to),
            ),
        )
    )
    return {"count": result.scalar_one()}


@router.get("/{character_id}", response_model=CharacterDetail)
async def get_character(character_id: int, db: AsyncSession = Depends(get_pg)):
    result = await db.execute(
        select(Character).where(Character.id == character_id, Character.is_deleted.is_(False))
    )
    c = result.scalar_one_or_none()
    if not c:
        from fastapi import HTTPException
        raise HTTPException(404, "Character not found")

    # relations
    rels_q = select(CharacterRelation).where(
        (CharacterRelation.from_character_id == character_id)
        | (CharacterRelation.to_character_id == character_id),
        CharacterRelation.worldline_id == WORLDLINE,
        CharacterRelation.is_deleted.is_(False),
    )
    rels_result = await db.execute(rels_q)
    rels = rels_result.scalars().all()

    # resolve character names for relations
    char_ids = set()
    for r in rels:
        char_ids.add(r.from_character_id)
        char_ids.add(r.to_character_id)
    char_ids.discard(character_id)
    names = {}
    if char_ids:
        names_result = await db.execute(
            select(Character.id, Character.name).where(Character.id.in_(char_ids))
        )
        names = dict(names_result.all())
    names[character_id] = c.name

    relations_out = [
        RelationOut(
            id=r.id,
            from_character_id=r.from_character_id,
            from_character_name=names.get(r.from_character_id),
            to_character_id=r.to_character_id,
            to_character_name=names.get(r.to_character_id),
            relation_type=r.relation_type,
            valid_from_chapter=r.valid_from_chapter,
            valid_until_chapter=r.valid_until_chapter,
            attributes=r.attributes or {},
        )
        for r in rels
    ]

    # faction memberships
    mem_q = select(FactionMembership).where(
        FactionMembership.character_id == character_id,
        FactionMembership.worldline_id == WORLDLINE,
        FactionMembership.is_deleted.is_(False),
    )
    mem_result = await db.execute(mem_q)
    mems = mem_result.scalars().all()
    faction_ids = {m.faction_id for m in mems}
    faction_names = {}
    if faction_ids:
        fn_result = await db.execute(
            select(Faction.id, Faction.name).where(Faction.id.in_(faction_ids))
        )
        faction_names = dict(fn_result.all())

    memberships_out = [
        MembershipOut(
            id=m.id,
            faction_id=m.faction_id,
            faction_name=faction_names.get(m.faction_id),
            role=m.role,
            valid_from_chapter=m.valid_from_chapter,
            valid_until_chapter=m.valid_until_chapter,
        )
        for m in mems
    ]

    # item ownerships
    own_q = select(ItemOwnership).where(
        ItemOwnership.character_id == character_id,
        ItemOwnership.worldline_id == WORLDLINE,
    )
    own_result = await db.execute(own_q)
    owns = own_result.scalars().all()
    item_ids = {o.item_id for o in owns if o.item_type == "artifact"}
    item_names = {}
    if item_ids:
        in_result = await db.execute(
            select(ItemArtifact.id, ItemArtifact.name).where(ItemArtifact.id.in_(item_ids))
        )
        item_names = dict(in_result.all())

    ownerships_out = [
        OwnershipOut(
            id=o.id,
            item_id=o.item_id,
            item_name=item_names.get(o.item_id),
            item_type=o.item_type,
            valid_from_chapter=o.valid_from_chapter,
            valid_until_chapter=o.valid_until_chapter,
            ownership_type=o.ownership_type,
        )
        for o in owns
    ]

    # realm timeline
    rt_q = select(CharacterRealmTimeline).where(
        CharacterRealmTimeline.character_id == character_id,
        CharacterRealmTimeline.worldline_id == WORLDLINE,
    ).order_by(CharacterRealmTimeline.start_chapter)
    rt_result = await db.execute(rt_q)
    rts = rt_result.scalars().all()

    return CharacterDetail(
        id=c.id,
        name=c.name,
        gender=c.gender,
        first_chapter=c.first_chapter,
        first_year=c.first_year,
        is_major=c.is_major,
        aliases=[AliasOut(id=a.id, alias=a.alias, alias_type=a.alias_type, first_chapter=a.first_chapter, last_chapter=a.last_chapter) for a in c.aliases],
        snapshots=[SnapshotOut(**{col: getattr(s, col) for col in SnapshotOut.model_fields}) for s in c.snapshots],
        relations=relations_out,
        faction_memberships=memberships_out,
        item_ownerships=ownerships_out,
        realm_timeline=[RealmTimelineOut(**{col: getattr(rt, col) for col in RealmTimelineOut.model_fields}) for rt in rts],
    )


@router.get("/{character_id}/snapshot")
async def get_snapshot_at_chapter(
    character_id: int,
    chapter: int = Query(..., description="Chapter number to get snapshot for"),
    db: AsyncSession = Depends(get_pg),
):
    """Get the character snapshot that covers a specific chapter."""
    q = select(CharacterSnapshot).where(
        CharacterSnapshot.character_id == character_id,
        CharacterSnapshot.worldline_id == WORLDLINE,
        CharacterSnapshot.chapter_start <= chapter,
    ).order_by(CharacterSnapshot.chapter_start.desc()).limit(1)

    result = await db.execute(q)
    snap = result.scalar_one_or_none()
    if not snap:
        from fastapi import HTTPException
        raise HTTPException(404, "No snapshot found for this chapter")

    return SnapshotOut(**{col: getattr(snap, col) for col in SnapshotOut.model_fields})
