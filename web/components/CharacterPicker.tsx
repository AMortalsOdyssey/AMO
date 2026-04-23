"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Search, X, Star, ChevronDown } from "lucide-react";
import type { CharacterBrief } from "@/lib/api";
import { getCharacterPortraitSrc } from "@/lib/characterPortraits";
import { getFeaturedCharacterIds } from "@/lib/featuredCharacters";

// 常用汉字拼音首字母映射（覆盖修仙小说常见字）
const PINYIN_MAP: Record<string, string> = {
  // A
  "阿": "A", "艾": "A", "安": "A", "昂": "A", "奥": "A", "傲": "A",
  // B
  "八": "B", "白": "B", "百": "B", "柏": "B", "班": "B", "半": "B", "邦": "B", "宝": "B", "保": "B", "暴": "B", "北": "B", "贝": "B", "本": "B", "碧": "B", "毕": "B", "边": "B", "变": "B", "彪": "B", "冰": "B", "丙": "B", "秉": "B", "炳": "B", "波": "B", "伯": "B", "博": "B", "卜": "B", "不": "B", "步": "B",
  // C
  "才": "C", "财": "C", "彩": "C", "苍": "C", "曹": "C", "草": "C", "策": "C", "岑": "C", "柴": "C", "禅": "C", "蝉": "C", "昌": "C", "长": "C", "常": "C", "嫦": "C", "超": "C", "朝": "C", "潮": "C", "尘": "C", "辰": "C", "陈": "C", "晨": "C", "成": "C", "承": "C", "城": "C", "程": "C", "澄": "C", "池": "C", "赤": "C", "冲": "C", "虫": "C", "崇": "C", "愁": "C", "初": "C", "楚": "C", "储": "C", "川": "C", "穿": "C", "传": "C", "春": "C", "纯": "C", "淳": "C", "慈": "C", "次": "C", "聪": "C", "从": "C", "丛": "C", "翠": "C", "村": "C",
  // D
  "达": "D", "大": "D", "代": "D", "丹": "D", "单": "D", "淡": "D", "当": "D", "刀": "D", "道": "D", "德": "D", "灯": "D", "等": "D", "邓": "D", "狄": "D", "嫡": "D", "帝": "D", "第": "D", "典": "D", "点": "D", "电": "D", "殿": "D", "雕": "D", "丁": "D", "顶": "D", "鼎": "D", "定": "D", "东": "D", "冬": "D", "董": "D", "洞": "D", "斗": "D", "豆": "D", "独": "D", "读": "D", "杜": "D", "度": "D", "端": "D", "段": "D", "断": "D", "敦": "D", "盾": "D", "顿": "D", "多": "D",
  // E
  "娥": "E", "峨": "E", "鹅": "E", "恩": "E", "儿": "E", "尔": "E", "耳": "E", "二": "E",
  // F
  "法": "F", "凡": "F", "樊": "F", "范": "F", "方": "F", "芳": "F", "房": "F", "飞": "F", "非": "F", "菲": "F", "肥": "F", "废": "F", "费": "F", "分": "F", "芬": "F", "奋": "F", "丰": "F", "风": "F", "封": "F", "枫": "F", "峰": "F", "锋": "F", "凤": "F", "佛": "F", "否": "F", "夫": "F", "伏": "F", "扶": "F", "芙": "F", "服": "F", "浮": "F", "符": "F", "福": "F", "府": "F", "父": "F", "付": "F", "负": "F", "附": "F", "富": "F", "傅": "F", "复": "F",
  // G
  "改": "G", "盖": "G", "甘": "G", "干": "G", "刚": "G", "钢": "G", "高": "G", "戈": "G", "歌": "G", "格": "G", "葛": "G", "隔": "G", "个": "G", "各": "G", "根": "G", "耕": "G", "更": "G", "庚": "G", "功": "G", "宫": "G", "弓": "G", "公": "G", "攻": "G", "工": "G", "龚": "G", "共": "G", "勾": "G", "钩": "G", "苟": "G", "狗": "G", "古": "G", "谷": "G", "骨": "G", "股": "G", "顾": "G", "固": "G", "故": "G", "瓜": "G", "挂": "G", "怪": "G", "关": "G", "官": "G", "冠": "G", "馆": "G", "管": "G", "贯": "G", "灌": "G", "光": "G", "广": "G", "归": "G", "龟": "G", "鬼": "G", "贵": "G", "桂": "G", "国": "G", "果": "G", "过": "G",
  // H
  "哈": "H", "海": "H", "害": "H", "含": "H", "寒": "H", "韩": "H", "罕": "H", "汉": "H", "汗": "H", "翰": "H", "航": "H", "毫": "H", "豪": "H", "浩": "H", "郝": "H", "皓": "H", "昊": "H", "禾": "H", "合": "H", "何": "H", "和": "H", "河": "H", "核": "H", "荷": "H", "贺": "H", "鹤": "H", "黑": "H", "痕": "H", "很": "H", "恒": "H", "横": "H", "衡": "H", "轰": "H", "红": "H", "宏": "H", "弘": "H", "洪": "H", "虹": "H", "鸿": "H", "侯": "H", "猴": "H", "后": "H", "厚": "H", "呼": "H", "狐": "H", "胡": "H", "湖": "H", "虎": "H", "护": "H", "花": "H", "华": "H", "滑": "H", "化": "H", "画": "H", "怀": "H", "淮": "H", "坏": "H", "欢": "H", "环": "H", "还": "H", "换": "H", "唤": "H", "焕": "H", "皇": "H", "黄": "H", "煌": "H", "惶": "H", "晃": "H", "灰": "H", "辉": "H", "回": "H", "悔": "H", "毁": "H", "会": "H", "惠": "H", "慧": "H", "昏": "H", "混": "H", "魂": "H", "浑": "H", "活": "H", "火": "H", "霍": "H", "祸": "H", "获": "H",
  // J
  "基": "J", "机": "J", "击": "J", "鸡": "J", "积": "J", "姬": "J", "激": "J", "及": "J", "吉": "J", "极": "J", "即": "J", "急": "J", "集": "J", "籍": "J", "几": "J", "己": "J", "挤": "J", "脊": "J", "计": "J", "记": "J", "纪": "J", "季": "J", "既": "J", "济": "J", "继": "J", "祭": "J", "寂": "J", "加": "J", "佳": "J", "家": "J", "嘉": "J", "甲": "J", "贾": "J", "驾": "J", "假": "J", "架": "J", "尖": "J", "坚": "J", "间": "J", "艰": "J", "兼": "J", "监": "J", "煎": "J", "剑": "J", "建": "J", "健": "J", "见": "J", "件": "J", "箭": "J", "渐": "J", "江": "J", "姜": "J", "将": "J", "蒋": "J", "奖": "J", "讲": "J", "降": "J", "交": "J", "娇": "J", "骄": "J", "焦": "J", "蕉": "J", "角": "J", "脚": "J", "搅": "J", "叫": "J", "教": "J", "阶": "J", "皆": "J", "接": "J", "街": "J", "揭": "J", "杰": "J", "结": "J", "节": "J", "劫": "J", "截": "J", "竭": "J", "解": "J", "姐": "J", "介": "J", "界": "J", "戒": "J", "届": "J", "借": "J", "巾": "J", "今": "J", "斤": "J", "金": "J", "津": "J", "筋": "J", "仅": "J", "紧": "J", "锦": "J", "谨": "J", "进": "J", "近": "J", "晋": "J", "尽": "J", "劲": "J", "荆": "J", "京": "J", "经": "J", "精": "J", "井": "J", "景": "J", "警": "J", "径": "J", "净": "J", "竞": "J", "静": "J", "敬": "J", "镜": "J", "境": "J", "九": "J", "久": "J", "酒": "J", "旧": "J", "救": "J", "就": "J", "舅": "J", "居": "J", "拘": "J", "菊": "J", "局": "J", "矩": "J", "举": "J", "巨": "J", "句": "J", "具": "J", "聚": "J", "剧": "J", "惧": "J", "据": "J", "锯": "J", "距": "J", "俱": "J", "卷": "J", "倦": "J", "决": "J", "绝": "J", "觉": "J", "爵": "J", "军": "J", "君": "J", "均": "J", "俊": "J", "峻": "J",
  // K
  "卡": "K", "开": "K", "凯": "K", "慨": "K", "刊": "K", "堪": "K", "看": "K", "康": "K", "慷": "K", "糠": "K", "考": "K", "靠": "K", "科": "K", "柯": "K", "可": "K", "克": "K", "刻": "K", "客": "K", "肯": "K", "坑": "K", "空": "K", "孔": "K", "控": "K", "口": "K", "扣": "K", "寇": "K", "枯": "K", "哭": "K", "苦": "K", "库": "K", "酷": "K", "裤": "K", "快": "K", "宽": "K", "款": "K", "狂": "K", "况": "K", "旷": "K", "矿": "K", "亏": "K", "奎": "K", "葵": "K", "魁": "K", "傀": "K", "昆": "K", "坤": "K", "捆": "K", "困": "K", "阔": "K",
  // L
  "拉": "L", "喇": "L", "辣": "L", "来": "L", "赖": "L", "兰": "L", "蓝": "L", "岚": "L", "览": "L", "懒": "L", "烂": "L", "滥": "L", "郎": "L", "狼": "L", "廊": "L", "朗": "L", "浪": "L", "捞": "L", "劳": "L", "牢": "L", "老": "L", "姥": "L", "乐": "L", "雷": "L", "蕾": "L", "磊": "L", "泪": "L", "类": "L", "累": "L", "冷": "L", "愣": "L", "黎": "L", "狸": "L", "离": "L", "梨": "L", "璃": "L", "礼": "L", "李": "L", "里": "L", "理": "L", "力": "L", "历": "L", "立": "L", "丽": "L", "利": "L", "励": "L", "例": "L", "隶": "L", "栗": "L", "荔": "L", "俐": "L", "厉": "L", "莉": "L", "吏": "L", "俪": "L", "连": "L", "廉": "L", "联": "L", "莲": "L", "脸": "L", "练": "L", "炼": "L", "链": "L", "恋": "L", "良": "L", "梁": "L", "凉": "L", "粮": "L", "两": "L", "亮": "L", "量": "L", "辽": "L", "疗": "L", "了": "L", "料": "L", "列": "L", "烈": "L", "裂": "L", "猎": "L", "林": "L", "临": "L", "琳": "L", "淋": "L", "霖": "L", "磷": "L", "鳞": "L", "凛": "L", "灵": "L", "铃": "L", "玲": "L", "零": "L", "龄": "L", "领": "L", "岭": "L", "令": "L", "另": "L", "刘": "L", "流": "L", "柳": "L", "留": "L", "六": "L", "龙": "L", "聋": "L", "隆": "L", "笼": "L", "陇": "L", "楼": "L", "搂": "L", "娄": "L", "漏": "L", "卢": "L", "炉": "L", "芦": "L", "颅": "L", "鲁": "L", "陆": "L", "录": "L", "鹿": "L", "路": "L", "露": "L", "律": "L", "绿": "L", "虑": "L", "率": "L", "滤": "L", "吕": "L", "旅": "L", "侣": "L", "履": "L", "屡": "L", "缕": "L", "乱": "L", "掠": "L", "略": "L", "伦": "L", "轮": "L", "论": "L", "罗": "L", "萝": "L", "逻": "L", "螺": "L", "洛": "L", "骆": "L", "络": "L", "落": "L",
  // M
  "妈": "M", "麻": "M", "马": "M", "玛": "M", "码": "M", "蚂": "M", "骂": "M", "埋": "M", "买": "M", "迈": "M", "麦": "M", "卖": "M", "脉": "M", "蛮": "M", "满": "M", "曼": "M", "慢": "M", "漫": "M", "芒": "M", "茫": "M", "盲": "M", "忙": "M", "莽": "M", "猫": "M", "茅": "M", "毛": "M", "矛": "M", "卯": "M", "茂": "M", "冒": "M", "帽": "M", "貌": "M", "贸": "M", "么": "M", "没": "M", "玫": "M", "枚": "M", "眉": "M", "梅": "M", "媒": "M", "每": "M", "美": "M", "妹": "M", "魅": "M", "门": "M", "萌": "M", "蒙": "M", "盟": "M", "猛": "M", "孟": "M", "梦": "M", "弥": "M", "迷": "M", "米": "M", "秘": "M", "密": "M", "蜜": "M", "眠": "M", "绵": "M", "棉": "M", "免": "M", "勉": "M", "面": "M", "苗": "M", "秒": "M", "妙": "M", "庙": "M", "灭": "M", "蔑": "M", "民": "M", "敏": "M", "名": "M", "明": "M", "鸣": "M", "命": "M", "谬": "M", "摸": "M", "模": "M", "膜": "M", "魔": "M", "抹": "M", "末": "M", "沫": "M", "莫": "M", "墨": "M", "默": "M", "漠": "M", "陌": "M", "谋": "M", "某": "M", "母": "M", "牡": "M", "亩": "M", "木": "M", "目": "M", "沐": "M", "牧": "M", "墓": "M", "幕": "M", "慕": "M", "暮": "M", "穆": "M",
  // N
  "拿": "N", "哪": "N", "纳": "N", "娜": "N", "乃": "N", "奶": "N", "耐": "N", "南": "N", "男": "N", "难": "N", "囊": "N", "脑": "N", "恼": "N", "闹": "N", "内": "N", "嫩": "N", "能": "N", "尼": "N", "泥": "N", "倪": "N", "你": "N", "逆": "N", "溺": "N", "年": "N", "念": "N", "娘": "N", "酿": "N", "鸟": "N", "捏": "N", "聂": "N", "您": "N", "宁": "N", "凝": "N", "拧": "N", "狞": "N", "牛": "N", "纽": "N", "扭": "N", "农": "N", "浓": "N", "弄": "N", "奴": "N", "努": "N", "怒": "N", "女": "N", "暖": "N", "虐": "N", "挪": "N", "诺": "N", "懦": "N",
  // O
  "欧": "O", "殴": "O", "藕": "O", "偶": "O",
  // P
  "爬": "P", "怕": "P", "拍": "P", "排": "P", "派": "P", "攀": "P", "盘": "P", "判": "P", "叛": "P", "盼": "P", "庞": "P", "旁": "P", "胖": "P", "炮": "P", "跑": "P", "泡": "P", "抛": "P", "袍": "P", "培": "P", "赔": "P", "配": "P", "佩": "P", "沛": "P", "盆": "P", "喷": "P", "朋": "P", "彭": "P", "棚": "P", "鹏": "P", "蓬": "P", "篷": "P", "膨": "P", "捧": "P", "碰": "P", "批": "P", "披": "P", "劈": "P", "皮": "P", "脾": "P", "疲": "P", "匹": "P", "屁": "P", "辟": "P", "偏": "P", "篇": "P", "片": "P", "骗": "P", "漂": "P", "飘": "P", "票": "P", "瞥": "P", "拼": "P", "贫": "P", "品": "P", "聘": "P", "平": "P", "评": "P", "凭": "P", "瓶": "P", "萍": "P", "坡": "P", "泼": "P", "颇": "P", "婆": "P", "迫": "P", "破": "P", "魄": "P", "剖": "P", "扑": "P", "铺": "P", "葡": "P", "仆": "P", "朴": "P", "浦": "P", "普": "P", "蒲": "P", "谱": "P", "瀑": "P", "菩": "P", "濮": "P",
  // Q
  "七": "Q", "妻": "Q", "柒": "Q", "齐": "Q", "奇": "Q", "祈": "Q", "崎": "Q", "骑": "Q", "棋": "Q", "旗": "Q", "歧": "Q", "岐": "Q", "乞": "Q", "企": "Q", "启": "Q", "起": "Q", "气": "Q", "弃": "Q", "汽": "Q", "契": "Q", "器": "Q", "千": "Q", "迁": "Q", "签": "Q", "前": "Q", "钱": "Q", "潜": "Q", "浅": "Q", "遣": "Q", "欠": "Q", "歉": "Q", "枪": "Q", "腔": "Q", "强": "Q", "墙": "Q", "抢": "Q", "悄": "Q", "敲": "Q", "乔": "Q", "侨": "Q", "桥": "Q", "瞧": "Q", "巧": "Q", "俏": "Q", "窍": "Q", "切": "Q", "茄": "Q", "且": "Q", "怯": "Q", "窃": "Q", "亲": "Q", "侵": "Q", "秦": "Q", "琴": "Q", "勤": "Q", "芹": "Q", "禽": "Q", "寝": "Q", "青": "Q", "轻": "Q", "清": "Q", "倾": "Q", "蜻": "Q", "情": "Q", "晴": "Q", "氰": "Q", "擎": "Q", "请": "Q", "庆": "Q", "琼": "Q", "穷": "Q", "丘": "Q", "邱": "Q", "秋": "Q", "求": "Q", "囚": "Q", "球": "Q", "区": "Q", "曲": "Q", "屈": "Q", "驱": "Q", "躯": "Q", "渠": "Q", "取": "Q", "趣": "Q", "去": "Q", "圈": "Q", "权": "Q", "全": "Q", "泉": "Q", "拳": "Q", "犬": "Q", "券": "Q", "劝": "Q", "缺": "Q", "却": "Q", "确": "Q", "雀": "Q", "裙": "Q", "群": "Q",
  // R
  "然": "R", "燃": "R", "染": "R", "让": "R", "饶": "R", "扰": "R", "惹": "R", "热": "R", "人": "R", "仁": "R", "忍": "R", "任": "R", "认": "R", "刃": "R", "韧": "R", "荣": "R", "容": "R", "溶": "R", "蓉": "R", "融": "R", "柔": "R", "肉": "R", "如": "R", "儒": "R", "茹": "R", "入": "R", "乳": "R", "辱": "R", "软": "R", "锐": "R", "瑞": "R", "芮": "R", "睿": "R", "润": "R", "若": "R", "弱": "R",
  // S
  "撒": "S", "洒": "S", "萨": "S", "塞": "S", "赛": "S", "三": "S", "伞": "S", "散": "S", "桑": "S", "丧": "S", "嫂": "S", "骚": "S", "扫": "S", "色": "S", "森": "S", "僧": "S", "杀": "S", "沙": "S", "纱": "S", "傻": "S", "砂": "S", "煞": "S", "山": "S", "删": "S", "衫": "S", "闪": "S", "陕": "S", "扇": "S", "善": "S", "擅": "S", "伤": "S", "商": "S", "裳": "S", "赏": "S", "上": "S", "尚": "S", "梢": "S", "烧": "S", "勺": "S", "少": "S", "绍": "S", "邵": "S", "哨": "S", "舌": "S", "蛇": "S", "舍": "S", "设": "S", "社": "S", "射": "S", "涉": "S", "摄": "S", "申": "S", "伸": "S", "身": "S", "深": "S", "神": "S", "沈": "S", "审": "S", "婶": "S", "甚": "S", "肾": "S", "慎": "S", "渗": "S", "升": "S", "生": "S", "声": "S", "省": "S", "圣": "S", "盛": "S", "剩": "S", "师": "S", "诗": "S", "狮": "S", "施": "S", "湿": "S", "十": "S", "石": "S", "时": "S", "识": "S", "实": "S", "食": "S", "史": "S", "使": "S", "始": "S", "驶": "S", "士": "S", "氏": "S", "世": "S", "市": "S", "示": "S", "式": "S", "事": "S", "侍": "S", "势": "S", "视": "S", "试": "S", "饰": "S", "室": "S", "释": "S", "是": "S", "逝": "S", "适": "S", "誓": "S", "收": "S", "手": "S", "守": "S", "首": "S", "寿": "S", "受": "S", "瘦": "S", "兽": "S", "书": "S", "叔": "S", "殊": "S", "抒": "S", "舒": "S", "梳": "S", "疏": "S", "蔬": "S", "输": "S", "熟": "S", "暑": "S", "属": "S", "署": "S", "术": "S", "束": "S", "述": "S", "树": "S", "竖": "S", "数": "S", "刷": "S", "耍": "S", "衰": "S", "帅": "S", "双": "S", "霜": "S", "爽": "S", "水": "S", "睡": "S", "顺": "S", "舜": "S", "瞬": "S", "说": "S", "硕": "S", "司": "S", "私": "S", "思": "S", "斯": "S", "丝": "S", "撕": "S", "死": "S", "四": "S", "寺": "S", "似": "S", "饲": "S", "肆": "S", "松": "S", "宋": "S", "送": "S", "诵": "S", "颂": "S", "搜": "S", "苏": "S", "俗": "S", "素": "S", "速": "S", "宿": "S", "诉": "S", "酸": "S", "蒜": "S", "算": "S", "虽": "S", "随": "S", "髓": "S", "隋": "S", "岁": "S", "碎": "S", "隧": "S", "孙": "S", "损": "S", "笋": "S", "缩": "S", "所": "S", "索": "S", "锁": "S",
  // T
  "他": "T", "她": "T", "它": "T", "塌": "T", "塔": "T", "踏": "T", "胎": "T", "台": "T", "太": "T", "泰": "T", "态": "T", "贪": "T", "摊": "T", "滩": "T", "坛": "T", "檀": "T", "谈": "T", "谭": "T", "弹": "T", "潭": "T", "坦": "T", "探": "T", "叹": "T", "炭": "T", "汤": "T", "唐": "T", "糖": "T", "堂": "T", "塘": "T", "膛": "T", "躺": "T", "趟": "T", "涛": "T", "滔": "T", "逃": "T", "桃": "T", "陶": "T", "淘": "T", "萄": "T", "套": "T", "特": "T", "腾": "T", "疼": "T", "藤": "T", "梯": "T", "踢": "T", "提": "T", "题": "T", "蹄": "T", "体": "T", "替": "T", "天": "T", "添": "T", "田": "T", "甜": "T", "填": "T", "挑": "T", "条": "T", "调": "T", "跳": "T", "贴": "T", "铁": "T", "帖": "T", "厅": "T", "听": "T", "亭": "T", "庭": "T", "停": "T", "艇": "T", "挺": "T", "通": "T", "同": "T", "铜": "T", "童": "T", "桶": "T", "统": "T", "痛": "T", "偷": "T", "头": "T", "投": "T", "透": "T", "凸": "T", "秃": "T", "突": "T", "图": "T", "徒": "T", "涂": "T", "途": "T", "土": "T", "吐": "T", "兔": "T", "团": "T", "推": "T", "腿": "T", "退": "T", "吞": "T", "屯": "T", "托": "T", "拖": "T", "脱": "T", "驼": "T", "妥": "T", "拓": "T",
  // W
  "挖": "W", "娃": "W", "瓦": "W", "袜": "W", "歪": "W", "外": "W", "弯": "W", "湾": "W", "完": "W", "玩": "W", "顽": "W", "丸": "W", "宛": "W", "挽": "W", "晚": "W", "碗": "W", "万": "W", "汪": "W", "王": "W", "亡": "W", "网": "W", "往": "W", "旺": "W", "忘": "W", "望": "W", "危": "W", "威": "W", "微": "W", "巍": "W", "韦": "W", "为": "W", "围": "W", "违": "W", "唯": "W", "惟": "W", "维": "W", "伟": "W", "伪": "W", "尾": "W", "委": "W", "卫": "W", "未": "W", "位": "W", "味": "W", "畏": "W", "胃": "W", "喂": "W", "魏": "W", "慰": "W", "蔚": "W", "温": "W", "文": "W", "闻": "W", "蚊": "W", "纹": "W", "稳": "W", "问": "W", "翁": "W", "窝": "W", "我": "W", "卧": "W", "握": "W", "乌": "W", "污": "W", "屋": "W", "无": "W", "吴": "W", "芜": "W", "吾": "W", "梧": "W", "武": "W", "五": "W", "午": "W", "舞": "W", "务": "W", "物": "W", "误": "W", "悟": "W", "雾": "W",
  // X
  "夕": "X", "西": "X", "吸": "X", "希": "X", "析": "X", "息": "X", "牺": "X", "悉": "X", "惜": "X", "稀": "X", "溪": "X", "熙": "X", "膝": "X", "锡": "X", "熄": "X", "嬉": "X", "习": "X", "席": "X", "袭": "X", "媳": "X", "喜": "X", "戏": "X", "系": "X", "细": "X", "隙": "X", "虾": "X", "瞎": "X", "峡": "X", "狭": "X", "侠": "X", "霞": "X", "下": "X", "吓": "X", "夏": "X", "仙": "X", "先": "X", "掀": "X", "鲜": "X", "纤": "X", "咸": "X", "贤": "X", "弦": "X", "嫌": "X", "闲": "X", "衔": "X", "显": "X", "险": "X", "县": "X", "现": "X", "线": "X", "限": "X", "宪": "X", "陷": "X", "献": "X", "腺": "X", "乡": "X", "相": "X", "香": "X", "箱": "X", "湘": "X", "详": "X", "祥": "X", "翔": "X", "享": "X", "响": "X", "想": "X", "向": "X", "项": "X", "巷": "X", "象": "X", "像": "X", "橡": "X", "消": "X", "宵": "X", "萧": "X", "逍": "X", "潇": "X", "销": "X", "小": "X", "晓": "X", "孝": "X", "笑": "X", "效": "X", "校": "X", "肖": "X", "啸": "X", "些": "X", "鞋": "X", "协": "X", "写": "X", "斜": "X", "携": "X", "邪": "X", "泄": "X", "泻": "X", "谢": "X", "屑": "X", "懈": "X", "蟹": "X", "心": "X", "辛": "X", "欣": "X", "新": "X", "薪": "X", "馨": "X", "信": "X", "星": "X", "腥": "X", "猩": "X", "刑": "X", "行": "X", "形": "X", "型": "X", "醒": "X", "幸": "X", "杏": "X", "性": "X", "姓": "X", "兄": "X", "凶": "X", "胸": "X", "雄": "X", "熊": "X", "休": "X", "修": "X", "羞": "X", "朽": "X", "秀": "X", "袖": "X", "绣": "X", "嗅": "X", "须": "X", "虚": "X", "需": "X", "徐": "X", "许": "X", "叙": "X", "序": "X", "绪": "X", "续": "X", "蓄": "X", "絮": "X", "宣": "X", "玄": "X", "悬": "X", "旋": "X", "漩": "X", "选": "X", "癣": "X", "眩": "X", "绚": "X", "靴": "X", "薛": "X", "学": "X", "穴": "X", "雪": "X", "血": "X", "勋": "X", "熏": "X", "寻": "X", "巡": "X", "旬": "X", "询": "X", "循": "X", "训": "X", "讯": "X", "逊": "X", "迅": "X", "巽": "X", "殉": "X", "汛": "X",
  // Y
  "压": "Y", "呀": "Y", "鸦": "Y", "鸭": "Y", "牙": "Y", "芽": "Y", "崖": "Y", "涯": "Y", "雅": "Y", "亚": "Y", "咽": "Y", "烟": "Y", "淹": "Y", "盐": "Y", "严": "Y", "言": "Y", "岩": "Y", "延": "Y", "炎": "Y", "沿": "Y", "研": "Y", "颜": "Y", "阎": "Y", "眼": "Y", "演": "Y", "厌": "Y", "宴": "Y", "艳": "Y", "验": "Y", "焰": "Y", "雁": "Y", "燕": "Y", "央": "Y", "殃": "Y", "秧": "Y", "杨": "Y", "羊": "Y", "阳": "Y", "洋": "Y", "仰": "Y", "养": "Y", "痒": "Y", "样": "Y", "漾": "Y", "妖": "Y", "腰": "Y", "邀": "Y", "摇": "Y", "遥": "Y", "瑶": "Y", "姚": "Y", "窑": "Y", "谣": "Y", "咬": "Y", "药": "Y", "要": "Y", "耀": "Y", "钥": "Y", "爷": "Y", "也": "Y", "野": "Y", "冶": "Y", "业": "Y", "叶": "Y", "页": "Y", "夜": "Y", "液": "Y", "一": "Y", "伊": "Y", "衣": "Y", "医": "Y", "依": "Y", "仪": "Y", "宜": "Y", "姨": "Y", "移": "Y", "遗": "Y", "疑": "Y", "乙": "Y", "已": "Y", "以": "Y", "矣": "Y", "蚁": "Y", "倚": "Y", "椅": "Y", "义": "Y", "亿": "Y", "忆": "Y", "艺": "Y", "议": "Y", "异": "Y", "译": "Y", "易": "Y", "役": "Y", "益": "Y", "逸": "Y", "意": "Y", "溢": "Y", "毅": "Y", "翼": "Y", "翌": "Y", "因": "Y", "音": "Y", "阴": "Y", "殷": "Y", "吟": "Y", "银": "Y", "引": "Y", "饮": "Y", "隐": "Y", "瘾": "Y", "印": "Y", "应": "Y", "英": "Y", "樱": "Y", "婴": "Y", "鹰": "Y", "迎": "Y", "盈": "Y", "营": "Y", "蝇": "Y", "赢": "Y", "影": "Y", "颖": "Y", "硬": "Y", "映": "Y", "哟": "Y", "拥": "Y", "庸": "Y", "雍": "Y", "永": "Y", "泳": "Y", "勇": "Y", "涌": "Y", "用": "Y", "优": "Y", "忧": "Y", "幽": "Y", "悠": "Y", "尤": "Y", "由": "Y", "油": "Y", "游": "Y", "友": "Y", "有": "Y", "又": "Y", "右": "Y", "幼": "Y", "诱": "Y", "于": "Y", "予": "Y", "余": "Y", "鱼": "Y", "娱": "Y", "渔": "Y", "愉": "Y", "愚": "Y", "舆": "Y", "雨": "Y", "与": "Y", "宇": "Y", "羽": "Y", "禹": "Y", "玉": "Y", "郁": "Y", "育": "Y", "狱": "Y", "浴": "Y", "欲": "Y", "域": "Y", "遇": "Y", "喻": "Y", "御": "Y", "裕": "Y", "预": "Y", "豫": "Y", "誉": "Y", "鸢": "Y", "元": "Y", "员": "Y", "园": "Y", "原": "Y", "圆": "Y", "援": "Y", "缘": "Y", "源": "Y", "远": "Y", "苑": "Y", "愿": "Y", "怨": "Y", "院": "Y", "月": "Y", "岳": "Y", "越": "Y", "跃": "Y", "粤": "Y", "悦": "Y", "阅": "Y", "云": "Y", "匀": "Y", "允": "Y", "陨": "Y", "孕": "Y", "运": "Y", "蕴": "Y", "韵": "Y",
  // Z
  "杂": "Z", "灾": "Z", "栽": "Z", "宰": "Z", "载": "Z", "再": "Z", "在": "Z", "咱": "Z", "暂": "Z", "赞": "Z", "赃": "Z", "葬": "Z", "遭": "Z", "糟": "Z", "凿": "Z", "早": "Z", "枣": "Z", "澡": "Z", "躁": "Z", "噪": "Z", "造": "Z", "灶": "Z", "皂": "Z", "则": "Z", "泽": "Z", "择": "Z", "责": "Z", "贼": "Z", "怎": "Z", "增": "Z", "憎": "Z", "曾": "Z", "赠": "Z", "渣": "Z", "扎": "Z", "眨": "Z", "炸": "Z", "诈": "Z", "摘": "Z", "斋": "Z", "宅": "Z", "窄": "Z", "债": "Z", "沾": "Z", "粘": "Z", "盏": "Z", "斩": "Z", "展": "Z", "占": "Z", "战": "Z", "站": "Z", "张": "Z", "章": "Z", "彰": "Z", "掌": "Z", "涨": "Z", "丈": "Z", "杖": "Z", "帐": "Z", "账": "Z", "障": "Z", "招": "Z", "昭": "Z", "找": "Z", "沼": "Z", "赵": "Z", "照": "Z", "罩": "Z", "兆": "Z", "肇": "Z", "召": "Z", "遮": "Z", "折": "Z", "哲": "Z", "者": "Z", "蔗": "Z", "这": "Z", "浙": "Z", "珍": "Z", "斟": "Z", "真": "Z", "甄": "Z", "诊": "Z", "枕": "Z", "阵": "Z", "振": "Z", "镇": "Z", "震": "Z", "争": "Z", "征": "Z", "挣": "Z", "狰": "Z", "峥": "Z", "睁": "Z", "蒸": "Z", "拯": "Z", "整": "Z", "正": "Z", "政": "Z", "证": "Z", "郑": "Z", "症": "Z", "之": "Z", "支": "Z", "芝": "Z", "枝": "Z", "知": "Z", "织": "Z", "脂": "Z", "肢": "Z", "蜘": "Z", "执": "Z", "侄": "Z", "直": "Z", "值": "Z", "职": "Z", "植": "Z", "殖": "Z", "止": "Z", "只": "Z", "址": "Z", "旨": "Z", "纸": "Z", "指": "Z", "至": "Z", "志": "Z", "制": "Z", "治": "Z", "质": "Z", "致": "Z", "置": "Z", "帜": "Z", "峙": "Z", "智": "Z", "滞": "Z", "稚": "Z", "挚": "Z", "掷": "Z", "中": "Z", "忠": "Z", "终": "Z", "钟": "Z", "衷": "Z", "种": "Z", "肿": "Z", "众": "Z", "重": "Z", "舟": "Z", "周": "Z", "州": "Z", "洲": "Z", "粥": "Z", "轴": "Z", "宙": "Z", "咒": "Z", "皱": "Z", "骤": "Z", "朱": "Z", "珠": "Z", "株": "Z", "蛛": "Z", "诸": "Z", "猪": "Z", "竹": "Z", "逐": "Z", "烛": "Z", "主": "Z", "煮": "Z", "嘱": "Z", "瞩": "Z", "助": "Z", "住": "Z", "注": "Z", "驻": "Z", "柱": "Z", "祝": "Z", "著": "Z", "筑": "Z", "铸": "Z", "抓": "Z", "爪": "Z", "专": "Z", "砖": "Z", "转": "Z", "撰": "Z", "赚": "Z", "庄": "Z", "装": "Z", "壮": "Z", "状": "Z", "撞": "Z", "幢": "Z", "追": "Z", "坠": "Z", "缀": "Z", "准": "Z", "拙": "Z", "捉": "Z", "桌": "Z", "琢": "Z", "灼": "Z", "卓": "Z", "着": "Z", "浊": "Z", "酌": "Z", "茁": "Z", "兹": "Z", "姿": "Z", "资": "Z", "滋": "Z", "子": "Z", "紫": "Z", "仔": "Z", "籽": "Z", "姊": "Z", "字": "Z", "自": "Z", "宗": "Z", "综": "Z", "棕": "Z", "踪": "Z", "总": "Z", "纵": "Z", "走": "Z", "奏": "Z", "租": "Z", "足": "Z", "族": "Z", "阻": "Z", "组": "Z", "祖": "Z", "诅": "Z", "钻": "Z", "嘴": "Z", "最": "Z", "醉": "Z", "罪": "Z", "尊": "Z", "遵": "Z", "昨": "Z", "左": "Z", "佐": "Z", "作": "Z", "坐": "Z", "座": "Z", "做": "Z",
};

