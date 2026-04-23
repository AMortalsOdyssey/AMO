-- AMO time_windows 补充: 951-1261 章（人界篇最后部分）
-- 执行时间: 导入 1001-1261 章完成后
-- 执行人: jianghaibo

-- 检查现有最大章节
-- SELECT MAX(chapter_end) FROM amo.time_windows;

-- 插入新时间窗口（基于原著剧情划分）
INSERT INTO amo.time_windows (chapter_start, chapter_end, description, allowed_actions, created_at)
VALUES
  -- 灵界篇收尾 (951-1000)
  (951, 980, '灵界·太乙门覆灭', '[]'::jsonb, NOW()),
  (980, 1000, '灵界·化神圆满', '[]'::jsonb, NOW()),

  -- 通天灵宝卷 (1001-1100)
  (1001, 1030, '天南·再返故地', '[]'::jsonb, NOW()),
  (1030, 1060, '天南·血刃宗之乱', '[]'::jsonb, NOW()),
  (1060, 1100, '天南·镇海钟夺宝', '[]'::jsonb, NOW()),

  -- 纵横人界卷前半 (1101-1180)
  (1101, 1130, '乱星海·星宫秘境', '[]'::jsonb, NOW()),
  (1130, 1160, '北寒·极阴老祖', '[]'::jsonb, NOW()),
  (1160, 1180, '天南·威震修真界', '[]'::jsonb, NOW()),

  -- 纵横人界卷后半 (1181-1261)
  (1181, 1210, '星宫·大战', '[]'::jsonb, NOW()),
  (1210, 1240, '乱星海·整合势力', '[]'::jsonb, NOW()),
  (1240, 1261, '飞升·人界篇终章', '[]'::jsonb, NOW());

-- 验证插入结果
-- SELECT chapter_start, chapter_end, description
-- FROM amo.time_windows
-- WHERE chapter_start >= 951
-- ORDER BY chapter_start;
