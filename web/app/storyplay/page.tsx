"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, type CharacterBrief } from "@/lib/api";
import { getFeaturedCharacterIds } from "@/lib/featuredCharacters";
import { CharacterPicker } from "@/components/CharacterPicker";

const API_BASE = "/api";
const CHARACTER_PAGE_SIZE = 500;

interface TimeWindowItem {
  id: number;
  chapter_start: number;
  chapter_end: number;
  start_anchor: string | null;
  end_anchor: string | null;
  description: string | null;
}

function mergeCharacters(existing: CharacterBrief[], incoming: CharacterBrief[]) {
  const merged = new Map<number, CharacterBrief>();

  for (const character of existing) {
    merged.set(character.id, character);
  }
  for (const character of incoming) {
    merged.set(character.id, character);
  }

  return Array.from(merged.values()).sort((a, b) => {
    if (a.is_major !== b.is_major) return Number(b.is_major) - Number(a.is_major);
    if (a.first_chapter !== b.first_chapter) return a.first_chapter - b.first_chapter;
    return a.id - b.id;
  });
}

async function loadAllStoryplayCharacters() {
  const { count } = await apiFetch<{ count: number }>("/characters/count");
  const totalPages = Math.max(1, Math.ceil(count / CHARACTER_PAGE_SIZE));

  const batches = await Promise.all(
    Array.from({ length: totalPages }, (_, index) =>
      apiFetch<CharacterBrief[]>(`/characters?page=${index + 1}&page_size=${CHARACTER_PAGE_SIZE}`)
    )
  );

  return mergeCharacters([], batches.flat());
}

