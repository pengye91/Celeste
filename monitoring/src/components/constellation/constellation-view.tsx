"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Panel } from "@/components/ui/panel";
import { StatusOrb } from "@/components/ui/status-orb";
import { cn } from "@/lib/utils";
import RotateCcw from "lucide-react/dist/esm/icons/rotate-ccw";
import ChevronRight from "lucide-react/dist/esm/icons/chevron-right";

export interface ConstellationNode {
  name: string;
  status: string;
  dependencies?: string[];
  task_type?: string;
  command?: string;
  arguments?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
}

interface ConstellationViewProps {
  nodes: ConstellationNode[];
  selectedNode?: ConstellationNode | null;
  onNodeSelect?: (node: ConstellationNode | undefined) => void;
  activeNodeName?: string;
  reducedMotion?: boolean;
}

/* ───────────────────────────────────────────────
   Deterministic hash (FNV-1a) for stable jitter
   ─────────────────────────────────────────────── */
function fnv1a(str: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    hash ^= str.charCodeAt(i);
    hash += (hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24);
  }
  return hash >>> 0;
}

function hashFloat(name: string, seed = 0): number {
  const h = fnv1a(name + String(seed));
  return (h % 10000) / 10000; // 0..1
}

/* ───────────────────────────────────────────────
   Layout engine: layered DAG
   ─────────────────────────────────────────────── */
interface NodeLayout {
  name: string;
  x: number;
  y: number;
  layer: number;
  indexInLayer: number;
}

const LAYER_HEIGHT = 120;
const NODE_SPACING = 140;
const CANVAS_PADDING = 80;

function computeLayout(nodes: ConstellationNode[]): Map<string, NodeLayout> {
  const layout = new Map<string, NodeLayout>();
  if (nodes.length === 0) return layout;

  // Build adjacency
  const depsMap = new Map<string, Set<string>>();
  const allNames = new Set(nodes.map((n) => n.name));
  for (const n of nodes) {
    depsMap.set(n.name, new Set(n.dependencies?.filter((d) => allNames.has(d)) ?? []));
  }

  // Kahn's algorithm for layering
  const inDegree = new Map<string, number>();
  for (const n of nodes) inDegree.set(n.name, 0);
  for (const [name, deps] of depsMap) {
    inDegree.set(name, (inDegree.get(name) ?? 0) + deps.size);
  }

  const layers: string[][] = [];
  let queue = nodes.filter((n) => (inDegree.get(n.name) ?? 0) === 0).map((n) => n.name);
  queue.sort((a, b) => a.localeCompare(b));

  const remainingInDegree = new Map(inDegree);
  const processed = new Set<string>();

  while (queue.length > 0) {
    const layer: string[] = [];
    const nextQueue: string[] = [];
    for (const name of queue) {
      if (processed.has(name)) continue;
      processed.add(name);
      layer.push(name);
      for (const [child, childDeps] of depsMap) {
        if (childDeps.has(name)) {
          const newDeg = (remainingInDegree.get(child) ?? 0) - 1;
          remainingInDegree.set(child, newDeg);
          if (newDeg === 0) nextQueue.push(child);
        }
      }
    }
    if (layer.length === 0) break;
    layer.sort((a, b) => a.localeCompare(b));
    layers.push(layer);
    nextQueue.sort((a, b) => a.localeCompare(b));
    queue = nextQueue;
  }

  // Any remaining nodes (cycles) — force them into last layer
  for (const n of nodes) {
    if (!processed.has(n.name)) {
      const lastLayer = layers[layers.length - 1];
      if (lastLayer) lastLayer.push(n.name);
      else layers.push([n.name]);
    }
  }

  // Compute positions
  for (let layerIdx = 0; layerIdx < layers.length; layerIdx++) {
    const layer = layers[layerIdx];
    const layerWidth = layer.length * NODE_SPACING;
    const startX = -layerWidth / 2 + NODE_SPACING / 2;

    for (let i = 0; i < layer.length; i++) {
      const name = layer[i];
      const jitter = (hashFloat(name, 0) - 0.5) * NODE_SPACING * 0.6;
      const x = startX + i * NODE_SPACING + jitter;
      const y = layerIdx * LAYER_HEIGHT;
      layout.set(name, { name, x, y, layer: layerIdx, indexInLayer: i });
    }
  }

  return layout;
}

