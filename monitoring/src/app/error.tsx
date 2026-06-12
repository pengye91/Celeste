"use client";

import Link from "next/link";
import { Shell } from "@/components/shell/shell";
import { Panel } from "@/components/ui/panel";
import { StatusOrb } from "@/components/ui/status-orb";
import { Button } from "@/components/ui/button";

/**
 * Top-level error boundary.
 *
 * Next.js 16 calls this when an unhandled error throws in a route
 * segment or its nested children. The component is a Client Component
 * (required by the React error-boundary contract) and is given an
 * `unstable_retry` callback that re-renders the failed segment. We
 * also surface a "Back to dashboard" link so the user can leave the
 * broken surface even when retry does not help.
 *
 * Per the spec, the visual treatment uses the design-system status
 * orb in its `error` variant (mars-500) plus the centred Panel pattern
 * established by the rest of the empty/error states.
 */
export default function GlobalError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return (
    <Shell>
      <div className="flex items-center justify-center min-h-[60vh]">
        <Panel variant="elevated" padding="lg" className="max-w-md w-full">
          <div className="flex flex-col items-center text-center">
            <div className="mb-5 flex items-center gap-3">
              <StatusOrb
                variant="error"
                size="lg"
                pulse
                label="Something went wrong"
              />
              <span className="font-mono text-xs uppercase tracking-widest text-mars-400">
                Error
              </span>
            </div>
            <h1 className="text-2xl font-display text-comet-100 mb-2">
              The signal dropped
            </h1>
            <p className="text-sm text-comet-500 mb-6 max-w-sm">
              Something broke while rendering this view. You can try
              again, or head back to the dashboard.
            </p>
            {error.digest ? (
              <p className="text-xs font-mono text-comet-500/70 mb-4">
                ref: {error.digest}
              </p>
            ) : null}
            <div className="flex items-center gap-2">
              <Button variant="primary" onClick={() => unstable_retry()}>
                Try again
              </Button>
              <Button variant="default" asChild>
                <Link href="/">Back to dashboard</Link>
              </Button>
            </div>
          </div>
        </Panel>
      </div>
    </Shell>
  );
}
