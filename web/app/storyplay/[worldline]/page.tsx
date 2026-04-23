"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { captureEvent } from "@/lib/analytics";

const API_BASE = "/api";

interface Chapter {
  chapter_order: number;
  title: string;
  content: string;
  description?: string;
  canon_chapter: number | null;
  present_characters?: string[];
  canon_divergence?: boolean;
}

interface Consequence {
  rule_name: string;
  consequence_type: string;
  severity: number;
  description: string;
  delay_type: string;
  trigger_condition?: string;
  status: string;
  trigger_reason?: string;
}

interface LoreCheck {
  verdict: string;
  explanation: string;
  alternative?: string;
  anchor_conflict?: boolean;
  present_characters?: string[];
}

interface WorldlineResponse {
  chapters?: Chapter[];
  consequences?: Record<string, unknown>[];
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseSseEvent(rawEvent: string) {
  const dataLines = rawEvent
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart());

  if (dataLines.length === 0) return null;

  try {
    return JSON.parse(dataLines.join("\n"));
  } catch {
    return null;
  }
}

function consumeSseBuffer(buffer: string, flush: boolean = false) {
  const chunks = buffer.split(/\r?\n\r?\n/);
  const remainder = flush ? "" : (chunks.pop() ?? "");
  const events = flush ? chunks.concat(remainder ? [remainder] : []) : chunks;
  return { events, remainder };
}

const ACTION_TYPES = [
  { type: "cultivate", label: "修炼" },
  { type: "explore", label: "探索" },
  { type: "combat", label: "战斗" },
  { type: "social", label: "社交" },
  { type: "trade", label: "交易" },
  { type: "custom", label: "自定义" },
];

const SEVERITY_COLORS = [
  "", "text-green-400", "text-green-400", "text-yellow-400", "text-yellow-400",
  "text-orange-400", "text-orange-400", "text-red-400", "text-red-400",
  "text-red-500", "text-red-600",
];

