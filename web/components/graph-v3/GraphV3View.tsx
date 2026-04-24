"use client";

import type { ForceGraph3DInstance } from "3d-force-graph";
import Image from "next/image";
import Link from "next/link";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import bottleIcon from "@/app/green-bottle-icon.png";
import { apiFetch, type GraphData, type GraphEdge, type GraphNode, type Stats } from "@/lib/api";
import { captureEvent } from "@/lib/analytics";

type ThreeModule = typeof import("three");

type Graph3DNode = GraphNode & {
  name: string;
  group: string;
  val: number;
  degree: number;
  color: string;
  fx?: number;
  fy?: number;
  fz?: number;
  x?: number;
  y?: number;
  z?: number;
  vx?: number;
  vy?: number;
  vz?: number;
};

type Graph3DLink = GraphEdge & {
  id: string;
  name: string;
  color: string;
};

type PreparedGraph = {
  nodes: Graph3DNode[];
  links: Graph3DLink[];
  nodeMap: Map<string, Graph3DNode>;
  adjacency: Map<string, { neighbors: string[]; links: string[] }>;
};

type GraphV3ViewProps = {
  initialSearchParams: Record<string, string | string[] | undefined>;
};

const HAN_LI_ID = "88";
const SPIRAL_INTRO_DURATION_MS = 3200;
const GRAPH_LINK_OPACITY = 0.08;
const FALLBACK_MAX_CHAPTER = 1394;

const NODE_SPECTRUM = [
  "#3be1c2",
  "#2fd6f5",
  "#63b7ff",
  "#8f98ff",
  "#ffbf3c",
  "#ff9b52",
  "#ff7396",
  "#b6e64f",
] as const;

const TYPE_ACCENTS: Record<string, string> = {
  Character: "#3be1c2",
  Faction: "#2fd6f5",
  Artifact: "#ffbf3c",
  Technique: "#8f98ff",
  Location: "#ff9b52",
  SpiritBeast: "#b6e64f",
  Unknown: "#8aa3b8",
};

const LINK_COLOR = "#6ee6d2";

function hashString(value: string) {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(index);
    hash |= 0;
  }
  return Math.abs(hash);
}

function spectrumColor(seed: string) {
  return NODE_SPECTRUM[hashString(seed) % NODE_SPECTRUM.length] ?? TYPE_ACCENTS.Unknown;
}

function nodeColorFor(node: GraphNode) {
  if (node.type === "Character") {
    return spectrumColor(`${node.label}:${node.id}`);
  }

  return TYPE_ACCENTS[node.type] ?? spectrumColor(`${node.type}:${node.label}:${node.id}`);
}

function buildSearchParams(params: Record<string, string | string[] | undefined>) {
  const next = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (typeof value === "string" && value.length > 0) {
      next.set(key, value);
      return;
    }
    if (Array.isArray(value)) {
      value.forEach((item) => next.append(key, item));
    }
  });
  const query = next.toString();
  return query ? `?${query}` : "";
}

function lerp(start: number, end: number, progress: number) {
  return start + (end - start) * progress;
}

function easeInOutCubic(value: number) {
  return value < 0.5 ? 4 * value ** 3 : 1 - ((-2 * value + 2) ** 3) / 2;
}

function relationName(edge: GraphEdge) {
  const relType = edge.properties?.type;
  return typeof relType === "string" && relType.length > 0 ? relType : edge.type;
}

function createShellForce(targetRadiusFor: (node: Graph3DNode) => number, strength = 0.08) {
  let nodes: Graph3DNode[] = [];

  function force(alpha: number) {
    nodes.forEach((node) => {
      const x = node.x ?? (Math.random() - 0.5) * 2;
      const y = node.y ?? (Math.random() - 0.5) * 2;
      const z = node.z ?? (Math.random() - 0.5) * 2;
      const radius = Math.hypot(x, y, z) || 1;
      const targetRadius = targetRadiusFor(node);
      const delta = (targetRadius - radius) * strength * alpha;

      node.vx = (node.vx ?? 0) + (x / radius) * delta;
      node.vy = (node.vy ?? 0) + (y / radius) * delta;
      node.vz = (node.vz ?? 0) + (z / radius) * delta;
    });
  }

  force.initialize = (nextNodes: Graph3DNode[]) => {
    nodes = nextNodes;
  };

  return force;
}

function fibonacciSpherePosition(index: number, total: number, radius: number) {
  const safeTotal = Math.max(total, 2);
  const offset = 2 / safeTotal;
  const increment = Math.PI * (3 - Math.sqrt(5));
  const y = ((index * offset) - 1) + offset / 2;
  const radial = Math.sqrt(Math.max(0, 1 - y * y));
  const phi = index * increment;

  return {
    x: Math.cos(phi) * radial * radius,
    y: y * radius,
    z: Math.sin(phi) * radial * radius,
  };
}

