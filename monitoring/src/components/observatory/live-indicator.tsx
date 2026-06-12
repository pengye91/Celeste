import Radio from "lucide-react/dist/esm/icons/radio";
import { cn } from "@/lib/utils";

/**
 * Visual state of the live event stream.
 *
 *  - connected   : SSE is open and receiving frames
 *  - reconnecting: SSE errored and is retrying with backoff
 *  - fallback    : SSE never connected or was abandoned; we are polling
 *  - idle        : the consumer is disabled; render nothing
 */
export type LiveIndicatorState =
  | "connected"
  | "reconnecting"
  | "fallback"
  | "idle";

interface LiveIndicatorProps {
  state: LiveIndicatorState;
  className?: string;
}

/**
 * Compact status pill for the observatory header.
 *
 * - role="status" + aria-live="polite" so screen readers announce
 *   reconnects / fallbacks without us spamming event content.
 * - data-state is exposed for CSS hooks and tests.
 * - data-testid="live-indicator" for test selectors.
 * - Pulse animations use Tailwind's `motion-safe:` prefix so users
 *   with prefers-reduced-motion never see a flashing dot.
 */
export function LiveIndicator({ state, className }: LiveIndicatorProps) {
  if (state === "idle") return null;

  const config = STATE_CONFIG[state];
  return (
    <div
      role="status"
      aria-live="polite"
      data-state={state}
      data-testid="live-indicator"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5",
        "font-mono text-[10px] uppercase tracking-wider",
        config.wrapper,
        className
      )}
    >
      <span className="relative flex items-center" aria-hidden="true">
        <span
          className={cn(
            "absolute inline-flex h-2 w-2 rounded-full opacity-60 motion-safe:animate-ping",
            config.ping
          )}
        />
        <span
          className={cn(
            "relative inline-flex h-2 w-2 rounded-full motion-safe:animate-pulse",
            config.dot
          )}
        />
      </span>
      <Radio className={cn("w-3 h-3", config.icon)} aria-hidden="true" />
      <span>{config.label}</span>
    </div>
  );
}

const STATE_CONFIG: Record<
  Exclude<LiveIndicatorState, "idle">,
  {
    label: string;
    wrapper: string;
    dot: string;
    ping: string;
    icon: string;
  }
> = {
  connected: {
    label: "Live",
    wrapper: "border-aurora-500/30 bg-aurora-500/10 text-aurora-400",
    dot: "bg-aurora-500",
    ping: "bg-aurora-500",
    icon: "text-aurora-400",
  },
  reconnecting: {
    label: "Reconnecting…",
    wrapper: "border-solar-500/30 bg-solar-500/10 text-solar-400",
    dot: "bg-solar-500",
    ping: "bg-solar-500",
    icon: "text-solar-400",
  },
  fallback: {
    label: "Polling fallback",
    wrapper: "border-space-500 bg-space-700/40 text-comet-400",
    // Fallback has no pulse/ping — it is the resting, non-live state.
    dot: "bg-comet-500",
    ping: "bg-comet-500",
    icon: "text-comet-500",
  },
};
