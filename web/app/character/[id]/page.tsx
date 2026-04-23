"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { apiFetch, type CharacterDetail } from "@/lib/api";
import { captureEvent } from "@/lib/analytics";

export default function CharacterPage() {
  const params = useParams();
  const id = params.id as string;
  const [char, setChar] = useState<CharacterDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function loadCharacter() {
      setLoading(true);
      try {
        const data = await apiFetch<CharacterDetail>(`/characters/${id}`);
        if (!cancelled) {
          setChar(data);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadCharacter();

    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    if (!char) return;
    captureEvent("character_detail_viewed", {
      character_id: char.id,
      character_name: char.name,
      is_major: char.is_major,
      first_chapter: char.first_chapter,
      snapshot_count: char.snapshots.length,
      relation_count: char.relations.length,
    });
  }, [char]);

  if (loading) return <div className="p-8 text-white/48">加载中...</div>;
  if (!char) return <div className="p-8 text-rose-300">角色不存在</div>;

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      {/* Header */}
      <div className="amo-panel mb-8 rounded-3xl p-6">
        <div className="flex items-center gap-3 mb-2">
          <h1 className="text-3xl font-semibold text-white/92">{char.name}</h1>
          {char.is_major && (
            <span className="rounded-full border border-emerald-300/20 bg-emerald-300/10 px-2 py-0.5 text-xs text-emerald-200">
              核心角色
            </span>
          )}
          {char.gender && (
            <span className="text-xs text-white/42">{char.gender === "male" ? "男" : char.gender === "female" ? "女" : char.gender}</span>
          )}
        </div>
        {char.aliases.length > 0 && (
          <div className="text-sm text-white/52">
            别名：{char.aliases.map((a) => a.alias).join("、")}
          </div>
        )}
        <div className="mt-1 text-sm text-white/36">首次出场：第{char.first_chapter}章</div>
        <div className="flex gap-2 mt-4">
          <Link
            href={`/chat?character_id=${char.id}`}
            onClick={() => {
              captureEvent("character_detail_chat_clicked", {
                character_id: char.id,
                character_name: char.name,
              });
            }}
            className="amo-button-primary rounded-xl px-4 py-2 text-sm font-medium transition-colors"
          >
            与{char.name}对话
          </Link>
          <Link
            href={`/graph-v3?center_id=${char.id}`}
            onClick={() => {
              captureEvent("character_detail_graph_clicked", {
                character_id: char.id,
                character_name: char.name,
              });
            }}
            className="amo-button-secondary rounded-xl px-4 py-2 text-sm transition-colors"
          >
            查看关系图谱
          </Link>
        </div>
      </div>

      {/* Realm Timeline */}
      {char.realm_timeline.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 text-lg font-semibold text-white/92">境界历程</h2>
          <div className="space-y-2">
            {char.realm_timeline.map((rt) => (
              <div key={rt.id} className="amo-panel rounded-2xl px-4 py-3 flex items-center gap-3">
                <div className="h-3 w-3 flex-shrink-0 rounded-full bg-emerald-300" />
                <div className="flex-1">
                  <span className="font-medium text-white/92">{rt.realm_stage}</span>
                </div>
                <div className="text-xs text-white/42">
                  第{rt.start_chapter}章
                  {rt.end_chapter && ` → 第${rt.end_chapter}章`}
                  {rt.start_year && ` (${rt.start_year}岁)`}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Snapshots */}
      {char.snapshots.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 text-lg font-semibold text-white/92">角色快照</h2>
          <div className="space-y-3">
            {char.snapshots.map((s) => (
              <div key={s.id} className="amo-panel rounded-2xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium text-emerald-200">{s.realm_stage}</span>
                  <span className="text-xs text-white/42">
                    第{s.chapter_start}章{s.chapter_end ? `~${s.chapter_end}` : "起"} · 知识边界: 第{s.knowledge_cutoff}章
                  </span>
                </div>
                {s.persona_prompt && (
                  <p className="mb-2 text-sm text-white/68">{s.persona_prompt}</p>
                )}
                {s.personality_traits.length > 0 && (
                  <div className="flex gap-1 flex-wrap">
                    {s.personality_traits.map((t, i) => (
                      <span key={i} className="rounded-full border border-white/10 bg-white/4 px-2 py-0.5 text-xs text-white/66">
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Relations */}
      {char.relations.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 text-lg font-semibold text-white/92">人物关系</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {char.relations.map((r) => {
              const other = r.from_character_id === char.id
                ? { id: r.to_character_id, name: r.to_character_name }
                : { id: r.from_character_id, name: r.from_character_name };
              return (
                <Link
                  key={r.id}
                  href={`/character/${other.id}`}
                  onClick={() => {
                    captureEvent("character_relation_clicked", {
                      character_id: char.id,
                      character_name: char.name,
                      target_character_id: other.id,
                      target_character_name: other.name ?? null,
                      relation_type: r.relation_type,
                    });
                  }}
                  className="amo-panel flex items-center gap-3 rounded-2xl px-4 py-3 transition-colors hover:border-emerald-200/18 hover:bg-white/4"
                >
                  <span className="text-white/92">{other.name || `#${other.id}`}</span>
                  <span className="rounded-full border border-white/10 bg-white/4 px-1.5 py-0.5 text-xs text-white/68">{r.relation_type}</span>
                  <span className="ml-auto text-xs text-white/36">第{r.valid_from_chapter}章起</span>
                </Link>
              );
            })}
          </div>
        </section>
      )}

      {/* Faction Memberships */}
      {char.faction_memberships.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 text-lg font-semibold text-white/92">势力归属</h2>
          <div className="space-y-2">
            {char.faction_memberships.map((m) => (
              <div key={m.id} className="amo-panel flex items-center gap-3 rounded-2xl px-4 py-3">
                <span className="text-emerald-200">{m.faction_name || `势力#${m.faction_id}`}</span>
                <span className="text-xs text-white/56">{m.role}</span>
                <span className="ml-auto text-xs text-white/36">第{m.valid_from_chapter}章起</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