/* ───────────────────────────────────────────────
   Status helpers
   ─────────────────────────────────────────────── */
function statusToVariant(status: string): "idle" | "running" | "success" | "error" | "warning" | "info" {
  switch (status.toLowerCase()) {
    case "running":
      return "running";
    case "completed":
      return "success";
    case "failed":
      return "error";
    case "paused":
      return "warning";
    case "pending":
    default:
      return "idle";
  }
}

function statusToOrbColor(status: string): string {
  switch (status.toLowerCase()) {
    case "running":
      return "#00d4aa";
    case "completed":
      return "#6b5ce7";
    case "failed":
      return "#e8453c";
    case "paused":
      return "#f5a623";
    case "pending":
    default:
      return "#2d2d44";
  }
}

function statusToGlowFilter(status: string): string {
  switch (status.toLowerCase()) {
    case "running":
      return "url(#glow-aurora)";
    case "completed":
      return "url(#glow-nebula)";
    case "failed":
      return "url(#glow-mars)";
    case "paused":
      return "url(#glow-solar)";
    case "pending":
    default:
      return "";
  }
}

/* ───────────────────────────────────────────────
   Mobile hook
   ─────────────────────────────────────────────── */
function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);
  return isMobile;
}

/* ───────────────────────────────────────────────
   Main component
   ─────────────────────────────────────────────── */
