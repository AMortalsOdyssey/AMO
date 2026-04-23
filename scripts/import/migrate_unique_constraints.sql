-- Migration: 修改关系表唯一约束，支持 valid_from_chapter 的 LEAST() 语义
-- 目的：将 valid_from_chapter 从唯一键中移除，让同一关系可以合并而非创建多条记录
-- 执行前请备份数据！

-- ============================================================
-- 1. character_relations
-- ============================================================

-- 删除旧约束（包含 valid_from_chapter）
ALTER TABLE character_relations
DROP CONSTRAINT IF EXISTS character_relations_from_character_id_to_character_id_relat_key;

-- 创建新约束（不含 valid_from_chapter）
ALTER TABLE character_relations
ADD CONSTRAINT character_relations_unique_relation
UNIQUE (from_character_id, to_character_id, relation_type, worldline_id);

-- 添加 updated_at 列（如果不存在）
ALTER TABLE character_relations ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- ============================================================
-- 2. faction_memberships
-- ============================================================

-- 删除旧约束
ALTER TABLE faction_memberships
DROP CONSTRAINT IF EXISTS faction_memberships_character_id_faction_id_valid_from_chap_key;

-- 创建新约束
ALTER TABLE faction_memberships
ADD CONSTRAINT faction_memberships_unique_membership
UNIQUE (character_id, faction_id, worldline_id);

-- 添加 updated_at 列（如果不存在）
ALTER TABLE faction_memberships ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- ============================================================
-- 3. item_ownerships
-- ============================================================

-- 删除旧约束
ALTER TABLE item_ownerships
DROP CONSTRAINT IF EXISTS item_ownerships_character_id_item_id_item_type_valid_from__key;

-- 创建新约束
ALTER TABLE item_ownerships
ADD CONSTRAINT item_ownerships_unique_ownership
UNIQUE (character_id, item_id, item_type, worldline_id);

-- 添加 updated_at 列（如果不存在）
ALTER TABLE item_ownerships ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- ============================================================
-- 4. 数据清理（可选）
-- 如果已有重复数据，需要先合并，保留最早的 valid_from_chapter
-- ============================================================

-- 合并 character_relations 重复数据（保留最小 valid_from_chapter）
-- WITH duplicates AS (
--     SELECT
--         from_character_id, to_character_id, relation_type, worldline_id,
--         MIN(valid_from_chapter) as earliest_chapter,
--         MIN(id) as keep_id
--     FROM character_relations
--     GROUP BY from_character_id, to_character_id, relation_type, worldline_id
--     HAVING COUNT(*) > 1
-- )
-- UPDATE character_relations cr
-- SET valid_from_chapter = d.earliest_chapter
-- FROM duplicates d
-- WHERE cr.id = d.keep_id;

-- DELETE FROM character_relations cr
-- WHERE EXISTS (
--     SELECT 1 FROM character_relations cr2
--     WHERE cr2.from_character_id = cr.from_character_id
--       AND cr2.to_character_id = cr.to_character_id
--       AND cr2.relation_type = cr.relation_type
--       AND cr2.worldline_id = cr.worldline_id
--       AND cr2.id < cr.id
-- );
