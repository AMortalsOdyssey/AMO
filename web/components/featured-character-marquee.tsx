"use client";

import { useEffect, useRef, useState } from "react";
import type { MouseEvent, PointerEvent as ReactPointerEvent } from "react";
import Link from "next/link";

export type FeaturedCharacterMarqueeItem = {
  id: number;
  name: string;
  aliases: string[];
  realmStage?: string;
  portraitSrc?: string | null;
};

type FeaturedCharacterMarqueeProps = {
  characters: FeaturedCharacterMarqueeItem[];
};

const ROW_DIRECTIONS = ["right", "left", "right", "left"] as const;
const ROW_DURATIONS = [47, 44, 49, 46] as const;
const MARQUEE_SLOWDOWN_FACTOR = 2;

type MarqueeDirection = (typeof ROW_DIRECTIONS)[number];

function splitIntoRows(items: FeaturedCharacterMarqueeItem[], rowCount: number) {
  const baseSize = Math.floor(items.length / rowCount);
  const remainder = items.length % rowCount;
  const rows: FeaturedCharacterMarqueeItem[][] = [];
  let cursor = 0;

  for (let index = 0; index < rowCount; index += 1) {
    const size = baseSize + (index < remainder ? 1 : 0);
    rows.push(items.slice(cursor, cursor + size));
    cursor += size;
  }

  return rows;
}

function sigilForName(name: string) {
  return name.slice(0, 1);
}

function normalizeOffset(offset: number, loopWidth: number, direction: MarqueeDirection) {
  if (loopWidth <= 0) return 0;

  if (direction === "left") {
    while (offset <= -loopWidth) offset += loopWidth;
    while (offset > 0) offset -= loopWidth;
    return offset;
  }

  while (offset >= 0) offset -= loopWidth;
  while (offset < -loopWidth) offset += loopWidth;
  return offset;
}