function radialFactorForNode(node: Graph3DNode, maxDegree: number) {
  const degreeRatio = node.degree / Math.max(maxDegree, 1);
  const seed = hashString(`${node.id}:${node.label}:${node.degree}`) / 0x7fffffff;
  const outerBias = 0.44 + (1 - Math.sqrt(degreeRatio || 0)) * 0.46;

  // Keep most nodes near the outer shell, but pull a meaningful slice inward
  // so the graph reads as a sphere with internal structure instead of a hollow shell.
  const inwardPocket = seed < 0.16 ? -0.2 : seed < 0.46 ? -0.1 : 0;
  const subtleJitter = (seed - 0.5) * 0.06;

  return Math.max(0.22, Math.min(0.96, outerBias + inwardPocket + subtleJitter));
}

function nodeSizeForDegree(degree: number, isMajor: boolean) {
  const base = isMajor ? 2.2 : 1.4;
  const degreeBoost = Math.min(1.85, Math.log2(degree + 2) * 0.55);
  return Math.min(6.4, Number((base + degreeBoost).toFixed(2)));
}

function percentileThreshold(values: number[], percentile: number) {
  if (values.length === 0) return 0;
  const index = Math.min(values.length - 1, Math.max(0, Math.floor(values.length * percentile)));
  return values[index] ?? 0;
}

function createImmortalNightPanoramaTexture(THREE: ThreeModule) {
  const canvas = document.createElement("canvas");
  canvas.width = 4096;
  canvas.height = 2048;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  const { width, height } = canvas;

  const baseGradient = ctx.createLinearGradient(0, 0, 0, height);
  baseGradient.addColorStop(0, "#02040b");
  baseGradient.addColorStop(0.35, "#050814");
  baseGradient.addColorStop(0.7, "#07101c");
  baseGradient.addColorStop(1, "#03050d");
  ctx.fillStyle = baseGradient;
  ctx.fillRect(0, 0, width, height);

  const moonGlow = ctx.createRadialGradient(width * 0.72, height * 0.28, 0, width * 0.72, height * 0.28, width * 0.22);
  moonGlow.addColorStop(0, "rgba(132, 165, 210, 0.10)");
  moonGlow.addColorStop(0.45, "rgba(88, 122, 176, 0.05)");
  moonGlow.addColorStop(1, "rgba(0, 0, 0, 0)");
  ctx.fillStyle = moonGlow;
  ctx.fillRect(0, 0, width, height);

  const nebulae = [
    { x: 0.18, y: 0.24, r: 0.22, color: "110,135,186", alpha: 0.08 },
    { x: 0.48, y: 0.18, r: 0.16, color: "97,121,168", alpha: 0.06 },
    { x: 0.82, y: 0.34, r: 0.18, color: "80,109,152", alpha: 0.05 },
    { x: 0.58, y: 0.62, r: 0.28, color: "70,98,146", alpha: 0.04 },
  ];

  nebulae.forEach(({ x, y, r, color, alpha }) => {
    const gradient = ctx.createRadialGradient(width * x, height * y, 0, width * x, height * y, width * r);
    gradient.addColorStop(0, `rgba(${color}, ${alpha})`);
    gradient.addColorStop(0.35, `rgba(${color}, ${alpha * 0.6})`);
    gradient.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);
  });

  for (let index = 0; index < 520; index += 1) {
    const x = Math.random() * width;
    const y = Math.pow(Math.random(), 0.72) * height * 0.82;
    const radius = Math.random() * 1.35 + 0.2;
    const alpha = Math.random() * 0.32 + 0.08;
    const hue = 210 + Math.random() * 40;
    ctx.beginPath();
    ctx.fillStyle = `hsla(${hue}, 35%, ${68 + Math.random() * 20}%, ${alpha})`;
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.lineWidth = 1.2;
  ctx.strokeStyle = "rgba(108, 138, 186, 0.07)";
  for (let index = 0; index < 4; index += 1) {
    ctx.beginPath();
    const startX = width * (0.08 + index * 0.22);
    const startY = height * (0.18 + Math.random() * 0.18);
    ctx.moveTo(startX, startY);
    for (let step = 1; step <= 6; step += 1) {
      const px = startX + step * (width * 0.06) + (Math.random() - 0.5) * width * 0.03;
      const py = startY + (Math.random() - 0.5) * height * 0.08;
      ctx.lineTo(px, py);
    }
    ctx.stroke();
  }

  const mist = ctx.createLinearGradient(0, height * 0.55, 0, height);
  mist.addColorStop(0, "rgba(40, 55, 86, 0)");
  mist.addColorStop(0.45, "rgba(26, 36, 56, 0.08)");
  mist.addColorStop(1, "rgba(7, 10, 18, 0.22)");
  ctx.fillStyle = mist;
  ctx.fillRect(0, height * 0.5, width, height * 0.5);

  ctx.fillStyle = "rgba(7, 10, 18, 0.96)";
  ctx.beginPath();
  ctx.moveTo(0, height * 0.78);
  for (let x = 0; x <= width; x += width / 18) {
    const peak = height * (0.68 + Math.random() * 0.16);
    const mid = x + width / 36;
    ctx.quadraticCurveTo(mid, peak, x + width / 18, height * (0.76 + Math.random() * 0.1));
  }
  ctx.lineTo(width, height);
  ctx.lineTo(0, height);
  ctx.closePath();
  ctx.fill();

  const horizonGlow = ctx.createLinearGradient(0, height * 0.68, 0, height * 0.82);
  horizonGlow.addColorStop(0, "rgba(76, 105, 154, 0)");
  horizonGlow.addColorStop(0.5, "rgba(62, 88, 126, 0.07)");
  horizonGlow.addColorStop(1, "rgba(0, 0, 0, 0)");
  ctx.fillStyle = horizonGlow;
  ctx.fillRect(0, height * 0.62, width, height * 0.25);

  const vignette = ctx.createRadialGradient(width * 0.5, height * 0.46, width * 0.18, width * 0.5, height * 0.5, width * 0.72);
  vignette.addColorStop(0, "rgba(0, 0, 0, 0)");
  vignette.addColorStop(1, "rgba(0, 0, 0, 0.28)");
  ctx.fillStyle = vignette;
  ctx.fillRect(0, 0, width, height);

  const texture = new THREE.CanvasTexture(canvas);
  texture.mapping = THREE.EquirectangularReflectionMapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}

