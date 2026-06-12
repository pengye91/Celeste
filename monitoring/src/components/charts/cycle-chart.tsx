import { useEffect, useMemo, useState } from "react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  BarChart,
  Bar,
  Line,
  ReferenceLine,
} from "recharts";
import type { NameType, ValueType } from "recharts/types/component/DefaultTooltipContent";
import { Panel } from "@/components/ui/panel";

export interface CycleData {
  cycleNumber: number;
  tokenCount?: number | null;
  durationMs?: number;
  nodeCount?: number;
  timestamp: string;
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

export function CycleChart({
  data,
  hasTokenData,
  budget,
}: {
  data: CycleData[];
  hasTokenData?: boolean;
  budget?: number | null;
}) {
  const reducedMotion = useReducedMotion();

  const hasTokens = useMemo(
    () =>
      hasTokenData === true &&
      data.some((d) => d.tokenCount != null && d.tokenCount !== undefined),
    [hasTokenData, data]
  );

  const chartData = useMemo(
    () =>
      data.map((d) => ({
        cycle: d.cycleNumber,
        tokens: d.tokenCount ?? 0,
        duration: d.durationMs ?? 0,
        nodes: d.nodeCount ?? 0,
      })),
    [data]
  );

  if (data.length === 0) {
    return (
      <Panel variant="subtle" padding="lg" className="w-full">
        <div className="flex flex-col items-start gap-2">
          <h3 className="font-sans text-lg font-semibold text-text-primary">
            No OPA cycles recorded
          </h3>
          <p className="text-sm text-text-secondary">
            Cycles will appear here once the OPA loop begins executing nodes.
            Start a workflow to generate cycle data.
          </p>
        </div>
      </Panel>
    );
  }

  if (hasTokens) {
    return (
      <figure className="w-full" aria-label="Accumulated tokens per OPA cycle">
        <figcaption className="mb-2 font-sans text-sm font-semibold text-text-secondary">
          Tokens per cycle
        </figcaption>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="tokenGradient" x1="0" y1="0" x2="0" y2="1">
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
                dataKey="cycle"
                tick={{ fill: "var(--text-tertiary)", fontSize: 12 }}
                axisLine={{ stroke: "var(--space-500)" }}
                tickLine={{ stroke: "var(--space-500)" }}
                label={{
                  value: "Cycle",
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
                label={{
                  value: "Tokens",
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
                formatter={(value: ValueType | undefined) => {
                  const num = typeof value === 'number' ? value : Number(value ?? 0);
                  return [num.toLocaleString(), "Tokens" satisfies NameType];
                }}
              />
              <Area
                type="monotone"
                dataKey="tokens"
                stroke="var(--aurora-500)"
                strokeWidth={2}
                fill="url(#tokenGradient)"
                isAnimationActive={!reducedMotion}
                animationDuration={800}
              />
              {budget != null && (
                <ReferenceLine
                  y={budget}
                  stroke="var(--mars-500)"
                  strokeDasharray="6 4"
                  strokeWidth={2}
                  label={{
                    value: `Budget: ${budget.toLocaleString()}`,
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

  return (
    <figure className="w-full" aria-label="Cycle duration and node count per OPA cycle">
      <figcaption className="mb-2 font-sans text-sm font-semibold text-text-secondary">
        Cycle metrics
      </figcaption>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="var(--space-500)"
              opacity={0.3}
            />
            <XAxis
              dataKey="cycle"
              tick={{ fill: "var(--text-tertiary)", fontSize: 12 }}
              axisLine={{ stroke: "var(--space-500)" }}
              tickLine={{ stroke: "var(--space-500)" }}
              label={{
                value: "Cycle",
                position: "insideBottom",
                offset: -2,
                fill: "var(--text-tertiary)",
                fontSize: 12,
              }}
            />
            <YAxis
              yAxisId="left"
              tick={{ fill: "var(--text-tertiary)", fontSize: 12 }}
              axisLine={{ stroke: "var(--space-500)" }}
              tickLine={{ stroke: "var(--space-500)" }}
              label={{
                value: "Duration (ms)",
                angle: -90,
                position: "insideLeft",
                fill: "var(--text-tertiary)",
                fontSize: 12,
              }}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fill: "var(--text-tertiary)", fontSize: 12 }}
              axisLine={{ stroke: "var(--space-500)" }}
              tickLine={{ stroke: "var(--space-500)" }}
              label={{
                value: "Nodes",
                angle: 90,
                position: "insideRight",
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
              labelStyle={{ color: "var(--text-secondary)" }}
            />
            <Bar
              yAxisId="left"
              dataKey="duration"
              fill="var(--nebula-500)"
              radius={[2, 2, 0, 0]}
              isAnimationActive={!reducedMotion}
              animationDuration={800}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="nodes"
              stroke="var(--solar-500)"
              strokeWidth={2}
              dot={{ r: 3, fill: "var(--solar-500)" }}
              isAnimationActive={!reducedMotion}
              animationDuration={800}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
