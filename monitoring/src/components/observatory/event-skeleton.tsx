/**
 * Skeleton placeholder for the event ticker. Renders a column of
 * pulsing rows that mirror the eventual event card layout, so the
 * transition from loading to live content is visually continuous.
 */
export function EventSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div
      data-testid="event-skeleton"
      className="space-y-2"
      aria-hidden="true"
    >
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-3 rounded-md border border-space-600 bg-space-800/60 px-3 py-2"
        >
          <div className="h-2 w-2 rounded-full bg-space-500 animate-pulse" />
          <div className="h-3 w-28 rounded-sm bg-space-600 animate-pulse" />
          <div className="h-3 w-40 flex-1 rounded-sm bg-space-600 animate-pulse" />
          <div className="h-3 w-12 rounded-sm bg-space-600 animate-pulse" />
        </div>
      ))}
    </div>
  );
}
