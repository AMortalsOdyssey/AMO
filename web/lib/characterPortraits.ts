import type { CharacterBrief } from "@/lib/api";

const POSTER_PORTRAIT_LABELS = [
  "孙火",
  "韩立",
  "柳眉",
  "慕沛灵",
  "宋玉",
  "梅凝",
  "金奎",
  "尸魈",
  "温天仁",
  "燕如嫣",
  "银月",
  "紫灵",
  "文思月",
  "甲越老",
  "菡云芝",
  "公孙杏",
  "范静梅",
  "卓如婷",
  "辛如音",
  "元瑶",
  "云道友",
  "妍丽",
  "侍女",
  "凌玉灵",
  "萧诧",
  "风希",
  "王婵",
  "乌丑",
  "南陇侯",
  "火云童子",
  "吕洛",
  "极阴",
  "蛮胡子",
  "妙鹤",
  "木藤子",
  "程天坤",
  "温天人",
  "青易",
  "万天明",
  "王天古",
  "天吾子",
  "啼魂兽",
  "南宫婉",
  "墨彩环",
  "向之礼",
  "刘靖",
  "董萱儿",
  "李化元",
  "钟吾",
  "张铁",
  "万小山",
  "厉飞雨",
  "红拂",
  "陈巧倩",
  "令狐老祖",
  "云露",
] as const;

export const POSTER_FEATURED_CHARACTER_NAMES = [...POSTER_PORTRAIT_LABELS];

const PORTRAIT_SRC_BY_NAME = new Map<string, string>(
  POSTER_PORTRAIT_LABELS.map((name, index) => [normalizeName(name), `/portraits/poster/${String(index + 1).padStart(2, "0")}.webp`]),
);

function normalizeName(name: string) {
  return name.trim();
}

function registerPortraitAliases(name: string, aliases: string[]) {
  const src = PORTRAIT_SRC_BY_NAME.get(normalizeName(name));
  if (!src) return;

  for (const alias of aliases) {
    PORTRAIT_SRC_BY_NAME.set(normalizeName(alias), src);
  }
}

registerPortraitAliases("尸魈", ["天魔煞尸"]);
registerPortraitAliases("紫灵", ["紫灵仙子"]);
registerPortraitAliases("卓如婷", ["范夫人"]);
registerPortraitAliases("萧诧", ["玄骨上人", "玄骨"]);
registerPortraitAliases("王婵", ["王蝉"]);
registerPortraitAliases("极阴", ["极阴祖师"]);
registerPortraitAliases("啼魂兽", ["啼魂"]);
registerPortraitAliases("红拂", ["红拂仙姑"]);
registerPortraitAliases("青易", ["青易居士"]);
registerPortraitAliases("金奎", ["金魁"]);

type PortraitCharacter = Pick<CharacterBrief, "name" | "aliases">;

export function getCharacterPortraitSrc(character: PortraitCharacter) {
  const names = [character.name, ...character.aliases];
  for (const name of names) {
    const src = PORTRAIT_SRC_BY_NAME.get(normalizeName(name));
    if (src) return src;
  }
  return null;
}