/** 获取名字的拼音首字母，如果无法识别则返回 # */
function getPinyinInitial(name: string): string {
  const firstChar = name[0];
  // 如果是英文字母直接返回大写
  if (/[a-zA-Z]/.test(firstChar)) {
    return firstChar.toUpperCase();
  }
  return PINYIN_MAP[firstChar] || "#";
}

/** 获取整个名字的拼音首字母串，用于搜索匹配 */
function getPinyinInitials(name: string): string {
  return name
    .split("")
    .map((char) => {
      if (/[a-zA-Z]/.test(char)) return char.toUpperCase();
      return PINYIN_MAP[char] || "";
    })
    .join("")
    .toLowerCase();
}

interface Props {
  characters: CharacterBrief[];
  featuredCharacterIds?: number[];
  selected: number | null;
  onSelect: (id: number) => void;
}

export function CharacterPicker({ characters, featuredCharacterIds, selected, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const resolvedFeaturedIds = useMemo(
    () => featuredCharacterIds ?? getFeaturedCharacterIds(characters),
    [characters, featuredCharacterIds]
  );
  const featuredOrder = useMemo(
    () => new Map(resolvedFeaturedIds.map((id, index) => [id, index])),
    [resolvedFeaturedIds]
  );
  const featuredIdSet = useMemo(() => new Set(resolvedFeaturedIds), [resolvedFeaturedIds]);

  const selectedChar = characters.find((c) => c.id === selected);

  const closePicker = () => {
    setOpen(false);
    setSearch("");
  };

  // Filter and group characters
  const { featured, majorOthers, grouped } = useMemo(() => {
    const query = search.toLowerCase().trim();
    const filtered = query
      ? characters.filter((c) => {
          // 支持：汉字名、别名、拼音首字母（如 "xy" 匹配 "萧炎"）
          const nameMatch = c.name.toLowerCase().includes(query);
          const aliasMatch = c.aliases.some((alias) => alias.toLowerCase().includes(query));
          const pinyinMatch = getPinyinInitials(c.name).includes(query);
          return nameMatch || aliasMatch || pinyinMatch;
        })
      : characters;

    const featured = filtered
      .filter((c) => featuredIdSet.has(c.id))
      .sort((a, b) => (featuredOrder.get(a.id) ?? 9999) - (featuredOrder.get(b.id) ?? 9999));
    const majorOthers = filtered.filter((c) => c.is_major && !featuredIdSet.has(c.id));
    const others = filtered.filter((c) => !c.is_major && !featuredIdSet.has(c.id));

    // Group by pinyin initial
    const grouped: Record<string, CharacterBrief[]> = {};
    for (const c of others) {
      const initial = getPinyinInitial(c.name);
      if (!grouped[initial]) grouped[initial] = [];
      grouped[initial].push(c);
    }

    // Sort each group by name
    for (const key of Object.keys(grouped)) {
      grouped[key].sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
    }

    return { featured, majorOthers, grouped };
  }, [characters, featuredIdSet, featuredOrder, search]);

  // Close on click outside
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        closePicker();
      }
    };
    if (open) {
      document.addEventListener("mousedown", handleClick);
      return () => document.removeEventListener("mousedown", handleClick);
    }
  }, [open]);

  // Keyboard shortcut
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
      if (e.key === "Escape" && open) {
        closePicker();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [open]);

  const handleSelect = (id: number) => {
    onSelect(id);
    closePicker();
  };

  const sortedGroups = Object.keys(grouped).sort((a, b) => {
    // # 放最后
    if (a === "#") return 1;
    if (b === "#") return -1;
    return a.localeCompare(b);
  });
  const totalFiltered = featured.length + majorOthers.length + Object.values(grouped).flat().length;

  return (
    <div ref={containerRef} className="relative">
      {/* Trigger button */}
      <button
        onClick={() => {
          if (open) {
            closePicker();
          } else {
            setOpen(true);
          }
        }}
        className="amo-input flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2 text-left text-sm transition-colors hover:border-white/12"
      >
        <span className={selectedChar ? "text-white/88" : "text-white/42"}>
          {selectedChar ? (
            <span className="flex items-center gap-2">
              <CharacterAvatar character={selectedChar} size="sm" />
              {featuredIdSet.has(selectedChar.id) && <span className="text-base leading-none">🔥</span>}
              <span>{selectedChar.name}</span>
              {!featuredIdSet.has(selectedChar.id) && selectedChar.is_major && (
                <Star className="h-3 w-3 fill-emerald-300 text-emerald-300" />
              )}
            </span>
          ) : (
            "选择角色..."
          )}
        </span>
        <div className="flex items-center gap-2">
          <kbd className="hidden items-center gap-0.5 rounded border border-white/8 bg-white/4 px-1.5 py-0.5 text-[10px] text-white/42 sm:inline-flex">
            ⌘K
          </kbd>
          <ChevronDown className={`h-4 w-4 text-white/42 transition-transform ${open ? "rotate-180" : ""}`} />
        </div>
      </button>

      {/* Dropdown panel */}
      {open && (
        <div className="amo-panel-strong absolute left-0 right-0 top-full z-50 mt-2 overflow-hidden rounded-2xl">
          {/* Search input */}
          <div className="border-b border-white/6 p-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/36" />
              <input
                ref={inputRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索角色名、别名或拼音首字母..."
                className="amo-input w-full rounded-xl py-2 pl-8 pr-8 text-sm"
              />
              {search && (
                <button
                  onClick={() => setSearch("")}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-white/36 hover:text-white/84"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>

          {/* Character list */}
          <div ref={listRef} className="max-h-80 overflow-y-auto">
            {totalFiltered === 0 ? (
              <div className="px-3 py-8 text-center text-sm text-white/40">
                未找到匹配的角色
              </div>
            ) : (
              <>
                {/* Featured characters section */}
                {featured.length > 0 && (
                  <div>
                    <div className="flex items-center gap-1.5 border-b border-white/6 bg-emerald-300/8 px-3 py-1.5 text-xs font-medium text-emerald-100/88">
                      <span>🔥</span>
                      热门角色
                    </div>
                    {featured.map((c) => (
                      <CharacterItem
                        key={c.id}
                        character={c}
                        badge="featured"
                        isSelected={c.id === selected}
                        onSelect={handleSelect}
                      />
                    ))}
                  </div>
                )}

                {/* Other major characters section */}
                {majorOthers.length > 0 && (
                  <div>
                    <div className="flex items-center gap-1.5 border-b border-white/6 bg-white/4 px-3 py-1.5 text-xs font-medium text-white/68">
                      <Star className="h-3 w-3" />
                      其他主要角色
                    </div>
                    {majorOthers.map((c) => (
                      <CharacterItem
                        key={c.id}
                        character={c}
                        badge="major"
                        isSelected={c.id === selected}
                        onSelect={handleSelect}
                      />
                    ))}
                  </div>
                )}

                {/* Grouped characters */}
                {sortedGroups.map((letter) => (
                  <div key={letter}>
                    <div className="border-b border-white/6 bg-white/3 px-3 py-1.5 text-xs font-medium text-white/34">
                      {letter}
                    </div>
                    {grouped[letter].map((c) => (
                      <CharacterItem
                        key={c.id}
                        character={c}
                        badge="default"
                        isSelected={c.id === selected}
                        onSelect={handleSelect}
                      />
                    ))}
                  </div>
                ))}
              </>
            )}
          </div>

          {/* Footer hint */}
          <div className="border-t border-white/6 px-3 py-2 text-[11px] text-white/32">
            共 {characters.length} 个角色
            {search && ` · 匹配 ${totalFiltered} 个`}
          </div>
        </div>
      )}
    </div>
  );
}

function CharacterAvatar({
  character,
  size = "md",
}: {
  character: CharacterBrief;
  size?: "sm" | "md";
}) {
  const portraitSrc = getCharacterPortraitSrc(character);
  const sizeClass = size === "sm" ? "h-7 w-7 text-xs" : "h-9 w-9 text-sm";

  return (
    <span className={`amo-picker-avatar ${sizeClass}`}>
      {portraitSrc ? (
        <img
          src={portraitSrc}
          alt={character.name}
          className="h-full w-full object-cover"
        />
      ) : (
        <span>{character.name.slice(0, 1)}</span>
      )}
    </span>
  );
}

function CharacterItem({
  character,
  badge,
  isSelected,
  onSelect,
}: {
  character: CharacterBrief;
  badge: "featured" | "major" | "default";
  isSelected: boolean;
  onSelect: (id: number) => void;
}) {
  return (
    <button
      onClick={() => onSelect(character.id)}
      className={`w-full px-3 py-2 text-left text-sm transition-colors flex items-center gap-2 ${
        isSelected
          ? "bg-emerald-300/10 text-white"
          : "text-white/82 hover:bg-white/4"
      }`}
    >
      <CharacterAvatar character={character} />
      {badge === "featured" && <span className="text-base leading-none flex-shrink-0">🔥</span>}
      <span className="truncate">{character.name}</span>
      {badge === "major" && (
        <Star className="h-3 w-3 flex-shrink-0 fill-emerald-300 text-emerald-300" />
      )}
      {isSelected && (
        <span className="ml-auto text-[10px] text-emerald-200/72">当前</span>
      )}
    </button>
  );
}
