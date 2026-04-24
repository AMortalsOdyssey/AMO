"use client";

import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  apiFetch,
  buildApiHeaders,
  type BillingSummary,
  type CharacterBrief,
  type Snapshot,
} from "@/lib/api";
import { captureEvent } from "@/lib/analytics";
import { getFeaturedCharacterIds } from "@/lib/featuredCharacters";
import { CharacterPicker } from "@/components/CharacterPicker";

const API_BASE = "/api";

interface Message {
  role: "user" | "assistant";
  content: string;
}

function ChatInner() {
  const searchParams = useSearchParams();
  const initCharId = searchParams.get("character_id");

  const [characters, setCharacters] = useState<CharacterBrief[]>([]);
  const [featuredCharacterIds, setFeaturedCharacterIds] = useState<number[]>([]);
  const [selectedChar, setSelectedChar] = useState<number | null>(initCharId ? Number(initCharId) : null);
  const [selectedCharName, setSelectedCharName] = useState("");
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [selectedSnap, setSelectedSnap] = useState<Snapshot | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [billingSummary, setBillingSummary] = useState<BillingSummary | null>(null);
  const [billingNotice, setBillingNotice] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const hasTrackedDirectEntryRef = useRef(false);

  useEffect(() => {
    apiFetch<BillingSummary>("/billing/me")
      .then(setBillingSummary)
      .catch(() => {
        setBillingSummary(null);
      });
  }, []);

  useEffect(() => {
    apiFetch<CharacterBrief[]>("/characters/for-chat?page_size=500").then((data) => {
      setCharacters(data);
      setFeaturedCharacterIds(getFeaturedCharacterIds(data));
    });
  }, []);

  useEffect(() => {
    if (!selectedChar) return;
    const c = characters.find((ch) => ch.id === selectedChar);
    if (c) {
      setSelectedCharName(c.name);
      if (!hasTrackedDirectEntryRef.current && initCharId && Number(initCharId) === c.id) {
        hasTrackedDirectEntryRef.current = true;
        captureEvent("chat_opened_with_character", {
          character_id: c.id,
          character_name: c.name,
          source: "query_character_id",
        });
      }
    }

    apiFetch<{ snapshots: Snapshot[] }>(`/characters/${selectedChar}`)
      .then((d) => {
        const snaps = (d.snapshots || [])
          .filter((s) => s.realm_stage !== "unknown")
          .sort((a, b) => a.chapter_start - b.chapter_start);
        // If no valid snapshots, use all (including unknown)
        const finalSnaps = snaps.length > 0 ? snaps : (d.snapshots || []);
        setSnapshots(finalSnaps);
        if (finalSnaps.length) setSelectedSnap(finalSnaps[finalSnaps.length - 1]); // default to latest
      });
    setMessages([]);
  }, [selectedChar, characters, initCharId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // 对话结束后自动聚焦输入框
  useEffect(() => {
    if (!streaming && selectedChar) {
      inputRef.current?.focus();
    }
  }, [streaming, selectedChar]);

  const refreshBillingSummary = async () => {
    try {
      const summary = await apiFetch<BillingSummary>("/billing/me");
      setBillingSummary(summary);
    } catch {
      // noop
    }
  };

  const sendMessage = async () => {
    if (!input.trim() || !selectedChar || streaming) return;
    const userMsg = input.trim();
    setBillingNotice(null);
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setStreaming(true);

    captureEvent("chat_message_sent", {
      character_id: selectedChar,
      character_name: selectedCharName,
      knowledge_cutoff: selectedSnap?.knowledge_cutoff ?? null,
      realm_stage: selectedSnap?.realm_stage ?? null,
      history_length: messages.length,
    });

    // Add placeholder assistant message
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    try {
      const body: Record<string, unknown> = {
        character_id: selectedChar,
        message: userMsg,
        history: messages.slice(-100),
      };
      if (selectedSnap) {
        if (selectedSnap.realm_stage !== "unknown") {
          body.realm_stage = selectedSnap.realm_stage;
        }
        body.chapter = selectedSnap.knowledge_cutoff;
      }

      const resp = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: buildApiHeaders(undefined, { json: true }),
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const contentType = resp.headers.get("Content-Type") || "";
        let detailMessage = `Chat request failed: ${resp.status}`;
        if (contentType.includes("application/json")) {
          const payload = await resp.json();
          const detail = payload?.detail || {};
          if (resp.status === 402 && detail.code === "insufficient_credits") {
            if (detail.summary) {
              setBillingSummary(detail.summary);
            } else {
              void refreshBillingSummary();
            }
            setBillingNotice(detail.message || "当前对话额度已用完，请先前往 Pricing 购买。");
            detailMessage = detail.message || detailMessage;
          } else {
            detailMessage = detail.message || payload?.error || detailMessage;
          }
        } else {
          detailMessage = await resp.text();
        }
        throw new Error(detailMessage);
      }

      const reader = resp.body?.getReader();
      if (!reader) {
        throw new Error("Chat response body is empty");
      }
      const decoder = new TextDecoder();
      let buffer = "";
      let fullContent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const data = JSON.parse(line.slice(6));
            if (data.content && !data.done) {
              fullContent += data.content;
              const captured = fullContent;
              setMessages((prev) => {
                const updated = prev.map((m, idx) =>
                  idx === prev.length - 1 && m.role === "assistant"
                    ? { ...m, content: captured }
                    : m
                );
                return updated;
              });
            }
            if (data.summary) {
              setBillingSummary(data.summary);
            }
            if (data.error) {
              setBillingNotice(data.content || "对话生成失败，请重试。");
            }
          } catch {
            // skip parse errors
          }
        }
      }
    } catch (e) {
      console.error("Chat error:", e);
      captureEvent("chat_message_failed", {
        character_id: selectedChar,
        character_name: selectedCharName,
      });
      if (e instanceof Error && e.message.includes("额度")) {
        setBillingNotice(e.message);
      }
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last.role === "assistant" && !last.content) {
          return [...prev.slice(0, -1), { ...last, content: e instanceof Error ? e.message : "对话出错，请重试。" }];
        }
        return prev;
      });
    }
    setStreaming(false);
  };

  const displayRealm = selectedSnap
    ? selectedSnap.realm_stage === "unknown" ? "未知境界" : selectedSnap.realm_stage
    : null;
  const outOfCredits = billingSummary ? billingSummary.remaining_credits <= 0 : false;

  const handleCharacterSelect = (charId: number | null) => {
    setSelectedChar(charId);
    if (charId === null) return;
    const character = characters.find((item) => item.id === charId);
    captureEvent("chat_character_selected", {
      character_id: charId,
      character_name: character?.name ?? null,
      source: "picker",
    });
  };

  const handleSnapshotSelect = (snapshot: Snapshot) => {
    setSelectedSnap(snapshot);
    setMessages([]);
    captureEvent("chat_snapshot_selected", {
      character_id: selectedChar,
      character_name: selectedCharName,
      snapshot_id: snapshot.id,
      realm_stage: snapshot.realm_stage,
      knowledge_cutoff: snapshot.knowledge_cutoff,
      chapter_start: snapshot.chapter_start,
      chapter_end: snapshot.chapter_end ?? null,
    });
  };

  return (
    <div className="flex h-[calc(100vh-4rem)]">
      {/* Sidebar */}
      <div className="amo-panel-strong flex w-72 flex-col rounded-r-3xl border-r border-white/6">
        <div className="border-b border-white/6 p-3">
          <div className="mb-2 text-xs uppercase tracking-[0.22em] text-white/34">选择角色</div>
          <CharacterPicker
            characters={characters}
            featuredCharacterIds={featuredCharacterIds}
            selected={selectedChar}
            onSelect={handleCharacterSelect}
          />
        </div>

        <div className="border-b border-white/6 p-3">
          <div className="mb-2 text-xs uppercase tracking-[0.22em] text-white/34">对话额度</div>
          <div className="amo-panel rounded-2xl p-3">
            <div className="text-3xl font-semibold text-white/92">
              {billingSummary ? billingSummary.remaining_credits : "..."}
            </div>
            <div className="mt-1 text-xs text-white/42">
              免费剩余 {billingSummary?.free_credits_remaining ?? "..."} · 累计已用 {billingSummary?.used_credits ?? "..."}
            </div>
            <div className="mt-3 text-xs leading-5 text-white/52">
              首次进入送 100 次，对话额度不足时可在 Pricing 购买 100 次 / $1。
            </div>
            <Link
              href="/pricing"
              className="mt-4 inline-flex rounded-full border border-emerald-200/20 bg-emerald-200/10 px-3 py-1.5 text-xs font-medium text-emerald-100 transition-colors hover:border-emerald-200/36 hover:bg-emerald-200/16"
            >
              打开 Pricing
            </Link>
          </div>
          {billingNotice ? (
            <div className="mt-3 rounded-xl border border-amber-200/14 bg-amber-200/8 px-3 py-2 text-xs leading-5 text-amber-50">
              {billingNotice}
            </div>
          ) : null}
        </div>

        {/* Snapshot selector */}
        {snapshots.length > 0 && (
          <div className="border-b border-white/6 p-3">
            <div className="mb-2 text-xs uppercase tracking-[0.22em] text-white/34">选择时间点</div>
            <div className="space-y-1 max-h-60 overflow-y-auto">
              {snapshots.map((s) => (
                <button
                  key={s.id}
                  onClick={() => handleSnapshotSelect(s)}
                  className={`w-full text-left text-xs px-2 py-1.5 rounded transition-colors ${
                    selectedSnap?.id === s.id
                      ? "border border-emerald-300/18 bg-emerald-300/10 text-white"
                      : "text-white/58 hover:bg-white/4"
                  }`}
                >
                  <div className="font-medium">
                    {s.realm_stage === "unknown" ? "未知境界" : s.realm_stage}
                  </div>
                  <div className="text-white/34">
                    第{s.chapter_start}章{s.chapter_end ? `~${s.chapter_end}` : "起"}
                    · 知识截止第{s.knowledge_cutoff}章
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Current snapshot info */}
        {selectedSnap && (
          <div className="p-3 flex-1 overflow-y-auto">
            <div className="mb-2 text-xs uppercase tracking-[0.22em] text-white/34">当前角色状态</div>
            <div className="space-y-2 text-xs">
              <div>
                <span className="text-white/34">境界: </span>
                <span className="text-emerald-200">{displayRealm}</span>
              </div>
              <div>
                <span className="text-white/34">知识边界: </span>
                <span className="text-white/84">第{selectedSnap.knowledge_cutoff}章</span>
              </div>
              {selectedSnap.personality_traits.length > 0 && (
                <div>
                  <span className="text-white/34">性格: </span>
                  <span className="text-white/64">{selectedSnap.personality_traits.join("、")}</span>
                </div>
              )}
              {selectedSnap.persona_prompt && (
                <div className="mt-2 leading-relaxed text-white/46">
                  {selectedSnap.persona_prompt.slice(0, 200)}
                  {selectedSnap.persona_prompt.length > 200 && "..."}
                </div>
              )}
            </div>
          </div>
        )}

        {snapshots.length === 0 && selectedChar && (
          <div className="p-3 text-xs text-white/34">
            该角色暂无快照数据，将使用默认设定对话。
          </div>
        )}
      </div>

      {/* Chat area */}
      <div className="flex flex-1 flex-col">
        {!selectedChar ? (
          <div className="flex flex-1 items-center justify-center text-white/32">
            请在左侧选择一个角色开始对话
          </div>
        ) : (
          <>
            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.length === 0 && (
                <div className="mt-20 text-center text-white/34">
                  <div className="mb-2 text-lg text-white/86">与「{selectedCharName}」对话</div>
                  <div className="text-sm">
                    {displayRealm && (
                      <>当前: {displayRealm} · 知识截止到第{selectedSnap!.knowledge_cutoff}章</>
                    )}
                  </div>
                </div>
              )}
              {messages.map((m, i) => (
                <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[70%] rounded-lg px-4 py-2.5 ${
                      m.role === "user"
                        ? "bg-gradient-to-br from-emerald-300 to-teal-300 text-emerald-950 shadow-lg shadow-emerald-500/10"
                        : "amo-panel text-white/84"
                    }`}
                  >
                    {m.role === "assistant" && (
                      <div className="mb-1 text-xs text-emerald-200/72">{selectedCharName}</div>
                    )}
                    <div className="whitespace-pre-wrap text-sm leading-relaxed">
                      {m.content || (streaming && i === messages.length - 1 ? "..." : "")}
                    </div>
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="border-t border-white/6 p-4">
              {outOfCredits ? (
                <div className="mb-3 rounded-2xl border border-amber-200/14 bg-amber-200/8 px-4 py-3 text-sm text-amber-50">
                  当前额度已耗尽，请前往 <Link href="/pricing" className="font-medium underline underline-offset-4">Pricing</Link> 购买更多对话次数。
                </div>
              ) : null}
              <div className="flex gap-2">
                <input
                  ref={inputRef}
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
                  placeholder={outOfCredits ? "额度不足，请先前往 Pricing" : `对${selectedCharName}说...`}
                  className="amo-input flex-1 rounded-xl px-4 py-2.5"
                  disabled={streaming || outOfCredits}
                />
                <button
                  onClick={sendMessage}
                  disabled={streaming || !input.trim() || outOfCredits}
                  className="amo-button-primary rounded-xl px-6 py-2.5 font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {streaming ? "..." : "发送"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="p-8 text-white/48">加载中...</div>}>
      <ChatInner />
    </Suspense>
  );
}
