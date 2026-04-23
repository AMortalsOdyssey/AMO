import type { CharacterBrief } from "@/lib/api";
import { POSTER_FEATURED_CHARACTER_NAMES } from "@/lib/characterPortraits";

export const FEATURED_CHARACTER_NAMES = [
  "青易居士",
  "蛮胡子",
  "金魁",
  ...POSTER_FEATURED_CHARACTER_NAMES,
  "韩立",
  "南宫婉",
  "墨大夫",
  "厉飞雨",
  "墨彩环",
  "银月",
  "元瑶",
  "紫灵仙子",
  "玄骨",
  "极阴",
  "风希",
  "凌玉灵",
  "大衍神君",
  "慕沛灵",
  "冰凤",
  "向之礼",
  "李化元",
  "辛如音",
  "齐云霄",
  "董萱儿",
  "陈巧倩",
  "王蝉",
  "燕如嫣",
  "南陇侯",
  "令狐老祖",
  "文思月",
  "汪凝",
  "万天明",
  "六道极圣",
  "凤仙子",
  "白瑶怡",
  "圭灵",
  "玲珑",
  "云露老魔",
  "红拂仙姑",
  "曲魂",
  "余子童",
  "张铁",
  "钟灵道",
  "吕洛",
  "天星双圣",
  "范夫人",
  "田琴儿",
  "曹梦容",
  "金蛟王",
  "古魔",
  "乌丑",
  "宋蒙",
  "云天啸",
  "温青",
  "王天古",
  "寒骊上人",
  "菡云芝",
  "妍丽",
  "雷万鹤",
  "范静梅",
  "红拂",
] as const;

export const FEATURED_CHARACTER_LIMIT = 50;

export function pickFeaturedCharacters(pool: CharacterBrief[]) {
  const selected: CharacterBrief[] = [];
  const seen = new Set<number>();

  for (const featuredName of FEATURED_CHARACTER_NAMES) {
    const match = pool.find(
      (character) =>
        !seen.has(character.id) &&
        (character.name === featuredName || character.aliases.includes(featuredName)),
    );
    if (!match) continue;
    selected.push(match);
    seen.add(match.id);
  }

  for (const character of pool) {
    if (seen.has(character.id)) continue;
    selected.push(character);
    seen.add(character.id);
    if (selected.length >= FEATURED_CHARACTER_LIMIT) break;
  }

  return selected.slice(0, FEATURED_CHARACTER_LIMIT);
}

export function getFeaturedCharacterIds(pool: CharacterBrief[]) {
  return pickFeaturedCharacters(pool).map((character) => character.id);
}
