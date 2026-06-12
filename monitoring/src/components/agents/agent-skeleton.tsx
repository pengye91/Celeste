import { Panel } from "@/components/ui/panel";

/**
 * Loading placeholder for a single agent card. Renders a pulsing panel
 * that mirrors the eventual card layout (orb + url line + tags) so the
 * transition into the loaded state feels like a fill-in, not a swap.
 *
 * The `motion-safe:` prefix lets prefers-reduced-motion users see static
 * placeholders instead of a pulsing animation.
 */
export function AgentSkeleton() {
  return (
    <Panel
      data-testid="agent-skeleton"
      aria-hidden="true"
      className="p-4 space-y-3 motion-safe:animate-pulse"
    >
      <div className="flex items-center gap-3">
        <div className="w-3 h-3 rounded-full bg-space-600" />
        <div className="h-4 w-32 rounded bg-space-600" />
      </div>
      <div className="h-3 w-3/4 rounded bg-space-700" />
      <div className="h-3 w-1/2 rounded bg-space-700" />
      <div className="flex gap-2 pt-1">
        <div className="h-4 w-12 rounded-sm bg-space-700" />
        <div className="h-4 w-16 rounded-sm bg-space-700" />
      </div>
    </Panel>
  );
}
