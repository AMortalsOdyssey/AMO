"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch, type TimelineEvent } from "@/lib/api";
import { captureEvent } from "@/lib/analytics";

const TYPE_COLORS: Record<string, string> = {
  faction_event: "#62e0a1",
  major_battle: "#f2b36c",
  realm_breakthrough: "#7fd8ff",
  world_event: "#46cfd9",
  character_death: "#e38ab2",
  item_acquisition: "#8bb8ff",
  location_move: "#56d2c4",
  relationship_change: "#b7e36c",
};

const TYPE_LABELS: Record<string, string> = {
  faction_event: "门派事件",
  major_battle: "重大战斗",
  realm_breakthrough: "境界突破",
  world_event: "世界事件",
  character_death: "角色死亡",
  item_acquisition: "获得法宝",
  location_move: "地点移动",
  relationship_change: "关系变化",
};

export default function TimelinePage() {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("");
  const [availableTypes, setAvailableTypes] = useState<string[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [jumpInput, setJumpInput] = useState("");
  const pageSize = 50;
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const hasTrackedViewRef = useRef(false);

  // Load first page to discover available types
  useEffect(() => {
    apiFetch<TimelineEvent[]>("/timeline?page_size=200").then((data) => {
      const types = [...new Set(data.map((e) => e.event_type))];
      setAvailableTypes(types);
    });
  }, []);

  // Load count
  useEffect(() => {
    const params = new URLSearchParams();
    if (filter) params.set("event_type", filter);
    apiFetch<{ total: number }>(`/timeline/count?${params}`).then((data) => {
      setTotalCount(data.total);
    });
  }, [filter]);

  useEffect(() => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (filter) params.set("event_type", filter);
    apiFetch<TimelineEvent[]>(`/timeline?${params}`)
      .then(setEvents)
      .finally(() => setLoading(false));
  }, [page, filter]);

  useEffect(() => {
    if (loading || hasTrackedViewRef.current) return;
    hasTrackedViewRef.current = true;
    captureEvent("timeline_viewed", {
      total_count: totalCount,
      available_type_count: availableTypes.length,
    });
  }, [availableTypes.length, loading, totalCount]);

  const handleFilterChange = (nextFilter: string) => {
    setLoading(true);
    setFilter(nextFilter);
    setPage(1);
    captureEvent("timeline_filter_changed", {
      event_type: nextFilter || "all",
    });
  };

  const handlePageChange = (nextPage: number, trigger: "first" | "prev" | "next" | "last" | "jump") => {
    setLoading(true);
    setPage(nextPage);
    captureEvent("timeline_page_changed", {
      trigger,
      from_page: page,
      to_page: nextPage,
      event_type: filter || "all",
    });
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="mb-6 text-2xl font-semibold text-white/92">世界时间线</h1>

      {/* Filters */}
      <div className="flex gap-2 mb-6 flex-wrap">
        <button
          onClick={() => handleFilterChange("")}
          className={`text-xs px-3 py-1.5 rounded transition-colors ${
            !filter ? "border border-emerald-300/18 bg-emerald-300/10 text-white" : "border border-white/8 bg-white/3 text-white/42 hover:text-white/86"
          }`}
        >
          全部
        </button>
        {availableTypes.map((t) => {
          const color = TYPE_COLORS[t] || "#6b7280";
          const label = TYPE_LABELS[t] || t;
          return (
            <button
              key={t}
              onClick={() => handleFilterChange(t)}
              className="border text-xs px-3 py-1.5 rounded transition-colors"
              style={
                filter === t
                  ? {
                      borderColor: `${color}66`,
                      backgroundColor: `${color}26`,
                      color,
                    }
                  : {
                      borderColor: `${color}33`,
                      backgroundColor: `${color}12`,
                      color: `${color}dd`,
                    }
              }
            >
              <span className="mr-1 inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
              {label}
            </button>
          );
        })}
      </div>

      {/* Timeline */}
      {loading ? (
        <div className="py-20 text-center text-white/40">加载中...</div>
      ) : events.length === 0 ? (
        <div className="py-20 text-center text-white/40">暂无数据</div>
      ) : (
        <div className="relative">
          {/* Vertical line */}
          <div className="absolute bottom-0 left-[72px] top-0 w-px bg-white/10" />

          <div className="space-y-1">
            {events.map((e) => {
              const color = TYPE_COLORS[e.event_type] || "#6b7280";
              const label = TYPE_LABELS[e.event_type] || e.event_type;
              return (
                <div key={e.id} className="flex gap-4 group">
                  {/* Year/Chapter */}
                  <div className="w-16 text-right flex-shrink-0 pt-3">
                    <div className="font-mono text-xs text-white/42">{e.world_year}岁</div>
                    {e.chapter_start && (
                      <div className="font-mono text-xs text-white/26">第{e.chapter_start}章</div>
                    )}
                  </div>

                  {/* Dot */}
                  <div className="flex-shrink-0 pt-4 relative z-10">
                    <div
                      className="h-3 w-3 rounded-full border-2 bg-[#081411]"
                      style={{ borderColor: color }}
                    />
                  </div>

                  {/* Content */}
                  <div className="amo-panel mb-1 flex-1 rounded-2xl p-3 transition-colors group-hover:border-emerald-200/18 group-hover:bg-white/4">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs px-1.5 py-0.5 rounded" style={{ backgroundColor: color + "22", color }}>
                        {label}
                      </span>
                      <span className="text-sm font-medium text-white/92">{e.event_name}</span>
                    </div>
                    {e.event_detail && (
                      <p className="text-xs leading-relaxed text-white/46">{e.event_detail}</p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Pagination */}
      <div className="flex items-center justify-center gap-3 mt-8 flex-wrap">
        <button
          onClick={() => handlePageChange(1, "first")}
          disabled={page === 1}
          className="amo-button-secondary rounded-xl px-3 py-2 text-sm disabled:opacity-30"
        >
          首页
        </button>
        <button
          onClick={() => handlePageChange(Math.max(1, page - 1), "prev")}
          disabled={page === 1}
          className="amo-button-secondary rounded-xl px-4 py-2 text-sm disabled:opacity-30"
        >
          上一页
        </button>
        <span className="px-2 py-2 text-sm text-white/52">
          第 <span className="font-medium text-emerald-200">{page}</span> / {totalPages} 页
          <span className="ml-2 text-white/32">（共 {totalCount} 条）</span>
        </span>
        <button
          onClick={() => handlePageChange(Math.min(totalPages, page + 1), "next")}
          disabled={page >= totalPages}
          className="amo-button-secondary rounded-xl px-4 py-2 text-sm disabled:opacity-30"
        >
          下一页
        </button>
        <button
          onClick={() => handlePageChange(totalPages, "last")}
          disabled={page >= totalPages}
          className="amo-button-secondary rounded-xl px-3 py-2 text-sm disabled:opacity-30"
        >
          末页
        </button>
        <div className="flex items-center gap-1 ml-2">
          <input
            type="number"
            min={1}
            max={totalPages}
            value={jumpInput}
            onChange={(e) => setJumpInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                const p = Math.max(1, Math.min(totalPages, Number(jumpInput) || 1));
                handlePageChange(p, "jump");
                setJumpInput("");
              }
            }}
            placeholder="页码"
            className="amo-input w-16 rounded-xl px-2 py-1.5 text-center text-sm"
          />
          <button
            onClick={() => {
              const p = Math.max(1, Math.min(totalPages, Number(jumpInput) || 1));
              handlePageChange(p, "jump");
              setJumpInput("");
            }}
            className="amo-button-secondary rounded-xl px-3 py-1.5 text-sm"
          >
            跳转
          </button>
        </div>
      </div>
    </div>
  );
}