function StoryplayInner() {
  const params = useParams();
  const searchParams = useSearchParams();
  const worldlineId = params.worldline as string;

  const characterName = searchParams.get("character_name") || "角色";
  const characterId = Number(searchParams.get("character_id")) || 0;
  const realm = searchParams.get("realm") || "未知";
  const windowStart = Number(searchParams.get("window_start")) || 1;
  const windowEnd = Number(searchParams.get("window_end")) || 250;
  const initChapter = Number(searchParams.get("chapter")) || windowStart;

  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [consequences, setConsequences] = useState<Consequence[]>([]);
  const [input, setInput] = useState("");
  const [actionType, setActionType] = useState("custom");
  const [submitting, setSubmitting] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [streamError, setStreamError] = useState<string | null>(null);
  const [streamRecoveryPending, setStreamRecoveryPending] = useState(false);
  const [lastCheck, setLastCheck] = useState<LoreCheck | null>(null);
  const [chapterContext, setChapterContext] = useState(initChapter);
  const [canonDivergence, setCanonDivergence] = useState(false);
  const chaptersEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const hasTrackedViewRef = useRef(false);

  const appendChapter = useCallback((chapter: Chapter) => {
    setChapters((prev) => {
      if (prev.some((item) => item.chapter_order === chapter.chapter_order)) {
        return prev;
      }
      return [...prev, chapter];
    });
    setChapterContext((current) => Math.max(current, (chapter.canon_chapter ?? current) + 1));
  }, []);

  const applyWorldlineData = useCallback((data: WorldlineResponse) => {
    const nextChapters = data.chapters || [];
    setChapters(nextChapters);
    setChapterContext(initChapter + nextChapters.length);
    setCanonDivergence(nextChapters.some((chapter) => chapter.canon_divergence));
    setConsequences(
      (data.consequences || []).map((c) => ({
        rule_name: typeof c.consequence_type === "string" ? c.consequence_type : "未知",
        consequence_type: c.consequence_type as string,
        severity: c.severity as number,
        description: c.description as string,
        delay_type: c.trigger_type as string,
        trigger_condition: c.trigger_condition as string | undefined,
        status: c.status as string,
        trigger_reason: c.trigger_reason as string | undefined,
      }))
    );
    return nextChapters;
  }, [initChapter]);

  const fetchWorldlineData = useCallback(async () => {
    const response = await fetch(`${API_BASE}/storyplay/worldline/${worldlineId}`);
    if (!response.ok) {
      throw new Error(`Failed to load worldline: ${response.status}`);
    }
    return (await response.json()) as WorldlineResponse;
  }, [worldlineId]);

  const loadWorldline = useCallback(async () => {
    return applyWorldlineData(await fetchWorldlineData());
  }, [applyWorldlineData, fetchWorldlineData]);

  const waitForPersistedChapter = useCallback(async (previousChapterCount: number) => {
    for (let attempt = 0; attempt < 20; attempt += 1) {
      try {
        const data = await fetchWorldlineData();
        const nextChapters = data.chapters || [];
        if (nextChapters.length > previousChapterCount) {
          return data;
        }
      } catch {
        // ignore transient refresh errors while waiting for background persistence
      }

      if (attempt < 19) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
    }

    return null;
  }, [fetchWorldlineData]);

  const revealRecoveredChapter = useCallback(async (partialContent: string, finalChapter: Chapter) => {
    if (!partialContent || !finalChapter.content.startsWith(partialContent)) {
      return;
    }

    const missingTail = finalChapter.content.slice(partialContent.length);
    if (!missingTail) {
      return;
    }

    const step = Math.max(16, Math.ceil(missingTail.length / 20));
    for (let i = step; i < missingTail.length; i += step) {
      setStreamingText(partialContent + missingTail.slice(0, i));
      await sleep(24);
    }
    setStreamingText(finalChapter.content);
    await sleep(80);
  }, []);

  // Load existing worldline data
  useEffect(() => {
    loadWorldline().catch(() => {});
  }, [loadWorldline]);

  useEffect(() => {
    if (hasTrackedViewRef.current) return;
    hasTrackedViewRef.current = true;
    captureEvent("storyplay_worldline_viewed", {
      worldline_id: worldlineId,
      character_id: characterId,
      character_name: characterName,
      realm,
      chapter_context: initChapter,
      window_start: windowStart,
      window_end: windowEnd,
    });
  }, [characterId, characterName, initChapter, realm, windowEnd, windowStart, worldlineId]);

  useEffect(() => {
    chaptersEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chapters, streamingText]);

  // 流式提交行动
  const submitActionStream = useCallback(async (forceSubmit: boolean = false) => {
    if (!input.trim() || submitting) return;
    const actionDetail = input.trim();
    const previousChapterCount = chapters.length;
    setSubmitting(true);
    setStreaming(true);
    setStreamingText("");
    setStreamError(null);
    setStreamRecoveryPending(false);
    setLastCheck(null);

    let narrativeContent = "";
    let chapterData: Chapter | null = null;

    try {
      captureEvent("storyplay_action_submitted", {
        worldline_id: worldlineId,
        character_id: characterId,
        character_name: characterName,
        action_type: actionType,
        action_detail_length: actionDetail.length,
        chapter_context: chapterContext,
        force_submit: forceSubmit,
      });

      const response = await fetch(`${API_BASE}/storyplay/action/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          worldline_id: worldlineId,
          character_id: characterId,
          action_type: actionType,
          action_detail: actionDetail,
          chapter_context: chapterContext,
          force: forceSubmit,
        }),
      });
      if (!response.ok) {
        throw new Error(`Storyplay stream failed: ${response.status} ${await response.text()}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("Storyplay stream body is empty");
      }
      const decoder = new TextDecoder();
      let buffer = "";
      const handleEvent = (data: Record<string, unknown>) => {
        if (data.type === "lore_check") {
          const loreCheck = data.data as LoreCheck;
          setLastCheck(loreCheck);
          captureEvent("storyplay_lore_check_received", {
            worldline_id: worldlineId,
            character_id: characterId,
            action_type: actionType,
            verdict: loreCheck.verdict,
            anchor_conflict: Boolean(loreCheck.anchor_conflict),
            has_alternative: Boolean(loreCheck.alternative),
          });
          // 如果建议替代方案且不是强制提交，停止流式
          if (loreCheck.verdict === "suggest_alternative" && !forceSubmit) {
            setStreaming(false);
            setSubmitting(false);
            setTimeout(() => inputRef.current?.focus(), 0);
            return true;
          }
        } else if (data.type === "narrative") {
          const content = typeof data.content === "string" ? data.content : "";
          narrativeContent += content;
          setStreamingText(narrativeContent);
        } else if (data.type === "chapter") {
          const payload = data.data as Record<string, unknown>;
          chapterData = {
            chapter_order: Number(payload.chapter_order),
            title: String(payload.title ?? `第${chapters.length + 1}章`),
            content: String(payload.content ?? narrativeContent),
            description: typeof payload.description === "string" ? payload.description : undefined,
            canon_chapter: chapterContext,
            present_characters: Array.isArray(payload.present_characters)
              ? payload.present_characters.filter((item): item is string => typeof item === "string")
              : undefined,
            canon_divergence: Boolean(payload.canon_divergence),
          };
          if (payload.canon_divergence) {
            setCanonDivergence(true);
          }
          captureEvent("storyplay_chapter_generated", {
            worldline_id: worldlineId,
            character_id: characterId,
            action_type: actionType,
            chapter_order: chapterData.chapter_order,
            canon_chapter: chapterData.canon_chapter,
            content_length: chapterData.content.length,
            canon_divergence: Boolean(chapterData.canon_divergence),
          });
          appendChapter(chapterData);
        } else if (data.type === "error") {
          console.error("Stream error:", data.message);
          setStreamError(typeof data.message === "string" ? data.message : "演绎生成失败，请重试。");
        } else if (data.type === "consequences") {
          const payload = Array.isArray(data.data) ? (data.data as Consequence[]) : [];
          if (payload.length) {
            setConsequences((prev) => [...prev, ...payload]);
          }
        } else if (data.type === "done") {
          if (chapterData) {
            setInput("");
            setStreamingText("");
            setStreamRecoveryPending(false);
          } else if (narrativeContent) {
            setStreamError("演绎文本已生成，但章节落库确认失败；当前内容已保留，请重试一次。");
          }
        }

        return false;
      };

      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
        const { events, remainder } = consumeSseBuffer(buffer, done);
        buffer = remainder;

        for (const rawEvent of events) {
          const data = parseSseEvent(rawEvent);
          if (!data) continue;
          if (handleEvent(data)) {
            return;
          }
        }

        if (done) break;
      }
    } catch (e) {
      if (!(narrativeContent && !chapterData)) {
        console.error("Stream action failed:", e);
      }
      captureEvent("storyplay_action_failed", {
        worldline_id: worldlineId,
        character_id: characterId,
        character_name: characterName,
        action_type: actionType,
        force_submit: forceSubmit,
        error_message: e instanceof Error ? e.message : "unknown_error",
      });
      if (narrativeContent) {
        if (chapterData) {
          appendChapter(chapterData);
          setInput("");
          setStreamingText("");
          setStreamRecoveryPending(false);
          setStreamError(null);
        } else {
          setStreaming(false);
          setStreamRecoveryPending(true);
          const persisted = await waitForPersistedChapter(previousChapterCount);
          setStreamRecoveryPending(false);
          if (persisted) {
            const persistedChapters = persisted.chapters || [];
            const recoveredChapter = persistedChapters[previousChapterCount];
            if (recoveredChapter) {
              await revealRecoveredChapter(narrativeContent, recoveredChapter);
            }
            applyWorldlineData(persisted);
            setInput("");
            setStreamingText("");
            setStreamError(null);
          } else {
            setStreamError(e instanceof Error ? e.message : "演绎生成失败，请重试。");
          }
        }
      } else {
        setStreamRecoveryPending(false);
        setStreamError(e instanceof Error ? e.message : "演绎生成失败，请重试。");
      }
    }

    setStreaming(false);
    setSubmitting(false);
    setTimeout(() => inputRef.current?.focus(), 0);
  }, [actionType, applyWorldlineData, appendChapter, chapterContext, chapters.length, characterId, characterName, input, submitting, waitForPersistedChapter, worldlineId, revealRecoveredChapter]);

  // 强制继续（忽略锚点冲突）
  const forceSubmit = () => {
    captureEvent("storyplay_force_continue_clicked", {
      worldline_id: worldlineId,
      character_id: characterId,
      character_name: characterName,
      action_type: actionType,
    });
    submitActionStream(true);
  };

  // 采纳建议
  const acceptSuggestion = () => {
    if (lastCheck?.alternative) {
      captureEvent("storyplay_suggestion_accepted", {
        worldline_id: worldlineId,
        character_id: characterId,
        character_name: characterName,
        action_type: actionType,
      });
      setInput(lastCheck.alternative);
      setLastCheck(null);
      inputRef.current?.focus();
    }
  };

  return (
    <div className="flex h-[calc(100vh-4rem)]">
      {/* Left: Status Panel */}
      <div className="amo-panel-strong flex w-64 flex-col overflow-y-auto rounded-r-3xl border-r border-white/6">
        <div className="border-b border-white/6 p-4">
          <div className="text-lg font-semibold text-white/92">{characterName}</div>
          <div className="mt-1 text-xs text-white/44">境界: {realm}</div>
          <div className="text-xs text-white/44">章节: 第{chapterContext}章</div>
          <div className="text-xs text-white/44">窗口: 第{windowStart}~{windowEnd}章</div>
          <div className="mt-1 font-mono text-xs text-white/28">{worldlineId}</div>
          {canonDivergence && (
            <div className="mt-2 text-xs px-2 py-1 rounded bg-orange-900/30 border border-orange-700/30 text-orange-400">
              ⚠️ 世界线已偏离原著
            </div>
          )}
        </div>

        {/* Consequences */}
        <div className="flex-1 p-4">
          <div className="mb-2 text-xs uppercase tracking-[0.22em] text-white/36">
            代价列表 ({consequences.length})
          </div>
          {consequences.length === 0 ? (
            <div className="text-xs text-white/28">暂无代价</div>
          ) : (
            <div className="space-y-2">
              {consequences.map((c, i) => (
                <div key={i} className="rounded-xl border border-white/6 bg-white/4 p-2 text-xs">
                  <div className={`font-medium ${SEVERITY_COLORS[c.severity] || "text-emerald-50/82"}`}>
                    {c.rule_name} [{c.severity}/10]
                  </div>
                  <div className="mt-0.5 text-white/42">{c.description}</div>
                  <div className="mt-0.5 flex items-center gap-1 text-white/32">
                    <span className={c.status === "triggered" ? "text-rose-300" : "text-white/42"}>
                      {c.status === "triggered" ? "已触发" : c.status === "pending" ? "待触发" : c.status}
                    </span>
                    {c.delay_type !== "immediate" && c.status === "pending" && (
                      <span className="text-white/28">
                        ({c.delay_type === "years_later" ? "延迟" : c.delay_type === "realm_trigger" ? "境界" : c.delay_type})
                      </span>
                    )}
                  </div>
                  {c.trigger_condition && c.status === "pending" && (
                    <div className="mt-0.5 text-[10px] text-white/28">
                      触发条件: {c.trigger_condition.slice(0, 50)}...
                    </div>
                  )}
                  {c.trigger_reason && c.status === "triggered" && (
                    <div className="text-orange-400/80 mt-0.5 text-[10px]">
                      触发原因: {c.trigger_reason}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Right: Main Area */}
      <div className="flex flex-1 flex-col">
        {/* Chapters Display */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {chapters.length === 0 && !streaming && !streamingText && (
            <div className="mt-20 text-center text-white/34">
              <div className="mb-2 text-lg text-white/86">「{characterName}」的世界线</div>
              <div className="text-sm">在下方输入你的行动，开始创造故事</div>
            </div>
          )}
          {chapters.map((ch) => (
            <div key={ch.chapter_order} className="max-w-2xl mx-auto">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs text-emerald-200/72">{ch.title}</span>
                <span className="text-[10px] text-white/28">{ch.content.length}字</span>
                {ch.canon_divergence && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-900/30 text-orange-400 border border-orange-700/30">
                    偏离原著
                  </span>
                )}
              </div>
              <div className="text-sm leading-relaxed whitespace-pre-wrap text-white/82">
                {ch.content}
              </div>
              {ch.present_characters && ch.present_characters.length > 0 && (
                <div className="mt-2 text-xs text-white/32">
                  在场角色: {ch.present_characters.join("、")}
                </div>
              )}
            </div>
          ))}
          {/* 流式输出中的内容 */}
          {streamingText && (
            <div className="max-w-2xl mx-auto">
              <div className="mb-2 text-xs text-emerald-200/72">
                第{chapters.length + 1}章（{streaming ? `生成中... ${streamingText.length}字` : streamRecoveryPending ? "连接中断，等待后台保存..." : "待确认"}）
              </div>
              <div className="text-sm leading-relaxed whitespace-pre-wrap text-white/82">
                {streamingText}
                {streaming && <span className="animate-pulse">▋</span>}
              </div>
            </div>
          )}
          <div ref={chaptersEndRef} />
        </div>

        {/* Lore Guard Feedback */}
        {streamError && (
          <div className="mx-6 mb-2 rounded-lg border border-red-800/30 bg-red-900/20 p-3 text-sm text-red-400">
            <div className="font-medium">演绎输出未完整落盘</div>
            <div className="mt-1 text-xs opacity-80">{streamError}</div>
          </div>
        )}

        {lastCheck && (
          <div className={`mx-6 mb-2 p-3 rounded-lg text-sm ${
            lastCheck.verdict === "allow"
              ? "bg-green-900/20 border border-green-800/30 text-green-400"
              : lastCheck.verdict === "allow_with_consequence"
              ? "bg-yellow-900/20 border border-yellow-800/30 text-yellow-400"
              : "bg-red-900/20 border border-red-800/30 text-red-400"
          }`}>
            <div className="font-medium">
              {lastCheck.verdict === "allow" ? "✓ 行为合理" :
               lastCheck.verdict === "allow_with_consequence" ? "⚠ 行为有代价" :
               "✗ 建议调整"}
            </div>
            <div className="text-xs mt-1 opacity-80">{lastCheck.explanation}</div>
            {lastCheck.alternative && lastCheck.verdict === "suggest_alternative" && (
              <div className="mt-2 flex gap-2">
                <button
                  onClick={acceptSuggestion}
                  className="amo-button-secondary rounded-xl px-3 py-1.5 text-xs transition-colors"
                >
                  采纳建议
                </button>
                <button
                  onClick={forceSubmit}
                  className="text-xs px-3 py-1.5 bg-orange-900/30 text-orange-400 border border-orange-700/30 rounded hover:bg-orange-900/50 transition-colors"
                >
                  强制继续（偏离原著）
                </button>
              </div>
            )}
            {lastCheck.present_characters && lastCheck.present_characters.length > 0 && (
              <div className="text-xs mt-2 opacity-70">
                当前在场: {lastCheck.present_characters.join("、")}
              </div>
            )}
          </div>
        )}

        {/* Action Input */}
        <div className="border-t border-white/6 p-4">
          {/* Quick Actions (Soft Hints) */}
          <div className="flex gap-2 mb-3 flex-wrap">
            {ACTION_TYPES.map((a) => (
              <button
                key={a.type}
                onClick={() => {
                  setActionType(a.type);
                  captureEvent("storyplay_action_type_selected", {
                    worldline_id: worldlineId,
                    character_id: characterId,
                    character_name: characterName,
                    action_type: a.type,
                  });
                }}
                className={`text-xs px-3 py-1.5 rounded transition-colors ${
                  actionType === a.type
                    ? "border border-emerald-300/18 bg-emerald-300/10 text-white"
                    : "border border-white/8 text-white/42 hover:text-white/86"
                  }`}
                >
                {a.label}
              </button>
            ))}
            <span className="ml-2 self-center text-[10px] text-white/28">
              (快捷按钮为叙事偏向提示，不强制)
            </span>
          </div>

          <div className="flex gap-2">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && submitActionStream(false)}
              placeholder={`描述${characterName}的行动...`}
              className="amo-input flex-1 rounded-xl px-4 py-2.5"
              disabled={submitting}
            />
            <button
              onClick={() => submitActionStream(false)}
              disabled={submitting || !input.trim()}
              className="amo-button-primary rounded-xl px-6 py-2.5 font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            >
              {streaming ? "生成中..." : submitting ? "处理中..." : "执行"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function StoryplayPage() {
  return (
    <Suspense fallback={<div className="p-8 text-white/48">加载中...</div>}>
      <StoryplayInner />
    </Suspense>
  );
}
