"use client";

import { useMemo } from "react";
import Cpu from "lucide-react/dist/esm/icons/cpu";
import Sparkles from "lucide-react/dist/esm/icons/sparkles";
import type { GlobalEvent } from "@/lib/types";
import { Panel } from "@/components/ui/panel";
import { cn } from "@/lib/utils";

interface ProviderMixProps {
  events: GlobalEvent[] | null | undefined;
}

/**
 * *Tertiary* pillar of the observatory per spec §6.13: if Celeste's
 * events include a `provider` or `model` key in their event_data, we
 * count occurrences and render a small bar chart. Otherwise we show
 * the "Provider telemetry not yet emitted" empty state — explicitly,
 * not silently — so the absence is visible to the operator.
 */
export function ProviderMix({ events }: ProviderMixProps) {
  const counts = useMemo(() => countProviders(events), [events]);

  if (counts.length === 0) {
    return (
      <Panel
        aria-label="Provider mix unavailable"
        className="text-center py-6"
        data-testid="provider-mix-empty"
      >
        <Sparkles
          className="w-5 h-5 mx-auto mb-2 text-comet-500 opacity-60"
          aria-hidden="true"
        />
        <p className="text-comet-400 text-sm font-medium">
          Provider telemetry not yet emitted
        </p>
        <p className="text-comet-600 text-xs mt-1 max-w-xs mx-auto">
          When events carry a <code className="font-mono">provider</code> or{" "}
          <code className="font-mono">model</code> field, this panel will
          roll up the fleet&apos;s mix.
        </p>
      </Panel>
    );
  }

  const max = Math.max(...counts.map((c) => c.count), 1);
  return (
    <Panel aria-label="Provider mix" className="space-y-3" data-testid="provider-mix">
      <header className="flex items-center gap-2">
        <Cpu className="w-4 h-4 text-nebula-400" aria-hidden="true" />
        <h2 className="text-sm font-body font-medium text-comet-100">
          Provider Mix
        </h2>
        <span className="text-xs text-comet-500 font-mono ml-auto">
          {counts.length} {counts.length === 1 ? "provider" : "providers"}
        </span>
      </header>
      <ul className="space-y-2">
        {counts.map((c) => (
          <li key={c.name} className="flex items-center gap-3 text-xs">
            <span className="w-24 truncate text-comet-300" title={c.name}>
              {c.name}
            </span>
            <div
              className="flex-1 h-2 rounded-sm bg-space-700 overflow-hidden"
              role="presentation"
            >
              <div
                className={cn(
                  "h-full rounded-sm",
                  c.name.toLowerCase().includes("claude") ||
                    c.name.toLowerCase().includes("anthropic")
                    ? "bg-aurora-500"
                    : c.name.toLowerCase().includes("gpt") ||
                      c.name.toLowerCase().includes("openai")
                    ? "bg-nebula-500"
                    : c.name.toLowerCase().includes("gemini")
                    ? "bg-solar-500"
                    : "bg-comet-400"
                )}
                style={{ width: `${(c.count / max) * 100}%` }}
              />
            </div>
            <span className="w-10 text-right font-mono text-comet-400">
              {c.count}
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function countProviders(
  events: GlobalEvent[] | null | undefined
): { name: string; count: number }[] {
  if (!events) return [];
  const map = new Map<string, number>();
  for (const e of events) {
    const data = e.event_data;
    if (!data) continue;
    const candidate =
      (typeof data.provider === "string" && data.provider) ||
      (typeof data.model === "string" && data.model) ||
      (typeof data.model_id === "string" && data.model_id) ||
      null;
    if (candidate) {
      map.set(candidate, (map.get(candidate) ?? 0) + 1);
    }
  }
  return Array.from(map.entries())
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count);
}
