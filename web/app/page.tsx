"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { apiFetch, type CharacterBrief, type Stats, type SearchResult } from "@/lib/api";
import { captureEvent } from "@/lib/analytics";
import FeaturedCharacterMarquee from "@/components/featured-character-marquee";
import { getCharacterPortraitSrc } from "@/lib/characterPortraits";
import { pickFeaturedCharacters } from "@/lib/featuredCharacters";

const HIDDEN_ALIAS_EXACT = new Set([
  "此女",
  "此人",
  "前辈",
  "师姐",
  "师弟",
  "师兄",
  "小师妹",
  "少女",
  "少妇",
  "美少妇",
  "老夫",
  "老鬼",
  "老魔",
  "本上人",
  "本岛主",
  "本圣祖",
  "逆徒",
  "家祖",
  "令孙",
  "隐匿之人",
  "老四",
]);

const CURATED_CHARACTER_DISPLAY: Record<string, { aliases?: string[]; realmStage?: string }> = {
  韩立: {
    aliases: ["狡猾的小子"],
    realmStage: "化神初期巅峰",
  },
};

function sanitizeAliases(aliases: string[]) {
  return aliases.filter((alias) => {
    const normalized = alias.trim();
    if (!normalized) return false;
    if (HIDDEN_ALIAS_EXACT.has(normalized)) return false;
    if (normalized.includes("少妇")) return false;
    if (normalized.endsWith("女子") || normalized.endsWith("修士") || normalized.endsWith("老者")) return false;
    return true;
  });
}

function pickDisplayRealmStage(realmStages: string[]) {
  const cleaned = realmStages
    .map((stage) => stage.trim())
    .filter((stage) => stage && stage.toLowerCase() !== "unknown");

  const preferred = [...cleaned].reverse().find((stage) => {
    return !["目标", "未成功", "未达成", "计划", "讨论", "伪装", "表面", "收敛"].some((token) => stage.includes(token));
  });

  return preferred || cleaned.at(-1);
}