function spiralIntroPosition(index: number, total: number, shellRadius: number) {
  const safeTotal = Math.max(total, 2);
  const normalizedIndex = index / (safeTotal - 1);
  const angle = normalizedIndex * Math.PI * 2 * 4.5;
  const radius = lerp(shellRadius * 0.08, shellRadius * 0.58, Math.sqrt(normalizedIndex));
  const depth = Math.sin(angle * 0.62) * shellRadius * 0.18;

  return {
    x: Math.cos(angle) * radius,
    y: Math.sin(angle) * radius,
    z: depth,
  };
}

function prepareGraphData(raw: GraphData, excludeProtagonist: boolean) {
  const visibleNodeIds = new Set(
    raw.nodes
      .filter((node) => !excludeProtagonist || node.id !== HAN_LI_ID)
      .map((node) => node.id),
  );

  const visibleLinks = raw.edges.filter(
    (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target),
  );

  const degrees = new Map<string, number>();
  const adjacency = new Map<string, { neighbors: string[]; links: string[] }>();

  visibleLinks.forEach((edge, index) => {
    degrees.set(edge.source, (degrees.get(edge.source) ?? 0) + 1);
    degrees.set(edge.target, (degrees.get(edge.target) ?? 0) + 1);

    const linkId = `link-${index}-${edge.source}-${edge.target}`;
    const sourceAdj = adjacency.get(edge.source) ?? { neighbors: [], links: [] };
    sourceAdj.neighbors.push(edge.target);
    sourceAdj.links.push(linkId);
    adjacency.set(edge.source, sourceAdj);

    const targetAdj = adjacency.get(edge.target) ?? { neighbors: [], links: [] };
    targetAdj.neighbors.push(edge.source);
    targetAdj.links.push(linkId);
    adjacency.set(edge.target, targetAdj);
  });

  const sortedDegrees = Array.from(degrees.values()).sort((a, b) => b - a);
  const topTwoPercentThreshold = percentileThreshold(sortedDegrees, 0.02);
  const topEightPercentThreshold = percentileThreshold(sortedDegrees, 0.08);

  const nodes = raw.nodes
    .filter((node) => visibleNodeIds.has(node.id))
    .map((node) => {
      const degree = degrees.get(node.id) ?? 0;
      const isMajor = node.properties?.is_major === true;
      const baseSize = nodeSizeForDegree(degree, isMajor);
      const eliteBoost = degree >= topTwoPercentThreshold && degree > 0 ? 1.12 : degree >= topEightPercentThreshold && degree > 0 ? 1.06 : 1;
      const val = Number((baseSize * eliteBoost).toFixed(2));

      return {
        ...node,
        name: node.label,
        group: node.type,
        degree,
        val,
        color: nodeColorFor(node),
      };
    });

  const links = visibleLinks.map((edge, index) => ({
    ...edge,
    id: `link-${index}-${edge.source}-${edge.target}`,
    name: relationName(edge),
    color: LINK_COLOR,
  }));

  return {
    nodes,
    links,
    adjacency,
    nodeMap: new Map(nodes.map((node) => [node.id, node])),
  } satisfies PreparedGraph;
}