function MarqueeRow({
  row,
  direction,
  duration,
}: {
  row: FeaturedCharacterMarqueeItem[];
  direction: MarqueeDirection;
  duration: number;
}) {
  const rowRef = useRef<HTMLDivElement | null>(null);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const segmentRef = useRef<HTMLDivElement | null>(null);
  const loopWidthRef = useRef(0);
  const offsetRef = useRef(0);
  const animationFrameRef = useRef<number | null>(null);
  const lastTimestampRef = useRef<number | null>(null);
  const draggingRef = useRef(false);
  const hoverPausedRef = useRef(false);
  const ignoreHoverUntilLeaveRef = useRef(false);
  const pointerDownRef = useRef(false);
  const activePointerIdRef = useRef<number | null>(null);
  const dragStartXRef = useRef(0);
  const dragStartYRef = useRef(0);
  const dragStartOffsetRef = useRef(0);
  const suppressClickRef = useRef(false);
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => {
    const track = trackRef.current;
    const segment = segmentRef.current;
    if (!track || !segment) return undefined;

    const applyOffset = () => {
      track.style.transform = `translate3d(${offsetRef.current}px, 0, 0)`;
    };

    const measure = () => {
      const segmentWidth = segment.getBoundingClientRect().width;
      const computedTrackStyle = window.getComputedStyle(track);
      const segmentGap = Number.parseFloat(computedTrackStyle.gap || computedTrackStyle.columnGap || "0") || 0;
      const nextLoopWidth = segmentWidth + segmentGap;
      if (!nextLoopWidth) return;

      loopWidthRef.current = nextLoopWidth;
      offsetRef.current = normalizeOffset(
        offsetRef.current || (direction === "left" ? 0 : -nextLoopWidth),
        nextLoopWidth,
        direction,
      );
      applyOffset();
    };

    const resizeObserver = new ResizeObserver(() => {
      measure();
    });

    resizeObserver.observe(segment);
    resizeObserver.observe(track);
    measure();

    const tick = (timestamp: number) => {
      const loopWidth = loopWidthRef.current;
      const paused = draggingRef.current || (hoverPausedRef.current && !ignoreHoverUntilLeaveRef.current);

      if (!paused && loopWidth > 0) {
        const deltaSeconds = lastTimestampRef.current == null ? 0 : (timestamp - lastTimestampRef.current) / 1000;
        const distancePerSecond = loopWidth / duration;
        const directionMultiplier = direction === "left" ? -1 : 1;
        offsetRef.current = normalizeOffset(
          offsetRef.current + (distancePerSecond * deltaSeconds * directionMultiplier),
          loopWidth,
          direction,
        );
        applyOffset();
      }

      lastTimestampRef.current = timestamp;
      animationFrameRef.current = window.requestAnimationFrame(tick);
    };

    animationFrameRef.current = window.requestAnimationFrame(tick);

    return () => {
      resizeObserver.disconnect();
      if (animationFrameRef.current != null) {
        window.cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, [direction, duration]);

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;

    pointerDownRef.current = true;
    activePointerIdRef.current = event.pointerId;
    dragStartXRef.current = event.clientX;
    dragStartYRef.current = event.clientY;
    dragStartOffsetRef.current = offsetRef.current;
    suppressClickRef.current = false;
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!pointerDownRef.current || activePointerIdRef.current !== event.pointerId || loopWidthRef.current <= 0) return;

    const dragDeltaX = event.clientX - dragStartXRef.current;
    const dragDeltaY = event.clientY - dragStartYRef.current;

    if (!draggingRef.current) {
      const absDeltaX = Math.abs(dragDeltaX);
      const absDeltaY = Math.abs(dragDeltaY);
      if (absDeltaX < 14 || absDeltaX <= absDeltaY) {
        return;
      }

      const rowElement = rowRef.current;
      if (!rowElement) return;

      draggingRef.current = true;
      hoverPausedRef.current = true;
      ignoreHoverUntilLeaveRef.current = false;
      suppressClickRef.current = true;
      lastTimestampRef.current = null;
      setIsDragging(true);
      rowElement.setPointerCapture(event.pointerId);
    }

    offsetRef.current = normalizeOffset(
      dragStartOffsetRef.current + dragDeltaX,
      loopWidthRef.current,
      direction,
    );

    if (trackRef.current) {
      trackRef.current.style.transform = `translate3d(${offsetRef.current}px, 0, 0)`;
    }
  };

  const finishDragging = (pointerId?: number) => {
    pointerDownRef.current = false;
    activePointerIdRef.current = null;

    if (!draggingRef.current) return;

    draggingRef.current = false;
    hoverPausedRef.current = false;
    ignoreHoverUntilLeaveRef.current = suppressClickRef.current;
    lastTimestampRef.current = null;
    setIsDragging(false);

    if (rowRef.current != null && pointerId != null && rowRef.current.hasPointerCapture(pointerId)) {
      rowRef.current.releasePointerCapture(pointerId);
    }
  };

  const handlePointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) {
      pointerDownRef.current = false;
      activePointerIdRef.current = null;
      return;
    }
    finishDragging(event.pointerId);
  };

  const handlePointerCancel = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) {
      pointerDownRef.current = false;
      activePointerIdRef.current = null;
      return;
    }
    finishDragging(event.pointerId);
  };

  const handlePointerEnter = () => {
    hoverPausedRef.current = true;
  };

  const handlePointerLeave = () => {
    pointerDownRef.current = false;
    activePointerIdRef.current = null;
    hoverPausedRef.current = false;
    ignoreHoverUntilLeaveRef.current = false;
  };

  const handleClickCapture = (event: MouseEvent<HTMLDivElement>) => {
    if (!suppressClickRef.current) return;

    event.preventDefault();
    event.stopPropagation();
    suppressClickRef.current = false;
  };

  return (
    <div
      ref={rowRef}
      className="amo-marquee-row"
      data-dragging={isDragging ? "true" : "false"}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerCancel}
      onPointerEnter={handlePointerEnter}
      onPointerLeave={handlePointerLeave}
      onClickCapture={handleClickCapture}
    >
      <div
        ref={trackRef}
        className="amo-marquee-track"
        data-direction={direction}
      >
        {[0, 1].map((copyIndex) => (
          <div
            key={`copy-${copyIndex}`}
            ref={copyIndex === 0 ? segmentRef : undefined}
            className="amo-marquee-segment"
          >
            {row.map((character) => (
                    <Link
                      key={`${copyIndex}-${character.id}`}
                      href={`/chat?character_id=${character.id}`}
                      className="amo-role-card group"
                    >
                      <div className="amo-role-sigil">
                        {character.portraitSrc ? (
                          <img
                            src={character.portraitSrc}
                            alt={character.name}
                            className="amo-role-sigil-image"
                          />
                        ) : (
                          <span>{sigilForName(character.name)}</span>
                        )}
                      </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold tracking-[0.06em] text-white/92 md:text-[15px]">
                    {character.name}
                  </div>
                  <div className="mt-1 truncate text-[11px] text-white/42 md:text-xs">
                    {character.aliases[0] ?? "凡尘一瞬，剑意长明"}
                  </div>
                </div>
                <div className="hidden shrink-0 text-right md:block">
                  <div className="text-[10px] uppercase tracking-[0.24em] text-cyan-200/42">Realm</div>
                  <div className="mt-1 max-w-28 truncate text-xs text-emerald-100/74">
                    {character.realmStage ?? "命途未尽"}
                  </div>
                </div>
              </Link>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function FeaturedCharacterMarquee({ characters }: FeaturedCharacterMarqueeProps) {
  const rows = splitIntoRows(characters, 4).filter((row) => row.length > 0);

  return (
    <div className="relative overflow-hidden rounded-[2rem] border border-white/8 bg-white/[0.025] px-2 py-4 md:px-4 md:py-5">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-200/24 to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 left-0 z-[1] w-20 bg-gradient-to-r from-[#121819] via-[#121819]/88 to-transparent md:w-28" />
      <div className="pointer-events-none absolute inset-y-0 right-0 z-[1] w-20 bg-gradient-to-l from-[#121819] via-[#121819]/88 to-transparent md:w-28" />

      <div className="flex flex-col gap-3 md:gap-4">
        {rows.map((row, index) => (
          <MarqueeRow
            key={`featured-row-${index}`}
            row={row}
            direction={ROW_DIRECTIONS[index] ?? "left"}
            duration={(ROW_DURATIONS[index] ?? 36) * MARQUEE_SLOWDOWN_FACTOR}
          />
        ))}
      </div>
    </div>
  );
}