export default function Home() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [characters, setCharacters] = useState<CharacterBrief[]>([]);
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const hasTrackedSearchFocusRef = useRef(false);
  const pendingSearchFocusSourceRef = useRef<"input" | "focus_button" | null>(null);

  useEffect(() => {
    apiFetch<Stats>("/stats").then(setStats);
    apiFetch<CharacterBrief[]>("/characters/for-chat?page_size=500").then((data) => {
      setCharacters(pickFeaturedCharacters(data));
    });
  }, []);

  useEffect(() => {
    const t = setTimeout(async () => {
      if (!search.trim()) {
        setSearchResults([]);
        setSearching(false);
        return;
      }
      setSearching(true);
      const data = await apiFetch<{ results: SearchResult[] }>(`/search?q=${encodeURIComponent(search)}&limit=10`);
      setSearchResults(data.results);
      if (data.results.length === 0) {
        captureEvent("homepage_search_empty_result", {
          query: search.trim(),
        });
      }
      setSearching(false);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const TYPE_LABELS: Record<string, string> = {
    character: "角色", faction: "势力", item: "法宝", technique: "功法", location: "地点",
  };

  return (
    <div className="relative mx-auto max-w-6xl px-4 py-10">
      <div className="pointer-events-none absolute left-[-5rem] top-2 h-44 w-44 rounded-full bg-white/5 blur-3xl" />
      <div className="pointer-events-none absolute right-[-3rem] top-16 h-40 w-40 rounded-full bg-emerald-200/7 blur-3xl" />
      <div className="pointer-events-none absolute inset-x-10 top-72 h-px bg-gradient-to-r from-transparent via-white/8 to-transparent" />

      {/* Hero */}
      <div className="mb-12 text-center">
        <div className="mb-4 inline-flex rounded-full border border-white/8 bg-white/4 px-4 py-1 text-[11px] uppercase tracking-[0.3em] text-white/52">
          A Mortal&apos;s Odyssey
        </div>
        <h1 className="amo-title-gradient mb-3 text-4xl font-semibold tracking-[0.14em] md:text-5xl">
          AMO · A Mortal&apos;s Odyssey
        </h1>
        <p className="mx-auto max-w-3xl text-lg text-white/62">
          资料索引 · 关系图谱 · 角色对话 · 交互演绎
        </p>
      </div>

      {/* Brand Note */}
      <section className="mb-12">
        <div className="amo-panel amo-panel-interactive mx-auto max-w-4xl rounded-3xl p-6 md:p-7">
          <div className="grid gap-6 md:grid-cols-[minmax(0,1.1fr)_minmax(0,1.4fr)] md:items-start">
            <div className="flex flex-col gap-3">
              <div className="amo-kicker inline-flex w-fit items-center rounded-full px-3 py-1 text-xs font-medium uppercase tracking-[0.2em]">
                Project Naming
              </div>
              <div className="flex flex-col gap-1">
                <p className="text-xs uppercase tracking-[0.2em] text-white/34">AMO</p>
                <h2 className="text-2xl font-semibold text-white/92 text-balance">A Mortal&apos;s Odyssey</h2>
              </div>
              <p className="max-w-md text-sm leading-6 text-white/62">
                AMO，取自 A Mortal&apos;s Odyssey，意指一段自凡俗视角出发、穿越漫长时间与未知边界的远征。
              </p>
            </div>

            <div className="flex flex-col gap-4 text-sm leading-6 text-white/74">
              <p>
                <span className="font-medium text-emerald-200">“Odyssey”</span>
                源自希腊史诗，指向一段漫长、艰险而近乎宿命的远征。
              </p>
              <p>
                在这里，它对应的是角色、势力与时间线在漫长修真叙事中的穿行、选择与代价，
                也是一个世界在时间推进中不断展开的层层回响。
              </p>
              <p className="text-white/42">
                AMO 所承载的，是一个围绕成长、因果与世界演化展开的长期故事空间。
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Search */}
      <div className="mx-auto mb-12 max-w-3xl relative">
        <div className="amo-input-wrap amo-search-shell">
          <input
            ref={searchInputRef}
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onFocus={() => {
              if (hasTrackedSearchFocusRef.current) return;
              const source = pendingSearchFocusSourceRef.current ?? "input";
              pendingSearchFocusSourceRef.current = null;
              hasTrackedSearchFocusRef.current = true;
              captureEvent("homepage_search_focused", { source });
            }}
            placeholder="搜索角色、势力、法宝、功法..."
            className="amo-input w-full rounded-full px-7 py-5 pr-24 text-base md:px-8 md:py-6 md:pr-28 md:text-[1.08rem]"
          />
          <button
            type="button"
            onClick={() => {
              pendingSearchFocusSourceRef.current = "focus_button";
              searchInputRef.current?.focus();
            }}
            aria-label="聚焦搜索"
            className="amo-search-action"
          >
            <span aria-hidden="true">↑</span>
          </button>
        </div>
        {searchResults.length > 0 && (
          <div className="amo-panel-strong absolute top-full z-50 mt-3 max-h-80 w-full overflow-y-auto rounded-[1.75rem]">
            {searchResults.map((r) => (
              <Link
                key={`${r.type}-${r.id}`}
                href={r.type === "character" ? `/character/${r.id}` : "#"}
                onClick={() => {
                  captureEvent("homepage_search_result_clicked", {
                    query: search.trim(),
                    result_type: r.type,
                    result_id: r.id,
                    result_name: r.name,
                  });
                }}
                className="amo-list-item block border-b border-white/6 px-4 py-3 last:border-0"
              >
                <span className="mr-2 rounded-full border border-white/8 bg-white/4 px-2 py-0.5 text-xs text-white/64">
                  {TYPE_LABELS[r.type] || r.type}
                </span>
                <span className="text-white/88">{r.name}</span>
                {r.detail && <span className="ml-2 text-sm text-white/40">{r.detail}</span>}
              </Link>
            ))}
          </div>
        )}
        {searching && <div className="amo-search-status">搜索中...</div>}
      </div>

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-3 md:grid-cols-5 gap-3 mb-12">
          {[
            { label: "角色", value: stats.characters },
            { label: "势力", value: stats.factions },
            { label: "事件", value: stats.events },
            { label: "法宝", value: stats.items },
            { label: "已导入章节", value: stats.chapters_imported },
          ].map((s) => (
            <div key={s.label} className="amo-panel amo-panel-interactive rounded-2xl p-4 text-center">
              <div className="text-2xl font-semibold text-white/92">{s.value}</div>
              <div className="mt-1 text-xs text-white/42">{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-12">
        <Link
          href="/graph-v3"
          onClick={() => captureEvent("homepage_quick_action_clicked", { target: "graph_v3", href: "/graph-v3" })}
          className="amo-panel amo-panel-interactive block rounded-3xl p-6"
        >
          <div className="mb-2 text-xl font-semibold text-white/90">3D 关系图谱</div>
          <div className="text-sm text-white/46">进入新的 3D 力导图视图，探索角色与实体关系网络</div>
        </Link>
        <Link
          href="/chat"
          onClick={() => captureEvent("homepage_quick_action_clicked", { target: "chat", href: "/chat" })}
          className="amo-panel amo-panel-interactive block rounded-3xl p-6"
        >
          <div className="mb-2 text-xl font-semibold text-white/90">角色对话</div>
          <div className="text-sm text-white/46">选择角色和时间点，沉浸式对话体验</div>
        </Link>
        <Link
          href="/storyplay"
          onClick={() => captureEvent("homepage_quick_action_clicked", { target: "storyplay", href: "/storyplay" })}
          className="amo-panel amo-panel-interactive block rounded-3xl p-6"
        >
          <div className="mb-2 text-xl font-semibold text-white/90">剧情演绎</div>
          <div className="text-sm text-white/46">在既定时间锚点之间选择角色与时间窗口，展开平行故事</div>
        </Link>
        <Link
          href="/timeline"
          onClick={() => captureEvent("homepage_quick_action_clicked", { target: "timeline", href: "/timeline" })}
          className="amo-panel amo-panel-interactive block rounded-3xl p-6"
        >
          <div className="mb-2 text-xl font-semibold text-white/90">时间线</div>
          <div className="text-sm text-white/46">纵览全局事件，追踪角色成长历程</div>
        </Link>
      </div>

      {/* Featured Characters */}
      <div className="mb-4">
        <h2 className="text-xl font-semibold text-white/90">热门角色</h2>
      </div>
      <FeaturedCharacterMarquee
        characters={characters.map((character) => {
          const override = CURATED_CHARACTER_DISPLAY[character.name];
          return {
            id: character.id,
            name: character.name,
            aliases: override?.aliases ?? sanitizeAliases(character.aliases),
            realmStage: override?.realmStage ?? pickDisplayRealmStage(character.realm_stages),
            portraitSrc: getCharacterPortraitSrc(character),
          };
        })}
        onCharacterClick={(character) => {
          captureEvent("featured_character_clicked", {
            character_id: character.id,
            character_name: character.name,
            source: "homepage_marquee",
          });
        }}
      />
    </div>
  );
}