export default function GraphV3View({ initialSearchParams }: GraphV3ViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<ForceGraph3DInstance<Graph3DNode, Graph3DLink> | null>(null);
  const shouldPlayIntroRef = useRef(false);
  const hasTrackedViewRef = useRef(false);
  const lastReportedChapterFilterRef = useRef<string | null>(null);

  const centerId = typeof initialSearchParams.center_id === "string" ? initialSearchParams.center_id : null;
  const initialCenterId = typeof centerId === "string" && centerId.length > 0 ? centerId : null;

  const [excludeProtagonist, setExcludeProtagonist] = useState(false);
  const [chapterInput, setChapterInput] = useState("");
  const [maxChapter, setMaxChapter] = useState(FALLBACK_MAX_CHAPTER);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [rawGraph, setRawGraph] = useState<GraphData | null>(null);
  const [preparedGraph, setPreparedGraph] = useState<PreparedGraph | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(initialCenterId);
  const [searchText, setSearchText] = useState("");
  const deferredChapterInput = useDeferredValue(chapterInput);
  const chapterSliderValue = chapterInput.trim() ? Number(chapterInput) : 0;
  const chapterSliderPercent = maxChapter > 0 ? (Math.max(0, Math.min(chapterSliderValue, maxChapter)) / maxChapter) * 100 : 0;

  function clampChapterValue(raw: string) {
    const digits = raw.replace(/[^\d]/g, "");
    if (!digits) return "";
    return String(Math.min(Number(digits), maxChapter));
  }

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const introWindow = window as Window & { __amoGraphV3NodeIntroShown?: boolean };
    if (mediaQuery.matches || introWindow.__amoGraphV3NodeIntroShown) return;
    introWindow.__amoGraphV3NodeIntroShown = true;
    shouldPlayIntroRef.current = true;
  }, []);

  useEffect(() => {
    let cancelled = false;

    apiFetch<Stats>("/stats")
      .then((stats) => {
        if (cancelled) return;
        setMaxChapter(Math.max(1, stats.max_chapter || FALLBACK_MAX_CHAPTER));
      })
      .catch(() => {
        if (cancelled) return;
        setMaxChapter(FALLBACK_MAX_CHAPTER);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!chapterInput.trim()) return;
    if (Number(chapterInput) <= maxChapter) return;
    setChapterInput(String(maxChapter));
  }, [chapterInput, maxChapter]);

  useEffect(() => {
    let cancelled = false;

    async function loadGraph() {
      setLoading(true);
      setError("");

      try {
        const params = new URLSearchParams({
          limit: initialCenterId ? "260" : "1000",
          node_types: "Character",
        });

        if (initialCenterId) {
          params.set("center_id", initialCenterId);
          params.set("depth", "2");
        }

        if (deferredChapterInput.trim()) {
          params.set("chapter_max", deferredChapterInput.trim());
        }

        const data = await apiFetch<GraphData>(`/graph?${params.toString()}`);
        if (cancelled) return;

        setRawGraph(data);
        setSelectedNodeId((prev) => prev ?? initialCenterId);
      } catch (loadError) {
        console.error("Failed to load graph V3:", loadError);
        if (!cancelled) {
          setError("3D 图谱加载失败，请稍后重试。");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadGraph();

    return () => {
      cancelled = true;
    };
  }, [deferredChapterInput, initialCenterId]);

  useEffect(() => {
    if (!rawGraph) {
      setPreparedGraph(null);
      return;
    }
    setPreparedGraph(prepareGraphData(rawGraph, excludeProtagonist));
  }, [excludeProtagonist, rawGraph]);

  useEffect(() => {
    if (!preparedGraph) return;
    if (selectedNodeId && preparedGraph.nodeMap.has(selectedNodeId)) return;
    if (preparedGraph.nodes.length === 0) {
      setSelectedNodeId(null);
      return;
    }
    if (initialCenterId && preparedGraph.nodeMap.has(initialCenterId)) {
      setSelectedNodeId(initialCenterId);
      return;
    }
    setSelectedNodeId(null);
  }, [initialCenterId, preparedGraph, selectedNodeId]);

  useEffect(() => {
    if (!preparedGraph || hasTrackedViewRef.current) return;
    hasTrackedViewRef.current = true;
    captureEvent("graph_v3_viewed", {
      node_count: preparedGraph.nodes.length,
      link_count: preparedGraph.links.length,
      initial_center_id: initialCenterId,
      chapter_filter: deferredChapterInput.trim() || null,
      exclude_protagonist: excludeProtagonist,
    });
  }, [deferredChapterInput, excludeProtagonist, initialCenterId, preparedGraph]);

  useEffect(() => {
    if (!preparedGraph) return;
    const currentValue = deferredChapterInput.trim() || null;
    if (lastReportedChapterFilterRef.current === null) {
      lastReportedChapterFilterRef.current = currentValue;
      return;
    }
    if (lastReportedChapterFilterRef.current === currentValue) return;
    lastReportedChapterFilterRef.current = currentValue;
    captureEvent("graph_v3_chapter_filter_changed", {
      chapter_filter: currentValue,
      node_count: preparedGraph.nodes.length,
      link_count: preparedGraph.links.length,
    });
  }, [deferredChapterInput, preparedGraph]);

  const searchResults = useMemo(() => {
    if (!preparedGraph || !searchText.trim()) return [];
    const query = searchText.trim().toLowerCase();
    return preparedGraph.nodes
      .filter((node) => node.label.toLowerCase().includes(query))
      .slice(0, 8);
  }, [preparedGraph, searchText]);

  const selectedNode = selectedNodeId && preparedGraph ? preparedGraph.nodeMap.get(selectedNodeId) ?? null : null;
  const selectedRelations = useMemo(() => {
    if (!preparedGraph || !selectedNodeId) return [];
    return preparedGraph.links
      .filter((link) => link.source === selectedNodeId || link.target === selectedNodeId)
      .map((link) => {
        const targetId = link.source === selectedNodeId ? link.target : link.source;
        const targetNode = preparedGraph.nodeMap.get(targetId);
        return {
          link,
          targetNode,
        };
      })
      .filter((item) => item.targetNode)
      .sort((a, b) => (b.targetNode?.degree ?? 0) - (a.targetNode?.degree ?? 0));
  }, [preparedGraph, selectedNodeId]);

  const typeSummary = useMemo(() => {
    if (!preparedGraph) return [];
    const counts = new Map<string, number>();
    preparedGraph.nodes.forEach((node) => {
      counts.set(node.type, (counts.get(node.type) ?? 0) + 1);
    });
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [preparedGraph]);

  function getLiveNode(nodeId: string) {
    const liveNodes = graphRef.current?.graphData().nodes as Graph3DNode[] | undefined;
    return liveNodes?.find((node) => node.id === nodeId) ?? preparedGraph?.nodeMap.get(nodeId) ?? null;
  }

  function focusCameraOnNode(nodeId: string) {
    const graph = graphRef.current;
    const node = getLiveNode(nodeId);
    if (!graph || !node) return;

    const { x = 0, y = 0, z = 0 } = node;
    const distance = 160;
    const nodeDistance = Math.hypot(x, y, z) || 1;
    const distRatio = 1 + distance / nodeDistance;

    graph.cameraPosition(
      {
        x: x * distRatio,
        y: y * distRatio,
        z: z * distRatio,
      },
      { x, y, z },
      800,
    );
  }

  useEffect(() => {
    if (!preparedGraph || !containerRef.current) return;

    const graphData = preparedGraph;
    let resizeObserver: ResizeObserver | null = null;
    let disposed = false;
    let backgroundTexture: { dispose: () => void } | null = null;
    let introFrameId: number | null = null;

    async function mountGraph() {
      const [{ default: ForceGraph3D }, THREE] = await Promise.all([import("3d-force-graph"), import("three")]);
      if (disposed || !containerRef.current) return;

      graphRef.current?._destructor();
      containerRef.current.innerHTML = "";

      const graph = new ForceGraph3D(
        containerRef.current,
      ) as unknown as ForceGraph3DInstance<Graph3DNode, Graph3DLink>;

      graphRef.current = graph;
      const graphWithHelpers = graph as ForceGraph3DInstance<Graph3DNode, Graph3DLink> & {
        refresh?: () => void;
        resetCountdown?: () => void;
      };
      const playIntro = shouldPlayIntroRef.current;
      shouldPlayIntroRef.current = false;

      const shellRadius = Math.max(380, Math.min(760, Math.sqrt(graphData.nodes.length) * 30));
      const maxDegree = Math.max(...graphData.nodes.map((node) => node.degree), 1);
      const targetNodes = graphData.nodes.map((node, index) => {
        const radius = shellRadius * radialFactorForNode(node, maxDegree);
        return {
          ...node,
          ...fibonacciSpherePosition(index, graphData.nodes.length, radius),
        };
      });
      const introNodes = targetNodes.map((node, index) => {
        if (!playIntro) return { ...node };
        const introPosition = spiralIntroPosition(index, graphData.nodes.length, shellRadius);
        return {
          ...node,
          ...introPosition,
          fx: introPosition.x,
          fy: introPosition.y,
          fz: introPosition.z,
        };
      });
      const renderData = {
        nodes: introNodes,
        links: graphData.links.map((link) => ({ ...link })),
      };

      const applyCenterFocus = (delay: number) => {
        if (!initialCenterId) return;
        window.setTimeout(() => {
          const liveNode = (graph.graphData().nodes as Graph3DNode[]).find((node) => node.id === initialCenterId);
          if (!liveNode) return;

          const { x = 0, y = 0, z = 0 } = liveNode;
          const distance = 160;
          const nodeDistance = Math.hypot(x, y, z) || 1;
          const distRatio = 1 + distance / nodeDistance;

          graph.cameraPosition(
            {
              x: x * distRatio,
              y: y * distRatio,
              z: z * distRatio,
            },
            { x, y, z },
            800,
          );
        }, delay);
      };

      const completeIntro = () => {
        const liveNodes = graph.graphData().nodes as Graph3DNode[];
        const targetNodeMap = new Map(targetNodes.map((node) => [node.id, node]));

        liveNodes.forEach((node) => {
          const targetNode = targetNodeMap.get(node.id);
          if (!targetNode) return;
          node.x = targetNode.x;
          node.y = targetNode.y;
          node.z = targetNode.z;
          delete node.fx;
          delete node.fy;
          delete node.fz;
        });

        graph.linkOpacity(GRAPH_LINK_OPACITY);
        graph.enableNodeDrag(true);
        graph.d3ReheatSimulation();
        graphWithHelpers.resetCountdown?.();
        graph.zoomToFit(900, 180);
        applyCenterFocus(320);
      };

      const runIntroTransition = () => {
        const liveNodes = graph.graphData().nodes as Graph3DNode[];
        const targetNodeMap = new Map(targetNodes.map((node) => [node.id, node]));
        const introNodeMap = new Map(introNodes.map((node) => [node.id, node]));
        const startedAt = performance.now();

        const animate = (timestamp: number) => {
          const rawProgress = Math.min((timestamp - startedAt) / SPIRAL_INTRO_DURATION_MS, 1);
          const progress = easeInOutCubic(rawProgress);

          liveNodes.forEach((node) => {
            const introNode = introNodeMap.get(node.id);
            const targetNode = targetNodeMap.get(node.id);
            if (!introNode || !targetNode) return;

            const nextX = lerp(introNode.x ?? 0, targetNode.x ?? 0, progress);
            const nextY = lerp(introNode.y ?? 0, targetNode.y ?? 0, progress);
            const nextZ = lerp(introNode.z ?? 0, targetNode.z ?? 0, progress);

            node.x = nextX;
            node.y = nextY;
            node.z = nextZ;
            node.fx = nextX;
            node.fy = nextY;
            node.fz = nextZ;
          });

          graph.linkOpacity(GRAPH_LINK_OPACITY * Math.max(0, (rawProgress - 0.45) / 0.55));
          graphWithHelpers.refresh?.();

          if (rawProgress >= 1) {
            completeIntro();
            return;
          }

          introFrameId = window.requestAnimationFrame(animate);
        };

        graph.zoomToFit(700, 120);
        introFrameId = window.requestAnimationFrame(animate);
      };

      backgroundTexture = createImmortalNightPanoramaTexture(THREE);
      if (backgroundTexture) {
        graph.scene().background = backgroundTexture as never;
      }

      graph
        .graphData(renderData)
        .backgroundColor("#040712")
        .showNavInfo(false)
        .nodeLabel(
          (node) =>
            `<div style="padding:6px 8px;border-radius:10px;background:rgba(2,6,23,0.9);border:1px solid rgba(148,163,184,0.25)">
              <div style="font-weight:700;color:#f8fafc">${node.label}</div>
              <div style="margin-top:2px;font-size:12px;color:#94a3b8">${node.type} · 连接 ${node.degree}</div>
            </div>`,
        )
        .linkLabel(
          (link) =>
            `<div style="padding:6px 8px;border-radius:10px;background:rgba(2,6,23,0.9);border:1px solid rgba(148,163,184,0.25)">
              <div style="font-weight:700;color:#f8fafc">${link.name}</div>
              <div style="margin-top:2px;font-size:12px;color:#94a3b8">${link.source} → ${link.target}</div>
            </div>`,
        )
        .nodeRelSize(2.55)
        .nodeVal((node) => node.val)
        .nodeOpacity(0.9)
        .nodeResolution(8)
        .enableNodeDrag(!playIntro)
        .nodeColor((node) => node.color)
        .linkWidth(0)
        .linkOpacity(playIntro ? 0 : GRAPH_LINK_OPACITY)
        .linkColor((link) => link.color)
        .onNodeClick((node) => {
          captureEvent("graph_v3_node_selected", {
            node_id: node.id,
            node_label: node.label,
            node_type: node.type,
            degree: node.degree,
            source: "canvas_click",
          });
          window.setTimeout(() => setSelectedNodeId(node.id), 0);
        })
        .onNodeDragEnd((node) => {
          captureEvent("graph_v3_node_selected", {
            node_id: node.id,
            node_label: node.label,
            node_type: node.type,
            degree: node.degree,
            source: "drag_end",
          });
          window.setTimeout(() => setSelectedNodeId(node.id), 0);
          graph.d3ReheatSimulation();
          graphWithHelpers.resetCountdown?.();
        })
        .cooldownTime(12000);

      graph.renderer().setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));

      const chargeForce = graph.d3Force("charge") as { strength?: (value: number) => unknown } | undefined;
      chargeForce?.strength?.(-220);

      const linkForce = graph.d3Force("link") as
        | { distance?: (value: number) => unknown; strength?: (value: number) => unknown }
        | undefined;
      linkForce?.distance?.(92);
      linkForce?.strength?.(0.12);

      graph.d3Force(
        "shell",
        createShellForce((node) => shellRadius * radialFactorForNode(node, maxDegree), 0.18),
      );

      graph.d3VelocityDecay(0.36);
      graph.d3AlphaDecay(0.024);
      graph.warmupTicks(90);

      resizeObserver = new ResizeObserver((entries) => {
        const entry = entries[0];
        if (!entry) return;
        const width = Math.max(entry.contentRect.width, 320);
        const height = Math.max(entry.contentRect.height, 480);
        graph.width(width);
        graph.height(height);
      });

      resizeObserver.observe(containerRef.current);
      if (playIntro) {
        runIntroTransition();
      } else {
        graph.zoomToFit(900, 180);
        applyCenterFocus(900);
      }
    }

    void mountGraph();

    return () => {
      disposed = true;
      if (introFrameId) {
        window.cancelAnimationFrame(introFrameId);
      }
      resizeObserver?.disconnect();
      backgroundTexture?.dispose();
      graphRef.current?._destructor();
      graphRef.current = null;
    };
  }, [initialCenterId, preparedGraph]);

  const clearLegacyQuery = buildSearchParams(
    Object.fromEntries(
      Object.entries(initialSearchParams).filter(([key]) => key !== "center_id"),
    ),
  );

  return (
    <div className="mx-auto flex w-full max-w-[1760px] flex-col gap-4 px-4 py-4 lg:px-6">
      <div className="amo-panel rounded-3xl p-4">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.24em] text-emerald-200/80">Graph V3</div>
            <h1 className="mt-1 text-2xl font-semibold text-white/92">3D 关系图谱</h1>
            <p className="mt-2 max-w-2xl text-sm text-white/46">
              基于现有图数据库直接渲染的 3D 力导图。节点可直接拖拽，关联结构会跟随力导布局自然联动。
            </p>
          </div>

          <div className="flex flex-wrap items-start gap-2 text-sm xl:max-w-[860px] xl:justify-end">
            <label className="flex items-center gap-2 rounded-full border border-white/8 bg-white/4 px-3 py-1.5 text-white/82">
              <input
                type="checkbox"
                checked={excludeProtagonist}
                onChange={(event) => {
                  const checked = event.target.checked;
                  setExcludeProtagonist(checked);
                  captureEvent("graph_v3_exclude_protagonist_toggled", {
                    exclude_protagonist: checked,
                  });
                }}
                className="accent-emerald-300"
              />
              排除主角
            </label>
            <div className="w-full rounded-2xl border border-white/8 bg-white/4 px-3 py-2.5 text-white/82 xl:min-w-[560px]">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm">章节截止</span>
                  <span className="rounded-full border border-emerald-200/14 bg-emerald-200/8 px-2 py-0.5 text-[11px] text-emerald-100/78">
                    可直接输入
                  </span>
                </div>
                <input
                  value={chapterInput}
                  onChange={(event) => setChapterInput(clampChapterValue(event.target.value))}
                  placeholder="直接输入章节"
                  className="rounded-full border border-white/8 bg-white/6 px-3 py-1 text-right text-white outline-none transition-colors placeholder:text-white/28 focus:border-emerald-200/22"
                />
              </div>
              <div className="mt-1.5 text-[11px] text-white/36">
                拖动小绿瓶或直接修改右侧数字，效果完全同步。
              </div>
              <div className="mt-3">
                <div className="relative h-11">
                  <div
                    className="pointer-events-none absolute inset-x-0 top-1/2 h-2.5 -translate-y-1/2 rounded-full border border-white/8 bg-white/6"
                    style={{
                      background: `linear-gradient(90deg, rgba(83, 201, 174, 0.34) 0%, rgba(83, 201, 174, 0.34) ${chapterSliderPercent}%, rgba(255,255,255,0.06) ${chapterSliderPercent}%, rgba(255,255,255,0.06) 100%)`,
                    }}
                  />
                  <div
                    className="pointer-events-none absolute top-1/2 z-[1] -translate-y-1/2"
                    style={{
                      left: `clamp(0px, calc(${chapterSliderPercent}% - 18px), calc(100% - 36px))`,
                    }}
                  >
                    <Image
                      src={bottleIcon}
                      alt="章节滑块"
                      width={38}
                      height={38}
                      className="h-9 w-9 object-contain drop-shadow-[0_10px_16px_rgba(7,18,16,0.36)]"
                    />
                  </div>
                <input
                  type="range"
                  min={0}
                  max={maxChapter}
                  step={1}
                  value={Math.max(0, Math.min(chapterSliderValue, maxChapter))}
                  onChange={(event) => {
                    const nextValue = Number(event.target.value);
                    setChapterInput(nextValue <= 0 ? "" : String(nextValue));
                  }}
                  className="amo-range absolute inset-0 z-[2] h-full w-full"
                  aria-label="章节截止滑块"
                />
                </div>
                <div className="mt-1.5 flex items-center justify-between text-[11px] text-white/34">
                  <span>第 1 章</span>
                  <span>第 {Math.max(1, Math.round(maxChapter / 2))} 章</span>
                  <span>第 {maxChapter} 章</span>
                </div>
              </div>
            </div>
            {initialCenterId && (
              <Link
                href={`/graph-v3${clearLegacyQuery}`}
                onClick={() => {
                  captureEvent("graph_v3_center_cleared", {
                    center_id: initialCenterId,
                  });
                }}
                className="rounded-full border border-white/8 bg-white/4 px-3 py-1.5 text-white/82 transition-colors hover:border-emerald-200/18"
              >
                清除角色聚焦
              </Link>
            )}
          </div>
        </div>

        <div className="mt-4 flex flex-col gap-3 md:flex-row md:items-center md:flex-wrap">
          <div className="flex flex-wrap gap-2">
            {typeSummary.length > 1 &&
              typeSummary.map(([type, count]) => (
                <div
                  key={type}
                  className="rounded-full border border-white/8 bg-white/4 px-3 py-1 text-xs text-white/78"
                >
                  <span
                    className="mr-2 inline-block h-2.5 w-2.5 rounded-full align-middle"
                    style={{ backgroundColor: TYPE_ACCENTS[type] ?? TYPE_ACCENTS.Unknown }}
                  />
                  {type} · {count}
                </div>
              ))}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                graphRef.current?.zoomToFit(700, 60);
                captureEvent("graph_v3_camera_reset", {});
              }}
              className="amo-button-secondary rounded-2xl px-4 py-2 text-sm transition-colors"
            >
              重置视角
            </button>
            <input
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
              placeholder="搜索节点并聚焦"
              className="amo-input w-full rounded-2xl px-4 py-2 text-sm md:w-72"
            />
          </div>
        </div>

        {searchResults.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {searchResults.map((node) => (
              <button
                key={node.id}
                type="button"
                onClick={() => {
                  setSelectedNodeId(node.id);
                  setSearchText(node.label);
                  window.requestAnimationFrame(() => focusCameraOnNode(node.id));
                  captureEvent("graph_v3_search_result_selected", {
                    node_id: node.id,
                    node_label: node.label,
                    node_type: node.type,
                  });
                }}
                className="rounded-full border border-white/8 bg-white/4 px-3 py-1 text-xs text-white/82 transition-colors hover:border-emerald-200/18 hover:text-white"
              >
                {node.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="grid min-h-[780px] grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <section className="amo-stage relative overflow-hidden rounded-3xl">
          {loading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#101516]/84 backdrop-blur-sm">
              <div className="text-sm text-white/76">3D 图谱加载中...</div>
            </div>
          )}
          {error && !loading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#101516]/90 px-6 text-center">
              <div className="text-sm text-rose-300">{error}</div>
            </div>
          )}

          <div className="pointer-events-none absolute left-5 top-5 z-[1] rounded-2xl border border-white/8 bg-[#101516]/58 px-4 py-2 text-xs text-white/34 backdrop-blur">
            拖拽节点可重排布局 · 拖动画布旋转 · 滚轮缩放
          </div>
          <div
            ref={containerRef}
            className="h-[780px] w-full"
          />
        </section>

        <aside className="flex flex-col gap-4">
          <section className="amo-panel rounded-3xl p-4">
            <div className="flex items-baseline justify-between">
              <div>
                <div className="text-xs uppercase tracking-[0.24em] text-white/34">Overview</div>
                <div className="mt-1 text-lg font-semibold text-white/92">当前图层</div>
              </div>
              <div className="text-sm text-white/46">
                {preparedGraph?.nodes.length ?? 0} 节点 · {preparedGraph?.links.length ?? 0} 关系
              </div>
            </div>
            <div className="mt-4 grid grid-cols-1 gap-3 text-sm">
              <div className="rounded-2xl border border-white/8 bg-white/4 p-3">
                <div className="text-white/34">章节过滤</div>
                <div className="mt-1 font-medium text-white/92">
                  {chapterInput.trim() ? `≤ 第${chapterInput}章` : "未限制"}
                </div>
              </div>
              <div className="rounded-2xl border border-white/8 bg-white/4 p-3">
                <div className="text-white/34">节点色谱</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {NODE_SPECTRUM.map((color) => (
                    <span
                      key={color}
                      className="inline-block h-4 w-4 rounded-full ring-1 ring-white/14"
                      style={{ backgroundColor: color }}
                    />
                  ))}
                </div>
                <div className="mt-2 text-xs text-white/46">
                  角色节点采用高亮宝石色带，提升识别度，同时保持整体秩序。
                </div>
              </div>
            </div>
          </section>

          <section className="amo-panel flex-1 rounded-3xl p-4">
            {selectedNode ? (
              <>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-xs uppercase tracking-[0.24em] text-white/34">Selected</div>
                    <h2 className="mt-1 text-xl font-semibold text-white/92">{selectedNode.label}</h2>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                      <span className="rounded-full border border-white/8 bg-white/4 px-2.5 py-1 text-white/78">
                        {selectedNode.type}
                      </span>
                      <span className="text-white/46">连接 {selectedNode.degree}</span>
                    </div>
                  </div>
                  <span
                    className="inline-block h-3.5 w-3.5 rounded-full"
                    style={{ backgroundColor: selectedNode.color }}
                  />
                </div>

                <div className="mt-4 flex gap-2">
                  {selectedNode.type === "Character" && (
                    <Link
                      href={`/character/${selectedNode.id}`}
                      onClick={() => {
                        captureEvent("graph_v3_character_detail_clicked", {
                          node_id: selectedNode.id,
                          node_label: selectedNode.label,
                        });
                      }}
                      className="amo-button-primary rounded-2xl px-3 py-2 text-sm transition-colors"
                    >
                      查看角色详情
                    </Link>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      focusCameraOnNode(selectedNode.id);
                    }}
                    className="amo-button-secondary rounded-2xl px-3 py-2 text-sm transition-colors"
                  >
                    聚焦镜头
                  </button>
                </div>

                <div className="mt-5">
                  <div className="mb-2 text-xs uppercase tracking-[0.22em] text-white/34">
                    关联关系 ({selectedRelations.length})
                  </div>
                  <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
                    {selectedRelations.map(({ link, targetNode }) => (
                      <button
                        key={link.id}
                        type="button"
                        onClick={() => {
                          if (!targetNode) return;
                          setSelectedNodeId(targetNode.id);
                          captureEvent("graph_v3_relation_clicked", {
                            source_node_id: selectedNode.id,
                            source_node_label: selectedNode.label,
                            target_node_id: targetNode.id,
                            target_node_label: targetNode.label,
                            relation_name: link.name,
                          });
                        }}
                        className="w-full rounded-2xl border border-white/8 bg-white/4 p-3 text-left transition-colors hover:border-emerald-200/18 hover:bg-white/6"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="font-medium text-white/92">{targetNode?.label}</div>
                            <div className="mt-1 text-xs text-white/46">
                              {link.name}
                              {typeof link.properties?.since_chapter === "number" &&
                                ` · 第${String(link.properties.since_chapter)}章起`}
                            </div>
                          </div>
                          <span
                            className="mt-1 inline-block h-2.5 w-2.5 rounded-full"
                            style={{ backgroundColor: targetNode?.color ?? TYPE_ACCENTS.Unknown }}
                          />
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <div className="flex h-full min-h-[320px] items-center justify-center text-sm text-white/34">
                点击一个节点查看详情
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
