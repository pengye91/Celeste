import { useEffect, useState } from "react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import type { NameType, ValueType } from "recharts/types/component/DefaultTooltipContent";
import { Panel } from "@/components/ui/panel";

export interface ConcurrencyPoint {
  timestamp: string;
  concurrency: number;
}

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });

  useEffect(() => {
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handler = (e: MediaQueryListEvent) => setReduced(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  return reduced;
}

export function WorkspaceChart({
  data,
  peakConcurrency,
}: {
  data: ConcurrencyPoint[];
  peakConcurrency?: number | null;
}) {
  const reducedMotion = useReducedMotion();

  if (data.length === 0) {
    return (
      <Panel variant="subtle" padding="lg" className="w-full">
        <div className="flex flex-col items-start gap-2">
          <h3 className="font-sans text-lg font-semibold text-text-primary">
            No workspace concurrency data
          </h3>
          <p className="text-sm text-text-secondary">
            Workspaces will appear here once the workflow begins spawning
            them. Start a workflow to generate workspace data.
          </p>
        </div>
      </Panel>
    );
  }

  return (
    <figure className="w-full" aria-label="Workspace concurrency over time">
      <figcaption className="mb-2 font-sans text-sm font-semibold text-text-secondary">
        Running workspaces over time
      </figcaption>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="workspaceGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--aurora-500)" stopOpacity={0.4} />
                <stop offset="100%" stopColor="var(--aurora-500)" stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="var(--space-500)"
              opacity={0.3}
            />
            <XAxis
              dataKey="timestamp"
              tick={{ fill: "var(--text-tertiary)", fontSize: 12 }}
              axisLine={{ stroke: "var(--space-500)" }}
              tickLine={{ stroke: "var(--space-500)" }}
              tickFormatter={(value: string) => {
                const d = new Date(value);
                return d.toLocaleTimeString("en-US", {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                  hour12: false,
                });
              }}
              label={{
                value: "Time",
                position: "insideBottom",
                offset: -2,
                fill: "var(--text-tertiary)",
                fontSize: 12,
              }}
            />
            <YAxis
              tick={{ fill: "var(--text-tertiary)", fontSize: 12 }}
              axisLine={{ stroke: "var(--space-500)" }}
              tickLine={{ stroke: "var(--space-500)" }}
              allowDecimals={false}
              label={{
                value: "Workspaces",
                angle: -90,
                position: "insideLeft",
                fill: "var(--text-tertiary)",
                fontSize: 12,
              }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--space-800)",
                border: "1px solid var(--space-500)",
                borderRadius: "var(--radius-md)",
                color: "var(--text-primary)",
                fontSize: 13,
              }}
              itemStyle={{ color: "var(--aurora-400)" }}
              labelStyle={{ color: "var(--text-secondary)" }}
              labelFormatter={(label: unknown) => {
                const labelStr = typeof label === 'string' ? label : String(label ?? '');
                const d = new Date(labelStr);
                return d.toLocaleString("en-US", {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                  hour12: false,
                });
              }}
              formatter={(value: ValueType | undefined) => {
                const num = typeof value === "number" ? value : Number(value ?? 0);
                return [num.toLocaleString(), "Running workspaces" satisfies NameType];
              }}
            />
            <Area
              type="stepAfter"
              dataKey="concurrency"
              stroke="var(--aurora-500)"
              strokeWidth={2}
              fill="url(#workspaceGradient)"
              isAnimationActive={!reducedMotion}
              animationDuration={800}
            />
            {peakConcurrency != null && (
              <ReferenceLine
                y={peakConcurrency}
                stroke="var(--mars-500)"
                strokeDasharray="6 4"
                strokeWidth={2}
                label={{
                  value: `Peak: ${peakConcurrency}`,
                  position: "insideTopRight",
                  fill: "var(--mars-400)",
                  fontSize: 12,
                }}
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
