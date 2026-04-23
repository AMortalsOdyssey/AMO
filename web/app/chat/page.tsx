"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiFetch, type CharacterBrief, type Snapshot } from "@/lib/api";
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
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    apiFetch<CharacterBrief[]>("/characters/for-chat?page_size=500").then((data) => {
      setCharacters(data);
      setFeaturedCharacterIds(getFeaturedCharacterIds(data));
    });
  }, []);

  useEffect(() => {
    if (!selectedChar) return;
    const c = characters.find((ch) => ch.id === selectedChar);
    if (c) setSelectedCharName(c.name);

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
  }, [selectedChar, characters]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // 对话结束后自动聚焦输入框
  useEffect(() => {
    if (!streaming && selectedChar) {
      inputRef.current?.focus();
    }
  }, [streaming, selectedChar]);

  const sendMessage = async () => {
    if (!input.trim() || !selectedChar || streaming) return;
    const userMsg = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setStreaming(true);

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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        throw new Error(`Chat request failed: ${resp.status} ${await resp.text()}`);
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
          } catch {
            // skip parse errors
          }
        }
      }
    } catch (e) {
      console.error("Chat error:", e);
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last.role === "assistant" && !last.content) {
          return [...prev.slice(0, -1), { ...last, content: "对话出错，请重试。" }];
        }
        return prev;
      });
    }
    setStreaming(false);
  };

  const displayRealm = selectedSnap
    ? selectedSnap.realm_stage === "unknown" ? "未知境界" : selectedSnap.realm_stage
    : null;

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
            onSelect={setSelectedChar}
          />
        </div>

        {/* Snapshot selector */}
        {snapshots.length > 0 && (
          <div className="border-b border-white/6 p-3">
            <div className="mb-2 text-xs uppercase tracking-[0.22em] text-white/34">选择时间点</div>
            <div className="space-y-1 max-h-60 overflow-y-auto">
              {snapshots.map((s) => (
                <button
                  key={s.id}
                  onClick={() => { setSelectedSnap(s); setMessages([]); }}
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
              <div className="flex gap-2">
                <input
                  ref={inputRef}
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
                  placeholder={`对${selectedCharName}说...`}
                  className="amo-input flex-1 rounded-xl px-4 py-2.5"
                  disabled={streaming}
                />
                <button
                  onClick={sendMessage}
                  disabled={streaming || !input.trim()}
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