export function ConstellationView({
  nodes,
  selectedNode,
  onNodeSelect,
  activeNodeName,
  reducedMotion,
}: ConstellationViewProps) {
  const isMobile = useIsMobile();
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, tx: 0, ty: 0 });
  const [focusedIndex, setFocusedIndex] = useState(0);
  const idPrefix = useId();

  const layout = useMemo(() => computeLayout(nodes), [nodes]);

  // Default view: fit all nodes
  useEffect(() => {
    if (nodes.length === 0 || isMobile) return;
    const xs: number[] = [];
    const ys: number[] = [];
    for (const l of layout.values()) {
      xs.push(l.x);
      ys.push(l.y);
    }
    if (xs.length === 0) return;
    const minX = Math.min(...xs) - 60;
    const maxX = Math.max(...xs) + 60;
    const minY = Math.min(...ys) - 60;
    const maxY = Math.max(...ys) + 60;

    const container = containerRef.current;
    if (!container) return;
    const cw = container.clientWidth;
    const ch = container.clientHeight;
    const contentW = maxX - minX;
    const contentH = maxY - minY;
    const scale = Math.min((cw - CANVAS_PADDING * 2) / contentW, (ch - CANVAS_PADDING * 2) / contentH, 1.5);
    const tx = cw / 2 - (minX + contentW / 2) * scale;
    const ty = ch / 2 - (minY + contentH / 2) * scale;
    setTransform({ x: tx, y: ty, k: scale });
  }, [layout, nodes.length, isMobile]);

  // Pan handlers
  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.button !== 0) return;
      setDragging(true);
      dragStart.current = { x: e.clientX, y: e.clientY, tx: transform.x, ty: transform.y };
    },
    [transform]
  );

  const onMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!dragging) return;
      const dx = e.clientX - dragStart.current.x;
      const dy = e.clientY - dragStart.current.y;
      setTransform((t) => ({ ...t, x: dragStart.current.tx + dx, y: dragStart.current.ty + dy }));
    },
    [dragging]
  );

  const onMouseUp = useCallback(() => setDragging(false), []);

  const onWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      const svg = svgRef.current;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      const newK = Math.max(0.2, Math.min(5, transform.k * delta));
      const newX = mx - (mx - transform.x) * (newK / transform.k);
      const newY = my - (my - transform.y) * (newK / transform.k);
      setTransform({ x: newX, y: newY, k: newK });
    },
    [transform]
  );

  // Keyboard navigation
  useEffect(() => {
    if (isMobile) return;
    const handleKey = (e: KeyboardEvent) => {
      if (nodes.length === 0) return;
      if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) {
        e.preventDefault();
        const sorted = [...nodes].sort((a, b) => a.name.localeCompare(b.name));
        let idx = focusedIndex;
        if (e.key === "ArrowDown" || e.key === "ArrowRight") {
          idx = (focusedIndex + 1) % sorted.length;
        } else {
          idx = (focusedIndex - 1 + sorted.length) % sorted.length;
        }
        setFocusedIndex(idx);
        const node = sorted[idx];
        const l = layout.get(node.name);
        if (l && containerRef.current) {
          const cw = containerRef.current.clientWidth;
          const ch = containerRef.current.clientHeight;
          const targetX = cw / 2 - l.x * transform.k;
          const targetY = ch / 2 - l.y * transform.k;
          setTransform({ x: targetX, y: targetY, k: transform.k });
        }
      }
      if (e.key === "Enter") {
        const sorted = [...nodes].sort((a, b) => a.name.localeCompare(b.name));
        onNodeSelect?.(sorted[focusedIndex]);
      }
      if (e.key === "Escape") {
        onNodeSelect?.(undefined);
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [isMobile, nodes, focusedIndex, layout, onNodeSelect, transform.k]);

  const resetView = useCallback(() => {
    if (nodes.length === 0) return;
    const xs: number[] = [];
    const ys: number[] = [];
    for (const l of layout.values()) {
      xs.push(l.x);
      ys.push(l.y);
    }
    const minX = Math.min(...xs) - 60;
    const maxX = Math.max(...xs) + 60;
    const minY = Math.min(...ys) - 60;
    const maxY = Math.max(...ys) + 60;
    const container = containerRef.current;
    if (!container) return;
    const cw = container.clientWidth;
    const ch = container.clientHeight;
    const contentW = maxX - minX;
    const contentH = maxY - minY;
    const scale = Math.min((cw - CANVAS_PADDING * 2) / contentW, (ch - CANVAS_PADDING * 2) / contentH, 1.5);
    const tx = cw / 2 - (minX + contentW / 2) * scale;
    const ty = ch / 2 - (minY + contentH / 2) * scale;
    setTransform({ x: tx, y: ty, k: scale });
  }, [layout, nodes.length]);

  /* ─────────── Mobile fallback ─────────── */
  if (isMobile) {
    const sorted = [...nodes].sort((a, b) => {
      const aActive = a.name === activeNodeName ? -1 : 0;
      const bActive = b.name === activeNodeName ? -1 : 0;
      if (aActive !== bActive) return aActive - bActive;
      const aDeps = a.dependencies?.length ?? 0;
      const bDeps = b.dependencies?.length ?? 0;
      return aDeps - bDeps;
    });

    return (
      <div className="flex flex-col h-full">
        <div aria-live="polite" className="sr-only">
          {selectedNode ? `Selected node ${selectedNode.name}, status ${selectedNode.status}` : "No node selected"}
        </div>
        <div className="flex-1 overflow-y-auto">
          {sorted.length === 0 ? (
            <Panel padding="lg" className="text-center text-comet-500">
              <p className="text-sm">No nodes in this workflow</p>
            </Panel>
          ) : (
            <div className="divide-y divide-space-500/30">
              {sorted.map((node) => {
                const isActive = node.name === activeNodeName;
                const isSelected = selectedNode?.name === node.name;
                return (
                  <button
                    key={node.name}
                    onClick={() => onNodeSelect?.(node)}
                    className={cn(
                      "w-full flex items-center gap-3 px-4 py-3 text-left transition-colors",
                      "hover:bg-space-700/50 focus:outline-none focus:ring-2 focus:ring-aurora-500 focus:ring-inset",
                      isSelected && "bg-space-700/80"
                    )}
                    aria-label={`Node ${node.name}, status ${node.status}${isActive ? ", active" : ""}`}
                    role="button"
                  >
                    <StatusOrb variant={statusToVariant(node.status)} pulse={node.status === "running"} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-comet-100 truncate">{node.name}</div>
                      {node.task_type && (
                        <div className="text-xs text-comet-500 truncate">{node.task_type}</div>
                      )}
                    </div>
                    <ChevronRight className="w-4 h-4 text-comet-500 shrink-0" />
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    );
  }

  /* ─────────── SVG renderer ─────────── */
  const edges: { from: NodeLayout; to: NodeLayout }[] = [];
  for (const node of nodes) {
    const to = layout.get(node.name);
    if (!to) continue;
    for (const depName of node.dependencies ?? []) {
      const from = layout.get(depName);
      if (from) edges.push({ from, to });
    }
  }

  const sortedNodes = [...nodes].sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div ref={containerRef} className="relative w-full h-full overflow-hidden bg-space-void select-none">
      {/* aria-live region */}
      <div aria-live="polite" className="sr-only">
        {selectedNode ? `Selected node ${selectedNode.name}, status ${selectedNode.status}` : "No node selected"}
      </div>

      {/* Reset button */}
      <button
        onClick={resetView}
        className="absolute top-3 right-3 z-10 flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-space-800/80 border border-space-500 text-xs text-comet-300 hover:bg-space-700 hover:border-aurora-500/50 transition-colors focus:outline-none focus:ring-2 focus:ring-aurora-500"
        aria-label="Reset view"
      >
        <RotateCcw className="w-3.5 h-3.5" />
        Reset view
      </button>

      <svg
        ref={svgRef}
        className="w-full h-full cursor-grab active:cursor-grabbing"
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
        onWheel={onWheel}
        role="img"
        aria-label="Constellation DAG view"
      >
        <defs>
          {/* Glow filters */}
          <filter id={`${idPrefix}-glow-aurora`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id={`${idPrefix}-glow-nebula`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id={`${idPrefix}-glow-mars`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id={`${idPrefix}-glow-solar`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <g transform={`translate(${transform.x}, ${transform.y}) scale(${transform.k})`}>
          {/* Edges */}
          {edges.map((edge, i) => {
            const isRunningSource =
              sortedNodes.find((n) => n.name === edge.from.name)?.status === "running";
            return (
              <g key={`edge-${i}`}>
                <line
                  x1={edge.from.x}
                  y1={edge.from.y}
                  x2={edge.to.x}
                  y2={edge.to.y}
                  stroke="rgba(45, 45, 68, 0.6)"
                  strokeWidth={1}
                />
                {/* Particle on running-source edges */}
                {isRunningSource && !reducedMotion && (
                  <circle r={2} fill="#00d4aa" opacity={0.8}>
                    <animateMotion
                      dur={`${3 + hashFloat(edge.from.name + edge.to.name, 1) * 2}s`}
                      repeatCount="indefinite"
                      path={`M${edge.from.x},${edge.from.y} L${edge.to.x},${edge.to.y}`}
                    />
                  </circle>
                )}
              </g>
            );
          })}

          {/* Nodes */}
          {nodes.map((node) => {
            const l = layout.get(node.name);
            if (!l) return null;
            const isSelected = selectedNode?.name === node.name;
            const isFocused = sortedNodes[focusedIndex]?.name === node.name;
            const color = statusToOrbColor(node.status);
            const glowId = statusToGlowFilter(node.status).replace("#", `#${idPrefix}-`);
            const isRunning = node.status === "running";

            return (
              <g
                key={node.name}
                transform={`translate(${l.x}, ${l.y})`}
                className="cursor-pointer"
                onClick={() => onNodeSelect?.(node)}
                role="button"
                tabIndex={0}
                aria-label={`Node ${node.name}, status ${node.status}`}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onNodeSelect?.(node);
                }}
              >
                {/* Selection ring */}
                {(isSelected || isFocused) && (
                  <circle r={22} fill="none" stroke="var(--aurora-500)" strokeWidth={2} strokeDasharray={isFocused && !isSelected ? "4 2" : undefined} />
                )}

                {/* Orb */}
                <circle
                  r={14}
                  fill={color}
                  filter={glowId}
                  className={cn(
                    isRunning && !reducedMotion && "animate-pulse-glow"
                  )}
                  style={{
                    opacity: node.status === "pending" ? 0.5 : 1,
                  }}
                />

                {/* Label */}
                <text
                  y={28}
                  textAnchor="middle"
                  fill="var(--comet-100)"
                  fontSize={11}
                  fontFamily="var(--font-mono)"
                  style={{ pointerEvents: "none" }}
                >
                  {node.name}
                </text>

                {/* Status label */}
                <text
                  y={40}
                  textAnchor="middle"
                  fill="var(--comet-500)"
                  fontSize={9}
                  fontFamily="var(--font-mono)"
                  style={{ pointerEvents: "none" }}
                >
                  {node.status}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