export default function StoryplayEntryPage() {
  const router = useRouter();
  const [characters, setCharacters] = useState<CharacterBrief[]>([]);
  const [featuredCharacterIds, setFeaturedCharacterIds] = useState<number[]>([]);
  const [windows, setWindows] = useState<TimeWindowItem[]>([]);
  const [selectedChar, setSelectedChar] = useState<number | null>(null);
  const [selectedWindow, setSelectedWindow] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  const [loadingCharacters, setLoadingCharacters] = useState(true);
  const [characterError, setCharacterError] = useState("");
  const [fallbackQuery, setFallbackQuery] = useState("");
  const [fallbackResults, setFallbackResults] = useState<CharacterBrief[]>([]);
  const [fallbackSearching, setFallbackSearching] = useState(false);
  const [fallbackError, setFallbackError] = useState("");
  const featuredCharacterIdSet = useMemo(() => new Set(featuredCharacterIds), [featuredCharacterIds]);

  useEffect(() => {
    let cancelled = false;

    async function loadInitialData() {
      setLoadingCharacters(true);
      setCharacterError("");

      try {
        const [allCharacters, allWindows, homepageCharacterPool] = await Promise.all([
          loadAllStoryplayCharacters(),
          apiFetch<TimeWindowItem[]>("/storyplay/time-windows"),
          apiFetch<CharacterBrief[]>("/characters/for-chat?page_size=500"),
        ]);

        if (cancelled) return;
        setCharacters(allCharacters);
        setWindows(allWindows);
        setFeaturedCharacterIds(getFeaturedCharacterIds(homepageCharacterPool));
      } catch (error) {
        console.error("Failed to load storyplay entry data:", error);
        if (!cancelled) {
          setCharacterError("角色列表加载失败，请刷新后重试。");
        }
      } finally {
        if (!cancelled) {
          setLoadingCharacters(false);
        }
      }
    }

    void loadInitialData();

    return () => {
      cancelled = true;
    };
  }, []);

  // 选角色时重置窗口选择
  const handleCharSelect = (charId: number | null) => {
    setSelectedChar(charId);
    setSelectedWindow(null);
  };

  const handleFallbackSearch = async () => {
    const query = fallbackQuery.trim();
    if (!query) {
      setFallbackResults([]);
      setFallbackError("");
      return;
    }

    setFallbackSearching(true);
    setFallbackError("");

    try {
      const params = new URLSearchParams({
        page_size: "50",
        search: query,
        exclude_minor: "false",
      });
      const results = await apiFetch<CharacterBrief[]>(`/characters?${params.toString()}`);
      setFallbackResults(results);
      if (results.length === 0) {
        setFallbackError("没有搜到匹配角色，可以换角色名或别名再试一次。");
      }
    } catch (error) {
      console.error("Failed to search storyplay characters:", error);
      setFallbackError("角色搜索失败，请稍后重试。");
    } finally {
      setFallbackSearching(false);
    }
  };

  const handleFallbackSelect = (character: CharacterBrief) => {
    setCharacters((prev) => mergeCharacters(prev, [character]));
    handleCharSelect(character.id);
    setFallbackQuery(character.name);
    setFallbackResults([]);
    setFallbackError("");
  };

  // 根据角色出场章节过滤可用的时间窗口
  const selectedCharData =
    characters.find((c) => c.id === selectedChar)
    || fallbackResults.find((c) => c.id === selectedChar);
  const filteredWindows = selectedCharData
    ? windows.filter((w) => w.chapter_end >= selectedCharData.first_chapter)
    : windows;

  const handleStart = async () => {
    if (!selectedChar || !selectedWindow) return;
    setStarting(true);
    try {
      const resp = await fetch(`${API_BASE}/storyplay/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character_id: selectedChar, time_window_id: selectedWindow }),
      });
      if (!resp.ok) {
        throw new Error(`Storyplay start failed: ${resp.status} ${await resp.text()}`);
      }
      const data = await resp.json();
      // Encode session info in URL params
      const params = new URLSearchParams({
        character_id: String(selectedChar),
        character_name: data.character.name,
        realm: data.character.realm_stage,
        chapter: String(data.chapter_context),
        window_start: String(data.time_window.chapter_start),
        window_end: String(data.time_window.chapter_end),
      });
      router.push(`/storyplay/${data.worldline_id}?${params}`);
    } catch (e) {
      console.error("Failed to start storyplay:", e);
    }
    setStarting(false);
  };

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <div className="mb-10 text-center">
        <h1 className="mb-2 text-3xl font-semibold text-white/92">演绎模式</h1>
        <p className="text-white/48">选择角色和时间窗口，在原著锚点之间创造你的故事</p>
      </div>

      {/* Character Select */}
      <div className="mb-8">
        <label className="mb-2 block text-sm text-white/58">选择角色</label>
        {loadingCharacters ? (
          <div className="amo-panel rounded-2xl px-4 py-3 text-white/42">
            角色加载中...
          </div>
        ) : characterError ? (
          <div className="w-full bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 text-sm text-red-300">
            {characterError}
          </div>
        ) : (
          <>
            <CharacterPicker
              characters={characters}
              featuredCharacterIds={featuredCharacterIds}
              selected={selectedChar}
              onSelect={(id) => handleCharSelect(id)}
            />
            <div className="mt-2 text-xs text-white/42">
              已加载 {characters.length} 个可演绎角色，支持角色名、别名和拼音首字母搜索。
            </div>

            <div className="amo-panel mt-3 rounded-2xl p-3">
              <div className="mb-2 text-xs text-white/58">
                找不到角色时，可在这里兜底搜索原著人物
              </div>
              <div className="flex gap-2">
                <input
                  value={fallbackQuery}
                  onChange={(e) => setFallbackQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void handleFallbackSearch();
                    }
                  }}
                  placeholder="输入角色名或别名，例如 墨大夫 / 南宫婉"
                  className="amo-input flex-1 rounded-xl px-3 py-2 text-sm"
                />
                <button
                  type="button"
                  onClick={() => void handleFallbackSearch()}
                  disabled={!fallbackQuery.trim() || fallbackSearching}
                  className="amo-button-secondary rounded-xl px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {fallbackSearching ? "搜索中..." : "搜索"}
                </button>
              </div>

              {fallbackError && (
                <div className="mt-2 text-xs text-emerald-200">{fallbackError}</div>
              )}

              {fallbackResults.length > 0 && (
                <div className="mt-3 max-h-56 overflow-y-auto space-y-1">
                  {fallbackResults.map((character) => {
                    const isFeatured = featuredCharacterIdSet.has(character.id);

                    return (
                      <button
                        key={character.id}
                        type="button"
                        onClick={() => handleFallbackSelect(character)}
                        className="amo-panel block w-full rounded-xl px-3 py-2 text-left text-sm text-white/84 transition-colors hover:border-emerald-200/18 hover:bg-white/4"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <span className="truncate flex items-center gap-1.5">
                            {isFeatured && <span className="text-base leading-none">🔥</span>}
                            <span className="truncate">{character.name}</span>
                            {!isFeatured && character.is_major && (
                              <span className="text-emerald-300">★</span>
                            )}
                          </span>
                          <span className="text-xs text-white/42">第{character.first_chapter}章</span>
                        </div>
                        {character.aliases.length > 0 && (
                          <div className="mt-1 truncate text-xs text-white/38">
                            别名：{character.aliases.join("、")}
                          </div>
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Time Window Select */}
      <div className="mb-8">
        <label className="mb-2 block text-sm text-white/58">
          选择时间窗口
          {selectedCharData && (
            <span className="ml-2 text-white/34">
              （{selectedCharData.name} 第{selectedCharData.first_chapter}章出场，显示可用窗口）
            </span>
          )}
        </label>
        {filteredWindows.length === 0 && selectedChar ? (
          <div className="py-4 text-sm text-white/34">该角色没有可用的时间窗口</div>
        ) : (
        <div className="space-y-2">
          {filteredWindows.map((w) => (
            <div key={w.id} className="relative pt-5">
              {selectedWindow === w.id && selectedChar && (
                <div className="pointer-events-none absolute right-3 top-0 z-10">
                  <button
                    type="button"
                    onClick={handleStart}
                    disabled={starting}
                    className="pointer-events-auto inline-flex items-center gap-2 rounded-full border border-emerald-200/20 bg-[#1a2524]/96 px-4 py-2 text-xs font-semibold tracking-[0.12em] text-emerald-100 shadow-[0_10px_28px_rgba(0,0,0,0.22)] ring-1 ring-white/6 backdrop-blur-xl transition-all duration-200 hover:-translate-y-0.5 hover:border-emerald-200/30 hover:bg-[#20302f] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <span className="inline-flex h-2 w-2 rounded-full bg-emerald-300 shadow-[0_0_10px_rgba(110,231,183,0.7)]" />
                    {starting ? "创建中..." : "开始演绎"}
                  </button>
                </div>
              )}

              <button
                type="button"
                onClick={() => setSelectedWindow(w.id)}
                className={`w-full text-left p-4 rounded-lg border transition-colors ${
                  selectedWindow === w.id
                    ? "border-emerald-300/18 bg-emerald-300/10 text-white"
                    : "amo-panel text-white/82 hover:border-emerald-200/18 hover:bg-white/4"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">第{w.chapter_start}~{w.chapter_end}章</span>
                  <span className="text-xs text-white/42">{w.chapter_end - w.chapter_start}章跨度</span>
                </div>
                <div className="mt-1 text-xs text-white/38">
                  {w.start_anchor && w.end_anchor
                    ? `${w.start_anchor} → ${w.end_anchor}`
                    : w.description || `第${w.chapter_start}~${w.chapter_end}章`}
                </div>
              </button>
            </div>
          ))}
        </div>
        )}
      </div>

      {/* Start Button */}
      <button
        onClick={handleStart}
        disabled={!selectedChar || !selectedWindow || starting || loadingCharacters}
        className="amo-button-primary w-full rounded-2xl py-3 font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50"
      >
        {starting ? "创建世界线中..." : "开始演绎"}
      </button>
    </div>
  );
}
